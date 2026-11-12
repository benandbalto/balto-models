"""Executive Summary: the policy outcomes of Seattle's MFTE and MHA programs on one project.

Written for public-sector readers, so it carries no confidentiality stamp. Column C is live: every figure is a link to
(or short formula over) the compiled model, registered with `Compiled.derive` so
the parity check recalculates it. Columns D-I compare every program combination;
each is a separate engine run at build time and is labelled as such.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from typing import Callable

from balto_model_engine import EngineError, Run, evaluate
from balto_valuation.branding import SPONSOR
from balto_valuation.overview import BAND, GREY_TEXT, INT, NAVY, PCT, PCT2, TOTAL, USD, _Writer, _col

SHEET = 'Executive Summary'
RATIO = '$0.00;($0.00);"-"'
PP = '+0.0" pts";-0.0" pts";"-"'


@dataclass(frozen=True)
class Scenario:
    label: str
    mfte: int
    mha_applies: int
    mha_performance: int


SCENARIOS = (
    Scenario('No MFTE, no MHA (baseline)', 0, 0, 0),
    Scenario('MHA payment', 0, 1, 0),
    Scenario('MHA performance', 0, 1, 1),
    Scenario('MFTE only', 1, 0, 0),
    Scenario('MFTE + MHA payment', 1, 1, 0),
    Scenario('MFTE + MHA performance', 1, 1, 1),
)


def scenario_runs(model, inputs) -> list[Run | None]:
    """One engine run per program combination; None when a combination cannot be calculated."""
    runs = []
    for s in SCENARIOS:
        try:
            runs.append(evaluate(model, {**inputs, 'mfte_elected': s.mfte, 'mha_applies': s.mha_applies,
                                         'mha_performance': s.mha_performance}))
        except EngineError:
            runs.append(None)
    return runs


def _mfte_text(r: Run) -> str:
    return 'Participates' if r.values['mfte_elected'][()] == 1 else 'Does not participate'


def _mha_text(r: Run) -> str:
    if r.values['mha_applies'][()] == 0:
        return 'Not applied'
    return 'Performance (on-site homes)' if r.values['mha_performance'][()] == 1 else 'Payment to City'


def _irr(r: Run, name: str) -> Decimal | None:
    metric = r.metrics.get(name, {})
    return metric.get('rate') if metric.get('status') == 'ok' else None


def write_summary(compiled, run: Run, deal, model, inputs, *, prepared: date | None = None) -> str:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.properties import PageSetupProperties

    wb = compiled.workbook
    ws = wb.create_sheet(SHEET, 0)
    w = _Writer(ws, compiled, run, deal)
    at, v = w.at, w.v
    runs = scenario_runs(model, inputs)
    current = next((i for i, s in enumerate(SCENARIOS) if (s.mfte, s.mha_applies, s.mha_performance) ==
                    tuple(int(v(run, n)) for n in ('mfte_elected', 'mha_applies', 'mha_performance'))), None)
    live, first, last = 3, 4, 3 + len(SCENARIOS)
    full = (2, last)

    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    ws.column_dimensions['A'].width = 2
    ws.column_dimensions['B'].width = 50
    for c in range(live, last + 1):
        ws.column_dimensions[_col(c)].width = 16

    navy = PatternFill('solid', fgColor=NAVY)
    for r in (1, 2, 3):
        for c in range(1, last + 2):
            ws.cell(r, c).fill = navy
    ws.row_dimensions[1].height, ws.row_dimensions[2].height, ws.row_dimensions[3].height = 8, 26, 18
    w.text(2, 2, SPONSOR.upper(), bold=True, size=16, color='FFFFFF')
    w.text(3, 2, 'Seattle Multifamily Development  ·  Policy Outcomes of MFTE and MHA', size=11, color='FFFFFF')
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    prepared = prepared or (datetime.fromtimestamp(int(epoch), timezone.utc).date() if epoch else date.today())
    w.text(3, last, f'Prepared {prepared:%B} {prepared.day}, {prepared.year}', size=9, color=BAND).alignment = Alignment(horizontal='right')
    for c in range(1, last + 2):
        ws.cell(4, c).fill = PatternFill('solid', fgColor=BAND)
    ws.row_dimensions[4].height = 4

    w.text(6, 2, deal.name, bold=True, size=14, color=NAVY)
    w.text(7, 2, '  ·  '.join((deal.location, f'Closing {deal.closing:%B %Y}',
                               f'{deal.horizon_years}-year projection')), size=10, color=GREY_TEXT)
    intro = ws.cell(9, 2)
    w.text(9, 2, "What Seattle's two affordability programs deliver on this proposed building, and what they cost the "
                 'project and the public. MFTE (Multifamily Tax Exemption) trades 12 years of property tax on the '
                 'residential improvements for income-restricted homes. MHA (Mandatory Housing Affordability) requires '
                 'either a payment to the City for affordable housing or income-restricted homes on site for 75 years.',
           size=10)
    ws.merge_cells(start_row=9, start_column=2, end_row=9, end_column=last)
    intro.alignment = Alignment(wrap_text=True, vertical='top')
    ws.row_dimensions[9].height = 44

    top = 11
    headers = {live: 'This workbook (live)'} | {first + i: s.label for i, s in enumerate(SCENARIOS)}
    w.band(top, full, 'Program comparison', headers)
    ws.row_dimensions[top + 1].height = 30
    if current is not None:
        ws.cell(top + 1, first + current).fill = PatternFill('solid', fgColor=TOTAL)
    row = top + 2

    def static(r_: int, col: int, value, fmt: str) -> None:
        if value is None:
            cell = w.text(r_, col, 'n/a', color='404040')
        elif isinstance(value, str):
            cell = w.text(r_, col, value, color='404040')
        else:
            cell = w.number(r_, col, float(value), fmt, color='404040')
        cell.alignment = Alignment(horizontal='right', wrap_text=isinstance(value, str))
        if current is not None and col == first + current:
            cell.fill = PatternFill('solid', fgColor=TOTAL)

    def line(label: str, fmt: str, live_cell: Callable[[int], object], value: Callable[[Run], object], bold=False):
        nonlocal row
        w.label(row, 2, label, bold=bold)
        live_cell(row)
        for i, r_ in enumerate(runs):
            static(row, first + i, None if r_ is None else value(r_), fmt)
        row += 1

    def scalar(label: str, name: str, fmt: str, bold=False):
        line(label, fmt, lambda r_: w.link(r_, live, name, fmt=fmt, bold=bold), lambda r_: r_.values[name][()], bold)

    def section(title: str):
        nonlocal row
        w.sub(row, full, title)
        row += 1

    section('Program choices')
    mfte_flag, applies, performs = at('mfte_elected'), at('mha_applies'), at('mha_performance')
    line('MFTE (Multifamily Tax Exemption)', '@',
         lambda r_: w.formula(r_, live, f'IF({mfte_flag}=1,"Participates","Does not participate")', _mfte_text, None, link=True),
         _mfte_text)
    line('MHA (Mandatory Housing Affordability)', '@',
         lambda r_: w.formula(r_, live, f'IF({applies}=0,"Not applied",IF({performs}=1,"Performance (on-site homes)","Payment to City"))',
                              _mha_text, None, link=True), _mha_text)
    for r_ in range(row - 2, row):
        for c in range(live, last + 1):
            ws.cell(r_, c).alignment = Alignment(horizontal='right', wrap_text=True)
        ws.row_dimensions[r_].height = 26

    section('Affordable homes delivered')
    scalar('Total homes', 'total_units', INT)
    scalar('MFTE income-restricted homes (12 years)', 'policy.mfte_homes', INT)
    scalar('MHA income-restricted homes (75 years)', 'policy.mha_homes', INT)
    scalar('Total income-restricted homes', 'policy.restricted_homes', INT, bold=True)
    scalar('Share of homes income-restricted', 'policy.restricted_share', PCT)
    scalar('Average monthly rent savings per restricted home', 'policy.monthly_savings_per_home', USD)
    scalar('Annual rent savings to restricted households (stabilized year)', 'policy.rent_savings', USD, bold=True)

    section('Public revenue and cost')
    scalar('MHA payment to the City for affordable housing', 'policy.city_mha_payment', USD, bold=True)
    scalar('MFTE property tax exemption, first full year', 'policy.mfte_exemption_annual', USD)
    scalar('MFTE property tax exemption over the 12-year term (nominal)', 'policy.mfte_exemption_term', USD, bold=True)
    scalar('MFTE exemption per MFTE home per year', 'policy.mfte_exemption_per_home', USD)
    scalar('MFTE tenant rent savings per $1 of exemption', 'policy.mfte_savings_per_exemption_dollar', RATIO)

    section('Project feasibility')
    scalar('Total development cost (including MHA payment)', 'project_cost', USD)
    scalar('Development cost per home', 'policy.cost_per_home', USD)
    scalar('Stabilized net operating income', 'stabilized_noi', USD)
    scalar('Yield on cost (stabilized NOI ÷ development cost)', 'policy.yield_on_cost', PCT2, bold=True)
    scalar('Peak equity required', 'peak_equity', USD)
    line('Levered project IRR', PCT2, lambda r_: w.metric(r_, live, 'levered_irr'), lambda r_: _irr(r_, 'levered_irr'), bold=True)
    line('Investor (LP) IRR', PCT2, lambda r_: w.metric(r_, live, 'lp_irr', bold=False), lambda r_: _irr(r_, 'lp_irr'))
    baseline = _irr(runs[0], 'levered_irr') if runs[0] is not None else None

    def change(r_: Run):
        irr = _irr(r_, 'levered_irr')
        return None if irr is None or baseline is None else (irr - baseline) * 100

    w.label(row, 2, 'Levered IRR change vs. baseline (percentage points)')
    base_cell = f'{_col(first)}{row - 2}'
    w.formula(row, live, f'IFERROR(({compiled.metrics["levered_irr"]}-{base_cell})*100,"n/a")',
              lambda x: (_irr(x, 'levered_irr') - baseline) * 100 if baseline is not None and _irr(x, 'levered_irr') is not None else 'n/a',
              PP, link=False)
    for i, r_ in enumerate(runs):
        static(row, first + i, None if r_ is None else change(r_), PP)
    row += 1

    # --- Rents by home type (live inputs) --------------------------------------------------------
    row += 1
    w.band(row, full, "Rents by home type (today's dollars, after utilities and required fees)",
           {3: 'Homes', 4: 'Market rent', 5: 'MFTE rent', 6: 'MFTE discount', 7: 'MHA rent', 8: 'MHA discount', 9: 'Restricted homes (MFTE / MHA)'})
    ws.row_dimensions[row + 1].height = 30
    row += 2
    for u in deal.unit_types:
        k = u.key
        w.label(row, 2, u.label)
        w.link(row, 3, 'units', k, fmt=INT)
        w.link(row, 4, 'market_rent', k, fmt=USD)
        w.link(row, 5, 'mfte_rent', k, fmt=USD)
        w.formula(row, 6, f'IF({_col(4)}{row}>0,MAX(0,1-{_col(5)}{row}/{_col(4)}{row}),0)',
                  lambda x, k=k: max(Decimal(0), 1 - v(x, 'mfte_rent', k) / v(x, 'market_rent', k)) if v(x, 'market_rent', k) > 0 else 0, PCT)
        w.link(row, 7, 'mha_rent', k, fmt=USD)
        w.formula(row, 8, f'IF({_col(4)}{row}>0,MAX(0,1-{_col(7)}{row}/{_col(4)}{row}),0)',
                  lambda x, k=k: max(Decimal(0), 1 - v(x, 'mha_rent', k) / v(x, 'market_rent', k)) if v(x, 'market_rent', k) > 0 else 0, PCT)
        w.formula(row, 9, f'{at("mfte.units", k)}&" / "&{at("mha.units", k)}',
                  lambda x, k=k: f"{int(v(x, 'mfte.units', k))} / {int(v(x, 'mha.units', k))}",
                  None, link=True).alignment = Alignment(horizontal='right')
        row += 1

    # --- How to read ------------------------------------------------------------------------
    row += 1
    w.band(row, full, 'How to read this summary')
    row += 1
    notes = (
        'Column C recalculates when inputs in this workbook change. Columns D-I are separate runs of the same model '
        'with each program combination, made when the workbook was built; rebuild the workbook to refresh them. '
        'The shaded column matches the program choices in this workbook.',
        'Income-restricted homes rent at or below the Office of Housing limit for their income level, less utilities '
        'and required fees. MFTE homes serve 40-90% of area median income (AMI) by home type and revert to market '
        'rent when the 12-year exemption ends. MHA homes serve 60% AMI (40% for homes of 400 sq ft or less) for 75 years. '
        'MFTE and MHA homes are always different homes.',
        'Rent savings are market rent less restricted rent on every restricted home in the stabilized year. The MFTE '
        'exemption is the property tax the residential improvements would otherwise pay; land and commercial space '
        'stay taxed. How much of an exemption shifts to other taxpayers rather than reducing levy collections depends '
        'on the levy and is not modeled.',
        'The MHA payment is due before the structural building permit and funds Office of Housing affordable housing '
        'elsewhere; homes it produces are not counted here. Under performance, only a fractional required home is paid.',
        'Feasibility measures are before income taxes. A project typically needs a return above its investors\' required '
        'return to be built; the program choice that keeps a project feasible delivers more homes than one that stops it.',
        'Every input has a recorded source or stated assumption on the Input Basis sheet when the workbook comes from a '
        'saved Balto run. Program rules: SMC 5.73 (MFTE Program 7, Ord. 127316) and SMC 23.58C (MHA).',
    )
    for text in notes:
        cell = ws.cell(row, 2)
        w.text(row, 2, text, size=9, color=GREY_TEXT)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=last)
        cell.alignment = Alignment(wrap_text=True, vertical='top')
        ws.row_dimensions[row].height = 38
        row += 1

    ws.freeze_panes = None
    ws.print_area = f'A1:{_col(last + 1)}{row}'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.print_options.horizontalCentered = True
    wb.active = 0
    return SHEET
