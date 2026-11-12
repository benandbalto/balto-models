"""The value-add acquisition model on a synthetic deal."""

from dataclasses import replace
from decimal import Decimal
import unittest

from balto_model_engine import EngineError, Model, evaluate, ref
from balto_valuation import Tranche, build_model, capital, ledger, operations, rents, timeline
from balto_valuation.example import example_deal, example_inputs
from balto_model_engine.operating import build_operating_cash_flow

TOL = Decimal("1e-6")


def run(deal=None, **changes):
    deal = deal or example_deal()
    inputs = {**example_inputs(), **changes}
    return evaluate(build_model(deal), inputs)


def months(r):
    return sorted(k[0] for k in r.values["noi"])


class ExampleTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = run()

    def v(self, name, *idx):
        return self.result.values[name][tuple(idx)]

    def test_shared_waterfall_version_has_a_pinned_example_digest(self):
        self.assertEqual(self.result.digest,
                         'beb59e30cec3368781487b360532536f9a7e37ee0703f25d0fdbe8e8e8da1858')

    def test_acquisition_exposes_dated_operations_and_explicit_reserves(self):
        from balto_valuation.model import POLICY
        m = Model('property-projection', '1.0.0', POLICY)
        deal = example_deal()
        timeline.build(m, deal)
        rents.build(m, deal)
        cash = operations.build(m, deal)
        self.assertEqual(cash.projection.currency, 'USD')
        self.assertEqual(cash.projection.period_dim, 'month')
        self.assertEqual(str(cash.projection.noi), 'noi')
        self.assertEqual(str(cash.reserves), 'replacement_reserve_deposit')
        self.assertEqual(str(cash.amount), 'ncf')
        self.assertEqual(len(cash.projection.income_lines), 4)
        self.assertEqual(len(cash.projection.expense_lines), 2)
        for month in months(self.result):
            self.assertAlmostEqual(self.v('ncf', month),
                                  self.v('noi', month) - self.v('replacement_reserve_deposit', month), delta=TOL)

    def test_debt_and_sale_consume_the_supplied_cash_flow_and_existing_windows(self):
        from balto_valuation.model import POLICY
        m = Model('alternative-reserves', '1.0.0', POLICY)
        deal = example_deal()
        timeline.build(m, deal)
        rents.build(m, deal)
        operating = operations.build(m, deal)
        cash = build_operating_cash_flow(m, projection=operating.projection,
            reserves=ref('replacement_reserve_deposit') * 2, name='alternative.before_debt')
        capital_reserve = capital.build_budget(m, deal)
        senior = capital.build_senior(m, deal, cash)
        refi = capital.build_refi(m, deal, cash)
        for tranche in deal.tranches:
            capital.build_tranche(m, tranche)
        ledger.build(m, deal, cash, senior=senior, refi=refi, capital_reserve=capital_reserve)
        inputs = {name: value for name, value in example_inputs().items()
                  if name in m.variables and m.variables[name].kind == 'input'}
        result = evaluate(m, inputs)
        def total_window(start, end):
            return sum(result.values['alternative.before_debt'][(month,)] for month in range(start, end + 1))
        self.assertAlmostEqual(result.value('senior.sizing_ncf'), total_window(1, 12), delta=TOL)
        self.assertAlmostEqual(result.value('refi.trailing_ncf'), total_window(19, 30), delta=TOL)
        self.assertAlmostEqual(result.value('sale.forward_ncf'), total_window(61, 72), delta=TOL)
        self.assertAlmostEqual(result.value('sale.price'), total_window(61, 72) / Decimal(example_inputs()['exit_cap_rate']), delta=TOL)
        self.assertLess(result.value('senior.sizing_ncf'), self.v('senior.sizing_ncf'))
        for month in (0, 1, 30, 60, 61):
            self.assertAlmostEqual(result.values['cash_from_operations'][(month,)],
                result.values['alternative.before_debt'][(month,)] * result.values['owned'][(month,)], delta=TOL)

    def test_rental_income_is_occupied_units_at_their_rents(self):
        r = self.result
        for m in months(r):
            expected = sum((r.values["occupied_classic"][(c, m)] * r.values["rent_classic"][(c, m)]
                            + r.values["occupied_renovated"][(c, m)] * r.values["rent_renovated"][(c, m)])
                           for c in ("1br_mkt", "2br_mkt", "1br_60", "2br_60", "2br_hap"))
            if m > 0:
                self.assertAlmostEqual(r.values["rental_income_total"][(m,)], expected, delta=TOL)

    def test_renovation_follows_turnover_at_the_stated_pace(self):
        # Units start only as they turn over, so a scope converges on its total
        # rather than finishing on a date.
        r = self.result
        starts = [r.values["reno_starts"][("1br_mkt", m)] for m in months(r)]
        self.assertTrue(17 < sum(starts[:61]) < sum(starts) <= 20)
        self.assertTrue(all(s <= 2 for s in starts))
        self.assertEqual(starts[0] + starts[1], 0)  # renovation starts in month 2
        self.assertAlmostEqual(self.v("reno_spend", 2),
                               starts[2] * 18000 + r.values["reno_starts"][("2br_mkt", 2)] * 22000, delta=TOL)

    def test_a_restricted_rent_never_exceeds_its_limit_and_loses_the_premium(self):
        r = self.result
        for m in months(r):
            limit = r.values["rent_limit"][("1br_60", m)]
            self.assertLessEqual(r.values["classic_target"][("1br_60", m)], limit)
            self.assertLessEqual(r.values["rent_classic"][("1br_60", m)], limit + TOL)
        # 2 BR at 60% AMI is above its net limit at closing, and is reported.
        test = r.tests["restricted_rent_within_limit"]
        self.assertFalse(test["passed"])
        self.assertEqual(test["firstBreach"], ["2br_60"])
        self.assertEqual(test["worstBreach"]["shortfall"], Decimal(1740 - (1824 - 120)))

    def test_a_contract_rent_steps_by_ocaf_on_each_anniversary(self):
        self.assertEqual(self.v("classic_target", "2br_hap", 12), 1900)
        self.assertEqual(self.v("classic_target", "2br_hap", 13), Decimal(1900) * Decimal("1.025"))

    def test_renewals_are_limited_by_the_rent_cap(self):
        r = run(renewal_increase="0.12", rent_cap="0.05")
        self.assertAlmostEqual(r.values["renewal_factor"][(1,)], Decimal("1.05") ** (Decimal(1) / 12), delta=TOL)

    def test_oregon_assessed_value_is_the_lesser_of_market_and_maximum(self):
        self.assertEqual(self.v("assessed_value", 1), 6400000)
        self.assertEqual(self.v("assessed_value", 13), Decimal(6400000) * Decimal("1.03"))
        inputs = {k: v for k, v in example_inputs().items() if k != "tax_max_assessed_value"}
        wa = evaluate(build_model(replace(example_deal(), tax_method="wa_market")), inputs)
        self.assertEqual(wa.values["assessed_value"][(1,)], 9800000)

    def test_sources_equal_uses_and_the_senior_loan_takes_the_lesser_constraint(self):
        self.assertAlmostEqual(self.v("debt_at_close") + self.v("equity_at_close"), self.v("total_uses"), delta=TOL)
        self.assertEqual(self.v("senior.amount"), min(self.v("senior.ltv_amount"), self.v("senior.dscr_amount")))

    def test_the_senior_loan_is_retired_by_the_refinance(self):
        r = self.result
        self.assertGreater(r.values["senior.payoff"][(30,)], 0)
        self.assertEqual(r.values["senior.balance"][(30,)], 0)
        self.assertEqual(r.values["refi.funding"][(30,)], r.values["refi.amount"][()])
        self.assertEqual(r.values["refi.balance"][(60,)], 0)
        no_refi = run(refi_included=0)
        self.assertEqual(no_refi.values["refi.amount"][()], 0)
        self.assertGreater(no_refi.values["senior.payoff"][(60,)], 0)

    def test_every_distribution_dollar_goes_to_the_lp_or_the_gp(self):
        r = self.result
        for m in months(r):
            dist = r.values["equity_distributions"][(m,)]
            self.assertAlmostEqual(r.values["lp_distribution"][(m,)] + r.values["gp_distribution"][(m,)], dist,
                                   delta=TOL)
            self.assertAlmostEqual(r.values["tier_1"][(m,)] + r.values["tier_2"][(m,)] + r.values["tier_3"][(m,)],
                                   dist, delta=TOL)
            self.assertGreaterEqual(dist, 0)

    def test_the_pref_account_uses_the_xirr_convention(self):
        # Once the pref account is paid off, the LP's tier-1 flows have zero
        # present value at the pref rate, discounted exactly as XIRR discounts.
        r, deal = self.result, example_deal()
        model = build_model(deal)
        dates = {i.key: Decimal(i.attrs["date"]) for i in model.dimensions["month"].items}
        rate, lp = Decimal("0.08"), Decimal("0.9")
        self.assertEqual(r.values["pref.balance"][(60,)], 0)
        npv = sum(((lp * r.values["tier_1"][(m,)] - r.values["lp_contribution"][(m,)])
                   / (1 + rate) ** ((dates[m] - dates[0]) / 365)) for m in range(61))
        self.assertAlmostEqual(npv, 0, delta=Decimal("1e-6"))

    def test_the_promote_is_earned_only_above_the_hurdle(self):
        metrics = self.result.metrics
        self.assertGreater(self.v("gp_promote_total"), 0)
        self.assertGreater(metrics["lp_irr"]["rate"], Decimal("0.14"))
        self.assertGreater(metrics["gp_irr"]["rate"], metrics["lp_irr"]["rate"])
        poor = run(exit_cap_rate="0.075")
        self.assertAlmostEqual(poor.values["gp_promote_total"][()], 0, delta=TOL)
        self.assertEqual(poor.metrics["lp_irr"]["rate"], poor.metrics["gp_irr"]["rate"])

    def test_results_report_tests_without_failing_the_run(self):
        self.assertTrue(self.result.tests["set_aside"]["passed"])
        self.assertTrue(self.result.tests["fully_funded"]["passed"])
        short = run(set_aside_units=25)
        self.assertFalse(short.tests["set_aside"]["passed"])

    def test_a_refinance_after_the_sale_is_refused(self):
        with self.assertRaises(EngineError) as caught:
            run(refi_month=70)
        self.assertEqual(caught.exception.code, "REFI_AFTER_SALE")

    def test_the_catch_up_brings_the_gp_promote_to_its_share_of_profit(self):
        r = run(catch_up_share=1)
        caught_up = 0
        for m in months(r):
            tcu, room = r.values["tier_catch_up"][(m,)], r.values["equity_distributions"][(m,)] - r.values["tier_1"][(m,)]
            if 0 < tcu < room:
                # Catch-up ends this month: the GP's promote is exactly promote_1 of profit so far.
                gp_share = 1 - Decimal("0.9")
                promote = r.values["wf.promote_before"][(m,)] + (1 - gp_share) * tcu
                profit = r.values["wf.profit_after_tier_1"][(m,)] + tcu
                self.assertAlmostEqual(promote, Decimal("0.2") * profit, delta=TOL)
                caught_up += 1
        self.assertEqual(caught_up, 1)
        self.assertGreater(r.metrics["gp_irr"]["rate"], self.result.metrics["gp_irr"]["rate"])
        for m in months(r):
            self.assertAlmostEqual(r.values["lp_distribution"][(m,)] + r.values["gp_distribution"][(m,)],
                                   r.values["equity_distributions"][(m,)], delta=TOL)

    def test_reserves_close_at_sale_and_all_transfers_reconcile(self):
        r = run(working_capital=100000, capex_start_month={'exterior': 59, 'systems': 30})
        sale = int(r.value('sale_month'))
        for prefix, balance in (('operating_reserve', 'operating_reserve.balance'),
                                ('capital_reserve', 'capex_reserve')):
            self.assertEqual(r.values[balance][(sale,)], 0)
            for idx, closing in r.values[balance].items():
                v = lambda name: r.values[prefix + '.' + name][idx]
                self.assertAlmostEqual(closing, v('opening') + v('deposits') - v('draw') - v('released'), delta=TOL)
                if idx[0] > sale:
                    self.assertEqual(closing, 0)
                    self.assertEqual(v('released'), 0)
        self.assertGreater(r.values['capital_reserve.released'][(sale,)], 0)
        self.assertAlmostEqual(r.values['reserves_released'][(sale,)],
            r.values['capital_reserve.released'][(sale,)] + r.values['operating_reserve.released'][(sale,)], delta=TOL)
        self.assertTrue(all(abs(x) < TOL for x in r.values['capital_reserve.unfunded'].values()))

    def test_operating_shortfalls_draw_the_reserve_before_calling_equity(self):
        funded = run(opex_fixed={"audit": 450000}, working_capital=100000)
        shortfall = sum(funded.values["operating_shortfall"].values())
        self.assertGreater(shortfall, 0)
        drawn = sum(funded.values["operating_reserve.draw"].values())
        self.assertAlmostEqual(drawn, min(shortfall, Decimal(100000)), delta=TOL)
        calls = sum(funded.values["operating_capital_call"].values())
        self.assertAlmostEqual(calls, shortfall - drawn, delta=TOL)
        sale = int(funded.value("sale_month"))
        self.assertAlmostEqual(funded.values["reserves_released"][(sale,)],
                               funded.values["capital_reserve.released"][(sale,)] + 100000 - drawn, delta=TOL)

    def test_a_phase_funded_at_an_event_is_paid_from_that_event(self):
        # The example's building-systems phase ($150,000 plus 10% contingency) is paid at the month-30 refinance.
        without = run(capex_amount={**example_inputs()["capex_amount"], "boilers": 0})
        self.assertEqual(self.v("deferred_capex_budget"), 165000)
        for name in ("capital_event_cash", "unlevered_cash_flow"):
            self.assertAlmostEqual(self.v(name, 30), without.values[name][(30,)] - 165000, delta=TOL)
        self.assertEqual(self.v("equity_at_close"), without.value("equity_at_close"))

    def test_a_phase_funded_at_closing_is_spent_evenly_from_the_reserve(self):
        self.assertEqual(self.v("capex_hard", "exterior"), 382000)
        self.assertEqual(self.v("capex_phase_total", "exterior"), 401100)
        for m in range(1, 13):
            self.assertAlmostEqual(self.v("property_capex_spend", m), Decimal(401100) / 12, delta=TOL)
        self.assertEqual(self.v("property_capex_spend", 13), 0)
        self.assertEqual(self.v("capex_budget"), self.v("reno_budget") + 401100)

    def test_capital_fee_bases_and_ownership_stop_spending_after_sale(self):
        result = run(capex_gc_rate={'exterior': '.12', 'systems': '.08'},
                     capex_gc_fee_rate={'exterior': '.07', 'systems': '.11'},
                     capex_contingency_rate={'exterior': '.13', 'systems': '.15'},
                     capex_start_month={'exterior': 59, 'systems': 30},
                     capex_months={'exterior': 3, 'systems': 1})
        for phase in ('exterior', 'systems'):
            hard = result.values['capex_hard'][(phase,)]
            conditions = result.values['capex_gc'][(phase,)]
            fee = result.values['capex_gc_fee'][(phase,)]
            self.assertEqual(fee, (hard + conditions) * Decimal('.07' if phase == 'exterior' else '.11'))
            self.assertEqual(result.values['capex_contingency'][(phase,)],
                             (hard + conditions + fee) * Decimal('.13' if phase == 'exterior' else '.15'))
        total = result.values['capex_phase_total'][('exterior',)]
        for month in (59, 60):
            self.assertAlmostEqual(result.values['property_capex_spend'][(month,)], total / 3, delta=TOL)
        self.assertEqual(result.values['property_capex_spend'][(61,)], 0)
        self.assertEqual(result.values['deferred_capex_spend'][(30,)],
                         result.values['capex_phase_total'][('systems',)])

    def test_capital_duration_keeps_acquisition_validation(self):
        for duration, code in ((0, 'INPUT_OUT_OF_RANGE'), ('1.5', 'EVENT_NOT_WHOLE')):
            with self.subTest(duration=duration):
                with self.assertRaises(EngineError) as caught:
                    run(capex_months={'exterior': duration, 'systems': 1})
                self.assertEqual(caught.exception.code, code)

    def test_closing_costs_by_method_and_category(self):
        self.assertEqual(self.v("closing_cost", "acquisition_fee"), Decimal("96000"))
        self.assertAlmostEqual(self.v("closing_cost", "origination"), self.v("senior.amount") * Decimal("0.01"),
                               delta=TOL)
        self.assertEqual(self.v("acquisition_costs"), 155000)
        self.assertAlmostEqual(self.v("closing_costs"), self.v("acquisition_costs") + self.v("financing_costs")
                               + self.v("acquisition_fee"), delta=TOL)
        # Financing costs are not a cost of the unlevered investment.
        self.assertAlmostEqual(-self.v("unlevered_cash_flow", 0),
                               9600000 + self.v("acquisition_costs") + self.v("acquisition_fee"), delta=TOL)

    def test_the_pro_forma_cases(self):
        def pf(name, case):
            return self.v(f"pf.{name}", case)
        units = self.v("total_units")
        # In place: occupied units at in-place rents.
        self.assertEqual(pf("rental_income", "in_place"),
                         12 * sum(self.v("occupied_at_close", c) * self.v("in_place_rent", c)
                                  for c in ("1br_mkt", "2br_mkt", "1br_60", "2br_60", "2br_hap")))
        # Year 1 is the projection's first hold year.
        self.assertAlmostEqual(pf("noi", "year_1"), self.v("year_1_noi"), delta=TOL)
        self.assertAlmostEqual(pf("egi", "year_1"), self.v("annual.egi", 1), delta=TOL)
        # Stabilized: no physical vacancy, the floor as economic vacancy.
        self.assertEqual(pf("vacancy", "stabilized"), 0)
        self.assertAlmostEqual(pf("vacancy_floor", "stabilized"), -Decimal("0.05") * pf("gpr", "stabilized"),
                               delta=TOL)
        # Exit year: the cash flow the sale is priced on.
        self.assertAlmostEqual(pf("ncf", "exit_year"), self.v("sale.forward_ncf"), delta=TOL)
        for case in ("in_place", "year_1", "stabilized", "exit_year"):
            self.assertAlmostEqual(pf("noi", case), pf("egi", case) - pf("opex_total", case), delta=TOL)
            self.assertAlmostEqual(pf("noi_per_unit", case) * units, pf("noi", case), delta=TOL)

    def test_held_in_place_rents_grow_as_renewals_and_never_mark_to_market(self):
        held = run(mark_to_market=0)
        for m in range(1, 25):
            carried = min(held.values["rent_classic"][("1br_mkt", m - 1)] * held.values["renewal_factor"][(m,)],
                          held.values["classic_target"][("1br_mkt", m)])
            self.assertAlmostEqual(held.values["rent_classic"][("1br_mkt", m)], carried, delta=TOL)
        self.assertGreater(held.values["annual.loss_to_lease_total"][(3,)],
                           self.result.values["annual.loss_to_lease_total"][(3,)])
        # The pro forma's stabilized case keeps the units occupied at closing at their in-place rents.
        gap = sum(min(held.values["occupied_at_close"][(c,)], held.values["units"][(c,)]
                      - held.values["reno_scope"][(c,)])
                  * max(held.values["classic_target"][(c, 0)] - held.values["in_place_rent"][(c,)], 0)
                  for c in ("1br_mkt", "2br_mkt"))
        gap += sum(held.values["occupied_at_close"][(c,)]
                   * max(held.values["classic_target"][(c, 0)] - held.values["in_place_rent"][(c,)], 0)
                   for c in ("1br_60", "2br_60"))
        self.assertAlmostEqual(held.values["pf.loss_to_lease"][("stabilized",)], -12 * gap, delta=TOL)
        self.assertEqual(self.v("pf.loss_to_lease", "stabilized"), 0)

    def test_an_unused_refinance_month_does_not_constrain_the_sale(self):
        r = run(refi_included=0, refi_month=70)
        self.assertEqual(r.value("refi.amount"), 0)

    def test_event_months_must_be_whole(self):
        with self.assertRaises(EngineError) as caught:
            run(sale_month="60.5")
        self.assertEqual(caught.exception.code, "EVENT_NOT_WHOLE")
        with self.assertRaises(EngineError):
            run(refi_included="0.5")

    def test_a_contract_rent_is_the_contract_schedule_whatever_the_renewal_terms(self):
        r = run(renewal_increase=0, turnover=0)
        for m in (13, 60):
            self.assertEqual(r.values["rent_classic"][("2br_hap", m)], r.values["classic_target"][("2br_hap", m)])
        self.assertEqual(r.values["rent_classic"][("2br_hap", 13)], Decimal(1900) * Decimal("1.025"))

    def test_cash_flow_that_cannot_cover_debt_supports_no_loan(self):
        r = run(opex_fixed={"audit": 1000000})
        self.assertLess(r.value("senior.sizing_ncf"), 0)
        self.assertEqual(r.value("senior.amount"), 0)
        self.assertTrue(all(x == 0 for x in r.values["senior.debt_service"].values()))

    def test_a_zero_rate_loan_amortizes_straight_line(self):
        r = run(**{"refi.rate": 0})
        self.assertAlmostEqual(r.value("refi.payment_constant"), Decimal(1) / 360, delta=Decimal("1e-20"))

    def test_sale_year_coverage_counts_only_owned_months(self):
        r = run(sale_month=31)
        year_3 = sum(r.values["ncf"][(m,)] for m in range(25, 32))
        self.assertAlmostEqual(r.values["annual.dscr"][(3,)],
                               year_3 / r.values["annual.senior_debt_service"][(3,)], delta=TOL)

    def test_closing_is_a_month_end(self):
        from datetime import date
        with self.assertRaisesRegex(ValueError, "last day of a month"):
            replace(example_deal(), closing=date(2026, 12, 30))


class TrancheModeTest(unittest.TestCase):

    def deal_with(self, mode):
        return replace(example_deal(), tranches=(Tranche("sub", "Subordinate loan", mode),))

    def inputs(self, mode):
        out = {k: v for k, v in example_inputs().items() if not k.startswith(("city_loan.", "seller_note."))}
        out.update({"sub.amount": 1000000, "sub.rate": "0.06"})
        if mode == "cash_sweep":
            out["sub.sweep_share"] = "0.5"
        return out

    def run_mode(self, mode):
        return evaluate(build_model(self.deal_with(mode)), self.inputs(mode))

    def test_accrue_pays_nothing_and_compounds_to_sale(self):
        r = self.run_mode("accrue")
        self.assertEqual(sum(r.values["sub.payment"].values()), 0)
        expected = Decimal(1000000) * (1 + Decimal("0.06") / 12) ** 60
        self.assertAlmostEqual(r.values["sub.payoff"][(60,)], expected, delta=TOL)

    def test_scheduled_pays_current_interest(self):
        r = self.run_mode("scheduled")
        self.assertEqual(r.values["sub.interest_paid"][(5,)], Decimal(1000000) * Decimal("0.06") / 12)
        self.assertEqual(r.values["sub.payoff"][(60,)], 1000000)

    def test_available_cash_pays_what_cash_allows(self):
        r = self.run_mode("available_cash")
        for m in range(1, 61):
            self.assertLessEqual(r.values["sub.interest_paid"][(m,)], r.values["sub.cash_available"][(m,)])

    def test_a_sweep_pays_interest_then_principal_from_its_share(self):
        r = self.run_mode("cash_sweep")
        for m in range(1, 61):
            paid = r.values["sub.payment"][(m,)]
            self.assertLessEqual(paid, Decimal("0.5") * r.values["sub.cash_available"][(m,)] + TOL)
        self.assertLess(r.values["sub.balance"][(59,)], 1000000)


if __name__ == "__main__":
    unittest.main()
