from decimal import Decimal
"""The application's data-only acquisition calculation contract."""
import json
import subprocess
import sys
import unittest
from dataclasses import asdict
from io import BytesIO
import base64
from openpyxl import load_workbook
from balto_valuation.example import example_deal, example_inputs
from balto_valuation.model import build_model
from balto_model_engine import evaluate


def snapshot():
    deal = asdict(example_deal())
    deal['closing'] = deal['closing'].isoformat()
    return {'deal': deal, 'inputs': example_inputs()}


def invoke(request):
    process = subprocess.run([sys.executable, '-m', 'balto_valuation.service'],
                             input=json.dumps({'contractVersion': '1', **request}),
                             text=True, capture_output=True, check=True)
    return json.loads(process.stdout)


class ServiceTest(unittest.TestCase):
    def test_data_only_snapshot_returns_the_exact_run_and_live_workbook(self):
        response = invoke({'operation': 'run', 'snapshot': snapshot(), 'context': {'note': 'Draft synthetic model', 'basis': {'purchase_price': {'kind': 'assumption', 'reason': '=not_a_formula'}}}})
        self.assertEqual(response['status'], 'succeeded')
        result = response['result']
        expected = evaluate(build_model(example_deal()), example_inputs())
        self.assertEqual(result['run']['digest'], expected.digest)
        self.assertEqual(result['run']['modelId'], 'value-add-acquisition')
        self.assertEqual(result['run']['metrics']['levered_irr']['rate'], str(expected.metrics['levered_irr']['rate']))
        book = load_workbook(BytesIO(base64.b64decode(result['workbookBase64'])))
        self.assertEqual(book.sheetnames[0], 'Deal Overview')
        self.assertEqual(book['Input Basis']['A2'].value, 'Draft synthetic model')
        self.assertEqual(book['Input Basis']['C4'].value, '=not_a_formula')
        self.assertEqual(book['Input Basis']['C4'].data_type, 's')
        self.assertTrue(any(cell.data_type == 'f' for row in book['Deal Overview'] for cell in row))

    def test_ten_year_hold_runs_with_the_buyers_forward_year(self):
        # The horizon carries the buyer's forward year after the sale, so a 10-year hold needs 11 years.
        value = snapshot()
        value['deal']['horizon_years'] = 11
        value['inputs']['sale_month'] = 120
        response = invoke({'operation': 'run', 'snapshot': value})
        self.assertEqual(response['status'], 'succeeded')
        self.assertIn('workbookBase64', response['result'])
        value['deal']['horizon_years'] = 12
        self.assertEqual(invoke({'operation': 'validate', 'snapshot': value})['status'], 'invalid')

    def test_missing_or_unknown_inputs_are_refused_without_echoing_submitted_values(self):
        value = snapshot()
        del value['inputs']['purchase_price']
        response = invoke({'operation': 'validate', 'snapshot': value})
        self.assertEqual(response['status'], 'invalid')
        value = snapshot()
        value['inputs']['execute_code'] = 'private-source-must-not-appear'
        response = invoke({'operation': 'validate', 'snapshot': value})
        self.assertEqual(response['status'], 'invalid')
        self.assertNotIn('private-source-must-not-appear', json.dumps(response))

    def test_description_supplies_the_required_input_contract_for_the_deal(self):
        response = invoke({'operation': 'describe', 'snapshot': {'deal': snapshot()['deal'], 'inputs': {}}})
        self.assertEqual(response['status'], 'succeeded')
        self.assertEqual(response['result']['model']['modelId'], 'value-add-acquisition')

    def test_saved_acquisition_projection_contains_actual_calendar_dates_and_owned_cash(self):
        response=invoke({'operation':'validate','snapshot':snapshot()})
        run=response['result']['run']
        self.assertEqual(run['projectionVersion'],'1')
        self.assertEqual(run['projection'][0]['date'],'2026-12-31')
        self.assertEqual(run['projection'][1]['date'],'2027-01-31')
        self.assertEqual(Decimal(run['projection'][-1]['operatingIncome']),0)
        self.assertEqual(Decimal(run['projection'][-1]['debtService']),0)

    def test_a_deal_with_only_unit_cost_capex_lines_runs_its_workbook(self):
        value = snapshot()
        value['deal']['capex_phases'] = [{'key': 'initial', 'label': 'Initial', 'funding': 'closing'}]
        value['deal']['capex_lines'] = [{'key': 'deferred_maint', 'label': 'Deferred maintenance',
                                         'phase': 'initial', 'method': 'unit_cost'}]
        value['inputs'].update(capex_amount={}, capex_unit_cost={'deferred_maint': 1500},
                               capex_count={'deferred_maint': 64}, capex_start_month={'initial': 1},
                               capex_months={'initial': 6}, capex_gc_rate={'initial': 0},
                               capex_gc_fee_rate={'initial': 0}, capex_contingency_rate={'initial': '0.1'})
        response = invoke({'operation': 'run', 'snapshot': value})
        self.assertEqual(response['status'], 'succeeded', response.get('finding'))
        self.assertIn('workbookBase64', response['result'])

    def test_a_workbook_layout_failure_is_reported_as_an_invalid_finding(self):
        from contextlib import redirect_stdout
        from io import StringIO, TextIOWrapper
        from unittest import mock
        from balto_model_engine.workbook import CompileError
        from balto_valuation import service
        stdin = TextIOWrapper(BytesIO(json.dumps({'contractVersion': '1', 'operation': 'run',
                                                  'snapshot': snapshot()}).encode()))
        out = StringIO()
        with mock.patch.object(service, 'write_workbook', side_effect=CompileError('The layout does not place x.')), \
                mock.patch.object(service.resource, 'setrlimit'), mock.patch.object(sys, 'stdin', stdin), \
                redirect_stdout(out):
            service.main()
        response = json.loads(out.getvalue())
        self.assertEqual(response['status'], 'invalid')
        self.assertEqual(response['finding'], {'code': 'WORKBOOK_LAYOUT', 'message': 'The layout does not place x.'})
