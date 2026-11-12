"""Commercial space leased under its own terms, shared by the acquisition and operating models.

Each space is leased on its own schedule, not as a share of apartment
occupancy. The in-place lease earns its base rent, stepping up by its bump each
year in its anniversary month, until it expires (or, when its options are
exercised, until the options run out, at the same bumps). The space then rolls
over as an expected value, as the residential model treats turnover:

- with the renewal probability, the tenant renews at market rent at once;
- otherwise the space is dark for the downtime months, carrying the TI and
  leasing commissions at rollover, then a new tenant pays market rent.

Second-generation leases bump on their own anniversaries and run to the end of
the projection: one rollover per space. A NNN tenant reimburses its share of
the recoverable costs the caller names (property tax, insurance) while
occupied; a gross tenant reimburses nothing. Commercial credit loss is a rate on
commercial rent and recoveries, independent of residential vacancy.

The caller owns the period dimension, its index (1 for the first operating
period), its calendar month, which periods operate, and which costs are
recoverable. Leasing costs are capital: callers keep them out of NOI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .expressions import Expr, attr, const, if_, lag, matches, power, ref, round_to, sum_over
from .model import Dimension, Item, Model, ModelDefinitionError

LEASE_TYPES = ('gross', 'nnn')
# The per-space inputs, scalar inputs and their bounds, in the order a workbook shows them.
SPACE_INPUTS = (
    ('rent', 'usd/year', 0, None), ('bump', 'rate/year', -0.2, 0.5), ('bump_month', 'month_of_year', 1, 12),
    ('expiry_month', 'month', 0, None), ('option_exercised', 'flag', 0, 1), ('option_months', 'month', 0, None),
    ('renewal_probability', 'rate', 0, 1), ('market_rent', 'usd/sf-year', 0, None),
    ('downtime_months', 'month', 0, 60), ('ti', 'usd/sf', 0, None), ('lc', 'usd/sf', 0, None),
)
SCALAR_INPUTS = (
    ('market_growth', 'rate/year', -0.2, 0.5), ('new_lease_bump', 'rate/year', -0.2, 0.5),
    ('credit_loss_rate', 'rate', 0, 1),
)


@dataclass(frozen=True)
class CommercialSpace:
    """A leasable commercial space: its rentable area and how its lease shares costs."""
    key: str
    label: str
    sf: int
    lease_type: str

    def __post_init__(self) -> None:
        if self.lease_type not in LEASE_TYPES:
            raise ValueError(f'Commercial space {self.key} is leased gross or nnn.')
        if type(self.sf) is not int or not 0 < self.sf <= 10_000_000:
            raise ValueError(f'Commercial space {self.key} needs a whole positive square footage.')


@dataclass(frozen=True)
class CommercialIncome:
    """Per-period totals across spaces (zero when there are none)."""
    period_dim: str
    potential_rent: Expr
    downtime: Expr
    base_rent: Expr
    recoveries: Expr
    credit_loss: Expr
    income: Expr
    net_rent: Expr
    leasing_costs: Expr
    occupied_sf: Expr
    total_sf: Expr
    has_spaces: bool


def space_dimension(spaces: Sequence[CommercialSpace], name: str = 'space') -> Dimension:
    if len({s.key for s in spaces}) != len(spaces):
        raise ModelDefinitionError('Commercial space keys must be unique.')
    return Dimension(name, [Item(s.key, label=s.label, sf=s.sf, lease_type=s.lease_type) for s in spaces])


def declare_inputs(m: Model, *, prefix: str = 'commercial', space_dim: str = 'space') -> None:
    """Declare the lease inputs; a property without commercial space has none.

    Models with their own input conventions may declare the same names instead.
    """
    if not m.dimensions[space_dim].items:
        return
    for name, unit, low, high in SPACE_INPUTS:
        m.input(f'{prefix}.{name}', unit=unit, dims=(space_dim,), minimum=low, maximum=high)
    m.input(f'{prefix}.recovery_share', unit='rate', dims=(space_dim,), minimum=0, maximum=1,
            where={'lease_type': 'nnn'})
    for name, unit, low, high in SCALAR_INPUTS:
        m.input(f'{prefix}.{name}', unit=unit, minimum=low, maximum=high)
    for name in ('bump_month', 'expiry_month', 'option_months', 'downtime_months', 'option_exercised'):
        r = ref(f'{prefix}.{name}')
        m.check(f'{prefix}.{name}_whole', dims=(space_dim,), condition=r == round_to(r, 0), code='EVENT_NOT_WHOLE',
                message=f'{prefix}.{name} must be a whole number.')


def build_commercial_income(m: Model, *, prefix: str = 'commercial', space_dim: str = 'space',
                            period_dim: str = 'month', period_index: Expr, month_of_year: Expr,
                            active: Expr, recoverable_costs: Expr, money: str = 'usd') -> CommercialIncome:
    """Lease schedules by space and period, and their per-period totals.

    `period_index` counts periods from the lease inputs' month 0 (closing or
    budget start); expiry and downtime are in the same months. `active` is 1 in
    operating periods. `recoverable_costs` is the property's recoverable cost in
    the period; a NNN space reimburses `recovery_share` of it while occupied.
    """
    p, dims, period = prefix, (space_dim, period_dim), (period_dim,)

    def calc(name: str, expr: Expr, unit: str = money, on: tuple[str, ...] = dims) -> Expr:
        m.calc(f'{p}.{name}', unit=unit, dims=on, expr=expr)
        return ref(f'{p}.{name}')

    if not m.dimensions[space_dim].items:
        return income_refs(prefix, period_dim, has_spaces=False)

    i, live, r = period_index, active, lambda n: ref(f'{p}.{n}')
    sf = attr(space_dim, 'sf')
    m.calc(f'{p}.lease_end', unit='month', dims=(space_dim,),
           expr=r('expiry_month') + r('option_exercised') * r('option_months'))
    m.calc(f'{p}.rollover_month', unit='month', dims=(space_dim,), expr=r('lease_end') + 1)
    m.calc(f'{p}.new_lease_month', unit='month', dims=(space_dim,), expr=r('rollover_month') + r('downtime_months'))
    renew, replace = r('renewal_probability'), 1 - r('renewal_probability')

    # The in-place lease's rent steps up in its anniversary month while operating.
    step = if_(month_of_year == r('bump_month'), if_(live > 0, 1 + r('bump'), 1), 1)
    calc('scheduled_rent', lag(f'{p}.scheduled_rent', period_dim, initial=r('rent') / 12) * step)
    calc('in_place', if_(i <= r('lease_end'), live, 0), unit='flag')
    calc('contract_rent', r('scheduled_rent') * r('in_place'))
    calc('market_rent_now', r('market_rent') * sf / 12 * power(1 + r('market_growth'), i / 12))

    # A second-generation lease signs at market and bumps on its own anniversaries.
    for lease, start in (('renewal', r('rollover_month')), ('new', r('new_lease_month'))):
        year_month = f'{p}.{lease}_lease_year_month'
        m.calc(year_month, unit='month', dims=dims,
               expr=if_(i < start, 0, if_(i == start, 1, if_(lag(year_month, period_dim, initial=0) >= 12, 1,
                                                              lag(year_month, period_dim, initial=0) + 1))))
        rent = f'{p}.{lease}_rent'
        m.calc(rent, unit=money, dims=dims,
               expr=if_(i < start, 0, if_(i == start, r('market_rent_now'),
                                          lag(rent, period_dim, initial=0)
                                          * if_(ref(year_month) == 1, 1 + r('new_lease_bump'), 1))))

    after = lambda start: if_(i >= start, 1, 0)
    calc('base_rent', r('contract_rent') + (renew * r('renewal_rent') + replace * r('new_rent')) * live)
    calc('occupancy', r('in_place') + (renew * after(r('rollover_month'))
                                       + replace * after(r('new_lease_month'))) * live, unit='rate')
    calc('downtime', replace * r('market_rent_now') * after(r('rollover_month'))
         * (1 - after(r('new_lease_month'))) * live)
    calc('recoveries', if_(matches(space_dim, lease_type='nnn'),
                           r('recovery_share') * recoverable_costs * r('occupancy'), 0))
    calc('leasing_costs', if_(i == r('rollover_month'), replace * sf * (r('ti') + r('lc')), 0) * live)

    def total(name: str, body: Expr, unit: str = money) -> Expr:
        return calc(f'{name}_total', sum_over(space_dim, body), unit=unit, on=period)

    base = total('base_rent', r('base_rent'))
    downtime = total('downtime', r('downtime'))
    potential = calc('potential_rent', base + downtime, on=period)
    recoveries = total('recoveries', r('recoveries'))
    credit = calc('credit_loss', r('credit_loss_rate') * (base + recoveries), on=period)
    income = calc('income', base + recoveries - credit, on=period)
    # Base rent after credit loss: what a separate commercial cap rate values.
    net_rent = calc('net_rent', base * (1 - r('credit_loss_rate')), on=period)
    leasing = total('leasing_costs', r('leasing_costs'))
    occupied = total('occupied_sf', r('occupancy') * sf, unit='sf')
    m.calc(f'{p}.total_sf', unit='sf', expr=sum_over(space_dim, sf * 1))
    return income_refs(prefix, period_dim, has_spaces=True)


def income_refs(prefix: str = 'commercial', period_dim: str = 'month', *, has_spaces: bool) -> CommercialIncome:
    """The totals `build_commercial_income` declared, by name, for components built separately."""
    if not has_spaces:
        zero = const(0)
        return CommercialIncome(period_dim, zero, zero, zero, zero, zero, zero, zero, zero, zero, zero, False)
    r = lambda n: ref(f'{prefix}.{n}')
    return CommercialIncome(period_dim, r('potential_rent'), r('downtime_total'), r('base_rent_total'),
                            r('recoveries_total'), r('credit_loss'), r('income'), r('net_rent'),
                            r('leasing_costs_total'), r('occupied_sf_total'), r('total_sf'), True)
