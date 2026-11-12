"""Annual forecasts separate full-year growth from partial-period spending."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, EngineError, Item, Model, ModelDefinitionError, evaluate
from balto_model_engine.operations import AnnualProjectionTerms, declare_annual_projection


class OperationsTest(unittest.TestCase):
    def test_partial_first_year_does_not_reduce_future_full_year_expenses(self):
        m=Model('synthetic-annual-expenses','1',DecimalPolicy(34,'ROUND_HALF_UP'))
        m.dimension(Dimension('tax_year',[Item(y) for y in (2026,2027,2028)]))
        def given(name,unit,dims=(),low=0,high=None):
            m.input(name,unit=unit,dims=dims,minimum=low,maximum=high)
        declare_annual_projection(m,given,('taxes','repairs'),rounding_places=0)
        vals={'expenses.annual_base':{'taxes':'100.4','repairs':'20'},
              'expenses.annual_growth':{('taxes',2026):'0',('taxes',2027):'.05',('taxes',2028):'.05',
                                       ('repairs',2026):'0',('repairs',2027):'0',('repairs',2028):'-.5'},
              'expenses.period_fraction':{2026:'.5',2027:'1',2028:'1'}}
        r=evaluate(m,vals)
        self.assertEqual(r.value('expenses.amount',expense='taxes',tax_year=2026),Decimal('50'))
        self.assertEqual(r.value('expenses.full_amount',expense='taxes',tax_year=2027),Decimal('105'))
        self.assertEqual(r.value('expenses.amount',expense='taxes',tax_year=2028),Decimal('110'))
        self.assertEqual(r.value('expenses.total',tax_year=2028),Decimal('120'))
        vals['expenses.annual_growth'][('taxes',2026)]='.1'
        with self.assertRaises(EngineError) as err:
            evaluate(m,vals)
        self.assertEqual(err.exception.code,'INITIAL_PROJECTION_GROWTH_NOT_ZERO')

    def test_full_precision_and_cent_rounding_are_explicit(self):
        for precision, expected in ((None, Decimal('11.02750')), (2, Decimal('11.03'))):
            m=Model('synthetic-annual-expenses','1',DecimalPolicy(34,'ROUND_HALF_UP'))
            m.dimension(Dimension('tax_year',[Item(2026),Item(2027)]))
            def given(name,unit,dims=(),low=0,high=None):
                m.input(name,unit=unit,dims=dims,minimum=low,maximum=high)
            declare_annual_projection(m,given,('expense',),rounding_places=precision)
            r=evaluate(m,{'expenses.annual_base':{'expense':'10.025'},
                          'expenses.annual_growth':{('expense',2026):'0',('expense',2027):'.1'},
                          'expenses.period_fraction':{2026:'0',2027:'1'}})
            self.assertEqual(r.value('expenses.amount',expense='expense',tax_year=2026),Decimal('0'))
            self.assertEqual(r.value('expenses.amount',expense='expense',tax_year=2027),expected)
        for items,precision,years in ((('bad name',),0,(2026,2027)),
                                     (('ok','ok'),0,(2026,2027)),
                                     (('ok',),True,(2026,2027)),
                                     (('ok',),0,(2026,2028))):
            m=Model('synthetic-invalid-expenses','1',DecimalPolicy(34,'ROUND_HALF_UP'))
            m.dimension(Dimension('tax_year',[Item(y) for y in years]))
            with self.assertRaises(ModelDefinitionError):
                declare_annual_projection(m,None,items,rounding_places=precision)

    def test_projection_terms_validate_the_same_expense_and_precision_contract(self):
        terms = AnnualProjectionTerms(('taxes', 'repairs'), None)
        self.assertEqual(terms.items, ('taxes', 'repairs'))
        self.assertIsNone(terms.rounding_places)
        for items, precision in (((), 0), (['taxes'], 0), (('taxes', 'taxes'), 0),
                                 (('bad name',), 0), ((False,), 0), (('taxes',), True),
                                 (('taxes',), 1)):
            with self.subTest(items=items), self.assertRaises(ModelDefinitionError):
                AnnualProjectionTerms(items, precision)
