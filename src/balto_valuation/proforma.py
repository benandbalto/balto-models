"""The pro forma: the property P&L line by line, side by side for four cases.

- **In-place**: the rent roll at closing annualized: occupied units at their
  in-place rents, vacant units lost, expenses at their underwritten year-one
  levels.
- **Year 1**: the projection's first hold year.
- **Stabilized (untrended)**: every unit leased at closing-date targets (units
  in the renovation scope at the renovated target), vacancy at the economic
  floor, expenses at year-one levels, no growth. When in-place rents hold
  (`mark_to_market` 0), units occupied at closing keep their in-place rents,
  shown as loss to lease.
- **Exit year**: the buyer's forward twelve months after the sale, the income
  the sale price is set on.

Commercial space in the untrended cases: in-place, a space leased at closing
at its in-place rent and a vacant one at closing-date market rent, lost to
vacancy; stabilized, every space leased, at its in-place rent when the lease
(with options exercised) runs through the sale and at closing-date market rent
otherwise. NNN recoveries are on year-one property tax and recoverable lines;
credit loss is at its rate.

Revenue deductions are negative so each block adds down; expenses are positive
and NOI is EGI less expenses.
"""

from __future__ import annotations

from balto_model_engine import Dimension, Item, Model, attr, if_, matches, max_, min_, ref, sum_over
from balto_model_engine.commercial import CommercialIncome

from .deal import Deal

CASES = (("in_place", "In-place (annualized)"), ("year_1", "Year 1"),
         ("stabilized", "Stabilized (untrended)"), ("exit_year", "Exit year (forward 12)"))
CASE = ("pf_case",)


def _by_case(in_place, year_1, stabilized, exit_year):
    return if_(matches("pf_case", case="in_place"), in_place,
               if_(matches("pf_case", case="year_1"), year_1,
                   if_(matches("pf_case", case="stabilized"), stabilized, exit_year)))


def _year_1(name):
    return sum_over("month", ref(name), hold_year=1)


def _exit(name):
    return sum_over("month", ref(name) * ref("exit_window"))


def _at_closing(name):
    """A monthly figure's value at closing (month 0), before any growth."""
    return sum_over("month", ref(name), index=0)


def build(m: Model, deal: Deal, *, commercial: CommercialIncome | None = None) -> None:
    m.dimension(Dimension("pf_case", [Item(k, label=label, case=k) for k, label in CASES]))
    occupied, units, floor = ref("occupied_at_close"), ref("units"), ref("vacancy_floor")
    classic, renovated = _at_closing("classic_target"), _at_closing("renovated_target")
    stabilized_classic, stabilized_renovated = classic, renovated

    # --- Revenue -----------------------------------------------------------------------------
    stabilized_gpr = sum_over("cohort", if_(matches("cohort", renovate=True),
                                            (units - ref("reno_scope")) * stabilized_classic
                                            + ref("reno_scope") * stabilized_renovated,
                                            units * stabilized_classic))
    # When in-place rents hold, the units occupied at closing (outside the renovation
    # scope) keep their in-place rent, so their gap to the target stays as loss to lease.
    held = if_(matches("cohort", renovate=True), min_(occupied, units - ref("reno_scope")), occupied)
    held_gap = sum_over("cohort", if_(matches("cohort", regime="contract"), 0,
                                      held * max_(classic - ref("in_place_rent"), 0)))
    m.calc("pf.gpr", unit="usd", dims=CASE,
           expr=_by_case(12 * sum_over("cohort", units * classic), _year_1("gpr_total"), 12 * stabilized_gpr,
                         _exit("gpr_total")))
    m.calc("pf.loss_to_lease", unit="usd", dims=CASE,
           expr=_by_case(-12 * sum_over("cohort", occupied * (classic - ref("in_place_rent"))),
                         -_year_1("loss_to_lease_total"), if_(ref("mark_to_market") > 0, 0, -12 * held_gap),
                         -_exit("loss_to_lease_total")))
    m.calc("pf.vacancy", unit="usd", dims=CASE,
           expr=_by_case(-12 * sum_over("cohort", (units - occupied) * classic), -_year_1("vacancy_total"), 0,
                         -_exit("vacancy_total")))
    m.calc("pf.downtime", unit="usd", dims=CASE,
           expr=_by_case(0, -_year_1("downtime_total"), 0, -_exit("downtime_total")))
    m.calc("pf.rental_income", unit="usd", dims=CASE,
           expr=ref("pf.gpr") + ref("pf.loss_to_lease") + ref("pf.vacancy") + ref("pf.downtime"))
    # The economic vacancy floor tops up physical vacancy and downtime to the floor.
    floor_gap = -max_(floor * ref("pf.gpr") + ref("pf.vacancy") + ref("pf.downtime"), 0)
    m.calc("pf.vacancy_floor", unit="usd", dims=CASE,
           expr=_by_case(floor_gap, -_year_1("vacancy_floor_adjustment"), floor_gap,
                         -_exit("vacancy_floor_adjustment")))
    rated = -ref("bad_debt_rate") * (ref("pf.rental_income") + ref("pf.vacancy_floor"))
    m.calc("pf.bad_debt", unit="usd", dims=CASE,
           expr=_by_case(rated, -_year_1("bad_debt"), rated, -_exit("bad_debt")))
    m.calc("pf.other_income", unit="usd", dims=CASE,
           expr=_by_case(12 * ref("other_income") * sum_over("cohort", occupied), _year_1("other_income_total"),
                         12 * ref("other_income") * ref("total_units") * (1 - floor), _exit("other_income_total")))
    egi = ref("pf.rental_income") + ref("pf.vacancy_floor") + ref("pf.bad_debt") + ref("pf.other_income")
    if commercial is not None and commercial.has_spaces:
        _commercial(m)
        egi = egi + ref("pf.commercial_income")
    m.calc("pf.egi", unit="usd", dims=CASE, expr=egi)

    # --- Expenses at year-one levels (untrended cases) ---------------------------------------------
    base = if_(matches("line", method="per_unit"), ref("opex_per_unit") * ref("total_units"),
               if_(matches("line", method="pct_egi"), ref("opex_rate") * ref("pf.egi"), ref("opex_fixed")))
    m.calc("pf.opex", unit="usd", dims=("line", "pf_case"),
           expr=_by_case(base, _year_1("opex"), base, _exit("opex")))
    tax = _at_closing("assessed_value") * ref("tax_levy_rate") * (1 - ref("tax_exemption"))
    m.calc("pf.property_tax", unit="usd", dims=CASE,
           expr=_by_case(tax, _year_1("property_tax"), tax, _exit("property_tax")))
    m.calc("pf.opex_total", unit="usd", dims=CASE, expr=sum_over("line", ref("pf.opex")) + ref("pf.property_tax"))
    m.calc("pf.noi", unit="usd", dims=CASE, expr=ref("pf.egi") - ref("pf.opex_total"))
    reserve = ref("replacement_reserve") * ref("total_units")
    m.calc("pf.reserves", unit="usd", dims=CASE,
           expr=_by_case(reserve, _year_1("replacement_reserve_deposit"), reserve,
                         _exit("replacement_reserve_deposit")))
    m.calc("pf.ncf", unit="usd", dims=CASE, expr=ref("pf.noi") - ref("pf.reserves"))

    # --- Measures ----------------------------------------------------------------------------------
    m.calc("pf.occupancy", unit="rate", dims=CASE,
           expr=_by_case(sum_over("cohort", occupied) / ref("total_units"), _year_1("occupancy") / 12, 1 - floor,
                         _exit("occupancy") / 12))
    m.calc("pf.noi_per_unit", unit="usd/unit", dims=CASE, expr=ref("pf.noi") / ref("total_units"))
    m.calc("pf.opex_per_unit", unit="usd/unit", dims=CASE, expr=ref("pf.opex_total") / ref("total_units"))
    m.calc("pf.expense_ratio", unit="rate", dims=CASE,
           expr=if_(ref("pf.egi") > 0, ref("pf.opex_total") / ref("pf.egi"), 0))
    m.calc("pf.cap_rate", unit="rate", dims=CASE, expr=ref("pf.noi") / ref("purchase_price"))
    m.calc("pf.yield_on_cost", unit="rate", dims=CASE, expr=ref("pf.noi") / ref("all_in_cost"))


def _commercial(m: Model) -> None:
    c = lambda name: ref(f"commercial.{name}")
    leased = if_(c("expiry_month") > 0, 1, 0)
    market = c("market_rent") * attr("space", "sf")
    potential = sum_over("space", leased * c("rent") + (1 - leased) * market)
    # Stabilized, a lease that runs (with its options) through the sale keeps its rent; any other is at market.
    held = if_(c("lease_end") >= ref("sale_month"), 1, 0)
    stabilized = sum_over("space", held * c("rent") + (1 - held) * market)
    m.calc("pf.commercial_rent", unit="usd", dims=CASE,
           expr=_by_case(potential, _year_1("commercial.potential_rent"), stabilized,
                         _exit("commercial.potential_rent")))
    m.calc("pf.commercial_vacancy", unit="usd", dims=CASE,
           expr=_by_case(-sum_over("space", (1 - leased) * market), -_year_1("commercial.downtime_total"), 0,
                         -_exit("commercial.downtime_total")))
    # Year-one recoverable costs, from the inputs (the pro forma's share-of-income lines depend on income).
    recoverable = (_at_closing("assessed_value") * ref("tax_levy_rate") * (1 - ref("tax_exemption"))
                   + sum_over("line", if_(matches("line", method="per_unit"), ref("opex_per_unit") * ref("total_units"),
                                          ref("opex_fixed")), recoverable=True))
    m.calc("pf.commercial_recoveries", unit="usd", dims=CASE,
           expr=_by_case(sum_over("space", c("recovery_share") * leased, lease_type="nnn") * recoverable,
                         _year_1("commercial.recoveries_total"),
                         sum_over("space", c("recovery_share"), lease_type="nnn") * recoverable,
                         _exit("commercial.recoveries_total")))
    rated = -c("credit_loss_rate") * (ref("pf.commercial_rent") + ref("pf.commercial_vacancy")
                                      + ref("pf.commercial_recoveries"))
    m.calc("pf.commercial_credit_loss", unit="usd", dims=CASE,
           expr=_by_case(rated, -_year_1("commercial.credit_loss"), rated, -_exit("commercial.credit_loss")))
    m.calc("pf.commercial_income", unit="usd", dims=CASE,
           expr=ref("pf.commercial_rent") + ref("pf.commercial_vacancy") + ref("pf.commercial_recoveries")
           + ref("pf.commercial_credit_loss"))
