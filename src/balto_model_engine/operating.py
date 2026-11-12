"""Composable operating-budget expressions, shared by the operating and acquisition models.

These builders declare formulas; they never round, choose assumptions, change
income definitions. Each model owns its periods and policies.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .expressions import Expr, ref, sum_within
from .model import Model, ModelDefinitionError


def annual_per_unit(amount: Expr, units: Expr, periods: int = 12) -> Expr:
    return amount * units / periods


def annual_fixed(amount: Expr, periods: int = 12) -> Expr:
    return amount / periods


def monthly_per_unit(amount: Expr, units: Expr, *, occupancy: Expr | None = None) -> Expr:
    """Monthly cost on total units, optionally scaled to occupied units."""
    cost = amount * units
    return cost if occupancy is None else cost * occupancy


def percentage_of(basis: Expr, rate: Expr) -> Expr:
    """Cost on a caller-selected income or expense basis; rates are fractions."""
    return basis * rate


def build_payroll_fte(model: Model, *, prefix: str, role_dim: str) -> None:
    """Allocate headcount and salary; caller declares sourced inputs/dimensions."""
    def r(name: str) -> Expr:
        return ref(f'{prefix}.{name}')

    model.calc(f'{prefix}.fte', unit='headcount', dims=(role_dim,),
               expr=r('head_count') * r('allocation') * r('fte_percent') / 100)
    model.calc(f'{prefix}.effective_fte_percent', unit='percent', dims=(role_dim,), expr=r('fte') * 100)
    model.calc(f'{prefix}.effective', unit='usd_per_year', dims=(role_dim,),
               expr=r('base_pay') * r('fte'))


def build_payroll_costs(model: Model, *, prefix: str, role_dim: str, component_dim: str) -> None:
    """Load allocated salary, including itemized child costs grouped by bucket.

    Requires build_payroll_fte and caller-declared component inputs. Fixed costs
    scale with FTE; percentage costs use allocated salary. Bonus components may
    use fixed or base amounts, never base-plus-bonus (which would form a cycle).
    Caller validates methods and retains source paths and reporting categories.
    """
    def r(name: str) -> Expr:
        return ref(f'{prefix}.{name}')

    model.calc(f'{prefix}.component.before_bonus', unit='usd_per_year', dims=(component_dim,),
               expr=r('component.fixed_annual') * r('fte')
                    + r('component.percent_base') * r('effective'))
    for part, default in (('base', r('effective')),
                          ('bonus', r('effective') * r('bonus_rate')),
                          ('tax', (r('effective') + r('bonus')) * r('tax_rate')),
                          ('benefits', r('effective') * r('benefits_rate'))):
        expr = default + sum_within(component_dim, r('component.before_bonus'), bucket=part)
        if part != 'bonus':
            expr = expr + (r('effective') + r('bonus')) * sum_within(
                component_dim, r('component.percent_base_bonus'), bucket=part)
        model.calc(f'{prefix}.{part}', unit='usd_per_year', dims=(role_dim,), expr=expr)
    model.calc(f'{prefix}.component.amount', unit='usd_per_year', dims=(component_dim,),
               expr=r('component.before_bonus')
                    + r('component.percent_base_bonus') * (r('effective') + r('bonus')))
    model.calc(f'{prefix}.total', unit='usd_per_year', dims=(role_dim,),
               expr=r('base') + r('bonus') + r('tax') + r('benefits'))


def build_noi(model: Model, *, income: Expr, expenses: Expr, name: str,
              dims: tuple[str, ...] = ()) -> None:
    """Operating income less operating expense; reserves and debt are separate."""
    model.calc(name, unit='usd', dims=dims, expr=income - expenses)


@dataclass(frozen=True)
class OperatingProjection:
    """Dated property operations in USD, before reserves, capex and debt.

    Expressions reference the model's canonical variables, retaining their
    sources and lineage. Income lines carry their signed effects on income;
    expense lines carry positive costs. Totals are explicit caller expressions,
    so this contract does not reinterpret a model's accounting policy.
    """
    period_dim: str
    date_attr: str
    units: Expr
    income_lines: tuple[Expr, ...]
    expense_lines: tuple[Expr, ...]
    income: Expr
    expenses: Expr
    noi: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


@dataclass(frozen=True)
class OperatingCashFlow:
    """An operating projection with an explicit reserve deduction, before debt."""
    projection: OperatingProjection
    reserves: Expr
    amount: Expr


def build_operating_projection(model: Model, *, period_dim: str, units: Expr,
                               income_lines: tuple[Expr, ...], expense_lines: tuple[Expr, ...],
                               income: Expr, expenses: Expr, noi_name: str,
                               date_attr: str = 'date') -> OperatingProjection:
    """Declare NOI and expose the model's dated operating expressions."""
    period = model.dimensions.get(period_dim)
    if period is None or not period.items or any(
        isinstance(item.attrs.get(date_attr), bool)
        or not isinstance(item.attrs.get(date_attr), (int, float, Decimal))
        or not Decimal(str(item.attrs[date_attr])).is_finite()
        for item in period.items
    ):
        raise ModelDefinitionError('An operating projection requires periods with finite numeric dates.')
    build_noi(model, income=income, expenses=expenses, name=noi_name, dims=(period_dim,))
    return OperatingProjection(period_dim, date_attr, units, income_lines, expense_lines,
                               income, expenses, ref(noi_name))


def build_operating_cash_flow(model: Model, *, projection: OperatingProjection,
                              reserves: Expr, name: str) -> OperatingCashFlow:
    """Keep reserve policy with the caller and declare cash flow before debt."""
    model.calc(name, unit='usd', dims=(projection.period_dim,), expr=projection.noi - reserves)
    return OperatingCashFlow(projection, reserves, ref(name))
