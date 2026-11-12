"""Capital math composes in standalone models with caller-owned assumptions."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, attr, evaluate, ref, sum_over, sum_within
from balto_model_engine.capital import build_capital_budget, build_even_spending, quantity_cost


class CapitalComponentTest(unittest.TestCase):
    def test_phase_budget_exposes_compounding_fee_bases_and_custom_names(self):
        model = Model('standalone-capital', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('stage', [Item('shell'), Item('fitout'), Item('empty')]))
        model.dimension(Dimension('work', [Item('roof', stage='shell'), Item('walls', stage='fitout')], parent='stage'))
        model.input('quantity', unit='units', dims=('work',), minimum=0)
        model.input('price', unit='usd', dims=('work',), minimum=0)
        model.calc('line.cost', unit='usd', dims=('work',), expr=quantity_cost(ref('price'), ref('quantity')))
        for name in ('fixed', 'conditions_rate', 'fee_rate', 'risk_rate'):
            model.input(name, unit='number', dims=('stage',), minimum=0)
        budget = build_capital_budget(model, phase_dim='stage',
            hard_costs=ref('fixed') + sum_within('work', ref('line.cost')),
            general_conditions_rate=ref('conditions_rate'), gc_fee_rate=ref('fee_rate'),
            contingency_rate=ref('risk_rate'), hard_name='construction.hard',
            general_conditions_name='construction.conditions', gc_fee_name='construction.fee',
            contingency_name='construction.risk', total_name='construction.total')
        model.calc('fee.basis', unit='usd', dims=('stage',), expr=budget.gc_fee_basis)
        model.calc('risk.basis', unit='usd', dims=('stage',), expr=budget.contingency_basis)
        run = evaluate(model, {'quantity': {'roof': 10, 'walls': 3}, 'price': {'roof': 100, 'walls': 200},
            'fixed': {'shell': 500, 'fitout': 400, 'empty': 0},
            'conditions_rate': {'shell': '.1', 'fitout': 0, 'empty': '.1'},
            'fee_rate': {'shell': '.2', 'fitout': 0, 'empty': '.2'},
            'risk_rate': {'shell': '.1', 'fitout': 0, 'empty': '.1'}})
        self.assertEqual(budget.phase_dim, 'stage')
        self.assertEqual(budget.currency, 'USD')
        self.assertEqual(run.series('construction.hard'), [Decimal(1500), Decimal(1000), Decimal(0)])
        self.assertEqual(run.series('fee.basis'), [Decimal(1650), Decimal(1000), Decimal(0)])
        self.assertEqual(run.series('risk.basis'), [Decimal(1980), Decimal(1000), Decimal(0)])
        self.assertEqual(run.series('construction.total'), [Decimal(2178), Decimal(1000), Decimal(0)])
        self.assertEqual(run.lineage['construction.fee']['dependsOn'],
                         ['construction.hard', 'construction.conditions', 'fee_rate'])

    def test_even_spending_reconciles_over_explicit_periods_and_activity(self):
        model = Model('standalone-spending', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('stage', [Item('shell'), Item('fitout')]))
        model.dimension(Dimension('interval', [Item(f't{i}', ordinal=i) for i in range(6)]))
        for name in ('budget', 'start', 'duration'):
            model.input(name, unit='number', dims=('stage',), minimum=0)
        model.input('active', unit='rate', dims=('interval',), minimum=0, maximum=1)
        schedule = build_even_spending(model, phase_dim='stage', period_dim='interval',
            budget=ref('budget'), period_index=attr('interval', 'ordinal'),
            start=ref('start'), periods=ref('duration'), activity=ref('active'), name='project.spend')
        model.calc('spent', unit='usd', dims=('stage',), expr=sum_over(schedule.period_dim, schedule.amount))
        inputs = {'budget': {'shell': 10, 'fitout': 9}, 'start': {'shell': 1, 'fitout': 3},
            'duration': {'shell': 3, 'fitout': 2}, 'active': {f't{i}': 1 for i in range(6)}}
        run = evaluate(model, inputs)
        self.assertEqual(schedule.phase_dim, 'stage')
        self.assertAlmostEqual(run.values['spent'][('shell',)], Decimal(10), delta=Decimal('1e-30'))
        self.assertEqual(run.values['spent'][('fitout',)], Decimal(9))
        for stage in ('shell', 'fitout'):
            self.assertEqual(run.values['project.spend'][(stage, 't0')], 0)
            self.assertEqual(run.values['project.spend'][(stage, 't5')], 0)
        self.assertEqual(run.values['project.spend'][('fitout', 't3')], Decimal('4.5'))
        self.assertEqual(run.values['project.spend'][('fitout', 't4')], Decimal('4.5'))
        truncated = evaluate(model, {**inputs, 'active': {**inputs['active'], 't4': 0}})
        self.assertEqual(truncated.values['spent'][('fitout',)], Decimal('4.5'))
        self.assertEqual(truncated.values['project.spend'][('fitout', 't4')], 0)
        self.assertEqual(run.lineage['project.spend']['dependsOn'],
                         ['start', 'duration', 'budget', 'active'])


if __name__ == '__main__':
    unittest.main()
