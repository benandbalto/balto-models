"""Run a deal and write its analyst workbook: live formulas, cached run values."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from balto_model_engine import evaluate
from balto_model_engine.workbook import Compiled, compile_workbook

from .deal import Deal
from .model import build_model
from .overview import SPONSOR, Sensitivity, write_overview
from .presentation import build_layout


def write_workbook(deal: Deal, inputs: Mapping[str, Any], path: str, *, sponsor: str = SPONSOR,
                   sensitivity: Sensitivity | None = None):
    """Evaluate the deal and save its workbook to `path`. Returns the model, run and compiled workbook."""
    model = build_model(deal)
    run = evaluate(model, inputs)
    compiled: Compiled = compile_workbook(model, run, build_layout(deal, sponsor))
    write_overview(compiled, run, deal, sponsor=sponsor, location=deal.location or None, sensitivity=sensitivity,
                   model_label=f"{run.model_id} {run.model_version} · run {run.digest[:12]}")
    _grey_after_sale(compiled, deal)
    _per_unit_columns(compiled, model, run)
    _validate_events(compiled)
    # The dimensions sheet is what attr() formulas read; it stays, out of the way.
    compiled.workbook["Dimensions"].sheet_state = "hidden"
    compiled.save(path)
    return model, run, compiled


def irr_sensitivity(deal: Deal, inputs: Mapping[str, Any], exit_caps: Sequence[Any], sale_months: Sequence[int],
                    metric: str = "levered_irr") -> Sensitivity:
    """`metric` for each exit cap rate and sale month, one engine run per cell."""
    model = build_model(deal)
    caps = [Decimal(str(c)) for c in exit_caps]
    irr = {}
    for month in sale_months:
        for cap in caps:
            result = evaluate(model, {**inputs, "sale_month": month, "exit_cap_rate": str(cap)})
            irr[(month, cap)] = result.metrics[metric].get("rate")
    return Sensitivity(caps, list(sale_months), irr)


def _grey_after_sale(compiled: Compiled, deal: Deal) -> None:
    """On the annual sheet, years after the sale year are the buyer's projection: greyed, not hidden."""
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    ws = compiled.workbook["Annual Cash Flow"]
    sale = compiled.cells["sale_month"][()]
    sheet, cell = sale.rsplit("!", 1)
    letters = "".join(ch for ch in cell if ch.isalpha())
    sale_abs = f"{sheet}!${letters}${cell[len(letters):]}"
    # Column C is closing and column D is Year 1.
    last = get_column_letter(3 + deal.horizon_years)
    ws.conditional_formatting.add(
        f"D1:{last}{ws.max_row}",
        FormulaRule(formula=[f"(COLUMN(D1)-3)*12>{sale_abs}+11"], font=Font(color="A6A6A6")))


def _validate_events(compiled: Compiled) -> None:
    """Excel refuses an event month that is not a whole month in range, and a refinance flag other than 0 or 1."""
    from openpyxl.worksheet.datavalidation import DataValidation

    for name in ("sale_month", "refi_month", "capex_start_month", "capex_months"):
        for address in compiled.cells.get(name, {}).values():
            sheet, cell = address.rsplit("!", 1)
            ws = compiled.workbook[sheet.strip("'")]
            dv = DataValidation(type="whole", operator="between", formula1="1", formula2="1000",
                                showErrorMessage=True, errorTitle="Whole months",
                                error="Event months are whole months after closing.")
            ws.add_data_validation(dv)
            dv.add(cell)
    for name in ("commercial.expiry_month", "commercial.option_months", "commercial.downtime_months"):
        for address in compiled.cells.get(name, {}).values():
            sheet, cell = address.rsplit("!", 1)
            ws = compiled.workbook[sheet.strip("'")]
            dv = DataValidation(type="whole", operator="between", formula1="0", formula2="1000",
                                showErrorMessage=True, errorTitle="Whole months", error="Lease months are whole months.")
            ws.add_data_validation(dv)
            dv.add(cell)
    switches = [((), "refi_included"), ((), "mark_to_market")]
    switches += [(idx, "commercial.option_exercised") for idx in compiled.cells.get("commercial.option_exercised", {})]
    for idx, name in switches:
        sheet, cell = compiled.cells[name][idx].rsplit("!", 1)
        ws = compiled.workbook[sheet.strip("'")]
        dv = DataValidation(type="list", formula1='"0,1"', showErrorMessage=True, errorTitle="Switch",
                            error="1 for yes, 0 for no.")
        ws.add_data_validation(dv)
        dv.add(cell)


def _per_unit_columns(compiled: Compiled, model, run) -> None:
    """Beside the pro forma's dollar columns, the same figures per unit per year, as live formulas."""
    from copy import copy

    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    ws = compiled.workbook["Pro Forma"]
    cases = model.dimensions["pf_case"].keys()
    units = compiled.cells["total_units"][()]
    first = 3  # column C holds the first case
    gap = first + len(cases)
    offset = len(cases) + 1
    header = ws.cell(1, first)
    for i, case in enumerate(cases):
        cell = ws.cell(1, first + offset + i)
        cell.value = f"{model.dimensions['pf_case'].item(case).attrs['label']} $/unit"
        cell.font, cell.fill = copy(header.font), copy(header.fill)
        cell.alignment = Alignment(horizontal="right", wrap_text=True)
        ws.column_dimensions[get_column_letter(first + offset + i)].width = 14
    ws.cell(1, gap).fill = copy(header.fill)
    ws.column_dimensions[get_column_letter(gap)].width = 2
    ws.row_dimensions[1].height = 30
    for row in range(2, ws.max_row + 1):
        source = ws.cell(row, first + len(cases) - 1)
        for i in range(len(cases) + 1):
            target = ws.cell(row, gap + i)
            if source.fill is not None and source.fill.fgColor.rgb not in (None, "00000000"):
                target.fill = copy(source.fill)
            target.border = copy(source.border)
    for name, var in model.variables.items():
        if not name.startswith("pf.") or var.unit != "usd":
            continue
        for idx, address in compiled.cells[name].items():
            sheet, coord = address.rsplit("!", 1)
            dollars = ws[coord]
            case = idx[var.dims.index("pf_case")]
            cell = ws.cell(dollars.row, first + offset + cases.index(case))
            compiled.derive(cell, f"{coord}/{units}",
                            lambda r, n=name, i=idx: r.values[n][i] / r.values["total_units"][()], run)
            cell.number_format = '#,##0;(#,##0);"-"'
            cell.font = Font(name="Arial", size=10, bold=bool(dollars.font and dollars.font.bold))
