from decimal import Decimal as D
import unittest
from balto_model_engine import EngineError, evaluate
from balto_development.seattle import build_model
from balto_development.seattle_example import example_deal, example_inputs, scenario_inputs

TOL = D('0.000001')


def run(inputs):
    return evaluate(build_model(example_deal()), inputs)


class SeattleMhaTest(unittest.TestCase):
    def test_mha_payment_is_rate_times_chargeable_area_paid_as_a_dated_project_cost(self):
        r = run(scenario_inputs(mfte=False, mha='payment'))
        self.assertEqual(r.model_id, 'seattle-multifamily-development')
        self.assertEqual(r.value('mha.payment'), D('2526420'))
        self.assertEqual(r.value('mha.monthly_payment', month='m1'), D('2526420'))
        self.assertEqual(r.value('mha.monthly_payment', month='m2'), 0)
        none = run(scenario_inputs(mfte=False, mha='none'))
        self.assertEqual(none.value('mha.payment'), 0)
        self.assertEqual(r.value('project_cost') - none.value('project_cost'), D('2526420'))
        self.assertEqual(r.value('total_project_spending'), r.value('project_cost'))
        # Payment keeps every unit at market rent.
        self.assertEqual(r.value('rental_income', month='m40'), none.value('rental_income', month='m40'))
        self.assertTrue(all(t['passed'] for t in r.tests.values()), r.tests)

    def test_mha_performance_restricts_units_and_pays_only_the_fractional_unit(self):
        r = run(scenario_inputs(mfte=False, mha='performance'))
        # 120 units x 9% = 10.8 required; 10 provided; 0.8 paid at the full-payment rate.
        self.assertEqual(r.value('mha.required_units'), D('10.8'))
        self.assertAlmostEqual(r.value('mha.payment'), D('2526420') * D('0.8') / D('10.8'), delta=TOL)
        self.assertEqual(r.value('units.market', unit_type='one'), 46)
        self.assertAlmostEqual(r.value('rent.mha', unit_type='two', month='m0'), D('1935'), delta=TOL)
        self.assertLess(r.value('stabilized_noi'), run(scenario_inputs(mfte=False, mha='payment')).value('stabilized_noi'))
        self.assertTrue(r.tests['mha_performance']['passed'])
        short = run({**scenario_inputs(mfte=False, mha='performance'), 'mha_units': {'studio': 4, 'one': 3, 'two': 2}})
        self.assertFalse(short.tests['mha_performance']['passed'])

    def test_mha_performance_under_two_required_units_needs_two_units(self):
        small = {**scenario_inputs(mfte=False, mha='performance'), 'mha_performance_rate': '0.01'}
        self.assertFalse(run({**small, 'mha_units': {'studio': 1, 'one': 0, 'two': 0}}).tests['mha_performance']['passed'])
        two = run({**small, 'mha_units': {'studio': 2, 'one': 0, 'two': 0}})
        self.assertTrue(two.tests['mha_performance']['passed'])
        self.assertEqual(two.value('mha.payment'), 0)


class SeattleMfteTest(unittest.TestCase):
    def test_mfte_exempts_residential_improvements_for_twelve_years_and_restricts_rents(self):
        on, off = run(scenario_inputs(mfte=True, mha='payment')), run(scenario_inputs(mfte=False, mha='payment'))
        self.assertEqual(on.value('mfte.exempt', month='m23'), 0)
        self.assertEqual(on.value('mfte.exempt', month='m24'), 1)
        self.assertEqual(on.value('tax.mfte_exemption', month='m30'), on.value('tax.improvements', month='m30'))
        self.assertEqual(on.value('tax.land', month='m30'), off.value('tax.land', month='m30'))
        self.assertAlmostEqual(on.value('tax.annual', month='m30'), on.value('tax.land', month='m30'), delta=TOL)
        self.assertEqual(off.value('tax.mfte_exemption', month='m30'), 0)
        self.assertLess(on.value('rental_income', month='m40'), off.value('rental_income', month='m40'))
        self.assertEqual(on.value('units.market', unit_type='studio'), 32)
        partial = run({**scenario_inputs(mfte=True, mha='payment'), 'residential_improvement_share': '0.9'})
        self.assertAlmostEqual(partial.value('tax.mfte_exemption', month='m30'), on.value('tax.improvements', month='m30') * D('0.9'), delta=TOL)

    def test_program_seven_set_aside_follows_the_family_unit_mix(self):
        r = run(scenario_inputs(mfte=True, mha='payment'))
        self.assertEqual(r.value('mfte.set_aside_rate'), D('0.20'))
        self.assertTrue(r.tests['mfte_set_aside']['passed'])
        studios = run({**scenario_inputs(mfte=True, mha='payment'), 'bedrooms': {'studio': 0, 'one': 1, 'two': 1}})
        self.assertEqual(studios.value('mfte.set_aside_rate'), D('0.25'))
        self.assertFalse(studios.tests['mfte_set_aside']['passed'])
        self.assertTrue(run(scenario_inputs(mfte=False, mha='payment')).tests['mfte_set_aside']['passed'])

    def test_mfte_and_mha_units_are_different_units(self):
        both = run(scenario_inputs(mfte=True, mha='performance'))
        self.assertEqual(both.value('units.market', unit_type='studio'), 40 - 8 - 4)
        too_many = {**scenario_inputs(mfte=True, mha='performance'), 'mha_units': {'studio': 33, 'one': 4, 'two': 2}}
        with self.assertRaises(EngineError) as caught:
            run(too_many)
        self.assertEqual(caught.exception.code, 'AFFORDABLE_UNITS')

    def test_sale_capitalizes_noi_without_mfte_and_adds_the_remaining_exemption_value(self):
        on, off = run(scenario_inputs(mfte=True, mha='payment')), run(scenario_inputs(mfte=False, mha='payment'))
        self.assertAlmostEqual(on.value('sale_forward_noi_without_mfte'), off.value('sale_forward_noi'), delta=TOL)
        self.assertEqual(on.value('mfte.remaining_months'), 24 + 144 - 84)
        monthly, rate = on.value('mfte.forward_monthly_benefit'), D('0.07') / 12
        self.assertGreater(monthly, 0)
        annuity = monthly * (1 - (1 + rate) ** -84) / rate
        self.assertAlmostEqual(on.value('mfte.remaining_value'), annuity, delta=D('0.01'))
        self.assertAlmostEqual(on.value('sale_gross_value'), off.value('sale_forward_noi') / D('0.05') + on.value('mfte.remaining_value'), delta=TOL)
        self.assertEqual(off.value('mfte.remaining_value'), 0)
        self.assertAlmostEqual(off.value('sale_gross_value'), off.value('sale_forward_noi') / D('0.05'), delta=TOL)
        self.assertTrue(all(t['passed'] for t in on.tests.values()), on.tests)
        self.assertGreater(on.metrics['levered_irr']['rate'], off.metrics['levered_irr']['rate'])

    def test_toggles_must_be_whole_flags_and_exemption_follows_completion(self):
        for change, code in (({'mfte_elected': '0.5'}, 'EVENT_NOT_WHOLE'), ({'mfte_start_month': 19}, 'EVENT_ORDER'),
                             ({'mha_payment_month': 21}, 'EVENT_ORDER')):
            with self.subTest(code=code), self.assertRaises(EngineError) as caught:
                run({**example_inputs(), **change})
            self.assertEqual(caught.exception.code, code)


class SeattleOperatingCostTest(unittest.TestCase):
    def test_owner_pays_water_sewer_and_garbage_and_bills_back_the_recovery_share(self):
        r = run(example_inputs())
        v = lambda name, month='m40': r.value(name, month=month)
        self.assertGreater(v('utility.wsg_expense'), 0)
        self.assertAlmostEqual(v('utility.wsg_recovery'), v('utility.wsg_expense') * D('0.80'), delta=TOL)
        self.assertAlmostEqual(v('total_income'), v('rental_income') + v('utility.wsg_recovery'), delta=TOL)
        self.assertEqual(v('utility.wsg_expense', 'm10'), 0)
        full = run({**example_inputs(), 'wsg_recovery_rate': 1})
        # Stabilized occupancy is 95% of homes.
        stab = D('40') * 110 + D('50') * 120 + D('30') * 200
        growth = D('1.03') ** (D(32) / 12)
        self.assertAlmostEqual(full.value('stabilized_noi') - r.value('stabilized_noi'), stab * D('0.95') * 12 * D('0.20') * growth, delta=D('0.01'))

    def test_mha_homes_carry_the_city_monitoring_fee_and_manager_compliance_cost_mfte_only_compliance(self):
        perf = run(scenario_inputs(mfte=False, mha='performance'))
        cheaper = run({**scenario_inputs(mfte=False, mha='performance'), 'mha_compliance_cost': 0})
        growth = D('1.03') ** (D(32) / 12)
        self.assertAlmostEqual(cheaper.value('stabilized_noi') - perf.value('stabilized_noi'), 10 * D('150') * growth, delta=D('0.01'))
        mfte = run(scenario_inputs(mfte=True, mha='none'))
        self.assertAlmostEqual(run({**scenario_inputs(mfte=True, mha='none'), 'mha_monitoring_fee': 0}).value('stabilized_noi'),
                               mfte.value('stabilized_noi'), delta=TOL)


class SeattlePolicyOutcomesTest(unittest.TestCase):
    def test_policy_outcomes_count_restricted_homes_rent_savings_and_public_cost(self):
        r = run(scenario_inputs(mfte=True, mha='performance'))
        v = r.value
        self.assertEqual((v('policy.mfte_homes'), v('policy.mha_homes'), v('policy.restricted_homes')), (24, 10, 34))
        self.assertAlmostEqual(v('policy.restricted_share'), D(34) / 120, delta=TOL)
        expected = sum((D(n) * (v('rent.market_stabilized', unit_type=u) - v('rent.mfte_stabilized', unit_type=u)) for u, n in (('studio', 8), ('one', 10), ('two', 6))), D(0)) * 12
        self.assertAlmostEqual(v('policy.mfte_rent_savings'), expected, delta=TOL)
        # First full exempt year is the stabilization month (32), after the exemption start (24).
        exemption = D('32800000') * D('1.03') ** (D(32) / 12) * D('0.00990845')
        self.assertAlmostEqual(v('policy.mfte_exemption_annual'), exemption, delta=D('0.01'))
        first = D('32800000') * D('1.03') ** 2 * D('0.00990845')
        self.assertAlmostEqual(v('policy.mfte_exemption_term'), first * (D('1.03') ** 12 - 1) / D('0.03'), delta=D('0.01'))
        self.assertAlmostEqual(v('policy.mfte_savings_per_exemption_dollar'), v('policy.mfte_rent_savings') / exemption, delta=D('0.000001'))
        self.assertEqual(v('policy.city_mha_payment'), v('mha.payment'))
        none = run(scenario_inputs(mfte=False, mha='payment'))
        for name in ('policy.restricted_homes', 'policy.rent_savings', 'policy.mfte_exemption_annual', 'policy.mfte_exemption_term',
                     'policy.mfte_savings_per_exemption_dollar', 'policy.monthly_savings_per_home'):
            self.assertEqual(none.value(name), 0, name)
