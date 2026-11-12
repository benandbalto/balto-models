"""Bounded periodic IRR using the canonical engine expression evaluator.

Cash flows must change from negative to positive exactly once (zero periods
are allowed). This establishes one economically meaningful root. The declared
rate interval must bracket it; unsupported cash flows fail explicitly.
"""
from decimal import Decimal

from . import ModelDefinitionError, const, if_, previous, ref, sum_over


def declare_periodic_irr(model, *, cash_flow, period_dim, periods_per_year,
                         prefix='returns', lower='-0.99', upper='10', iterations=80):
    """Declare periodic/annual compounded IRR and its NPV residual.

    The dimension has contiguous integer ``period`` attributes starting at zero.
    Period zero is undiscounted. Bounds are structural reviewed rate limits,
    not search guesses. No root is returned outside the interval.
    """
    if (type(periods_per_year) is not int or not 1 <= periods_per_year <= 12
            or type(iterations) is not int or not 32 <= iterations <= 120
            or period_dim not in model.dimensions):
        raise ModelDefinitionError('Returns require a period dimension, annual frequency and 32–120 iterations.')
    items = model.dimensions[period_dim].items
    if (len(items) < 2 or any(type(i.attrs.get('period')) is not int for i in items)
            or [i.attrs.get('period') for i in items] != list(range(len(items)))):
        raise ModelDefinitionError('Return periods must be contiguous integers starting at zero.')
    if any(isinstance(v, (bool, float)) or not isinstance(v, (int, str, Decimal)) for v in (lower, upper)):
        raise ModelDefinitionError('IRR bounds must be exact decimal rates.')
    try:
        lo, hi = Decimal(lower), Decimal(upper)
    except Exception as exc:
        raise ModelDefinitionError('IRR bounds must be finite decimal rates.') from exc
    if not lo.is_finite() or not hi.is_finite() or not -1 < lo < hi <= 100:
        raise ModelDefinitionError('IRR bounds must satisfy -1 < lower < upper <= 100.')
    cf = ref(cash_flow)
    model.calc(prefix + '.negative_cash', unit='USD',
               expr=sum_over(period_dim, if_(cf < 0, -cf, const(0))))
    model.calc(prefix + '.positive_cash', unit='USD',
               expr=sum_over(period_dim, if_(cf > 0, cf, const(0))))
    for suffix in ('negative_cash', 'positive_cash'):
        model.check(prefix + '.' + suffix, condition=ref(prefix + '.' + suffix) > 0,
                    code='IRR_REQUIRES_SIGN_CHANGE', message='IRR requires negative and positive cash flows.')
    model.calc(prefix + '.positive_seen', unit='count', dims=(period_dim,),
               expr=previous(prefix + '.positive_seen', period_dim,
                             initial=if_(cf > 0, const(1), const(0)),
                             step=lambda p: if_(cf > 0, const(1), p)))
    model.calc(prefix + '.prior_positive', unit='count', dims=(period_dim,),
               expr=previous(prefix + '.positive_seen', period_dim, initial=0))
    model.check(prefix + '.conventional', dims=(period_dim,),
                condition=if_(cf < 0, ref(prefix + '.prior_positive'), const(0)) == 0,
                code='IRR_NONCONVENTIONAL_CASH_FLOW',
                message='IRR supports one change from negative to positive cash flows.')

    def npv(name, rate):
        model.calc(name + '.discount', unit='ratio', dims=(period_dim,),
                   expr=previous(name + '.discount', period_dim, initial=1,
                                 step=lambda p: p / (1 + rate)))
        model.calc(name + '.npv', unit='USD',
                   expr=sum_over(period_dim, cf * ref(name + '.discount')))
        return ref(name + '.npv')

    lower_npv = npv(prefix + '.lower', const(lo))
    upper_npv = npv(prefix + '.upper', const(hi))
    model.check(prefix + '.lower_bracket', condition=lower_npv >= 0,
                code='IRR_OUTSIDE_BRACKET', message='IRR is below the declared lower rate bound.')
    model.check(prefix + '.upper_bracket', condition=upper_npv <= 0,
                code='IRR_OUTSIDE_BRACKET', message='IRR is above the declared upper rate bound.')
    low, high = const(lo), const(hi)
    for i in range(iterations):
        name = prefix + '.iteration_' + str(i)
        model.calc(name + '.rate', unit='ratio', expr=(low + high) / 2)
        rate = ref(name + '.rate')
        residual = npv(name, rate)
        model.calc(name + '.low', unit='ratio', expr=if_(residual >= 0, rate, low))
        model.calc(name + '.high', unit='ratio', expr=if_(residual >= 0, high, rate))
        low, high = ref(name + '.low'), ref(name + '.high')
    model.calc(prefix + '.periodic_irr', unit='ratio', expr=(low + high) / 2)
    growth = const(1)
    for _ in range(periods_per_year):
        growth = growth * (1 + ref(prefix + '.periodic_irr'))
    model.calc(prefix + '.annual_irr', unit='ratio', expr=growth - 1)
    model.calc(prefix + '.npv', unit='USD',
               expr=npv(prefix + '.result', ref(prefix + '.periodic_irr')))
