"""Reusable periodic investor returns through engine declarations."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, EngineError, ModelDefinitionError, evaluate
from balto_model_engine.returns import declare_periodic_irr


class ReturnsTest(unittest.TestCase):
    def test_quarterly_return_annualizes_compound_growth(self):
        m = Model('synthetic-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('quarter', [Item(i, period=i) for i in range(5)]))
        m.input('cash', unit='USD', dims=('quarter',))
        declare_periodic_irr(m, cash_flow='cash', period_dim='quarter', periods_per_year=4)
        r = evaluate(m, {'cash': {0: '-100', 1: '0', 2: '0', 3: '0', 4: '121'}})
        self.assertAlmostEqual(r.value('returns.periodic_irr'), Decimal('1.1').sqrt()-1, places=20)
        self.assertAlmostEqual(r.value('returns.annual_irr'), Decimal('.21'), places=20)
        self.assertAlmostEqual(r.value('returns.npv'), Decimal('0'), places=19)

    def test_zero_and_negative_returns_and_multiple_contributions(self):
        for flows, expected in (({0: '-100', 1: '100'}, '0'),
                                ({0: '-100', 1: '90'}, '-.1'),
                                ({0: '-100', 1: '-20', 2: '143'}, '.1')):
            m = Model('synthetic-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            m.dimension(Dimension('year', [Item(i, period=i) for i in flows]))
            m.input('cash', unit='USD', dims=('year',))
            declare_periodic_irr(m, cash_flow='cash', period_dim='year', periods_per_year=1)
            r = evaluate(m, {'cash': flows})
            self.assertAlmostEqual(r.value('returns.periodic_irr'), Decimal(expected), places=20)

    def test_ambiguous_or_unbracketed_cash_flows_fail_explicitly(self):
        for flows, code in (({0: '-100', 1: '120', 2: '-10'}, 'IRR_NONCONVENTIONAL_CASH_FLOW'),
                            ({0: '100', 1: '120', 2: '10'}, 'IRR_REQUIRES_SIGN_CHANGE'),
                            ({0: '-1', 1: '100', 2: '0'}, 'IRR_OUTSIDE_BRACKET')):
            m = Model('synthetic-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            m.dimension(Dimension('year', [Item(i, period=i) for i in flows]))
            m.input('cash', unit='USD', dims=('year',))
            declare_periodic_irr(m, cash_flow='cash', period_dim='year', periods_per_year=1)
            with self.assertRaises(EngineError) as err:
                evaluate(m, {'cash': flows})
            self.assertEqual(err.exception.code, code)

    def test_invalid_period_structure_and_bounds_rejected(self):
        for periods in ((0, 2), (False, 1)):
            m = Model('synthetic-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            m.dimension(Dimension('year', [Item(i, period=p) for i, p in enumerate(periods)]))
            m.input('cash', unit='USD', dims=('year',))
            with self.assertRaises(ModelDefinitionError):
                declare_periodic_irr(m, cash_flow='cash', period_dim='year', periods_per_year=1)

        for bounds in (('-1', '10'), ('0', '-1'), ('NaN', '10'), (False, '10'), ('.1', 0.2)):
            m = Model('synthetic-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            m.dimension(Dimension('year', [Item(i, period=i) for i in range(2)]))
            m.input('cash', unit='USD', dims=('year',))
            with self.assertRaises(ModelDefinitionError):
                declare_periodic_irr(m, cash_flow='cash', period_dim='year', periods_per_year=1,
                                     lower=bounds[0], upper=bounds[1])
