"""Capital budget, senior loan, refinance and subordinate tranches.

The senior loan is sized at closing as the lesser of loan-to-value on price
and the amount whose amortizing payment year-one cash flow covers at the
minimum DSCR. The refinance, when included, is sized the same way on the
trailing twelve months of cash flow at the refinance month, retires the senior
loan, and is repaid at sale. Every sizing is a closed form, so it stays live
when an input changes in the workbook.

Each loan is the same rows: opening balance, funding, interest, scheduled
principal, payoff and closing balance, with interest-only months and then a
level payment. Subordinate tranches are paid from cash at their priority by
their mode:

- `accrue`: nothing paid; interest compounds and is repaid at sale;
- `available_cash`: interest up to the cash available, the rest accrues;
- `cash_sweep`: a share of the cash available pays interest, then principal;
- `scheduled`: current interest paid in full (hard pay).
"""

from __future__ import annotations

from balto_model_engine import (
    Dimension, Expr, Item, Model, const, if_, lag, matches, max_, min_, ref, round_to, sum_over, sum_within,
)

from balto_model_engine.capital import build_capital_budget, build_even_spending, quantity_cost
from balto_model_engine.debt import (
    DebtSchedule, LoanSizing, build_debt_schedule, build_loan_sizing, build_payment_terms,
)
from balto_model_engine.funding import ReserveSchedule, build_reserve
from balto_model_engine.periods import period_total, period_window
from balto_model_engine.operating import OperatingCashFlow

from .deal import Deal, Tranche
from .timeline import IDX

MONTH = ("month",)


def build_budget(m: Model, deal: Deal) -> ReserveSchedule:
    m.input("purchase_price", unit="usd", minimum=0)
    m.input("working_capital", unit="usd", minimum=0)
    _closing_costs(m, deal)
    _capex(m, deal)

    m.calc("reno_budget", unit="usd",
           expr=sum_over("cohort", if_(matches("cohort", renovate=True), ref("reno_scope") * ref("reno_cost"), 0)))
    # Funded at closing: the renovation program and the phases paid from the capital reserve.
    m.calc("capex_budget", unit="usd", expr=ref("reno_budget") + ref("property_capex_budget"))
    m.calc("reno_spend", unit="usd", dims=MONTH,
           expr=sum_over("cohort", if_(matches("cohort", renovate=True), ref("reno_starts") * ref("reno_cost"), 0)))
    m.calc("capex_spend", unit="usd", dims=MONTH,
           expr=ref("reno_spend") + ref("property_capex_spend") + ref("deferred_capex_spend"))
    # The capital budget is funded into a reserve at closing and drawn as it is spent;
    # a phase funded at an event is paid from that event instead.
    return build_reserve(m, prefix="capital_reserve", period_dim="month",
        deposits=if_(IDX == 0, ref("capex_budget"), 0),
        eligible_spending=(ref("reno_spend") + ref("property_capex_spend")) * ref("owned"),
        release=ref("is_sale") * (ref("capital_reserve.available") - ref("capital_reserve.draw")),
        balance_name="capex_reserve")



def _closing_costs(m: Model, deal: Deal) -> None:
    """Each closing cost by its method, and subtotals by category."""
    m.dimension(Dimension("closing_cost", [Item(c.key, label=c.label, category=c.category, method=c.method,
                                                rated=c.method != "fixed", closing_cost=c.key)
                                           for c in deal.closing_costs]))
    m.input("closing_cost_amount", unit="usd", dims=("closing_cost",), minimum=0, where={"method": "fixed"})
    m.input("closing_cost_rate", unit="rate", dims=("closing_cost",), minimum=0, maximum="0.2",
            where={"rated": True})
    # A fixed cost is its amount; a rated one is worked out from the price or the senior loan.
    m.calc("closing_cost", unit="usd", dims=("closing_cost",), where={"rated": True},
           expr=ref("closing_cost_rate") * if_(matches("closing_cost", method="pct_price"), ref("purchase_price"),
                                               ref("senior.amount")))
    for name, category in (("acquisition_costs", "acquisition"), ("financing_costs", "financing"),
                           ("acquisition_fee", "sponsor_fee")):
        m.calc(name, unit="usd",
               expr=sum_over("closing_cost", ref("closing_cost_amount"), category=category, rated=False)
               + sum_over("closing_cost", ref("closing_cost"), category=category, rated=True))
    m.calc("closing_costs", unit="usd",
           expr=ref("acquisition_costs") + ref("financing_costs") + ref("acquisition_fee"))


def _capex(m: Model, deal: Deal) -> None:
    """The capital budget by phase: hard-cost lines, then general conditions, GC fee and contingency."""
    if not deal.capex_phases:
        m.calc("property_capex_budget", unit="usd", expr=const(0))
        m.calc("deferred_capex_budget", unit="usd", expr=const(0))
        for name in ("property_capex_spend", "deferred_capex_spend"):
            m.calc(name, unit="usd", dims=MONTH, expr=const(0) * ref("live"))
        return
    m.dimension(Dimension("capex_phase", [Item(p.key, label=p.label, funding=p.funding, capex_phase=p.key)
                                          for p in deal.capex_phases]))
    m.dimension(Dimension("capex_line", [Item(x.key, label=x.label, method=x.method, capex_phase=x.phase,
                                              capex_line=x.key)
                                         for x in deal.capex_lines], parent="capex_phase"))
    m.input("capex_amount", unit="usd", dims=("capex_line",), minimum=0, where={"method": "lump"})
    m.input("capex_unit_cost", unit="usd", dims=("capex_line",), minimum=0, where={"method": "unit_cost"})
    m.input("capex_count", unit="units", dims=("capex_line",), minimum=0, where={"method": "unit_cost"})
    m.calc("capex_line_cost", unit="usd", dims=("capex_line",), where={"method": "unit_cost"},
           expr=quantity_cost(ref("capex_unit_cost"), ref("capex_count")))

    phase = ("capex_phase",)
    m.input("capex_start_month", unit="month", dims=phase, minimum=1)
    m.input("capex_months", unit="month", dims=phase, minimum=1)
    m.input("capex_gc_rate", unit="rate", dims=phase, minimum=0, maximum="0.5")
    m.input("capex_gc_fee_rate", unit="rate", dims=phase, minimum=0, maximum="0.5")
    m.input("capex_contingency_rate", unit="rate", dims=phase, minimum=0, maximum="0.5")
    for name in ("capex_start_month", "capex_months"):
        m.check(f"{name}_whole", dims=phase, condition=ref(name) == round_to(ref(name), 0), code="EVENT_NOT_WHOLE",
                message=f"{name} must be a whole number.")
    budget = build_capital_budget(m, phase_dim="capex_phase",
        hard_costs=sum_within("capex_line", ref("capex_amount"), method="lump")
                   + sum_within("capex_line", ref("capex_line_cost"), method="unit_cost"),
        general_conditions_rate=ref("capex_gc_rate"), gc_fee_rate=ref("capex_gc_fee_rate"),
        contingency_rate=ref("capex_contingency_rate"), hard_name="capex_hard",
        general_conditions_name="capex_gc", gc_fee_name="capex_gc_fee",
        contingency_name="capex_contingency", total_name="capex_phase_total")
    spending = build_even_spending(m, phase_dim=budget.phase_dim, period_dim="month",
        budget=budget.total, period_index=IDX, start=ref("capex_start_month"),
        periods=ref("capex_months"), activity=ref("owned"), name="capex_phase_spend")
    for funding, budget_name, spend in (("closing", "property_capex_budget", "property_capex_spend"),
                                      ("event", "deferred_capex_budget", "deferred_capex_spend")):
        m.calc(budget_name, unit="usd", expr=sum_over(budget.phase_dim, budget.total, funding=funding))
        m.calc(spend, unit="usd", dims=MONTH, expr=sum_over(spending.phase_dim, spending.amount, funding=funding))


def _build_acquisition_loan(m: Model, p: str, *, fund_month: Expr, payoff_month: Expr,
                            amount: Expr, fee: bool = True) -> DebtSchedule:
    """Acquisition input bounds; shared component owns the monthly loan math."""
    m.input(f"{p}.rate", unit="rate/year", minimum=0, maximum=0.25)
    m.input(f"{p}.amort_years", unit="years", minimum=1, maximum=40)
    m.input(f"{p}.io_months", unit="month", minimum=0)
    if fee:
        m.input(f"{p}.fee_rate", unit="rate", minimum=0, maximum=0.1)
    terms = build_payment_terms(m, prefix=p, annual_rate=ref(f"{p}.rate"),
                                amort_years=ref(f"{p}.amort_years"))
    return build_debt_schedule(m, prefix=p, period_dim="month", period_index=IDX,
        amount=amount, terms=terms, fund_period=fund_month, payoff_period=payoff_month,
        io_periods=ref(f"{p}.io_months"), fee_rate=ref(f"{p}.fee_rate") if fee else None)


def _size_acquisition_loan(m: Model, p: str, *, income: Expr, value: Expr,
                           included: Expr | None = None) -> LoanSizing:
    """Acquisition underwriting bounds; caller selects income and value."""
    m.input(f"{p}.max_ltv", unit="rate", minimum=0, maximum=1)
    m.input(f"{p}.min_dscr", unit="ratio", minimum=1)
    return build_loan_sizing(m, prefix=p, income=income, value=value,
        max_ltv=ref(f"{p}.max_ltv"), min_dscr=ref(f"{p}.min_dscr"),
        payment_constant=ref(f"{p}.payment_constant"), included=included)


def build_senior(m: Model, deal: Deal, cash: OperatingCashFlow) -> DebtSchedule:
    m.calc("senior.sizing_ncf", unit="usd", expr=period_total(cash.projection.period_dim, cash.amount, hold_year=1))
    if deal.senior_loan == "assumed":
        amount = _assume_acquisition_loan(m, "senior", income=ref("senior.sizing_ncf"), value=ref("purchase_price"))
    else:
        amount = _size_acquisition_loan(m, "senior", income=ref("senior.sizing_ncf"),
                                        value=ref("purchase_price")).amount
    m.calc("senior.payoff_month", unit="month",
           expr=if_(ref("refi_included") == 1, ref("refi_month"), ref("sale_month")))
    # The senior loan's fees are closing costs (financing).
    return _build_acquisition_loan(m, "senior", fund_month=const(0),
        payoff_month=ref("senior.payoff_month"), amount=amount, fee=False)


def _assume_acquisition_loan(m: Model, p: str, *, income: Expr, value: Expr) -> Expr:
    """The seller's loan at its balance on the closing date, paid on its own rate and remaining
    amortization. A new loan's LTV and DSCR amounts are reported beside it, not applied, and the
    loan must be retired (refinanced or sold) by its maturity."""
    m.input(f"{p}.max_ltv", unit="rate", minimum=0, maximum=1)
    m.input(f"{p}.min_dscr", unit="ratio", minimum=1)
    m.input(f"{p}.assumed_balance", unit="usd", minimum=0)
    m.input(f"{p}.maturity_month", unit="month", minimum=1)
    m.calc(f"{p}.ltv_amount", unit="usd", expr=ref(f"{p}.max_ltv") * value)
    m.calc(f"{p}.dscr_amount", unit="usd", expr=income / ref(f"{p}.min_dscr") / 12 / ref(f"{p}.payment_constant"))
    m.calc(f"{p}.amount", unit="usd", expr=ref(f"{p}.assumed_balance"))
    m.test(f"{p}_maturity", condition=ref(f"{p}.payoff_month") <= ref(f"{p}.maturity_month"),
           code="LOAN_PAST_MATURITY", message="The assumed loan is outstanding past its maturity.")
    return ref(f"{p}.amount")


def build_refi(m: Model, deal: Deal, cash: OperatingCashFlow, *, forward: bool = False) -> DebtSchedule:
    """The refinance, sized on trailing twelve months of cash flow, or with `forward` on a choice of
    trailing or the twelve months after the refinance (`refi.forward_sizing`)."""
    m.input("refi.cap_rate", unit="rate", minimum="0.01", maximum="0.2")
    m.calc("refi.window_ncf", unit="usd", dims=MONTH, expr=cash.amount * ref("refi_window"))
    m.calc("refi.trailing_ncf", unit="usd", expr=period_total(cash.projection.period_dim, ref("refi.window_ncf")))
    income = ref("refi.trailing_ncf")
    if forward:
        m.input("refi.forward_sizing", unit="flag", minimum=0, maximum=1)
        m.calc("refi.forward_window", unit="flag", dims=MONTH,
               expr=period_window(IDX, start=ref("refi_month"), end=ref("refi_month") + 12,
                                  include_start=False, include_end=True))
        m.calc("refi.forward_window_ncf", unit="usd", dims=MONTH, expr=cash.amount * ref("refi.forward_window"))
        m.calc("refi.forward_ncf", unit="usd",
               expr=period_total(cash.projection.period_dim, ref("refi.forward_window_ncf")))
        m.calc("refi.sizing_ncf", unit="usd",
               expr=if_(ref("refi.forward_sizing") > 0, ref("refi.forward_ncf"), ref("refi.trailing_ncf")))
        income = ref("refi.sizing_ncf")
    m.calc("refi.value", unit="usd", expr=income / ref("refi.cap_rate"))
    sized = _size_acquisition_loan(m, "refi", income=income, value=ref("refi.value"), included=ref("refi_included"))
    loan = _build_acquisition_loan(m, "refi", fund_month=ref("refi_month"),
        payoff_month=ref("sale_month"), amount=sized.amount)
    m.calc("refi.costs", unit="usd", dims=MONTH, expr=ref("is_refi") * loan.fee)
    return loan


def build_tranche(m: Model, t: Tranche) -> None:
    """A subordinate loan funded at closing, paid from `{key}.cash_available`, repaid at sale."""
    k = t.key
    m.input(f"{k}.amount", unit="usd", minimum=0)
    m.input(f"{k}.rate", unit="rate/year", minimum=0, maximum=0.25)
    if t.mode == "cash_sweep":
        m.input(f"{k}.sweep_share", unit="rate", minimum=0, maximum=1)
    m.calc(f"{k}.opening", unit="usd", dims=MONTH, expr=lag(f"{k}.balance", "month", initial=0))
    m.calc(f"{k}.accrued_opening", unit="usd", dims=MONTH, expr=lag(f"{k}.accrued", "month", initial=0))
    m.calc(f"{k}.funding", unit="usd", dims=MONTH, expr=if_(IDX == 0, ref(f"{k}.amount"), 0))
    # Unpaid interest compounds with principal.
    m.calc(f"{k}.interest_due", unit="usd", dims=MONTH,
           expr=(ref(f"{k}.opening") + ref(f"{k}.accrued_opening")) * ref(f"{k}.rate") / 12)
    owed = ref(f"{k}.accrued_opening") + ref(f"{k}.interest_due")
    available = ref(f"{k}.cash_available")
    if t.mode == "accrue":
        paid = const(0)
    elif t.mode == "available_cash":
        paid = min_(available, owed)
    elif t.mode == "cash_sweep":
        paid = min_(ref(f"{k}.sweep_share") * available, owed)
    else:
        paid = ref(f"{k}.interest_due")
    m.calc(f"{k}.interest_paid", unit="usd", dims=MONTH, expr=paid)
    if t.mode == "cash_sweep":
        principal = min_(max_(ref(f"{k}.sweep_share") * available - ref(f"{k}.interest_paid"), 0),
                         ref(f"{k}.opening"))
    else:
        principal = const(0)
    m.calc(f"{k}.principal_paid", unit="usd", dims=MONTH, expr=principal)
    m.calc(f"{k}.payment", unit="usd", dims=MONTH, expr=ref(f"{k}.interest_paid") + ref(f"{k}.principal_paid"))
    m.calc(f"{k}.payoff", unit="usd", dims=MONTH,
           expr=ref("is_sale") * (ref(f"{k}.opening") - ref(f"{k}.principal_paid") + owed - ref(f"{k}.interest_paid")))
    m.calc(f"{k}.accrued", unit="usd", dims=MONTH,
           expr=(1 - ref("is_sale")) * (owed - ref(f"{k}.interest_paid")))
    m.calc(f"{k}.balance", unit="usd", dims=MONTH,
           expr=(1 - ref("is_sale")) * (ref(f"{k}.opening") + ref(f"{k}.funding") - ref(f"{k}.principal_paid")))
