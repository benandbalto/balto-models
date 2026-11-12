"""Metrics computed from a finished run.

An IRR is not an expression node: it is a root of a polynomial in the rate,
not a value of one item, and it may not exist or may not be unique. It is
computed once the flows are evaluated and reported with how it was found.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Rates scanned for a sign change of NPV, from -99.99% to 1,000,000% a year,
# evenly in log(1 + rate). A root outside this range is reported as not found
# rather than chased.
_LOW_GROWTH, _HIGH_GROWTH, _STEPS = 1e-4, 1e4, 1600


def xirr(flows: list[Decimal], days: list[Decimal], tolerance: Decimal) -> dict[str, Any]:
    """The annual rate at which the flows, dated in days, have zero present value.

    The convention is Excel's `XIRR`: each flow is discounted by
    `(1 + rate) ** ((day - first day) / 365)`. The result is `status: ok` with
    the rate, or a status saying why there is none: every flow has the same
    sign, no rate in the scanned range gives zero, or more than one does.
    """
    if not any(f > 0 for f in flows) or not any(f < 0 for f in flows):
        return {"status": "no_sign_change"}
    years = [(d - days[0]) / Decimal(365) for d in days]
    fyears = [float(y) for y in years]
    fflows = [float(f) for f in flows]

    def npv_float(rate: float) -> float:
        return sum(f / (1.0 + rate) ** y for f, y in zip(fflows, fyears))

    ratio = (_HIGH_GROWTH / _LOW_GROWTH) ** (1 / _STEPS)
    grid = [_LOW_GROWTH * ratio ** i - 1.0 for i in range(_STEPS + 1)]
    values = [npv_float(r) for r in grid]
    brackets = [(grid[i], grid[i + 1]) for i in range(_STEPS)
                if values[i] == 0 or (values[i] < 0) != (values[i + 1] < 0)]
    if not brackets:
        return {"status": "no_root"}
    if len(brackets) > 1:
        return {"status": "multiple_roots"}

    def npv(rate: Decimal) -> Decimal:
        return sum((f / (1 + rate) ** y for f, y in zip(flows, years)), Decimal(0))

    low, high = Decimal(repr(brackets[0][0])), Decimal(repr(brackets[0][1]))
    f_low = npv(low)
    if f_low == 0:
        return {"status": "ok", "rate": low}
    while high - low > tolerance:
        mid = (low + high) / 2
        f_mid = npv(mid)
        if f_mid == 0:
            return {"status": "ok", "rate": mid}
        if (f_mid < 0) == (f_low < 0):
            low, f_low = mid, f_mid
        else:
            high = mid
    return {"status": "ok", "rate": (low + high) / 2}
