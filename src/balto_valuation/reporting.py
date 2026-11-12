"""Annual summary, returns and tests reported with the run."""

from __future__ import annotations

from balto_model_engine import Model, attr, if_, ref, sum_over, sum_within

from .deal import Deal

YEAR = ("hold_year",)

# Monthly figures rolled up by hold year, in the order the annual sheet shows them.
ANNUAL = (
    "gpr_total", "loss_to_lease_total", "cash_from_operations", "vacancy_total", "downtime_total",
    "vacancy_floor_adjustment", "bad_debt",
    "rental_income_total", "other_income_total", "egi", "property_tax", "opex_total", "noi",
    "replacement_reserve_deposit", "ncf", "capex_spend", "senior_debt_service", "asset_management_fee",
    "operating_capital_call", "operating_distribution", "capital_event_cash", "equity_contributions",
    "equity_distributions", "levered_cash_flow", "lp_distribution", "gp_distribution", "gp_promote",
    "unlevered_cash_flow",
)
# Commercial figures rolled up by hold year, when the deal has commercial space.
COMMERCIAL_ANNUAL = (
    "commercial.potential_rent", "commercial.downtime_total",
    "commercial.recoveries_total", "commercial.credit_loss", "commercial.income", "commercial.leasing_costs_total",
)


def build(m: Model, deal: Deal) -> None:
    for name in ANNUAL + (COMMERCIAL_ANNUAL if deal.commercial_spaces else ()):
        m.calc(f"annual.{name}", unit="usd", dims=YEAR, expr=sum_within("month", ref(name)))
    m.calc("annual.opex", unit="usd", dims=("line", "hold_year"), expr=sum_within("month", ref("opex")))
    for t in deal.tranches:
        m.calc(f"annual.{t.key}.payment", unit="usd", dims=YEAR, expr=sum_within("month", ref(f"{t.key}.payment")))
    m.calc("annual.occupancy", unit="rate", dims=YEAR,
           expr=sum_within("month", ref("occupancy")) / attr("hold_year", "months"))
    # Coverage is on cash flow while owned: a sale year's DSCR excludes the buyer's months.
    m.calc("annual.dscr", unit="ratio", dims=YEAR,
           expr=if_(ref("annual.senior_debt_service") > 0,
                    ref("annual.cash_from_operations") / ref("annual.senior_debt_service"), 0))
    m.calc("annual.cash_on_cash", unit="rate", dims=YEAR,
           expr=ref("annual.operating_distribution") / ref("equity_at_close"))
    m.calc("annual.units_renovated", unit="units", dims=YEAR,
           expr=sum_within("month", ref("reno_starts_total")))

    # --- Headline figures ------------------------------------------------------------
    m.calc("price_per_unit", unit="usd/unit", expr=ref("purchase_price") / ref("total_units"))
    m.calc("year_1_noi", unit="usd", expr=sum_over("month", ref("noi"), hold_year=1))
    m.calc("going_in_cap_rate", unit="rate", expr=ref("year_1_noi") / ref("purchase_price"))
    m.calc("all_in_cost", unit="usd",
           expr=ref("purchase_price") + ref("closing_costs") + ref("capex_budget") + ref("deferred_capex_budget"))
    m.calc("yield_on_cost", unit="rate", expr=ref("sale.forward_ncf") / ref("all_in_cost"))
    m.calc("total_contributions", unit="usd", expr=sum_over("month", ref("equity_contributions")))
    m.calc("total_distributions", unit="usd", expr=sum_over("month", ref("equity_distributions")))
    m.calc("equity_multiple", unit="ratio", expr=ref("total_distributions") / ref("total_contributions"))
    m.calc("levered_profit", unit="usd", expr=ref("total_distributions") - ref("total_contributions"))
    m.calc("lp_multiple", unit="ratio",
           expr=sum_over("month", ref("lp_distribution")) / sum_over("month", ref("lp_contribution")))
    m.calc("gp_multiple", unit="ratio",
           expr=sum_over("month", ref("gp_distribution")) / sum_over("month", ref("gp_contribution")))
    m.calc("gp_promote_total", unit="usd", expr=sum_over("month", ref("gp_promote")))
    m.calc("sponsor_fees", unit="usd",
           expr=ref("acquisition_fee") + sum_over("month", ref("asset_management_fee")) + ref("sale.disposition_fee"))
    m.calc("capital_calls_after_close", unit="usd",
           expr=sum_over("month", ref("operating_capital_call") + ref("capital_event_call") + ref("capital_reserve.unfunded")))

    m.xirr("unlevered_irr", flows="unlevered_cash_flow", dim="month", date_attr="date")
    m.xirr("levered_irr", flows="levered_cash_flow", dim="month", date_attr="date")
    m.xirr("lp_irr", flows="lp_cash_flow", dim="month", date_attr="date")
    m.xirr("gp_irr", flows="gp_cash_flow", dim="month", date_attr="date")

    # --- Tests reported with the run ------------------------------------------------------
    m.input("set_aside_units", unit="units", minimum=0)
    m.test("set_aside", condition=ref("restricted_units") >= ref("set_aside_units"), code="SET_ASIDE_SHORT",
           message="Fewer restricted units than the regulatory agreement requires.")
    m.test("senior_dscr", dims=YEAR,
           condition=if_(ref("annual.senior_debt_service") > 0, ref("annual.dscr"), 99) >= ref("senior.min_dscr"),
           code="DSCR_BELOW_MINIMUM", message="Cash flow covers senior debt service below the minimum DSCR.")
    m.test("fully_funded", condition=ref("capital_calls_after_close") <= 0, code="CAPITAL_CALL",
           message="The plan needs equity after closing to cover a shortfall.")
