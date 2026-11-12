"""A deal's structure: what the model is built over, as opposed to the values it is run with.

Structure decides which variables and formulas exist: the unit cohorts and
their rent regimes, the expense lines and their methods, the property-tax
method, the subordinate tranches and their payment modes, the commercial
spaces and their lease types, and the horizon.
Everything an analyst flexes (rents, rates, months, prices) is an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from balto_model_engine.commercial import CommercialSpace

REGIMES = ("market", "restricted", "contract")
OPEX_METHODS = ("per_unit", "pct_egi", "fixed")
TAX_METHODS = ("or_mav", "wa_market")
SENIOR_LOANS = ("sized", "assumed")
PAYMENT_MODES = ("accrue", "available_cash", "cash_sweep", "scheduled")
CLOSING_COST_CATEGORIES = ("acquisition", "financing", "sponsor_fee")
CLOSING_COST_METHODS = ("fixed", "pct_price", "pct_senior")
CAPEX_FUNDING = ("closing", "event")
CAPEX_METHODS = ("lump", "unit_cost")


@dataclass(frozen=True)
class UnitType:
    key: str
    label: str
    bedrooms: int


@dataclass(frozen=True)
class Cohort:
    """Units of one type under one rent regime, renovated or not, tracked together."""
    key: str
    label: str
    unit_type: str
    regime: str
    renovate: bool = False


@dataclass(frozen=True)
class OpexLine:
    """An expense line. A recoverable line is reimbursed by NNN commercial tenants, with property tax."""
    key: str
    label: str
    method: str
    recoverable: bool = False


@dataclass(frozen=True)
class Tranche:
    """A subordinate loan funded at closing and repaid at sale, paid per its mode."""
    key: str
    label: str
    mode: str


@dataclass(frozen=True)
class ClosingCost:
    """One closing cost: a fixed amount, a share of the price, or a share of the senior loan."""
    key: str
    label: str
    category: str
    method: str


@dataclass(frozen=True)
class CapexPhase:
    """A phase of the capital budget.

    `closing`: funded into the capital reserve at closing and spent evenly over
    its months. `event`: paid in its months from that month's capital-event cash
    (a refinance, say), or called from equity when there is none.
    """
    key: str
    label: str
    funding: str


@dataclass(frozen=True)
class CapexLine:
    """A hard-cost line of a phase: a lump sum, or a unit cost times a count."""
    key: str
    label: str
    phase: str
    method: str


# The usual closing costs; a deal lists its own when these do not fit.
STANDARD_CLOSING_COSTS = (
    ClosingCost("title_escrow", "Title insurance & escrow", "acquisition", "fixed"),
    ClosingCost("transfer_tax", "Transfer / excise tax", "acquisition", "pct_price"),
    ClosingCost("buyer_legal", "Buyer legal", "acquisition", "fixed"),
    ClosingCost("third_party", "Third-party reports (appraisal, PCA, environmental, survey)", "acquisition", "fixed"),
    ClosingCost("due_diligence", "Due diligence & travel", "acquisition", "fixed"),
    ClosingCost("origination", "Lender origination fee", "financing", "pct_senior"),
    ClosingCost("lender_legal", "Lender legal", "financing", "fixed"),
    ClosingCost("loan_application", "Loan application & processing", "financing", "fixed"),
    ClosingCost("lender_reports", "Lender third-party reports", "financing", "fixed"),
    ClosingCost("rate_lock", "Rate lock / buydown", "financing", "fixed"),
    ClosingCost("acquisition_fee", "Acquisition fee", "sponsor_fee", "pct_price"),
)


@dataclass(frozen=True)
class Deal:
    name: str
    closing: date
    horizon_years: int
    unit_types: tuple[UnitType, ...]
    cohorts: tuple[Cohort, ...]
    opex_lines: tuple[OpexLine, ...]
    tax_method: str
    tranches: tuple[Tranche, ...] = field(default_factory=tuple)
    # Months a unit is offline once its renovation starts.
    downtime_months: int = 2
    # Where the property is, for the workbook's cover; it changes no figure.
    location: str = ""
    closing_costs: tuple[ClosingCost, ...] = STANDARD_CLOSING_COSTS
    capex_phases: tuple[CapexPhase, ...] = field(default_factory=tuple)
    capex_lines: tuple[CapexLine, ...] = field(default_factory=tuple)
    # Ground-floor retail and other commercial space, each under its own lease.
    commercial_spaces: tuple[CommercialSpace, ...] = field(default_factory=tuple)
    # `sized`: a new senior loan sized on LTV and DSCR. `assumed`: the seller's loan, taken over at its
    # balance and terms; what a new loan would size to is reported beside it.
    senior_loan: str = "sized"
    # Whether the property-tax exemption ends during the hold (a multifamily tax exemption, say).
    tax_exemption_ends: bool = False

    def __post_init__(self) -> None:
        types = {t.key for t in self.unit_types}
        # Every period is a whole month: a closing mid-month would need stub-period proration.
        if (self.closing + timedelta(days=1)).day != 1:
            raise ValueError("Closing must be the last day of a month.")
        if not 2 <= self.horizon_years <= 30:
            raise ValueError("The horizon is 2 to 30 years.")
        for c in self.cohorts:
            if c.unit_type not in types or c.regime not in REGIMES:
                raise ValueError(f"Cohort {c.key} names an unknown unit type or regime.")
            if c.renovate and c.regime == "contract":
                raise ValueError(f"Cohort {c.key}: a contract cohort's rent does not change with renovation.")
        for line in self.opex_lines:
            if line.method not in OPEX_METHODS:
                raise ValueError(f"Expense line {line.key} has an unknown method.")
            # A recovery on a share of income would be circular.
            if line.recoverable and line.method == "pct_egi":
                raise ValueError(f"Expense line {line.key}: a share-of-income line is not recoverable.")
        if self.tax_method not in TAX_METHODS:
            raise ValueError("Property tax method must be or_mav or wa_market.")
        if self.senior_loan not in SENIOR_LOANS:
            raise ValueError("The senior loan is sized or assumed.")
        for t in self.tranches:
            if t.mode not in PAYMENT_MODES:
                raise ValueError(f"Tranche {t.key} has an unknown payment mode.")
        if self.downtime_months < 1:
            raise ValueError("Renovation downtime is at least one month.")
        for c in self.closing_costs:
            if c.category not in CLOSING_COST_CATEGORIES or c.method not in CLOSING_COST_METHODS:
                raise ValueError(f"Closing cost {c.key} has an unknown category or method.")
        phases = {p.key for p in self.capex_phases}
        for p in self.capex_phases:
            if p.funding not in CAPEX_FUNDING:
                raise ValueError(f"Capital phase {p.key} is funded at closing or at an event.")
        for line in self.capex_lines:
            if line.phase not in phases or line.method not in CAPEX_METHODS:
                raise ValueError(f"Capital line {line.key} names an unknown phase or method.")
        for group in (self.closing_costs, self.capex_phases, self.capex_lines, self.commercial_spaces):
            if len({x.key for x in group}) != len(group):
                raise ValueError("Keys must be unique.")
        keys = [c.key for c in self.cohorts] + [t.key for t in self.unit_types]
        if len(set(keys)) != len(keys) or len({t.key for t in self.tranches}) != len(self.tranches):
            raise ValueError("Keys must be unique.")
