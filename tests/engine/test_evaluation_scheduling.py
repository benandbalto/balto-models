"""Public evaluation contracts that index scheduling must preserve."""

from decimal import Decimal
import unittest

from balto_model_engine import (
    DecimalPolicy, Dimension, EngineError, Item, Model, attr, evaluate, if_, lag,
    ref, sum_over, sum_within,
)


class EvaluationSchedulingTest(unittest.TestCase):
    def test_recurrence_keeps_declared_order_with_different_dimension_positions(self):
        m = Model("scheduling-fixture", "1", DecimalPolicy(34, "ROUND_HALF_EVEN"))
        m.dimension(Dimension("period", [Item("later"), Item("first"), Item("last")]))
        m.dimension(Dimension("cohort", [Item("b"), Item("a")]))
        m.input("step", unit="usd", dims=("cohort",))
        m.calc("opening", unit="usd", dims=("cohort", "period"),
               expr=lag("closing", "period", initial=0))
        m.calc("closing", unit="usd", dims=("period", "cohort"),
               expr=ref("opening") + ref("step"))
        run = evaluate(m, {"step": {"b": 2, "a": 3}})
        self.assertEqual(list(run.values["opening"]),
                         [(c, p) for p in ("later", "first", "last") for c in ("b", "a")])
        self.assertEqual(list(run.values["closing"]),
                         [(p, c) for p in ("later", "first", "last") for c in ("b", "a")])
        self.assertEqual(list(run.values["closing"].values()),
                         [Decimal(x) for x in (2, 3, 4, 6, 6, 9)])

    def test_filtered_recurrence_and_empty_selection_keep_lazy_branches(self):
        m = Model("filtered-schedule", "1", DecimalPolicy(34, "ROUND_HALF_EVEN"))
        m.dimension(Dimension("period", [Item(9, enabled=True, index=0),
                                        Item(4, enabled=True, index=1),
                                        Item(1, enabled=False, index=2)]))
        m.calc("opening", unit="usd", dims=("period",), where={"enabled": True},
               expr=lag("closing", "period", initial=0))
        m.calc("closing", unit="usd", dims=("period",), where={"enabled": True},
               expr=ref("opening") + 2)
        m.calc("unused", unit="usd", dims=("period",), where={"enabled": "absent"},
               expr=ref("opening") / 0)
        m.calc("safe", unit="usd", dims=("period",),
               expr=if_(attr("period", "index") < 2, ref("closing"), 0))
        run = evaluate(m, {})
        self.assertEqual(run.series("closing"), [Decimal(2), Decimal(4)])
        self.assertEqual(run.values["unused"], {})
        self.assertEqual(run.series("safe"), [Decimal(2), Decimal(4), Decimal(0)])

    def test_filtered_selection_supports_structured_attributes_and_changes_between_runs(self):
        m = Model("selection-fixture", "1", DecimalPolicy(34, "ROUND_HALF_EVEN"))
        m.dimension(Dimension("building", [Item("b"), Item("a")]))
        m.dimension(Dimension("unit", [Item("u2", building="b", tags=["leased"]),
                                      Item("u1", building="a", tags=["vacant"])], parent="building"))
        m.input("rent", unit="usd", dims=("unit",), where={"tags": ["leased"]})
        m.calc("income", unit="usd", dims=("building",),
               expr=sum_within("unit", ref("rent"), tags=["leased"]))
        m.calc("total", unit="usd", expr=sum_over("building", ref("income")))
        first = evaluate(m, {"rent": {"u2": 7}})
        self.assertEqual(first.series("income"), [Decimal(7), Decimal(0)])
        m.dimensions["unit"].item("u1").attrs["tags"] = ["leased"]
        second = evaluate(m, {"rent": {"u2": 8, "u1": 3}})
        self.assertEqual(second.series("income"), [Decimal(8), Decimal(3)])
        self.assertEqual(second.value("total"), Decimal(11))
        self.assertNotEqual(first.digest, second.digest)
        with self.assertRaises(EngineError) as error:
            evaluate(m, {"rent": {"u2": 8}})
        self.assertEqual((error.exception.code, error.exception.key), ("INPUT_MISSING", "rent[u1]"))

    def test_check_due_after_recurrence_fails_before_downstream_division(self):
        m = Model("recurrence-check", "1", DecimalPolicy(34, "ROUND_HALF_EVEN"))
        m.dimension(Dimension("period", [Item(9), Item(4)]))
        m.calc("opening", unit="usd", dims=("period",), expr=lag("closing", "period", initial=0))
        m.calc("closing", unit="usd", dims=("period",), expr=ref("opening"))
        m.check("funded", dims=("period",), condition=ref("closing") > 0,
                code="NOT_FUNDED", message="The account needs funding.")
        m.calc("coverage", unit="ratio", dims=("period",), expr=1 / ref("closing"))
        with self.assertRaises(EngineError) as error:
            evaluate(m, {})
        self.assertEqual((error.exception.code, error.exception.key), ("NOT_FUNDED", "funded[9]"))


if __name__ == "__main__":
    unittest.main()
