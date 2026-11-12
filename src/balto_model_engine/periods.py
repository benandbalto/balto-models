"""Period aggregation with caller-owned boundaries and income policy."""
from .expressions import Expr, if_, sum_over


def period_window(period: Expr, *, start: Expr, end: Expr,
                  include_start: bool, include_end: bool) -> Expr:
    """A numeric 0/1 mask; coordinates may be ordinals or numeric dates.

    Both boundaries are explicit. The caller supplies a coherent coordinate
    system and enough periods; missing periods are never extrapolated.
    """
    lower = period >= start if include_start else period > start
    upper = period <= end if include_end else period < end
    return if_(lower, if_(upper, 1, 0), 0)


def period_total(period_dim: str, amount: Expr, *, activity: Expr | None = None,
                 **where) -> Expr:
    """Sum eligible cash, optionally masked and/or filtered by period attributes.

    No annualization, rounding, reserve deduction or event policy is inferred.
    """
    return sum_over(period_dim, amount if activity is None else amount * activity, **where)
