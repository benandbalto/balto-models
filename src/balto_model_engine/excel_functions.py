"""Excel functions `pycel` lacks, for recalculating compiled workbooks.

Loaded as a `pycel` plugin by `parity`. Each one follows Excel's own
definition and method, independently of the engine, so a workbook formula that
Excel would evaluate differently from the run shows as a parity difference.
"""

from __future__ import annotations


def _flat(value):
    if isinstance(value, (tuple, list)):
        for v in value:
            yield from _flat(v)
    else:
        yield value


def xirr(values, dates, guess=None):
    """Excel's `XIRR`: Newton's method from `guess` (10%), at most 100 steps, else `#NUM!`.

    Flows are discounted by `(1 + rate) ** ((date - first date) / 365)`.
    """
    flows = [float(v) for v in _flat(values)]
    days = [float(d) for d in _flat(dates)]
    if len(flows) != len(days) or not any(f > 0 for f in flows) or not any(f < 0 for f in flows):
        return "#NUM!"
    years = [(d - days[0]) / 365.0 for d in days]
    rate = 0.1 if guess is None else float(guess)
    for _ in range(100):
        if rate <= -1.0:
            return "#NUM!"
        npv = sum(f / (1.0 + rate) ** y for f, y in zip(flows, years))
        slope = sum(-y * f / (1.0 + rate) ** (y + 1.0) for f, y in zip(flows, years))
        if slope == 0:
            return "#NUM!"
        step = npv / slope
        rate -= step
        if abs(step) <= 1e-12 * max(1.0, abs(rate)):
            return rate
    return "#NUM!"
