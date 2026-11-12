from decimal import Decimal as D
import unittest
from balto_model_engine import Model, DecimalPolicy, Dimension, Item, ref, attr, if_, evaluate
from balto_model_engine.debt import build_draw_debt

class DrawTest(unittest.TestCase):
    def test_capped_draws_capitalized_interest_and_payoff_reconcile(self):
        m = Model('construction-test', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('period', [Item(i, index=i) for i in range(4)]))
        for name in ('spend', 'rate', 'fraction'):
            m.input(name, unit='number', dims=('period',))
        loan = build_draw_debt(m, prefix='loan', period_dim='period', eligible_spending=ref('spend'),
            debt_share=ref('share'), commitment=ref('limit'), annual_rate=ref('rate'),
            year_fraction=ref('fraction'), capitalize=if_(attr('period','index') < 3, 1, 0),
            draw_allowed=if_(attr('period','index') < 3, 1, 0), payoff=if_(attr('period','index') == 3, 1, 0))
        m.input('share', unit='rate'); m.input('limit', unit='usd')
        run = evaluate(m, dict(spend={0:100,1:100,2:100,3:0}, rate={i:'.12' for i in range(4)}, fraction={i:'0.08333333333333333333333333333333333' for i in range(4)}, share='.5',limit=80))
        self.assertEqual(loan.currency, 'USD')
        self.assertEqual(run.value('loan.funding', period=0), 50)
        self.assertEqual(run.value('loan.balance', period=2), 80)
        self.assertGreater(run.value('loan.unfunded', period=1), 20)
        self.assertGreater(run.value('loan.cash_interest', period=2), 0)
        self.assertEqual(run.value('loan.payoff', period=3), 80)
        self.assertEqual(run.value('loan.balance', period=3), 0)
        for i in range(4):
            v=lambda n:run.value('loan.'+n,period=i)
            self.assertAlmostEqual(v('opening')+v('funding')+v('capitalized_interest')-v('payoff'),v('balance'),delta=D('1e-25'))
            self.assertEqual(v('interest'),v('capitalized_interest')+v('cash_interest'))
