from decimal import Decimal as D
import unittest
from balto_model_engine import evaluate
from balto_development.model import build_model
from balto_development.example import example_deal,example_inputs
class DevelopmentTest(unittest.TestCase):
    def test_development_spending_debt_units_and_equity_reconcile(self):
        m=build_model(example_deal());r=evaluate(m,example_inputs())
        self.assertEqual(r.model_id,'multifamily-development')
        self.assertEqual(r.value('project_cost'),D('13440000'))
        self.assertEqual(r.value('total_units'),40)
        self.assertEqual(r.value('occupied_units',month='m0'),0)
        self.assertEqual(r.value('occupied_units',month='m11'),0)
        self.assertEqual(r.value('occupied_units',month='m12'),5)
        self.assertEqual(r.value('occupied_units',month='m20'),38)
        self.assertEqual(r.value('construction.balance',month='m24'),0)
        self.assertEqual(r.value('permanent.balance',month='m48'),0)
        self.assertGreater(r.value('stabilized_noi'),0)
        self.assertGreater(r.value('peak_equity'),0)
        self.assertTrue(all(t['passed'] for t in r.tests.values()),r.tests)
        for key in m.dimensions['month'].keys():
            idx=(key,)
            v=lambda n:r.values[n][idx]
            self.assertAlmostEqual(v('construction.opening')+v('construction.funding')+v('construction.capitalized_interest')-v('construction.payoff'),v('construction.balance'),delta=D('1e-20'))
            self.assertAlmostEqual(v('sources')+v('equity_funded')+v('funding_gap'),v('uses')+v('distribution'),delta=D('1e-20'))
            self.assertLessEqual(v('occupied_units'),v('delivered_units'))
        self.assertEqual(r.metrics['levered_irr']['status'],'ok')

    def test_overrun_and_delay_keep_unfunded_costs_and_maturity_breach_visible(self):
        from balto_development.example import downside_inputs
        m=build_model(example_deal());base=evaluate(m,example_inputs());r=evaluate(m,downside_inputs())
        self.assertGreater(r.value('total_funding_gap'),0)
        self.assertGreater(sum(r.series('construction.interest')),sum(base.series('construction.interest')))
        self.assertFalse(r.tests['funded']['passed'])
        self.assertFalse(r.tests['construction_capacity']['passed'])
        self.assertFalse(r.tests['construction_maturity']['passed'])
        self.assertEqual(r.value('project_cost'),D('15860000'))
        self.assertEqual(r.value('total_project_spending'),r.value('project_cost'))
        self.assertEqual(r.value('occupied_units',month='m17'),0)
        self.assertEqual(r.value('construction.balance',month='m30'),0)

    def test_rent_ceiling_stays_binding_as_market_targets_grow(self):
        inputs={**example_inputs(),'market_rent':{'one':'6000'},'rent_limit':{'one':'3000'}}
        r=evaluate(build_model(example_deal()),inputs)
        for i in range(12,61):
            occupied=r.value('occupied_units',month=f'm{i}')
            fraction=r.value('period_fraction',month=f'm{i}')
            self.assertLessEqual(r.value('rental_income',month=f'm{i}'),occupied*D(3000)*fraction+D('.000001'))

    def test_stub_and_floating_construction_interest_use_opening_debt_and_explicit_day_basis(self):
        inputs=example_inputs();inputs['construction_rate']['m1']='0.12';inputs['capitalize_interest']=0
        r=evaluate(build_model(example_deal()),inputs)
        expected=D('1300000')*D('.12')*16/365
        self.assertAlmostEqual(r.value('construction.interest',month='m1'),expected,delta=D('.000001'))
        self.assertEqual(r.value('construction.capitalized_interest',month='m1'),0)
        self.assertEqual(r.value('construction.cash_interest',month='m1'),r.value('construction.interest',month='m1'))
        self.assertEqual(r.value('construction.interest',month='m0'),0)

    def test_invalid_event_order_fractional_units_and_unspent_budget_are_structural_errors(self):
        from balto_model_engine import EngineError
        for change,code in (({'occupancy_month':11},'EVENT_ORDER'),({'units':{'one':'40.5'}},'EVENT_NOT_WHOLE'),({'completion_month':10},'SPEND_AFTER_COMPLETION'),({'spending_weight':{**example_inputs()['spending_weight'],'d1':'0'}},'SPENDING_WEIGHTS')):
            with self.subTest(code=code),self.assertRaises(EngineError) as caught:
                evaluate(build_model(example_deal()),{**example_inputs(),**change})
            self.assertEqual(caught.exception.code,code)

    def test_development_investors_use_required_equity_and_net_distributions(self):
        from balto_development.example import downside_inputs
        for inputs in (example_inputs(),downside_inputs()):
            r=evaluate(build_model(example_deal()),inputs)
            self.assertIn('lp_irr',r.metrics)
            self.assertIn('gp_irr',r.metrics)
            for i in range(61):
                v=lambda n:r.value(n,month=f'm{i}')
                self.assertAlmostEqual(v('lp_contribution')+v('gp_contribution'),v('equity_required'),delta=D('1e-20'))
                self.assertAlmostEqual(v('lp_distribution')+v('gp_distribution'),v('distribution'),delta=D('1e-20'))
                self.assertAlmostEqual(v('lp_cash_flow')+v('gp_cash_flow'),v('investor_flow'),delta=D('1e-20'))
            self.assertEqual(r.metrics['lp_irr']['status'],'ok')
            self.assertGreater(r.value('total_gp_promote'),0)

    def test_fee_sensitivities_reduce_returns_and_all_investor_cash_reconciles(self):
        base_inputs=example_inputs()
        cases={
            'base':base_inputs,
            'zero_fees':{**base_inputs,'developer_fee':{'building':0},'gc_fee_rate':{'building':0},'management_fee':0,'construction_fee_rate':0,'permanent_fee_rate':0,'sale_cost_rate':0},
            'higher_fees':{**base_inputs,'developer_fee':{'building':500000},'gc_fee_rate':{'building':'.15'},'management_fee':'.05','construction_fee_rate':'.02','permanent_fee_rate':'.02','sale_cost_rate':'.04'},
            'no_promote':{**base_inputs,'promote_1':0,'promote_2':0,'catch_up_share':0},
            'no_cash_receipts':{**base_inputs,'market_rent':{'one':0}},
        }
        model=build_model(example_deal())
        results={name:evaluate(model,inputs) for name,inputs in cases.items()}
        for name,r in results.items():
            with self.subTest(case=name):
                for key in model.dimensions['month'].keys():
                    v=lambda n:r.value(n,month=key)
                    self.assertAlmostEqual(v('lp_cash_flow')+v('gp_cash_flow'),v('investor_flow'),delta=D('.000001'))
                    self.assertAlmostEqual(v('sources')+v('equity_funded')+v('funding_gap'),v('uses')+v('distribution'),delta=D('.000001'))
        for metric in ('levered_irr','lp_irr','gp_irr'):
            self.assertGreater(results['zero_fees'].metrics[metric]['rate'],results['base'].metrics[metric]['rate'])
            self.assertLess(results['higher_fees'].metrics[metric]['rate'],results['base'].metrics[metric]['rate'])
        no_promote=results['no_promote']
        for metric in ('lp_irr','gp_irr'):
            self.assertAlmostEqual(no_promote.metrics[metric]['rate'],no_promote.metrics['levered_irr']['rate'],delta=D('1e-10'))
        self.assertAlmostEqual(no_promote.value('total_gp_promote'),0,delta=D('.000001'))
        for metric in ('levered_irr','lp_irr','gp_irr'):
            self.assertEqual(results['no_cash_receipts'].metrics[metric]['status'],'no_sign_change')
            self.assertNotIn('rate',results['no_cash_receipts'].metrics[metric])
