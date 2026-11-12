import tempfile
import importlib.util
import unittest
from balto_development.example import example_deal,example_inputs
from balto_development.workbook import write_workbook
from balto_model_engine.parity import Tolerance,check_parity
from decimal import Decimal as D
@unittest.skipUnless(all(importlib.util.find_spec(n) for n in ('openpyxl','pycel')), 'Workbook parity dependencies required')
class DevelopmentWorkbookTest(unittest.TestCase):
    def test_workbook_recalculates_and_flexes_development_dates_costs_and_interest(self):
        with tempfile.TemporaryDirectory() as d:
            path=d+'/development.xlsx'
            model,run,compiled=write_workbook(example_deal(),example_inputs(),path)
            self.assertIn('Investor Waterfall',compiled.workbook.sheetnames)
            tolerance=Tolerance(absolute=D('.000001'),relative=D('1e-9'))
            result=check_parity(path,compiled,model,run,tolerance=tolerance)
            self.assertTrue(result.ok,result.mismatches[:5])
            flex={'lp_share':{():'0.8'},'pref_rate':{():'0.1'},'catch_up_share':{():'0.5'},'promote_1':{():'0.15'},'promote_2':{():'0.25'},'hurdle_rate':{():'0.14'},'hard_cost':{('building',):'10000000'},'completion_month':{():18},'occupancy_month':{():18},'stabilization_month':{():26},'conversion_month':{():30},'equity_commitment':{():'4000000'},'construction_rate':{('m1',):'.12'},'spending_month':{(f'd{i}',):i+6 for i in range(1,13)}}
            result=check_parity(path,compiled,model,run,tolerance=tolerance,flex=flex,inputs=example_inputs())
            self.assertTrue(result.ok,result.mismatches[:5])
            self.assertGreater(result.compared,1000)
