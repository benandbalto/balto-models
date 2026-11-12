"""Bounded, data-only entry point: one JSON request in, one response out, no stored state."""
from dataclasses import fields
from decimal import Decimal
from datetime import date, timedelta
import base64
import json
try:
    import resource
except ImportError:  # Windows: no rlimits, so the limits below do not apply there.
    resource = None
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from balto_model_engine import EngineError, ModelDefinitionError, evaluate
from balto_model_engine.workbook import CompileError
from balto_model_engine.commercial import CommercialSpace
from .deal import Deal, UnitType, Cohort, OpexLine, Tranche, ClosingCost, CapexPhase, CapexLine
from .model import build_model
from .workbook import write_workbook

GROUPS = {'unit_types': UnitType, 'cohorts': Cohort, 'opex_lines': OpexLine,
          'tranches': Tranche, 'closing_costs': ClosingCost,
          'capex_phases': CapexPhase, 'capex_lines': CapexLine, 'commercial_spaces': CommercialSpace}
# Structure fields added in later versions; a snapshot without one takes this default.
OPTIONAL_FIELDS = {'commercial_spaces': [], 'senior_loan': 'sized', 'tax_exemption_ends': False}
# The horizon includes the buyer's forward year after the sale, so 11 years allows a
# 10-year hold. Longer horizons push the live workbook's exit-year formulas past
# Excel's 8,192-character limit (at 14 years).
MAX_HORIZON_YEARS = 11


def read_deal(value):
    if not isinstance(value, dict):
        raise ValueError('Deal structure must explicitly include every field.')
    structure = OPTIONAL_FIELDS | value
    if set(structure) != {f.name for f in fields(Deal)}:
        raise ValueError('Deal structure must explicitly include every field.')
    structure['closing'] = date.fromisoformat(structure['closing'])
    for name, cls in GROUPS.items():
        rows = structure[name]
        if not isinstance(rows, list) or len(rows) > 50:
            raise ValueError('Invalid structure size.')
        structure[name] = tuple(cls(**row) for row in rows)
        if len({r.key for r in structure[name]}) != len(rows):
            raise ValueError('Structure keys must be unique.')
    if (not 2 <= structure['horizon_years'] <= MAX_HORIZON_YEARS or len(structure['cohorts']) > 20
            or len(structure['commercial_spaces']) > 20):
        raise ValueError('horizon_years must be 2 to 11, with at most 20 cohorts and 20 commercial spaces.')
    return Deal(**structure)


def serialize(run, model):
    result = {'modelId': run.model_id, 'modelVersion': run.model_version,
            'engineVersion': run.engine_version, 'decimalPolicy': run.decimal_policy,
            'digest': run.digest, 'dimensions': run.dims, 'lineage': run.lineage,
            'values': {name: [{'index': list(index), 'value': format(value, 'f')}
                              for index, value in rows.items()] for name, rows in run.values.items()},
            'metrics': run.metrics, 'tests': run.tests}

    if run.model_id == 'value-add-acquisition':
        rows=[]
        for item in model.dimensions['month'].items:
            index=(item.key,)
            value=lambda key:run.values[key][index]
            owned=value('owned')
            rows.append(dict(date=(date(1899,12,30)+timedelta(days=int(item.attrs['date']))).isoformat(),
                cashFlow=value('levered_cash_flow'),lpCashFlow=value('lp_cash_flow'),gpCashFlow=value('gp_cash_flow'),
                eligibleIncome=value('cash_from_operations'),debtService=value('senior_debt_service'),
                operatingIncome=value('egi') if owned else Decimal(0),operatingExpense=value('opex_total') if owned else Decimal(0),noi=value('noi') if owned else Decimal(0),
                managementFee=value('asset_management_fee'),unitMonths=run.values['total_units'][()] if owned else Decimal(0)))
        result.update(projectionVersion='1',projection=rows,units=run.values['total_units'][()])
    return result


def limit_resources():
    """Cap CPU time and memory. Required on Linux, where Balto sandboxes the service;
    best effort elsewhere (macOS rejects the memory cap, Windows has neither)."""
    if resource is None:
        return
    for limit, value in ((resource.RLIMIT_CPU, 45), (resource.RLIMIT_AS, 768 * 1024 * 1024)):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            if sys.platform.startswith('linux'):
                raise


def main():
    limit_resources()
    try:
        payload = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError('Request too large.')
        request = json.loads(payload)
        if request.get('contractVersion') != '1' or request.get('operation') not in ('run', 'validate', 'describe'):
            raise ValueError('Invalid request.')
        snapshot = request['snapshot']
        if set(snapshot) != {'deal', 'inputs'} or not isinstance(snapshot['inputs'], dict):
            raise ValueError('Invalid snapshot.')
        if snapshot['deal'].get('kind') == 'development':
            from balto_development.deal import read_deal as read_structure
            from balto_development.model import build_model as assemble
            from balto_development.workbook import write_workbook as render
        elif snapshot['deal'].get('kind') == 'seattle_development':
            from balto_development.deal import read_deal as read_development
            from balto_development.seattle import build_model as assemble, write_workbook as render
            read_structure = lambda value: read_development(value, 'seattle_development')
        else:
            read_structure, assemble, render = read_deal, build_model, write_workbook
        deal = read_structure(snapshot['deal'])
        model = assemble(deal)
        if request['operation'] == 'describe':
            result = {'model': model.describe()}
        elif request['operation'] == 'validate':
            result = {'run': serialize(evaluate(model, snapshot['inputs']), model)}
        else:
            with TemporaryDirectory(prefix='balto-valuation-') as directory:
                path = Path(directory) / 'valuation.xlsx'
                _, run, compiled = render(deal, snapshot['inputs'], str(path))
                context = request.get('context', {})
                sheet = compiled.workbook.create_sheet('Input Basis')
                sheet.append(['Draft valuation assumptions and source references'])
                sheet.append([context.get('note', '')])
                sheet.append(['Input', 'Basis', 'Reason', 'Exact source', 'References / quotes', 'Pinned provenance'])
                for key, basis in sorted(context.get('basis', {}).items()):
                    sheet.append([key, basis['kind'], basis['reason'], basis.get('versionId', basis.get('runId', '')),
                                  json.dumps(basis.get('references', []), ensure_ascii=False),
                                  json.dumps(context.get('provenance', {}).get(key, {}), ensure_ascii=False)])
                for row in sheet:
                    for cell in row:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
                sheet.freeze_panes = 'A4'
                for column in ('A', 'B', 'C', 'D', 'E', 'F'):
                    sheet.column_dimensions[column].width = 35 if column != 'C' else 65
                compiled.save(str(path))
                workbook = path.read_bytes()
                if len(workbook) > 10 * 1024 * 1024:
                    raise ValueError('Workbook too large.')
                result = {'run': serialize(run, model), 'workbookBase64': base64.b64encode(workbook).decode('ascii')}
        response = {'contractVersion': '1', 'status': 'succeeded', 'result': result}
    except EngineError as error:
        response = {'contractVersion': '1', 'status': 'invalid',
                    'finding': {'code': error.code, 'message': str(error), 'key': error.key}}
    except CompileError as error:
        # The run evaluated but its workbook cannot be laid out; the message names variables, not values.
        response = {'contractVersion': '1', 'status': 'invalid',
                    'finding': {'code': 'WORKBOOK_LAYOUT', 'message': str(error)}}
    except (ValueError, TypeError, KeyError, ModelDefinitionError):
        response = {'contractVersion': '1', 'status': 'invalid',
                    'finding': {'code': 'VALIDATION_ERROR', 'message': 'Invalid valuation model data.'}}
    except Exception:
        response = {'contractVersion': '1', 'status': 'failed',
                    'finding': {'code': 'CALCULATION_FAILED', 'message': 'Valuation calculation failed.'}}
    sys.stdout.write(json.dumps(response, default=lambda value: format(value, 'f') if isinstance(value, Decimal) else str(value), separators=(',', ':')))


if __name__ == '__main__':
    main()
