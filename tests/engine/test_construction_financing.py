"""Construction financing behavior through the shared declaration interface."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, EngineError, evaluate, ref
from balto_model_engine.construction_financing import declare_construction_financing


def schedule(values, **terms):
    model = Model('synthetic-construction', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
    model.dimension(Dimension('facility', [Item('bond'), Item('bridge')]))
    model.dimension(Dimension('month', [Item(i, period=i) for i in range(5)]))
    def given(name, unit, dims=(), low=0, high=None):
        model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
    if 'repayment_amount' in terms:
        model.input('reviewed_payoff', unit='USD', dims=('facility',))
    declare_construction_financing(model, given, draw_end_period=terms.pop('draw_end_period', 3),
                                   settlement_period=terms.pop('settlement_period', 3), **terms)
    return evaluate(model, values)


def inputs():
    return {'construction.commitment': {'bond': '200', 'bridge': '100'},
            'construction.annual_rate': {'bond': '.12', 'bridge': '.06'},
            'construction.draw': {(f, m): ('100' if f == 'bond' and m == 0 else
                                           '50' if m == 1 else '0')
                                  for f in ('bond', 'bridge') for m in range(5)}}


class ConstructionFinancingTest(unittest.TestCase):
    def test_interest_timing_elections_are_strict_and_capitalization_boundaries_are_explicit(self):
        for lag in (True, False, '1', 1.0, -1, 13, None):
            with self.subTest(lag=lag), self.assertRaises(ModelDefinitionError):
                schedule(inputs(), interest_payment_lag=lag)
        for cutoff in (True, '1', 1.0, -1, 6):
            with self.subTest(cutoff=cutoff), self.assertRaises(ModelDefinitionError):
                schedule(inputs(), capitalization_end_period=cutoff)
        for settlement in (True, '4', 4.0, 2, 5):
            with self.subTest(settlement=settlement), self.assertRaises(ModelDefinitionError):
                schedule(inputs(), interest_settlement_period=settlement)
        none_capitalized = schedule(inputs(), capitalization_end_period=0)
        all_capitalized = schedule(inputs(), capitalization_end_period=5)
        default = schedule(inputs())
        for month in range(5):
            self.assertEqual(none_capitalized.value('construction.capitalized_interest', facility='bond', month=month), Decimal('0'))
            self.assertEqual(all_capitalized.value('construction.capitalized_interest', facility='bond', month=month),
                             default.value('construction.interest', facility='bond', month=month))
            self.assertEqual(default.value('construction.ending_interest_payable', facility='bond', month=month), Decimal('0'))
        longest_lag = schedule(inputs(), interest_payment_lag=12)
        self.assertEqual(longest_lag.value('construction.interest_owed', facility='bond'), Decimal('4'))
        self.assertEqual(sum(longest_lag.value('construction.cash_interest', facility='bond', month=m) for m in range(5)), Decimal('0'))

    def test_forecast_tail_remains_visible_until_explicit_cash_settlement(self):
        values = inputs()
        values['reviewed_payoff'] = {'bond': '100', 'bridge': '50'}
        run = schedule(values, repayment_amount=ref('reviewed_payoff'), interest_payment_lag=1)
        self.assertEqual(run.value('construction.interest_owed', facility='bond'), Decimal('.5'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=4), Decimal('.5'))
        accrued = sum(run.value('construction.interest', facility='bond', month=m) for m in range(5))
        paid = sum(run.value('construction.cash_interest', facility='bond', month=m) for m in range(5))
        self.assertEqual(accrued, paid + run.value('construction.interest_owed', facility='bond'))
        settled = schedule(values, repayment_amount=ref('reviewed_payoff'), interest_payment_lag=1,
                           interest_settlement_period=4)
        self.assertEqual(settled.value('construction.cash_interest', facility='bond', month=4), Decimal('1'))
        self.assertEqual(settled.value('construction.interest_owed', facility='bond'), Decimal('0'))
        with self.assertRaises(EngineError) as err:
            schedule(values, repayment_amount=ref('reviewed_payoff'), interest_payment_lag=1,
                     interest_settlement_period=3)
        self.assertEqual(err.exception.code, 'INTEREST_AFTER_SETTLEMENT')

    def test_explicit_interest_settlement_pays_accumulated_tail_once(self):
        run = schedule(inputs(), interest_payment_lag=3, interest_settlement_period=3)
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=2), Decimal('0'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=3), Decimal('4'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=4), Decimal('0'))
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=3), Decimal('0'))
        self.assertEqual(run.value('construction.interest_owed', facility='bond'), Decimal('0'))
        self.assertEqual(sum(run.value('construction.cash_interest', facility='bond', month=m) for m in range(5)), Decimal('4'))

    def test_cash_payment_lag_carries_accrual_and_pays_tail_after_capitalization_cutoff(self):
        run = schedule(inputs(), capitalization_end_period=1, interest_payment_lag=1)
        expected_cash = (Decimal('0'), Decimal('1'), Decimal('1.5'), Decimal('1.5'), Decimal('0'))
        for month, cash in enumerate(expected_cash):
            self.assertEqual(run.value('construction.cash_interest', facility='bond', month=month), cash)
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=0), Decimal('1'))
        self.assertEqual(run.value('construction.opening_interest_payable', facility='bond', month=1), Decimal('1'))
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=2), Decimal('1.5'))
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=4), Decimal('0'))
        self.assertEqual(run.value('construction.operating_interest', facility='bond', month=2), Decimal('1.5'))
        self.assertEqual(sum(run.value('construction.cash_interest', facility='bond', month=m) for m in range(5)),
                         sum(run.value('construction.interest', facility='bond', month=m) for m in range(5)))

    def test_capitalization_cutoff_classifies_interest_once_without_increasing_principal(self):
        run = schedule(inputs(), capitalization_end_period=1)
        self.assertEqual(run.value('construction.capitalized_interest', facility='bond', month=0), Decimal('1'))
        self.assertEqual(run.value('construction.capitalized_interest', facility='bond', month=1), Decimal('0'))
        self.assertEqual(run.value('construction.operating_interest', facility='bond', month=1), Decimal('1.5'))
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=2), Decimal('150'))
        for facility in ('bond', 'bridge'):
            for month in range(5):
                self.assertEqual(run.value('construction.interest', facility=facility, month=month),
                                 run.value('construction.capitalized_interest', facility=facility, month=month)
                                 + run.value('construction.operating_interest', facility=facility, month=month))
                self.assertEqual(run.value('construction.cash_interest', facility=facility, month=month),
                                 run.value('construction.interest', facility=facility, month=month))

    def test_shared_owner_preserves_caller_dimensions_and_supports_other_model_names(self):
        model = Model('synthetic-other-model', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('funding_facility', [Item('rehab')]))
        model.dimension(Dimension('period', [Item(i, period=i, reviewed=True) for i in range(10, 15)]))
        original = [dict(item.attrs) for item in model.dimensions['period'].items]
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_construction_financing(model, given, draw_end_period=12, settlement_period=14,
                                       facility_dim='funding_facility', period_dim='period', prefix='rehab_debt')
        self.assertEqual([item.attrs for item in model.dimensions['period'].items], original)
        run = evaluate(model, {'rehab_debt.commitment': {'rehab': '100'},
                               'rehab_debt.annual_rate': {'rehab': '.12'},
                               'rehab_debt.draw': {('rehab', i): '100' if i == 10 else '0'
                                                   for i in range(10, 15)}})
        self.assertEqual(run.value('rehab_debt.interest', funding_facility='rehab', period=13), Decimal('1'))
        self.assertEqual(run.value('rehab_debt.ending_balance', funding_facility='rehab', period=14), Decimal('0'))

    def test_draw_cutoff_and_settlement_are_distinct_and_repayment_cannot_exceed_principal(self):
        run = schedule(inputs(), draw_end_period=2, settlement_period=4)
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=3), Decimal('150'))
        self.assertEqual(run.value('construction.interest', facility='bond', month=3), Decimal('1.50'))
        self.assertEqual(run.value('construction.repayment', facility='bond', month=4), Decimal('150'))
        for amount, code in (('151', 'CONSTRUCTION_REPAYMENT_EXCEEDS_PRINCIPAL'),
                             ('-1', 'INVALID_CONSTRUCTION_REPAYMENT')):
            values = inputs()
            values['reviewed_payoff'] = {'bond': amount, 'bridge': '50'}
            with self.subTest(amount=amount), self.assertRaises(EngineError) as err:
                schedule(values, repayment_amount=ref('reviewed_payoff'))
            self.assertEqual(err.exception.code, code)
        with self.assertRaises(ModelDefinitionError):
            schedule(inputs(), draw_end_period=4, settlement_period=3)

    def test_reviewed_partial_payoff_preserves_residual_principal_and_interest(self):
        values = inputs()
        values['reviewed_payoff'] = {'bond': '100', 'bridge': '50'}
        run = schedule(values, repayment_amount=ref('reviewed_payoff'))
        self.assertEqual(run.value('construction.repayment', facility='bond', month=3), Decimal('100'))
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=4), Decimal('50'))
        self.assertEqual(run.value('construction.interest', facility='bond', month=4), Decimal('.50'))

    def test_draws_cannot_exceed_commitments_or_continue_after_conversion(self):
        for field, key, amount, code in (
                ('construction.draw', ('bond', 1), '101', 'CONSTRUCTION_COMMITMENT_EXCEEDED'),
                ('construction.draw', ('bond', 3), '1', 'DRAW_AFTER_CONVERSION'),
                ('construction.draw', ('bridge', 4), '1', 'DRAW_AFTER_CONVERSION')):
            values = inputs()
            values[field][key] = amount
            with self.subTest(key=key), self.assertRaises(EngineError) as err:
                schedule(values)
            self.assertEqual(err.exception.code, code)
        values = inputs()
        values['construction.draw'][('bond', 1)] = '-1'
        with self.assertRaises(EngineError):
            schedule(values)

    def test_full_precision_interest_preserves_explicit_source_balance_math(self):
        values = inputs()
        values['construction.annual_rate']['bond'] = '.071'
        run = schedule(values, rounding_places=None)
        expected = Decimal('150') * Decimal('.071') / 12
        self.assertAlmostEqual(run.value('construction.interest', facility='bond', month=1), expected, places=26)
        rounded = schedule(values)
        self.assertEqual(rounded.value('construction.interest', facility='bond', month=1), Decimal('.89'))

    def test_invalid_timing_precision_and_period_dimensions_are_rejected(self):
        for precision in (True, 2.0, 0, '2'):
            with self.subTest(precision=precision), self.assertRaises(ModelDefinitionError):
                schedule(inputs(), rounding_places=precision)
        for periods, conversion in (([0, 2, 3], 3), ([0, 1, 2], 3), ([0, 1, 2], 0),
                                    ([0, True, 2], 2), ([0, 1, 2], True)):
            model = Model('synthetic-invalid', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            model.dimension(Dimension('facility', [Item('bond')]))
            model.dimension(Dimension('month', [Item(i, period=p) for i, p in enumerate(periods)]))
            with self.subTest(periods=periods, conversion=conversion), self.assertRaises(ModelDefinitionError):
                declare_construction_financing(model, None, draw_end_period=conversion, settlement_period=conversion)

    def test_draws_accrue_interest_on_ending_principal_and_pay_off_at_conversion(self):
        run = schedule(inputs())
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=1), Decimal('150'))
        self.assertEqual(run.value('construction.opening_balance', facility='bond', month=0), Decimal('0'))
        self.assertEqual(run.value('construction.opening_balance', facility='bond', month=1), Decimal('100'))
        self.assertEqual(run.value('construction.interest', facility='bond', month=1), Decimal('1.50'))
        self.assertEqual(run.value('construction.repayment', facility='bond', month=3), Decimal('150'))
        self.assertEqual(run.value('construction.opening_balance', facility='bond', month=3), Decimal('150'))
        for month in (3, 4):
            self.assertEqual(run.value('construction.ending_balance', facility='bond', month=month), Decimal('0'))
            self.assertEqual(run.value('construction.interest', facility='bond', month=month), Decimal('0'))
        self.assertEqual(run.value('construction.total_draw', facility='bridge'), Decimal('50'))
        self.assertEqual(run.value('construction.interest', facility='bridge', month=1), Decimal('.25'))


if __name__ == '__main__':
    unittest.main()
