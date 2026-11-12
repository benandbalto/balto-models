"""Full-month, single-funding debt formulas and explicit output contracts.

Callers own sourced inputs, bounds, whole-period/event validation and coverage.
These components neither round nor infer dates, stub interest, draws or rates.
"""
from dataclasses import dataclass, field
from typing import Literal

from .expressions import Expr, const, if_, lag, max_, min_, power, ref, round_to
from .model import Model


@dataclass(frozen=True)
class PaymentTerms:
    monthly_rate: Expr
    payment_constant: Expr


def build_payment_terms(model: Model, *, prefix: str, annual_rate: Expr,
                        amort_years: Expr) -> PaymentTerms:
    """Monthly annual-rate/12 and payment per dollar over 12*years periods.

    Requires a nonnegative annual rate and positive amortization term. An
    exactly zero rate uses 1/n without evaluating the positive-rate formula.
    """
    monthly = ref(f'{prefix}.monthly_rate')
    constant = ref(f'{prefix}.payment_constant')
    model.calc(f'{prefix}.monthly_rate', unit='rate', expr=annual_rate / 12)
    model.calc(f'{prefix}.payment_constant', unit='rate',
        expr=if_(monthly > 0, monthly / (1 - power(1 + monthly, -12 * amort_years)),
                 1 / (12 * amort_years)))
    return PaymentTerms(monthly, constant)


@dataclass(frozen=True)
class DebtSchedule:
    period_dim: str
    amount: Expr
    terms: PaymentTerms
    payment: Expr
    fee: Expr
    opening: Expr
    funding: Expr
    interest: Expr
    principal: Expr
    payoff: Expr
    balance: Expr
    debt_service: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_debt_schedule(model: Model, *, prefix: str, period_dim: str,
                        period_index: Expr, amount: Expr, terms: PaymentTerms,
                        fund_period: Expr, payoff_period: Expr, io_periods: Expr,
                        fee_rate: Expr | None = None) -> DebtSchedule:
    """One funding, IO then level payment, remaining principal paid at payoff.

    Periods must be ordered consecutive months. Funding earns no interest in
    its period; interest uses the prior closing balance. Scheduled principal
    starts strictly after fund_period + io_periods and is capped at opening
    principal. Payoff follows that period's scheduled principal. Events must
    be distinct, whole, covered periods with payoff after funding; the caller
    validates them. Excluded loans pass zero amount. Optional fee is an amount
    on funding principal (zero when omitted); the caller places it in its
    cash ledger.
    """
    def r(name: str) -> Expr:
        return ref(f'{prefix}.{name}')

    dims = (period_dim,)
    model.calc(f'{prefix}.payment', unit='usd', expr=amount * terms.payment_constant)
    fee = const(0)
    if fee_rate is not None:
        model.calc(f'{prefix}.fee', unit='usd', expr=amount * fee_rate)
        fee = r('fee')
    model.calc(f'{prefix}.opening', unit='usd', dims=dims, expr=lag(f'{prefix}.balance', period_dim, initial=0))
    model.calc(f'{prefix}.funding', unit='usd', dims=dims, expr=if_(period_index == fund_period, amount, 0))
    model.calc(f'{prefix}.interest', unit='usd', dims=dims, expr=r('opening') * terms.monthly_rate)
    model.calc(f'{prefix}.principal', unit='usd', dims=dims,
        expr=if_(period_index > fund_period + io_periods,
                 min_(max_(r('payment') - r('interest'), 0), r('opening')), 0))
    model.calc(f'{prefix}.payoff', unit='usd', dims=dims,
        expr=if_(period_index == payoff_period, r('opening') - r('principal'), 0))
    model.calc(f'{prefix}.balance', unit='usd', dims=dims,
        expr=r('opening') + r('funding') - r('principal') - r('payoff'))
    model.calc(f'{prefix}.debt_service', unit='usd', dims=dims, expr=r('interest') + r('principal'))
    return DebtSchedule(period_dim, amount, terms, r('payment'), fee, r('opening'),
        r('funding'), r('interest'), r('principal'), r('payoff'), r('balance'), r('debt_service'))


@dataclass(frozen=True)
class LoanSizing:
    ltv_amount: Expr | None
    dscr_amount: Expr
    amount: Expr


def build_loan_sizing(model: Model, *, prefix: str, income: Expr, value: Expr | None,
                      max_ltv: Expr | None, min_dscr: Expr, payment_constant: Expr,
                      included: Expr | None = None, fee_rate: Expr | None = None,
                      prior_payments: Expr | None = None, increment: Expr | None = None,
                      maximum: Expr | None = None) -> LoanSizing:
    """Nonnegative lesser of LTV and annual eligible cash / DSCR / 12 / payment.

    Caller selects annual cash and valuation bases, validates positive DSCR and
    payment constant, and supplies a numeric 0/1 inclusion flag if conditional.
    IO does not relax sizing: the amortizing payment constant is used.

    Affordable-lender options, each absent unless supplied:

    - `value`/`max_ltv` None: no LTV constraint (DSCR sizing only).
    - `fee_rate`: an annual fee per dollar of original principal (issuer,
      servicing or MIP) inside the covered debt service.
    - `prior_payments`: annual must-pay obligations ahead of this loan (a soft
      lender's mandatory payment). Coverage applies to them too: the payment
      capacity is income / DSCR - prior payments.
    - `increment`: the amount rounds down to a multiple (1,000 for a bond).
    - `maximum`: the lender's commitment cap, applied after rounding.
    """
    if (value is None) != (max_ltv is None):
        raise ValueError('An LTV constraint needs both a value and a maximum LTV.')
    ltv = ref(f'{prefix}.ltv_amount') if value is not None else None
    dscr = ref(f'{prefix}.dscr_amount')
    if ltv is not None:
        model.calc(f'{prefix}.ltv_amount', unit='usd', expr=max_ltv * value)
    if fee_rate is None and prior_payments is None:
        model.calc(f'{prefix}.dscr_amount', unit='usd', expr=income / min_dscr / 12 / payment_constant)
    else:
        model.calc(f'{prefix}.annual_constant', unit='rate',
                   expr=12 * payment_constant + (fee_rate if fee_rate is not None else 0))
        model.calc(f'{prefix}.payment_capacity', unit='usd',
                   expr=income / min_dscr - (prior_payments if prior_payments is not None else 0))
        model.calc(f'{prefix}.dscr_amount', unit='usd',
                   expr=ref(f'{prefix}.payment_capacity') / ref(f'{prefix}.annual_constant'))
    amount = max_(min_(ltv, dscr), 0) if ltv is not None else max_(dscr, 0)
    if increment is not None:
        # ROUND_HALF_UP(x - 0.5) is FLOOR(x) for nonnegative x, in Python and Excel alike.
        amount = round_to(amount / increment - const('0.5'), 0) * increment
    if maximum is not None:
        amount = min_(amount, maximum)
    model.calc(f'{prefix}.amount', unit='usd', expr=amount if included is None else included * amount)
    return LoanSizing(ltv, dscr, ref(f'{prefix}.amount'))


@dataclass(frozen=True)
class PeriodAmortization:
    """A level-payment loan amortizing monthly, reported in longer (annual) periods."""
    period_dim: str
    amount: Expr
    terms: PaymentTerms
    months: Expr
    opening: Expr
    payments: Expr
    interest: Expr
    principal: Expr
    closing: Expr
    fee: Expr
    debt_service: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_period_amortization(model: Model, *, prefix: str, period_dim: str, amount: Expr,
                              terms: PaymentTerms, months: Expr, fee: Expr | None = None) -> PeriodAmortization:
    """Monthly amortization summed into each period of `period_dim` in closed form.

    `months` is the number of monthly payments in each period (12 in a full
    year, fewer in a first year that converts mid-year, 0 before payments
    begin). The loan is outstanding at `amount` before its first period.
    `fee` is a caller-owned amount per period (an issuer fee on original
    principal, say), included in debt service. Nothing is rounded.
    """
    def r(name: str) -> Expr:
        return ref(f'{prefix}.{name}')

    dims = (period_dim,)
    rate, pmt = terms.monthly_rate, amount * terms.payment_constant
    model.calc(f'{prefix}.months', unit='month', dims=dims, expr=months)
    model.calc(f'{prefix}.opening', unit='usd', dims=dims, expr=lag(f'{prefix}.closing', period_dim, initial=amount))
    growth = power(1 + rate, r('months'))
    model.calc(f'{prefix}.closing', unit='usd', dims=dims,
               expr=max_(if_(rate > 0, r('opening') * growth - pmt * (growth - 1) / rate,
                             r('opening') - pmt * r('months')), 0))
    model.calc(f'{prefix}.principal', unit='usd', dims=dims, expr=r('opening') - r('closing'))
    model.calc(f'{prefix}.payments', unit='usd', dims=dims,
               expr=if_(r('opening') > 0, min_(pmt * r('months'), r('opening') * growth), 0))
    model.calc(f'{prefix}.interest', unit='usd', dims=dims, expr=r('payments') - r('principal'))
    model.calc(f'{prefix}.fee', unit='usd', dims=dims, expr=if_(r('opening') > 0, fee, 0) if fee is not None else const(0))
    model.calc(f'{prefix}.debt_service', unit='usd', dims=dims, expr=r('payments') + r('fee'))
    return PeriodAmortization(period_dim, amount, terms, r('months'), r('opening'), r('payments'), r('interest'),
                              r('principal'), r('closing'), r('fee'), r('debt_service'))


@dataclass(frozen=True)
class DrawDebtSchedule:
    """End-period draws; interest on opening principal with an explicit day basis."""
    period_dim: str
    opening: Expr
    funding: Expr
    interest: Expr
    capitalized_interest: Expr
    cash_interest: Expr
    payoff: Expr
    balance: Expr
    unfunded: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_draw_debt(model: Model, *, prefix: str, period_dim: str,
                    eligible_spending: Expr, debt_share: Expr, commitment: Expr,
                    annual_rate: Expr, year_fraction: Expr, capitalize: Expr,
                    draw_allowed: Expr, payoff: Expr) -> DrawDebtSchedule:
    """Interest first, then eligible spending draws within a fixed commitment.

    Interest is opening balance * caller's period rate * year fraction. This
    end-period draw convention avoids a circular interest reserve. Requested
    capitalized interest consumes commitment before spending draws; interest
    beyond capacity is current-paid. The caller supplies 0/1 event flags,
    nonnegative rates/day fractions and commitment, share in [0,1], and owns
    loan eligibility, maturity, funding priority and fees. Unfunded draw requests
    remain an economic outcome, never a failed calculation.
    """
    dims = (period_dim,)
    def calc(name, expr):
        model.calc(f'{prefix}.{name}', unit='usd', dims=dims, expr=expr)
        return ref(f'{prefix}.{name}')
    opening = calc('opening', lag(f'{prefix}.balance', period_dim, initial=0))
    interest = calc('interest', opening * annual_rate * year_fraction)
    capacity = max_(commitment - opening, 0)
    capitalized = calc('capitalized_interest', min_(interest * capitalize, capacity))
    requested = calc('requested', max_(eligible_spending, 0) * debt_share * draw_allowed)
    funding = calc('funding', min_(requested, max_(capacity - capitalized, 0)))
    unfunded = calc('unfunded', requested - funding)
    cash_interest = calc('cash_interest', interest - capitalized)
    paid_off = calc('payoff', payoff * (opening + funding + capitalized))
    balance = calc('balance', opening + funding + capitalized - paid_off)
    return DrawDebtSchedule(period_dim, opening, funding, interest, capitalized,
                            cash_interest, paid_off, balance, unfunded)
