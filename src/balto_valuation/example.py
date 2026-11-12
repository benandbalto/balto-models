"""A synthetic Oregon value-add deal for demonstrations and tests.

Every figure here is invented. The 60% AMI limits and utility allowances are
placeholders shaped like a published table, not HUD or OHCS figures.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from balto_model_engine.commercial import CommercialSpace

from .deal import CapexLine, CapexPhase, Cohort, Deal, OpexLine, Tranche, UnitType


def example_deal() -> Deal:
    return Deal(
        name="Alder Court (synthetic)",
        closing=date(2026, 12, 31),
        horizon_years=10,
        unit_types=(UnitType("1br", "1 BR / 1 BA", 1), UnitType("2br", "2 BR / 1 BA", 2)),
        cohorts=(
            Cohort("1br_mkt", "1 BR market", "1br", "market", renovate=True),
            Cohort("2br_mkt", "2 BR market", "2br", "market", renovate=True),
            Cohort("1br_60", "1 BR 60% AMI", "1br", "restricted"),
            Cohort("2br_60", "2 BR 60% AMI", "2br", "restricted"),
            Cohort("2br_hap", "2 BR HAP contract", "2br", "contract"),
        ),
        opex_lines=(
            OpexLine("payroll", "Payroll & benefits", "per_unit"),
            OpexLine("repairs", "Repairs & maintenance", "per_unit"),
            OpexLine("turnover", "Turnover & make-ready", "per_unit"),
            OpexLine("utilities", "Utilities", "per_unit"),
            OpexLine("insurance", "Insurance", "per_unit"),
            OpexLine("admin", "Administrative & marketing", "per_unit"),
            OpexLine("contracts", "Contract services", "per_unit"),
            OpexLine("management", "Management fee", "pct_egi"),
            OpexLine("audit", "Audit, legal & compliance", "fixed"),
        ),
        tax_method="or_mav",
        tranches=(
            Tranche("city_loan", "City soft loan", "cash_sweep"),
            Tranche("seller_note", "Seller note", "accrue"),
        ),
        downtime_months=2,
        location="Portland, Oregon (synthetic example)",
        capex_phases=(
            CapexPhase("exterior", "Exterior and common areas", "closing"),
            CapexPhase("systems", "Year 3 building systems", "event"),
        ),
        capex_lines=(
            CapexLine("roof", "Roof replacement", "exterior", "lump"),
            CapexLine("paint", "Exterior paint and siding repair", "exterior", "lump"),
            CapexLine("common", "Lobby, corridors and amenity refresh", "exterior", "lump"),
            CapexLine("locks", "Smart locks", "exterior", "unit_cost"),
            CapexLine("boilers", "Boiler and domestic hot water replacement", "systems", "lump"),
        ),
    )


def example_inputs() -> dict:
    return {
        # Timeline
        "sale_month": 60, "refi_included": 1, "refi_month": 30,
        # Unit types
        "market_rent": {"1br": 1450, "2br": 1750},
        "reno_premium": {"1br": 175, "2br": 210},
        "reno_cost": {"1br": 18000, "2br": 22000},
        # Cohorts
        "units": {"1br_mkt": 20, "2br_mkt": 20, "1br_60": 12, "2br_60": 8, "2br_hap": 4},
        "occupied_at_close": {"1br_mkt": 19, "2br_mkt": 18, "1br_60": 12, "2br_60": 8, "2br_hap": 4},
        "in_place_rent": {"1br_mkt": 1320, "2br_mkt": 1590, "1br_60": 1380, "2br_60": 1740, "2br_hap": 1900},
        "rent_limit_gross": {"1br_60": 1520, "2br_60": 1824},
        "utility_allowance": {"1br_60": 95, "2br_60": 120},
        "contract_rent": {"2br_hap": 1900},
        "reno_scope": {"1br_mkt": 20, "2br_mkt": 20},
        "reno_pace": {"1br_mkt": 2, "2br_mkt": 2},
        "market_growth": "0.03", "renewal_increase": "0.04", "rent_cap": "0.095", "turnover": "0.40",
        "ami_growth": "0.03", "ua_growth": "0.03", "ocaf": "0.025", "reno_start_month": 2,
        "mark_to_market": 1,
        # Operations
        "vacancy_floor": "0.05", "bad_debt_rate": "0.015", "other_income": 45,
        "opex_per_unit": {"payroll": 1800, "repairs": 900, "turnover": 350, "utilities": 1500, "insurance": 750,
                          "admin": 400, "contracts": 450},
        "opex_rate": {"management": "0.045"},
        "opex_fixed": {"audit": 12000},
        "opex_growth": {"payroll": "0.035", "repairs": "0.03", "turnover": "0.03", "utilities": "0.04",
                        "insurance": "0.06", "admin": "0.03", "contracts": "0.03", "management": 0,
                        "audit": "0.03"},
        "tax_market_value": 9800000, "tax_max_assessed_value": 6400000, "tax_market_growth": "0.04",
        "tax_levy_rate": "0.0175", "tax_exemption": 0,
        "replacement_reserve": 300,
        # Capital budget
        "purchase_price": 9600000, "working_capital": 100000,
        "capex_amount": {"roof": 180000, "paint": 110000, "common": 60000, "boilers": 150000},
        "capex_unit_cost": {"locks": 500}, "capex_count": {"locks": 64},
        "capex_start_month": {"exterior": 1, "systems": 30}, "capex_months": {"exterior": 12, "systems": 1},
        "capex_gc_rate": {"exterior": "0.05", "systems": 0}, "capex_gc_fee_rate": {"exterior": 0, "systems": 0},
        "capex_contingency_rate": {"exterior": 0, "systems": "0.10"},
        # Closing costs (the standard list)
        "closing_cost_amount": {"title_escrow": 45000, "buyer_legal": 60000, "third_party": 35000,
                                "due_diligence": 15000, "lender_legal": 35000, "loan_application": 10000,
                                "lender_reports": 12000, "rate_lock": 0},
        "closing_cost_rate": {"transfer_tax": 0, "origination": "0.01", "acquisition_fee": "0.01"},
        # Senior loan
        "senior.max_ltv": "0.65", "senior.min_dscr": "1.25", "senior.rate": "0.0575", "senior.amort_years": 30,
        "senior.io_months": 24,
        # Refinance
        "refi.cap_rate": "0.0525", "refi.max_ltv": "0.70", "refi.min_dscr": "1.25", "refi.rate": "0.0575",
        "refi.amort_years": 30, "refi.io_months": 0, "refi.fee_rate": "0.01",
        # Subordinate tranches
        "city_loan.amount": 750000, "city_loan.rate": "0.03", "city_loan.sweep_share": "0.5",
        "seller_note.amount": 500000, "seller_note.rate": "0.06",
        # Partnership and exit
        "asset_management_fee_rate": "0.01",
        "exit_cap_rate": "0.0525", "selling_cost_rate": "0.02", "disposition_fee_rate": "0.005",
        "lp_share": "0.9", "pref_rate": "0.08", "hurdle_rate": "0.14", "promote_1": "0.2", "promote_2": "0.3",
        "catch_up_share": 0,
        "set_aside_units": 20,
    }


def example_mixed_use() -> tuple[Deal, dict]:
    """The example with two invented ground-floor spaces: a NNN cafe on options and a gross office rolling."""
    deal = example_deal()
    deal = replace(
        deal, name="Alder Court Mixed-Use (synthetic)",
        opex_lines=tuple(replace(x, recoverable=x.key == "insurance") for x in deal.opex_lines),
        commercial_spaces=(CommercialSpace("cafe", "Corner cafe (NNN)", 2600, "nnn"),
                           CommercialSpace("office", "Office suite (gross)", 1800, "gross")))
    inputs = {
        **example_inputs(),
        "commercial.rent": {"cafe": 72000, "office": 21600},
        "commercial.bump": {"cafe": "0.025", "office": 0},
        "commercial.bump_month": {"cafe": 7, "office": 2},
        "commercial.expiry_month": {"cafe": 6, "office": 17},
        "commercial.option_exercised": {"cafe": 1, "office": 0},
        "commercial.option_months": {"cafe": 60, "office": 0},
        "commercial.renewal_probability": {"cafe": "0.5", "office": "0.4"},
        "commercial.market_rent": {"cafe": 30, "office": 22},
        "commercial.downtime_months": {"cafe": 5, "office": 5},
        "commercial.ti": {"cafe": 20, "office": 30},
        "commercial.lc": {"cafe": 5, "office": 5},
        "commercial.recovery_share": {"cafe": "0.25"},
        "commercial.market_growth": "0.025", "commercial.new_lease_bump": "0.03",
        "commercial.credit_loss_rate": "0.04", "commercial_exit_cap_rate": "0.0725",
    }
    return deal, inputs
