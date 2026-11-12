"""Other income, commercial leases, operating expenses, property tax and the income bridge.

Residential other income is per occupied unit. Commercial space is leased on
its own terms (the engine's commercial component): its rent, recoveries and
credit loss add to effective gross income independent of apartment occupancy,
and its leasing costs are capital, paid below NOI. A NNN tenant reimburses its
share of property tax and of the expense lines marked recoverable.

Expense lines use one of three methods: per unit per year, a percentage of
effective gross income, or a fixed annual amount, each escalating on the
anniversary of closing. Property tax follows the jurisdiction:

- `or_mav` (Oregon): assessed value is the lesser of real market value and
  maximum assessed value, which grows 3% a year; a sale does not reset it.
- `wa_market` (Washington): assessed value follows market value.
"""

from __future__ import annotations

from balto_model_engine import Dimension, Item, Model, attr, const, if_, matches, max_, min_, power, ref, sum_over

from balto_model_engine.commercial import (
    CommercialIncome, build_commercial_income, declare_inputs, income_refs, space_dimension,
)
from balto_model_engine.operating import (
    OperatingCashFlow, annual_per_unit, annual_fixed,
    build_operating_projection, build_operating_cash_flow,
)

from .deal import Deal
from .timeline import IDX

MONTH = ("month",)


def build(m: Model, deal: Deal, *, exemption_month: bool = False) -> OperatingCashFlow:
    """With `exemption_month`, the tax exemption starts at `tax_exemption_month` (a nonprofit
    partner's exemption granted after closing, say) instead of applying from closing."""
    m.dimension(Dimension("line", [Item(x.key, label=x.label, method=x.method, recoverable=x.recoverable)
                                   for x in deal.opex_lines]))
    m.dimension(space_dimension(deal.commercial_spaces))
    live = ref("live")

    # --- Income below rent -------------------------------------------------------
    m.input("vacancy_floor", unit="rate", minimum=0, maximum=1)
    m.input("bad_debt_rate", unit="rate", minimum=0, maximum=1)
    m.input("other_income", unit="usd/unit-month", minimum=0)
    # Physical vacancy comes from the unit states; the floor is a minimum, not an addition.
    m.calc("vacancy_floor_adjustment", unit="usd", dims=MONTH,
           expr=max_(ref("vacancy_floor") * ref("gpr_total") - ref("vacancy_total") - ref("downtime_total"), 0))
    m.calc("bad_debt", unit="usd", dims=MONTH,
           expr=ref("bad_debt_rate") * (ref("rental_income_total") - ref("vacancy_floor_adjustment")))
    m.calc("other_income_total", unit="usd", dims=MONTH, expr=ref("other_income") * ref("occupied_units") * live)
    commercial = _commercial(m, deal)
    egi = ref("rental_income_total") - ref("vacancy_floor_adjustment") - ref("bad_debt") + ref("other_income_total")
    m.calc("egi", unit="usd", dims=MONTH, expr=egi + commercial.income if commercial.has_spaces else egi)

    # --- Expense lines -------------------------------------------------------------
    m.input("opex_per_unit", unit="usd/unit-year", dims=("line",), minimum=0, where={"method": "per_unit"})
    m.input("opex_rate", unit="rate", dims=("line",), minimum=0, maximum=1, where={"method": "pct_egi"})
    m.input("opex_fixed", unit="usd", dims=("line",), minimum=0, where={"method": "fixed"})
    m.input("opex_growth", unit="rate/year", dims=("line",), minimum=-0.2, maximum=0.5)
    m.calc("opex", unit="usd", dims=("line", "month"),
           expr=if_(matches("line", method="pct_egi"), ref("opex_rate") * ref("egi"), _escalated_line(live)))

    # --- Property tax ------------------------------------------------------------------
    m.input("tax_market_value", unit="usd", minimum=0)
    m.input("tax_market_growth", unit="rate/year", minimum=-0.2, maximum=0.5)
    m.input("tax_levy_rate", unit="rate", minimum=0, maximum=0.1)
    m.input("tax_exemption", unit="rate", minimum=0, maximum=1)
    m.calc("tax_market_value_now", unit="usd", dims=MONTH,
           expr=ref("tax_market_value") * power(1 + ref("tax_market_growth"), ref("growth_year")))
    if deal.tax_method == "or_mav":
        m.input("tax_max_assessed_value", unit="usd", minimum=0)
        m.calc("tax_max_assessed_now", unit="usd", dims=MONTH,
               expr=ref("tax_max_assessed_value") * power(const("1.03"), ref("growth_year")))
        assessed = min_(ref("tax_market_value_now"), ref("tax_max_assessed_now"))
    else:
        assessed = ref("tax_market_value_now")
    m.calc("assessed_value", unit="usd", dims=MONTH, expr=assessed)
    exemption = ref("tax_exemption")
    if exemption_month:
        m.input("tax_exemption_month", unit="month", minimum=0)
        exemption = if_(IDX >= ref("tax_exemption_month"), exemption, 0)
    if deal.tax_exemption_ends:
        m.input("tax_exemption_end_month", unit="month", minimum=0)
        exemption = if_(IDX < ref("tax_exemption_end_month"), exemption, 0)
    m.calc("property_tax", unit="usd", dims=MONTH,
           expr=ref("assessed_value") * ref("tax_levy_rate") * (1 - exemption) / 12 * live)

    # --- NOI and cash flow before debt ---------------------------------------------------
    m.input("replacement_reserve", unit="usd/unit-year", minimum=0)
    m.calc("opex_total", unit="usd", dims=MONTH, expr=sum_over("line", ref("opex")) + ref("property_tax"))
    projection = build_operating_projection(
        m, period_dim='month', units=ref('total_units'),
        income_lines=(ref('rental_income_total'), -ref('vacancy_floor_adjustment'),
                      -ref('bad_debt'), ref('other_income_total'))
                     + ((commercial.income,) if commercial.has_spaces else ()),
        expense_lines=(ref('opex'), ref('property_tax')),
        income=ref('egi'), expenses=ref('opex_total'), noi_name='noi')
    m.calc("replacement_reserve_deposit", unit="usd", dims=MONTH,
           expr=ref("replacement_reserve") * ref("total_units") / 12 * live)
    return build_operating_cash_flow(m, projection=projection,
                                     reserves=ref('replacement_reserve_deposit'), name='ncf')


def commercial_income(deal: Deal) -> CommercialIncome:
    """The commercial totals `build` declared (zero without commercial space)."""
    return income_refs(has_spaces=bool(deal.commercial_spaces))


def _escalated_line(live):
    """A per-unit or fixed expense line's monthly amount (share-of-income lines are not recoverable)."""
    escalation = power(1 + ref("opex_growth"), ref("growth_year"))
    return if_(matches("line", method="per_unit"),
               annual_per_unit(ref("opex_per_unit"), ref("total_units")) * escalation * live,
               annual_fixed(ref("opex_fixed")) * escalation * live)


def _commercial(m: Model, deal: Deal) -> CommercialIncome:
    """Commercial leases, with NNN recoveries of property tax and the recoverable lines."""
    declare_inputs(m)
    if deal.commercial_spaces:
        # Recomputed from the line inputs rather than read from `opex`, whose
        # share-of-income lines depend on the income these recoveries are part of.
        m.calc("recoverable_costs", unit="usd", dims=MONTH,
               expr=ref("property_tax") + sum_over("line", _escalated_line(ref("live")), recoverable=True))
    return build_commercial_income(m, period_index=IDX, month_of_year=attr("month", "month_of_year"),
                                   active=ref("live"), recoverable_costs=ref("recoverable_costs"))
