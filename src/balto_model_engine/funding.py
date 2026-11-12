"""USD reserve transfers and external funding, with caller-owned priorities."""
from dataclasses import dataclass, field
from typing import Literal
from .expressions import Expr, lag, max_, min_, ref
from .model import Model


@dataclass(frozen=True)
class ReserveSchedule:
    period_dim: str
    opening: Expr
    deposits: Expr
    available: Expr
    draw: Expr
    unfunded: Expr
    released: Expr
    balance: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_reserve(model: Model, *, prefix: str, period_dim: str,
                  deposits: Expr, eligible_spending: Expr, release: Expr,
                  balance_name: str | None = None) -> ReserveSchedule:
    """Deposit, draw, then release; requests are nonnegative USD amounts.

    Draws and releases cannot exceed available cash. Unfunded spending remains
    an economic outcome. Callers select eligibility, timing, bounds and whether
    to replenish. Transfers do not themselves create income or project costs.
    """
    dims = (period_dim,)
    balance_name = balance_name or f'{prefix}.balance'
    def calc(name, expr):
        key = f'{prefix}.{name}'
        model.calc(key, unit='usd', dims=dims, expr=expr)
        return ref(key)
    opening = calc('opening', lag(balance_name, period_dim, initial=0))
    deposit = calc('deposits', deposits)
    model.check(f'{prefix}.deposits_nonnegative', dims=dims, condition=deposit >= 0,
                code='NEGATIVE_RESERVE_DEPOSIT', message='Reserve deposits must be nonnegative.')
    available = calc('available', opening + deposit)
    draw = calc('draw', min_(max_(eligible_spending, 0), max_(available, 0)))
    unfunded = calc('unfunded', max_(eligible_spending - draw, 0))
    released = calc('released', min_(max_(release, 0), max_(available - draw, 0)))
    model.calc(balance_name, unit='usd', dims=dims, expr=available - draw - released)
    return ReserveSchedule(period_dim, opening, deposit, available, draw, unfunded,
                           released, ref(balance_name))


@dataclass(frozen=True)
class FundingLedger:
    period_dim: str
    cash: Expr
    contribution: Expr
    distribution: Expr
    unmet: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_funding(model: Model, *, period_dim: str, sources: Expr, uses: Expr,
                  transfers_in: Expr, transfers_out: Expr, external_funding: Expr,
                  cash_name: str, contribution_name: str, distribution_name: str,
                  unmet_name: str) -> FundingLedger:
    """Sources include supplied external funding; transfers are separate cash moves.

    Contribution is the required external funding before supplied funding, unmet
    is the remaining gap, and distribution is cash left after funding. Sources
    and uses exclude internal reserve moves. A caller assuming full equity funding
    passes zero supplied funding and uses contribution as its capital call.
    Caller owns priority, eligible cash, nonnegative funding and event policy.
    """
    dims = (period_dim,)
    model.calc(cash_name, unit='usd', dims=dims,
               expr=sources + transfers_in - uses - transfers_out)
    cash = ref(cash_name)
    model.calc(contribution_name, unit='usd', dims=dims, expr=max_(external_funding - cash, 0))
    model.calc(distribution_name, unit='usd', dims=dims, expr=max_(cash, 0))
    model.calc(unmet_name, unit='usd', dims=dims, expr=max_(-cash, 0))
    return FundingLedger(period_dim, cash, ref(contribution_name), ref(distribution_name), ref(unmet_name))
