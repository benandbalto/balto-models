"""All inputs and development formulas remain editable and independently calculable."""
from balto_model_engine import evaluate
from balto_model_engine.workbook import compile_workbook,Layout,Sheet,Row,Heading,MetricRow
from balto_valuation.branding import SPONSOR
from .model import build_model

LABELS={'project_cost':'Land and development budget (excluding financing)',
        'stabilized_noi':'Stabilized annual NOI', 'peak_equity':'Peak net required equity',
        'total_equity_required':'Total equity required', 'total_distributions':'Total distributions',
        'total_funding_gap':'Unmet committed funding', 'investor_flow':'Investor cash flow assuming full required equity',
        'construction.capitalized_interest':'Capitalized construction interest',
        'construction.cash_interest':'Current-paid construction interest',
        'permanent_size.amount':'Permanent loan amount', 'funding_gap':'Unmet equity funding',
        'spending_weight':'Explicit fraction of phase budget', 'rent_limit':'Net monthly rent ceiling (explicit assumption)',
        'period_fraction':'Operations fraction of calendar month'}

SEATTLE_LABELS={'mha.payment':'MHA payment due (fee in lieu, or fractional unit under performance)',
        'mha.required_units':'MHA performance units required', 'mfte.set_aside_rate':'MFTE Program 7 set-aside rate',
        'mfte.required_units':'MFTE units required', 'mfte.remaining_value':'Present value of remaining MFTE benefit at sale',
        'sale_forward_noi_without_mfte':'Forward NOI at sale without MFTE (market rents, full tax)',
        'sale_gross_value':'Gross sale value', 'mfte.net_benefit':'MFTE net benefit (tax saved less rent given up and compliance)',
        'tax.mfte_exemption':'Annual MFTE exemption (residential improvements)'}

# Program names and finance abbreviations stay capitalized in generated labels.
ACRONYMS={'mfte':'MFTE','mha':'MHA','lp':'LP','gp':'GP','irr':'IRR','noi':'NOI','ami':'AMI','gc':'GC',
          'ltv':'LTV','dscr':'DSCR','pv':'PV','av':'AV','f12':'F12'}

def readable(name):
    words=name.replace('.',' ').replace('_',' ').split()
    words=[ACRONYMS.get(w.lower(),w) for w in words]
    first=words[0] if words[0].isupper() else words[0].capitalize()
    return ' '.join([first,*(w if w.isupper() else w.lower() for w in words[1:])])

def write_workbook(deal,inputs,path,build=build_model,labels=None,footer='Draft development model'):
    m=build(deal);run=evaluate(m,inputs);labels={**LABELS,**(labels or {})}
    groups={'Summary':[], 'Assumptions':[], 'Phase Budget':[], 'Spending Curve':[],
            'Unit Targets':[], 'Lease Up':[], 'Construction Loan':[], 'Permanent Loan':[], 'Monthly Cash Flow':[], 'Investor Waterfall':[]}
    if any(n.startswith(('mfte.','mha.','tax.')) and v.dims==('month',) for n,v in m.variables.items()):groups['Seattle Programs']=[]
    for name,var in m.variables.items():
        if var.kind=='input':sheet='Assumptions'
        elif name.startswith(('mfte.','mha.','tax.')) and var.dims==('month',):sheet='Seattle Programs'
        elif var.dims==('phase',):sheet='Phase Budget'
        elif var.dims==('spend',):sheet='Spending Curve'
        elif var.dims==('unit_type',):sheet='Unit Targets'
        elif 'unit_type' in var.dims:sheet='Lease Up'
        elif name.startswith('construction.'):sheet='Construction Loan'
        elif name.startswith(('permanent.','permanent_size.')):sheet='Permanent Loan'
        elif name.startswith(('lp_','gp_','wf.','pref.','hurdle.','tier_')):sheet='Investor Waterfall'
        elif not var.dims:sheet='Summary'
        else:sheet='Monthly Cash Flow'
        groups[sheet].append(Row(name,labels.get(name,readable(name))))
    groups['Summary']=[Heading(deal.name),Heading('Draft development assumptions; review source basis and all funding outcomes'),
        Heading('Construction: end-period draws; ACT/365F interest on opening debt'),
        Heading('Returns assume full required equity; committed funding gaps remain visible'),*groups['Summary'],MetricRow('levered_irr','Levered IRR assuming full required equity'),
        MetricRow('lp_irr','LP IRR assuming full required equity'),MetricRow('gp_irr','GP IRR including co-invest and promote')]
    compiled=compile_workbook(m,run,Layout(tuple(Sheet(name,tuple(rows),columns='month' if name in ('Lease Up','Construction Loan','Permanent Loan','Monthly Cash Flow','Investor Waterfall','Seattle Programs') else None) for name,rows in groups.items()),header=SPONSOR.upper(),footer=footer))
    compiled.workbook['Dimensions'].sheet_state='hidden'
    compiled.save(path)
    return m,run,compiled
