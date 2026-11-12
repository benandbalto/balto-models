"""Dated investor allocations through the public model interface."""
from decimal import Decimal as D
import unittest
from balto_model_engine import DecimalPolicy,Dimension,Item,Model,attr,evaluate,ref


def investor_model(days=(0,365)):
    from balto_model_engine.waterfall import WaterfallTerms,build_waterfall
    m=Model('standalone-investors','1.0.0',DecimalPolicy(34,'ROUND_HALF_UP'))
    elapsed=0;items=[]
    for i,days_in_period in enumerate(days):
        elapsed+=days_in_period
        items.append(Item(f'e{i}',days=days_in_period,date=45000+elapsed))
    m.dimension(Dimension('event',items))
    for name in ('contributions','distributions'):m.input(name,unit='usd',dims=('event',))
    for name in ('lp_share','pref_rate','hurdle_rate','promote_1','promote_2','catch_up_share'):m.input(name,unit='rate')
    terms=WaterfallTerms(*(ref(n) for n in ('lp_share','pref_rate','hurdle_rate','promote_1','promote_2','catch_up_share')))
    schedule=build_waterfall(m,period_dim='event',elapsed_days=attr('event','days'),contributions=ref('contributions'),distributions=ref('distributions'),terms=terms)
    m.xirr('lp_irr',flows='lp_cash_flow',dim='event',date_attr='date')
    m.xirr('gp_irr',flows='gp_cash_flow',dim='event',date_attr='date')
    return m,schedule


def inputs(**changes):
    return dict(contributions={'e0':100,'e1':0},distributions={'e0':0,'e1':108},
        lp_share='.9',pref_rate='.08',hurdle_rate='.12',promote_1='.2',promote_2='.3',catch_up_share=1,**changes)


class WaterfallTest(unittest.TestCase):
    def test_standalone_investors_receive_capital_and_actual_365_preferred_return(self):
        m,s=investor_model();r=evaluate(m,inputs())
        self.assertEqual(s.period_dim,'event');self.assertEqual(s.currency,'USD')
        self.assertEqual(r.value('lp_contribution',event='e0'),90)
        self.assertEqual(r.value('gp_contribution',event='e0'),10)
        self.assertEqual(r.value('pref.opening',event='e1'),D('97.2'))
        self.assertEqual(r.value('tier_1',event='e1'),108)
        self.assertEqual(r.value('lp_distribution',event='e1'),D('97.2'))
        self.assertEqual(r.value('gp_distribution',event='e1'),D('10.8'))
        self.assertEqual(r.value('pref.balance',event='e1'),0)
        self.assertAlmostEqual(r.metrics['lp_irr']['rate'],D('.08'),delta=D('1e-10'))

    def test_invalid_net_cash_and_terms_are_structural_errors(self):
        from balto_model_engine import EngineError
        for name,value in (('lp_share',0),('lp_share',D('1.1')),('pref_rate',-1),('promote_1',1),('catch_up_share',2)):
            m,_=investor_model();data=inputs();data[name]=value
            with self.subTest(name=name),self.assertRaises(EngineError) as caught:
                evaluate(m,data)
            self.assertEqual(caught.exception.code,'WATERFALL_TERMS')
        for name in ('contributions','distributions'):
            m,_=investor_model();data=inputs();data[name]['e0']=-1
            with self.subTest(cash=name),self.assertRaises(EngineError) as caught:evaluate(m,data)
            self.assertEqual(caught.exception.code,'WATERFALL_CASH')
        m,_=investor_model(days=(0,-1))
        with self.assertRaises(EngineError) as caught:evaluate(m,inputs())
        self.assertEqual(caught.exception.code,'WATERFALL_DAYS')

    def test_catch_up_hurdle_and_residual_allocate_net_profit_and_reconcile(self):
        m,s=investor_model();data=inputs();data['distributions']['e1']=200;r=evaluate(m,data)
        self.assertEqual(r.value('tier_1',event='e1'),108)
        self.assertAlmostEqual(r.value('tier_catch_up',event='e1'),D(16)/7,delta=D('1e-25'))
        self.assertEqual(r.value('tier_2',event='e1'),5)
        self.assertAlmostEqual(r.value('lp_distribution',event='e1'),D('154.17'),delta=D('1e-25'))
        self.assertAlmostEqual(r.value('gp_distribution',event='e1'),D('45.83'),delta=D('1e-25'))
        self.assertEqual(r.value('hurdle.balance',event='e1'),0)
        for key in m.dimensions['event'].keys():
            v=lambda n:r.value(n,event=key)
            self.assertAlmostEqual(v('lp_distribution')+v('gp_distribution'),D(data['distributions'][key]),delta=D('1e-25'))
            self.assertEqual(v('lp_contribution')+v('gp_contribution'),data['contributions'][key])
            self.assertAlmostEqual(v('lp_cash_flow')+v('gp_cash_flow'),D(data['distributions'][key])-D(data['contributions'][key]),delta=D('1e-25'))
            self.assertAlmostEqual(sum(v(n) for n in ('tier_1','tier_catch_up','tier_2','tier_3')),D(data['distributions'][key]),delta=D('1e-25'))
        for share in (0,'.1','.3'):
            data['catch_up_share']=share;r=evaluate(m,data)
            self.assertEqual(r.value('tier_catch_up',event='e1'),0)

    def test_irregular_dates_new_capital_partial_receipts_and_downside_balances(self):
        m,_=investor_model(days=(0,16,366,20));data=inputs()
        data['contributions']={'e0':100,'e1':20,'e2':0,'e3':0}
        data['distributions']={'e0':0,'e1':0,'e2':50,'e3':40}
        r=evaluate(m,data)
        opening=D(90)*(D('1.08')**(D(16)/365))+D(18)
        self.assertAlmostEqual(r.value('pref.opening',event='e1'),opening,delta=D('1e-20'))
        expected=opening*(D('1.08')**(D(366)/365))-45
        self.assertAlmostEqual(r.value('pref.balance',event='e2'),expected,delta=D('1e-20'))
        self.assertGreater(r.value('pref.balance',event='e3'),0)
        self.assertEqual(r.value('gp_promote',event='e3'),0)
        self.assertEqual(r.metrics['lp_irr']['status'],'ok')
        self.assertLess(r.metrics['lp_irr']['rate'],0)
        data['distributions']=dict.fromkeys(data['distributions'],0)
        r=evaluate(m,data)
        self.assertEqual(r.metrics['lp_irr']['status'],'no_sign_change')
        self.assertEqual(r.metrics['gp_irr']['status'],'no_sign_change')

    def test_full_lp_ownership_and_zero_rates_have_defined_balances_and_returns(self):
        m,_=investor_model();data=inputs();data.update(lp_share=1,pref_rate=0,hurdle_rate=0,catch_up_share=0)
        data['distributions']['e1']=200;r=evaluate(m,data)
        self.assertEqual(r.value('lp_distribution',event='e1'),170)
        self.assertEqual(r.value('gp_distribution',event='e1'),30)
        self.assertEqual(r.metrics['gp_irr']['status'],'no_sign_change')

    def test_nonconventional_cash_flows_preserve_no_root_status(self):
        m,_=investor_model(days=(0,365,365));data=inputs()
        data.update(pref_rate=0,hurdle_rate=0,promote_1=0,promote_2=0,catch_up_share=0)
        data['contributions']={'e0':0,'e1':200,'e2':0}
        data['distributions']={'e0':100,'e1':0,'e2':150}
        r=evaluate(m,data)
        self.assertEqual(r.metrics['lp_irr']['status'],'no_root')
        self.assertNotIn('rate',r.metrics['lp_irr'])
