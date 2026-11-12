"""The analyst workbook's layout: which sheet shows each figure, labelled and formatted.

The layout is data for the engine's workbook compiler. Every figure is a live
formula or an input cell; nothing here computes.
"""

from __future__ import annotations

from balto_model_engine.workbook import Heading, Layout, MetricRow, Row, Sheet

from .deal import Deal
from .overview import CONFIDENTIAL, SPONSOR
from .reporting import ANNUAL, COMMERCIAL_ANNUAL

LABELS = {
    "capital_reserve.opening": "Capital reserve, opening",
    "capital_reserve.deposits": "Capital reserve deposits (internal transfer)",
    "capital_reserve.available": "Capital reserve available",
    "capital_reserve.draw": "Capital spending funded from reserve",
    "capital_reserve.unfunded": "Capital spending requiring equity",
    "capital_reserve.released": "Capital reserve released",
    "operating_reserve.deposits": "Operating reserve deposits (internal transfer)",
    "operating_reserve.available": "Operating reserve available",
    "operating_reserve.unfunded": "Operating spending requiring equity",
    "operating_reserve.released": "Operating reserve released",
    "operating_funded_cash": "Operating cash after reserve draw",
    "operating_funding_required": "Operating equity funding required",
    "capital_event_funding_required": "Capital event equity funding required",
    # Timeline
    "sale_month": "Sale month", "refi_included": "Refinance included (1 = yes)", "refi_month": "Refinance month",
    "live": "Operating month", "owned": "Owned and operating", "is_sale": "Sale month",
    "is_refi": "Refinance month", "exit_window": "Buyer's forward 12 months",
    "refi_window": "Lender's trailing 12 months",
    "growth_year": "Escalation years", "market_factor": "Market rent growth factor",
    "renewal_factor": "Renewal growth factor (monthly)",
    # Rents
    "market_rent": "Market rent at closing", "reno_premium": "Renovation premium",
    "reno_cost": "Renovation cost per unit",
    "units": "Units", "occupied_at_close": "Occupied at closing", "in_place_rent": "In-place rent",
    "rent_limit_gross": "Gross rent limit (AMI table)", "utility_allowance": "Utility allowance",
    "contract_rent": "Contract rent", "reno_scope": "Units to renovate", "reno_pace": "Renovation starts per month",
    "market_growth": "Market rent growth", "renewal_increase": "Renewal increase", "rent_cap": "Statewide rent cap",
    "turnover": "Annual turnover", "ami_growth": "AMI limit growth", "ua_growth": "Utility allowance growth",
    "ocaf": "HAP contract OCAF", "reno_start_month": "Renovation start month",
    "mark_to_market": "Mark in-place rents to market on turnover (1 = yes)",
    "market_rent_now": "Market rent", "rent_limit": "Net rent limit", "classic_target": "Rent target, classic",
    "renovated_target": "Rent target, renovated",
    "occupied_classic_open": "Occupied classic, opening", "vacant_classic_open": "Vacant classic, opening",
    "move_outs_classic": "Move-outs, classic", "scope_remaining_open": "Scope remaining, opening",
    "reno_starts": "Renovation starts", "releases_classic": "Re-leases, classic", "vacant_classic": "Vacant classic",
    "occupied_classic": "Occupied classic", "scope_remaining": "Scope remaining", "in_renovation": "In renovation",
    "reno_completions": "Renovations completed", "occupied_renovated_open": "Occupied renovated, opening",
    "vacant_renovated_open": "Vacant renovated, opening", "move_outs_renovated": "Move-outs, renovated",
    "leases_renovated": "New leases, renovated", "vacant_renovated": "Vacant renovated",
    "occupied_renovated": "Occupied renovated", "units_converted": "Units converted",
    "rent_classic": "Average rent, classic", "rent_renovated": "Average rent, renovated",
    "gpr": "Gross potential rent", "loss_to_lease": "Loss to lease", "vacancy_loss": "Vacancy",
    "downtime_loss": "Renovation downtime", "rental_income": "Rental income",
    "total_units": "Units", "restricted_units": "Restricted units", "occupied_units": "Occupied units",
    "occupancy": "Physical occupancy",
    "gpr_total": "Gross potential rent", "loss_to_lease_total": "Loss to lease", "vacancy_total": "Vacancy",
    "downtime_total": "Renovation downtime", "rental_income_total": "Rental income",
    # Operations
    "vacancy_floor": "Economic vacancy floor", "bad_debt_rate": "Bad debt",
    "other_income": "Other income per occupied unit",
    "vacancy_floor_adjustment": "Vacancy to floor", "bad_debt": "Bad debt", "other_income_total": "Other income",
    "egi": "Effective gross income", "opex_per_unit": "Annual cost per unit", "opex_rate": "Share of EGI",
    "opex_fixed": "Annual amount", "opex_growth": "Annual escalation", "opex": "Expense",
    "tax_market_value": "Real market value at closing", "tax_market_growth": "Market value growth",
    "tax_levy_rate": "Levy rate", "tax_exemption": "Exempt share", "tax_exemption_end_month": "Exemption ends (month)", "tax_max_assessed_value": "Maximum assessed value",
    "tax_market_value_now": "Real market value", "tax_max_assessed_now": "Maximum assessed value",
    "assessed_value": "Assessed value", "property_tax": "Property tax", "replacement_reserve": "Replacement reserve",
    "opex_total": "Total operating expenses", "noi": "Net operating income",
    "replacement_reserve_deposit": "Replacement reserve", "ncf": "Cash flow before debt",
    # Capital
    "purchase_price": "Purchase price",
    "working_capital": "Working capital & operating reserve",
    "closing_cost": "Closing cost", "acquisition_costs": "Total acquisition costs",
    "financing_costs": "Total financing costs", "closing_costs": "Total closing costs",
    "property_capex_budget": "Property capital funded at closing",
    "deferred_capex_budget": "Property capital paid at events",
    "property_capex_spend": "Property capital spend (from reserve)",
    "deferred_capex_spend": "Property capital spend (at events)",
    "pf.gpr": "Gross potential rent", "pf.loss_to_lease": "Loss to lease", "pf.vacancy": "Physical vacancy",
    "pf.downtime": "Renovation downtime", "pf.rental_income": "Net rental income",
    "pf.vacancy_floor": "Economic vacancy (to the floor)", "pf.bad_debt": "Bad debt",
    "pf.other_income": "Other income", "pf.egi": "Effective gross income",
    "pf.property_tax": "Property tax", "pf.opex_total": "Total operating expenses",
    "pf.noi": "Net operating income", "pf.reserves": "Replacement reserve", "pf.ncf": "Cash flow before debt",
    "pf.occupancy": "Occupancy", "pf.noi_per_unit": "NOI per unit", "pf.opex_per_unit": "Expenses per unit",
    "pf.expense_ratio": "Expense ratio (of EGI)", "pf.cap_rate": "Cap rate on purchase price",
    "pf.yield_on_cost": "Yield on all-in cost",
    "operating_shortfall": "Operating shortfall", "operating_reserve.opening": "Operating reserve, opening",
    "operating_reserve.draw": "Drawn from operating reserve", "operating_reserve.balance": "Operating reserve balance",
    "catch_up_share": "GP catch-up share (0 = none)", "tier_catch_up": "Catch-up: GP promote to its share of profit",
    "wf.contributions_to_date": "Contributions to date", "wf.distributions_before": "Distributions before this month",
    "wf.distributions_to_date": "Distributions to date", "wf.promote_before": "GP promote before this month",
    "wf.promote_to_date": "GP promote to date", "wf.profit_after_tier_1": "Profit distributed after tier 1",
    "wf.catch_up_owed": "Catch-up owed to the GP",
    "acquisition_fee": "Acquisition fee",
    "reno_budget": "Unit renovation budget", "capex_budget": "Capital budget", "reno_spend": "Unit renovation spend",
    "capex_spend": "Capital spending",
    "capex_reserve": "Capital reserve balance",
    # Cascade and events
    "asset_management_fee_rate": "Asset management fee (of equity)",
    "cash_from_operations": "Cash flow before debt", "senior_debt_service": "Senior debt service",
    "cash_after_senior": "Cash after senior debt", "asset_management_fee": "Asset management fee",
    "cash_after_fees": "Cash after debt and fees", "operating_capital_call": "Capital call",
    "operating_distribution": "Operating distribution",
    "exit_cap_rate": "Exit cap rate", "selling_cost_rate": "Selling costs", "disposition_fee_rate": "Disposition fee",
    "sale.window_ncf": "Buyer's forward cash flow", "sale.forward_ncf": "Forward 12-month cash flow",
    "sale.price": "Sale price", "sale.costs": "Selling costs", "sale.disposition_fee": "Disposition fee",
    "sale.net_proceeds": "Sale proceeds before debt repayment", "loan_payoffs": "Loan payoffs",
    "reserves_released": "Reserves released",
    "capital_event_cash": "Capital event cash", "capital_event_call": "Capital call, capital event",
    "capital_event_distribution": "Capital event distribution",
    "total_uses": "Total uses", "debt_at_close": "Debt at closing", "equity_at_close": "Equity at closing",
    "equity_contributions": "Equity contributions", "equity_distributions": "Equity distributions",
    "levered_cash_flow": "Levered cash flow", "unlevered_cash_flow": "Unlevered cash flow",
    # Waterfall
    "lp_share": "LP share of capital", "pref_rate": "Preferred return", "hurdle_rate": "Second hurdle (IRR)",
    "promote_1": "GP promote above pref", "promote_2": "GP promote above hurdle",
    "lp_contribution": "LP contribution", "gp_contribution": "GP contribution",
    "pref.accrual": "Pref accrual rate", "pref.opening": "LP pref account before distribution",
    "tier_1": "Tier 1: return of capital and pref", "pref.balance": "LP pref account",
    "hurdle.accrual": "Hurdle accrual rate", "hurdle.opening": "LP hurdle account before tier 2",
    "tier_2": "Tier 2: to the hurdle", "hurdle.balance": "LP hurdle account", "tier_3": "Tier 3: residual",
    "lp_distribution": "LP distributions", "gp_distribution": "GP distributions", "gp_promote": "GP promote",
    "lp_cash_flow": "LP cash flow", "gp_cash_flow": "GP cash flow",
    # Reporting
    "price_per_unit": "Price per unit", "year_1_noi": "Year 1 NOI", "going_in_cap_rate": "Going-in cap rate",
    "all_in_cost": "All-in cost", "yield_on_cost": "Yield on cost (exit forward cash flow)",
    "total_contributions": "Equity contributed", "total_distributions": "Equity distributed",
    "equity_multiple": "Equity multiple", "levered_profit": "Profit", "lp_multiple": "LP multiple",
    "gp_multiple": "GP multiple", "gp_promote_total": "GP promote", "sponsor_fees": "Sponsor fees",
    "capital_calls_after_close": "Capital calls after closing", "set_aside_units": "Required restricted units",
    "annual.occupancy": "Average occupancy", "annual.dscr": "Senior DSCR", "annual.cash_on_cash": "Cash on cash",
    "annual.units_renovated": "Renovation starts", "reno_starts_total": "Units starting renovation",
    "annual.opex": "Expense",
    # Commercial space
    "commercial.rent": "Annual base rent at closing", "commercial.bump": "Annual rent bump",
    "commercial.bump_month": "Bump month (1 = January)",
    "commercial.expiry_month": "Lease expiration month (0 = vacant)",
    "commercial.option_exercised": "Renewal options exercised (1 = yes)",
    "commercial.option_months": "Option term (months)",
    "commercial.renewal_probability": "Renewal probability at market",
    "commercial.market_rent": "Market rent at closing", "commercial.downtime_months": "Downtime if not renewed (months)",
    "commercial.ti": "Tenant improvements (new tenant)", "commercial.lc": "Leasing commissions (new tenant)",
    "commercial.recovery_share": "Share of recoverable costs reimbursed (NNN)",
    "commercial.market_growth": "Commercial market rent growth",
    "commercial.new_lease_bump": "Annual bump on new commercial leases",
    "commercial.credit_loss_rate": "Commercial vacancy & credit loss",
    "commercial_exit_cap_rate": "Commercial exit cap rate (0 = at the exit cap rate)",
    "commercial.lease_end": "In-place lease ends (month)", "commercial.rollover_month": "Rollover month",
    "commercial.new_lease_month": "New tenant commencement month",
    "commercial.scheduled_rent": "In-place lease rent schedule", "commercial.in_place": "In-place lease running",
    "commercial.contract_rent": "In-place lease rent", "commercial.market_rent_now": "Market rent (whole space)",
    "commercial.renewal_lease_year_month": "Renewal lease, month of lease year",
    "commercial.renewal_rent": "Renewal lease rent",
    "commercial.new_lease_year_month": "New lease, month of lease year", "commercial.new_rent": "New lease rent",
    "commercial.base_rent": "Base rent (expected)", "commercial.occupancy": "Occupancy (expected)",
    "commercial.downtime": "Downtime", "commercial.recoveries": "Recoveries",
    "commercial.leasing_costs": "Leasing costs (TI & LC)",
    "commercial.potential_rent": "Commercial potential rent", "commercial.downtime_total": "Commercial vacancy & downtime",
    "commercial.base_rent_total": "Commercial base rent", "commercial.recoveries_total": "Commercial recoveries",
    "commercial.credit_loss": "Commercial credit loss", "commercial.income": "Commercial income",
    "commercial.net_rent": "Commercial base rent after credit loss",
    "commercial.leasing_costs_total": "Commercial leasing costs (TI & LC)",
    "commercial.occupied_sf_total": "Commercial SF occupied", "commercial.total_sf": "Commercial SF",
    "recoverable_costs": "Recoverable costs (property tax & recoverable lines)",
    "sale.commercial_window": "Buyer's forward commercial rent",
    "sale.forward_commercial": "Forward 12-month commercial rent (after credit loss)",
    "pf.commercial_rent": "Commercial potential rent", "pf.commercial_vacancy": "Commercial vacancy & downtime",
    "pf.commercial_recoveries": "Commercial recoveries", "pf.commercial_credit_loss": "Commercial credit loss",
    "pf.commercial_income": "Commercial income",
}

UNITS = {
    "usd": "$", "usd/unit": "$/unit", "usd/unit-month": "$/unit/mo", "usd/unit-year": "$/unit/yr", "rate": "%",
    "rate/year": "%/yr", "ratio": "x", "units": "units", "units/month": "units/mo", "month": "month",
    "flag": "flag", "years": "years", "factor": "factor", "usd/year": "$/yr", "month_of_year": "month",
    "usd/sf-year": "$/SF/yr", "usd/sf": "$/SF", "sf": "SF",
}

LOAN = {
    "max_ltv": "Maximum LTV", "min_dscr": "Minimum DSCR", "rate": "Interest rate",
    "amort_years": "Amortization (years)",
    "io_months": "Interest-only months", "fee_rate": "Origination fee", "cap_rate": "Lender cap rate",
    "sizing_ncf": "Year 1 cash flow", "trailing_ncf": "Trailing 12-month cash flow", "value": "Value",
    "ltv_amount": "Amount at maximum LTV", "dscr_amount": "Amount at minimum DSCR", "amount": "Loan amount",
    "assumed_balance": "Assumed balance at closing", "maturity_month": "Maturity (month)",
    "monthly_rate": "Monthly rate", "payment_constant": "Payment constant (monthly)", "payment": "Amortizing payment",
    "fee": "Origination fee", "payoff_month": "Payoff month", "opening": "Opening balance", "funding": "Funding",
    "interest": "Interest", "principal": "Scheduled principal", "payoff": "Payoff", "balance": "Closing balance",
    "debt_service": "Debt service", "window_ncf": "Cash flow in sizing window", "costs": "Refinance costs",
    "sweep_share": "Share of cash swept", "accrued_opening": "Accrued interest, opening",
    "interest_due": "Interest due", "interest_paid": "Interest paid", "principal_paid": "Principal paid",
    "accrued": "Accrued interest", "cash_available": "Cash available at its priority", "cash_after": "Cash after",
}


def _label(name: str, deal: Deal) -> str:
    if name in LABELS:
        return LABELS[name]
    if name.startswith("annual."):
        return _label(name.removeprefix("annual."), deal)
    if name.startswith("in_renovation_"):
        return f"In renovation, month {name.rsplit('_', 1)[1]}"
    prefix, _, field = name.partition(".")
    owner = {"senior": "Senior", "refi": "Refinance", **{t.key: t.label for t in deal.tranches}}.get(prefix)
    if owner and field == "payment" and prefix not in ("senior", "refi"):
        return f"{owner} — Paid from operations"
    if owner and field in LOAN:
        return f"{owner} — {LOAN[field]}"
    return name.replace("_", " ").capitalize()


def build_layout(deal: Deal, sponsor: str = SPONSOR) -> Layout:
    def r(name: str, total: bool = False, fmt: str | None = None) -> Row:
        return Row(name, _label(name, deal), fmt, total)

    def g(name: str, label: str = "", fmt: str | None = None, total: bool = False, **where) -> Row:
        """The items of `name` matching `where`, labelled by item."""
        return Row(name, label, fmt, total, where)

    tranches = deal.tranches
    spaces = bool(deal.commercial_spaces)
    # Without phases there is no Capital Budget sheet; its one remaining figure shows on Sources & Uses.
    no_phases = () if deal.capex_phases else (r("deferred_capex_budget"),)
    loan_inputs = ("rate", "amort_years", "io_months", "max_ltv", "min_dscr")
    stages = [f"in_renovation_{k}" for k in range(1, deal.downtime_months + 1)]

    summary = Sheet("Returns Detail", (
        Heading(deal.name),
        r("total_units"), r("restricted_units"), *([r("commercial.total_sf", fmt="#,##0")] if spaces else []),
        r("price_per_unit"), r("year_1_noi"), r("going_in_cap_rate"),
        r("all_in_cost"), r("yield_on_cost"),
        Heading("Returns"),
        MetricRow("unlevered_irr", "Unlevered IRR"), MetricRow("levered_irr", "Levered equity IRR (before promote)"),
        MetricRow("lp_irr", "LP IRR"), MetricRow("gp_irr", "GP IRR (co-invest and promote)"),
        r("equity_multiple"), r("lp_multiple"), r("gp_multiple"),
        r("total_contributions"), r("total_distributions"), r("levered_profit", True),
        Heading("Sponsor economics"),
        r("gp_promote_total"), r("sponsor_fees"),
        Heading("Exit"),
        r("sale.forward_ncf"), *([r("sale.forward_commercial")] if spaces else []),
        r("sale.price", True), r("sale.costs"), r("sale.disposition_fee"),
        r("sale.net_proceeds", True),
        Heading("Funding check"),
        r("capital_calls_after_close"),
    ))

    assumptions = Sheet("Assumptions", (
        Heading("Timeline (months after closing)"),
        r("sale_month"), r("refi_included"), r("refi_month"), r("reno_start_month"),
        Heading("Revenue"),
        r("market_growth"), r("renewal_increase"), r("rent_cap"), r("turnover"), r("ami_growth"), r("ua_growth"),
        r("ocaf"), r("mark_to_market", fmt='"Yes";"Yes";"No"'), r("vacancy_floor"), r("bad_debt_rate"),
        r("other_income"),
        *([Heading("Commercial space (leases on the Commercial Leases sheet)"), r("commercial.market_growth"),
           r("commercial.new_lease_bump"), r("commercial.credit_loss_rate")] if spaces else []),
        Heading("Expenses and property tax"),
        r("replacement_reserve"), r("tax_market_value"),
        *([r("tax_max_assessed_value")] if deal.tax_method == "or_mav" else []),
        r("tax_market_growth"), r("tax_levy_rate"), r("tax_exemption"),
        *([r("tax_exemption_end_month")] if deal.tax_exemption_ends else []),
        Heading("Assumed senior loan" if deal.senior_loan == "assumed" else "Senior loan"),
        *([r("senior.assumed_balance"), r("senior.maturity_month")] if deal.senior_loan == "assumed" else []),
        *(r(f"senior.{f}") for f in loan_inputs),
        Heading("Refinance"), r("refi.cap_rate"), *(r(f"refi.{f}") for f in loan_inputs), r("refi.fee_rate"),
        *(x for t in tranches for x in (
            Heading(f"{t.label} ({t.mode.replace('_', ' ')})"), r(f"{t.key}.amount"), r(f"{t.key}.rate"),
            *([r(f"{t.key}.sweep_share")] if t.mode == "cash_sweep" else []))),
        Heading("Partnership"),
        r("lp_share"), r("pref_rate"), r("catch_up_share"), r("hurdle_rate"), r("promote_1"), r("promote_2"),
        r("asset_management_fee_rate"),
        Heading("Exit"), r("exit_cap_rate"), *([r("commercial_exit_cap_rate")] if spaces else []),
        r("selling_cost_rate"), r("disposition_fee_rate"),
        Heading("Regulatory agreement"), r("set_aside_units"),
    ))

    unit_mix = Sheet("Unit Mix", (
        Heading("Rent roll at closing"),
        r("units", True), r("occupied_at_close"), r("in_place_rent"),
        Heading("Regulated rents"),
        r("rent_limit_gross"), r("utility_allowance"), r("contract_rent"),
        Heading("Renovation program"),
        r("reno_scope"), r("reno_pace", fmt="0.0"),
    ), columns="cohort")
    unit_types = Sheet("Unit Types", (r("market_rent"), r("reno_premium"), r("reno_cost")), columns="unit_type")
    expenses = Sheet("Operating Expenses", (r("opex_per_unit"), r("opex_rate"), r("opex_fixed"), r("opex_growth")),
                     columns="line")

    categories = [(c, label) for c, label in (("acquisition", "Acquisition costs"), ("financing", "Financing costs"),
                                              ("sponsor_fee", "Sponsor fees"))
                  if any(x.category == c for x in deal.closing_costs)]
    subtotal = {"acquisition": "acquisition_costs", "financing": "financing_costs", "sponsor_fee": "acquisition_fee"}
    sources_uses = Sheet("Sources & Uses", (
        Heading("Purchase"), r("purchase_price", True),
        *(x for c, label in categories for x in (
            Heading(label), g("closing_cost_amount", category=c),
            *(y for k in deal.closing_costs if k.category == c and k.method != "fixed" for y in (
                g("closing_cost_rate", f"{k.label}: % of {'price' if k.method == 'pct_price' else 'senior loan'}",
                  closing_cost=k.key),
                g("closing_cost", k.label, closing_cost=k.key))),
            Row(subtotal[c], "Total sponsor fees at closing" if c == "sponsor_fee" else None, None, True)
            if c == "sponsor_fee" else r(subtotal[c], True))),
        r("closing_costs", True),
        Heading("Capital budget funded at closing" + (" (Capital Budget sheet)" if deal.capex_phases else "")),
        *(() if deal.capex_phases else (r("reno_budget"), r("property_capex_budget"))), r("capex_budget", True),
        Heading("Reserves"), r("working_capital"), *no_phases,
        Heading("Sources and uses"),
        r("total_uses", True), r("debt_at_close"), r("equity_at_close", True),
    ))

    phase_rows = []
    for p in deal.capex_phases:
        funding = "funded at closing" if p.funding == "closing" else "paid at its month from capital-event cash"
        lines = [x for x in deal.capex_lines if x.phase == p.key]
        phase_rows += [
            Heading(f"{p.label} ({funding})"),
            g("capex_start_month", "Start month", capex_phase=p.key), g("capex_months", "Months", capex_phase=p.key),
            *([g("capex_amount", capex_phase=p.key)] if any(x.method == "lump" for x in lines) else []),
            *(y for x in lines if x.method == "unit_cost" for y in (
                g("capex_unit_cost", f"{x.label}: unit cost", capex_line=x.key),
                g("capex_count", f"{x.label}: count", capex_line=x.key),
                g("capex_line_cost", x.label, capex_line=x.key))),
            g("capex_hard", "Hard costs", total=True, capex_phase=p.key),
            g("capex_gc_rate", "General conditions rate", capex_phase=p.key),
            g("capex_gc", "General conditions", capex_phase=p.key),
            g("capex_gc_fee_rate", "GC fee rate", capex_phase=p.key),
            g("capex_gc_fee", "GC fee", capex_phase=p.key),
            g("capex_contingency_rate", "Contingency rate", capex_phase=p.key),
            g("capex_contingency", "Contingency", capex_phase=p.key),
            g("capex_phase_total", "Phase total", total=True, capex_phase=p.key),
        ]
    capex = Sheet("Capital Budget", (
        *phase_rows,
        Heading("Capital budget"),
        r("reno_budget"), r("property_capex_budget"), r("deferred_capex_budget"),
    ))

    capital = Sheet("Loan Sizing", (
        Heading("Senior loan sizing at closing"),
        r("senior.sizing_ncf"), r("senior.monthly_rate", fmt="0.0000%"),
        r("senior.payment_constant", fmt="0.0000%"), r("senior.ltv_amount"), r("senior.dscr_amount"),
        r("senior.amount", True), r("senior.payment"), r("senior.payoff_month"),
        Heading("Refinance sizing"),
        r("refi.trailing_ncf"), r("refi.value"), r("refi.monthly_rate", fmt="0.0000%"),
        r("refi.payment_constant", fmt="0.0000%"), r("refi.ltv_amount"), r("refi.dscr_amount"),
        r("refi.amount", True), r("refi.payment"), r("refi.fee"),
    ))

    annual_rows = {name: r(f"annual.{name}") for name in ANNUAL + (COMMERCIAL_ANNUAL if spaces else ())}
    for name in ("egi", "noi", "ncf", "levered_cash_flow", "unlevered_cash_flow", "rental_income_total",
                 "commercial.income"):
        annual_rows[name] = r(f"annual.{name}", True)
    commercial_income = ("commercial.potential_rent", "commercial.downtime_total", "commercial.recoveries_total",
                         "commercial.credit_loss", "commercial.income") if spaces else ()
    annual = Sheet("Annual Cash Flow", (
        Heading("Revenue"),
        *(annual_rows[n] for n in ("gpr_total", "loss_to_lease_total", "vacancy_total", "downtime_total",
                                   "rental_income_total", "vacancy_floor_adjustment", "bad_debt",
                                   "other_income_total", *commercial_income, "egi")),
        r("annual.occupancy"), r("annual.units_renovated"),
        Heading("Operating expenses"),
        r("annual.opex"), annual_rows["property_tax"], annual_rows["opex_total"],
        annual_rows["noi"], annual_rows["replacement_reserve_deposit"], annual_rows["ncf"],
        Heading("Debt and distributions"),
        annual_rows["cash_from_operations"], annual_rows["senior_debt_service"], r("annual.dscr"),
        *(r(f"annual.{t.key}.payment") for t in tranches),
        annual_rows["asset_management_fee"], annual_rows["operating_capital_call"],
        annual_rows["operating_distribution"], r("annual.cash_on_cash"),
        Heading("Capital"),
        annual_rows["capex_spend"],
        *([annual_rows["commercial.leasing_costs_total"]] if spaces else []), annual_rows["capital_event_cash"],
        Heading("Equity"),
        *(annual_rows[n] for n in ("equity_contributions", "equity_distributions", "levered_cash_flow",
                                   "lp_distribution", "gp_distribution", "gp_promote", "unlevered_cash_flow")),
    ), columns="hold_year")

    cash_flow = Sheet("Monthly Cash Flow", (
        Heading("Timeline"),
        r("live"), r("owned"), r("is_sale"), r("is_refi"), r("exit_window"), r("refi_window"),
        r("growth_year", fmt="0"),
        Heading("Revenue"),
        r("gpr_total"), r("loss_to_lease_total"), r("vacancy_total"), r("downtime_total"),
        r("rental_income_total", True), r("vacancy_floor_adjustment"), r("bad_debt"), r("other_income_total"),
        *(r(n, n == "commercial.income") for n in commercial_income),
        r("egi", True), r("occupied_units"), r("occupancy"),
        Heading("Operating expenses"),
        r("opex"), r("tax_market_value_now"),
        *([r("tax_max_assessed_now")] if deal.tax_method == "or_mav" else []),
        r("assessed_value"), r("property_tax"), r("opex_total", True),
        r("noi", True), r("replacement_reserve_deposit"), r("ncf", True),
        Heading("Capital spending"),
        r("reno_starts_total"), r("reno_spend"),
        *([g("capex_phase_spend", "Capital spend")] if deal.capex_phases else []),
        r("property_capex_spend"), r("deferred_capex_spend"), r("capex_spend", True),
        *([r("commercial.leasing_costs_total")] if spaces else []),
        r("capital_reserve.opening"), r("capital_reserve.deposits"), r("capital_reserve.available"),
        r("capital_reserve.draw"), r("capital_reserve.unfunded"), r("capital_reserve.released"),
        r("capex_reserve"),
        Heading("Operating cascade"),
        r("cash_from_operations"), r("senior_debt_service"), r("cash_after_senior", True),
        *(x for t in tranches for x in (r(f"{t.key}.cash_available"), r(f"{t.key}.cash_after"))),
        r("asset_management_fee"), r("cash_after_fees", True), r("operating_shortfall"),
        r("operating_reserve.opening"), r("operating_reserve.deposits"), r("operating_reserve.available"),
        r("operating_reserve.draw"), r("operating_reserve.unfunded"), r("operating_reserve.released"),
        r("operating_reserve.balance"), r("operating_funded_cash"), r("operating_funding_required"),
        r("operating_capital_call"),
        r("operating_distribution", True),
        Heading("Capital events"),
        r("sale.window_ncf"), *([r("sale.commercial_window")] if spaces else []), r("refi.window_ncf"),
        r("refi.costs"), r("loan_payoffs"), r("reserves_released"),
        r("capital_event_cash", True), r("capital_event_funding_required"), r("capital_event_call"), r("capital_event_distribution", True),
        Heading("Equity cash flows"),
        r("equity_contributions"), r("equity_distributions"), r("levered_cash_flow", True),
        r("unlevered_cash_flow", True),
    ), columns="month")

    rent_roll = Sheet("Rental Projection", (
        Heading("Rent growth"),
        r("market_factor", fmt="0.0000"), r("renewal_factor", fmt="0.000000"), r("market_rent_now"),
        Heading("Rent targets by cohort"),
        r("rent_limit"), r("classic_target"), r("renovated_target"),
        Heading("Classic units"),
        r("occupied_classic_open"), r("vacant_classic_open"), r("move_outs_classic"), r("scope_remaining_open"),
        r("reno_starts"), r("releases_classic"), r("vacant_classic"), r("occupied_classic", True),
        r("scope_remaining"),
        Heading("Renovation"),
        *(r(s) for s in stages), r("in_renovation", True), r("reno_completions"), r("units_converted"),
        Heading("Renovated units"),
        r("occupied_renovated_open"), r("vacant_renovated_open"), r("move_outs_renovated"),
        r("leases_renovated"), r("vacant_renovated"), r("occupied_renovated", True),
        Heading("Average rent per occupied unit"),
        r("rent_classic"), r("rent_renovated"),
        Heading("Revenue by cohort"),
        r("gpr"), r("loss_to_lease"), r("vacancy_loss"), r("downtime_loss"), r("rental_income", True),
    ), columns="month")

    lease_inputs = ("rent", "bump", "bump_month", "expiry_month", "option_exercised", "option_months",
                    "renewal_probability", "market_rent", "downtime_months", "ti", "lc", "recovery_share")
    commercial_leases = Sheet("Commercial Leases", (
        Heading("In-place lease"), *(r(f"commercial.{n}") for n in lease_inputs[:6]),
        Heading("Rollover"), *(r(f"commercial.{n}") for n in lease_inputs[6:11]),
        Heading("Reimbursements"), r("commercial.recovery_share"),
        Heading("Lease timeline"),
        r("commercial.lease_end", fmt="0"), r("commercial.rollover_month", fmt="0"),
        r("commercial.new_lease_month", fmt="0"),
    ), columns="space")
    commercial_projection = Sheet("Commercial Projection", (
        Heading("In-place leases"),
        r("commercial.scheduled_rent"), r("commercial.in_place", fmt="0"), r("commercial.contract_rent"),
        Heading("Second-generation leases"),
        r("commercial.market_rent_now"), r("commercial.renewal_lease_year_month", fmt="0"),
        r("commercial.renewal_rent"), r("commercial.new_lease_year_month", fmt="0"), r("commercial.new_rent"),
        Heading("Income by space"),
        r("commercial.base_rent"), r("commercial.occupancy"), r("commercial.downtime"), r("recoverable_costs"),
        r("commercial.recoveries"), r("commercial.leasing_costs"),
        Heading("Commercial totals (income lines on Monthly Cash Flow)"),
        r("commercial.base_rent_total", True), r("commercial.net_rent"),
        r("commercial.occupied_sf_total", fmt="#,##0"),
    ), columns="month")
    commercial_sheets = (commercial_leases,) if spaces else ()

    loan_rows = ("opening", "funding", "interest", "principal", "payoff", "balance", "debt_service")
    tranche_rows = ("opening", "accrued_opening", "funding", "interest_due", "interest_paid", "principal_paid",
                    "payment", "payoff", "accrued", "balance")
    debt = Sheet("Debt Schedule", (
        Heading("Senior loan"), *(r(f"senior.{f}", f in ("balance", "debt_service")) for f in loan_rows),
        Heading("Refinance loan"), *(r(f"refi.{f}", f in ("balance", "debt_service")) for f in loan_rows),
        *(x for t in tranches for x in (
            Heading(f"{t.label} ({t.mode.replace('_', ' ')})"),
            *(r(f"{t.key}.{f}", f in ("balance", "payment")) for f in tranche_rows))),
    ), columns="month")

    waterfall = Sheet("Partnership Waterfall", (
        Heading("Contributions"),
        r("lp_contribution"), r("gp_contribution"),
        Heading("Tier 1: return of capital and preferred return"),
        r("pref.accrual", fmt="0.0000%"), r("pref.opening"), r("tier_1", True), r("pref.balance"),
        Heading("Catch-up"),
        r("wf.contributions_to_date"), r("wf.distributions_before"), r("wf.profit_after_tier_1"),
        r("wf.promote_before"), r("wf.catch_up_owed"), r("tier_catch_up", True),
        Heading("Tier 2: to the second hurdle"),
        r("hurdle.accrual", fmt="0.0000%"), r("hurdle.opening"), r("tier_2", True), r("hurdle.balance"),
        Heading("Tier 3: residual"),
        r("tier_3", True),
        Heading("Distributions and returns"),
        r("lp_distribution"), r("gp_distribution"), r("gp_promote"), r("wf.distributions_to_date"),
        r("wf.promote_to_date"), r("lp_cash_flow", True),
        r("gp_cash_flow", True),
    ), columns="month")

    proforma = Sheet("Pro Forma", (
        Heading("Revenue"),
        r("pf.gpr"), r("pf.loss_to_lease"), r("pf.vacancy"), r("pf.downtime"), r("pf.rental_income", True),
        r("pf.vacancy_floor"), r("pf.bad_debt"), r("pf.other_income"),
        *((r("pf.commercial_rent"), r("pf.commercial_vacancy"), r("pf.commercial_recoveries"),
           r("pf.commercial_credit_loss"), r("pf.commercial_income", True)) if spaces else ()),
        r("pf.egi", True),
        Heading("Operating expenses"),
        g("pf.opex"), r("pf.property_tax"), r("pf.opex_total", True),
        r("pf.noi", True), r("pf.reserves"), r("pf.ncf", True),
        Heading("Measures"),
        r("pf.occupancy"), r("pf.noi_per_unit"), r("pf.opex_per_unit"), r("pf.expense_ratio"), r("pf.cap_rate"),
        r("pf.yield_on_cost"),
    ), columns="pf_case")

    return Layout((assumptions, sources_uses, *([capex] if deal.capex_phases else []), proforma, annual, capital,
                   unit_mix, unit_types, *commercial_sheets, expenses, cash_flow, rent_roll,
                   *([commercial_projection] if spaces else []), debt, waterfall, summary),
                  units=UNITS, header=sponsor,
                  footer=f"{sponsor} · Confidential — for discussion purposes only" if CONFIDENTIAL else sponsor)
