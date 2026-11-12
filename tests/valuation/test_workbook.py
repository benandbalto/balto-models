"""The analyst workbook recalculates, independently, to the run."""

from dataclasses import replace
from decimal import Decimal
import importlib.util
import os
import tempfile
import unittest

from balto_valuation.branding import SPONSOR
from balto_valuation.example import example_deal, example_inputs

HAS_COMPILER_DEPS = all(importlib.util.find_spec(m) is not None for m in ("openpyxl", "pycel"))
# Compounding over the hold drifts in the last binary digits.
TOLERANCE = dict(absolute=Decimal("0.000001"), relative=Decimal("1e-9"))


@unittest.skipUnless(HAS_COMPILER_DEPS, "openpyxl and pycel are needed to compile and recalculate")
class WorkbookTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from balto_valuation.workbook import write_workbook
        cls.dir = tempfile.TemporaryDirectory()
        # A shorter horizon keeps the recalculation quick; the formulas are the same.
        cls.deal = replace(example_deal(), horizon_years=6)
        cls.inputs = {**example_inputs(), "sale_month": 48, "refi_month": 24}
        cls.path = os.path.join(cls.dir.name, "deal.xlsx")
        cls.model, cls.result, cls.compiled = write_workbook(cls.deal, cls.inputs, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def check(self, **kwargs):
        from balto_model_engine.parity import Tolerance, check_parity
        return check_parity(self.path, self.compiled, self.model, self.result, tolerance=Tolerance(**TOLERANCE),
                            **kwargs)

    def test_the_workbook_recalculates_to_the_run(self):
        report = self.check()
        self.assertTrue(report.ok, report.mismatches[:5])
        self.assertGreater(report.compared, 15000)

    def test_flexing_the_deal_in_the_workbook_matches_a_fresh_run(self):
        flex = {"sale_month": {(): 60}, "refi_included": {(): 0}, "purchase_price": {(): 9200000},
                "turnover": {(): "0.5"}, "exit_cap_rate": {(): "0.055"}, "market_rent": {("2br",): 1800},
                "reno_pace": {("1br_mkt",): 3}, "promote_2": {(): "0.35"}}
        report = self.check(flex=flex, inputs=self.inputs)
        self.assertTrue(report.ok, report.mismatches[:5])

    def test_returns_are_live_xirr_formulas(self):
        from openpyxl import load_workbook
        ws = load_workbook(self.path)["Returns Detail"]
        formulas = [ws[a.split("!")[1]].value for a in self.compiled.metrics.values()]
        self.assertEqual(len(formulas), 4)
        self.assertTrue(all(f.startswith("=XIRR(") for f in formulas))

    def test_the_overview_is_a_branded_cover_of_live_formulas(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.path)
        self.assertEqual(wb.sheetnames[0], "Deal Overview")
        ws = wb["Deal Overview"]
        self.assertEqual(ws["B2"].value, SPONSOR.upper())
        self.assertEqual(wb["Dimensions"].sheet_state, "hidden")
        overview = [a for a in self.compiled.derived if a.startswith("'Deal Overview'!")]
        self.assertGreater(len(overview), 200)
        for address in overview:
            self.assertTrue(ws[address.split("!")[1]].value.startswith("="), address)
        # The parity checks above recalculate each of these against the run.

    def test_the_pro_forma_has_live_per_unit_columns(self):
        from openpyxl import load_workbook
        ws = load_workbook(self.path)["Pro Forma"]
        self.assertEqual(ws["H1"].value, "In-place (annualized) $/unit")
        noi = self.compiled.cells["pf.noi"][("year_1",)].rsplit("!", 1)[1]
        per_unit = ws.cell(ws[noi].row, 9).value
        self.assertTrue(per_unit.startswith(f"={noi}/"), per_unit)

    def test_a_failed_check_shows_on_the_overview(self):
        from openpyxl import load_workbook
        ws = load_workbook(self.path, data_only=True)["Deal Overview"]
        labels = {ws.cell(r, 2).value: ws.cell(r, 3).value for r in range(1, ws.max_row + 1)}
        self.assertEqual(labels["Sources equal uses"], "OK")
        # The synthetic 2 BR 60% units are above their net limit at closing.
        self.assertEqual(labels["In-place restricted rents at or below the net limit"], "Review")


@unittest.skipUnless(HAS_COMPILER_DEPS, "openpyxl and pycel are needed to compile and recalculate")
class EdgeDealTest(unittest.TestCase):
    """Deal shapes the example does not have still compile, with an overview that recalculates."""

    def build(self, deal, inputs):
        from balto_model_engine.parity import Tolerance, check_parity
        from balto_valuation.workbook import write_workbook
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deal.xlsx")
            model, result, compiled = write_workbook(deal, inputs, path)
            report = check_parity(path, compiled, model, result, tolerance=Tolerance(**TOLERANCE))
        self.assertTrue(report.ok, report.mismatches[:5])

    def test_a_deal_without_renovation_or_tranches(self):
        from balto_valuation import Cohort
        deal = replace(example_deal(), horizon_years=4, tranches=(),
                       cohorts=tuple(Cohort(c.key, c.label, c.unit_type, c.regime) for c in example_deal().cohorts))
        inputs = {k: v for k, v in example_inputs().items() if not k.startswith(("city_loan.", "seller_note."))}
        inputs.update(sale_month=24, refi_month=18, reno_scope={}, reno_pace={})
        self.build(deal, inputs)

    def test_a_fully_vacant_acquisition(self):
        deal = replace(example_deal(), horizon_years=4)
        inputs = {**example_inputs(), "sale_month": 24, "refi_month": 18,
                  "occupied_at_close": {k: 0 for k in example_inputs()["occupied_at_close"]}}
        self.build(deal, inputs)

    def capex_only(self, method):
        lines = tuple(x for x in example_deal().capex_lines if x.method == method)
        phases = tuple(p for p in example_deal().capex_phases if any(x.phase == p.key for x in lines))
        deal = replace(example_deal(), horizon_years=4, capex_phases=phases, capex_lines=lines)
        inputs = {**example_inputs(), "sale_month": 24, "refi_month": 18}
        for name in ("capex_amount", "capex_unit_cost", "capex_count"):
            inputs[name] = {k: v for k, v in inputs[name].items() if k in {x.key for x in lines}}
        for name in ("capex_start_month", "capex_months", "capex_gc_rate", "capex_gc_fee_rate",
                     "capex_contingency_rate"):
            inputs[name] = {k: v for k, v in inputs[name].items() if k in {p.key for p in phases}}
        self.build(deal, inputs)

    def test_a_capital_budget_with_only_unit_cost_lines(self):
        self.capex_only("unit_cost")

    def test_a_capital_budget_with_only_lump_lines(self):
        self.capex_only("lump")


if __name__ == "__main__":
    unittest.main()
