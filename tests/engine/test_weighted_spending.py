import unittest
from balto_model_engine import Model,DecimalPolicy,Dimension,Item,ref,evaluate,EngineError,sum_within
from balto_model_engine.capital import build_weighted_spending
class WeightedTest(unittest.TestCase):
    def test_explicit_curve_spends_budget_once_and_rejects_incomplete_weights(self):
        m=Model('curve','1',DecimalPolicy(34,'ROUND_HALF_UP'))
        m.dimension(Dimension('phase',[Item('shell')]))
        m.dimension(Dimension('draw',[Item('a',phase='shell'),Item('b',phase='shell')],parent='phase'))
        m.input('cost',unit='usd',dims=('phase',)); m.input('weight',unit='rate',dims=('draw',),minimum=0,maximum=1)
        schedule=build_weighted_spending(m,phase_dim='phase',period_dim='draw',budget=ref('cost'),weight=ref('weight'),name='spend')
        m.calc('spent',unit='usd',dims=('phase',),expr=sum_within('draw',schedule.amount))
        r=evaluate(m,{'cost':{'shell':100},'weight':{'a':'.25','b':'.75'}})
        self.assertEqual(r.series('spend'),[25,75]);self.assertEqual(r.value('spent',phase='shell'),100)
        with self.assertRaises(EngineError) as caught:evaluate(m,{'cost':{'shell':100},'weight':{'a':'.25','b':'.5'}})
        self.assertEqual(caught.exception.code,'SPENDING_WEIGHTS')
