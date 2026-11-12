"""An assumed senior loan and a property-tax exemption that ends during the hold (acquisition 0.5.0)."""

from dataclasses import replace
from decimal import Decimal
import importlib.util
import os
import tempfile
import unittest

from balto_model_engine import evaluate
from balto_valuation.example import example_deal, example_inputs
from balto_valuation.model import build_model
from balto_valuation.service import read_deal

HAS_COMPILER_DEPS = all(importlib.util.find_spec(m) is not None for m in ("openpyxl", "pycel"))
TOLERANCE = dict(absolute=Decimal("0.000001"), relative=Decimal("1e-9"))


def assumed_example():
    """The example deal taking over a $7.5M loan at 4.92% with 26 years left, maturing in month 60,
    held to a sale in month 72 without a refinance."""
    deal = replace(example_deal(), senior_loan="assumed", tax_exemption_ends=True)
    inputs = {**example_inputs(), "senior.assumed_balance": 7500000, "senior.maturity_month": 60,
              "senior.rate": "0.0492", "senior.amort_years": 26, "senior.io_months": 0,
              "tax_exemption": "0.8", "tax_exemption_end_month": 25, "refi_included": 0, "sale_month": 72}
    return deal, inputs


class AssumedLoanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deal, cls.inputs = assumed_example()
        cls.result = evaluate(build_model(cls.deal), cls.inputs)

    def v(self, name, *idx):
        return self.result.values[name][idx]

    def test_the_loan_is_the_assumed_balance_whatever_it_would_size_to(self):
        self.assertEqual(self.v("senior.amount"), Decimal(7500000))
        self.assertNotEqual(self.v("senior.dscr_amount"), self.v("senior.amount"))
        self.assertEqual(self.v("senior.ltv_amount"), Decimal("0.65") * 9600000)

    def test_the_loan_pays_its_own_rate_and_remaining_amortization(self):
        self.assertAlmostEqual(self.v("senior.interest", 1), Decimal(7500000) * Decimal("0.0492") / 12, places=6)
        r = Decimal("0.0492") / 12
        payment = Decimal(7500000) * r / (1 - (1 + r) ** -312)
        self.assertAlmostEqual(self.v("senior.payment"), payment, places=4)

    def test_a_sale_past_maturity_fails_the_maturity_test(self):
        self.assertFalse(self.result.tests["senior_maturity"]["passed"])
        early = evaluate(build_model(self.deal), {**self.inputs, "sale_month": 60})
        self.assertTrue(early.tests["senior_maturity"]["passed"])

    def test_the_exemption_ends_at_its_month(self):
        tax = self.result.values["property_tax"]
        base = evaluate(build_model(self.deal), {**self.inputs, "tax_exemption": 0}).values["property_tax"]
        self.assertAlmostEqual(tax[(24,)], base[(24,)] * Decimal("0.2"), places=6)
        self.assertEqual(tax[(25,)], base[(25,)])

    def test_a_sized_deal_is_unchanged(self):
        self.assertNotIn("senior.assumed_balance", build_model(example_deal()).variables)
        self.assertNotIn("tax_exemption_end_month", build_model(example_deal()).variables)

    def test_saved_structures_read_with_the_defaults(self):
        structure = {"name": "Synthetic", "closing": "2026-12-31", "horizon_years": 5, "location": "WA",
                     "downtime_months": 2, "tax_method": "wa_market",
                     "unit_types": [{"key": "studio", "label": "Studio", "bedrooms": 0}],
                     "cohorts": [{"key": "market", "label": "Market", "unit_type": "studio", "regime": "market",
                                  "renovate": False}],
                     "opex_lines": [], "tranches": [], "closing_costs": [], "capex_phases": [], "capex_lines": []}
        deal = read_deal(structure)
        self.assertEqual((deal.senior_loan, deal.tax_exemption_ends), ("sized", False))
        assumed = read_deal({**structure, "senior_loan": "assumed", "tax_exemption_ends": True})
        self.assertEqual((assumed.senior_loan, assumed.tax_exemption_ends), ("assumed", True))
        with self.assertRaises(ValueError):
            read_deal({**structure, "senior_loan": "bridge"})


@unittest.skipUnless(HAS_COMPILER_DEPS, "openpyxl and pycel are needed to compile and recalculate")
class AssumedLoanWorkbookTest(unittest.TestCase):
    def test_the_workbook_recalculates_to_the_run(self):
        from balto_model_engine.parity import Tolerance, check_parity
        from balto_valuation.workbook import write_workbook
        deal, inputs = assumed_example()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "assumed.xlsx")
            model, result, compiled = write_workbook(replace(deal, horizon_years=5), {**inputs, "sale_month": 36, "senior.maturity_month": 36}, path)
            report = check_parity(path, compiled, model, result, tolerance=Tolerance(**TOLERANCE))
            self.assertTrue(report.ok, report.mismatches[:5])


if __name__ == "__main__":
    unittest.main()
