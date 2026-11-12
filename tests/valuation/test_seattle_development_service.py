import base64, json, subprocess, sys, unittest
from dataclasses import asdict
from io import BytesIO
from openpyxl import load_workbook
from balto_development.seattle_example import example_deal, scenario_inputs


class SeattleDevelopmentServiceTest(unittest.TestCase):
    def invoke(self, operation, inputs, kind='seattle_development'):
        deal = asdict(example_deal()); deal['closing'] = deal['closing'].isoformat(); deal['kind'] = kind
        request = {'contractVersion': '1', 'operation': operation, 'snapshot': {'deal': deal, 'inputs': inputs},
                   'context': {'note': 'Synthetic Seattle development only', 'basis': {}}}
        p = subprocess.run([sys.executable, '-m', 'balto_valuation.service'], input=json.dumps(request), text=True, capture_output=True, check=True)
        return json.loads(p.stdout)

    def test_saved_workflow_runs_the_seattle_model_with_a_program_sheet(self):
        response = self.invoke('run', scenario_inputs(mfte=True, mha='payment'))
        self.assertEqual(response['status'], 'succeeded', response)
        run = response['result']['run']
        self.assertEqual((run['modelId'], run['modelVersion']), ('seattle-multifamily-development', '0.1.0'))
        self.assertTrue(all(t['passed'] for t in run['tests'].values()), run['tests'])
        book = load_workbook(BytesIO(base64.b64decode(response['result']['workbookBase64'])))
        self.assertIn('Seattle Programs', book.sheetnames)
        self.assertIn('Investor Waterfall', book.sheetnames)

    def test_describe_lists_program_toggles_and_a_development_kind_is_not_seattle(self):
        described = self.invoke('describe', {})
        names = {v['name'] for v in described['result']['model']['variables'] if v['kind'] == 'input'}
        self.assertTrue({'mfte_elected', 'mha_applies', 'mha_performance', 'levy_rate'} <= names)
        self.assertEqual(self.invoke('validate', scenario_inputs(mfte=True, mha='payment'), kind='development')['status'], 'invalid')
