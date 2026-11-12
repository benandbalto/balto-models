"""Reusable loan schedules and ordered payments, declared in the shared engine.

Callers own available operating cash, evidence and tax classification. This
module owns financing balances and payments; it performs no I/O or numeric math.
"""
from dataclasses import dataclass
import re

from . import ModelDefinitionError, const, if_, lag, matches, previous, ref, round_to
from .financial import fixed_rate_payment, maximum, minimum


@dataclass(frozen=True)
class LoanTerms:
    name: str
    advance_month: int
    first_payment_month: int
    amortization_months: int
    maturity_month: int | None
    repayment: str
    compound_interest: bool
    mortgage_insurance_basis: str = "none"
    origination: str = "cash"
    paid_interest_basis: str = "annual"

    def __post_init__(self):
        if (not isinstance(self.name, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.name) is None
                or any(type(n) is not int or not 0 <= n <= 600
                       for n in (self.advance_month, self.first_payment_month))
                or self.first_payment_month < self.advance_month
                or type(self.amortization_months) is not int or not 1 <= self.amortization_months <= 600
                or (self.maturity_month is not None and (type(self.maturity_month) is not int
                    or not self.first_payment_month <= self.maturity_month <= 1200))
                or self.repayment not in ('amortizing', 'interest_only', 'accrual', 'cash_flow_interest', 'cash_flow_principal')
                or type(self.compound_interest) is not bool
                or self.mortgage_insurance_basis not in ('none', 'original', 'outstanding')
                or self.origination not in ('cash', 'noncash')
                or self.paid_interest_basis not in ('annual', 'accrual_period')):
            raise ModelDefinitionError('Loan terms require valid timing, repayment and a unique safe name.')
        if self.paid_interest_basis != 'annual' and not self.repayment.startswith('cash_flow'):
            raise ModelDefinitionError('A prorated paid-interest ceiling requires cash-flow debt.')
        if self.mortgage_insurance_basis != 'none' and self.repayment not in ('amortizing', 'interest_only'):
            raise ModelDefinitionError('Mortgage insurance requires scheduled debt.')
        if self.repayment in ('amortizing', 'interest_only') and self.compound_interest:
            raise ModelDefinitionError('Scheduled loans cannot compound unpaid interest.')
        if self.repayment not in ('amortizing', 'interest_only') and self.maturity_month is not None:
            raise ModelDefinitionError('Contingent loan payoff is a separate exit obligation.')


def declare_loan_stack(model, loans, given, *, cash_available, prefix='debt', period_dim='month',
                       advances_by_loan=None, rounding_places=2):
    """Declare monthly loans in payment-priority order.

    The caller's period dimension must expose contiguous integer indices as
    `period`. Operating cash excludes advances, equity and opening project cash;
    scheduled debt can create a shortfall, visible in cash_after_payments.
    advances_by_loan supplies period expressions for explicitly drawn contingent
    loans; absent names retain their one-time scalar origin. Explicit None for
    rounding_places preserves full precision throughout every loan in the stack.
    """
    if (not isinstance(loans, tuple) or not 1 <= len(loans) <= 20
            or any(not isinstance(loan, LoanTerms) for loan in loans)
            or len({loan.name for loan in loans}) != len(loans)):
        raise ModelDefinitionError('A loan stack requires one to twenty distinct loans.')
    if advances_by_loan is not None and (not isinstance(advances_by_loan, dict)
            or set(advances_by_loan) - {loan.name for loan in loans}
            or any(expr is None for expr in advances_by_loan.values())):
        raise ModelDefinitionError('Explicit advances must identify loans in the stack.')
    if rounding_places is not None and (type(rounding_places) is not int or rounding_places != 2):
        raise ModelDefinitionError('Loan stacks require cents or explicit full money precision.')
    cash = cash_available
    for loan in loans:
        p = prefix + '.' + loan.name
        declare_loan(model, loan, given, prefix=p, period_dim=period_dim, cash_available=cash,
                     advances=None if advances_by_loan is None else advances_by_loan.get(loan.name),
                     rounding_places=rounding_places)
        cash = ref(p + '.cash_after_payment')
    for name in ('advance', 'proceeds', 'noncash_proceeds', 'interest', 'interest_paid', 'interest_accrued', 'principal',
                 'debt_service', 'mortgage_insurance', 'ending_balance', 'accrued_interest_balance', 'total_owed'):
        expr = const(0)
        for loan in loans:
            expr = expr + ref(prefix + '.' + loan.name + '.' + name)
        model.calc(prefix + '.' + name, unit='USD', dims=(period_dim,), expr=expr)
    model.calc(prefix + '.cash_after_payments', unit='USD', dims=(period_dim,), expr=cash)


def declare_loan(model, loan, given, *, prefix, period_dim, cash_available,
                 accrual_fraction=None, scheduled_payment_months=None, rounding_places=2,
                 advances=None):
    """Declare one loan. Nonmonthly accrual is supported for contingent loans.

    `accrual_fraction` is the effective year fraction for contingent periods;
    default 1/12. Scheduled annual periods use whole `scheduled_payment_months`
    and full precision, retaining the same monthly annuity. None for
    rounding_places preserves worksheet precision for offline schedule audits.
    Explicit advances replace the scalar amount and may recur for contingent
    debt from advance_month onward. Origination selects cash proceeds or noncash
    cost deferral; both increase principal. Simple-interest arrears remain
    separately owed; cash-flow interest payments cover current interest only.
    """
    if (not isinstance(loan, LoanTerms) or (rounding_places is not None
            and (type(rounding_places) is not int or rounding_places != 2))):
        raise ModelDefinitionError('Loan declarations require valid terms and explicit money precision.')
    scheduled = loan.repayment in ('amortizing', 'interest_only')
    if scheduled and advances is not None:
        raise ModelDefinitionError('Recurrent advances require contingent debt.')
    if scheduled and accrual_fraction is not None:
        raise ModelDefinitionError('Scheduled loans require monthly periods.')
    if scheduled_payment_months is not None and (not scheduled or accrual_fraction is not None or rounding_places is not None):
        raise ModelDefinitionError('Annual scheduled payments require scheduled debt and full precision.')
    annual_schedule = scheduled_payment_months is not None
    fraction = (scheduled_payment_months / 12 if annual_schedule else
                const(1) / 12 if accrual_fraction is None else accrual_fraction)
    p, dims = prefix, (period_dim,)
    if advances is None:
        given(p + '.amount', 'USD')
    given(p + '.annual_rate', 'nominal_ratio/year', high='0.3')
    if loan.mortgage_insurance_basis != 'none':
        given(p + '.mortgage_insurance_annual_rate', 'nominal_ratio/year', high='0.3')
    if loan.repayment == 'amortizing':
        fixed_rate_payment(model, prefix=p, amount=p + '.amount', annual_rate=p + '.annual_rate',
                           term=loan.amortization_months, rounding_places=rounding_places)
    model.calc(p + '.advance', unit='USD', dims=dims,
               expr=advances if advances is not None else
                    if_(matches(period_dim, period=loan.advance_month), ref(p + '.amount'), const(0)))
    model.calc(p + '.proceeds', unit='USD', dims=dims,
               expr=ref(p + '.advance') if loan.origination == 'cash' else const(0))
    model.calc(p + '.noncash_proceeds', unit='USD', dims=dims,
               expr=ref(p + '.advance') if loan.origination == 'noncash' else const(0))
    active_attr = p + '.payment_active'
    periods = [item.attrs.get('period') for item in model.dimensions[period_dim].items]
    if (not periods or any(type(n) is not int for n in periods)
            or periods != list(range(periods[0], periods[0] + len(periods)))
            or loan.advance_month not in periods or loan.first_payment_month < periods[0]):
        raise ModelDefinitionError('Financing requires contiguous periods containing the advance.')
    advance_attr = p + '.advance_active'
    for item in model.dimensions[period_dim].items:
        item.attrs[advance_attr] = item.attrs['period'] >= loan.advance_month
        item.attrs[active_attr] = item.attrs['period'] >= loan.first_payment_month
    active = matches(period_dim, **{active_attr: True})
    if advances is not None:
        model.check(p + '.nonnegative_advance', dims=dims, condition=ref(p + '.advance') >= 0,
                    code='INVALID_LOAN_ADVANCE', message='Loan advances cannot be negative.')
        model.check(p + '.advance_timing', dims=dims,
                    condition=if_(matches(period_dim, **{advance_attr: True}), const(0), ref(p + '.advance')) == 0,
                    code='INVALID_LOAN_ADVANCE', message='Debt cannot originate before its advance period.')
    model.check(p + '.accrual_period', dims=dims, condition=fraction >= 0,
                code='INVALID_ACCRUAL_PERIOD', message='Interest accrual periods cannot be negative.')
    model.check(p + '.accrual_period_max', dims=dims, condition=fraction <= 1,
                code='INVALID_ACCRUAL_PERIOD', message='An interest accrual period cannot exceed one year.')
    if annual_schedule:
        valid_count = const(0)
        for count in range(13):
            valid_count = valid_count + if_(scheduled_payment_months == count, const(1), const(0))
        model.check(p + '.whole_payment_months', dims=dims, condition=valid_count == 1,
                    code='INVALID_PAYMENT_MONTHS', message='Scheduled periods require zero to twelve whole payments.')
        model.check(p + '.inactive_payment_months', dims=dims,
                    condition=if_(active, const(0), scheduled_payment_months) == 0,
                    code='INVALID_PAYMENT_MONTHS', message='Payments cannot precede the first payment period.')
        if loan.repayment == 'amortizing':
            model.calc(p + '.payments_made', unit='months', dims=dims,
                       expr=previous(p + '.payments_made', period_dim, initial=scheduled_payment_months,
                                     step=lambda prior: prior + scheduled_payment_months))
            model.check(p + '.payment_term', dims=dims, condition=ref(p + '.payments_made') <= loan.amortization_months,
                        code='PAYMENTS_EXCEED_TERM', message='Scheduled payments cannot exceed the amortization term.')
            # Annuity future value coefficients avoid a second numeric calculator
            # and work at zero rates, without division by the interest rate.
            model.calc(p + '.growth_0', unit='ratio', expr=const(1))
            model.calc(p + '.annuity_0', unit='ratio', expr=const(0))
            for count in range(1, 13):
                model.calc(p + f'.growth_{count}', unit='ratio',
                           expr=ref(p + f'.growth_{count - 1}') * (1 + ref(p + '.annual_rate') / 12))
                model.calc(p + f'.annuity_{count}', unit='ratio',
                           expr=ref(p + f'.annuity_{count - 1}') * (1 + ref(p + '.annual_rate') / 12) + 1)

    def money(expr):
        return expr if rounding_places is None else round_to(expr, rounding_places)

    model.calc(p + '.cash_before_payment', unit='USD', dims=dims, expr=cash_available)
    cash_flow = loan.repayment.startswith('cash_flow')
    if cash_flow:
        given(p + '.cash_flow_fraction', 'ratio', dims, high=1)
        given(p + '.paid_annual_rate', 'nominal_ratio/year', high='0.3')
        given(p + '.payment_cap', 'USD')
        model.calc(p + '.paid_interest_fraction', unit='ratio', dims=dims,
                   expr=fraction if loan.paid_interest_basis == 'accrual_period' else const(1))
        available = ref(p + '.cash_before_payment')
        share = money(available * ref(p + '.cash_flow_fraction'))
        budget = if_(available >= 0, minimum(available, share), share)
        budget = if_(ref(p + '.payment_cap') > 0, minimum(budget, ref(p + '.payment_cap')), budget)
    else:
        budget = const(0)
    model.calc(p + '.payment_budget', unit='USD', dims=dims, expr=if_(active, budget, const(0)))

    def scheduled_principal(balance):
        if not annual_schedule:
            return minimum(balance, maximum(ref(p + '.payment') - ref(p + '.interest'), const(0)))
        closing_balance = balance
        for count in range(1, 13):
            closing_balance = if_(scheduled_payment_months == count,
                balance * ref(p + f'.growth_{count}') - ref(p + '.payment') * ref(p + f'.annuity_{count}'),
                closing_balance)
        return minimum(balance, maximum(balance - closing_balance, const(0)))

    def interest(balance):
        if annual_schedule and loan.repayment == 'amortizing':
            return if_(balance > 0, maximum(const(0), ref(p + '.payment') * scheduled_payment_months - scheduled_principal(balance)), const(0))
        return money(balance * ref(p + '.annual_rate') * fraction)

    def paid_interest(balance):
        if scheduled:
            return if_(active, ref(p + '.interest'), const(0))
        if cash_flow:
            # Annual preserves the reviewed workbook ceiling. Proration is an
            # explicit contract election using this period's accrual fraction.
            limit = minimum(ref(p + '.interest'), balance * ref(p + '.paid_annual_rate')
                            * ref(p + '.paid_interest_fraction'))
            budget = ref(p + '.payment_budget')
            return maximum(const(0), minimum(budget, minimum(limit, money(minimum(budget, limit)))))
        return const(0)

    def principal(balance):
        if loan.repayment == 'amortizing':
            result = scheduled_principal(balance)
        elif loan.repayment == 'cash_flow_principal':
            result = if_(fraction > 0, minimum(balance, maximum(ref(p + '.payment_budget') - ref(p + '.interest_paid'), const(0))), const(0))
        else:
            result = const(0)
        if loan.maturity_month is not None:
            result = if_(matches(period_dim, period=loan.maturity_month), balance, result)
        return if_(active, result, const(0))

    # Keep the recurrence on the balance alone. Interest and principal are
    # shared calculation nodes, rather than repeated inside its transition.
    model.calc(p + '.ending_balance', unit='USD', dims=dims,
               expr=ref(p + '.opening_balance')
                    + (ref(p + '.interest_accrued') if loan.compound_interest else const(0))
                    - ref(p + '.principal'))
    model.calc(p + '.opening_balance', unit='USD', dims=dims,
               expr=lag(p + '.ending_balance', period_dim, initial=const(0)) + ref(p + '.advance'))
    model.calc(p + '.interest', unit='USD', dims=dims, expr=interest(ref(p + '.opening_balance')))
    model.calc(p + '.simple_interest', unit='USD', dims=dims,
               expr=money(ref(p + '.opening_balance') * ref(p + '.annual_rate') * fraction))
    model.calc(p + '.interest_paid', unit='USD', dims=dims, expr=paid_interest(ref(p + '.opening_balance')))
    model.calc(p + '.interest_accrued', unit='USD', dims=dims, expr=ref(p + '.interest') - ref(p + '.interest_paid'))
    model.calc(p + '.principal', unit='USD', dims=dims, expr=principal(ref(p + '.opening_balance')))
    insurance_basis = ref(p + '.amount') if loan.mortgage_insurance_basis == 'original' else ref(p + '.opening_balance')
    model.calc(p + '.mortgage_insurance', unit='USD', dims=dims,
               expr=const(0) if loan.mortgage_insurance_basis == 'none' else
                    if_(active, if_(ref(p + '.opening_balance') > 0,
                        money(insurance_basis * ref(p + '.mortgage_insurance_annual_rate') * fraction), const(0)), const(0)))
    model.calc(p + '.debt_service', unit='USD', dims=dims,
               expr=ref(p + '.interest_paid') + ref(p + '.principal') + ref(p + '.mortgage_insurance'))
    model.calc(p + '.accrued_interest_balance', unit='USD', dims=dims,
               expr=const(0) if loan.compound_interest else previous(p + '.accrued_interest_balance', period_dim,
                    initial=ref(p + '.interest_accrued'), step=lambda prior: prior + ref(p + '.interest_accrued')))
    model.calc(p + '.total_owed', unit='USD', dims=dims,
               expr=ref(p + '.ending_balance') + ref(p + '.accrued_interest_balance'))
    model.calc(p + '.cash_after_payment', unit='USD', dims=dims,
               expr=ref(p + '.cash_before_payment') - ref(p + '.debt_service'))
