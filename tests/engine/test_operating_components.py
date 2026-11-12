"""Reusable operating math runs independently and keeps released model results."""
from decimal import Decimal
from datetime import date
import unittest
from balto_model_engine import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, evaluate, monthly_calendar, ref, sum_over
from balto_model_engine.operating import (
    annual_per_unit, annual_fixed, build_noi, build_payroll_fte, build_payroll_costs,
    monthly_per_unit, percentage_of,
    build_operating_projection, build_operating_cash_flow,
)


class OperatingComponentTest(unittest.TestCase):
    def test_operating_projection_requires_dated_periods(self):
        for items in ([Item(1)], [Item(1, date='January')], [Item(1, date=True)],
                      [Item(1, date=Decimal('NaN'))], []):
            with self.subTest(items=items):
                m = Model('undated-property', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
                m.dimension(Dimension('period', items))
                with self.assertRaisesRegex(ModelDefinitionError, 'numeric dates'):
                    build_operating_projection(m, period_dim='period', units=ref('units'),
                        income_lines=(ref('income'),), expense_lines=(ref('expenses'),),
                        income=ref('income'), expenses=ref('expenses'), noi_name='noi')
                self.assertNotIn('noi', m.variables)

    def test_dated_projection_keeps_noi_separate_from_reserves_and_debt(self):
        m = Model('standalone-property', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        calendar = monthly_calendar(date(2026, 12, 31), 2)
        m.dimension(Dimension('period', [
            Item(i.key, as_of=i.attrs['date'], month_of_year=i.attrs['month_of_year'])
            for i in calendar.items]))
        m.input('units', unit='units')
        for name in ('rent', 'other', 'expense', 'reserve', 'debt'):
            m.input(name, unit='usd', dims=('period',))
        m.calc('income', unit='usd', dims=('period',), expr=ref('rent') + ref('other'))
        projection = build_operating_projection(
            m, period_dim='period', date_attr='as_of', units=ref('units'),
            income_lines=(ref('rent'), ref('other')), expense_lines=(ref('expense'),),
            income=ref('income'), expenses=ref('expense'), noi_name='property.noi')
        cash = build_operating_cash_flow(m, projection=projection, reserves=ref('reserve'),
                                         name='property.before_debt')
        m.calc('equity_cash', unit='usd', dims=(projection.period_dim,), expr=cash.amount - ref('debt'))
        m.calc('total_noi', unit='usd', expr=sum_over(projection.period_dim, projection.noi))
        run = evaluate(m, {'units': 10, 'rent': {0: 0, 1: 5000, 2: 6000},
                           'other': {0: 0, 1: 200, 2: 300}, 'expense': {0: 0, 1: 1500, 2: 1600},
                           'reserve': {0: 0, 1: 100, 2: 200}, 'debt': {0: 0, 1: 900, 2: 1000}})
        self.assertEqual(projection.currency, 'USD')
        self.assertEqual(projection.date_attr, 'as_of')
        self.assertEqual(m.dimensions[projection.period_dim].items[1].attrs['month_of_year'], 1)
        self.assertEqual(run.series('property.noi'), [Decimal(0), Decimal(3700), Decimal(4700)])
        self.assertEqual(run.series('property.before_debt'), [Decimal(0), Decimal(3600), Decimal(4500)])
        self.assertEqual(run.series('equity_cash'), [Decimal(0), Decimal(2700), Decimal(3500)])
        self.assertEqual(run.value('total_noi'), Decimal(8400))
        self.assertEqual(run.lineage['property.noi']['dependsOn'], ['income', 'expense'])
        self.assertEqual(run.lineage['property.before_debt']['dependsOn'], ['property.noi', 'reserve'])

    def test_expense_methods_use_explicit_quantity_income_basis_and_period_count(self):
        m = Model('expense-budget', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(1), Item(2)]))
        for name in ('units', 'monthly_rate', 'annual_rate', 'annual_fixed', 'fee_rate'):
            m.input(name, unit='number')
        for name in ('occupancy', 'income'):
            m.input(name, unit='number', dims=('month',))
        m.calc('expense', unit='usd', dims=('month',), expr=
               monthly_per_unit(ref('monthly_rate'), ref('units'), occupancy=ref('occupancy'))
               + annual_per_unit(ref('annual_rate'), ref('units'), periods=4)
               + annual_fixed(ref('annual_fixed'), periods=4)
               + percentage_of(ref('income'), ref('fee_rate')))
        run = evaluate(m, {'units': 10, 'monthly_rate': 20, 'annual_rate': 400,
                           'annual_fixed': 2000, 'fee_rate': '0.05',
                           'occupancy': {1: '0.5', 2: 1}, 'income': {1: 5000, 2: 6000}})
        self.assertEqual(run.series('expense'), [Decimal(1850), Decimal(2000)])

    def test_allocated_staffing_loads_salary_bonus_tax_and_itemized_benefits(self):
        m = Model('staffing-budget', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('staff', [Item('manager'), Item('technician')]))
        inputs = {}
        for name, values in {
            'base_pay': [80000, 60000], 'head_count': [2, 1],
            'allocation': ['0.5', 1], 'fte_percent': [50, 100],
            'bonus_rate': ['0.1', 0], 'tax_rate': ['0.15', 0],
            'benefits_rate': ['0.03', 0],
        }.items():
            m.input(f'staffing.{name}', unit='number', dims=('staff',))
            inputs[f'staffing.{name}'] = dict(zip(['manager', 'technician'], values))
        build_payroll_fte(m, prefix='staffing', role_dim='staff')
        m.dimension(Dimension('allowance', [
            Item('phone', staff='manager', bucket='base'),
            Item('health', staff='manager', bucket='benefits'),
            Item('retirement', staff='manager', bucket='benefits'),
        ], parent='staff'))
        for method, values in {
            'fixed_annual': [600, 12000, 0], 'percent_base': [0, 0, '0.02'],
            'percent_base_bonus': [0, 0, '0.01'],
        }.items():
            m.input(f'staffing.component.{method}', unit='number', dims=('allowance',))
            inputs[f'staffing.component.{method}'] = dict(zip(['phone', 'health', 'retirement'], values))
        build_payroll_costs(m, prefix='staffing', role_dim='staff', component_dim='allowance')
        m.calc('monthly_staffing', unit='usd', dims=('staff',),
               expr=annual_fixed(ref('staffing.total')))
        run = evaluate(m, inputs)
        self.assertEqual(run.series('staffing.fte'), [Decimal('0.5'), Decimal(1)])
        self.assertEqual(run.series('staffing.base'), [Decimal(40300), Decimal(60000)])
        self.assertEqual(run.series('staffing.bonus'), [Decimal(4000), Decimal(0)])
        self.assertEqual(run.series('staffing.tax'), [Decimal(6600), Decimal(0)])
        self.assertEqual(run.series('staffing.benefits'), [Decimal(8440), Decimal(0)])
        self.assertEqual(run.series('staffing.component.amount'), [Decimal(300), Decimal(6000), Decimal(1240)])
        self.assertEqual(run.series('staffing.total'), [Decimal(59340), Decimal(60000)])
        self.assertEqual(run.series('monthly_staffing'), [Decimal(4945), Decimal(5000)])

    def test_monthly_noi_budget_composes_income_and_operating_expenses(self):
        m = Model('noi-budget', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(1), Item(2)]))
        m.input('income', unit='usd', dims=('month',))
        m.input('units', unit='units', minimum=1)
        m.input('insurance', unit='usd/unit-year', minimum=0)
        m.input('fixed', unit='usd/year', minimum=0)
        m.calc('expenses', unit='usd', dims=('month',),
               expr=annual_per_unit(ref('insurance'), ref('units')) + annual_fixed(ref('fixed')))
        build_noi(m, income=ref('income'), expenses=ref('expenses'), name='noi', dims=('month',))
        run = evaluate(m, {'income': {1: 5000, 2: 6000}, 'units': 10, 'insurance': 600, 'fixed': 12000})
        self.assertEqual(run.series('noi'), [Decimal(3500), Decimal(4500)])
        self.assertEqual(run.lineage['noi']['dependsOn'], ['income', 'expenses'])
