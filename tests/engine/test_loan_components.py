"""Shared calendar and loan components, each checked against an independent calculation."""
from decimal import Decimal
import unittest

from balto_model_engine import Dimension, Item, Model, DecimalPolicy, annual_calendar, attr, const, evaluate, if_, ref
from balto_model_engine.debt import build_debt_schedule, build_loan_sizing, build_payment_terms, build_period_amortization

POLICY = DecimalPolicy(precision=34, rounding="ROUND_HALF_UP")
D = Decimal


def model(*dims):
    m = Model("components", "0.0.1", POLICY)
    for dim in dims:
        m.dimension(dim)
    return m


class AnnualCalendarTest(unittest.TestCase):
    def test_years_carry_index_calendar_year_and_a_year_end_date(self):
        years = annual_calendar(2025, 3)
        self.assertEqual([i.attrs["calendar_year"] for i in years.items], [2025, 2026, 2027])
        self.assertEqual(years.items[0].attrs["date"], 46022)  # 2025-12-31 as an Excel serial.
        with self.assertRaises(ValueError):
            annual_calendar(2025, 0)


class LoanSizingTest(unittest.TestCase):
    def sized(self, **options):
        m = model()
        for name in ("noi", "rate"):
            m.input(name, unit="x")
        terms = build_payment_terms(m, prefix="loan", annual_rate=ref("rate"), amort_years=const(35))
        build_loan_sizing(m, prefix="loan", income=ref("noi"), value=None, max_ltv=None, min_dscr=const("1.15"),
                          payment_constant=terms.payment_constant, **options)
        return m, evaluate(m, {"noi": "600000", "rate": "0.065"})

    def test_fee_prior_payments_rounding_and_cap_follow_the_lender_convention(self):
        _, run = self.sized(fee_rate=const("0.001"), prior_payments=const("52500.40"), increment=const(1000))
        r = D("0.065") / 12
        constant = r / (1 - (1 + r) ** -420)
        exact = (D(600000) / D("1.15") - D("52500.40")) / (12 * constant + D("0.001"))
        self.assertEqual(run.value("loan.amount"), (exact // 1000) * 1000)
        self.assertEqual(run.value("loan.amount"), 6384000)
        _, run = self.sized(fee_rate=const("0.001"), increment=const(1000), maximum=const(5000000))
        self.assertEqual(run.value("loan.amount"), 5000000)

    def test_without_options_the_formula_is_unchanged(self):
        m, run = self.sized()
        names = [v["name"] for v in m.describe()["variables"]]
        self.assertNotIn("loan.annual_constant", names)
        self.assertNotIn("loan.ltv_amount", names)
        self.assertEqual(run.value("loan.amount"), run.value("loan.dscr_amount"))

    def test_an_ltv_constraint_needs_both_value_and_ratio(self):
        m = model()
        m.input("noi", unit="x")
        terms = build_payment_terms(m, prefix="loan", annual_rate=const(0), amort_years=const(30))
        with self.assertRaises(ValueError):
            build_loan_sizing(m, prefix="loan", income=ref("noi"), value=ref("noi"), max_ltv=None, min_dscr=const(1),
                              payment_constant=terms.payment_constant)


class PeriodAmortizationTest(unittest.TestCase):
    def test_annual_totals_equal_the_monthly_schedule(self):
        months = Dimension("month", [Item(i, index=i) for i in range(0, 41)])
        years = annual_calendar(2025, 4)
        m = model(months, years)
        terms = build_payment_terms(m, prefix="terms", annual_rate=const("0.065"), amort_years=const(35))
        # Monthly: funded in month 0, first payment month 1. Annual: 5 months in year 1, then 12.
        build_debt_schedule(m, prefix="monthly", period_dim="month", period_index=attr("month", "index"),
                            amount=const(1000000), terms=terms, fund_period=const(0), payoff_period=const(99), io_periods=const(0))
        build_period_amortization(m, prefix="annual", period_dim="year", amount=const(1000000), terms=terms,
                                  months=if_(attr("year", "index") == 1, 5, 12), fee=const(1250))
        run = evaluate(m, {})
        ends = {1: 5, 2: 17, 3: 29, 4: 41 - 1}
        start = 1
        for year, end in ends.items():
            interest = sum(run.value("monthly.interest", month=i) for i in range(start, end + 1))
            months_in = end - start + 1
            if months_in == 12 or year == 1:
                self.assertAlmostEqual(run.value("annual.interest", year=year), interest, places=6)
                self.assertAlmostEqual(run.value("annual.closing", year=year), run.value("monthly.balance", month=end), places=6)
            start = end + 1
        self.assertAlmostEqual(run.value("annual.debt_service", year=2), run.value("annual.payments", year=2) + 1250, places=10)


if __name__ == "__main__":
    unittest.main()
