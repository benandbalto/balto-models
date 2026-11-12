"""Engine 0.4.0: lags across variables, power, min/max, period attributes, tests, and XIRR."""

from datetime import date
from decimal import Decimal
import unittest

from balto_model_engine import (
    DecimalPolicy, Dimension, allocate_round, EngineError, Item, Model, ModelDefinitionError, attr, evaluate, excel_serial, if_,
    lag, max_, min_, monthly_calendar, power, previous, ref, sum_over, xirr,
)


def model() -> Model:
    m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_EVEN"))
    m.dimension(Dimension("month", [Item(i, index=i) for i in range(0, 7)]))
    return m


def sweep_loan(m: Model) -> None:
    """A loan whose interest reads its opening balance and whose sweep repays it from cash."""
    m.input("amount", unit="usd")
    m.input("rate", unit="ratio")
    m.input("share", unit="ratio")
    m.input("cash", unit="usd", dims=("month",))
    m.calc("opening", unit="usd", dims=("month",), expr=lag("closing", "month", initial=0))
    m.calc("funded", unit="usd", dims=("month",), expr=if_(attr("month", "index") == 0, ref("amount"), 0))
    m.calc("interest", unit="usd", dims=("month",), expr=ref("opening") * ref("rate") / 12)
    m.calc("sweep", unit="usd", dims=("month",),
           expr=min_(max_(ref("cash") - ref("interest"), 0) * ref("share"), ref("opening")))
    m.calc("closing", unit="usd", dims=("month",), expr=ref("opening") + ref("funded") - ref("sweep"))
    m.calc("total_swept", unit="usd", expr=sum_over("month", ref("sweep")))


INPUTS = {"amount": 1000, "rate": "0.12", "share": "0.5", "cash": {0: 0, **{i: 300 for i in range(1, 7)}}}


class LagTest(unittest.TestCase):

    def test_variables_that_lag_one_another_are_evaluated_month_by_month(self):
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        balance = Decimal(1000)
        for month in range(1, 7):
            interest = balance * Decimal("0.01")
            swept = min((300 - interest) * Decimal("0.5"), balance)
            self.assertEqual(run.value("interest", month=month), interest)
            balance -= swept
            self.assertEqual(run.value("closing", month=month), balance)
        self.assertEqual(run.value("total_swept"), Decimal(1000) - balance)
        self.assertEqual(run.lineage["opening"]["lags"], ["closing"])

    def test_a_same_month_cycle_is_still_a_definition_error(self):
        m = model()
        m.calc("a", unit="usd", dims=("month",), expr=ref("b") + 1)
        m.calc("b", unit="usd", dims=("month",), expr=ref("a") + 1)
        with self.assertRaisesRegex(ModelDefinitionError, "Undeclared cycle"):
            evaluate(m, {})

    def test_a_block_member_may_not_allocate_over_the_block_dimension(self):
        # Members are evaluated a month at a time, so an allocation over months
        # would read months not yet evaluated.
        m = model()
        m.calc("a", unit="usd", dims=("month",), expr=lag("b", "month", initial=0) + 1)
        m.calc("b", unit="usd", dims=("month",), expr=allocate_round(ref("a") / 3, "month", 2))
        with self.assertRaisesRegex(ModelDefinitionError, "recurrence block"):
            evaluate(m, {})

    def test_a_block_lags_along_one_dimension(self):
        m = model()
        m.dimension(Dimension("tranche", [Item("a"), Item("b")]))
        m.calc("x", unit="usd", dims=("month", "tranche"), expr=lag("y", "month", initial=0) + 1)
        m.calc("y", unit="usd", dims=("month", "tranche"), expr=lag("x", "tranche", initial=0) + ref("x"))
        with self.assertRaisesRegex(ModelDefinitionError, "more than one dimension"):
            evaluate(m, {})

    def test_a_block_may_carry_other_dimensions(self):
        m = model()
        m.dimension(Dimension("tranche", [Item("a"), Item("b")]))
        m.input("draw", unit="usd", dims=("tranche",))
        m.calc("opening", unit="usd", dims=("tranche", "month"), expr=lag("closing", "month", initial=0))
        m.calc("closing", unit="usd", dims=("tranche", "month"), expr=ref("opening") + ref("draw"))
        run = evaluate(m, {"draw": {"a": 1, "b": 2}})
        self.assertEqual(run.value("closing", tranche="b", month=6), Decimal(14))

    def test_a_lag_of_an_input_needs_no_block(self):
        m = model()
        m.input("rent", unit="usd", dims=("month",))
        m.calc("change", unit="usd", dims=("month",), expr=ref("rent") - lag("rent", "month", initial=ref("rent")))
        run = evaluate(m, {"rent": {i: 100 + i for i in range(7)}})
        self.assertEqual(run.series("change"), [Decimal(0)] + [Decimal(1)] * 6)

    def test_a_check_runs_after_its_block(self):
        m = model()
        sweep_loan(m)
        m.check("non_negative", condition=ref("closing") >= 0, code="NEGATIVE_BALANCE",
                message="A balance went negative.", dims=("month",))
        self.assertEqual(evaluate(m, INPUTS).value("closing", month=0), Decimal(1000))


class NodeTest(unittest.TestCase):

    def test_power_compounds_an_annual_rate_monthly(self):
        m = model()
        m.input("growth", unit="ratio")
        m.calc("monthly", unit="ratio", expr=power(1 + ref("growth"), Decimal(1) / 12) - 1)
        monthly = evaluate(m, {"growth": "0.03"}).value("monthly")
        self.assertAlmostEqual(float((1 + monthly) ** 12), 1.03, places=15)

    def test_a_fractional_power_of_a_negative_number_is_undefined(self):
        m = model()
        m.input("x", unit="ratio")
        m.calc("root", unit="ratio", expr=power(ref("x"), "0.5"))
        with self.assertRaises(EngineError) as caught:
            evaluate(m, {"x": -4})
        self.assertEqual(caught.exception.code, "CALCULATION_UNDEFINED")

    def test_min_and_max_take_two_or_more_expressions(self):
        m = model()
        m.input("a", unit="usd")
        m.calc("clamped", unit="usd", expr=max_(min_(ref("a"), 10, 20), 0))
        self.assertEqual(evaluate(m, {"a": 15}).value("clamped"), Decimal(10))
        self.assertEqual(evaluate(m, {"a": -5}).value("clamped"), Decimal(0))
        with self.assertRaises(TypeError):
            min_(ref("a"))

    def test_an_event_month_is_compared_with_the_period_index(self):
        m = model()
        m.input("sale_month", unit="month")
        m.calc("sold", unit="flag", dims=("month",), expr=if_(attr("month", "index") >= ref("sale_month"), 1, 0))
        self.assertEqual(evaluate(m, {"sale_month": 4}).series("sold"), [Decimal(x) for x in (0, 0, 0, 0, 1, 1, 1)])

    def test_an_attribute_read_as_a_value_must_be_numeric_on_every_item(self):
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_EVEN"))
        m.dimension(Dimension("month", [Item(1, index=1), Item(2, index="2")]))
        m.calc("i", unit="month", dims=("month",), expr=attr("month", "index"))
        with self.assertRaisesRegex(ModelDefinitionError, "numeric index"):
            evaluate(m, {})


class CalendarTest(unittest.TestCase):

    def test_a_month_end_closing_starts_full_months(self):
        cal = monthly_calendar(date(2026, 12, 31), 13)
        first, jan, feb = cal.items[0], cal.item(1), cal.item(2)
        self.assertEqual((first.attrs["days"], first.attrs["hold_year"]), (0, 0))
        self.assertEqual((jan.attrs["days"], jan.attrs["calendar_year"], jan.attrs["hold_year"]), (31, 2027, 1))
        self.assertEqual(feb.attrs["days"], 28)
        self.assertEqual(cal.item(13).attrs["hold_year"], 2)
        self.assertEqual(jan.attrs["date"], excel_serial(date(2027, 1, 31)))

    def test_a_mid_month_closing_has_a_stub_first_month(self):
        cal = monthly_calendar(date(2027, 3, 15), 2)
        self.assertEqual([i.attrs["days"] for i in cal.items], [0, 16, 30])

    def test_excel_serial_matches_excel(self):
        self.assertEqual(excel_serial(date(2026, 1, 1)), 46023)


class TestResultTest(unittest.TestCase):

    def test_a_breached_test_is_reported_and_the_run_finishes(self):
        m = model()
        m.input("noi", unit="usd", dims=("month",))
        m.input("debt_service", unit="usd")
        m.calc("dscr", unit="ratio", dims=("month",), expr=ref("noi") / ref("debt_service"))
        m.test("dscr_minimum", condition=ref("dscr") >= "1.25", code="DSCR_BELOW_MINIMUM",
               message="DSCR is below the covenant minimum.", dims=("month",))
        run = evaluate(m, {"noi": {0: 130, 1: 120, 2: 100, 3: 125, 4: 130, 5: 110, 6: 140}, "debt_service": 100})
        result = run.tests["dscr_minimum"]
        self.assertFalse(result["passed"])
        self.assertEqual((result["items"], result["breaches"]), (7, 3))
        self.assertEqual(result["firstBreach"], [1])
        self.assertEqual(result["worstBreach"], {"item": [2], "shortfall": Decimal("0.25")})

    def test_a_passing_test_reports_no_breach(self):
        m = model()
        m.input("x", unit="usd")
        m.test("positive", condition=ref("x") > 0, code="NOT_POSITIVE", message="x is not positive.")
        self.assertEqual(evaluate(m, {"x": 1}).tests["positive"],
                         {"code": "NOT_POSITIVE", "message": "x is not positive.", "passed": True,
                          "items": 1, "breaches": 0})

    def test_test_results_are_part_of_the_digest(self):
        m = model()
        m.input("x", unit="usd")
        m.test("positive", condition=ref("x") > 0, code="NOT_POSITIVE", message="x is not positive.")
        self.assertNotEqual(evaluate(m, {"x": 1}).digest, evaluate(m, {"x": -1}).digest)


class XirrTest(unittest.TestCase):

    def test_one_year_at_ten_percent(self):
        result = xirr([Decimal(-1000), Decimal(1100)], [Decimal(0), Decimal(365)], Decimal("1e-12"))
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(float(result["rate"]), 0.10, places=11)

    def test_flows_of_one_sign_have_no_irr(self):
        self.assertEqual(xirr([Decimal(1), Decimal(2)], [Decimal(0), Decimal(30)], Decimal("1e-10")),
                         {"status": "no_sign_change"})

    def test_two_roots_are_reported_not_chosen(self):
        # -100, +230, -132 a year apart has roots at 10% and 20%.
        result = xirr([Decimal(-100), Decimal(230), Decimal(-132)], [Decimal(0), Decimal(365), Decimal(730)],
                      Decimal("1e-10"))
        self.assertEqual(result, {"status": "multiple_roots"})

    def test_a_declared_metric_is_computed_from_the_run(self):
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_EVEN"))
        m.dimension(monthly_calendar(date(2026, 12, 31), 12))
        m.input("flow", unit="usd", dims=("month",))
        m.calc("lp_flow", unit="usd", dims=("month",), expr=ref("flow"))
        m.xirr("lp_irr", flows="lp_flow", dim="month", date_attr="date")
        flows = {i: 0 for i in range(13)}
        flows[0], flows[12] = -1000, 1080
        metric = evaluate(m, {"flow": flows}).metrics["lp_irr"]
        self.assertEqual(metric["status"], "ok")
        self.assertAlmostEqual(float(metric["rate"]), 0.08, places=9)
        self.assertEqual(metric["flows"], "lp_flow")

    def test_a_metric_needs_a_series_over_its_dimension(self):
        m = model()
        m.input("flow", unit="usd")
        m.xirr("irr", flows="flow", dim="month", date_attr="index")
        with self.assertRaisesRegex(ModelDefinitionError, "flows must be"):
            evaluate(m, {"flow": 1})


class PreviousStillWorksTest(unittest.TestCase):

    def test_previous_and_lag_agree_on_a_self_recurrence(self):
        m = model()
        m.calc("a", unit="usd", dims=("month",), expr=previous("a", "month", initial=1, step=lambda p: p * 2))
        m.calc("b", unit="usd", dims=("month",), expr=lag("b", "month", initial=Decimal("0.5")) * 2)
        run = evaluate(m, {})
        self.assertEqual(run.series("a"), run.series("b"))


if __name__ == "__main__":
    unittest.main()
