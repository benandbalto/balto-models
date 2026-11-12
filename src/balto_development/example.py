"""Invented 40-unit project. These assumptions are not a reviewed deal or quote."""
from datetime import date
from .deal import DevelopmentDeal,Phase,SpendingPeriod,UnitType

def example_deal():
    return DevelopmentDeal('development','Synthetic development','Testville, WA',date(2027,1,15),5,
        (Phase('building','Building'),),tuple(SpendingPeriod(f'd{i}','building',f'Draw {i}') for i in range(1,13)),
        (UnitType('one','One bedroom'),))

def example_inputs():
    weights=['0.05','0.05','0.075','0.075','0.10','0.15','0.15','0.10','0.075','0.075','0.05','0.05']
    return dict(land_cost='2000000',closing_cost='100000',hard_cost={'building':'8000000'},
        soft_cost={'building':'1500000'},developer_fee={'building':'260000'},
        conditions_rate={'building':0},gc_fee_rate={'building':'0.10'},contingency_rate={'building':'0.10'},
        spending_weight={f'd{i}':v for i,v in enumerate(weights,1)},spending_month={f'd{i}':i for i in range(1,13)},
        completion_month=12,occupancy_month=12,stabilization_month=20,conversion_month=24,construction_maturity_month=24,sale_month=48,
        units={'one':40},market_rent={'one':'3000'},rent_limit={'one':'10000'},lease_pace={'one':5},
        stabilized_vacancy='0.05',rent_growth='0.025',opex_growth='0.025',annual_opex='350000',management_fee='0.03',
        construction_commitment='9500000',construction_share='0.65',land_eligible=1,
        construction_rate={f'm{i}':'0.08' for i in range(61)},capitalize_interest=1,construction_fee_rate='0.01',
        permanent_rate='0.06',permanent_amort_years=30,permanent_io_months=0,permanent_ltv='0.65',
        permanent_dscr='1.25',permanent_cap_rate='0.055',permanent_fee_rate='0.01',
        exit_cap_rate='0.06',sale_cost_rate='0.02',equity_commitment='10000000',working_capital='150000',
        lp_share='0.90',pref_rate='0.08',hurdle_rate='0.12',promote_1='0.20',promote_2='0.30',catch_up_share=1)

def downside_inputs():
    inputs=example_inputs()
    return {**inputs,'hard_cost':{'building':'10000000'},'spending_month':{f'd{i}':i+6 for i in range(1,13)},
        'completion_month':18,'occupancy_month':18,'stabilization_month':26,'conversion_month':30,
        'equity_commitment':'4000000'}
