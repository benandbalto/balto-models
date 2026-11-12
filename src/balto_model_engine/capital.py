"""Capital budget and spending expressions with caller-owned timing and funding.

These builders declare ordinary model formulas in USD. Callers supply sourced
inputs, dimensions, line aggregation, rate bounds and rounding policy.
"""
from dataclasses import dataclass, field
from typing import Literal

from .expressions import Expr, if_, ref
from .model import Model


def quantity_cost(unit_cost: Expr, quantity: Expr) -> Expr:
    """Hard-cost line priced on an explicit quantity."""
    return unit_cost * quantity


@dataclass(frozen=True)
class CapitalBudget:
    """Phase costs with visible fee bases; no funding or timing assumptions."""
    phase_dim: str
    hard: Expr
    general_conditions: Expr
    gc_fee_basis: Expr
    gc_fee: Expr
    contingency_basis: Expr
    contingency: Expr
    total: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_capital_budget(model: Model, *, phase_dim: str, hard_costs: Expr,
                         general_conditions_rate: Expr, gc_fee_rate: Expr,
                         contingency_rate: Expr, hard_name: str,
                         general_conditions_name: str, gc_fee_name: str,
                         contingency_name: str, total_name: str) -> CapitalBudget:
    """GC fee uses hard + conditions; contingency also includes the GC fee.

    Hard costs are an explicit caller expression, allowing mixed fixed and
    quantity-priced lines without imposing input names or aggregation policy.
    No intermediate rounding is introduced.
    """
    dims = (phase_dim,)
    model.calc(hard_name, unit='usd', dims=dims, expr=hard_costs)
    hard = ref(hard_name)
    model.calc(general_conditions_name, unit='usd', dims=dims,
               expr=hard * general_conditions_rate)
    conditions = ref(general_conditions_name)
    fee_basis = hard + conditions
    model.calc(gc_fee_name, unit='usd', dims=dims, expr=fee_basis * gc_fee_rate)
    fee = ref(gc_fee_name)
    contingency_basis = hard + conditions + fee
    model.calc(contingency_name, unit='usd', dims=dims,
               expr=contingency_basis * contingency_rate)
    contingency = ref(contingency_name)
    model.calc(total_name, unit='usd', dims=dims, expr=hard + conditions + fee + contingency)
    return CapitalBudget(phase_dim, hard, conditions, fee_basis, fee,
                         contingency_basis, contingency, ref(total_name))


@dataclass(frozen=True)
class SpendingSchedule:
    """Budget spending on caller-selected periods, before funding decisions."""
    phase_dim: str
    period_dim: str
    budget: Expr
    amount: Expr


def build_even_spending(model: Model, *, phase_dim: str, period_dim: str,
                        budget: Expr, period_index: Expr, start: Expr,
                        periods: Expr, activity: Expr, name: str) -> SpendingSchedule:
    """Spend budget / periods from start (inclusive) to start + periods (exclusive).

    The caller supplies the period index and activity multiplier, validates a
    positive whole duration, and provides the full active horizon if full budget
    reconciliation is required. A shortened horizon or activity mask can leave
    unspent budget. No residual allocation or rounding is introduced.
    """
    model.calc(name, unit='usd', dims=(phase_dim, period_dim),
               expr=if_(period_index >= start,
                        if_(period_index < start + periods, budget / periods, 0), 0) * activity)
    return SpendingSchedule(phase_dim, period_dim, budget, ref(name))


def build_weighted_spending(model: Model, *, phase_dim: str, period_dim: str,
                            budget: Expr, weight: Expr, name: str) -> SpendingSchedule:
    """Explicit child periods of each phase; weights sum to one, never normalized.

    Each period dimension item belongs to a phase. Caller owns dates, eligibility,
    and coverage; all cost remains visible if dates move. No residual rounding.
    """
    from .expressions import sum_within, max_
    if model.dimensions[period_dim].parent != phase_dim:
        raise ValueError('Weighted spending periods must belong to the phase dimension.')
    model.check(f'{name}.nonnegative', dims=(period_dim,), condition=weight >= 0,
                code='SPENDING_WEIGHTS', message='Spending weights must be nonnegative.')
    deviation = sum_within(period_dim, weight) - 1
    model.check(f'{name}.weights_total', dims=(phase_dim,),
                condition=max_(deviation, -deviation) <= '0.000000000001',
                code='SPENDING_WEIGHTS', message='Each phase spending curve must sum to one.')
    model.calc(name, unit='usd', dims=(period_dim,), expr=budget * weight)
    return SpendingSchedule(phase_dim, period_dim, budget, ref(name))
