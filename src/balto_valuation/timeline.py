"""Calendar and event flags.

Month 0 is closing; operations run from month 1. Events are input months, so
an analyst can move the sale or the refinance in the workbook. The property
projection runs to the horizon so forward income exists after any sale month.
"""

from __future__ import annotations

from balto_model_engine import Dimension, Item, Model, attr, if_, max_, monthly_calendar, ref, round_to

from balto_model_engine.periods import period_window

from .deal import Deal

IDX = attr("month", "index")


def build(m: Model, deal: Deal) -> None:
    years = deal.horizon_years
    m.dimension(Dimension("hold_year", [Item(y, label="Closing" if y == 0 else f"Year {y}",
                                             months=1 if y == 0 else 12) for y in range(years + 1)]))
    cal = monthly_calendar(deal.closing, years * 12)
    m.dimension(Dimension("month", [Item(i.key, label="Close" if i.key == 0 else f"M{i.key}", **i.attrs)
                                    for i in cal.items], parent="hold_year"))
    last = len(cal.items) - 1

    m.input("sale_month", unit="month", minimum=13, maximum=last - 12)
    m.input("refi_included", unit="flag", minimum=0, maximum=1)
    m.input("refi_month", unit="month", minimum=12, maximum=last - 12)
    # Event months are whole months and the refinance is in or out, or no month would match the event.
    for name in ("sale_month", "refi_month", "refi_included"):
        m.check(f"{name}_whole", condition=ref(name) == round_to(ref(name), 0), code="EVENT_NOT_WHOLE",
                message=f"{name} must be a whole number.")
    # An unused refinance month does not constrain the sale.
    m.check("refi_before_sale", condition=if_(ref("refi_included") > 0, ref("refi_month") - ref("sale_month"), -1) < 0,
            code="REFI_AFTER_SALE", message="The refinance month must come before the sale month.")

    month = ("month",)
    m.calc("live", unit="flag", dims=month, expr=if_(IDX >= 1, 1, 0))
    m.calc("owned", unit="flag", dims=month, expr=if_(IDX <= ref("sale_month"), ref("live"), 0))
    m.calc("is_sale", unit="flag", dims=month, expr=if_(IDX == ref("sale_month"), 1, 0))
    m.calc("is_refi", unit="flag", dims=month, expr=if_(IDX == ref("refi_month"), ref("refi_included"), 0))
    # Forward twelve months after the sale (the buyer's year one), and the
    # trailing twelve months ending at the refinance (the lender's T12).
    m.calc("exit_window", unit="flag", dims=month,
           expr=period_window(IDX, start=ref("sale_month"), end=ref("sale_month") + 12,
                              include_start=False, include_end=True))
    m.calc("refi_window", unit="flag", dims=month,
           expr=period_window(IDX, start=ref("refi_month") - 12, end=ref("refi_month"),
                              include_start=False, include_end=True))
    # Annual escalations step on each anniversary of closing.
    m.calc("growth_year", unit="years", dims=month, expr=max_(attr("month", "hold_year") - 1, 0))
