"""A monthly calendar dimension whose items carry period attributes as values.

Month 0 is closing. Each later month ends on a month-end; when closing is not
a month-end, month 1 is the stub to the end of the closing month and its day
count prorates that month's operations. Dates are Excel serial days (1900 date
system), so the same numbers date an `XIRR` in Python and in a workbook.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import date

from .model import Dimension, Item

_EXCEL_EPOCH = date(1899, 12, 30)


def excel_serial(day: date) -> int:
    return (day - _EXCEL_EPOCH).days


def _month_end(year: int, month: int) -> date:
    return date(year, month, _calendar.monthrange(year, month)[1])


def monthly_calendar(closing: date, months: int, name: str = "month") -> Dimension:
    """Months 0..`months`. Attributes: `index`, `date`, `days`, `calendar_year`, `month_of_year`, `hold_year`.

    `hold_year` is 0 at closing and `ceil(index / 12)` after it.
    """
    if months < 1:
        raise ValueError("A calendar needs at least one month after closing.")
    ends = [closing]
    year, month = closing.year, closing.month
    if closing != _month_end(year, month):
        ends.append(_month_end(year, month))
    while len(ends) <= months:
        month += 1
        if month > 12:
            year, month = year + 1, 1
        ends.append(_month_end(year, month))
    items = []
    for i, end in enumerate(ends):
        items.append(Item(i, index=i, date=excel_serial(end), days=(end - ends[i - 1]).days if i else 0,
                          calendar_year=end.year, month_of_year=end.month, hold_year=-(-i // 12)))
    return Dimension(name, items)


def annual_calendar(first_year: int, years: int, name: str = "year") -> Dimension:
    """Operating years 1..`years` from calendar year `first_year`, for annual models.

    Attributes: `index` (1 for the first year), `calendar_year`, and `date`, the
    Excel serial of 31 December, so an annual series can date an operating
    projection or an `XIRR` as a monthly one does.
    """
    if years < 1:
        raise ValueError("An annual calendar needs at least one year.")
    return Dimension(name, [Item(y, label=str(first_year + y - 1), index=y, calendar_year=first_year + y - 1,
                                 date=excel_serial(date(first_year + y - 1, 12, 31))) for y in range(1, years + 1)])
