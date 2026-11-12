"""The Deal Overview: a branded cover sheet.

Every figure is a live formula over the compiled sheets: a link (green) to the
cell that holds it, or a short calculation (black) from such links. Each one
is registered with `Compiled.derive` together with what it must show for a
run, so the parity check recalculates the overview too. The one exception is
the optional return sensitivity, which is a grid of separate engine runs and
is labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import os
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from balto_model_engine import Run
from balto_model_engine.workbook import Compiled

from .deal import Deal

from .branding import CONFIDENTIAL, SPONSOR
SHEET = "Deal Overview"

FONT = "Arial"
NAVY, BAND, TOTAL, GREY_TEXT = "1F3864", "D9E1F2", "F2F2F2", "595959"
LINK, INPUT = "008000", "0000FF"
USD = '$#,##0;($#,##0);"-"'
USD2 = '$#,##0.00;($#,##0.00);"-"'
PCT = '0.0%;(0.0%);"-"'
PCT2 = '0.00%;(0.00%);"-"'
INT = '#,##0;(#,##0);"-"'
UNITS1 = '#,##0.0;(#,##0.0);"-"'
MULT = '0.00"x";(0.00"x");"-"'
YEARS = '0.0 "yrs"'
DATE = "mmm d, yyyy"
MONTH = "mmm-yy"

REGIME_LABEL = {"market": "Market", "restricted": "Income-restricted", "contract": "HAP contract"}
MODE_LABEL = {"accrue": "Accrues to sale", "available_cash": "Pays from available cash",
              "cash_sweep": "Cash sweep", "scheduled": "Scheduled"}
TAX_LABEL = {"or_mav": "Oregon (lesser of RMV and MAV + 3%)", "wa_market": "Washington (market value)"}

LEFT = (2, 5)    # B:E — label in B, values in C:E
RIGHT = (7, 13)  # G:M — label in G, values in J:M


@dataclass(frozen=True)
class Sensitivity:
    """Levered equity IRR across exit cap rates and sale months, each a separate engine run."""
    exit_caps: Sequence[Decimal]
    sale_months: Sequence[int]
    irr: Mapping[tuple[int, Decimal], Decimal | None]


def _serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def _d(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


class _Writer:
    def __init__(self, ws, compiled: Compiled, run: Run, deal: Deal) -> None:
        self.ws, self.compiled, self.run, self.deal = ws, compiled, run, deal

    # --- Addresses ------------------------------------------------------------

    def at(self, name: str, *idx) -> str:
        return self.compiled.cells[name][tuple(idx)]

    def has(self, name: str, *idx) -> bool:
        return tuple(idx) in self.compiled.cells.get(name, {})

    def span(self, name: str) -> str:
        """The row of a monthly variable from closing to the horizon, as one range."""
        cells = self.compiled.cells[name]
        first, last = cells[min(cells)], cells[max(cells)]
        return f"{first}:{last.rsplit('!', 1)[1]}"

    @staticmethod
    def v(run: Run, name: str, *idx) -> Decimal:
        return run.values[name][tuple(idx)]

    @staticmethod
    def total(run: Run, name: str) -> Decimal:
        return sum(run.values[name].values(), Decimal(0))

    # --- Cells ------------------------------------------------------------------

    def font(self, **style):
        from openpyxl.styles import Font
        return Font(name=FONT, size=style.pop("size", 10), **style)

    def text(self, row: int, col: int, value: str, **style) -> Any:
        cell = self.ws.cell(row, col)
        cell.value = value
        cell.data_type = "s"
        cell.font = self.font(**style)
        return cell

    def number(self, row: int, col: int, value: Any, fmt: str, **style) -> Any:
        cell = self.ws.cell(row, col, value)
        cell.number_format = fmt
        cell.font = self.font(**style)
        return cell

    def formula(self, row: int, col: int, formula: str, expect: Callable[[Run], Any], fmt: str | None,
                bold: bool = False, link: bool = False) -> Any:
        cell = self.ws.cell(row, col)
        self.compiled.derive(cell, formula, expect, self.run)
        if fmt:
            cell.number_format = fmt
        cell.font = self.font(bold=bold, color=LINK if link else None)
        return cell

    def link(self, row: int, col: int, name: str, *idx, fmt: str, bold: bool = False) -> Any:
        return self.formula(row, col, self.at(name, *idx), lambda r: self.v(r, name, *idx), fmt, bold, link=True)

    def metric(self, row: int, col: int, name: str, bold: bool = True) -> Any:
        return self.formula(row, col, self.compiled.metrics[name], lambda r: r.metrics[name].get("rate"), PCT2,
                            bold, link=True)

    # --- Blocks -------------------------------------------------------------------

    def band(self, row: int, cols: tuple[int, int], title: str, headers: Mapping[int, str] | None = None) -> None:
        from openpyxl.styles import Alignment, Border, PatternFill, Side

        fill = PatternFill("solid", fgColor=NAVY)
        for c in range(cols[0], cols[1] + 1):
            self.ws.cell(row, c).fill = fill
        self.text(row, cols[0], title.upper(), bold=True, color="FFFFFF")
        if headers:
            rule = Border(bottom=Side(style="thin", color="808080"))
            for c in range(cols[0], cols[1] + 1):
                self.ws.cell(row + 1, c).border = rule
            for c, h in headers.items():
                self.text(row + 1, c, h, bold=True).alignment = Alignment(horizontal="right", wrap_text=True)

    def sub(self, row: int, cols: tuple[int, int], title: str) -> None:
        from openpyxl.styles import PatternFill

        for c in range(cols[0], cols[1] + 1):
            self.ws.cell(row, c).fill = PatternFill("solid", fgColor=BAND)
        self.text(row, cols[0], title, bold=True, color=NAVY)

    def label(self, row: int, col: int, text: str, bold: bool = False, indent: int = 1) -> None:
        from openpyxl.styles import Alignment
        self.text(row, col, text, bold=bold).alignment = Alignment(indent=0 if bold else indent)

    def shade_total(self, row: int, cols: tuple[int, int], double: bool = False) -> None:
        from openpyxl.styles import Border, PatternFill, Side

        thin = Side(style="thin", color="808080")
        bottom = Side(style="double", color="808080") if double else None
        for c in range(cols[0], cols[1] + 1):
            cell = self.ws.cell(row, c)
            cell.fill = PatternFill("solid", fgColor=TOTAL)
            cell.border = Border(top=thin, bottom=bottom)
            if cell.font is not None and c == cols[0]:
                cell.font = self.font(bold=True)

    def note(self, row: int, col: int, text: str) -> None:
        self.text(row, col, text, size=9, italic=True, color=GREY_TEXT)


def write_overview(compiled: Compiled, run: Run, deal: Deal, *, sponsor: str = SPONSOR,
                   location: str | None = None, sensitivity: Sensitivity | None = None,
                   model_label: str = "", prepared: date | None = None) -> str:
    """Add the overview as the first sheet of `compiled.workbook` and return its name."""
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.properties import PageSetupProperties

    wb = compiled.workbook
    ws = wb.create_sheet(SHEET, 0)
    w = _Writer(ws, compiled, run, deal)
    at, v, total, span = w.at, w.v, w.total, w.span
    years = [k for k in range(deal.horizon_years + 1)]
    last_col = max(RIGHT[1], 3 + len(years) - 1)
    full = (2, last_col)

    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 38
    for c in range(3, last_col + 1):
        ws.column_dimensions[_col(c)].width = 13.5

    # --- Title -----------------------------------------------------------------------------
    navy = PatternFill("solid", fgColor=NAVY)
    for r in (1, 2, 3):
        for c in range(1, last_col + 2):
            ws.cell(r, c).fill = navy
    ws.row_dimensions[1].height = 8
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 18
    w.text(2, 2, sponsor.upper(), bold=True, size=16, color="FFFFFF")
    kind = "Mixed-Use" if deal.commercial_spaces else "Multifamily"
    title = f"Value-Add {kind} Acquisition"
    w.text(3, 2, f"{title}  ·  Deal Overview", size=11, color="FFFFFF")
    if CONFIDENTIAL:
        w.text(2, last_col, "CONFIDENTIAL", bold=True, size=9, color="FFFFFF").alignment = Alignment(horizontal="right")
    # SOURCE_DATE_EPOCH (the reproducible-builds convention) pins the date for published examples.
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    prepared = prepared or (datetime.fromtimestamp(int(epoch), timezone.utc).date() if epoch else date.today())
    w.text(3, last_col, f"Prepared {prepared:%B} {prepared.day}, {prepared.year}", size=9, color=BAND).alignment = \
        Alignment(horizontal="right")
    for c in range(1, last_col + 2):
        ws.cell(4, c).fill = PatternFill("solid", fgColor=BAND)
    ws.row_dimensions[4].height = 4

    w.text(6, 2, deal.name, bold=True, size=14, color=NAVY)
    facts = [x for x in (location, f"Closing {deal.closing:%B} {deal.closing.day}, {deal.closing.year}", f"{deal.horizon_years}-year projection")
             if x]
    w.text(7, 2, "  ·  ".join(facts), size=10, color=GREY_TEXT)
    if model_label:
        w.text(7, last_col, model_label, size=8, color="808080").alignment = Alignment(horizontal="right")

    units = at("total_units")
    sale = at("sale_month")
    closing_serial = _serial(deal.closing)

    # --- Property and acquisition (left) | Returns (right) ----------------------------------
    top = 9
    w.band(top, LEFT, "Property & acquisition")
    r = top + 1
    rows_left = [
        ("Total units", lambda r_: w.link(r_, 3, "total_units", fmt=INT)),
        ("Income-restricted units (AMI)", lambda r_: (
            w.link(r_, 3, "restricted_units", fmt=INT),
            w.formula(r_, 4, f"{at('restricted_units')}/{units}",
                      lambda x: v(x, "restricted_units") / v(x, "total_units"), PCT))),
        ("Occupancy at closing", lambda r_: w.formula(
            r_, 3, f"SUM({_cells_range(compiled, 'occupied_at_close')})/{units}",
            lambda x: total(x, "occupied_at_close") / v(x, "total_units"), PCT)),
        ("Purchase price", lambda r_: w.link(r_, 3, "purchase_price", fmt=USD, bold=True)),
        ("Price per unit", lambda r_: w.link(r_, 3, "price_per_unit", fmt=USD)),
        ("Year 1 NOI", lambda r_: w.link(r_, 3, "year_1_noi", fmt=USD)),
        ("Going-in cap rate (Year 1 NOI)", lambda r_: w.link(r_, 3, "going_in_cap_rate", fmt=PCT2)),
        ("Capital budget (renovation + property)", lambda r_: w.link(r_, 3, "capex_budget", fmt=USD)),
        ("All-in cost", lambda r_: w.link(r_, 3, "all_in_cost", fmt=USD, bold=True)),
        ("All-in cost per unit", lambda r_: w.formula(
            r_, 3, f"{at('all_in_cost')}/{units}", lambda x: v(x, "all_in_cost") / v(x, "total_units"), USD)),
        ("Yield on cost (exit forward cash flow)", lambda r_: w.link(r_, 3, "yield_on_cost", fmt=PCT2)),
    ]
    for text, put in rows_left:
        w.label(r, 2, text)
        put(r)
        r += 1
    left_end = r

    w.band(top, RIGHT, "Returns summary", {10: "Unlevered", 11: "Levered equity", 12: "LP", 13: "GP"})
    r = top + 2
    unlev = span("unlevered_cash_flow")
    flows = {11: "levered_cash_flow", 12: "lp_cash_flow", 13: "gp_cash_flow"}
    w.label(r, 7, "IRR", bold=True)
    for col, name in ((10, "unlevered_irr"), (11, "levered_irr"), (12, "lp_irr"), (13, "gp_irr")):
        w.metric(r, col, name)
    r += 1
    w.label(r, 7, "Equity multiple")
    w.formula(r, 10, f'SUMIF({unlev},">0")/-SUMIF({unlev},"<0")',
              lambda x: _pos(x, "unlevered_cash_flow") / -_neg(x, "unlevered_cash_flow"), MULT)
    for col, name in ((11, "equity_multiple"), (12, "lp_multiple"), (13, "gp_multiple")):
        w.link(r, col, name, fmt=MULT)
    r += 1
    w.label(r, 7, "Capital invested")
    w.formula(r, 10, f'-SUMIF({unlev},"<0")', lambda x: -_neg(x, "unlevered_cash_flow"), USD)
    w.link(r, 11, "total_contributions", fmt=USD)
    for col, name in ((12, "lp_contribution"), (13, "gp_contribution")):
        w.formula(r, col, f"SUM({span(name)})", lambda x, n=name: total(x, n), USD)
    r += 1
    w.label(r, 7, "Total distributions")
    w.formula(r, 10, f'SUMIF({unlev},">0")', lambda x: _pos(x, "unlevered_cash_flow"), USD)
    w.link(r, 11, "total_distributions", fmt=USD)
    for col, name in ((12, "lp_distribution"), (13, "gp_distribution")):
        w.formula(r, col, f"SUM({span(name)})", lambda x, n=name: total(x, n), USD)
    r += 1
    w.label(r, 7, "Net profit", bold=True)
    w.formula(r, 10, f"SUM({unlev})", lambda x: total(x, "unlevered_cash_flow"), USD, bold=True)
    for col, name in flows.items():
        w.formula(r, col, f"SUM({span(name)})", lambda x, n=name: total(x, n), USD, bold=True)
    w.shade_total(r, RIGHT)
    r += 2
    w.label(r, 7, "Hold period")
    w.formula(r, 10, f"{sale}/12", lambda x: v(x, "sale_month") / 12, YEARS, link=True)
    r += 1
    w.label(r, 7, "Sale date")
    w.formula(r, 10, f"EDATE({closing_serial},{sale})",
              lambda x: _serial(_add_months(deal.closing, int(v(x, "sale_month")))), DATE, link=True)
    r += 1
    w.note(r, 7, "GP returns include the promote and co-investment; sponsor fees are shown separately.")
    r += 1
    right_end = r

    # --- Sources and uses (left) | Capitalization (right) --------------------------------------
    top = max(left_end, right_end) + 1
    w.band(top, LEFT, "Sources & uses at closing", {3: "Amount", 4: "Per unit", 5: "% of total"})
    r = top + 2
    total_uses = at("total_uses")

    def su_row(row: int, text: str, formula: str, expect, bold: bool = False, link: bool = True) -> None:
        w.label(row, 2, text, bold=bold)
        c = w.formula(row, 3, formula, expect, USD, bold=bold, link=link)
        here = c.coordinate
        w.formula(row, 4, f"{here}/{units}", lambda x: expect(x) / v(x, "total_units"), USD, bold=bold)
        w.formula(row, 5, f"{here}/{total_uses}", lambda x: expect(x) / v(x, "total_uses"), PCT, bold=bold)

    w.sub(r, LEFT, "Uses")
    r += 1
    for name, text in (("purchase_price", "Purchase price"), ("acquisition_costs", "Acquisition closing costs"),
                       ("financing_costs", "Financing costs"), ("acquisition_fee", "Acquisition fee"),
                       ("reno_budget", "Unit renovation budget"),
                       ("property_capex_budget", "Property capital (funded at closing)"),
                       ("working_capital", "Working capital & operating reserve")):
        su_row(r, text, at(name), lambda x, n=name: v(x, n))
        r += 1
    su_row(r, "Total uses", total_uses, lambda x: v(x, "total_uses"), bold=True)
    w.shade_total(r, LEFT)
    uses_row = r
    r += 1
    w.sub(r, LEFT, "Sources")
    r += 1
    first_source = r
    su_row(r, "Senior loan", at("senior.amount"), lambda x: v(x, "senior.amount"))
    r += 1
    for t in deal.tranches:
        su_row(r, t.label, at(f"{t.key}.amount"), lambda x, k=t.key: v(x, f"{k}.amount"))
        r += 1
    lp = at("lp_share")
    equity = at("equity_at_close")
    su_row(r, "LP equity", f"{equity}*{lp}", lambda x: v(x, "equity_at_close") * v(x, "lp_share"), link=False)
    r += 1
    su_row(r, "GP equity (co-invest)", f"{equity}*(1-{lp})",
           lambda x: v(x, "equity_at_close") * (1 - v(x, "lp_share")), link=False)
    r += 1
    su_row(r, "Total sources", f"SUM(C{first_source}:C{r - 1})", lambda x: v(x, "total_uses"), bold=True,
           link=False)
    w.shade_total(r, LEFT, double=True)
    sources_row = r
    r += 1
    left_end = r

    w.band(top, RIGHT, "Capitalization", {10: "Amount", 11: "Rate", 12: "LTV / LTC", 13: "Terms"})
    r = top + 2
    price = at("purchase_price")
    w.label(r, 7, "Senior acquisition loan")
    w.link(r, 10, "senior.amount", fmt=USD)
    w.link(r, 11, "senior.rate", fmt=PCT2)
    w.formula(r, 12, f"{at('senior.amount')}/{price}", lambda x: v(x, "senior.amount") / v(x, "purchase_price"), PCT)
    w.link(r, 13, "senior.amort_years", fmt='0" yr amort"')
    r += 1
    for t in deal.tranches:
        w.label(r, 7, t.label)
        w.link(r, 10, f"{t.key}.amount", fmt=USD)
        w.link(r, 11, f"{t.key}.rate", fmt=PCT2)
        w.text(r, 13, MODE_LABEL[t.mode], size=9).alignment = Alignment(horizontal="right")
        r += 1
    debt = at("debt_at_close")
    w.label(r, 7, "Total debt at closing", bold=True)
    w.link(r, 10, "debt_at_close", fmt=USD, bold=True)
    w.formula(r, 12, f"{debt}/{total_uses}", lambda x: v(x, "debt_at_close") / v(x, "total_uses"), PCT,
              bold=True)
    w.text(r, 13, "of total cost", size=9, color=GREY_TEXT).alignment = Alignment(horizontal="right")
    w.shade_total(r, RIGHT)
    r += 1
    w.label(r, 7, "Equity at closing", bold=True)
    w.link(r, 10, "equity_at_close", fmt=USD, bold=True)
    w.formula(r, 12, f"{equity}/{total_uses}", lambda x: v(x, "equity_at_close") / v(x, "total_uses"), PCT,
              bold=True)
    r += 2
    w.sub(r, RIGHT, "Senior loan sizing")
    r += 1
    w.label(r, 7, "Sized by")
    if w.has("senior.assumed_balance"):
        w.label(r, 10, "Assumed loan")
    else:
        w.formula(r, 10, f'IF({at("senior.ltv_amount")}<={at("senior.dscr_amount")},"Max LTV","Min DSCR")',
                  lambda x: "Max LTV" if v(x, "senior.ltv_amount") <= v(x, "senior.dscr_amount") else "Min DSCR",
                  None)
    ws.cell(r, 10).alignment = Alignment(horizontal="right")
    r += 1
    w.label(r, 7, "Interest-only period")
    w.link(r, 10, "senior.io_months", fmt='0" months"')
    r += 1
    w.label(r, 7, "Year 1 DSCR (senior)")
    w.link(r, 10, "annual.dscr", 1, fmt=MULT)
    r += 1
    w.label(r, 7, "Debt yield (Year 1 NOI)")
    w.formula(r, 10, f"{at('year_1_noi')}/{at('senior.amount')}",
              lambda x: v(x, "year_1_noi") / v(x, "senior.amount"), PCT2)
    r += 1
    w.label(r, 7, "Refinance")
    w.formula(r, 10, f'IF({at("refi_included")}=1,{at("refi_month")},"None")',
              lambda x: v(x, "refi_month") if v(x, "refi_included") == 1 else "None", '"Month "0', link=True)
    ws.cell(r, 10).alignment = Alignment(horizontal="right")
    w.link(r, 11, "refi.rate", fmt=PCT2)
    w.formula(r, 12, f"IF({at('refi.value')}>0,{at('refi.amount')}/{at('refi.value')},0)",
              lambda x: v(x, "refi.amount") / v(x, "refi.value") if v(x, "refi.value") > 0 else Decimal(0), PCT)
    r += 1
    w.label(r, 7, "Refinance loan amount")
    w.link(r, 10, "refi.amount", fmt=USD)
    r += 1
    right_end = r

    # --- Business plan (left) | Exit (right) ------------------------------------------------
    top = max(left_end, right_end) + 1
    w.band(top, LEFT, "Business plan & key assumptions")
    r = top + 1
    scope = _cells_range(compiled, "reno_scope")
    plan = [
        ("Units to renovate", f"SUM({scope})", lambda x: total(x, "reno_scope"), INT, False),
        ("Average renovation cost per unit", f"IF(SUM({scope})>0,{at('reno_budget')}/SUM({scope}),0)",
         lambda x: v(x, "reno_budget") / total(x, "reno_scope") if total(x, "reno_scope") else Decimal(0), USD,
         False),
        ("Renovation starts (units per month)", f"SUM({_cells_range(compiled, 'reno_pace')})",
         lambda x: total(x, "reno_pace"), UNITS1, True),
        ("Market rent growth", at("market_growth"), lambda x: v(x, "market_growth"), PCT, True),
        ("In-place rents marked to market on turnover", at("mark_to_market"), lambda x: v(x, "mark_to_market"),
         '"Yes";"Yes";"No"', True),
        ("Renewal increase (capped by statute)", f"MIN({at('renewal_increase')},{at('rent_cap')})",
         lambda x: min(v(x, "renewal_increase"), v(x, "rent_cap")), PCT, False),
        ("Annual turnover", at("turnover"), lambda x: v(x, "turnover"), PCT, True),
        ("AMI limit growth", at("ami_growth"), lambda x: v(x, "ami_growth"), PCT, True),
        ("Economic vacancy floor", at("vacancy_floor"), lambda x: v(x, "vacancy_floor"), PCT, True),
        ("Bad debt", at("bad_debt_rate"), lambda x: v(x, "bad_debt_rate"), PCT, True),
        ("Replacement reserve ($/unit/yr)", at("replacement_reserve"), lambda x: v(x, "replacement_reserve"), USD,
         True),
        ("Capital paid at later events (refinance, sale)", at("deferred_capex_budget"),
         lambda x: v(x, "deferred_capex_budget"), USD, True),
    ]
    for text, formula, expect, fmt, is_link in plan:
        w.label(r, 2, text)
        w.formula(r, 3, formula, expect, fmt, link=is_link)
        r += 1
    w.label(r, 2, "Renovation downtime")
    w.text(r, 3, f"{deal.downtime_months} months").alignment = Alignment(horizontal="right")
    r += 1
    w.label(r, 2, "Property tax")
    w.text(r, 3, TAX_LABEL[deal.tax_method], size=9).alignment = Alignment(horizontal="left")
    r += 1
    left_end = r

    w.band(top, RIGHT, "Exit")
    r = top + 1
    exit_rows = [
        ("Sale month", sale, lambda x: v(x, "sale_month"), INT, True, False),
        ("Buyer's forward 12-month cash flow", at("sale.forward_ncf"), lambda x: v(x, "sale.forward_ncf"), USD,
         True, False),
        ("Exit cap rate", at("exit_cap_rate"), lambda x: v(x, "exit_cap_rate"), PCT2, True, False),
        ("Gross sale price", at("sale.price"), lambda x: v(x, "sale.price"), USD, True, True),
        ("Price per unit", f"{at('sale.price')}/{units}", lambda x: v(x, "sale.price") / v(x, "total_units"), USD,
         False, False),
        ("Selling costs and disposition fee", f"-({at('sale.costs')}+{at('sale.disposition_fee')})",
         lambda x: -(v(x, "sale.costs") + v(x, "sale.disposition_fee")), USD, False, False),
        ("Sale proceeds before debt repayment", at("sale.net_proceeds"), lambda x: v(x, "sale.net_proceeds"), USD,
         True, True),
        ("Loan payoffs at sale", f"-SUMPRODUCT({span('loan_payoffs')},{span('is_sale')})",
         lambda x: -_at_sale(x, "loan_payoffs"), USD, False, False),
        ("Reserves released", f"SUMPRODUCT({span('reserves_released')},{span('is_sale')})",
         lambda x: _at_sale(x, "reserves_released"), USD, False, False),
        ("Net proceeds to equity", f"SUMPRODUCT({span('capital_event_cash')},{span('is_sale')})",
         lambda x: _at_sale(x, "capital_event_cash"), USD, False, True),
    ]
    for text, formula, expect, fmt, is_link, bold in exit_rows:
        w.label(r, 7, text, bold=bold)
        w.formula(r, 10, formula, expect, fmt, bold=bold, link=is_link)
        if text == "Net proceeds to equity":
            w.shade_total(r, RIGHT, double=True)
        r += 1
    right_end = r

    # --- Partnership (left) | Sale price sensitivity (right) ---------------------------------
    top = max(left_end, right_end) + 1
    w.band(top, LEFT, "Partnership & sponsor economics")
    r = top + 1
    w.label(r, 2, "LP / GP share of capital")
    w.link(r, 3, "lp_share", fmt=PCT)
    w.formula(r, 4, f"1-{lp}", lambda x: 1 - v(x, "lp_share"), PCT)
    r += 1
    for name, text in (("pref_rate", "Preferred return (to LP)"), ("catch_up_share", "GP catch-up share (0 = none)"),
                       ("promote_1", "GP promote above the pref"),
                       ("hurdle_rate", "Second hurdle (LP IRR)"), ("promote_2", "GP promote above the hurdle"),
                       ("asset_management_fee_rate", "Asset management fee (of equity, annual)"),
                       ("disposition_fee_rate", "Disposition fee (of sale price)")):
        w.label(r, 2, text)
        w.link(r, 3, name, fmt=PCT2 if "promote" not in name else PCT)
        r += 1
    w.label(r, 2, "Acquisition fee")
    w.link(r, 3, "acquisition_fee", fmt=USD)
    r += 1
    w.label(r, 2, "GP promote earned", bold=True)
    w.link(r, 3, "gp_promote_total", fmt=USD, bold=True)
    r += 1
    w.label(r, 2, "Sponsor fees earned", bold=True)
    w.link(r, 3, "sponsor_fees", fmt=USD, bold=True)
    r += 1
    left_end = r

    w.band(top, RIGHT, "Sale price sensitivity")
    r = top + 1
    w.note(r, 7, "Gross sale price by exit cap rate (across) and forward cash flow (down). Live.")
    r += 1
    deltas = [Decimal("-0.005"), Decimal("-0.0025"), Decimal(0), Decimal("0.0025"), Decimal("0.005")]
    ncf_changes = [Decimal("-0.10"), Decimal("-0.05"), Decimal(0), Decimal("0.05"), Decimal("0.10")]
    cap, fwd = at("exit_cap_rate"), at("sale.forward_ncf")
    header_row = r
    w.text(r, 8, "Forward cash flow", bold=True, size=9).alignment = Alignment(horizontal="left")
    for j, d in enumerate(deltas):
        c = 9 + j
        w.formula(r, c, f"{cap}+({_lit(d)})", lambda x, d=d: v(x, "exit_cap_rate") + d, PCT2, bold=True)
        ws.cell(r, c).fill = PatternFill("solid", fgColor=BAND)
    r += 1
    for i, g in enumerate(ncf_changes):
        w.number(r, 7, float(g), '+0%;-0%;"Base"', bold=True).alignment = Alignment(horizontal="right")
        w.formula(r, 8, f"{fwd}*(1+G{r})", lambda x, g=g: v(x, "sale.forward_ncf") * (1 + g), USD)
        for j, d in enumerate(deltas):
            c = 9 + j
            hdr = f"{_col(c)}${header_row}"
            cell = w.formula(r, c, f"$H{r}/{hdr}",
                             lambda x, g=g, d=d: v(x, "sale.forward_ncf") * (1 + g) / (v(x, "exit_cap_rate") + d),
                             USD)
            if g == 0 and d == 0:
                cell.font = Font(name=FONT, size=10, bold=True)
                cell.fill = PatternFill("solid", fgColor=TOTAL)
        r += 1
    right_end = r

    # --- Return sensitivity (engine runs, static) --------------------------------------------
    top = max(left_end, right_end) + 1
    if sensitivity is not None:
        w.band(top, full, "Levered equity IRR sensitivity — exit cap rate × sale month")
        r = top + 1
        w.note(r, 2, "Each cell is a separate run of the model at build time. It does not update when inputs "
                     "change in this workbook; rebuild the workbook to refresh it.")
        r += 1
        w.text(r, 2, "Sale month  \\  Exit cap", bold=True)
        for j, capv in enumerate(sensitivity.exit_caps):
            w.number(r, 3 + j, float(capv), PCT2, bold=True).fill = PatternFill("solid", fgColor=BAND)
        r += 1
        base = (int(v(run, "sale_month")), v(run, "exit_cap_rate"))
        for m_ in sensitivity.sale_months:
            w.number(r, 2, m_, '"Month "0', bold=True).alignment = Alignment(horizontal="right")
            for j, capv in enumerate(sensitivity.exit_caps):
                irr = sensitivity.irr.get((m_, capv))
                cell = w.number(r, 3 + j, float(irr) if irr is not None else "n/a", PCT2, color="404040")
                if (m_, capv) == base:
                    cell.font = Font(name=FONT, size=10, bold=True)
                    cell.fill = PatternFill("solid", fgColor=TOTAL)
            r += 1
        top = r + 1

    # --- Unit mix -------------------------------------------------------------------------
    w.band(top, full, "Unit mix & affordability at closing",
           {3: "Regime", 4: "Units", 5: "Occupied", 6: "In-place rent", 7: "Market rent", 8: "Net limit / contract",
            9: "Year 1 rent", 10: "Units to renovate", 11: "Renovated rent", 12: "Renovation cost / unit"})
    ws.row_dimensions[top + 1].height = 26
    r = top + 2
    first_mix = r
    for c in deal.cohorts:
        w.label(r, 2, c.label)
        w.text(r, 3, REGIME_LABEL[c.regime], size=9).alignment = Alignment(horizontal="right")
        w.link(r, 4, "units", c.key, fmt=INT)
        w.link(r, 5, "occupied_at_close", c.key, fmt=INT)
        w.link(r, 6, "in_place_rent", c.key, fmt=USD)
        w.link(r, 7, "market_rent_now", c.unit_type, 1, fmt=USD)
        if c.regime == "restricted":
            w.link(r, 8, "rent_limit", c.key, 1, fmt=USD)
        elif c.regime == "contract":
            w.link(r, 8, "contract_rent", c.key, fmt=USD)
        w.link(r, 9, "classic_target", c.key, 1, fmt=USD)
        if c.renovate:
            w.link(r, 10, "reno_scope", c.key, fmt=INT)
            w.link(r, 11, "renovated_target", c.key, 1, fmt=USD)
            w.link(r, 12, "reno_cost", c.unit_type, fmt=USD)
        r += 1
    last_mix = r - 1
    w.label(r, 2, "Total / weighted average", bold=True)
    for col in (4, 5, 10):
        name = {4: "units", 5: "occupied_at_close", 10: "reno_scope"}[col]
        w.formula(r, col, f"SUM({_col(col)}{first_mix}:{_col(col)}{last_mix})",
                  lambda x, n=name: total(x, n), INT, bold=True)
    occ_rng, units_rng = f"E{first_mix}:E{last_mix}", f"D{first_mix}:D{last_mix}"
    # A fully vacant acquisition has no in-place rent to average.
    w.formula(r, 6, f"IF(SUM({occ_rng})>0,SUMPRODUCT(F{first_mix}:F{last_mix},{occ_rng})/SUM({occ_rng}),0)",
              lambda x: sum((v(x, "in_place_rent", c.key) * v(x, "occupied_at_close", c.key) for c in deal.cohorts),
                            Decimal(0)) / total(x, "occupied_at_close")
              if total(x, "occupied_at_close") else Decimal(0),
              USD, bold=True)
    for col, fn in ((7, lambda x, c: v(x, "market_rent_now", c.unit_type, 1)),
                    (9, lambda x, c: v(x, "classic_target", c.key, 1))):
        L = _col(col)
        w.formula(r, col, f"SUMPRODUCT({L}{first_mix}:{L}{last_mix},{units_rng})/SUM({units_rng})",
                  lambda x, fn=fn: sum((fn(x, c) * v(x, "units", c.key) for c in deal.cohorts), Decimal(0))
                  / total(x, "units"), USD, bold=True)
    w.shade_total(r, full)
    r += 1
    w.label(r, 2, "Restricted units required by the regulatory agreement")
    w.link(r, 4, "set_aside_units", fmt=INT)
    r += 1
    w.note(r, 2, "Rents are per unit per month. Net limit is the gross AMI limit less the utility allowance, grown "
                 "from closing; Year 1 rent is the lesser of market and the limit (or the contract rent).")
    r += 2

    if deal.commercial_spaces:
        r = _commercial_table(w, r, full)

    # --- Annual cash flow ------------------------------------------------------------------
    top = r
    w.band(top, full, "Annual cash flow")
    r = top + 1
    for k in years:
        col = 3 + k
        w.text(r, col, "Closing" if k == 0 else f"Year {k}", bold=True).alignment = Alignment(horizontal="right")
        w.number(r + 1, col, _serial(_add_months(deal.closing, 12 * k)), MONTH, size=9,
                 color=GREY_TEXT).alignment = Alignment(horizontal="right")
    w.text(r + 1, 2, "Period ending", size=9, color=GREY_TEXT)
    for c in range(2, last_col + 1):
        from openpyxl.styles import Border, Side
        ws.cell(r + 1, c).border = Border(bottom=Side(style="thin", color="808080"))
    r += 2
    strip_first = r
    tranche_names = [f"annual.{t.key}.payment" for t in deal.tranches]
    commercial = ("annual.commercial.income",) if deal.commercial_spaces else ()
    strip = [
        ("Gross potential rent", ("annual.gpr_total",), (), False),
        ("Vacancy, loss to lease, downtime & bad debt",
         ("annual.egi",), ("annual.gpr_total", "annual.other_income_total", *commercial), False),
        ("Other income", ("annual.other_income_total",), (), False),
        ("Commercial income (rent, recoveries, less credit loss)", commercial, (), False),
        ("Effective gross income", ("annual.egi",), (), True),
        ("Operating expenses incl. property tax", (), ("annual.opex_total",), False),
        ("Net operating income", ("annual.noi",), (), True),
        ("Replacement reserve", (), ("annual.replacement_reserve_deposit",), False),
        ("Capital spending", (), ("annual.capex_spend",), False),
        ("Commercial leasing costs (TI & LC)", (), ("annual.commercial.leasing_costs_total",) if commercial else (),
         False),
        ("Senior debt service", (), ("annual.senior_debt_service",), False),
        ("Subordinate debt payments", (), tuple(tranche_names), False),
        ("Asset management fee", (), ("annual.asset_management_fee",), False),
        ("Capital events (refinance, sale)", ("annual.capital_event_cash",), (), False),
        ("Equity contributions", (), ("annual.equity_contributions",), False),
        ("Levered cash flow to equity", ("annual.levered_cash_flow",), (), True),
        ("Unlevered cash flow", ("annual.unlevered_cash_flow",), (), False),
    ]
    for text, plus, minus, bold in strip:
        if not plus and not minus:
            continue
        w.label(r, 2, text, bold=bold)
        for k in years:
            terms = [f"+{at(n, k)}" for n in plus] + [f"-{at(n, k)}" for n in minus]
            formula = "".join(terms).lstrip("+")
            is_link = len(terms) == 1 and not minus
            w.formula(r, 3 + k, formula,
                      lambda x, k=k, p=plus, m_=minus: sum((v(x, n, k) for n in p), Decimal(0))
                      - sum((v(x, n, k) for n in m_), Decimal(0)),
                      USD, bold=bold, link=is_link)
        if bold:
            w.shade_total(r, full, double=text.startswith("Levered"))
        r += 1
    r += 1
    w.sub(r, full, "Operating metrics")
    r += 1
    for text, name, fmt in (("Average physical occupancy", "annual.occupancy", PCT),
                            ("Senior DSCR", "annual.dscr", MULT),
                            ("Cash-on-cash (operating distributions / equity)", "annual.cash_on_cash", PCT),
                            ("Renovation starts (units)", "annual.units_renovated", UNITS1)):
        w.label(r, 2, text)
        for k in years:
            if k == 0 and name != "annual.units_renovated":
                continue
            w.link(r, 3 + k, name, k, fmt=fmt)
        r += 1
    strip_last = r - 1
    # Years after the sale are the buyer's projection: shown, but greyed.
    grey = Font(name=FONT, size=10, color="A6A6A6")
    ws.conditional_formatting.add(
        f"D{strip_first}:{_col(last_col)}{strip_last}",
        FormulaRule(formula=[f"(COLUMN(D{strip_first})-3)*12>{_abs(sale)}+11"], font=grey))
    w.note(r, 2, "Years after the sale year are greyed: the property is projected on for the buyer's forward year, "
                 "but the partnership no longer owns it.")
    r += 2

    # --- Checks ------------------------------------------------------------------------------
    w.band(r, full, "Checks")
    r += 1
    min_dscr = at("senior.min_dscr")
    owned_years = ",".join(f"OR({at('annual.senior_debt_service', k)}<=0,{at('annual.dscr', k)}>={min_dscr})"
                           for k in years if k)
    checks = [
        ("Sources equal uses", f'IF(ABS(C{sources_row}-C{uses_row})<0.5,"OK","Review")', lambda x: "OK"),
        ("Senior DSCR at or above the minimum in every year", f'IF(AND({owned_years}),"OK","Review")',
         lambda x: "OK" if all(v(x, "annual.senior_debt_service", k) <= 0
                               or v(x, "annual.dscr", k) >= v(x, "senior.min_dscr") for k in years if k)
         else "Review"),
        ("Restricted units meet the regulatory set-aside",
         f'IF({at("restricted_units")}>={at("set_aside_units")},"OK","Review")',
         lambda x: "OK" if v(x, "restricted_units") >= v(x, "set_aside_units") else "Review"),
        ("No capital calls after closing", f'IF({at("capital_calls_after_close")}<=0,"OK","Review")',
         lambda x: "OK" if v(x, "capital_calls_after_close") <= 0 else "Review"),
        ("In-place restricted rents at or below the net limit",
         "IF(AND(" + ",".join(f"{at('in_place_rent', c.key)}<={at('rent_limit', c.key, 0)}"
                              for c in deal.cohorts if c.regime == "restricted") + '),"OK","Review")',
         lambda x: "OK" if all(v(x, "in_place_rent", c.key) <= v(x, "rent_limit", c.key, 0)
                               for c in deal.cohorts if c.regime == "restricted") else "Review"),
    ]
    first_check = r
    for text, formula, expect in checks:
        if "AND()" in formula:
            continue
        w.label(r, 2, text)
        w.formula(r, 3, formula, expect, None, bold=True)
        ws.cell(r, 3).alignment = Alignment(horizontal="center")
        r += 1
    red = Font(name=FONT, size=10, bold=True, color="C00000")
    green = Font(name=FONT, size=10, bold=True, color=LINK)
    ws.conditional_formatting.add(f"C{first_check}:C{r - 1}",
                                  FormulaRule(formula=[f'C{first_check}="Review"'], font=red,
                                              fill=PatternFill("solid", fgColor="FCE4D6")))
    ws.conditional_formatting.add(f"C{first_check}:C{r - 1}",
                                  FormulaRule(formula=[f'C{first_check}="OK"'], font=green))
    r += 1
    leases = ", Commercial Leases" if deal.commercial_spaces else ""
    w.note(r, 2, f"Blue = inputs (Assumptions, Unit Mix, Unit Types{leases} and Expenses sheets). Green = links to the "
                 "calculation sheets. Black = calculated here. Every figure recalculates when an input changes.")
    r += 1
    w.note(r, 2, "Detail: Annual Cash Flow, Monthly Cash Flow, Rental Projection, Debt Schedule and Partnership "
                 "Waterfall sheets. All dollar figures are nominal.")
    last_row = r

    # --- Print -------------------------------------------------------------------------------
    ws.print_area = f"A1:{_col(last_col + 1)}{last_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.oddFooter.left.text = f"{sponsor} · Confidential — for discussion purposes only" if CONFIDENTIAL else sponsor
    ws.oddFooter.right.text = "Page &P of &N"
    for part in (ws.oddFooter.left, ws.oddFooter.right):
        part.size = 8
    wb.active = 0
    return SHEET


def _commercial_table(w: _Writer, top: int, full: tuple[int, int]) -> int:
    """The commercial spaces and their leases, linked to the Commercial Leases sheet."""
    from openpyxl.styles import Alignment

    deal, v = w.deal, w.v
    w.band(top, full, "Commercial space",
           {3: "Lease", 4: "SF", 5: "Annual rent", 6: "Rent / SF", 7: "Expires (month)", 8: "Options exercised",
            9: "Renewal probability", 10: "Market rent / SF", 11: "Downtime (months)", 12: "Recovery share"})
    w.ws.row_dimensions[top + 1].height = 26
    r = first = top + 2
    for s in deal.commercial_spaces:
        w.label(r, 2, s.label)
        w.text(r, 3, "NNN" if s.lease_type == "nnn" else "Gross", size=9).alignment = Alignment(horizontal="right")
        w.number(r, 4, s.sf, INT)
        w.link(r, 5, "commercial.rent", s.key, fmt=USD)
        w.formula(r, 6, f"E{r}/D{r}", lambda x, s=s: v(x, "commercial.rent", s.key) / s.sf, USD2)
        w.link(r, 7, "commercial.expiry_month", s.key, fmt=INT)
        w.link(r, 8, "commercial.option_exercised", s.key, fmt='"Yes";"Yes";"No"')
        w.link(r, 9, "commercial.renewal_probability", s.key, fmt=PCT)
        w.link(r, 10, "commercial.market_rent", s.key, fmt=USD2)
        w.link(r, 11, "commercial.downtime_months", s.key, fmt=INT)
        if s.lease_type == "nnn":
            w.link(r, 12, "commercial.recovery_share", s.key, fmt=PCT)
        r += 1
    w.label(r, 2, "Total / average", bold=True)
    sf = sum(s.sf for s in deal.commercial_spaces)
    w.formula(r, 4, f"SUM(D{first}:D{r - 1})", lambda x: Decimal(sf), INT, bold=True)
    w.formula(r, 5, f"SUM(E{first}:E{r - 1})", lambda x: w.total(x, "commercial.rent"), USD, bold=True)
    w.formula(r, 6, f"E{r}/D{r}", lambda x: w.total(x, "commercial.rent") / sf, USD2, bold=True)
    w.shade_total(r, full)
    r += 1
    w.note(r, 2, "Each space is leased on its own terms, independent of apartment occupancy. Expiration is in months "
                 "after closing; exercised options extend the lease at its bumps. At rollover the space renews at "
                 "market with the renewal probability, otherwise it is dark for the downtime and re-leased at market.")
    return r + 2


# --- Helpers ----------------------------------------------------------------------------------

def _col(c: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(c)


def _abs(address: str) -> str:
    """`'Sheet'!C5` as `'Sheet'!$C$5`, for a conditional-format rule."""
    sheet, cell = address.rsplit("!", 1)
    letters = "".join(ch for ch in cell if ch.isalpha())
    return f"{sheet}!${letters}${cell[len(letters):]}"


def _cells_range(compiled: Compiled, name: str) -> str:
    """A variable's cells along one column, as a range (an input listed by item); 0 when it has none."""
    cells = list(compiled.cells[name].values())
    if not cells:
        return "0"
    sheets = {c.rsplit("!", 1)[0] for c in cells}
    if len(sheets) != 1:
        raise ValueError(f"{name} is not on one sheet.")
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
    at = [coordinate_from_string(c.rsplit("!", 1)[1]) for c in cells]
    rows = sorted(r for _, r in at)
    cols = sorted(column_index_from_string(c) for c, _ in at)
    sheet = sheets.pop()
    if len(set(cols)) == 1 and rows == list(range(rows[0], rows[0] + len(rows))):
        return f"{sheet}!{at[0][0]}{rows[0]}:{at[0][0]}{rows[-1]}"
    if len(set(rows)) == 1 and cols == list(range(cols[0], cols[0] + len(cols))):
        return f"{sheet}!{_col(cols[0])}{rows[0]}:{_col(cols[-1])}{rows[0]}"
    return ",".join(cells)


def _pos(run: Run, name: str) -> Decimal:
    return sum((x for x in run.values[name].values() if x > 0), Decimal(0))


def _neg(run: Run, name: str) -> Decimal:
    return sum((x for x in run.values[name].values() if x < 0), Decimal(0))


def _at_sale(run: Run, name: str) -> Decimal:
    return sum((run.values[name][i] * run.values["is_sale"][i] for i in run.values[name]), Decimal(0))


def _add_months(d: date, months: int) -> date:
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _lit(d: Decimal) -> str:
    return format(d.normalize(), "f")
