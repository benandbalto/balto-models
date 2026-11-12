"""Commercial space in the value-add acquisition: own leases into EGI, NOI, sizing, exit and the workbook."""

from dataclasses import replace
from decimal import Decimal
import importlib.util
import os
import tempfile
import unittest

from balto_model_engine import evaluate
from balto_valuation.example import example_deal, example_inputs, example_mixed_use
from balto_valuation.model import build_model
from balto_valuation.service import read_deal

HAS_COMPILER_DEPS = all(importlib.util.find_spec(m) is not None for m in ("openpyxl", "pycel"))
TOLERANCE = dict(absolute=Decimal("0.000001"), relative=Decimal("1e-9"))


class Close(unittest.TestCase):
    def assertEqual(self, first, second, msg=None):
        """Model figures carry 34 digits; the expected side is worked to Python's 28."""
        if isinstance(first, Decimal) or isinstance(second, Decimal):
            return self.assertAlmostEqual(Decimal(first), Decimal(second), places=12, msg=msg)
        return super().assertEqual(first, second, msg)


def run(deal, inputs):
    return evaluate(build_model(deal), inputs)


class CommercialModelTest(Close):
    @classmethod
    def setUpClass(cls):
        cls.deal, cls.inputs = example_mixed_use()
        cls.base = run(example_deal(), example_inputs())
        cls.mixed = run(cls.deal, cls.inputs)

    def v(self, result, name, *idx):
        return result.values[name][idx]

    def test_commercial_income_adds_to_egi_without_scaling_with_apartment_occupancy(self):
        for month in (1, 12, 40):
            self.assertEqual(self.v(self.mixed, "egi", month) - self.v(self.base, "egi", month),
                             self.v(self.mixed, "commercial.income", month))
        vacant = run(self.deal, {**self.inputs, "occupied_at_close": {k: 0 for k in self.inputs["occupied_at_close"]}})
        self.assertEqual(self.v(vacant, "commercial.income", 1), self.v(self.mixed, "commercial.income", 1))
        self.assertEqual(self.v(self.mixed, "other_income_total", 1), self.v(self.base, "other_income_total", 1))

    def test_nnn_recoveries_follow_property_tax_and_recoverable_lines(self):
        month = 3
        recoverable = self.v(self.mixed, "property_tax", month) + self.v(self.mixed, "opex", "insurance", month)
        self.assertEqual(self.v(self.mixed, "recoverable_costs", month), recoverable)
        self.assertEqual(self.v(self.mixed, "commercial.recoveries", "cafe", month), recoverable * Decimal("0.25"))
        self.assertEqual(self.v(self.mixed, "commercial.recoveries", "office", month), 0)

    def test_leasing_costs_are_paid_below_noi(self):
        rollover = 18
        leasing = self.v(self.mixed, "commercial.leasing_costs_total", rollover)
        self.assertEqual(leasing, Decimal("0.6") * 1800 * 35)
        self.assertEqual(self.v(self.mixed, "cash_from_operations", rollover),
                         self.v(self.mixed, "ncf", rollover) - leasing)
        self.assertEqual(self.v(self.mixed, "noi", rollover),
                         self.v(self.mixed, "egi", rollover) - self.v(self.mixed, "opex_total", rollover))

    def test_commercial_income_sizes_the_senior_loan(self):
        self.assertGreater(self.v(self.mixed, "senior.sizing_ncf"), self.v(self.base, "senior.sizing_ncf"))
        self.assertGreaterEqual(self.v(self.mixed, "senior.amount"), self.v(self.base, "senior.amount"))

    def test_a_separate_commercial_exit_cap_values_the_commercial_rent(self):
        fwd, com = self.v(self.mixed, "sale.forward_ncf"), self.v(self.mixed, "sale.forward_commercial")
        self.assertEqual(self.v(self.mixed, "sale.price"),
                         (fwd - com) / Decimal("0.0525") + com / Decimal("0.0725"))
        blended = run(self.deal, {**self.inputs, "commercial_exit_cap_rate": 0})
        self.assertEqual(self.v(blended, "sale.price"), fwd / Decimal("0.0525"))

    def test_pro_forma_cases_carry_commercial_income(self):
        pf = lambda case: self.v(self.mixed, "pf.commercial_income", case)
        self.assertEqual(pf("year_1"), sum(self.v(self.mixed, "annual.commercial.income", k) for k in (1,)))
        # The office's below-market lease ends before the sale, so stabilized marks it to market.
        stabilized_rent = self.v(self.mixed, "pf.commercial_rent", "stabilized")
        self.assertEqual(stabilized_rent, 72000 + 22 * 1800)
        self.assertEqual(self.v(self.mixed, "pf.commercial_rent", "in_place"), 72000 + 21600)
        for case in ("in_place", "year_1", "stabilized", "exit_year"):
            self.assertGreater(pf(case), 0)

    def test_a_deal_without_commercial_space_is_unchanged(self):
        self.assertNotIn("commercial.income", self.base.values)
        self.assertNotIn("commercial_exit_cap_rate", build_model(example_deal()).variables)

    def test_saved_structures_without_commercial_spaces_still_read(self):
        structure = {"name": "Synthetic", "closing": "2026-12-31", "horizon_years": 5, "location": "WA",
                     "downtime_months": 2, "tax_method": "wa_market",
                     "unit_types": [{"key": "studio", "label": "Studio", "bedrooms": 0}],
                     "cohorts": [{"key": "market", "label": "Market", "unit_type": "studio", "regime": "market",
                                  "renovate": False}],
                     "opex_lines": [{"key": "insurance", "label": "Insurance", "method": "per_unit"}],
                     "tranches": [], "closing_costs": [], "capex_phases": [], "capex_lines": []}
        self.assertEqual(read_deal(structure).commercial_spaces, ())
        spaced = read_deal({**structure, "commercial_spaces": [
            {"key": "retail", "label": "Retail", "sf": 2000, "lease_type": "nnn"}],
            "opex_lines": [{"key": "insurance", "label": "Insurance", "method": "per_unit", "recoverable": True}]})
        self.assertEqual(spaced.commercial_spaces[0].lease_type, "nnn")
        self.assertTrue(spaced.opex_lines[0].recoverable)
        with self.assertRaises(ValueError):
            read_deal({**structure, "commercial_spaces": [{"key": "r", "label": "R", "sf": 10, "lease_type": "net"}]})

    def test_a_share_of_income_line_is_not_recoverable(self):
        from balto_valuation import OpexLine
        with self.assertRaises(ValueError):
            replace(example_deal(), opex_lines=(OpexLine("management", "Management", "pct_egi", True),))


@unittest.skipUnless(HAS_COMPILER_DEPS, "openpyxl and pycel are needed to compile and recalculate")
class CommercialWorkbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from balto_valuation.workbook import write_workbook
        cls.dir = tempfile.TemporaryDirectory()
        deal, inputs = example_mixed_use()
        cls.deal = replace(deal, horizon_years=5)
        cls.inputs = {**inputs, "sale_month": 36, "refi_month": 24}
        cls.path = os.path.join(cls.dir.name, "mixed.xlsx")
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

    def test_flexing_a_lease_in_the_workbook_matches_a_fresh_run(self):
        flex = {"commercial.option_exercised": {("cafe",): 0}, "commercial.market_rent": {("office",): 25},
                "commercial_exit_cap_rate": {(): "0.07"}, "commercial.credit_loss_rate": {(): "0.1"}}
        report = self.check(flex=flex, inputs=self.inputs)
        self.assertTrue(report.ok, report.mismatches[:5])

    def test_commercial_sheets_and_overview(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.path)
        self.assertIn("Commercial Leases", wb.sheetnames)
        self.assertIn("Commercial Projection", wb.sheetnames)
        labels = [c.value for c in wb["Deal Overview"]["B"] if isinstance(c.value, str)]
        self.assertIn("COMMERCIAL SPACE", labels)
        self.assertIn("Mixed-Use", wb["Deal Overview"]["B3"].value)
        self.assertIn("Commercial income (rent, recoveries, less credit loss)", labels)
        self.assertIn("pf.commercial_income", self.compiled.cells)


if __name__ == "__main__":
    unittest.main()
