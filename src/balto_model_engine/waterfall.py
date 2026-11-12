"""Conventional LP/GP capital, compounded ACT/365 pref, catch-up and promote.

Inputs are nonnegative net cash after sponsor fees and property funding policy.
Contributions enter after accrual; distributions pay pref/capital pro rata,
then GP catch-up, second LP hurdle and residual promote. This is one explicit
policy, not arbitrary tiers.
"""
from dataclasses import dataclass, field
from typing import Literal
from . import Model, if_, lag, max_, min_, power, ref
from .expressions import Expr


@dataclass(frozen=True)
class WaterfallTerms:
    lp_share: Expr
    pref_rate: Expr
    hurdle_rate: Expr
    promote_1: Expr
    promote_2: Expr
    catch_up_share: Expr


@dataclass(frozen=True)
class InvestorWaterfall:
    period_dim: str
    lp_contribution: Expr
    gp_contribution: Expr
    lp_distribution: Expr
    gp_distribution: Expr
    lp_cash_flow: Expr
    gp_cash_flow: Expr
    gp_promote: Expr
    pref_balance: Expr
    hurdle_balance: Expr
    tier_1: Expr
    tier_catch_up: Expr
    tier_2: Expr
    tier_3: Expr
    currency: Literal['USD'] = field(default='USD', init=False)


def build_waterfall(m: Model, *, period_dim: str, elapsed_days: Expr,
                    contributions: Expr, distributions: Expr,
                    terms: WaterfallTerms) -> InvestorWaterfall:
    """Declare live formulas over caller-owned ordered dates and cash flows.

    elapsed_days is the actual difference from the preceding cash-flow date,
    zero at the first event. Rates are annual effective, compounded ACT/365.
    The component validates cash, elapsed days, and conventional terms:
    0 < LP share <= 1, pref/hurdle in [0,1], 0 <= promote < 1, catch-up in [0,1].
    A catch-up share insufficient to reach the promote target skips catch-up,
    preserving the conventional acquisition policy. Fees are already in uses.
    XIRR is declared by the caller on the returned dated investor cash flows.
    """
    dims = (period_dim,)
    for name, expression, lower, upper, strict_lower, strict_upper in (
        ('lp_share', terms.lp_share, 0, 1, True, False),
        ('pref_rate', terms.pref_rate, 0, 1, False, False),
        ('hurdle_rate', terms.hurdle_rate, 0, 1, False, False),
        ('promote_1', terms.promote_1, 0, 1, False, True),
        ('promote_2', terms.promote_2, 0, 1, False, True),
        ('catch_up_share', terms.catch_up_share, 0, 1, False, False),
    ):
        m.check('wf.'+name+'.minimum', condition=expression > lower if strict_lower else expression >= lower,
                code='WATERFALL_TERMS', message=name+' is below the permitted range.')
        m.check('wf.'+name+'.maximum', condition=expression < upper if strict_upper else expression <= upper,
                code='WATERFALL_TERMS', message=name+' is above the permitted range.')
    m.check('wf.days', dims=dims, condition=elapsed_days >= 0,
            code='WATERFALL_DAYS', message='Investor events must be in chronological order.')
    for name, cash in (('contributions', contributions), ('distributions', distributions)):
        m.check('wf.'+name+'.nonnegative', dims=dims, condition=cash >= 0,
                code='WATERFALL_CASH', message='Waterfall '+name+' must be nonnegative net cash.')
    lp, dist = terms.lp_share, distributions
    split_2 = (1 - terms.promote_1) * lp
    split_3 = (1 - terms.promote_2) * lp
    years = elapsed_days / 365

    m.calc("lp_contribution", unit="usd", dims=dims, expr=contributions * lp)
    m.calc("gp_contribution", unit="usd", dims=dims, expr=contributions - ref("lp_contribution"))

    # Tier 1: pref account.
    m.calc("pref.accrual", unit="rate", dims=dims, expr=power(1 + terms.pref_rate, years) - 1)
    m.calc("pref.opening", unit="usd", dims=dims,
           expr=lag("pref.balance", period_dim, initial=0) * (1 + ref("pref.accrual")) + ref("lp_contribution"))
    m.calc("tier_1", unit="usd", dims=dims, expr=min_(dist, ref("pref.opening") / lp))
    m.calc("pref.balance", unit="usd", dims=dims, expr=ref("pref.opening") - lp * ref("tier_1"))

    # Catch-up: the GP's promote so far against `promote_1` of profit so far.
    k = terms.catch_up_share
    m.calc("wf.contributions_to_date", unit="usd", dims=dims,
           expr=lag("wf.contributions_to_date", period_dim, initial=0) + contributions)
    m.calc("wf.distributions_before", unit="usd", dims=dims,
           expr=lag("wf.distributions_to_date", period_dim, initial=0))
    m.calc("wf.distributions_to_date", unit="usd", dims=dims, expr=ref("wf.distributions_before") + dist)
    m.calc("wf.promote_before", unit="usd", dims=dims, expr=lag("wf.promote_to_date", period_dim, initial=0))
    m.calc("wf.profit_after_tier_1", unit="usd", dims=dims,
           expr=max_(ref("wf.distributions_before") + ref("tier_1") - ref("wf.contributions_to_date"), 0))
    m.calc("wf.catch_up_owed", unit="usd", dims=dims,
           expr=max_(terms.promote_1 * ref("wf.profit_after_tier_1") - ref("wf.promote_before"), 0))
    # Each catch-up dollar adds (share − GP share) to the promote and one to profit.
    gain = k - (1 - lp) - terms.promote_1
    m.calc("tier_catch_up", unit="usd", dims=dims,
           expr=if_(gain > 0, min_(dist - ref("tier_1"), ref("wf.catch_up_owed") / gain), 0))

    # Tier 2: hurdle account, reduced by the LP's tier-1 and catch-up receipts.
    m.calc("hurdle.accrual", unit="rate", dims=dims, expr=power(1 + terms.hurdle_rate, years) - 1)
    m.calc("hurdle.opening", unit="usd", dims=dims,
           expr=lag("hurdle.balance", period_dim, initial=0) * (1 + ref("hurdle.accrual")) + ref("lp_contribution")
           - lp * ref("tier_1") - (1 - k) * ref("tier_catch_up"))
    m.calc("tier_2", unit="usd", dims=dims,
           expr=min_(dist - ref("tier_1") - ref("tier_catch_up"), max_(ref("hurdle.opening"), 0) / split_2))
    m.calc("hurdle.balance", unit="usd", dims=dims,
           expr=max_(ref("hurdle.opening") - split_2 * ref("tier_2"), 0))

    # Tier 3: residual.
    m.calc("tier_3", unit="usd", dims=dims, expr=dist - ref("tier_1") - ref("tier_catch_up") - ref("tier_2"))

    m.calc("lp_distribution", unit="usd", dims=dims,
           expr=lp * ref("tier_1") + (1 - k) * ref("tier_catch_up") + split_2 * ref("tier_2")
           + split_3 * ref("tier_3"))
    m.calc("gp_distribution", unit="usd", dims=dims, expr=dist - ref("lp_distribution"))
    m.calc("gp_promote", unit="usd", dims=dims, expr=ref("gp_distribution") - (1 - lp) * dist)
    m.calc("wf.promote_to_date", unit="usd", dims=dims, expr=ref("wf.promote_before") + ref("gp_promote"))
    m.calc("lp_cash_flow", unit="usd", dims=dims, expr=ref("lp_distribution") - ref("lp_contribution"))
    m.calc("gp_cash_flow", unit="usd", dims=dims, expr=ref("gp_distribution") - ref("gp_contribution"))

    def reconciles(name, left, right):
        m.check('wf.'+name, dims=dims, condition=max_(left-right, right-left) <= '0.000001',
                code='WATERFALL_RECONCILIATION', message='Investor '+name+' does not reconcile.')
    reconciles('contributions', ref('lp_contribution')+ref('gp_contribution'), contributions)
    reconciles('distributions', ref('lp_distribution')+ref('gp_distribution'), distributions)
    reconciles('tiers', ref('tier_1')+ref('tier_catch_up')+ref('tier_2')+ref('tier_3'), distributions)
    reconciles('cash_flows', ref('lp_cash_flow')+ref('gp_cash_flow'), distributions-contributions)
    reconciles('pref_balance', ref('pref.balance'), ref('pref.opening')-terms.lp_share*ref('tier_1'))
    reconciles('hurdle_balance', ref('hurdle.balance'), max_(ref('hurdle.opening')-(1-terms.promote_1)*terms.lp_share*ref('tier_2'),0))

    return InvestorWaterfall(period_dim, ref("lp_contribution"), ref("gp_contribution"), ref("lp_distribution"), ref("gp_distribution"), ref("lp_cash_flow"), ref("gp_cash_flow"), ref("gp_promote"), ref("pref.balance"), ref("hurdle.balance"), ref("tier_1"), ref("tier_catch_up"), ref("tier_2"), ref("tier_3"))
