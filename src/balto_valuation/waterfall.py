"""Acquisition investor terms and net ledger cash, using the shared waterfall."""
from balto_model_engine import Model, attr, ref
from balto_model_engine.waterfall import WaterfallTerms, build_waterfall


def build(m: Model):
    m.input('lp_share', unit='rate', minimum='0.000001', maximum=1)
    m.input('pref_rate', unit='rate/year', minimum=0, maximum=1)
    m.input('hurdle_rate', unit='rate/year', minimum=0, maximum=1)
    m.input('promote_1', unit='rate', minimum=0, maximum='0.99')
    m.input('promote_2', unit='rate', minimum=0, maximum='0.99')
    m.input('catch_up_share', unit='rate', minimum=0, maximum=1)
    return build_waterfall(m, period_dim='month', elapsed_days=attr('month','days'),
        contributions=ref('equity_contributions'), distributions=ref('equity_distributions'),
        terms=WaterfallTerms(*(ref(n) for n in ('lp_share','pref_rate','hurdle_rate','promote_1','promote_2','catch_up_share'))))
