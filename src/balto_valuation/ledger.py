"""Monthly cascade, sale and equity cash flows.

Operating cash while owned pays, in order: senior debt service, each
subordinate tranche by its mode, then the asset management fee. What remains
is distributed; a shortfall is a capital call, so distributable cash is never
negative. Capital events (refinance and sale) run their own cascade: proceeds
less costs and payoffs, plus reserves released at sale.

The sale price is forward twelve months of cash flow after reserves divided by
the exit cap rate; the property projection runs past the sale so
that year exists. With commercial space, a commercial exit cap rate above zero
values the forward commercial base rent (after credit loss) at that rate and
the rest of the cash flow at the exit cap rate; recoveries and expenses stay
with the rest. Commercial leasing costs (TI and commissions) are paid from
operating cash before debt, below NOI, so they reduce coverage in the year a
space rolls but not the cash flow that sizes loans or sets the sale price.
"""

from __future__ import annotations

from balto_model_engine import Model, const, if_, max_, power, ref

from balto_model_engine.commercial import CommercialIncome, income_refs
from balto_model_engine.debt import DebtSchedule
from balto_model_engine.funding import ReserveSchedule, build_funding, build_reserve
from balto_model_engine.periods import period_total
from balto_model_engine.operating import OperatingCashFlow

from .deal import Deal
from .timeline import IDX

MONTH = ("month",)


def build(m: Model, deal: Deal, cash: OperatingCashFlow, *,
          senior: DebtSchedule, refi: DebtSchedule, capital_reserve: ReserveSchedule,
          commercial: CommercialIncome | None = None, fixed_am_fee: bool = False) -> None:
    """With `fixed_am_fee` the asset management fee is the greater of the rate on equity and an
    annual amount escalating on each closing anniversary."""
    commercial = commercial or income_refs(has_spaces=False)
    # --- Operating cascade -----------------------------------------------------------
    m.input("asset_management_fee_rate", unit="rate/year", minimum=0, maximum=0.05)
    property_cash = cash.amount - commercial.leasing_costs if commercial.has_spaces else cash.amount
    m.calc("cash_from_operations", unit="usd", dims=MONTH, expr=property_cash * ref("owned"))
    m.calc("senior_debt_service", unit="usd", dims=MONTH,
           expr=senior.debt_service + refi.debt_service)
    m.calc("cash_after_senior", unit="usd", dims=MONTH,
           expr=ref("cash_from_operations") - ref("senior_debt_service"))
    before = "cash_after_senior"
    for t in deal.tranches:
        m.calc(f"{t.key}.cash_available", unit="usd", dims=MONTH, expr=max_(ref(before), 0))
        m.calc(f"{t.key}.cash_after", unit="usd", dims=MONTH, expr=ref(before) - ref(f"{t.key}.payment"))
        before = f"{t.key}.cash_after"
    am_fee = ref("asset_management_fee_rate") * ref("equity_at_close")
    if fixed_am_fee:
        m.input("asset_management_fee_fixed", unit="usd/year", minimum=0)
        m.input("asset_management_fee_growth", unit="rate/year", minimum=-0.2, maximum=0.5)
        am_fee = max_(am_fee, ref("asset_management_fee_fixed")
                      * power(1 + ref("asset_management_fee_growth"), ref("growth_year")))
    m.calc("asset_management_fee", unit="usd", dims=MONTH, expr=am_fee / 12 * ref("owned"))
    m.calc("cash_after_fees", unit="usd", dims=MONTH, expr=ref(before) - ref("asset_management_fee"))
    # A shortfall draws on the working-capital reserve funded at closing; only the rest is called.
    m.calc("operating_shortfall", unit="usd", dims=MONTH, expr=max_(-ref("cash_after_fees"), 0))
    operating_reserve = build_reserve(m, prefix="operating_reserve", period_dim="month",
        deposits=if_(IDX == 0, ref("working_capital"), 0),
        eligible_spending=ref("operating_shortfall"),
        release=ref("is_sale") * (ref("operating_reserve.available") - ref("operating_reserve.draw")))
    build_funding(m, period_dim="month", sources=ref("cash_after_fees"), uses=const(0),
        transfers_in=operating_reserve.draw, transfers_out=const(0), external_funding=const(0),
        cash_name="operating_funded_cash", contribution_name="operating_capital_call",
        distribution_name="operating_distribution", unmet_name="operating_funding_required")

    # --- Sale ---------------------------------------------------------------------------
    m.input("exit_cap_rate", unit="rate", minimum="0.01", maximum="0.2")
    m.input("selling_cost_rate", unit="rate", minimum=0, maximum="0.1")
    m.input("disposition_fee_rate", unit="rate", minimum=0, maximum="0.05")
    m.calc("sale.window_ncf", unit="usd", dims=MONTH, expr=cash.amount * ref("exit_window"))
    m.calc("sale.forward_ncf", unit="usd", expr=period_total(cash.projection.period_dim, ref("sale.window_ncf")))
    if commercial.has_spaces:
        # 0 values the commercial income with the rest, at the exit cap rate.
        m.input("commercial_exit_cap_rate", unit="rate", minimum=0, maximum="0.2")
        m.calc("sale.commercial_window", unit="usd", dims=MONTH, expr=commercial.net_rent * ref("exit_window"))
        m.calc("sale.forward_commercial", unit="usd",
               expr=period_total(cash.projection.period_dim, ref("sale.commercial_window")))
        m.calc("sale.price", unit="usd",
               expr=if_(ref("commercial_exit_cap_rate") > 0,
                        (ref("sale.forward_ncf") - ref("sale.forward_commercial")) / ref("exit_cap_rate")
                        + ref("sale.forward_commercial") / ref("commercial_exit_cap_rate"),
                        ref("sale.forward_ncf") / ref("exit_cap_rate")))
    else:
        m.calc("sale.price", unit="usd", expr=ref("sale.forward_ncf") / ref("exit_cap_rate"))
    m.calc("sale.costs", unit="usd", expr=ref("sale.price") * ref("selling_cost_rate"))
    m.calc("sale.disposition_fee", unit="usd", expr=ref("sale.price") * ref("disposition_fee_rate"))
    m.calc("sale.net_proceeds", unit="usd", expr=ref("sale.price") - ref("sale.costs") - ref("sale.disposition_fee"))

    # --- Capital events -----------------------------------------------------------------
    payoffs = senior.payoff + refi.payoff
    for t in deal.tranches:
        payoffs = payoffs + ref(f"{t.key}.payoff")
    m.calc("loan_payoffs", unit="usd", dims=MONTH, expr=payoffs)
    m.calc("reserves_released", unit="usd", dims=MONTH,
           expr=capital_reserve.released + operating_reserve.released)
    build_funding(m, period_dim="month",
        sources=ref("is_sale") * ref("sale.net_proceeds") + refi.funding,
        uses=ref("refi.costs") + ref("loan_payoffs") + ref("deferred_capex_spend"),
        transfers_in=ref("reserves_released"), transfers_out=const(0), external_funding=const(0),
        cash_name="capital_event_cash", contribution_name="capital_event_call",
        distribution_name="capital_event_distribution", unmet_name="capital_event_funding_required")

    # --- Sources and uses at closing ------------------------------------------------------
    debt = senior.amount
    for t in deal.tranches:
        debt = debt + ref(f"{t.key}.amount")
    m.calc("total_uses", unit="usd",
           expr=ref("purchase_price") + ref("closing_costs") + ref("capex_budget") + ref("working_capital"))
    m.calc("debt_at_close", unit="usd", expr=debt)
    m.calc("equity_at_close", unit="usd", expr=ref("total_uses") - ref("debt_at_close"))
    m.check("equity_positive", condition=ref("equity_at_close") > 0, code="NO_EQUITY",
            message="Debt at closing covers every use; the model needs equity at closing.")

    # --- Equity cash flows ---------------------------------------------------------------
    m.calc("equity_contributions", unit="usd", dims=MONTH,
           expr=if_(IDX == 0, ref("equity_at_close"), 0) + ref("operating_capital_call") + ref("capital_event_call") + capital_reserve.unfunded)
    m.calc("equity_distributions", unit="usd", dims=MONTH,
           expr=ref("operating_distribution") + ref("capital_event_distribution"))
    m.calc("levered_cash_flow", unit="usd", dims=MONTH,
           expr=ref("equity_distributions") - ref("equity_contributions"))
    # Unlevered: price and acquisition costs, cash flow less capital spending while owned, net sale.
    m.calc("unlevered_cash_flow", unit="usd", dims=MONTH,
           expr=-if_(IDX == 0, ref("purchase_price") + ref("acquisition_costs") + ref("acquisition_fee"), 0)
           + (property_cash - ref("capex_spend")) * ref("owned") + ref("is_sale") * ref("sale.net_proceeds"))
