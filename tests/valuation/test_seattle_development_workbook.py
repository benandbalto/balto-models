import importlib.util, tempfile, unittest
from decimal import Decimal as D
from balto_development.seattle import write_workbook
from balto_development.seattle_example import example_deal, example_inputs
from balto_model_engine.parity import Tolerance, check_parity


@unittest.skipUnless(all(importlib.util.find_spec(n) for n in ('openpyxl', 'pycel')), 'Workbook parity dependencies required')
class SeattleDevelopmentWorkbookTest(unittest.TestCase):
    def test_workbook_recalculates_and_flexes_program_toggles(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + '/seattle.xlsx'
            model, run, compiled = write_workbook(example_deal(), example_inputs(), path)
            tolerance = Tolerance(absolute=D('.000001'), relative=D('1e-9'))
            result = check_parity(path, compiled, model, run, tolerance=tolerance)
            self.assertTrue(result.ok, result.mismatches[:5])
            flex = {'mfte_elected': {(): 0}, 'mha_performance': {(): 1}, 'mha_performance_rate': {(): '0.10'},
                    'levy_rate': {(): '0.0095'}, 'sale_month': {(): 72}}
            result = check_parity(path, compiled, model, run, tolerance=tolerance, flex=flex, inputs=example_inputs())
            self.assertTrue(result.ok, result.mismatches[:5])
            self.assertGreater(result.compared, 1000)
