"""Reserve transfers and external funding through public model evaluation."""
import unittest
from balto_model_engine import DecimalPolicy, Dimension, EngineError, Item, Model, evaluate, ref
from balto_model_engine.funding import build_reserve


def reserve_model():
    m = Model('standalone-reserve', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    m.dimension(Dimension('interval', [Item(i) for i in range(5)]))
    for name in ('deposit', 'spending', 'release'):
        m.input(name, unit='usd', dims=('interval',), minimum=0)
    reserve = build_reserve(m, prefix='cash', period_dim='interval',
        deposits=ref('deposit'), eligible_spending=ref('spending'), release=ref('release'))
    return m, reserve


INPUTS = dict(deposit={0: 100, 1: 0, 2: 20, 3: 50, 4: 0},
              spending={0: 0, 1: 120, 2: 10, 3: 0, 4: 0},
              release={0: 0, 1: 0, 2: 0, 3: 60, 4: 60})


class FundingComponentTest(unittest.TestCase):
    def test_negative_reserve_deposit_is_a_structural_error(self):
        m, _ = reserve_model()
        build_reserve(m, prefix='invalid', period_dim='interval', deposits=-ref('deposit'),
                      eligible_spending=ref('spending'), release=ref('release'))
        with self.assertRaises(EngineError) as caught:
            evaluate(m, INPUTS)
        self.assertEqual(caught.exception.code, 'NEGATIVE_RESERVE_DEPOSIT')

    def test_internal_transfers_do_not_duplicate_costs_and_unmet_funding_is_visible(self):
        from balto_model_engine.funding import build_funding
        m, reserve = reserve_model()
        m.input('income', unit='usd', dims=('interval',))
        m.input('funding', unit='usd', dims=('interval',), minimum=0)
        funding = build_funding(m, period_dim='interval', sources=ref('income') + ref('funding'),
            uses=ref('spending'), transfers_in=reserve.draw + reserve.released,
            transfers_out=reserve.deposits, cash_name='net', contribution_name='call',
            distribution_name='distribution', external_funding=ref('funding'), unmet_name='unmet')
        m.calc('investor.flow', unit='usd', dims=(funding.period_dim,),
               expr=funding.distribution - funding.contribution)
        inputs = {**INPUTS, 'income': dict.fromkeys(range(5), 0),
                  'funding': {0: 100, 1: 5, 2: 20, 3: 0, 4: 0}}
        r = evaluate(m, inputs)
        self.assertEqual(list(r.values['unmet'].values()), [0, 15, 0, 0, 0])
        self.assertEqual(list(r.values['call'].values()), [100, 20, 20, 0, 0])
        self.assertEqual(list(r.values['distribution'].values()), [0, 0, 0, 10, 0])
        self.assertEqual(sum(r.values['investor.flow'].values()), -130)
        # Only 130 of actual spending, even though reserves are deposited and released.
        for idx in r.values['net']:
            self.assertEqual(r.values['net'][idx] + r.values['unmet'][idx], r.values['distribution'][idx])

    def test_deposits_draws_depletion_and_repeated_release_reconcile(self):
        m, reserve = reserve_model()
        m.calc('consumer', unit='usd', dims=(reserve.period_dim,), expr=reserve.balance)
        r = evaluate(m, INPUTS)
        self.assertEqual(reserve.currency, 'USD')
        self.assertEqual(list(r.values['cash.balance'].values()), [100, 0, 10, 0, 0])
        self.assertEqual(list(r.values['cash.draw'].values()), [0, 100, 10, 0, 0])
        self.assertEqual(list(r.values['cash.unfunded'].values()), [0, 20, 0, 0, 0])
        self.assertEqual(list(r.values['cash.released'].values()), [0, 0, 0, 60, 0])
        for idx in r.values['cash.balance']:
            v = lambda name: r.values['cash.' + name][idx]
            self.assertEqual(v('balance'), v('opening') + v('deposits') - v('draw') - v('released'))
            self.assertEqual(r.values['consumer'][idx], v('balance'))
