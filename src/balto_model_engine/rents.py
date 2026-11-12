"""Rent target policy shared by acquisition and development assemblies."""
from .expressions import Expr,min_

def rent_target(market:Expr, *, net_ceiling:Expr|None=None)->Expr:
    """Market target, bounded by a caller-supplied net rent ceiling when applicable.

    Callers own market growth, utility allowances, affordability program terms,
    contract/renewal policy and bounds. The ceiling applies after market growth.
    """
    return market if net_ceiling is None else min_(net_ceiling,market)
