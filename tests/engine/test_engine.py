"""Behavioural tests for the Balto model engine."""

from decimal import Decimal
import unittest

from balto_model_engine import (
    DecimalPolicy, Dimension, EngineError, Item, Model, ModelDefinitionError,
    allocate_round, const, evaluate, if_, mapped, matches, previous, ref, round_to, sum_over, sum_within, total,
)

MONTHS = Dimension("month", [Item(m) for m in range(1, 13)])


def model(*, version: str = "1.0.0") -> Model:
    return Model("fixture", version, DecimalPolicy(precision=34, rounding="ROUND_HALF_EVEN"))


class ScalarEvaluationTest(unittest.TestCase):

    def test_a_calculation_is_evaluated_from_its_inputs(self):
        m = model()
        m.input("rent", unit="usd")
        m.input("units", unit="count")
        m.calc("gross_rent", unit="usd", expr=ref("rent") * ref("units") * 12)
        run = evaluate(m, {"rent": "950", "units": 20})
        self.assertEqual(run.value("gross_rent"), Decimal("228000"))

    def test_operators_accept_plain_numbers_on_either_side(self):
        m = model()
        m.input("occupancy", unit="ratio")
        m.calc("vacancy", unit="ratio", expr=1 - ref("occupancy"))
        m.calc("half", unit="ratio", expr=ref("vacancy") / 2)
        m.calc("negated", unit="ratio", expr=-ref("half"))
        run = evaluate(m, {"occupancy": "0.9"})
        self.assertEqual(run.value("negated"), Decimal("-0.05"))

    def test_the_decimal_policy_governs_precision(self):
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=6, rounding="ROUND_HALF_EVEN"))
        m.input("a", unit="usd")
        m.calc("third", unit="usd", expr=ref("a") / 3)
        self.assertEqual(evaluate(m, {"a": 1}).value("third"), Decimal("0.333333"))


class DimensionTest(unittest.TestCase):

    def test_a_variable_is_defined_once_and_evaluated_for_every_item(self):
        m = model()
        m.dimension(MONTHS)
        m.input("gpr", unit="usd")
        m.input("occupancy", unit="ratio", dims=("month",))
        m.calc("vacancy", unit="usd", dims=("month",), expr=-(ref("gpr") * (1 - ref("occupancy"))))
        run = evaluate(m, {"gpr": 1000, "occupancy": {1: "0.5", **{i: 1 for i in range(2, 13)}}})
        self.assertEqual(run.value("vacancy", month=1), Decimal("-500.0"))
        self.assertEqual(run.value("vacancy", month=2), Decimal("0"))

    def test_a_sum_ranges_over_a_dimension_and_may_filter_by_attribute(self):
        m = model()
        m.dimension(Dimension("role", [Item("pm", kind="office"), Item("tech", kind="maintenance"),
                                       Item("leasing", kind="office")]))
        m.input("pay", unit="usd", dims=("role",))
        m.calc("office_pay", unit="usd", expr=sum_over("role", ref("pay"), kind="office"))
        m.calc("all_pay", unit="usd", expr=sum_over("role", ref("pay")))
        run = evaluate(m, {"pay": {"pm": 80000, "tech": 60000, "leasing": 50000}})
        self.assertEqual(run.value("office_pay"), Decimal("130000"))
        self.assertEqual(run.value("all_pay"), Decimal("190000"))

    def test_a_sum_over_an_empty_dimension_is_zero(self):
        m = model()
        m.dimension(Dimension("role", []))
        m.input("pay", unit="usd", dims=("role",))
        m.calc("payroll", unit="usd", expr=sum_over("role", ref("pay")))
        self.assertEqual(evaluate(m, {"pay": {}}).value("payroll"), Decimal(0))

    def test_total_adds_named_variables(self):
        m = model()
        for name in ("a", "b", "c"):
            m.input(name, unit="usd")
        m.calc("t", unit="usd", expr=total("a", "b", "c"))
        self.assertEqual(evaluate(m, {"a": 1, "b": 2, "c": "3.5"}).value("t"), Decimal("6.5"))


class RoundingTest(unittest.TestCase):

    def test_round_uses_the_policy_rounding_mode(self):
        m = model()
        m.input("x", unit="usd")
        m.calc("r", unit="usd", expr=round_to(ref("x"), 2))
        self.assertEqual(evaluate(m, {"x": "0.125"}).value("r"), Decimal("0.12"))
        self.assertEqual(evaluate(m, {"x": "0.135"}).value("r"), Decimal("0.14"))

    def test_allocated_rounding_ties_the_items_to_the_rounded_total(self):
        m = model()
        m.dimension(MONTHS)
        m.input("annual", unit="usd")
        m.calc("monthly", unit="usd", dims=("month",), expr=ref("annual") / 12)
        m.calc("cents", unit="usd", dims=("month",), expr=allocate_round(ref("monthly"), "month", 2))
        m.calc("check", unit="usd", expr=sum_over("month", ref("cents")))
        run = evaluate(m, {"annual": 1000})
        self.assertEqual(run.value("check"), Decimal("1000.00"))
        self.assertEqual({run.value("cents", month=i) for i in range(1, 13)},
                         {Decimal("83.33"), Decimal("83.34")})

    def test_allocated_rounding_moves_a_cent_toward_the_item_that_lost_it(self):
        # Rounding up to the $0.01 total goes to an item rounded down, never onto
        # the negative item, which would flip its sign.
        m = model()
        m.dimension(Dimension("part", [Item(i) for i in range(4)]))
        m.input("amount", unit="usd", dims=("part",))
        m.calc("cents", unit="usd", dims=("part",), expr=allocate_round(ref("amount"), "part", 2))
        run = evaluate(m, {"amount": {0: "0.0049", 1: "0.0049", 2: "0.0049", 3: "-0.005"}})
        self.assertEqual([run.value("cents", part=i) for i in range(4)],
                         [Decimal("0.01"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")])


class ConditionTest(unittest.TestCase):

    def test_a_condition_selects_between_two_expressions(self):
        m = model()
        m.input("fee", unit="usd")
        m.input("income", unit="usd")
        m.calc("share", unit="ratio",
               expr=if_(ref("income") == 0, const(0), round_to(ref("fee") / ref("income"), 4)))
        self.assertEqual(evaluate(m, {"fee": 5, "income": 100}).value("share"), Decimal("0.0500"))
        self.assertEqual(evaluate(m, {"fee": 5, "income": 0}).value("share"), Decimal(0))


class InputValidationTest(unittest.TestCase):

    def m(self) -> Model:
        m = model()
        m.dimension(MONTHS)
        m.input("occupancy", unit="ratio", dims=("month",), minimum=0, maximum=1)
        m.calc("avg", unit="ratio", expr=sum_over("month", ref("occupancy")) / 12)
        return m

    def test_a_missing_input_is_refused(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_MISSING", "occupancy"))

    def test_an_input_must_cover_every_item_of_its_dimensions(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {"occupancy": {1: 1}})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_MISSING", "occupancy[2]"))

    def test_an_input_outside_its_declared_bounds_is_refused(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {"occupancy": {i: ("1.2" if i == 3 else 1) for i in range(1, 13)}})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_OUT_OF_RANGE", "occupancy[3]"))

    def test_a_non_numeric_input_is_refused(self):
        for bad in (True, None, "ninety", float("nan")):
            with self.assertRaises(EngineError) as err:
                evaluate(self.m(), {"occupancy": {i: (bad if i == 1 else 1) for i in range(1, 13)}})
            self.assertEqual(err.exception.code, "INPUT_INVALID")

    def test_an_unknown_input_is_refused(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {"occupancy": {i: 1 for i in range(1, 13)}, "helipad": 1})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_UNKNOWN", "helipad"))

    def test_an_input_may_be_declared_on_a_subset_of_items(self):
        m = model()
        m.dimension(Dimension("unit_type", [Item("studio", regulated=True), Item("1br", regulated=False)]))
        m.input("rent", unit="usd", dims=("unit_type",))
        m.input("ceiling", unit="usd", dims=("unit_type",), where={"regulated": True})
        m.check("rent_within_ceiling", dims=("unit_type",), where={"regulated": True},
                condition=ref("rent") <= ref("ceiling"), code="REGULATORY_LIMIT_EXCEEDED",
                message="A budget rent exceeds the unit's maximum allowable rent.")
        run = evaluate(m, {"rent": {"studio": 1000, "1br": 5000}, "ceiling": {"studio": 1084}})
        self.assertEqual(run.value("rent", unit_type="1br"), Decimal(5000))
        with self.assertRaises(EngineError) as err:
            evaluate(m, {"rent": {"studio": 1400, "1br": 5000}, "ceiling": {"studio": 1084}})
        self.assertEqual((err.exception.code, err.exception.key),
                         ("REGULATORY_LIMIT_EXCEEDED", "rent_within_ceiling[studio]"))


class CheckTest(unittest.TestCase):

    def test_a_check_fails_the_run_before_calculations_its_failure_would_break(self):
        m = model()
        m.input("fee", unit="usd")
        m.input("units", unit="count", minimum=0)
        m.calc("fee_per_unit", unit="usd", expr=ref("fee") / ref("units"))
        m.check("has_units", condition=ref("units") > 0, code="NO_UNITS", message="A budget needs units.")
        with self.assertRaises(EngineError) as err:
            evaluate(m, {"fee": 100, "units": 0})
        self.assertEqual((err.exception.code, err.exception.key), ("NO_UNITS", "has_units"))

    def test_a_calculation_that_divides_by_zero_is_refused(self):
        m = model()
        m.input("fee", unit="usd")
        m.input("units", unit="count")
        m.calc("fee_per_unit", unit="usd", expr=ref("fee") / ref("units"))
        with self.assertRaises(EngineError) as err:
            evaluate(m, {"fee": 100, "units": 0})
        self.assertEqual((err.exception.code, err.exception.key), ("CALCULATION_UNDEFINED", "fee_per_unit"))


class ModelDefinitionTest(unittest.TestCase):

    def test_an_undeclared_cycle_is_a_definition_error(self):
        m = model()
        m.input("x", unit="usd")
        m.calc("a", unit="usd", expr=ref("b") + ref("x"))
        m.calc("b", unit="usd", expr=ref("a") * 2)
        with self.assertRaises(ModelDefinitionError) as err:
            evaluate(m, {"x": 1})
        self.assertIn("cycle", str(err.exception))

    def test_a_reference_to_an_undeclared_variable_is_a_definition_error(self):
        m = model()
        m.calc("a", unit="usd", expr=ref("nope") + 1)
        with self.assertRaises(ModelDefinitionError):
            evaluate(m, {})

    def test_a_reference_must_be_bound_on_every_dimension_it_carries(self):
        m = model()
        m.dimension(MONTHS)
        m.input("occupancy", unit="ratio", dims=("month",))
        m.calc("scalar", unit="ratio", expr=ref("occupancy") * 2)
        with self.assertRaises(ModelDefinitionError):
            evaluate(m, {"occupancy": {i: 1 for i in range(1, 13)}})

    def test_a_variable_is_defined_exactly_once(self):
        m = model()
        m.input("a", unit="usd")
        with self.assertRaises(ModelDefinitionError):
            m.calc("a", unit="usd", expr=const(1))

    def test_an_undeclared_dimension_is_a_definition_error(self):
        m = model()
        with self.assertRaises(ModelDefinitionError):
            m.input("a", unit="usd", dims=("month",))


class RunTest(unittest.TestCase):

    def m(self) -> Model:
        m = model()
        m.input("rent", unit="usd")
        m.calc("annual", unit="usd", expr=ref("rent") * 12)
        return m

    def test_a_run_pins_model_and_engine_identity(self):
        run = evaluate(self.m(), {"rent": 950})
        self.assertEqual((run.model_id, run.model_version), ("fixture", "1.0.0"))
        self.assertTrue(run.engine_version)

    def test_a_run_records_each_figures_kind_and_lineage(self):
        run = evaluate(self.m(), {"rent": 950})
        self.assertEqual(run.lineage["rent"]["kind"], "input")
        self.assertEqual(run.lineage["annual"]["kind"], "calculation")
        self.assertEqual(run.lineage["annual"]["expression"], "rent * 12")
        self.assertEqual(run.lineage["annual"]["dependsOn"], ["rent"])

    def test_the_run_digest_is_deterministic_and_input_sensitive(self):
        a = evaluate(self.m(), {"rent": 950}).digest
        self.assertEqual(a, evaluate(self.m(), {"rent": "950"}).digest)
        self.assertNotEqual(a, evaluate(self.m(), {"rent": 951}).digest)

    def test_the_run_digest_changes_when_a_formula_changes(self):
        other = model()
        other.input("rent", unit="usd")
        other.calc("annual", unit="usd", expr=ref("rent") * 12 + 0)
        self.assertNotEqual(evaluate(self.m(), {"rent": 950}).digest, evaluate(other, {"rent": 950}).digest)

    def test_the_run_digest_tells_attribute_values_apart_by_type(self):
        # flag=True and flag="True" select different items, so they are different
        # formulas even when both happen to give the same value.
        def with_filter(value):
            m = model()
            m.dimension(Dimension("part", [Item(0, flag=True), Item(1, flag="True")]))
            m.input("x", unit="usd", dims=("part",))
            m.calc("picked", unit="usd", expr=sum_over("part", ref("x"), flag=value))
            m.calc("chosen", unit="usd", dims=("part",), expr=if_(matches("part", flag=value), ref("x"), 0))
            return evaluate(m, {"x": {0: 0, 1: 0}})
        self.assertNotEqual(with_filter(True).digest, with_filter("True").digest)


TRAILING = {"name": "T12.xlsx", "sha256": "ab" * 32}


class SourceTest(unittest.TestCase):
    """A source is verbatim external data, supplied apart from chosen inputs."""

    def m(self) -> Model:
        m = model()
        m.dimension(Dimension("account", [Item(0), Item(1)]))
        m.source("trailing.amount", unit="usd_per_year", dims=("account",), document=TRAILING)
        m.input("growth", unit="ratio")
        m.calc("trailing.total", unit="usd_per_year", expr=sum_over("account", ref("trailing.amount")))
        return m

    def test_a_source_is_read_from_the_sources_and_recorded_with_its_document(self):
        run = evaluate(self.m(), {"growth": "1.04"}, sources={"trailing.amount": {0: "1200.50", 1: "-200.50"}})
        self.assertEqual(run.value("trailing.total"), Decimal("1000.00"))
        self.assertEqual(run.lineage["trailing.amount"]["kind"], "source")
        self.assertEqual(run.lineage["trailing.amount"]["document"], TRAILING)

    def test_a_source_is_not_an_input_and_an_input_is_not_a_source(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {"growth": 1, "trailing.amount": {0: 1, 1: 1}})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_UNKNOWN", "trailing.amount"))
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {}, sources={"trailing.amount": {0: 1, 1: 1}, "growth": 1})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_UNKNOWN", "growth"))

    def test_a_source_must_cover_every_item(self):
        with self.assertRaises(EngineError) as err:
            evaluate(self.m(), {"growth": 1}, sources={"trailing.amount": {0: 1}})
        self.assertEqual((err.exception.code, err.exception.key), ("INPUT_MISSING", "trailing.amount[1]"))

    def test_a_source_names_its_document(self):
        with self.assertRaises(ModelDefinitionError):
            model().source("rent_roll", unit="usd", document={})

    def test_the_document_is_part_of_the_run_digest(self):
        other = model()
        other.dimension(Dimension("account", [Item(0), Item(1)]))
        other.source("trailing.amount", unit="usd_per_year", dims=("account",),
                     document={**TRAILING, "sha256": "cd" * 32})
        other.input("growth", unit="ratio")
        other.calc("trailing.total", unit="usd_per_year", expr=sum_over("account", ref("trailing.amount")))
        sources = {"trailing.amount": {0: 1, 1: 1}}
        self.assertNotEqual(evaluate(self.m(), {"growth": 1}, sources=sources).digest,
                            evaluate(other, {"growth": 1}, sources=sources).digest)


class MappingTest(unittest.TestCase):
    """A mapping is a reviewed correspondence from a source's items to targets."""

    SELLER = {0: "4020 Tenant Rent", 1: "4025 HAP Rent", 2: "6410 Bad Debt", 3: "7404 Interior Capex"}

    def m(self, assign=None, signs=None) -> Model:
        m = model()
        m.dimension(Dimension("account", [Item(k) for k in self.SELLER]))
        m.source("trailing.amount", unit="usd_per_year", dims=("account",), document=TRAILING)
        m.mapping("trailing_map", dim="account",
                  assign=assign if assign is not None else {0: "gpr", 1: "gpr", 2: "bad_debt", 3: None},
                  signs=signs if signs is not None else {2: -1})
        m.calc("trailing.gpr", unit="usd_per_year", expr=mapped("trailing_map", "gpr", ref("trailing.amount")))
        m.calc("trailing.bad_debt", unit="usd_per_year",
               expr=mapped("trailing_map", "bad_debt", ref("trailing.amount")))
        return m

    SOURCES = {"trailing.amount": {0: "700000", 1: "180000", 2: "39600", 3: "78600"}}

    def test_mapped_sums_the_items_assigned_to_a_target_with_their_sign(self):
        run = evaluate(self.m(), {}, sources=self.SOURCES)
        self.assertEqual(run.value("trailing.gpr"), Decimal("880000"))
        self.assertEqual(run.value("trailing.bad_debt"), Decimal("-39600"))

    def test_mapped_names_its_mapping_in_the_lineage(self):
        lineage = evaluate(self.m(), {}, sources=self.SOURCES).lineage["trailing.gpr"]
        self.assertEqual(lineage["expression"], "mapped(trailing_map -> gpr: trailing.amount)")
        self.assertEqual(lineage["dependsOn"], ["trailing.amount"])
        self.assertEqual(lineage["mappings"], ["trailing_map"])

    def test_every_item_is_assigned_or_explicitly_excluded(self):
        with self.assertRaises(ModelDefinitionError):
            self.m(assign={0: "gpr", 1: "gpr", 2: "bad_debt"})
        with self.assertRaises(ModelDefinitionError):
            self.m(assign={0: "gpr", 1: "gpr", 2: "bad_debt", 3: None, 9: "gpr"})

    def test_a_sign_reverses_an_item_and_is_nothing_else(self):
        with self.assertRaises(ModelDefinitionError):
            self.m(signs={2: 2})
        with self.assertRaises(ModelDefinitionError):
            self.m(signs={3: -1})  # an excluded item feeds no target

    def test_a_target_no_item_is_mapped_to_is_a_definition_error(self):
        m = self.m()
        m.calc("trailing.water", unit="usd_per_year", expr=mapped("trailing_map", "water", ref("trailing.amount")))
        with self.assertRaises(ModelDefinitionError):
            evaluate(m, {}, sources=self.SOURCES)

    def test_the_mapping_is_part_of_the_run_digest(self):
        base = evaluate(self.m(), {}, sources=self.SOURCES)
        moved = evaluate(self.m(assign={0: "gpr", 1: "gpr", 2: "bad_debt", 3: "bad_debt"}), {}, sources=self.SOURCES)
        self.assertNotEqual(base.digest, moved.digest)


RENT_ROLL = {"name": "RR.pdf", "sha256": "cd" * 32}


class HierarchyTest(unittest.TestCase):
    """A dimension may nest in a parent: each unit belongs to one unit type."""

    def m(self) -> Model:
        m = model()
        m.dimension(Dimension("unit_type", [Item("1BR", basis="market"), Item("2BR", basis="in_place")]))
        m.dimension(Dimension("unit", [Item("101", unit_type="1BR", occupied=True),
                                       Item("102", unit_type="1BR", occupied=False),
                                       Item("201", unit_type="2BR", occupied=True)], parent="unit_type"))
        m.source("rent", unit="usd", dims=("unit",), document=RENT_ROLL)
        m.input("market", unit="usd", dims=("unit_type",))
        return m

    SOURCES = {"rent": {"101": 1000, "102": 950, "201": 1400}}
    INPUTS = {"market": {"1BR": 1100, "2BR": 1500}}

    def test_a_child_item_reads_its_parents_value(self):
        m = self.m()
        m.calc("gap", unit="usd", dims=("unit",), expr=ref("market") - ref("rent"))
        run = evaluate(m, self.INPUTS, sources=self.SOURCES)
        self.assertEqual([run.value("gap", unit=u) for u in ("101", "102", "201")],
                         [Decimal(100), Decimal(150), Decimal(100)])

    def test_sum_within_adds_the_children_of_the_current_parent(self):
        m = self.m()
        m.calc("count", unit="units", dims=("unit_type",), expr=sum_within("unit", const(1)))
        m.calc("occupied", unit="units", dims=("unit_type",), expr=sum_within("unit", const(1), occupied=True))
        m.calc("roll", unit="usd", dims=("unit_type",), expr=sum_within("unit", ref("rent")))
        run = evaluate(m, self.INPUTS, sources=self.SOURCES)
        self.assertEqual(run.value("count", unit_type="1BR"), 2)
        self.assertEqual(run.value("occupied", unit_type="1BR"), 1)
        self.assertEqual(run.value("roll", unit_type="2BR"), 1400)
        self.assertEqual(evaluate(m, self.INPUTS, sources=self.SOURCES).lineage["roll"]["expression"],
                         "sum_within(unit: rent)")

    def test_a_condition_may_test_an_items_attributes(self):
        m = self.m()
        m.calc("start", unit="usd", dims=("unit",), expr=if_(matches("unit", occupied=True), ref("rent"), ref("market")))
        m.calc("basis_rent", unit="usd", dims=("unit",),
               expr=if_(matches("unit_type", basis="market"), ref("market"), ref("rent")))
        run = evaluate(m, self.INPUTS, sources=self.SOURCES)
        self.assertEqual([run.value("start", unit=u) for u in ("101", "102", "201")], [1000, 1100, 1400])
        self.assertEqual([run.value("basis_rent", unit=u) for u in ("101", "102", "201")], [1100, 1100, 1400])

    def test_a_child_must_name_a_declared_parent_item(self):
        m = model()
        m.dimension(Dimension("unit_type", [Item("1BR")]))
        with self.assertRaises(ModelDefinitionError):
            m.dimension(Dimension("unit", [Item("101", unit_type="3BR")], parent="unit_type"))
        with self.assertRaises(ModelDefinitionError):
            m.dimension(Dimension("unit", [Item("101")], parent="unit_type"))
        with self.assertRaises(ModelDefinitionError):
            m.dimension(Dimension("unit", [Item("101", building="A")], parent="building"))

    def test_sum_within_needs_its_parent_bound(self):
        m = self.m()
        m.calc("everything", unit="units", expr=sum_within("unit", const(1)))
        with self.assertRaises(ModelDefinitionError):
            evaluate(m, self.INPUTS, sources=self.SOURCES)
        flat = self.m()
        flat.calc("types", unit="units", expr=sum_within("unit_type", const(1)))
        with self.assertRaises(ModelDefinitionError):
            evaluate(flat, self.INPUTS, sources=self.SOURCES)

    def test_the_hierarchy_is_part_of_the_run_digest(self):
        moved = model()
        moved.dimension(Dimension("unit_type", [Item("1BR", basis="market"), Item("2BR", basis="in_place")]))
        moved.dimension(Dimension("unit", [Item("101", unit_type="1BR", occupied=True),
                                           Item("102", unit_type="2BR", occupied=False),
                                           Item("201", unit_type="2BR", occupied=True)], parent="unit_type"))
        moved.source("rent", unit="usd", dims=("unit",), document=RENT_ROLL)
        moved.input("market", unit="usd", dims=("unit_type",))
        self.assertNotEqual(evaluate(self.m(), self.INPUTS, sources=self.SOURCES).digest,
                            evaluate(moved, self.INPUTS, sources=self.SOURCES).digest)


class PreviousTest(unittest.TestCase):
    """A recurrence reads a variable at the previous item of an ordered dimension."""

    def test_a_variable_may_carry_forward_from_its_previous_month(self):
        m = model()
        m.dimension(MONTHS)
        m.input("opening", unit="usd")
        m.input("growth", unit="ratio")
        m.calc("rent", unit="usd", dims=("month",),
               expr=previous("rent", "month", initial=ref("opening"), step=lambda p: p * (1 + ref("growth"))))
        run = evaluate(m, {"opening": 1000, "growth": "0.1"})
        self.assertEqual(run.value("rent", month=1), 1000)
        self.assertEqual(run.value("rent", month=3), Decimal("1210.00"))
        self.assertEqual(run.lineage["rent"]["dependsOn"], ["opening", "growth"])

    def test_previous_may_read_another_variable(self):
        m = model()
        m.dimension(MONTHS)
        m.input("move_ins", unit="units", dims=("month",))
        m.calc("prior_move_ins", unit="units", dims=("month",),
               expr=previous("move_ins", "month", initial=const(0)))
        run = evaluate(m, {"move_ins": {i: i for i in range(1, 13)}})
        self.assertEqual(run.series("prior_move_ins")[:3], [0, 1, 2])

    def test_a_recurrence_must_run_along_its_own_dimension(self):
        m = model()
        m.dimension(MONTHS)
        m.input("opening", unit="usd")
        m.calc("rent", unit="usd", expr=previous("rent", "month", initial=ref("opening")))
        with self.assertRaises(ModelDefinitionError):
            evaluate(m, {"opening": 1})


if __name__ == "__main__":
    unittest.main()
