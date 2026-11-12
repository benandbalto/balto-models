"""Shared explicit construction draws, principal settlement and interest.

Callers supply draw timing and facility assumptions. This declaration owns the
principal schedule and performs no I/O or separate numeric calculation.
"""
import re

from . import ModelDefinitionError, const, if_, matches, previous, ref, round_to, sum_over


def _before_period(period_dim, periods, cutoff):
    """Select reviewed periods without mutating shared dimension metadata."""
    selectors = [if_(matches(period_dim, period=period), const(1), const(0))
                 for period in periods if period < cutoff]
    while len(selectors) > 1:
        selectors = [selectors[i] + selectors[i + 1] if i + 1 < len(selectors)
                     else selectors[i] for i in range(0, len(selectors), 2)]
    return selectors[0] if selectors else const(0)


def declare_construction_financing(model, given, *, draw_end_period, settlement_period,
                                   facility_dim='facility', period_dim='month',
                                   prefix='construction', rounding_places=2,
                                   repayment_amount=None, capitalization_end_period=None,
                                   interest_payment_lag=0, interest_settlement_period=None):
    """Accrue monthly interest on ending principal after explicit settlement.

    Draws stop before draw_end_period. Settlement occurs once in its separately
    reviewed period; repayment_amount can supply a reviewed facility expression,
    otherwise all drawn principal is repaid. A partial payoff leaves principal
    outstanding and continues accruing interest. Interest uses principal after
    same-period draws and repayment.
    None precision preserves full precision; the default rounds each accrual to
    cents, with no further rounding when paying accumulated interest.

    capitalization_end_period is exclusive; None classifies all interest as a
    capitalized cost. This classification never increases loan principal. Cash
    payment follows the explicit zero-to-twelve-period interest_payment_lag.
    Accruals beyond the cash forecast remain visible in interest_owed; no final
    payment is invented. An elected interest_settlement_period clears all unpaid
    accruals once and requires no interest accrual thereafter. Cost classification
    does not truncate cash payments or extinguish interest payable.
    """
    if (not isinstance(prefix, str) or re.fullmatch(r'[a-z][a-z0-9_.]{0,127}', prefix) is None
            or facility_dim == period_dim or facility_dim not in model.dimensions
            or period_dim not in model.dimensions
            or (rounding_places is not None and (type(rounding_places) is not int or rounding_places != 2))):
        raise ModelDefinitionError('Construction financing requires distinct declared dimensions and cents or full precision.')
    periods = [item.attrs.get('period') for item in model.dimensions[period_dim].items]
    if (not periods or any(type(period) is not int for period in periods)
            or periods != list(range(periods[0], periods[0] + len(periods)))
            or any(type(period) is not int or period not in periods or period <= periods[0]
                   for period in (draw_end_period, settlement_period))
            or settlement_period < draw_end_period):
        raise ModelDefinitionError('Construction financing requires contiguous periods, a draw cutoff and subsequent settlement.')
    if capitalization_end_period is not None and (type(capitalization_end_period) is not int
            or not periods[0] <= capitalization_end_period <= periods[-1] + 1):
        raise ModelDefinitionError('Construction interest capitalization requires an explicit in-horizon cutoff.')
    if type(interest_payment_lag) is not int or not 0 <= interest_payment_lag <= 12:
        raise ModelDefinitionError('Construction cash interest requires a whole payment lag from zero to twelve periods.')
    if interest_settlement_period is not None and (type(interest_settlement_period) is not int
            or interest_settlement_period not in periods or interest_settlement_period < settlement_period):
        raise ModelDefinitionError('Interest settlement must occur in the forecast at or after principal settlement.')
    dims = (facility_dim, period_dim)
    given(prefix + '.commitment', 'USD', (facility_dim,))
    given(prefix + '.annual_rate', 'nominal_ratio/year', (facility_dim,), high='0.3')
    given(prefix + '.draw', 'USD', dims)
    # A balanced expression avoids recursion depth proportional to the horizon
    # and does not mutate caller-owned period metadata.
    active = _before_period(period_dim, periods, draw_end_period)
    settlement = matches(period_dim, period=settlement_period)
    model.check(prefix + '.draw_period', dims=dims,
                condition=if_(active == 1, const(0), ref(prefix + '.draw')) == 0,
                code='DRAW_AFTER_CONVERSION', message='Construction facilities cannot draw at or after their draw cutoff.')
    model.calc(prefix + '.total_draw', unit='USD', dims=(facility_dim,),
               expr=sum_over(period_dim, ref(prefix + '.draw')))
    amount = ref(prefix + '.total_draw') if repayment_amount is None else repayment_amount
    model.calc(prefix + '.repayment', unit='USD', dims=dims,
               expr=if_(settlement, amount, const(0)))
    model.calc(prefix + '.ending_balance', unit='USD', dims=dims,
               expr=previous(prefix + '.ending_balance', period_dim,
                             initial=ref(prefix + '.draw') - ref(prefix + '.repayment'),
                             step=lambda prior: prior + ref(prefix + '.draw') - ref(prefix + '.repayment')))
    model.calc(prefix + '.opening_balance', unit='USD', dims=dims,
               expr=ref(prefix + '.ending_balance') - ref(prefix + '.draw') + ref(prefix + '.repayment'))
    model.check(prefix + '.repayment_limit', dims=dims,
                condition=ref(prefix + '.ending_balance') >= 0,
                code='CONSTRUCTION_REPAYMENT_EXCEEDS_PRINCIPAL', message='Construction repayment exceeds outstanding principal.')
    model.check(prefix + '.nonnegative_repayment', dims=dims,
                condition=ref(prefix + '.repayment') >= 0,
                code='INVALID_CONSTRUCTION_REPAYMENT', message='Construction repayment cannot be negative.')
    model.check(prefix + '.commitment_limit', dims=dims,
                condition=ref(prefix + '.opening_balance') + ref(prefix + '.draw') <= ref(prefix + '.commitment'),
                code='CONSTRUCTION_COMMITMENT_EXCEEDED', message='Construction debt exceeds its commitment.')
    interest = ref(prefix + '.ending_balance') * ref(prefix + '.annual_rate') / 12
    model.calc(prefix + '.interest', unit='USD', dims=dims,
               expr=interest if rounding_places is None else round_to(interest, rounding_places))
    capitalized = (ref(prefix + '.interest') if capitalization_end_period is None else
                   if_(_before_period(period_dim, periods, capitalization_end_period) == 1,
                       ref(prefix + '.interest'), const(0)))
    model.calc(prefix + '.capitalized_interest', unit='USD', dims=dims, expr=capitalized)
    model.calc(prefix + '.operating_interest', unit='USD', dims=dims,
               expr=ref(prefix + '.interest') - ref(prefix + '.capitalized_interest'))
    lag_names = [prefix + '.interest']
    for lag in range(1, interest_payment_lag + 1):
        name = prefix + f'.interest_lag_{lag}'
        model.calc(name, unit='USD', dims=dims,
                   expr=previous(lag_names[-1], period_dim, initial=const(0)))
        lag_names.append(name)
    # Each unpaid accrual cohort is referenced once. This avoids cancellation
    # in a running accrued-minus-cash balance at full decimal precision.
    unpaid = const(0)
    for name in lag_names[:-1]:
        unpaid = unpaid + ref(name)
    cash = ref(lag_names[-1])
    if interest_settlement_period is not None:
        before_settlement = _before_period(period_dim, periods, interest_settlement_period) == 1
        at_settlement = matches(period_dim, period=interest_settlement_period)
        cash = if_(before_settlement, cash,
                   if_(at_settlement, unpaid + cash, const(0)))
        unpaid = if_(before_settlement, unpaid, const(0))
        model.check(prefix + '.interest_after_settlement', dims=dims,
                    condition=if_(_before_period(period_dim, periods, interest_settlement_period + 1) == 1,
                                  const(0), ref(prefix + '.interest')) == 0,
                    code='INTEREST_AFTER_SETTLEMENT', message='Interest cannot accrue after its final settlement.')
    model.calc(prefix + '.cash_interest', unit='USD', dims=dims, expr=cash)
    model.calc(prefix + '.ending_interest_payable', unit='USD', dims=dims,
               expr=unpaid)
    model.calc(prefix + '.opening_interest_payable', unit='USD', dims=dims,
               expr=previous(prefix + '.ending_interest_payable', period_dim, initial=const(0)))
    model.calc(prefix + '.interest_owed', unit='USD', dims=(facility_dim,),
               expr=sum_over(period_dim, if_(matches(period_dim, period=periods[-1]),
                                            ref(prefix + '.ending_interest_payable'), const(0))))
