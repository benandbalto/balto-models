"""Explicit-event development, capped end-period construction draws and lease-up.

Construction interest uses ACT/365F on opening debt; new draws are at period end.
All project costs are eligible except closing, financing fees and working capital;
land eligibility is explicit. Equity funds the residual, capped by its commitment.
Returns use required equity (fully funded case); funding gaps remain failed
*economic* outcomes rather than suppressing the run or assuming free money.
"""
from balto_model_engine import (Model,DecimalPolicy,Dimension,Item,attr,ref,if_,lag,min_,max_,
    power,round_to,sum_over,monthly_calendar,const)
from balto_model_engine.capital import build_capital_budget,build_weighted_spending
from balto_model_engine.debt import build_draw_debt,build_payment_terms,build_loan_sizing,build_debt_schedule
from balto_model_engine.funding import build_reserve,build_funding
from balto_model_engine.rents import rent_target
from balto_model_engine.waterfall import WaterfallTerms,build_waterfall
from balto_model_engine.operating import build_operating_projection
from .deal import DevelopmentDeal
MODEL_ID='multifamily-development'
MODEL_VERSION='0.2.0'

class Assembly:
    """Shared development references handed from one assembly stage to the next."""
    def __init__(self,**values):self.__dict__.update(values)

def build_model(deal:DevelopmentDeal):
    m,a=start_development(deal,MODEL_ID,MODEL_VERSION)
    a.noi,a.stabilized_noi=build_market_operations(m,a)
    finish_development(m,a)
    return m

def start_development(deal:DevelopmentDeal,model_id,model_version,extra_cost=None):
    """Calendar, events, unit, budget and spending inputs through scheduled project spending.

    `extra_cost(m, idx)` may return (project-level cost, monthly spending) outside the phase budget."""
    import calendar
    m=Model(model_id,model_version,DecimalPolicy(34,'ROUND_HALF_UP'))
    cal=monthly_calendar(deal.closing,deal.horizon_years*12)
    m.dimension(Dimension('month',[Item(f'm{i.key}',label='Closing' if i.key==0 else f'M{i.key}',
        calendar_days=calendar.monthrange(i.attrs['calendar_year'],i.attrs['month_of_year'])[1],**i.attrs) for i in cal.items]))
    m.dimension(Dimension('phase',[Item(p.key,label=p.label) for p in deal.phases]))
    m.dimension(Dimension('spend',[Item(p.key,phase=p.phase,label=p.label) for p in deal.spending_periods],parent='phase'))
    m.dimension(Dimension('unit_type',[Item(u.key,label=u.label) for u in deal.unit_types]))
    last=deal.horizon_years*12
    idx=attr('month','index');mo=('month',);ut=('unit_type',);ph=('phase',)
    def inp(name,unit='usd',dims=(),lo=0,hi=None):m.input(name,unit=unit,dims=dims,minimum=lo,maximum=hi)
    def calc(name,expr,unit='usd',dims=()):m.calc(name,unit=unit,dims=dims,expr=expr);return ref(name)
    def whole(name,dims=()):m.check(name+'.whole',dims=dims,condition=ref(name)==round_to(ref(name),0),code='EVENT_NOT_WHOLE',message=name+' must be whole.')
    for name in ('land_cost','closing_cost','annual_opex','construction_commitment','equity_commitment','working_capital'):inp(name)
    for name in ('hard_cost','soft_cost','developer_fee'):inp(name,dims=ph)
    for name in ('conditions_rate','gc_fee_rate','contingency_rate'):inp(name,'rate',ph,0,1)
    inp('spending_weight','rate',('spend',),0,1);inp('spending_month','month',('spend',),1,last-12);whole('spending_month',('spend',))
    for name in ('completion_month','occupancy_month','stabilization_month','conversion_month','sale_month','construction_maturity_month'):
        inp(name,'month',(),1,last-12);whole(name)
    for earlier,later in (('completion_month','occupancy_month'),('occupancy_month','stabilization_month')):
        m.check(earlier+'.order',condition=ref(earlier)<=ref(later),code='EVENT_ORDER',message=earlier+' must precede '+later+'.')
    for earlier,later in (('stabilization_month','conversion_month'),('conversion_month','sale_month')):
        m.check(earlier+'.order',condition=ref(earlier)<ref(later),code='EVENT_ORDER',message=earlier+' must precede '+later+'.')
    m.check('spend_before_completion',dims=('spend',),condition=ref('spending_month')<=ref('completion_month'),code='SPEND_AFTER_COMPLETION',message='All scheduled project spending must be covered by completion.')
    for name in ('units','market_rent','rent_limit','lease_pace'):inp(name,'units' if name in ('units','lease_pace') else 'usd/unit-month',ut)
    whole('units',ut)
    for name in ('stabilized_vacancy','management_fee','construction_share','construction_fee_rate','permanent_ltv','permanent_fee_rate','sale_cost_rate'):inp(name,'rate',(),0,1)
    for name in ('rent_growth','opex_growth'):inp(name,'rate',(),-.2,.5)
    inp('construction_rate','rate',mo,0,1)
    for name in ('land_eligible','capitalize_interest'):inp(name,'flag',(),0,1);whole(name)
    inp('permanent_rate','rate',(),0,1);inp('permanent_amort_years','years',(),1,50)
    inp('permanent_io_months','month',(),0,last);whole('permanent_io_months')
    inp('permanent_dscr','ratio',(),1,5)
    for name in ('permanent_cap_rate','exit_cap_rate'):inp(name,'rate',(),'.001',1)
    owned=calc('owned',if_(idx<=ref('sale_month'),1,0),'flag',mo)
    sale=calc('is_sale',if_(idx==ref('sale_month'),1,0),'flag',mo)
    convert=calc('is_conversion',if_(idx==ref('conversion_month'),1,0),'flag',mo)
    period_fraction=calc('period_fraction',attr('month','days')/attr('month','calendar_days'),'rate',mo)
    capital=build_capital_budget(m,phase_dim='phase',hard_costs=ref('hard_cost'),general_conditions_rate=ref('conditions_rate'),
        gc_fee_rate=ref('gc_fee_rate'),contingency_rate=ref('contingency_rate'),hard_name='budget.hard',
        general_conditions_name='budget.conditions',gc_fee_name='budget.gc_fee',contingency_name='budget.contingency',total_name='budget.construction')
    budget=calc('budget.total',capital.total+ref('soft_cost')+ref('developer_fee'),dims=ph)
    extra=extra_cost(m,idx) if extra_cost else None
    budgeted=ref('land_cost')+sum_over('phase',budget)
    project=calc('project_cost',budgeted+extra[0] if extra else budgeted)
    spend=build_weighted_spending(m,phase_dim='phase',period_dim='spend',budget=budget,weight=ref('spending_weight'),name='scheduled_spending')
    scheduled=sum_over('spend',if_(ref('spending_month')==idx,spend.amount,0))+if_(idx==0,ref('land_cost'),0)
    monthly_spend=calc('project_spending',scheduled+extra[1] if extra else scheduled,dims=mo)
    calc('total_project_spending',sum_over('month',monthly_spend))
    return m,Assembly(deal=deal,last=last,idx=idx,mo=mo,ut=ut,inp=inp,calc=calc,owned=owned,sale=sale,convert=convert,
        period_fraction=period_fraction,project=project,monthly_spend=monthly_spend)

def build_market_operations(m,a):
    """Market lease-up under an explicit net rent ceiling and one blended operating expense."""
    idx,mo,ut,calc,period_fraction=a.idx,a.mo,a.ut,a.calc,a.period_fraction
    delivered,occupied,target=build_lease_up(m,a)
    base_rent=calc('rent.target',rent_target(ref('market_rent')*power(1+ref('rent_growth'),idx/12),net_ceiling=ref('rent_limit')),'usd/unit-month',ut+mo)
    rents=calc('rental_income',sum_over('unit_type',occupied*base_rent)*period_fraction,dims=mo)
    operating=if_(idx>=ref('occupancy_month'),1,0)
    expense=calc('operating_expense',operating*ref('annual_opex')/12*power(1+ref('opex_growth'),idx/12)*period_fraction+rents*ref('management_fee'),dims=mo)
    projection=build_operating_projection(m,period_dim='month',units=ref('delivered_units'),income_lines=(rents,),expense_lines=(expense,),income=rents,expenses=expense,noi_name='noi')
    noi=projection.noi
    stabilized_rent=sum_over('unit_type',target*rent_target(ref('market_rent')*power(1+ref('rent_growth'),ref('stabilization_month')/12),net_ceiling=ref('rent_limit')))*12
    stabilized_noi=calc('stabilized_noi',stabilized_rent*(1-ref('management_fee'))-ref('annual_opex')*power(1+ref('opex_growth'),ref('stabilization_month')/12))
    return noi,stabilized_noi

def build_lease_up(m,a):
    """Single delivery at completion and lease-up from first occupancy at an explicit pace."""
    idx,mo,ut,calc=a.idx,a.mo,a.ut,a.calc
    delivered=calc('units.delivered',if_(idx>=ref('completion_month'),ref('units'),0),'units',ut+mo)
    target=calc('units.target_occupied',ref('units')*(1-ref('stabilized_vacancy')),'units',ut)
    occupied=calc('units.occupied',if_(idx>=ref('occupancy_month'),min_(target,lag('units.occupied','month',initial=0)+ref('lease_pace')),0),'units',ut+mo)
    calc('total_units',sum_over('unit_type',ref('units')),'units')
    calc('delivered_units',sum_over('unit_type',delivered),'units',mo)
    calc('occupied_units',sum_over('unit_type',occupied),'units',mo)
    return delivered,occupied,target

def finish_development(m,a,gross_sale_value=None):
    """Construction and permanent debt, sale, reserve, funding, investor waterfall and checks.

    `gross_sale_value(m, a)` may replace the forward-twelve-month NOI capitalization."""
    idx,mo,ut,last,inp,calc=a.idx,a.mo,a.ut,a.last,a.inp,a.calc
    owned,sale,convert,monthly_spend,project,noi,stabilized_noi=a.owned,a.sale,a.convert,a.monthly_spend,a.project,a.noi,a.stabilized_noi
    eligible=calc('eligible_spending',monthly_spend-if_(idx==0,ref('land_cost')*(1-ref('land_eligible')),0),dims=mo)
    construction=build_draw_debt(m,prefix='construction',period_dim='month',eligible_spending=eligible,
        debt_share=ref('construction_share'),commitment=ref('construction_commitment'),annual_rate=ref('construction_rate'),
        year_fraction=attr('month','days')/365,capitalize=if_(idx<ref('conversion_month'),ref('capitalize_interest'),0),
        draw_allowed=if_(idx<ref('conversion_month'),if_(idx<=ref('construction_maturity_month'),1,0),0),payoff=convert)
    terms=build_payment_terms(m,prefix='permanent',annual_rate=ref('permanent_rate'),amort_years=ref('permanent_amort_years'))
    size=build_loan_sizing(m,prefix='permanent_size',income=stabilized_noi,value=stabilized_noi/ref('permanent_cap_rate'),max_ltv=ref('permanent_ltv'),min_dscr=ref('permanent_dscr'),payment_constant=terms.payment_constant)
    permanent=build_debt_schedule(m,prefix='permanent',period_dim='month',period_index=idx,amount=size.amount,terms=terms,fund_period=ref('conversion_month'),payoff_period=ref('sale_month'),io_periods=ref('permanent_io_months'),fee_rate=ref('permanent_fee_rate'))
    if gross_sale_value is None:
        f12=calc('sale_forward_noi',sum_over('month',if_(idx>ref('sale_month'),if_(idx<=ref('sale_month')+12,noi,0),0)))
        proceeds=calc('sale_proceeds',sale*max_(f12,0)/ref('exit_cap_rate')*(1-ref('sale_cost_rate')),dims=mo)
    else:
        proceeds=calc('sale_proceeds',sale*max_(gross_sale_value(m,a),0)*(1-ref('sale_cost_rate')),dims=mo)
    cash_income=calc('operating_cash',owned*noi,dims=mo)
    reserve=build_reserve(m,prefix='operating_reserve',period_dim='month',deposits=if_(idx==0,ref('working_capital'),0),eligible_spending=max_(-cash_income+permanent.debt_service+construction.cash_interest,0),release=sale*(ref('operating_reserve.available')-ref('operating_reserve.draw')))
    sources=calc('sources',max_(cash_income,0)+construction.funding+permanent.funding+proceeds+reserve.draw+reserve.released,dims=mo)
    uses=calc('uses',monthly_spend+max_(-cash_income,0)+construction.cash_interest+construction.payoff+permanent.debt_service+permanent.payoff+reserve.deposits+if_(idx==0,ref('closing_cost')+ref('construction_commitment')*ref('construction_fee_rate'),0)+convert*permanent.fee,dims=mo)
    funding=build_funding(m,period_dim='month',sources=sources,uses=uses,transfers_in=const(0),transfers_out=const(0),external_funding=const(0),cash_name='cash_before_equity',contribution_name='equity_required',distribution_name='distribution',unmet_name='funding_required')
    prior=lag('equity_used','month',initial=0)
    equity=calc('equity_funded',min_(funding.contribution,max_(ref('equity_commitment')-prior,0)),dims=mo)
    calc('equity_used',prior+equity,dims=mo)
    gap=calc('funding_gap',funding.contribution-equity,dims=mo)
    flow=calc('investor_flow',funding.distribution-funding.contribution,dims=mo)
    # Caller-owned conventional LP/GP terms; fees are already explicit project uses.
    for name,unit,lo,hi in (('lp_share','rate','0.000001',1),
            ('pref_rate','rate/year',0,1),('hurdle_rate','rate/year',0,1),
            ('promote_1','rate',0,'0.99'),('promote_2','rate',0,'0.99'),('catch_up_share','rate',0,1)):
        inp(name,unit,(),lo,hi)
    investors=build_waterfall(m,period_dim='month',elapsed_days=attr('month','days'),
        contributions=funding.contribution,distributions=funding.distribution,
        terms=WaterfallTerms(*(ref(n) for n in ('lp_share','pref_rate','hurdle_rate','promote_1','promote_2','catch_up_share'))))
    calc('total_lp_distributions',sum_over('month',investors.lp_distribution))
    calc('total_gp_distributions',sum_over('month',investors.gp_distribution))
    calc('total_gp_promote',sum_over('month',investors.gp_promote))
    m.xirr('lp_irr',flows='lp_cash_flow',dim='month',date_attr='date')
    m.xirr('gp_irr',flows='gp_cash_flow',dim='month',date_attr='date')
    cumulative=calc('cumulative_investor_flow',lag('cumulative_investor_flow','month',initial=0)+flow,dims=mo)
    # Max over periods via a running maximum; the terminal value is the peak.
    calc('peak_equity_to_date',max_(lag('peak_equity_to_date','month',initial=0),-cumulative),dims=mo)
    calc('peak_equity',sum_over('month',if_(idx==last,ref('peak_equity_to_date'),0)))
    calc('total_equity_required',sum_over('month',funding.contribution));calc('total_distributions',sum_over('month',funding.distribution))
    calc('total_interest',sum_over('month',construction.interest+permanent.interest))
    calc('total_funding_gap',sum_over('month',gap))
    m.xirr('levered_irr',flows='investor_flow',dim='month',date_attr='date')
    tol='0.000001'
    def reconciles(name,left,right,dims=()):m.check(name,dims=dims,condition=max_(left-right,right-left)<=tol,code='RECONCILIATION',message=name+' does not reconcile.')
    reconciles('project_budget',ref('total_project_spending'),project)
    reconciles('loan_bridge',construction.opening+construction.funding+construction.capitalized_interest-construction.payoff,construction.balance,mo)
    reconciles('permanent_bridge',permanent.opening+permanent.funding-permanent.principal-permanent.payoff,permanent.balance,mo)
    reconciles('reserve_bridge',reserve.opening+reserve.deposits-reserve.draw-reserve.released,reserve.balance,mo)
    m.check('unit_inventory',dims=ut+mo,condition=ref('units.occupied')<=ref('units.delivered'),code='UNIT_INVENTORY',message='Occupied units exceed delivered units.')
    reconciles('sources_uses',sources+equity+gap,uses+funding.distribution,mo)
    m.test('construction_maturity',condition=ref('conversion_month')<=ref('construction_maturity_month'),code='MATURITY_BREACH',message='Conversion occurs after construction maturity; an extension is required.')
    m.test('funded',dims=mo,condition=gap<=tol,code='FUNDING_GAP',message='Committed equity does not cover required funding; returns assume the required capital is supplied.')
    m.test('construction_capacity',dims=mo,condition=construction.unfunded<=tol,code='DRAW_SHORTFALL',message='Construction commitment does not cover requested eligible draws.')
    m.test('stabilized',condition=sum_over('month',if_(idx==ref('stabilization_month'),ref('occupied_units'),0))>=sum_over('unit_type',ref('units.target_occupied'))-tol,code='LEASE_UP_SHORTFALL',message='Lease-up does not reach target by the stated stabilization month.')
