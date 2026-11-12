"""Standalone monthly debt schedules and sizing through ordinary model runs."""
from decimal import Decimal
import unittest

from balto_model_engine import DecimalPolicy, Dimension, Item, Model, attr, evaluate, ref
from balto_model_engine.debt import build_debt_schedule, build_loan_sizing, build_payment_terms


def debt_model():
    m = Model('standalone-debt', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    m.dimension(Dimension('interval', [Item(f't{i}', ordinal=i) for i in range(8)]))
    for name in ('amount', 'rate', 'years', 'io', 'fund', 'retire', 'fee_rate'):
        m.input(name, unit='number')
    terms = build_payment_terms(m, prefix='bank', annual_rate=ref('rate'), amort_years=ref('years'))
    debt = build_debt_schedule(m, prefix='bank', period_dim='interval',
        period_index=attr('interval', 'ordinal'), amount=ref('amount'), terms=terms,
        fund_period=ref('fund'), payoff_period=ref('retire'), io_periods=ref('io'), fee_rate=ref('fee_rate'))
    m.calc('closing.copy', unit='usd', dims=(debt.period_dim,), expr=debt.balance)
    return m, debt


INPUTS = dict(amount=1200, rate=0, years=1, io=2, fund=1, retire=5, fee_rate='.01')


class DebtComponentTest(unittest.TestCase):
    def test_sizing_selects_ltv_or_dscr_and_excludes_unsupported_debt(self):
        m, debt = debt_model()
        for name in ('income', 'value', 'ltv', 'dscr', 'included'):
            m.input(name, unit='number')
        sized = build_loan_sizing(m, prefix='limit', income=ref('income'), value=ref('value'),
            max_ltv=ref('ltv'), min_dscr=ref('dscr'), payment_constant=debt.terms.payment_constant,
            included=ref('included'))
        m.calc('supported', unit='usd', expr=sized.amount)
        inputs = {**INPUTS, 'income': 100, 'value': 1000, 'ltv': '.7', 'dscr': 2, 'included': 1}
        r = evaluate(m, inputs)
        self.assertEqual(r.value('limit.ltv_amount'), 700)
        self.assertAlmostEqual(r.value('limit.dscr_amount'), Decimal(50), delta=Decimal('1e-30'))
        self.assertEqual(r.value('supported'), r.value('limit.dscr_amount'))
        high = evaluate(m, {**inputs, 'income': 2000})
        self.assertEqual(high.value('supported'), 700)
        for changes in ({'income': 0}, {'income': -100}, {'included': 0}):
            self.assertEqual(evaluate(m, {**inputs, **changes}).value('supported'), 0)
        # Without an inclusion flag, sizing is unconditional.
        build_loan_sizing(m, prefix='always', income=ref('income'), value=ref('value'),
            max_ltv=ref('ltv'), min_dscr=ref('dscr'), payment_constant=debt.terms.payment_constant)
        r = evaluate(m, {**inputs, 'included': 0})
        self.assertGreater(r.value('always.amount'), 0)

    def test_zero_rate_io_then_amortization_and_early_payoff_reconcile(self):
        m, debt = debt_model()
        r = evaluate(m, INPUTS)
        self.assertEqual(debt.currency, 'USD')
        self.assertEqual(debt.period_dim, 'interval')
        self.assertAlmostEqual(r.value('bank.payment'), Decimal(100), delta=Decimal('1e-30'))
        self.assertEqual(r.value('bank.fee'), 12)
        self.assertEqual(r.values['bank.funding'][('t1',)], 1200)
        self.assertEqual(r.values['bank.principal'][('t3',)], 0)
        self.assertAlmostEqual(r.values['bank.principal'][('t4',)], Decimal(100), delta=Decimal('1e-30'))
        self.assertAlmostEqual(r.values['bank.payoff'][('t5',)], Decimal(1000), delta=Decimal('1e-30'))
        for i in range(8):
            idx = (f't{i}',)
            self.assertEqual(r.values['bank.balance'][idx], r.values['closing.copy'][idx])
            self.assertEqual(r.values['bank.balance'][idx], r.values['bank.opening'][idx]
                + r.values['bank.funding'][idx] - r.values['bank.principal'][idx] - r.values['bank.payoff'][idx])
            self.assertEqual(r.values['bank.interest'][idx], 0)
        self.assertEqual(r.values['bank.balance'][('t5',)], 0)
        self.assertEqual(r.values['bank.balance'][('t7',)], 0)
        excluded = evaluate(m, {**INPUTS, 'amount': 0})
        for name in ('funding', 'interest', 'principal', 'payoff', 'balance', 'debt_service'):
            self.assertTrue(all(value == 0 for value in excluded.values[f'bank.{name}'].values()))
        interest = evaluate(m, {**INPUTS, 'rate': '.12'})
        self.assertEqual(interest.values['bank.interest'][('t1',)], 0)
        self.assertEqual(interest.values['bank.interest'][('t2',)], 12)
        self.assertEqual(interest.values['bank.debt_service'][('t3',)], 12)
        self.assertGreater(interest.values['bank.principal'][('t4',)], 0)
        self.assertEqual(interest.values['bank.balance'][('t5',)], 0)


if __name__ == '__main__':
    unittest.main()
