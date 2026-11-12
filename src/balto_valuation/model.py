"""The value-add acquisition model, assembled from its components."""

from __future__ import annotations

from balto_model_engine import DecimalPolicy, Model

from . import capital, ledger, operations, proforma, rents, reporting, timeline, waterfall
from .deal import Deal

MODEL_ID = "value-add-acquisition"
MODEL_VERSION = "0.5.0"
# Excel's ROUND rounds half away from zero; the model uses the same rule.
POLICY = DecimalPolicy(precision=34, rounding="ROUND_HALF_UP")


def build_model(deal: Deal) -> Model:
    m = Model(MODEL_ID, MODEL_VERSION, POLICY)
    timeline.build(m, deal)
    rents.build(m, deal)
    operating_cash = operations.build(m, deal)
    commercial = operations.commercial_income(deal)
    capital_reserve = capital.build_budget(m, deal)
    senior = capital.build_senior(m, deal, operating_cash)
    refi = capital.build_refi(m, deal, operating_cash)
    for t in deal.tranches:
        capital.build_tranche(m, t)
    ledger.build(m, deal, operating_cash, commercial=commercial, senior=senior, refi=refi, capital_reserve=capital_reserve)
    waterfall.build(m)
    reporting.build(m, deal)
    proforma.build(m, deal, commercial=commercial)
    return m
