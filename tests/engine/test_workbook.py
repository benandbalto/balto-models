"""The workbook compiler and its independent recalculation."""

from datetime import date
from decimal import Decimal
import importlib.util
import os
import tempfile
import unittest

from balto_model_engine import (
    DecimalPolicy, Dimension, Item, Model, allocate_round, attr, evaluate, if_, matches, monthly_calendar, power, ref,
    sum_over, round_to,
)
from test_recurrence import INPUTS, model, sweep_loan

HAS_COMPILER_DEPS = all(importlib.util.find_spec(m) is not None for m in ("openpyxl", "pycel"))


@unittest.skipUnless(HAS_COMPILER_DEPS, "openpyxl and pycel are needed to compile and recalculate")
class CompileTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def compile(self, m, run, layout=None):
        from balto_model_engine.workbook import compile_workbook
        compiled = compile_workbook(m, run, layout)
        path = compiled.save(os.path.join(self.dir.name, "model.xlsx"))
        return compiled, path

    def test_long_forecast_construction_interest_total_compiles_and_recalculates(self):
        from balto_model_engine.parity import check_parity
        m = Model('long-construction-interest', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i) for i in range(601)]))
        m.dimension(Dimension('facility', [Item('bond'), Item('bridge'), Item('taxable')]))
        m.input('interest', unit='usd', dims=('facility', 'month'))
        m.calc('total', unit='usd', expr=sum_over('month', sum_over('facility', ref('interest'))))
        inputs = {'interest': {(f, i): '10.25' for f in ('bond', 'bridge', 'taxable') for i in range(601)}}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run, inputs=inputs,
                              flex={'interest': {('bond', 0): '20.25'}})
        self.assertTrue(report.ok, report.mismatches)

    def test_long_forecast_shortfall_count_compiles_and_recalculates(self):
        from balto_model_engine import const
        from balto_model_engine.parity import check_parity
        m = Model('long-forecast-count', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i) for i in range(601)]))
        m.input('shortfall', unit='usd', dims=('month',))
        m.calc('shortfall_months', unit='count',
               expr=sum_over('month', if_(ref('shortfall') > 0, const(1), const(0))))
        inputs = {'shortfall': {i: '1' if i % 2 else '0' for i in range(601)}}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run, inputs=inputs,
                              flex={'shortfall': {(0,): '1'}})
        self.assertTrue(report.ok, report.mismatches)

    def test_half_cent_tax_effect_rounds_away_from_zero_after_multiplication(self):
        from balto_model_engine.parity import check_parity
        m = Model('half-cent-tax', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i) for i in range(12)]))
        m.input('income', unit='usd', dims=('month',))
        m.input('rate', unit='ratio')
        m.calc('tax', unit='usd', expr=round_to(sum_over('month', ref('income')) * ref('rate'), 2))
        inputs = {'income': {i: '-1103.675' for i in range(12)}, 'rate': '0.25'}
        run = evaluate(m, inputs)
        self.assertEqual(run.value('tax'), Decimal('-3311.03'))
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)

    def test_live_validation_flags_invalid_inputs_and_model_rules(self):
        from balto_model_engine.workbook import compile_workbook
        from pycel import ExcelCompiler
        from balto_model_engine.parity import _strip_cached
        m = Model('live-validation', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.input('reserve', unit='usd', minimum=0, maximum=100)
        m.input('withdrawal', unit='usd', minimum=0)
        m.check('funded_withdrawal', condition=ref('withdrawal') <= ref('reserve'),
                code='RESERVE_OVERDRAW', message='Withdrawals must be funded.')
        run = evaluate(m, {'reserve': 50, 'withdrawal': 20})
        compiled = compile_workbook(m, run, include_checks=True)
        path = compiled.save(os.path.join(self.dir.name, 'checks.xlsx'))
        bare = os.path.join(self.dir.name, 'checks-bare.xlsx')
        _strip_cached(path, bare)
        xl = ExcelCompiler(filename=bare)
        self.assertEqual([xl.evaluate(f'Checks!C{i}') for i in range(2, 5)], [1, 1, 1])
        reserve = compiled.cells['reserve'][()].replace("'", '')
        xl.set_value(reserve, -1)
        self.assertEqual(xl.evaluate('Checks!C2'), 0)
        self.assertEqual(xl.evaluate('Checks!C3'), 0)
        xl.set_value(reserve, 'bad input')
        self.assertEqual(xl.evaluate('Checks!C3'), 0)

    def test_half_cent_allocation_preserves_tie_order_after_excel_recalculation(self):
        from balto_model_engine.parity import check_parity
        m = Model('half-cent-allocation', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i) for i in range(12)]))
        m.input('cost', unit='usd', dims=('month',))
        m.input('deferred_fraction', unit='ratio')
        m.calc('deferred', unit='usd', dims=('month',),
               expr=allocate_round(ref('cost') * ref('deferred_fraction'), 'month', 2))
        inputs = {'cost': {i: '16666.67' if i < 11 else '16666.63' for i in range(12)},
                  'deferred_fraction': '0.5'}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)

    def test_reserve_and_funding_workbook_recalculates_depletion_and_release(self):
        from test_funding_components import reserve_model, INPUTS
        from balto_model_engine.funding import build_funding
        from balto_model_engine import const
        from balto_model_engine.parity import check_parity
        m, reserve = reserve_model()
        build_funding(m, period_dim='interval', sources=const(0), uses=ref('spending'),
            transfers_in=reserve.draw + reserve.released, transfers_out=reserve.deposits,
            external_funding=const(0), cash_name='net', contribution_name='call',
            distribution_name='distribution', unmet_name='unmet')
        run = evaluate(m, INPUTS)
        compiled, path = self.compile(m, run)
        for flex in ({}, {'deposit': {(0,): 0}}, {'spending': {(1,): 40}},
                     {'release': {(3,): 0, (4,): 100}}):
            report = check_parity(path, compiled, m, run, inputs=INPUTS, flex=flex)
            self.assertTrue(report.ok, report.mismatches)

    def test_shared_noi_budget_compiles_to_live_formulas_and_recalculates(self):
        from balto_model_engine.operating import annual_per_unit, build_noi
        from balto_model_engine.parity import check_parity
        m = Model('noi-budget', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(1), Item(2)]))
        m.input('income', unit='usd', dims=('month',))
        m.input('units', unit='units')
        m.input('expense_per_unit', unit='usd/unit-year')
        m.calc('expenses', unit='usd', dims=('month',),
               expr=annual_per_unit(ref('expense_per_unit'), ref('units')))
        build_noi(m, income=ref('income'), expenses=ref('expenses'), name='noi', dims=('month',))
        inputs = {'income': {1: 5000, 2: 6000}, 'units': 10, 'expense_per_unit': 600}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run, inputs=inputs)
        self.assertTrue(report.ok, report.mismatches)

    def test_standalone_capital_budget_and_spending_recalculate_with_flexed_inputs(self):
        from balto_model_engine.capital import build_capital_budget, build_even_spending, quantity_cost
        from balto_model_engine.parity import check_parity
        m = Model('capital-workbook', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('stage', [Item('build')]))
        m.dimension(Dimension('interval', [Item(f't{i}', ordinal=i) for i in range(5)]))
        for name in ('price', 'quantity', 'gc_rate', 'fee_rate', 'risk_rate', 'start', 'duration'):
            m.input(name, unit='number', dims=('stage',))
        budget = build_capital_budget(m, phase_dim='stage',
            hard_costs=quantity_cost(ref('price'), ref('quantity')),
            general_conditions_rate=ref('gc_rate'), gc_fee_rate=ref('fee_rate'),
            contingency_rate=ref('risk_rate'), hard_name='build.hard',
            general_conditions_name='build.conditions', gc_fee_name='build.fee',
            contingency_name='build.risk', total_name='build.total')
        spend = build_even_spending(m, phase_dim=budget.phase_dim, period_dim='interval',
            budget=budget.total, period_index=attr('interval', 'ordinal'),
            start=ref('start'), periods=ref('duration'), activity=if_(ref('quantity') > 0, 1, 0),
            name='build.spend')
        m.calc('build.spent', unit='usd', dims=('stage',), expr=sum_over(spend.period_dim, spend.amount))
        inputs = {name: {'build': value} for name, value in {
            'price': 100, 'quantity': 3, 'gc_rate': '.1', 'fee_rate': '.2', 'risk_rate': '.1',
            'start': 1, 'duration': 3}.items()}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)
        report = check_parity(path, compiled, m, run, inputs=inputs,
            flex={'quantity': {('build',): 5}, 'fee_rate': {('build',): '.15'},
                  'duration': {('build',): 2}, 'start': {('build',): 2}})
        self.assertTrue(report.ok, report.mismatches)

    def test_standalone_debt_and_windows_recalculate_with_flexed_terms(self):
        from test_debt_components import INPUTS as debt_inputs, debt_model
        from balto_model_engine.debt import build_loan_sizing
        from balto_model_engine.periods import period_total, period_window
        from balto_model_engine.parity import check_parity
        m, debt = debt_model()
        m.input('eligible', unit='usd', dims=('interval',))
        m.input('value', unit='usd')
        m.input('included', unit='flag')
        m.input('ltv', unit='rate')
        m.input('dscr', unit='ratio')
        m.calc('eligible.window', unit='usd', expr=period_total(debt.period_dim, ref('eligible'),
            activity=period_window(attr('interval', 'ordinal'), start=ref('fund'), end=ref('retire'),
                                   include_start=False, include_end=True)))
        build_loan_sizing(m, prefix='limit', income=ref('eligible.window'), value=ref('value'),
            max_ltv=ref('ltv'), min_dscr=ref('dscr'),
            payment_constant=debt.terms.payment_constant, included=ref('included'))
        inputs = {**debt_inputs, 'eligible': {f't{i}': 10 + i for i in range(8)},
                  'value': 1000, 'included': 1, 'ltv': '.7', 'dscr': '1.25'}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)
        for flex in ({'rate': {(): '.12'}, 'io': {(): 0}, 'retire': {(): 4},
                      'years': {(): 2}, 'fund': {(): 2}, 'amount': {(): 1400},
                      'ltv': {(): '.6'}, 'dscr': {(): '1.5'}},
                     {'included': {(): 0}, 'eligible': {('t3',): -100}},
                     {'amount': {(): 0}}):
            report = check_parity(path, compiled, m, run, inputs=inputs, flex=flex)
            self.assertTrue(report.ok, report.mismatches)

    def test_a_recurrence_block_recalculates_to_the_run(self):
        from balto_model_engine.parity import check_parity
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)
        self.assertEqual(report.compared, 5 * 7 + 1)

    def test_a_flexed_input_recalculates_to_a_fresh_run(self):
        from balto_model_engine.parity import check_parity
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run, inputs=INPUTS,
                              flex={"rate": {(): "0.2"}, "cash": {(3,): 50}})
        self.assertTrue(report.ok, report.mismatches)

    def test_a_lag_is_the_previous_column(self):
        from openpyxl import load_workbook
        m = model()
        sweep_loan(m)
        compiled, path = self.compile(m, evaluate(m, INPUTS))
        ws = load_workbook(path)["Calculations by month"]
        opening = compiled.cells["opening"]
        self.assertEqual(ws[opening[(0,)].split("!")[1]].value, "=0")
        closing_month_2 = compiled.cells["closing"][(2,)].split("!")[1]
        self.assertEqual(ws[opening[(3,)].split("!")[1]].value, f"={closing_month_2}")

    def test_every_formula_carries_the_runs_value(self):
        from openpyxl import load_workbook
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        compiled, path = self.compile(m, run)
        wb = load_workbook(path, data_only=True)
        for name, cells in compiled.cells.items():
            for idx, address in cells.items():
                sheet, cell = address.rsplit("!", 1)
                cached = wb[sheet.strip("'")][cell].value
                self.assertAlmostEqual(float(run.values[name][idx]), cached, places=9, msg=address)

    def test_recalculation_does_not_trust_cached_values(self):
        from balto_model_engine.parity import check_parity
        from balto_model_engine.workbook import compile_workbook
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        compiled = compile_workbook(m, run)
        compiled._cached = {k: v + 1000 for k, v in compiled._cached.items()}
        path = compiled.save(os.path.join(self.dir.name, "stale.xlsx"))
        self.assertTrue(check_parity(path, compiled, m, run).ok)

    def test_a_wrong_formula_is_caught(self):
        from openpyxl import load_workbook
        from balto_model_engine.parity import check_parity
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        compiled, path = self.compile(m, run)
        wb = load_workbook(path)
        sheet, cell = compiled.cells["interest"][(2,)].rsplit("!", 1)
        wb[sheet.strip("'")][cell] = "=0"
        wb.save(path)
        report = check_parity(path, compiled, m, run)
        self.assertFalse(report.ok)
        self.assertIn("interest[2]", [x["figure"] for x in report.mismatches])

    def test_allocated_rounding_ties_in_formulas(self):
        from balto_model_engine.parity import check_parity
        m = model()
        m.input("annual", unit="usd")
        m.input("weight", unit="ratio", dims=("month",))
        m.calc("even", unit="usd", dims=("month",), expr=allocate_round(ref("annual") / 7, "month", 2))
        m.calc("weighted", unit="usd", dims=("month",), expr=allocate_round(ref("annual") * ref("weight"), "month", 2))
        m.calc("check_even", unit="usd", expr=sum_over("month", ref("even")))
        inputs = {"annual": "1000.03", "weight": {0: "0.1", 1: "0.1", 2: "0.2", 3: "0.15", 4: "0.15", 5: "0.1",
                                                    6: "0.2"}}
        run = evaluate(m, inputs)
        self.assertEqual(run.value("check_even"), Decimal("1000.03"))
        compiled, path = self.compile(m, run)
        self.assertTrue(check_parity(path, compiled, m, run).ok)
        flexed = check_parity(path, compiled, m, run, inputs=inputs, flex={"annual": {(): "999.99"}})
        self.assertTrue(flexed.ok, flexed.mismatches)

    def test_an_attribute_condition_is_resolved_per_cell(self):
        from openpyxl import load_workbook
        m = model()
        m.dimension(Dimension("unit", [Item("a", regulated=True), Item("b", regulated=False)]))
        m.input("rent", unit="usd", dims=("unit",))
        m.input("cap", unit="usd", dims=("unit",), where={"regulated": True})
        m.calc("allowed", unit="usd", dims=("unit",),
               expr=if_(matches("unit", regulated=True), ref("cap"), ref("rent")))
        run = evaluate(m, {"rent": {"a": 10, "b": 20}, "cap": {"a": 8}})
        compiled, path = self.compile(m, run)
        ws = load_workbook(path)["Calculations"]
        a = compiled.cells["allowed"][("a",)].split("!")[1]
        b = compiled.cells["allowed"][("b",)].split("!")[1]
        self.assertNotIn("IF", ws[a].value)
        self.assertNotIn("IF", ws[b].value)

    def test_labels_are_text_even_when_they_look_like_formulas(self):
        from openpyxl import load_workbook
        m = model()
        m.dimension(Dimension("unit", [Item("=HYPERLINK(1)")]))
        m.input("rent", unit="usd", dims=("unit",))
        compiled, path = self.compile(m, evaluate(m, {"rent": {"=HYPERLINK(1)": 1}}))
        ws = load_workbook(path)["Inputs"]
        labels = [c.value for c in ws["A"]]
        self.assertIn("rent · =HYPERLINK(1)", labels)
        row = labels.index("rent · =HYPERLINK(1)") + 1
        self.assertEqual(ws[f"A{row}"].data_type, "s")

    def test_the_layout_must_place_every_figure_once(self):
        from balto_model_engine.workbook import CompileError, Layout, Sheet, compile_workbook
        m = model()
        sweep_loan(m)
        run = evaluate(m, INPUTS)
        with self.assertRaisesRegex(CompileError, "does not place"):
            compile_workbook(m, run, Layout((Sheet("Only", ("amount",)),)))
        m = model()
        m.dimension(Dimension("unit", [Item("a")]))
        m.input("rent", unit="usd", dims=("unit",))
        with self.assertRaisesRegex(CompileError, "does not run across"):
            compile_workbook(m, evaluate(m, {"rent": {"a": 1}}), Layout((Sheet("Monthly", ("rent",), "month"),)))

    def test_a_negative_constant_keeps_its_sign(self):
        from balto_model_engine.parity import check_parity
        m = model()
        m.input("rate", unit="ratio")
        m.calc("discount", unit="ratio", expr=power(1 + ref("rate"), -12))
        run = evaluate(m, {"rate": "0.01"})
        compiled, path = self.compile(m, run)
        self.assertTrue(check_parity(path, compiled, m, run).ok)

    def test_a_sum_of_sums_is_written_as_ranges(self):
        from openpyxl import load_workbook
        from balto_model_engine.parity import check_parity
        m = model()
        m.dimension(Dimension("unit", [Item("a", kind="x"), Item("b", kind="y"), Item("c", kind="x")]))
        m.input("rent", unit="usd", dims=("unit",))
        m.input("other", unit="usd", dims=("unit",))
        m.calc("both", unit="usd", expr=sum_over("unit", ref("rent") - ref("other")))
        m.calc("x_only", unit="usd", expr=sum_over("unit", if_(matches("unit", kind="x"), ref("rent"), 0)))
        inputs = {"rent": {"a": 10, "b": 20, "c": 30}, "other": {"a": 1, "b": 2, "c": 3}}
        run = evaluate(m, inputs)
        compiled, path = self.compile(m, run)
        ws = load_workbook(path)["Calculations"]
        both = ws[compiled.cells["both"][()].split("!")[1]].value
        x_only = ws[compiled.cells["x_only"][()].split("!")[1]].value
        self.assertRegex(both, r"^=\(SUM\([^)]*\)-SUM\([^)]*\)\)$")
        self.assertNotIn("+0", x_only)
        self.assertTrue(check_parity(path, compiled, m, run).ok)

    def test_presentation_rows_and_a_live_xirr(self):
        from openpyxl import load_workbook
        from balto_model_engine.parity import check_parity
        from balto_model_engine.workbook import Heading, Layout, MetricRow, Row, Sheet
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(monthly_calendar(date(2026, 12, 31), 12))
        m.input("price", unit="usd")
        m.input("rent", unit="usd")
        m.calc("flow", unit="usd", dims=("month",),
               expr=if_(attr("month", "index") == 0, -ref("price"),
                        ref("rent") + if_(attr("month", "index") == 12, ref("price"), 0)))
        m.xirr("irr", flows="flow", dim="month", date_attr="date")
        inputs = {"price": 1000, "rent": 8}
        run = evaluate(m, inputs)
        layout = Layout((
            Sheet("Summary", (Heading("Deal"), Row("price", "Purchase price", total=True), Row("rent", "Rent"),
                              MetricRow("irr", "IRR"))),
            Sheet("Flows", (Row("flow", "Cash flow", '#,##0'),), "month"),
        ), units={"usd": "$"})
        compiled, path = self.compile(m, run, layout)
        ws = load_workbook(path)["Summary"]
        labels = [c.value for c in ws["A"]]
        self.assertEqual(labels[1:5], ["Deal", "Purchase price", "Rent", "IRR"])
        self.assertEqual(ws["B3"].value, "$")
        self.assertTrue(ws["C3"].font.bold)
        self.assertTrue(ws["C5"].value.startswith("=XIRR('Flows'!"))
        self.assertTrue(check_parity(path, compiled, m, run).ok)
        flexed = check_parity(path, compiled, m, run, inputs=inputs, flex={"rent": {(): 12}})
        self.assertTrue(flexed.ok, flexed.mismatches)
        self.assertGreater(run.metrics["irr"]["rate"], 0)

    def test_a_sum_of_more_than_255_cells_keeps_its_grouping(self):
        from balto_model_engine.parity import check_parity
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(Dimension("unit", [Item(i, kind="x" if i % 2 == 0 else "y") for i in range(512)]))
        m.input("rent", unit="usd", dims=("unit",))
        m.calc("doubled", unit="usd", expr=sum_over("unit", ref("rent"), kind="x") * 2)
        inputs = {"rent": {i: 1 for i in range(512)}}
        run = evaluate(m, inputs)
        self.assertEqual(run.value("doubled"), 512)
        compiled, path = self.compile(m, run)
        report = check_parity(path, compiled, m, run)
        self.assertTrue(report.ok, report.mismatches)

    def test_an_allocation_under_a_labelled_row(self):
        from balto_model_engine.parity import check_parity
        from balto_model_engine.workbook import Layout, Row, Sheet
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(monthly_calendar(date(2026, 12, 31), 1))
        m.input("total", unit="usd")
        m.calc("a", unit="usd", dims=("month",), expr=allocate_round(ref("total") / 2, "month", 2))
        run = evaluate(m, {"total": "0.25"})
        layout = Layout((Sheet("Inputs", (Row("total", "Total"),)), Sheet("Months", (Row("a", "A"),), "month")))
        compiled, path = self.compile(m, run, layout)
        self.assertTrue(check_parity(path, compiled, m, run).ok)

    def test_xirr_is_recalculated_independently_of_the_engine(self):
        from balto_model_engine.excel_functions import xirr
        # The engine's run and Excel's Newton method must agree on a high rate.
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(monthly_calendar(date(2026, 12, 31), 12))
        m.input("price", unit="usd")
        m.calc("flow", unit="usd", dims=("month",),
               expr=if_(attr("month", "index") == 0, -ref("price"), if_(attr("month", "index") == 12, 2000, 0)))
        m.xirr("irr", flows="flow", dim="month", date_attr="date")
        run = evaluate(m, {"price": 100})
        self.assertAlmostEqual(float(run.metrics["irr"]["rate"]), 19.0, places=6)
        self.assertAlmostEqual(xirr([-100, 2000], [0, 365]), 19.0, places=9)
        self.assertEqual(xirr([100, 200], [0, 365]), "#NUM!")

    def test_a_variable_can_be_shown_in_groups_of_items(self):
        from openpyxl import load_workbook
        from balto_model_engine.parity import check_parity
        from balto_model_engine.workbook import CompileError, Heading, Layout, Row, Sheet, compile_workbook
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(Dimension("cost", [Item("a", label="Title", kind="buy"), Item("b", label="Lender legal", kind="loan"),
                                       Item("c", label="Escrow", kind="buy")]))
        m.input("cost", unit="usd", dims=("cost",))
        m.calc("total", unit="usd", expr=sum_over("cost", ref("cost")))
        run = evaluate(m, {"cost": {"a": 1, "b": 2, "c": 3}})
        layout = Layout((Sheet("Costs", (Heading("Acquisition"), Row("cost", "", where={"kind": "buy"}),
                                         Heading("Financing"), Row("cost", "", where={"kind": "loan"}),
                                         Row("total", "Total", total=True))),))
        compiled, path = self.compile(m, run, layout)
        labels = [c.value for c in load_workbook(path)["Costs"]["A"]]
        self.assertEqual(labels[1:8], ["Acquisition", "Title", "Escrow", None, "Financing", "Lender legal", "Total"])
        self.assertTrue(check_parity(path, compiled, m, run).ok)
        partial = Layout((Sheet("Costs", (Row("cost", "", where={"kind": "buy"}), Row("total"))),))
        with self.assertRaisesRegex(CompileError, "every item of cost"):
            compile_workbook(m, run, partial)

    def test_a_calculation_over_some_items(self):
        from balto_model_engine.parity import check_parity
        m = Model("fixture", "1.0.0", DecimalPolicy(precision=34, rounding="ROUND_HALF_UP"))
        m.dimension(Dimension("line", [Item("roof", method="lump"), Item("locks", method="unit")]))
        m.input("amount", unit="usd", dims=("line",), where={"method": "lump"})
        m.input("unit_cost", unit="usd", dims=("line",), where={"method": "unit"})
        m.input("count", unit="units", dims=("line",), where={"method": "unit"})
        m.calc("cost", unit="usd", dims=("line",), where={"method": "unit"}, expr=ref("unit_cost") * ref("count"))
        m.calc("total", unit="usd", expr=sum_over("line", ref("amount"), method="lump")
               + sum_over("line", ref("cost"), method="unit"))
        inputs = {"amount": {"roof": 100}, "unit_cost": {"locks": 5}, "count": {"locks": 4}}
        run = evaluate(m, inputs)
        self.assertEqual(list(run.values["cost"]), [("locks",)])
        self.assertEqual(run.value("total"), 120)
        compiled, path = self.compile(m, run)
        self.assertTrue(check_parity(path, compiled, m, run).ok)


if __name__ == "__main__":
    unittest.main()
