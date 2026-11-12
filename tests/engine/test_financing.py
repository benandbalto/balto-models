"""Shared financing contracts exercised without a deal-specific model."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, evaluate, ref
from balto_model_engine.financing import LoanTerms, declare_loan_stack, declare_loan


def run_stack(loans, values, months=4, **kwargs):
    model = Model('synthetic-financing', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    model.dimension(Dimension('month', [Item(i, period=i) for i in range(months + 1)]))
    model.input('available_cash', unit='USD', dims=('month',))
    def given(name, unit, dims=(), low=0, high=None):
        model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
    declare_loan_stack(model, loans, given, cash_available=ref('available_cash'), **kwargs)
    return evaluate(model, values)


class FinancingTest(unittest.TestCase):
    def test_monthly_stack_preserves_full_precision_annuity_when_reviewed(self):
        loan = LoanTerms('senior', 1, 1, 12, None, 'amortizing', False,
                         mortgage_insurance_basis='original')
        values = {'available_cash': {m: '5000' for m in range(13)},
                  'debt.senior.amount': '1200', 'debt.senior.annual_rate': '.12',
                  'debt.senior.mortgage_insurance_annual_rate': '.012'}
        run = run_stack((loan,), values, months=12, rounding_places=None)
        rate = Decimal('.01')
        payment = Decimal('1200') * rate / (1 - (1 + rate) ** -12)
        self.assertAlmostEqual(run.value('debt.senior.payment'), payment, places=20)
        self.assertAlmostEqual(run.value('debt.senior.ending_balance', month=3),
                               Decimal('1200') * (1 + rate) ** 3
                               - payment * ((1 + rate) ** 3 - 1) / rate, places=20)
        self.assertAlmostEqual(sum(run.series('debt.interest_paid')), payment * 12 - 1200, places=20)
        self.assertAlmostEqual(sum(run.series('debt.principal')), Decimal('1200'), places=20)
        self.assertAlmostEqual(run.value('debt.total_owed', month=12), Decimal('0'), places=20)
        self.assertEqual(sum(run.series('debt.mortgage_insurance')), Decimal('14.4'))
        rounded = run_stack((loan,), values, months=12)
        self.assertEqual(rounded.value('debt.senior.payment'), payment.quantize(Decimal('.01')))

    def test_loan_precision_rejects_boolean_and_inexact_structure(self):
        loan = LoanTerms('senior', 1, 1, 12, None, 'amortizing', False)
        for precision in (True, False, 2.0, '2', 0):
            with self.assertRaises(ModelDefinitionError):
                run_stack((loan,), {}, rounding_places=precision)
            model = Model('synthetic-precision', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            model.dimension(Dimension('month', [Item(i, period=i) for i in range(3)]))
            with self.assertRaises(ModelDefinitionError):
                declare_loan(model, loan, None, prefix='loan', period_dim='month',
                             cash_available=ref('cash'), rounding_places=precision)

    def test_reviewed_paid_interest_basis_selects_monthly_or_annual_ceiling(self):
        annual = LoanTerms('seller', 1, 1, 12, None, 'cash_flow_interest', False)
        from dataclasses import replace
        monthly = replace(annual, paid_interest_basis='accrual_period')
        values = {'available_cash': {m: '1000' for m in range(3)},
                  'debt.seller.amount': '1200', 'debt.seller.annual_rate': '.12',
                  'debt.seller.paid_annual_rate': '.06', 'debt.seller.payment_cap': '0',
                  'debt.seller.cash_flow_fraction': {m: '1' for m in range(3)}}
        run = run_stack((monthly,), values, months=2)
        self.assertEqual(run.value('debt.seller.interest', month=1), Decimal('12'))
        self.assertEqual(run.value('debt.seller.interest_paid', month=1), Decimal('6'))
        self.assertEqual(run.value('debt.seller.accrued_interest_balance', month=2), Decimal('12'))
        run = run_stack((annual,), values, months=2)
        self.assertEqual(run.value('debt.seller.interest_paid', month=1), Decimal('12'))
        self.assertEqual(run.value('debt.seller.accrued_interest_balance', month=2), Decimal('0'))

    def test_paid_interest_ceiling_uses_reviewed_partial_year_fraction(self):
        model = Model('synthetic-partial-year', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('period', [Item(i, period=i) for i in range(3)]))
        model.input('available', unit='USD', dims=('period',))
        model.input('year_fraction', unit='ratio', dims=('period',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_loan(model, LoanTerms('seller', 0, 1, 12, None, 'cash_flow_interest', True,
                                     paid_interest_basis='accrual_period'),
                     given, prefix='loan', period_dim='period', cash_available=ref('available'),
                     accrual_fraction=ref('year_fraction'), rounding_places=None)
        run = evaluate(model, {'available': {i: '1000' for i in range(3)},
                               'year_fraction': {0: '0', 1: '.25', 2: '.5'},
                               'loan.amount': '1200', 'loan.annual_rate': '.12',
                               'loan.paid_annual_rate': '.06', 'loan.payment_cap': '0',
                               'loan.cash_flow_fraction': {i: '1' for i in range(3)}})
        self.assertEqual(run.value('loan.interest_paid', period=1), Decimal('18'))
        self.assertEqual(run.value('loan.ending_balance', period=1), Decimal('1218'))
        self.assertEqual(run.value('loan.interest_paid', period=2), Decimal('36.54'))
        self.assertEqual(run.value('loan.ending_balance', period=2), Decimal('1254.54'))
        self.assertEqual(run.value('loan.paid_interest_fraction', period=2), Decimal('.5'))

    def test_paid_interest_basis_requires_explicit_cash_flow_contract(self):
        from dataclasses import replace
        loan = LoanTerms('seller', 0, 0, 12, None, 'cash_flow_interest', False)
        for basis in (True, 'monthly', None):
            with self.assertRaises(ModelDefinitionError):
                replace(loan, paid_interest_basis=basis)
        for mode in ('amortizing', 'interest_only', 'accrual'):
            with self.assertRaises(ModelDefinitionError):
                replace(loan, repayment=mode, paid_interest_basis='accrual_period')

    def test_noncash_cost_deferrals_incur_debt_without_cash_proceeds(self):
        model = Model('synthetic-deferral', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('month', [Item(i, period=i) for i in range(5)]))
        model.input('available_cash', unit='USD', dims=('month',))
        model.input('deferred_cost', unit='USD', dims=('month',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        loan = LoanTerms('fee', 1, 3, 12, None, 'cash_flow_principal', True,
                         origination='noncash')
        declare_loan_stack(model, (loan,), given, cash_available=ref('available_cash'),
                           advances_by_loan={'fee': ref('deferred_cost')})
        values = {'available_cash': {i: '100' for i in range(5)},
                  'deferred_cost': {0: '0', 1: '100', 2: '50', 3: '0', 4: '0'},
                  'debt.fee.annual_rate': '0.12', 'debt.fee.paid_annual_rate': '0.12',
                  'debt.fee.payment_cap': '0',
                  'debt.fee.cash_flow_fraction': {i: '1' for i in range(5)}}
        run = evaluate(model, values)
        self.assertEqual(run.value('debt.proceeds', month=1), Decimal('0'))
        self.assertEqual(run.value('debt.advance', month=2), Decimal('50'))
        self.assertEqual(run.value('debt.noncash_proceeds', month=1), Decimal('100'))
        self.assertEqual(run.value('debt.fee.ending_balance', month=2), Decimal('152.51'))
        self.assertEqual(run.value('debt.fee.principal', month=2), Decimal('0'))
        self.assertEqual(run.value('debt.fee.interest_paid', month=3), Decimal('1.53'))
        self.assertEqual(run.value('debt.fee.principal', month=3), Decimal('98.47'))
        self.assertEqual(run.value('debt.fee.ending_balance', month=3), Decimal('54.04'))
        self.assertEqual(run.value('debt.fee.ending_balance', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.cash_after_payments', month=4), Decimal('45.42'))

    def test_explicit_advances_require_nonnegative_amounts_and_valid_origination_timing(self):
        from balto_model_engine import EngineError
        model = Model('synthetic-advance-validation', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('month', [Item(i, period=i) for i in range(3)]))
        model.input('advance', unit='USD', dims=('month',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_loan(model, LoanTerms('loan', 1, 1, 12, None, 'accrual', False), given,
                     prefix='loan', period_dim='month', cash_available=ref('advance') * 0,
                     advances=ref('advance'))
        values = {'advance': {0: '0', 1: '10', 2: '20'}, 'loan.annual_rate': '0'}
        run = evaluate(model, values)
        self.assertEqual(run.value('loan.proceeds', month=2), Decimal('20'))
        self.assertEqual(run.value('loan.total_owed', month=2), Decimal('30'))
        for month, amount in ((0, '1'), (2, '-1')):
            invalid = dict(values, advance=dict(values['advance']))
            invalid['advance'][month] = amount
            with self.subTest(month=month), self.assertRaises(EngineError) as err:
                evaluate(model, invalid)
            self.assertEqual(err.exception.code, 'INVALID_LOAN_ADVANCE')
        with self.assertRaises(ModelDefinitionError):
            LoanTerms('loan', 0, 0, 12, None, 'accrual', False, origination='unknown')

    def test_cash_and_noncash_origins_share_payment_priority_without_combining_cash_sources(self):
        loans = (LoanTerms('senior', 1, 1, 2, 2, 'amortizing', False),
                 LoanTerms('fee', 1, 1, 12, None, 'cash_flow_principal', False,
                           origination='noncash'))
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.senior.amount': '120', 'debt.senior.annual_rate': '0',
                  'debt.fee.amount': '100', 'debt.fee.annual_rate': '0',
                  'debt.fee.paid_annual_rate': '0', 'debt.fee.payment_cap': '0',
                  'debt.fee.cash_flow_fraction': {m: '1' for m in range(5)}}
        run = run_stack(loans, values)
        self.assertEqual(run.value('debt.advance', month=1), Decimal('220'))
        self.assertEqual(run.value('debt.proceeds', month=1), Decimal('120'))
        self.assertEqual(run.value('debt.noncash_proceeds', month=1), Decimal('100'))
        self.assertEqual(run.value('debt.fee.principal', month=1), Decimal('40'))
        self.assertEqual(run.value('debt.fee.ending_balance', month=2), Decimal('20'))
        self.assertEqual(run.value('debt.cash_after_payments', month=3), Decimal('80'))
        model = Model('synthetic-advance-rejections', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('month', [Item(i, period=i) for i in range(3)]))
        model.input('advance', unit='USD', dims=('month',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        with self.assertRaises(ModelDefinitionError):
            declare_loan_stack(model, loans, given, cash_available=ref('advance'),
                               advances_by_loan={'missing': ref('advance')})
        with self.assertRaises(ModelDefinitionError):
            declare_loan(model, loans[0], given, prefix='loan', period_dim='month',
                         cash_available=ref('advance'), advances=ref('advance'))

    def test_mortgage_insurance_reduces_cash_before_junior_payments(self):
        loans = (LoanTerms('senior', 1, 1, 2, 2, 'amortizing', False,
                           mortgage_insurance_basis='original'),
                 LoanTerms('seller', 1, 1, 12, None, 'cash_flow_principal', False))
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.senior.amount': '120', 'debt.senior.annual_rate': '0',
                  'debt.senior.mortgage_insurance_annual_rate': '0.12',
                  'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0',
                  'debt.seller.paid_annual_rate': '0', 'debt.seller.payment_cap': '0',
                  'debt.seller.cash_flow_fraction': {m: '1' for m in range(5)}}
        run = run_stack(loans, values)
        self.assertEqual(run.value('debt.mortgage_insurance', month=1), Decimal('1.20'))
        self.assertEqual(run.value('debt.senior.debt_service', month=1), Decimal('61.20'))
        self.assertEqual(run.value('debt.seller.principal', month=1), Decimal('38.80'))
        self.assertEqual(run.value('debt.mortgage_insurance', month=2), Decimal('1.20'))
        self.assertEqual(run.value('debt.mortgage_insurance', month=3), Decimal('0'))
        self.assertEqual(run.value('debt.senior.total_owed', month=2), Decimal('0'))
        from dataclasses import replace
        run = run_stack((replace(loans[0], mortgage_insurance_basis='outstanding'), loans[1]), values)
        self.assertEqual(run.value('debt.mortgage_insurance', month=2), Decimal('0.60'))
        with self.assertRaises(ModelDefinitionError):
            replace(loans[1], mortgage_insurance_basis='original')

    def test_scheduled_annual_periods_preserve_monthly_amortization_and_original_premiums(self):
        model = Model('synthetic-annual-senior', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('year', [Item(i, period=i) for i in range(3)]))
        model.input('cash', unit='USD', dims=('year',))
        model.input('months', unit='months', dims=('year',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_loan(model, LoanTerms('senior', 0, 1, 12, None, 'amortizing', False, 'original'),
                     given, prefix='loan', period_dim='year', cash_available=ref('cash'),
                     scheduled_payment_months=ref('months'), rounding_places=None)
        values = {'cash': {i: '5000' for i in range(3)}, 'months': {0: '0', 1: '3', 2: '9'},
                  'loan.amount': '1200', 'loan.annual_rate': '0.12',
                  'loan.mortgage_insurance_annual_rate': '0.012'}
        run = evaluate(model, values)
        r = Decimal('0.01')
        payment = Decimal('1200') * r / (1 - (1 + r) ** -12)
        closing = Decimal('1200') * (1 + r) ** 3 - payment * ((1 + r) ** 3 - 1) / r
        self.assertAlmostEqual(run.value('loan.ending_balance', year=1), closing, places=20)
        self.assertAlmostEqual(run.value('loan.interest_paid', year=1), payment * 3 - (1200 - closing), places=20)
        self.assertEqual(run.value('loan.simple_interest', year=1), Decimal('36'))
        self.assertEqual(run.value('loan.mortgage_insurance', year=1), Decimal('3.6'))
        self.assertAlmostEqual(run.value('loan.ending_balance', year=2), Decimal('0'), places=20)
        self.assertEqual(run.value('loan.mortgage_insurance', year=2), Decimal('10.8'))
        values['loan.annual_rate'] = '0'
        run = evaluate(model, values)
        self.assertEqual(run.value('loan.ending_balance', year=1), Decimal('900'))
        self.assertEqual(run.value('loan.debt_service', year=2), Decimal('910.8'))
        from balto_model_engine import EngineError
        values['months'][1] = '3.5'
        with self.assertRaises(EngineError) as err:
            evaluate(model, values)
        self.assertEqual(err.exception.code, 'INVALID_PAYMENT_MONTHS')
        values['months'][1], values['months'][2] = '4', '9'
        with self.assertRaises(EngineError) as err:
            evaluate(model, values)
        self.assertEqual(err.exception.code, 'PAYMENTS_EXCEED_TERM')

    def test_two_amortizing_loans_fund_and_repay_independently(self):
        loans = (LoanTerms('senior', 1, 1, 2, 2, 'amortizing', False),
                 LoanTerms('junior', 2, 2, 3, 4, 'amortizing', False))
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.senior.amount': '100.01', 'debt.senior.annual_rate': '0',
                  'debt.junior.amount': '90', 'debt.junior.annual_rate': '0'}
        run = run_stack(loans, values)
        self.assertEqual(run.value('debt.proceeds', month=1), Decimal('100.01'))
        self.assertEqual(run.value('debt.proceeds', month=2), Decimal('90'))
        self.assertEqual(run.value('debt.debt_service', month=2), Decimal('80'))
        self.assertEqual(run.value('debt.senior.ending_balance', month=2), Decimal('0'))
        self.assertEqual(run.value('debt.junior.ending_balance', month=3), Decimal('30'))
        self.assertEqual(run.value('debt.ending_balance', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.cash_after_payments', month=2), Decimal('20'))

    def test_cash_flow_loans_follow_priority_and_track_simple_and_compound_accrual(self):
        loans = (LoanTerms('senior', 1, 1, 2, 2, 'amortizing', False),
                 LoanTerms('compound', 1, 1, 12, None, 'cash_flow_principal', True),
                 LoanTerms('simple', 1, 1, 12, None, 'cash_flow_interest', False))
        values = {'available_cash': {m: '100' if m == 1 else '0' for m in range(5)},
                  'debt.senior.amount': '100', 'debt.senior.annual_rate': '0'}
        for name, rate, share in (('compound', '0.12', '0.5'), ('simple', '0.24', '1')):
            p = 'debt.' + name
            values.update({p + '.amount': '100', p + '.annual_rate': rate,
                           p + '.paid_annual_rate': rate, p + '.payment_cap': '0',
                           p + '.cash_flow_fraction': {m: share for m in range(5)}})
        run = run_stack(loans, values)
        self.assertEqual(run.value('debt.compound.cash_before_payment', month=1), Decimal('50'))
        self.assertEqual(run.value('debt.compound.principal', month=1), Decimal('24'))
        self.assertEqual(run.value('debt.compound.ending_balance', month=2), Decimal('76.76'))
        self.assertEqual(run.value('debt.compound.interest_accrued', month=2), Decimal('0.76'))
        self.assertEqual(run.value('debt.simple.ending_balance', month=2), Decimal('100'))
        self.assertEqual(run.value('debt.simple.accrued_interest_balance', month=2), Decimal('2'))
        self.assertEqual(run.value('debt.simple.total_owed', month=2), Decimal('102'))
        self.assertEqual(run.value('debt.cash_after_payments', month=2), Decimal('-50'))

    def test_payment_caps_and_interest_only_repayments_leave_unpaid_interest_visible(self):
        loan = LoanTerms('seller', 1, 1, 12, None, 'cash_flow_interest', False)
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0.12',
                  'debt.seller.paid_annual_rate': '0.001', 'debt.seller.payment_cap': '5',
                  'debt.seller.cash_flow_fraction': {m: '1' for m in range(5)}}
        run = run_stack((loan,), values)
        self.assertEqual(run.value('debt.seller.interest_paid', month=1), Decimal('1'))
        self.assertEqual(run.value('debt.seller.payment_budget', month=1), Decimal('5'))
        self.assertEqual(run.value('debt.seller.principal', month=1), Decimal('0'))
        self.assertEqual(run.value('debt.seller.total_owed', month=4), Decimal('1036'))
        values['debt.seller.paid_annual_rate'] = '0.12'
        values['debt.seller.payment_cap'] = '0.005'
        values['available_cash'][1] = '0.005'
        run = run_stack((loan,), values)
        self.assertLessEqual(run.value('debt.seller.debt_service', month=1), Decimal('0.005'))

    def test_annual_cash_flow_periods_do_not_pay_principal_in_a_zero_accrual_period(self):
        model = Model('synthetic-annual-financing', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('year', [Item(i, period=i) for i in range(3)]))
        model.input('cash', unit='USD', dims=('year',))
        model.input('accrual_fraction', unit='ratio', dims=('year',))
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_loan(model, LoanTerms('soft', 0, 0, 12, None, 'cash_flow_principal', False),
                     given, prefix='financing.soft', period_dim='year', cash_available=ref('cash'),
                     accrual_fraction=ref('accrual_fraction'), rounding_places=None)
        values = {'cash': {i: '100' for i in range(3)}, 'accrual_fraction': {0: '0', 1: '0.5', 2: '1'},
                  'financing.soft.amount': '1000', 'financing.soft.annual_rate': '0.12',
                  'financing.soft.paid_annual_rate': '0.12', 'financing.soft.payment_cap': '0',
                  'financing.soft.cash_flow_fraction': {i: '1' for i in range(3)}}
        run = evaluate(model, values)
        self.assertEqual(run.value('financing.soft.principal', year=0), Decimal('0'))
        self.assertEqual(run.value('financing.soft.interest', year=1), Decimal('60'))
        self.assertEqual(run.value('financing.soft.ending_balance', year=1), Decimal('960'))
        self.assertEqual(run.value('financing.soft.interest_accrued', year=2), Decimal('15.2'))

    def test_interest_only_loan_pays_a_balloon_and_reports_scheduled_shortfalls(self):
        loan = LoanTerms('senior', 1, 1, 12, 3, 'interest_only', False)
        values = {'available_cash': {m: '0' for m in range(5)},
                  'debt.senior.amount': '1000', 'debt.senior.annual_rate': '0.12'}
        run = run_stack((loan,), values)
        self.assertEqual(run.value('debt.interest_paid', month=1), Decimal('10'))
        self.assertEqual(run.value('debt.principal', month=1), Decimal('0'))
        self.assertEqual(run.value('debt.debt_service', month=3), Decimal('1010'))
        self.assertEqual(run.value('debt.cash_after_payments', month=3), Decimal('-1010'))
        self.assertEqual(run.value('debt.total_owed', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.interest', month=4), Decimal('0'))

    def test_negative_cash_budget_is_visible_and_never_becomes_a_negative_payment(self):
        loan = LoanTerms('seller', 1, 1, 12, None, 'cash_flow_principal', False)
        values = {'available_cash': {m: '-100' for m in range(5)},
                  'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0.12',
                  'debt.seller.paid_annual_rate': '0.12', 'debt.seller.payment_cap': '0',
                  'debt.seller.cash_flow_fraction': {m: '0.5' for m in range(5)}}
        run = run_stack((loan,), values)
        self.assertEqual(run.value('debt.seller.payment_budget', month=1), Decimal('-50'))
        self.assertEqual(run.value('debt.seller.debt_service', month=1), Decimal('0'))
        self.assertEqual(run.value('debt.seller.total_owed', month=1), Decimal('1010'))

    def test_accrual_only_debt_and_contingent_payment_dates_are_explicit(self):
        loans = (LoanTerms('deferred', 1, 2, 12, None, 'accrual', True),)
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.deferred.amount': '100', 'debt.deferred.annual_rate': '0.12'}
        run = run_stack(loans, values)
        self.assertEqual(run.value('debt.debt_service', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.total_owed', month=4), Decimal('104.06'))
        self.assertEqual(run.value('debt.interest', month=2), Decimal('1.01'))
        for changes in ({'advance_month': True}, {'first_payment_month': 0},
                        {'name': 'bad name'}, {'repayment': 'unknown'},
                        {'maturity_month': 1}):
            from dataclasses import replace
            with self.subTest(changes=changes), self.assertRaises(ModelDefinitionError):
                replace(loans[0], **changes)
        with self.assertRaises(ModelDefinitionError):
            run_stack((loans[0], loans[0]), values)

    def test_rounding_cannot_exceed_a_subcent_interest_payment_ceiling(self):
        loan = LoanTerms('seller', 1, 1, 12, None, 'cash_flow_interest', False)
        values = {'available_cash': {m: '100' for m in range(5)},
                  'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0.12',
                  'debt.seller.paid_annual_rate': '0.000005', 'debt.seller.payment_cap': '0',
                  'debt.seller.cash_flow_fraction': {m: '1' for m in range(5)}}
        run = run_stack((loan,), values)
        self.assertEqual(run.value('debt.seller.interest_paid', month=1), Decimal('0.005'))
        self.assertEqual(run.value('debt.seller.interest_accrued', month=1), Decimal('9.995'))
