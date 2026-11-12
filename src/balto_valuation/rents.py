"""Unit cohorts, rent regimes, turnover and the renovation program.

Each cohort's units move between states every month, as expected values:

    occupied classic --turnover--> vacant classic --start--> in renovation --downtime--> vacant renovated
    vacant classic --re-lease (next month)--> occupied classic
    vacant renovated --lease (next month)--> occupied renovated --turnover--> vacant renovated

Rent per occupied unit is a weighted average: renewing leases grow by the
renewal increase (limited by the statewide cap) but not past the regime's
target; new leases sign at the target. Targets come from the regime:

- market: market rent, plus the renovation premium once renovated;
- restricted: the lesser of market and the net limit (gross limit for the
  AMI tier less the utility allowance), so a premium above the limit is lost;
- contract: the contract rent, adjusted annually by OCAF.
"""

from __future__ import annotations

from balto_model_engine import (
    Dimension, Item, Model, const, if_, lag, matches, max_, min_, power, ref, round_to, sum_over, total,
)

from balto_model_engine.rents import rent_target
from .deal import Deal
from .timeline import IDX

CM = ("cohort", "month")


def _by_regime(market, restricted, contract):
    return if_(matches("cohort", regime="market"), market,
               if_(matches("cohort", regime="restricted"), restricted, contract))


def _renovating(then, otherwise=0):
    return if_(matches("cohort", renovate=True), then, otherwise)


def build(m: Model, deal: Deal) -> None:
    m.dimension(Dimension("unit_type", [Item(t.key, label=t.label, bedrooms=t.bedrooms) for t in deal.unit_types]))
    m.dimension(Dimension("cohort", [Item(c.key, label=c.label, unit_type=c.unit_type, regime=c.regime,
                                          renovate=c.renovate) for c in deal.cohorts], parent="unit_type"))

    # --- Inputs ---------------------------------------------------------------
    m.input("market_rent", unit="usd/unit-month", dims=("unit_type",), minimum=0)
    m.input("reno_premium", unit="usd/unit-month", dims=("unit_type",), minimum=0)
    m.input("reno_cost", unit="usd/unit", dims=("unit_type",), minimum=0)
    m.input("units", unit="units", dims=("cohort",), minimum=0)
    m.input("occupied_at_close", unit="units", dims=("cohort",), minimum=0)
    m.input("in_place_rent", unit="usd/unit-month", dims=("cohort",), minimum=0)
    m.input("rent_limit_gross", unit="usd/unit-month", dims=("cohort",), minimum=0, where={"regime": "restricted"})
    m.input("utility_allowance", unit="usd/unit-month", dims=("cohort",), minimum=0,
            where={"regime": "restricted"})
    m.input("contract_rent", unit="usd/unit-month", dims=("cohort",), minimum=0, where={"regime": "contract"})
    m.input("reno_scope", unit="units", dims=("cohort",), minimum=0, where={"renovate": True})
    m.input("reno_pace", unit="units/month", dims=("cohort",), minimum=0, where={"renovate": True})
    for name, lo, hi in (("market_growth", -0.2, 0.5), ("renewal_increase", 0, 0.5), ("rent_cap", 0, 1),
                         ("turnover", 0, 1), ("ami_growth", -0.2, 0.5), ("ua_growth", -0.2, 0.5),
                         ("ocaf", -0.2, 0.5)):
        m.input(name, unit="rate/year", minimum=lo, maximum=hi)
    m.input("reno_start_month", unit="month", minimum=1)
    # 1: a unit that turns over re-leases at the target rent; 0: in-place rents hold and grow as renewals.
    m.input("mark_to_market", unit="flag", minimum=0, maximum=1)
    m.check("mark_to_market_whole", condition=ref("mark_to_market") == round_to(ref("mark_to_market"), 0),
            code="EVENT_NOT_WHOLE", message="mark_to_market must be 0 or 1.")
    m.check("occupied_within_units", dims=("cohort",), condition=ref("occupied_at_close") <= ref("units"),
            code="OCCUPIED_EXCEEDS_UNITS", message="A cohort has more occupied units than units.")
    m.check("scope_within_units", dims=("cohort",), where={"renovate": True},
            condition=ref("reno_scope") <= ref("units"), code="SCOPE_EXCEEDS_UNITS",
            message="A cohort's renovation scope exceeds its units.")

    # --- Rent targets ---------------------------------------------------------
    month = ("month",)
    m.calc("market_factor", unit="factor", dims=month, expr=power(1 + ref("market_growth"), IDX / 12))
    # Renewals compound monthly at the renewal increase, limited by the statewide cap.
    m.calc("renewal_factor", unit="factor", dims=month,
           expr=if_(IDX >= 1, power(1 + min_(ref("renewal_increase"), ref("rent_cap")), const(1) / 12), 1))
    m.calc("market_rent_now", unit="usd/unit-month", dims=("unit_type", "month"),
           expr=ref("market_rent") * ref("market_factor"))
    m.calc("rent_limit", unit="usd/unit-month", dims=CM,
           expr=_by_regime(0, ref("rent_limit_gross") * power(1 + ref("ami_growth"), ref("growth_year"))
                           - ref("utility_allowance") * power(1 + ref("ua_growth"), ref("growth_year")), 0))
    m.calc("classic_target", unit="usd/unit-month", dims=CM,
           expr=_by_regime(ref("market_rent_now"), rent_target(ref("market_rent_now"), net_ceiling=ref("rent_limit")),
                           ref("contract_rent") * power(1 + ref("ocaf"), ref("growth_year"))))
    renovated_market = ref("market_rent_now") + ref("reno_premium") * ref("market_factor")
    m.calc("renovated_target", unit="usd/unit-month", dims=CM,
           expr=_by_regime(renovated_market, rent_target(renovated_market, net_ceiling=ref("rent_limit")), ref("classic_target")))

    # --- Unit states: classic units ---------------------------------------------
    live = ref("live")
    m.calc("occupied_classic_open", unit="units", dims=CM,
           expr=lag("occupied_classic", "month", initial=ref("occupied_at_close")))
    m.calc("vacant_classic_open", unit="units", dims=CM,
           expr=lag("vacant_classic", "month", initial=ref("units") - ref("occupied_at_close")))
    m.calc("move_outs_classic", unit="units", dims=CM,
           expr=ref("occupied_classic_open") * ref("turnover") / 12 * live)
    m.calc("scope_remaining_open", unit="units", dims=CM,
           expr=lag("scope_remaining", "month", initial=_renovating(ref("reno_scope"))))
    available = ref("vacant_classic_open") + ref("move_outs_classic")
    starts = min_(available, ref("reno_pace"), ref("scope_remaining_open"))
    m.calc("reno_starts", unit="units", dims=CM,
           expr=_renovating(if_(IDX >= ref("reno_start_month"), starts, 0)))
    from_vacant = ref("reno_starts")
    # Units vacant at the start of the month that are not renovated re-lease this month.
    m.calc("releases_classic", unit="units", dims=CM,
           expr=max_(ref("vacant_classic_open") - from_vacant, 0) * live)
    m.calc("vacant_classic", unit="units", dims=CM,
           expr=ref("vacant_classic_open") + ref("move_outs_classic") - from_vacant - ref("releases_classic"))
    m.calc("occupied_classic", unit="units", dims=CM,
           expr=ref("occupied_classic_open") - ref("move_outs_classic") + ref("releases_classic"))
    m.calc("scope_remaining", unit="units", dims=CM, expr=ref("scope_remaining_open") - ref("reno_starts"))

    # --- Renovation downtime: one row per month offline -----------------------------
    stages = [f"in_renovation_{k}" for k in range(1, deal.downtime_months + 1)]
    m.calc(stages[0], unit="units", dims=CM, expr=ref("reno_starts"))
    for before, stage in zip(stages, stages[1:]):
        m.calc(stage, unit="units", dims=CM, expr=lag(before, "month", initial=0))
    m.calc("in_renovation", unit="units", dims=CM, expr=total(*stages))
    m.calc("reno_completions", unit="units", dims=CM, expr=lag(stages[-1], "month", initial=0))

    # --- Unit states: renovated units ----------------------------------------------
    m.calc("occupied_renovated_open", unit="units", dims=CM, expr=lag("occupied_renovated", "month", initial=0))
    m.calc("vacant_renovated_open", unit="units", dims=CM, expr=lag("vacant_renovated", "month", initial=0))
    m.calc("move_outs_renovated", unit="units", dims=CM,
           expr=ref("occupied_renovated_open") * ref("turnover") / 12 * live)
    m.calc("leases_renovated", unit="units", dims=CM, expr=ref("vacant_renovated_open") * live)
    m.calc("vacant_renovated", unit="units", dims=CM,
           expr=(ref("vacant_renovated_open") + ref("reno_completions") + ref("move_outs_renovated")
                 - ref("leases_renovated")))
    m.calc("occupied_renovated", unit="units", dims=CM,
           expr=ref("occupied_renovated_open") - ref("move_outs_renovated") + ref("leases_renovated"))
    m.calc("units_converted", unit="units", dims=CM, expr=_renovating(ref("reno_scope") - ref("scope_remaining")))

    # Units are conserved, to rounding far below a unit.
    drift = (ref("occupied_classic") + ref("vacant_classic") + ref("in_renovation") + ref("vacant_renovated")
             + ref("occupied_renovated") - ref("units"))
    for name, condition in (("units_conserved_low", drift >= const("-1e-9")),
                            ("units_conserved_high", drift <= const("1e-9"))):
        m.check(name, dims=CM, condition=condition, code="UNITS_NOT_CONSERVED",
                message="A cohort's unit states do not sum to its units.")

    # --- Rent per occupied unit --------------------------------------------------------
    # A contract's rent is the contract schedule for every unit under it; other
    # regimes blend renewals (capped) with new leases. A new lease is at the target
    # when in-place rents are marked to market on turnover; otherwise it carries
    # the in-place rent forward, grown like a renewal (the in-place rents hold).
    carried = min_(lag("rent_classic", "month", initial=ref("in_place_rent")) * ref("renewal_factor"),
                   ref("classic_target"))
    new_lease = if_(ref("mark_to_market") > 0, ref("classic_target"), carried)
    blended = if_(ref("occupied_classic") > 0,
                  ((ref("occupied_classic_open") - ref("move_outs_classic")) * carried
                   + ref("releases_classic") * new_lease) / ref("occupied_classic"),
                  ref("classic_target"))
    m.calc("rent_classic", unit="usd/unit-month", dims=CM,
           expr=if_(matches("cohort", regime="contract"), ref("classic_target"), blended))
    m.calc("rent_renovated", unit="usd/unit-month", dims=CM, expr=if_(ref("occupied_renovated") > 0,
                    ((ref("occupied_renovated_open") - ref("move_outs_renovated"))
                     * min_(lag("rent_renovated", "month", initial=0) * ref("renewal_factor"),
                            ref("renovated_target"))
                     + ref("leases_renovated") * ref("renovated_target")) / ref("occupied_renovated"),
                    ref("renovated_target")))

    # --- Revenue bridge by cohort ----------------------------------------------
    m.calc("gpr", unit="usd", dims=CM,
           expr=((ref("units") - ref("units_converted")) * ref("classic_target")
                 + ref("units_converted") * ref("renovated_target")) * live)
    m.calc("loss_to_lease", unit="usd", dims=CM,
           expr=(ref("occupied_classic") * (ref("classic_target") - ref("rent_classic"))
                 + ref("occupied_renovated") * (ref("renovated_target") - ref("rent_renovated"))) * live)
    m.calc("vacancy_loss", unit="usd", dims=CM,
           expr=(ref("vacant_classic") * ref("classic_target")
                 + ref("vacant_renovated") * ref("renovated_target")) * live)
    m.calc("downtime_loss", unit="usd", dims=CM, expr=ref("in_renovation") * ref("renovated_target") * live)
    m.calc("rental_income", unit="usd", dims=CM,
           expr=ref("gpr") - ref("loss_to_lease") - ref("vacancy_loss") - ref("downtime_loss"))

    # --- Property totals -----------------------------------------------------------------
    m.calc("total_units", unit="units", expr=sum_over("cohort", ref("units")))
    m.calc("restricted_units", unit="units", expr=sum_over("cohort", ref("units"), regime="restricted"))
    for name, body in (("gpr_total", "gpr"), ("loss_to_lease_total", "loss_to_lease"),
                       ("vacancy_total", "vacancy_loss"), ("downtime_total", "downtime_loss"),
                       ("rental_income_total", "rental_income")):
        m.calc(name, unit="usd", dims=month, expr=sum_over("cohort", ref(body)))
    m.calc("occupied_units", unit="units", dims=month,
           expr=sum_over("cohort", ref("occupied_classic") + ref("occupied_renovated")))
    m.calc("occupancy", unit="rate", dims=month, expr=ref("occupied_units") / ref("total_units"))
    m.calc("reno_starts_total", unit="units", dims=month, expr=sum_over("cohort", ref("reno_starts")))

    m.test("restricted_rent_within_limit", dims=("cohort",), where={"regime": "restricted"},
           condition=ref("in_place_rent") <= ref("rent_limit_gross") - ref("utility_allowance"),
           code="RENT_ABOVE_LIMIT",
           message="A restricted cohort's in-place rent is above its net limit; it drops to the limit.")
