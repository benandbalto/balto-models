"""Invented 120-unit Seattle mid-rise. Costs, rents and values are not a reviewed deal or quote.

Homes average 546 net sq ft (studios 350, one bedrooms 550, two bedrooms
800): 65,500 net sq ft in an 82,000 gross sq ft building at 80% efficiency.
Hard cost is $320 per gross sq ft before GC fee and contingency.

Program terms follow the published 2026 rules: MHA Medium (M1) at $30.81/sq ft
(SDCI, effective 2026-03-01) or a 9% performance set-aside at 60% AMI (40% for
homes of 400 sq ft or less, so the studios); MFTE
Program 7 (Ord. 127316) with a 20% set-aside because 25% of units have two
bedrooms; levy code 0010 at $9.90845 per $1,000 (King County 2026).
Restricted rents are the Office of Housing 2026-27 P7 gross limits (MFTE: studio
60%, one bedroom 75%, two bedroom 90% AMI; MHA: 40% studio, 60% otherwise) less the City's
"tenant pays all utilities" estimate (effective 2025-02-01: $160 / $185 / $285),
since tenants pay electricity and are billed water, sewer and garbage (WSG). The
WSG cost is that estimate less the electricity-and-heat estimate ($110 / $120 /
$200); the owner recovers 80% of it.
"""
from datetime import date
from .deal import DevelopmentDeal,Phase,SpendingPeriod,UnitType

def example_deal():
    return DevelopmentDeal('seattle_development','Synthetic Seattle mid-rise','Seattle, WA',date(2027,1,15),8,
        (Phase('building','Building'),),tuple(SpendingPeriod(f'd{i}','building',f'Draw {i}') for i in range(1,21)),
        (UnitType('studio','Studio'),UnitType('one','One bedroom'),UnitType('two','Two bedroom')))

def example_inputs():
    weights=['0.05']*20
    return dict(land_cost='6000000',closing_cost='250000',hard_cost={'building':'26240000'},
        soft_cost={'building':'5740000'},developer_fee={'building':'1500000'},
        conditions_rate={'building':0},gc_fee_rate={'building':'0.05'},contingency_rate={'building':'0.05'},
        spending_weight={f'd{i}':v for i,v in enumerate(weights,1)},spending_month={f'd{i}':i for i in range(1,21)},
        completion_month=20,occupancy_month=20,stabilization_month=32,conversion_month=36,construction_maturity_month=36,sale_month=84,
        units={'studio':40,'one':50,'two':30},bedrooms={'studio':0,'one':1,'two':2},
        market_rent={'studio':'1935','one':'2565','two':'3510'},
        rent_limit={'studio':'100000','one':'100000','two':'100000'},lease_pace={'studio':4,'one':5,'two':3},
        stabilized_vacancy='0.05',rent_growth='0.03',opex_growth='0.03',annual_opex='643200',management_fee='0.03',
        construction_commitment='38000000',construction_share='0.60',land_eligible=1,
        construction_rate={f'm{i}':'0.075' for i in range(97)},capitalize_interest=1,construction_fee_rate='0.01',
        permanent_rate='0.06',permanent_amort_years=30,permanent_io_months=0,permanent_ltv='0.65',
        permanent_dscr='1.25',permanent_cap_rate='0.05',permanent_fee_rate='0.01',
        exit_cap_rate='0.05',sale_cost_rate='0.02',equity_commitment='33000000',working_capital='500000',
        lp_share='0.90',pref_rate='0.08',hurdle_rate='0.12',promote_1='0.20',promote_2='0.30',catch_up_share=1,
        affordable_rent_growth='0.035',
        mha_applies=1,mha_performance=0,mha_payment_rate='30.81',mha_chargeable_area='82000',
        mha_performance_rate='0.09',mha_payment_month=1,mha_monitoring_fee='200',mha_compliance_cost='150',
        mha_units={'studio':4,'one':4,'two':2},mha_rent={'studio':'991','one':'1665','two':'1935'},
        mfte_elected=1,mfte_start_month=24,mfte_compliance_cost='150',mfte_exit_discount_rate='0.07',
        mfte_units={'studio':8,'one':10,'two':6},mfte_rent={'studio':'1566','one':'2127','two':'3045'},
        wsg_cost={'studio':'110','one':'120','two':'200'},wsg_recovery_rate='0.80',
        levy_rate='0.00990845',land_assessed_value='6000000',improvement_assessed_value='32800000',
        residential_improvement_share=1,assessed_value_growth='0.03',improvement_tax_month=24)

def scenario_inputs(*,mfte,mha):
    """Toggle MFTE participation and the MHA path ('payment', 'performance' or 'none')."""
    return {**example_inputs(),'mfte_elected':1 if mfte else 0,
            'mha_applies':0 if mha=='none' else 1,'mha_performance':1 if mha=='performance' else 0}
