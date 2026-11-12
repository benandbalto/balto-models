"""Seattle multifamily development with MFTE and MHA participation as explicit toggles.

Builds on the shared development stages (budget, lease-up, construction and
permanent debt, sale, funding and investor waterfall) and adds Seattle's
programs and property tax:

- MHA-R (SMC 23.58C). When it applies, the owner either pays the fee in lieu
  (rate per sq ft x chargeable gross floor area, due before the first
  structural building permit) or performs: restricted units at least the
  set-aside rate x total units, with any fractional unit paid as
  full payment x shortfall / required units. Performance units carry a 75-year
  covenant, so they stay restricted through sale.
- MFTE Program 7 (SMC 5.73). Electing restricts the stated units from first
  occupancy and exempts the residential share of improvement value from
  property tax for 12 years from the stated start month. The set-aside is 20%
  when at least 12% of units have two or more bedrooms or 3% have three or
  more, otherwise 25%. Restriction ends with the exemption.
- MHA and MFTE units are always different units (SMC 23.58C.050.C.5).

Restricted rents are caller-supplied net monthly rents (published gross limit
less the City's utility estimate and mandatory fees), growing at the affordable rent
growth rate and never above the market rent. Restricted and market units lease
up in proportion. The owner pays water, sewer and garbage (WSG) for every
occupied home at `wsg_cost` and bills back `wsg_recovery_rate` of it.
`annual_opex` excludes WSG and property tax, which is modeled here:
land is taxed in every owned month, improvements from the stated month.

At sale, a buyer capitalizes forward NOI as if MFTE had ended (market rents on
MFTE units and full tax) and adds the present value of the remaining MFTE net
benefit (tax saved less rent given up), so a temporary exemption is not
capitalized in perpetuity. Program compliance shortfalls are economic tests.
"""
from balto_model_engine import attr, if_, max_, min_, power, ref, round_to, sum_over
from balto_model_engine.operating import build_operating_projection
from balto_model_engine.rents import rent_target
from .deal import DevelopmentDeal
from .model import build_lease_up, finish_development, start_development

MODEL_ID = 'seattle-multifamily-development'
MODEL_VERSION = '0.1.0'
MFTE_TERM_MONTHS = 144


def build_model(deal: DevelopmentDeal):
    m, a = start_development(deal, MODEL_ID, MODEL_VERSION, extra_cost=_mha_payment)
    a.noi, a.stabilized_noi = _operations(m, a)
    finish_development(m, a, gross_sale_value=_sale_value)
    _compliance(m, a)
    _policy(m, a)
    return m


def _flag(m, name):
    m.input(name, unit='flag', minimum=0, maximum=1)
    m.check(name + '.whole', condition=ref(name) == round_to(ref(name), 0), code='EVENT_NOT_WHOLE', message=name + ' must be whole.')


def _mha_payment(m, idx):
    _flag(m, 'mha_applies')
    _flag(m, 'mha_performance')
    for name, unit in (('mha_payment_rate', 'usd/sqft'), ('mha_chargeable_area', 'sqft')):
        m.input(name, unit=unit, minimum=0)
    m.input('mha_performance_rate', unit='rate', minimum=0, maximum=1)
    m.input('mha_payment_month', unit='month', minimum=0)
    m.check('mha_payment_month.whole', condition=ref('mha_payment_month') == round_to(ref('mha_payment_month'), 0),
            code='EVENT_NOT_WHOLE', message='mha_payment_month must be whole.')
    m.check('mha_payment_month.order', condition=ref('mha_payment_month') <= ref('completion_month'),
            code='EVENT_ORDER', message='The MHA payment is due before the structural building permit, so before completion.')
    m.input('mha_units', unit='units', dims=('unit_type',), minimum=0)
    m.check('mha_units.whole', dims=('unit_type',), condition=ref('mha_units') == round_to(ref('mha_units'), 0),
            code='EVENT_NOT_WHOLE', message='mha_units must be whole.')
    full = ref('mha_payment_rate') * ref('mha_chargeable_area')
    m.calc('mha.full_payment', unit='usd', expr=full)
    performing = ref('mha_applies') * ref('mha_performance')
    m.calc('mha.units', unit='units', dims=('unit_type',), expr=performing * ref('mha_units'))
    m.calc('mha.required_units', unit='units', expr=sum_over('unit_type', ref('units')) * ref('mha_performance_rate'))
    required, provided = ref('mha.required_units'), sum_over('unit_type', ref('mha_units'))
    fraction = if_(provided < required, ref('mha.full_payment') * (required - provided) / required, 0)
    m.calc('mha.fraction_payment', unit='usd', expr=fraction)
    m.calc('mha.payment', unit='usd', expr=ref('mha_applies') * if_(ref('mha_performance') == 1, ref('mha.fraction_payment'), ref('mha.full_payment')))
    m.calc('mha.monthly_payment', unit='usd', dims=('month',), expr=if_(idx == ref('mha_payment_month'), ref('mha.payment'), 0))
    return ref('mha.payment'), ref('mha.monthly_payment')


def _operations(m, a):
    idx, mo, ut, calc, pf = a.idx, a.mo, a.ut, a.calc, a.period_fraction
    _flag(m, 'mfte_elected')
    m.input('mfte_units', unit='units', dims=ut, minimum=0)
    m.check('mfte_units.whole', dims=ut, condition=ref('mfte_units') == round_to(ref('mfte_units'), 0),
            code='EVENT_NOT_WHOLE', message='mfte_units must be whole.')
    m.input('bedrooms', unit='bedrooms', dims=ut, minimum=0, maximum=6)
    m.check('bedrooms.whole', dims=ut, condition=ref('bedrooms') == round_to(ref('bedrooms'), 0),
            code='EVENT_NOT_WHOLE', message='bedrooms must be whole.')
    for name in ('mfte_rent', 'mha_rent'):
        m.input(name, unit='usd/unit-month', dims=ut, minimum=0)
    m.input('affordable_rent_growth', unit='rate', minimum='-0.2', maximum='0.5')
    m.input('mfte_start_month', unit='month', minimum=1)
    m.check('mfte_start_month.whole', condition=ref('mfte_start_month') == round_to(ref('mfte_start_month'), 0),
            code='EVENT_NOT_WHOLE', message='mfte_start_month must be whole.')
    m.check('mfte_start_month.order', condition=ref('mfte_start_month') >= ref('completion_month'),
            code='EVENT_ORDER', message='The MFTE exemption starts after the final certificate, so after completion.')
    m.input('wsg_cost', unit='usd/unit-month', dims=ut, minimum=0)
    m.input('wsg_recovery_rate', unit='rate', minimum=0, maximum=1)
    for name, unit in (('mfte_compliance_cost', 'usd/unit-year'), ('mha_compliance_cost', 'usd/unit-year'),
                       ('mha_monitoring_fee', 'usd/unit-year'),
                       ('land_assessed_value', 'usd'), ('improvement_assessed_value', 'usd')):
        m.input(name, unit=unit, minimum=0)
    m.input('mfte_exit_discount_rate', unit='rate', minimum='0.001', maximum=1)
    m.input('levy_rate', unit='rate', minimum=0, maximum='0.05')
    m.input('residential_improvement_share', unit='rate', minimum=0, maximum=1)
    m.input('assessed_value_growth', unit='rate', minimum='-0.2', maximum='0.5')
    m.input('improvement_tax_month', unit='month', minimum=0)
    m.check('improvement_tax_month.whole', condition=ref('improvement_tax_month') == round_to(ref('improvement_tax_month'), 0),
            code='EVENT_NOT_WHOLE', message='improvement_tax_month must be whole.')

    mfte_units = calc('mfte.units', ref('mfte_elected') * ref('mfte_units'), 'units', ut)
    market_units = calc('units.market', ref('units') - mfte_units - ref('mha.units'), 'units', ut)
    m.check('affordable_units', dims=ut, condition=ref('mfte_units') + ref('mha_units') <= ref('units'),
            code='AFFORDABLE_UNITS', message='MFTE and MHA units are different units and cannot exceed the units of a type.')
    end = ref('mfte_start_month') + MFTE_TERM_MONTHS
    restricted = calc('mfte.restricted', ref('mfte_elected') * if_(idx < end, 1, 0), 'flag', mo)
    exempt = calc('mfte.exempt', restricted * if_(idx >= ref('mfte_start_month'), 1, 0), 'flag', mo)

    def market_at(when):
        return rent_target(ref('market_rent') * power(1 + ref('rent_growth'), when / 12), net_ceiling=ref('rent_limit'))

    def restricted_at(name, when):
        return rent_target(ref('market_rent') * power(1 + ref('rent_growth'), when / 12),
                           net_ceiling=ref(name) * power(1 + ref('affordable_rent_growth'), when / 12))

    def blended(when, mfte_restricted):
        mfte_rent = if_(mfte_restricted == 1, restricted_at('mfte_rent', when), market_at(when)) if mfte_restricted is not None else market_at(when)
        total = market_units * market_at(when) + mfte_units * mfte_rent + ref('mha.units') * restricted_at('mha_rent', when)
        return if_(ref('units') > 0, total / ref('units'), 0)

    calc('rent.target', market_at(idx), 'usd/unit-month', ut + mo)
    calc('rent.mfte', restricted_at('mfte_rent', idx), 'usd/unit-month', ut + mo)
    calc('rent.mha', restricted_at('mha_rent', idx), 'usd/unit-month', ut + mo)
    rent = calc('rent.blended', blended(idx, restricted), 'usd/unit-month', ut + mo)
    open_rent = calc('rent.blended_without_mfte', blended(idx, None), 'usd/unit-month', ut + mo)
    _, occupied, target = build_lease_up(m, a)
    rents = calc('rental_income', sum_over('unit_type', occupied * rent) * pf, dims=mo)
    wsg_month = power(1 + ref('opex_growth'), idx / 12) * pf
    wsg = calc('utility.wsg_expense', sum_over('unit_type', occupied * ref('wsg_cost')) * wsg_month, dims=mo)
    recovery = calc('utility.wsg_recovery', wsg * ref('wsg_recovery_rate'), dims=mo)
    concession = calc('mfte.rent_concession', sum_over('unit_type', occupied * (open_rent - rent)) * pf, dims=mo)
    operating = if_(idx >= ref('occupancy_month'), 1, 0)
    growth = power(1 + ref('opex_growth'), idx / 12)
    expense = calc('operating_expense', operating * ref('annual_opex') / 12 * growth * pf + rents * ref('management_fee'), dims=mo)
    per_month = operating * growth * pf / 12
    mfte_cost = calc('mfte.compliance_cost', restricted * sum_over('unit_type', mfte_units) * ref('mfte_compliance_cost') * per_month, dims=mo)
    mha_cost = calc('mha.compliance_cost', sum_over('unit_type', ref('mha.units'))
                    * (ref('mha_compliance_cost') + ref('mha_monitoring_fee')) * per_month, dims=mo)
    program_cost = calc('program_compliance_cost', mfte_cost + mha_cost, dims=mo)
    av_growth = power(1 + ref('assessed_value_growth'), idx / 12)
    calc('tax.land', ref('land_assessed_value') * av_growth * ref('levy_rate'), 'usd/year', mo)
    calc('tax.improvements', if_(idx >= ref('improvement_tax_month'), ref('improvement_assessed_value') * av_growth * ref('levy_rate'), 0), 'usd/year', mo)
    calc('tax.mfte_exemption', exempt * ref('residential_improvement_share') * ref('tax.improvements'), 'usd/year', mo)
    calc('tax.annual', ref('tax.land') + ref('tax.improvements') - ref('tax.mfte_exemption'), 'usd/year', mo)
    tax = calc('property_tax', ref('tax.annual') / 12 * pf, dims=mo)
    exemption = calc('mfte.tax_saved', ref('tax.mfte_exemption') / 12 * pf, dims=mo)
    income = calc('total_income', rents + recovery, dims=mo)
    expenses = calc('total_expense', expense + wsg + program_cost + tax, dims=mo)
    projection = build_operating_projection(m, period_dim='month', units=ref('delivered_units'), income_lines=(rents, recovery),
                                            expense_lines=(expense, wsg, program_cost, tax), income=income, expenses=expenses, noi_name='noi')
    calc('mfte.net_benefit', exemption - concession * (1 - ref('management_fee')) - mfte_cost, dims=mo)

    # Closed form at the stabilization event (a sum over months would exceed Excel's formula length).
    stab = ref('stabilization_month')
    calc('rent.market_stabilized', market_at(stab), 'usd/unit-month', ut)
    calc('rent.mfte_stabilized', restricted_at('mfte_rent', stab), 'usd/unit-month', ut)
    calc('rent.mha_stabilized', restricted_at('mha_rent', stab), 'usd/unit-month', ut)
    restricted_stab = calc('mfte.restricted_at_stabilization', ref('mfte_elected') * if_(stab < end, 1, 0), 'flag')
    stab_rent = calc('rent.stabilized', blended(stab, restricted_stab), 'usd/unit-month', ut)
    stab_growth = power(1 + ref('assessed_value_growth'), stab / 12)
    improvements = if_(stab >= ref('improvement_tax_month'), ref('improvement_assessed_value') * stab_growth * ref('levy_rate'), 0)
    exempt_stab = restricted_stab * if_(stab >= ref('mfte_start_month'), 1, 0)
    stab_tax = calc('tax.stabilized', ref('land_assessed_value') * stab_growth * ref('levy_rate')
                    + improvements * (1 - exempt_stab * ref('residential_improvement_share')), 'usd/year')
    stabilized_program = (restricted_stab * sum_over('unit_type', mfte_units) * ref('mfte_compliance_cost')
                          + sum_over('unit_type', ref('mha.units')) * (ref('mha_compliance_cost') + ref('mha_monitoring_fee')))
    stabilized_wsg = sum_over('unit_type', target * ref('wsg_cost')) * 12 * (1 - ref('wsg_recovery_rate'))
    stabilized_noi = calc('stabilized_noi', sum_over('unit_type', target * stab_rent) * 12 * (1 - ref('management_fee'))
                          - (ref('annual_opex') + stabilized_program + stabilized_wsg) * power(1 + ref('opex_growth'), stab / 12) - stab_tax)
    return projection.noi, stabilized_noi


def _sale_value(m, a):
    idx, mo, calc = a.idx, a.mo, a.calc
    sale = ref('sale_month')
    window = calc('sale.forward_window', if_(idx > sale, if_(idx <= sale + 12, 1, 0), 0), 'flag', mo)
    # Per-month lines summed as plain ranges keep the workbook formulas short.
    forward = lambda name, body, unit='usd': sum_over('month', calc(name, window * body, unit, mo))
    calc('sale_forward_noi', forward('sale.forward_noi', ref('noi')))
    calc('sale_forward_noi_without_mfte', forward('sale.forward_noi_without_mfte', ref('noi') - ref('mfte.net_benefit')))
    end = ref('mfte_start_month') + MFTE_TERM_MONTHS
    months = calc('mfte.remaining_months', ref('mfte_elected') * max_(end - sale, 0), 'month')
    benefit_months = calc('mfte.forward_exempt_months', forward('sale.forward_exempt', ref('mfte.exempt'), 'flag'), 'month')
    benefit = forward('sale.forward_mfte_benefit', ref('mfte.exempt') * ref('mfte.net_benefit'))
    monthly = calc('mfte.forward_monthly_benefit', if_(benefit_months > 0, benefit / max_(benefit_months, 1), 0))
    rate = ref('mfte_exit_discount_rate') / 12
    calc('mfte.remaining_value', monthly * (1 - power(1 + rate, -months)) / rate)
    return calc('sale_gross_value', ref('sale_forward_noi_without_mfte') / ref('exit_cap_rate') + ref('mfte.remaining_value'))


def _policy(m, a):
    """Public-policy outcomes: restricted homes, tenant rent savings, City payment, tax exemption, feasibility.

    Rent savings are stabilized-year (market less restricted rent on every restricted home). The exemption
    is valued in its first full year (the later of stabilization and the exemption start); its 12-year total
    grows that year at the assessed value growth rate.
    """
    calc = a.calc
    count = lambda name: sum_over('unit_type', ref(name))
    mfte_homes = calc('policy.mfte_homes', count('mfte.units'), 'units')
    mha_homes = calc('policy.mha_homes', count('mha.units'), 'units')
    homes = calc('policy.restricted_homes', mfte_homes + mha_homes, 'units')
    calc('policy.restricted_share', if_(ref('total_units') > 0, homes / ref('total_units'), 0), 'rate')
    mfte_savings = calc('policy.mfte_rent_savings', sum_over('unit_type', ref('mfte.units') * (ref('rent.market_stabilized') - ref('rent.mfte_stabilized'))) * 12)
    mha_savings = calc('policy.mha_rent_savings', sum_over('unit_type', ref('mha.units') * (ref('rent.market_stabilized') - ref('rent.mha_stabilized'))) * 12)
    savings = calc('policy.rent_savings', mfte_savings + mha_savings)
    calc('policy.monthly_savings_per_home', if_(homes > 0, savings / 12 / max_(homes, 1), 0), 'usd/unit-month')
    when = max_(ref('stabilization_month'), ref('mfte_start_month'))
    growth = 1 + ref('assessed_value_growth')
    def exemption_at(month):
        taxed = if_(month >= ref('improvement_tax_month'), 1, 0)
        return (ref('mfte_elected') * taxed * ref('residential_improvement_share') * ref('improvement_assessed_value')
                * power(growth, month / 12) * ref('levy_rate'))
    exemption = calc('policy.mfte_exemption_annual', exemption_at(when))
    first = exemption_at(ref('mfte_start_month'))
    term = if_(ref('assessed_value_growth') == 0, 12, (power(growth, 12) - 1) / max_(ref('assessed_value_growth'), '0.000000001'))
    calc('policy.mfte_exemption_term', first * term)
    calc('policy.mfte_savings_per_exemption_dollar', if_(exemption > 0, mfte_savings / max_(exemption, '0.01'), 0), 'ratio')
    calc('policy.mfte_exemption_per_home', if_(mfte_homes > 0, exemption / max_(mfte_homes, 1), 0), 'usd/unit-year')
    calc('policy.city_mha_payment', ref('mha.payment'))
    calc('policy.cost_per_home', if_(ref('total_units') > 0, ref('project_cost') / ref('total_units'), 0), 'usd/unit')
    calc('policy.yield_on_cost', if_(ref('project_cost') > 0, ref('stabilized_noi') / ref('project_cost'), 0), 'rate')


def _compliance(m, a):
    total = sum_over('unit_type', ref('units'))
    family = sum_over('unit_type', if_(ref('bedrooms') >= 2, ref('units'), 0))
    large = sum_over('unit_type', if_(ref('bedrooms') >= 3, ref('units'), 0))
    m.calc('mfte.set_aside_rate', unit='rate', expr=if_(family >= total * '0.12', '0.20', if_(large >= total * '0.03', '0.20', '0.25')))
    m.calc('mfte.required_units', unit='units', expr=total * ref('mfte.set_aside_rate'))
    m.test('mfte_set_aside', condition=ref('mfte_elected') * ref('mfte.required_units') <= sum_over('unit_type', ref('mfte.units')),
           code='MFTE_SET_ASIDE', message='MFTE units are below the Program 7 set-aside (whole units at or above the required share).')
    provided = sum_over('unit_type', ref('mha.units'))
    large_units = sum_over('unit_type', if_(ref('bedrooms') >= 3, ref('mha.units'), 0))
    # Under two required units: two units, or one unit with three or more bedrooms.
    small = if_(provided >= 2, 1, if_(large_units >= 1, 1, 0))
    # Two or more: the whole part must be provided; a remaining fraction is paid.
    whole = if_(provided > ref('mha.required_units') - 1, 1, 0)
    met = if_(ref('mha.required_units') < 2, small, whole)
    m.test('mha_performance', condition=ref('mha_applies') * ref('mha_performance') * (1 - met) <= 0,
           code='MHA_PERFORMANCE_SHORTFALL', message='MHA performance units are below the whole-unit requirement; a payment covers only a fractional unit.')


def write_workbook(deal, inputs, path):
    """Live development workbook led by an Executive Summary of the programs' policy outcomes."""
    from .seattle_summary import write_summary
    from .workbook import SEATTLE_LABELS, write_workbook as write_development
    model, run, compiled = write_development(deal, inputs, path, build=build_model, labels=SEATTLE_LABELS,
                                             footer='Draft Seattle development model (MFTE and MHA)')
    write_summary(compiled, run, deal, model, inputs)
    compiled.save(path)
    return model, run, compiled
