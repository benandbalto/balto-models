"""Reusable annual operating projections evaluated by the canonical engine."""
from dataclasses import dataclass
import re

from . import Dimension, Item, ModelDefinitionError, const, if_, matches, previous, ref, round_to, sum_over


@dataclass(frozen=True)
class AnnualProjectionTerms:
    items: tuple[str, ...]
    rounding_places: int | None

    def __post_init__(self):
        if (not isinstance(self.items, tuple) or not 1 <= len(self.items) <= 200
                or any(not isinstance(name, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name) is None
                       for name in self.items)
                or len(set(self.items)) != len(self.items)
                or (self.rounding_places is not None and
                    (type(self.rounding_places) is not int or self.rounding_places not in (0, 2)))):
            raise ModelDefinitionError('Annual projections require distinct expense names and explicit precision.')


def declare_annual_projection(model, given, items, *, period_dim='tax_year',
                              prefix='expenses', rounding_places=0):
    """Grow full-year expenses, then prorate each modeled annual period.

    The first period's growth input must be zero. Later periods grow the prior
    full-year amount, rounding at each step when explicitly requested. The
    period fraction never affects the full-year amount used for future growth.
    None preserves full decimal precision. No inputs or sources are inferred.
    """
    terms = AnnualProjectionTerms(items, rounding_places)
    if period_dim not in model.dimensions:
        raise ModelDefinitionError('Annual projections require a declared period dimension.')
    periods = model.dimensions[period_dim].keys()
    if (not periods or any(type(period) is not int for period in periods)
            or periods != list(range(periods[0], periods[0] + len(periods)))):
        raise ModelDefinitionError('Annual projections require ascending contiguous integer periods.')
    model.dimension(Dimension('expense', [Item(name) for name in terms.items]))
    given(prefix + '.annual_base', 'USD', ('expense',))
    given(prefix + '.annual_growth', 'ratio', ('expense', period_dim), low=-1)
    given(prefix + '.period_fraction', 'ratio', (period_dim,), high=1)
    first_attr = prefix + '.first_projection'
    for i, item in enumerate(model.dimensions[period_dim].items):
        item.attrs[first_attr] = i == 0
    model.check(prefix + '.initial_growth', dims=('expense', period_dim),
                condition=if_(matches(period_dim, **{first_attr: True}), ref(prefix + '.annual_growth'), const(0)) == 0,
                code='INITIAL_PROJECTION_GROWTH_NOT_ZERO',
                message='The first annual projection period cannot grow its base.')

    def money(expr):
        return expr if terms.rounding_places is None else round_to(expr, terms.rounding_places)

    model.calc(prefix + '.full_amount', unit='USD', dims=('expense', period_dim),
               expr=previous(prefix + '.full_amount', period_dim, initial=ref(prefix + '.annual_base'),
                             step=lambda prior: money(prior * (1 + ref(prefix + '.annual_growth')))))
    model.calc(prefix + '.amount', unit='USD', dims=('expense', period_dim),
               expr=money(ref(prefix + '.full_amount') * ref(prefix + '.period_fraction')))
    model.calc(prefix + '.total', unit='USD', dims=(period_dim,),
               expr=sum_over('expense', ref(prefix + '.amount')))
