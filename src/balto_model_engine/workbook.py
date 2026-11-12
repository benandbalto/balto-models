"""Compile a model and its run to an Excel workbook with live formulas.

Every calculation becomes an Excel formula written from its expression, with
the run's value cached in the cell, so the workbook shows the run in any
reader and recalculates when an analyst flexes an input. Inputs and sources
are constants. Nothing is transcribed: an expression the compiler cannot write
as a formula refuses the compile rather than leaving a value in its place.

Layout is data: each sheet names its variables and, optionally, the dimension
laid across its columns (usually `month`). A variable occupies one row per item
of its other dimensions. `allocate_round` adds helper rows beneath its
variable that carry the largest-remainder allocation in formulas. A sheet may
also carry presentation: headings, labels, number formats, total rows, and
`XIRR` cells for the model's declared metrics.

`openpyxl` is imported lazily so the engine itself stays dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable
from xml.sax.saxutils import escape as xml_escape
import re
import zipfile

from .evaluate import Run, _Evaluator, _IndexSchedule, _key
from .expressions import (
    AllocateRound, Attr, Binary, Compare, Const, Expr, Extreme, If, Lag, Mapped, Matches, Neg, Power, Previous,
    Prior, Ref, Round, Sum, SumWithin,
)
from .model import Model

# Excel refuses a formula longer than this many characters.
MAX_FORMULA = 8192
FIRST_VALUE_COLUMN = 3  # A: label, B: unit
# Font colours: an input typed in, a formula reading another sheet.
INPUT, LINK = "0000FF", "008000"
_SHEET_NAME = re.compile(r"^[^\[\]:*?/\\']{1,31}$")
_SINGLE_SUM = re.compile(r"^SUM\([^()]*\)$")


class CompileError(Exception):
    """The model or layout cannot be written as a workbook of formulas."""


@dataclass(frozen=True)
class Row:
    """A variable's rows, with a label, an Excel number format, and total styling."""
    variable: str
    label: str | None = None
    format: str | None = None
    total: bool = False
    # Only the items whose attributes match, so one variable can be shown in groups
    # (each item still placed exactly once). An empty label shows the item labels alone.
    where: dict | None = None


@dataclass(frozen=True)
class Heading:
    text: str


@dataclass(frozen=True)
class MetricRow:
    """A declared XIRR metric as a live `XIRR` over its flows' row and the dates above it."""
    metric: str
    label: str | None = None
    format: str = "0.00%"


@dataclass(frozen=True)
class Sheet:
    name: str
    # Variable names, or Row, Heading and MetricRow entries.
    variables: tuple
    columns: str | None = None


# Number formats by a variable's unit, unless a row states its own.
UNIT_FORMATS = {
    "usd": '#,##0;(#,##0);"-"',
    "usd/unit": '#,##0;(#,##0);"-"',
    "usd/unit-month": '#,##0;(#,##0);"-"',
    "usd/unit-year": '#,##0;(#,##0);"-"',
    "rate": '0.00%;(0.00%);"-"',
    "rate/year": '0.00%;(0.00%);"-"',
    "ratio": '0.00"x"',
    "units": '#,##0.0;(#,##0.0);"-"',
    "month": "0",
    "flag": "0",
}


@dataclass(frozen=True)
class Layout:
    sheets: tuple[Sheet, ...]
    formats: dict | None = None
    # How each unit is shown in the unit column; a unit not named shows as itself.
    units: dict | None = None
    font: str = "Arial"
    # Printed on every page: the header centred, the footer on the left beside the sheet and page.
    header: str | None = None
    footer: str | None = None


@dataclass
class Compiled:
    """The workbook and where every figure lives, as `'Sheet'!C5` by variable and item."""
    workbook: Any
    cells: dict[str, dict[tuple, str]] = field(default_factory=dict)
    # Each placed metric's cell.
    metrics: dict[str, str] = field(default_factory=dict)
    # Presentation formulas written outside the layout (a cover sheet, say), each
    # with what it must show for a run, so parity checks them too.
    derived: dict[str, Callable[[Run], Any]] = field(default_factory=dict)

    def save(self, path: str) -> str:
        """Save, then cache the run's value in every formula cell."""
        self.workbook.save(path)
        _cache_values(path, self.workbook, self._cached)
        return path

    def derive(self, cell, formula: str, expect: Callable[[Run], Any], run: Run) -> None:
        """Write `formula` into `cell`; it must show `expect(run)` (a number or text) for any run."""
        cell.value = "=" + formula
        if isinstance(cell.value, str) and len(cell.value) > MAX_FORMULA:
            raise CompileError(f"{cell.coordinate}: the formula exceeds Excel's {MAX_FORMULA} characters.")
        self.derived[_address(cell.parent.title, cell.row, cell.column)] = expect
        self._cached[(cell.parent.title, cell.coordinate)] = expect(run)

    _cached: dict[tuple[str, str], Decimal] = field(default_factory=dict)


def default_layout(model: Model, columns: str | None = "month") -> Layout:
    """Sources, inputs and calculations on their own sheets, each split by whether it runs across `columns`."""
    if columns is not None and columns not in model.dimensions:
        columns = None
    sheets = []
    for kind, title in (("source", "Sources"), ("input", "Inputs"), ("calculation", "Calculations")):
        names = [v.name for v in model.variables.values() if v.kind == kind]
        across = tuple(n for n in names if columns in model.variables[n].dims)
        flat = tuple(n for n in names if n not in across)
        if flat:
            sheets.append(Sheet(title, flat))
        if across:
            sheets.append(Sheet(f"{title} by {columns}", across, columns))
    return Layout(tuple(sheets))


def compile_workbook(model: Model, run: Run, layout: Layout | None = None, *,
                     include_checks: bool = False) -> Compiled:
    if (run.model_id, run.model_version) != (model.model_id, model.version):
        raise CompileError("The run is not a run of this model.")
    layout = layout or default_layout(model)
    compiler = _Compiler(model, run, layout)
    compiled = compiler.compile()
    if include_checks:
        compiler.write_checks(compiled)
    return compiled


class _Compiler:
    def __init__(self, model: Model, run: Run, layout: Layout) -> None:
        self.model, self.run, self.layout = model, run, layout
        self.ev = _Evaluator(model, run.values, _IndexSchedule(model))
        self.cells: dict[str, dict[tuple, tuple[str, int, int]]] = {}
        self.attr_cells: dict[tuple[str, Any, str], tuple[str, int, int]] = {}
        self.sheet_columns: dict[str, str | None] = {}
        # Helper rows for each allocation group: (node id, outer env) -> row positions.
        self.allocations: dict[tuple, dict[str, Any]] = {}
        self.cached: dict[tuple[str, str], Decimal] = {}

    # --- Layout ------------------------------------------------------------

    def write_checks(self, compiled: Compiled) -> None:
        """Expose the model's rules and input bounds as live pass/fail formulas."""
        if 'Checks' in self.wb.sheetnames:
            raise CompileError('Checks is reserved for generated validation rules.')
        ws = self.wb.create_sheet('Checks')
        ws.append(['Rule', 'Index', 'Passed (1=yes, 0=no)', 'Meaning'])
        # Track appended rows locally: openpyxl's max_row rescans every cell.
        row = 1
        rules = [(c.name, c.dims, c.where, c.condition, c.message) for c in self.model.checks]
        for name, dims, where, condition, message in rules:
            for idx in self.ev.indices.indices(dims, where):
                env = dict(zip(dims, idx))
                ws.append([name, str(idx), None, message])
                row += 1
                formula = f'IFERROR(IF({self._condition(condition, env, "Checks")},1,0),0)'
                compiled.derive(ws.cell(row, 3), formula,
                    lambda r, c=condition, e=env: int(_Evaluator(self.model, r.values, self.ev.indices).truth(c, e)),
                    self.run)
        for name, var in self.model.variables.items():
            if var.kind != 'input':
                continue
            for idx, address in compiled.cells[name].items():
                terms = [f'ISNUMBER({address})']
                if var.minimum is not None:
                    terms.append(f'{address}>={var.minimum}')
                if var.maximum is not None:
                    terms.append(f'{address}<={var.maximum}')
                ws.append([name, str(idx), None, 'Input must be numeric and within its declared bounds.'])
                row += 1
                compiled.derive(ws.cell(row, 3),
                    f'IFERROR(IF(AND({",".join(terms)}),1,0),0)', lambda r: 1, self.run)
        ws.freeze_panes = 'C2'
        ws.auto_filter.ref = ws.dimensions
        for column, width in [('A', 55), ('B', 24), ('C', 24), ('D', 80)]:
            ws.column_dimensions[column].width = width

    def compile(self) -> Compiled:
        from openpyxl import Workbook
        from openpyxl.workbook.properties import CalcProperties

        self._check_layout()
        # Every variable has a placement, though one with no items has no cells.
        self.cells = {name: {} for name in self.model.variables}
        wb = Workbook()
        wb.remove(wb.active)
        self.wb = wb
        dims_sheet = wb.create_sheet("Dimensions")
        self._write_dimensions(dims_sheet)
        placed: list[tuple[Any, str, tuple]] = []
        metric_rows: list[tuple[Any, int, MetricRow]] = []
        self.formats: dict[tuple[str, str, tuple], tuple[str | None, bool]] = {}
        for spec in self.layout.sheets:
            ws = wb.create_sheet(spec.name)
            self.sheet_columns[spec.name] = spec.columns
            row = self._write_header(ws, spec)
            for entry in spec.variables:
                if isinstance(entry, Heading):
                    row += 1 if row > self._first_row(spec) else 0
                    self._heading(ws, row, entry.text, spec)
                    row += 1
                    continue
                if isinstance(entry, MetricRow):
                    metric_rows.append((ws, row, entry))
                    row += 1
                    continue
                entry = entry if isinstance(entry, Row) else Row(entry)
                name = entry.variable
                var = self.model.variables[name]
                other = tuple(d for d in var.dims if d != spec.columns)
                other_idx = self.ev.indices.indices(other, var.where if len(var.dims) == 1 else ())
                if entry.where:
                    other_idx = [o for o in other_idx if self._matches(other, o, entry.where)]
                for oidx in other_idx:
                    label = name if entry.label is None else entry.label
                    # A group narrowed to one item by its label needs no item suffix.
                    if oidx and not (entry.where and entry.label and len(other_idx) == 1):
                        items = ", ".join(self._item_label(d, k) for d, k in zip(other, oidx))
                        label = f"{label} · {items}" if label else items
                    _text(ws.cell(row, 1), label)
                    _text(ws.cell(row, 2), (self.layout.units or {}).get(var.unit, var.unit))
                    self._style_label(ws, row, entry.total, spec)
                    env_other = dict(zip(other, oidx))
                    if spec.columns in var.dims:
                        keys = self.model.dimensions[spec.columns].keys(var.where if other == () else ())
                        for key in keys:
                            env = {**env_other, spec.columns: key}
                            idx = tuple(env[d] for d in var.dims)
                            self._place(name, idx, (spec.name, row, self._column(spec.columns, key)))
                            placed.append((ws, name, idx))
                    else:
                        idx = tuple(env_other[d] for d in var.dims)
                        self._place(name, idx, (spec.name, row, FIRST_VALUE_COLUMN))
                        placed.append((ws, name, idx))
                    fmt = entry.format or self._formats().get(var.unit)
                    self.formats[name] = (fmt, entry.total)
                    row += 1
                # Helper rows for this variable's allocations follow it.
                if not entry.where:
                    row = self._reserve_helpers(name, row)
            self._finish_sheet(ws, spec)
        for name, values in self.run.values.items():
            if set(self.cells[name]) != set(values):
                raise CompileError(f"The layout does not place every item of {name} exactly once.")
        for ws, name, idx in placed:
            self._write_value(ws, name, idx)
        self._write_helpers()
        metrics = {m.metric: self._write_metric(ws, row, m) for ws, row, m in metric_rows}
        # The dimensions are reference; the presentation comes first.
        wb.move_sheet("Dimensions", offset=len(wb.sheetnames) - 1)
        wb.calculation = CalcProperties(fullCalcOnLoad=True)
        compiled = Compiled(wb, {n: {i: _address(*c) for i, c in cs.items()} for n, cs in self.cells.items()},
                            metrics)
        compiled._cached = self.cached
        return compiled

    def _font(self, **style):
        from openpyxl.styles import Font
        return Font(name=self.layout.font, size=style.pop("size", 10), **style)

    def _formats(self) -> dict:
        return {**UNIT_FORMATS, **(self.layout.formats or {})}

    def _check_layout(self) -> None:
        seen: dict[str, str] = {}
        grouped_names: dict[str, bool] = {}
        names = set()
        metrics: set[str] = set()
        for spec in self.layout.sheets:
            if not _SHEET_NAME.match(spec.name) or spec.name == "Dimensions" or spec.name in names:
                raise CompileError(f"Sheet name {spec.name!r} is not a valid, unique Excel sheet name.")
            names.add(spec.name)
            if spec.columns is not None and spec.columns not in self.model.dimensions:
                raise CompileError(f"Sheet {spec.name}: {spec.columns} is not a dimension.")
            for entry in spec.variables:
                if isinstance(entry, Heading):
                    continue
                if isinstance(entry, MetricRow):
                    if entry.metric not in self.model.metrics or entry.metric in metrics:
                        raise CompileError(f"Sheet {spec.name}: {entry.metric} is not a declared metric "
                                           "placed once.")
                    metrics.add(entry.metric)
                    continue
                name = entry.variable if isinstance(entry, Row) else entry
                var = self.model.variables.get(name)
                if var is None:
                    raise CompileError(f"Sheet {spec.name} names undeclared variable {name}.")
                grouped = isinstance(entry, Row) and bool(entry.where)
                if name in seen and not (grouped and grouped_names.get(name)):
                    raise CompileError(f"{name} is placed on both {seen[name]} and {spec.name}.")
                grouped_names[name] = grouped
                if spec.columns is not None and var.dims and spec.columns not in var.dims:
                    raise CompileError(f"{name} does not run across {spec.columns}, the columns of {spec.name}.")
                seen[name] = spec.name
        # A variable whose filter matches no item (an input for a method no line uses) has nothing to place.
        missing = [n for n in self.model.variables if n not in seen and self.run.values.get(n)]
        if missing:
            raise CompileError(f"The layout does not place {', '.join(missing)}.")

    def _matches(self, dims: tuple, idx: tuple, where: dict) -> bool:
        """Whether every attribute in `where` is held by one of the items of `idx`."""
        items = [self.model.dimensions[d].item(k) for d, k in zip(dims, idx)]
        return all(any(i.attrs.get(a) == v for i in items) for a, v in where.items())

    def _place(self, name: str, idx: tuple, cell: tuple) -> None:
        if idx in self.cells[name]:
            raise CompileError(f"{_key(name, idx)} is placed twice.")
        self.cells[name][idx] = cell

    def _item_label(self, dim: str, key: Any) -> str:
        label = self.model.dimensions[dim].item(key).attrs.get("label")
        return label if isinstance(label, str) else str(key)

    def _first_row(self, spec: Sheet) -> int:
        return self._header_rows[spec.name]

    def _last_column(self, spec: Sheet) -> int:
        return FIRST_VALUE_COLUMN + (len(self.model.dimensions[spec.columns].items) - 1 if spec.columns else 0)

    def _heading(self, ws, row: int, text: str, spec: Sheet) -> None:
        from openpyxl.styles import PatternFill

        _text(ws.cell(row, 1), text)
        for col in range(1, self._last_column(spec) + 1):
            cell = ws.cell(row, col)
            cell.font = self._font(bold=True, color="1F3864")
            cell.fill = PatternFill("solid", fgColor="D9E1F2")

    def _style_label(self, ws, row: int, total: bool, spec: Sheet) -> None:
        from openpyxl.styles import Alignment, Border, PatternFill, Side

        ws.cell(row, 2).font = self._font(color="808080", size=9)
        ws.cell(row, 1).font = self._font(bold=total)
        if total:
            # A total reads across its whole row: shaded, with a rule above.
            for col in range(1, self._last_column(spec) + 1):
                ws.cell(row, col).fill = PatternFill("solid", fgColor="F2F2F2")
                ws.cell(row, col).border = Border(top=Side(style="thin", color="808080"))
        else:
            ws.cell(row, 1).alignment = Alignment(indent=1)

    def _finish_sheet(self, ws, spec: Sheet) -> None:
        ws.column_dimensions["A"].width = 46
        ws.column_dimensions["B"].width = 13
        if spec.columns is None:
            ws.column_dimensions[_column_letter(FIRST_VALUE_COLUMN)].width = 18
        else:
            for i in range(len(self.model.dimensions[spec.columns].items)):
                ws.column_dimensions[_column_letter(FIRST_VALUE_COLUMN + i)].width = 13
        ws.freeze_panes = ws.cell(self._header_rows[spec.name], FIRST_VALUE_COLUMN)
        ws.sheet_view.showGridLines = False
        # Landscape; a sheet of a few columns fits one page wide, a long timeline
        # prints across pages with its labels and header repeated.
        ws.page_setup.orientation = "landscape"
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
        ws.page_setup.fitToWidth = 1 if self._last_column(spec) <= 16 else 0
        ws.print_title_rows = f"1:{self._header_rows[spec.name] - 1}"
        ws.print_title_cols = "A:B"
        ws.print_options.gridLines = False
        if self.layout.header:
            ws.oddHeader.center.text = self.layout.header
            ws.oddHeader.center.font = f"{self.layout.font},Bold"
        ws.oddFooter.left.text = self.layout.footer or ""
        ws.oddFooter.center.text = "&A"
        ws.oddFooter.right.text = "Page &P of &N"
        for part in (ws.oddFooter.left, ws.oddFooter.center, ws.oddFooter.right):
            part.size = 8

    def _write_metric(self, ws, row: int, entry: MetricRow) -> str:
        """`XIRR` over the flows' row and the date header row of the sheet that carries them."""
        from openpyxl.styles import Alignment

        metric = self.model.metrics[entry.metric]
        cells = self.cells[metric.flows]
        keys = self.model.dimensions[metric.dim].keys()
        first, last = cells[(keys[0],)], cells[(keys[-1],)]
        dates = [self.attr_cells.get((metric.dim, k, metric.date_attr, first[0])) for k in keys]
        if self.sheet_columns.get(first[0]) != metric.dim or None in dates:
            raise CompileError(f"{entry.metric}: its flows must lie across a sheet of {metric.dim} with "
                               f"{metric.date_attr} in the header.")
        here = ws.title
        _text(ws.cell(row, 1), entry.label or entry.metric)
        _text(ws.cell(row, 2), (self.layout.units or {}).get("rate", "rate"))
        ws.cell(row, 2).font = self._font(color="808080", size=9)
        cell = ws.cell(row, FIRST_VALUE_COLUMN)
        result = self.run.metrics.get(entry.metric, {})
        self._formula(cell, f"XIRR({_range(first[0], first[1], first[2], last[1], last[2], here=here)},"
                            f"{_range(*dates[0], dates[-1][1], dates[-1][2], here=here)})",
                      result.get("rate"), entry.metric)
        cell.number_format = entry.format
        cell.font = self._font(bold=True, color=LINK if "!" in cell.value else None)
        ws.cell(row, 1).font = self._font()
        ws.cell(row, 1).alignment = Alignment(indent=1)
        return _address(here, row, FIRST_VALUE_COLUMN)

    def _column(self, dim: str, key: Any) -> int:
        return FIRST_VALUE_COLUMN + self.model.dimensions[dim].position(key)

    def _write_dimensions(self, ws) -> None:
        """Every dimension's items and numeric attributes, which `attr()` reads."""
        row = 1
        for dim in self.model.dimensions.values():
            attrs = sorted({k for i in dim.items for k, v in i.attrs.items() if _numeric(v)})
            _text(ws.cell(row, 1), dim.name)
            for c, name in enumerate(attrs):
                _text(ws.cell(row, 2 + c), name)
            row += 1
            for item in dim.items:
                _text(ws.cell(row, 1), str(item.key))
                for c, name in enumerate(attrs):
                    if name in item.attrs:
                        ws.cell(row, 2 + c, int(item.attrs[name]) if isinstance(item.attrs[name], int)
                                else float(item.attrs[name]))
                        self.attr_cells[(dim.name, item.key, name)] = ("Dimensions", row, 2 + c)
                row += 1
            row += 1

    def _write_header(self, ws, spec: Sheet) -> int:
        from openpyxl.styles import Alignment, PatternFill

        if not hasattr(self, "_header_rows"):
            self._header_rows: dict[str, int] = {}
        band = PatternFill("solid", fgColor="1F3864")
        white = self._font(bold=True, color="FFFFFF")
        _text(ws.cell(1, 1), spec.name)
        _text(ws.cell(1, 2), "Unit")
        if spec.columns is None:
            _text(ws.cell(1, FIRST_VALUE_COLUMN), "Value")
            for col in range(1, FIRST_VALUE_COLUMN + 1):
                ws.cell(1, col).font, ws.cell(1, col).fill = white, band
            self._header_rows[spec.name] = 2
            return 2
        dim = self.model.dimensions[spec.columns]
        for col in (1, 2):
            ws.cell(1, col).font, ws.cell(1, col).fill = white, band
        for item in dim.items:
            cell = ws.cell(1, self._column(dim.name, item.key))
            _text(cell, self._item_label(dim.name, item.key))
            cell.font, cell.fill = white, band
            cell.alignment = Alignment(horizontal="right")
        # Numeric attributes repeat as header rows, so attr() reads the column's own header.
        # A date shows first; the rest are grouped beneath it.
        attrs = sorted({k for i in dim.items for k, v in i.attrs.items() if _numeric(v)},
                       key=lambda a: (a != "date", a))
        grey = self._font(color="808080", size=9)
        for r, name in enumerate(attrs, start=2):
            _text(ws.cell(r, 1), "Period ending" if name == "date" else f"{dim.name}.{name}")
            ws.cell(r, 1).font = grey
            if name != "date":
                ws.row_dimensions[r].outlineLevel = 1
                ws.row_dimensions[r].hidden = True
            for item in dim.items:
                if name in item.attrs:
                    col = self._column(dim.name, item.key)
                    cell = ws.cell(r, col, int(item.attrs[name]) if isinstance(item.attrs[name], int)
                                   else float(item.attrs[name]))
                    cell.font = grey
                    if name == "date":
                        cell.number_format = "mmm-yy"
                    self.attr_cells[(dim.name, item.key, name, spec.name)] = (spec.name, r, col)
        self._header_rows[spec.name] = 2 + len(attrs)
        return 2 + len(attrs)

    # --- Values and formulas ------------------------------------------------

    def _write_value(self, ws, name: str, idx: tuple) -> None:
        from openpyxl.styles import PatternFill

        var = self.model.variables[name]
        sheet, row, col = self.cells[name][idx]
        cell = ws.cell(row, col)
        value = self.run.values[name][idx]
        if var.kind == "calculation":
            formula = self._emit(var.expr, dict(zip(var.dims, idx)), sheet)[0]
            self._formula(cell, formula, value, f"{name}{list(idx) or ''}")
            # Blue is typed in, green comes from another sheet, black is worked out here.
            color = LINK if "!" in formula else None
        else:
            cell.value = _number(value)
            color = INPUT
            if var.kind != "input":
                cell.fill = PatternFill("solid", fgColor="EDEDED")
        fmt, total = getattr(self, "formats", {}).get(name, (None, False))
        if fmt:
            cell.number_format = fmt
        cell.font = self._font(bold=total, color=color)

    def _formula(self, cell, formula: str, value: Decimal | None, owner: str) -> None:
        text = "=" + formula
        if len(text) > MAX_FORMULA:
            raise CompileError(f"{owner}: the formula exceeds Excel's {MAX_FORMULA} characters.")
        cell.value = text
        if value is not None:
            self.cached[(cell.parent.title, cell.coordinate)] = value

    def _emit(self, e: Expr, env: dict[str, Any], here: str) -> tuple[str, int]:
        """The Excel text of `e` at one cell, with its precedence (higher binds tighter)."""
        if isinstance(e, Const):
            text = _literal(e.value)
            return (text, 9) if e.value >= 0 else (f"(-{text})", 9)
        if isinstance(e, Ref):
            return self._ref(e.name, env, here), 9
        if isinstance(e, Prior):
            dim = self.model.dimensions[e.dim]
            prev = dim.items[dim.position(env[e.dim]) - 1].key
            return self._ref(e.name, {**env, e.dim: prev}, here), 9
        if isinstance(e, Lag):
            dim = self.model.dimensions[e.dim]
            at = dim.position(env[e.dim])
            if at == 0:
                return self._emit(e.initial, env, here)
            return self._ref(e.name, {**env, e.dim: dim.items[at - 1].key}, here), 9
        if isinstance(e, Previous):
            if self.model.dimensions[e.dim].position(env[e.dim]) == 0:
                return self._emit(e.initial, env, here)
            return self._emit(e.step, env, here)
        if isinstance(e, Binary):
            prec = Binary.PRECEDENCE[e.op]
            left, lp = self._emit(e.left, env, here)
            right, rp = self._emit(e.right, env, here)
            left = f"({left})" if lp < prec else left
            right = f"({right})" if rp < prec or (rp == prec and e.op in "-/") else right
            return f"{left}{e.op}{right}", prec
        if isinstance(e, Neg):
            inner, p = self._emit(e.operand, env, here)
            return f"-({inner})" if p < 9 else f"-{inner}", 3
        if isinstance(e, Power):
            return f"POWER({self._emit(e.base, env, here)[0]},{self._emit(e.exponent, env, here)[0]})", 9
        if isinstance(e, Extreme):
            args = ",".join(self._emit(a, env, here)[0] for a in e.args)
            return f"{e.op.upper()}({args})", 9
        if isinstance(e, Attr):
            key = self.ev.key(e.dim, env)
            cell = self.attr_cells.get((e.dim, key, e.name, here)) or self.attr_cells[(e.dim, key, e.name)]
            return _address(*cell, here=here), 9
        if isinstance(e, If):
            if isinstance(e.condition, Matches):
                # Attributes are structure: the branch is chosen per cell.
                return self._emit(e.then if self.ev.truth(e.condition, env) else e.otherwise, env, here)
            cond = self._condition(e.condition, env, here)
            return (f"IF({cond},{self._emit(e.then, env, here)[0]},{self._emit(e.otherwise, env, here)[0]})", 9)
        if isinstance(e, Sum):
            keys = self.model.dimensions[e.dim].keys(e.where)
            return self._sum([(e.body, {**env, e.dim: k}, 1) for k in keys], here), 9
        if isinstance(e, SumWithin):
            dim = self.model.dimensions[e.dim]
            parent = self.ev.key(dim.parent, env)
            keys = dim.keys(e.where + ((dim.parent, parent),))
            return self._sum([(e.body, {**env, e.dim: k}, 1) for k in keys], here), 9
        if isinstance(e, Mapped):
            mapping = self.model.mappings[e.mapping]
            return self._sum([(e.body, {**env, mapping.dim: k}, s) for k, s in mapping.items_for(e.target)],
                             here), 9
        if isinstance(e, Round):
            # Guard the rounding boundary against accumulated binary noise,
            # retaining eight extra decimal places beyond the requested unit.
            return f"ROUND(ROUND({self._emit(e.body, env, here)[0]},{e.places + 8}),{e.places})", 9
        if isinstance(e, AllocateRound):
            return self._allocated(e, env, here), 9
        raise CompileError(f"The compiler cannot express {type(e).__name__}.")

    def _condition(self, c, env: dict[str, Any], here: str) -> str:
        if isinstance(c, Matches):
            return "TRUE" if self.ev.truth(c, env) else "FALSE"
        if isinstance(c, Compare):
            return f"{self._emit(c.left, env, here)[0]}{c.op}{self._emit(c.right, env, here)[0]}"
        raise CompileError(f"The compiler cannot express condition {type(c).__name__}.")

    def _ref(self, name: str, env: dict[str, Any], here: str) -> str:
        dims = self.model.variables[name].dims
        idx = tuple(self.ev.key(d, env) for d in dims)
        cell = self.cells.get(name, {}).get(idx)
        if cell is None:
            raise CompileError(f"{_key(name, idx)} is referenced but has no cell.")
        return _address(*cell, here=here)

    def _sum(self, terms: list[tuple[Expr, dict, int]], here: str) -> str:
        if not terms:
            return "0"
        plain = all(isinstance(b, Ref) and s == 1 for b, _, s in terms)
        if plain:
            cells = [self.cells[b.name][tuple(self.ev.key(d, env) for d in self.model.variables[b.name].dims)]
                     for b, env, _ in terms]
            span = _contiguous(cells)
            if span is not None:
                return f"SUM({_range(*span, here=here)})"
            parts = [_address(*c, here=here) for c in cells]
            # SUM takes at most 255 arguments; the chunks are one term, so they are grouped.
            chunks = [f"SUM({','.join(parts[i:i + 255])})" for i in range(0, len(parts), 255)]
            return chunks[0] if len(chunks) == 1 else f"({'+'.join(chunks)})"
        # A sum of a sum or difference is the sum or difference of the sums, so
        # each side can still be a range.
        first = terms[0][0]
        if (isinstance(first, Sum) and all(b is first and s == 1 for b, _, s in terms)):
            # Sum each inner item across the outer periods. This preserves
            # range compression for a facility-by-month rectangle.
            parts = [self._sum([(first.body, {**env, first.dim: key}, 1) for _, env, _ in terms], here)
                     for key in self.model.dimensions[first.dim].keys(first.where)]
            return '(' + '+'.join(parts) + ')' if parts else '0'
        # Counting matching periods is one COUNTIF over the source range,
        # rather than hundreds of repeated IF expressions.
        if (isinstance(first, If) and isinstance(first.condition, Compare)
                and isinstance(first.condition.left, Ref) and isinstance(first.condition.right, Const)
                and isinstance(first.then, Const) and first.then.value == 1
                and isinstance(first.otherwise, Const) and first.otherwise.value == 0
                and all(b is first and s == 1 for b, _, s in terms)):
            name = first.condition.left.name
            cells = [self.cells[name][tuple(self.ev.key(d, env) for d in self.model.variables[name].dims)]
                     for _, env, _ in terms]
            span = _contiguous(cells)
            if span is not None:
                criterion = first.condition.op + _literal(first.condition.right.value)
                return f'COUNTIF({_range(*span, here=here)},"{criterion}")'
        if (isinstance(first, Binary) and first.op in "+-"
                and all(b is first for b, _, _ in terms) and all(s == 1 for _, _, s in terms)):
            left = self._sum([(first.left, env, 1) for _, env, _ in terms], here)
            right = self._sum([(first.right, env, 1) for _, env, _ in terms], here)
            if right == "0":
                return left
            if first.op == "-" and not _SINGLE_SUM.match(right) and not right.startswith("("):
                right = f"({right})"
            return f"({left}{first.op}{right})"
        out = ""
        for body, env, sign in terms:
            text, p = self._emit(body, env, here)
            if text == "0":
                # An item a filter or attribute condition excludes adds nothing.
                continue
            out += ("-" if sign < 0 else "+") + (f"({text})" if p <= 1 else text)
        if not out:
            return "0"
        return f"({out.removeprefix('+')})"

    # --- Largest-remainder allocation in formulas ----------------------------

    def _reserve_helpers(self, name: str, row: int) -> int:
        """Reserve helper rows for every allocation group in `name`'s expression."""
        var = self.model.variables[name]
        if var.expr is None:
            return row
        nodes = [n for n in var.expr.walk() if isinstance(n, AllocateRound)]
        if not nodes:
            return row
        groups: dict[tuple, None] = {}
        for idx in self.cells[name]:
            env = dict(zip(var.dims, idx))
            for node in nodes:
                outer = tuple(sorted((k, v) for k, v in env.items() if k != node.dim))
                groups.setdefault((id(node), outer), None)
        sheet = self.cells[name][next(iter(self.cells[name]))][0]
        for node in nodes:
            for (nid, outer) in groups:
                if nid != id(node):
                    continue
                label = f"{name}{'[' + ','.join(str(v) for _, v in outer) + ']' if outer else ''}"
                rows = {kind: row + i for i, kind in enumerate(("raw", "units", "abs", "key", "rank", "drift"))}
                self.allocations[(nid, outer)] = {"node": node, "sheet": sheet, "rows": rows, "label": label,
                                                  "env": dict(outer), "owner": name}
                row += len(rows)
        return row

    def _allocated(self, e: AllocateRound, env: dict[str, Any], here: str) -> str:
        outer = tuple(sorted((k, v) for k, v in env.items() if k != e.dim))
        group = self.allocations.get((id(e), outer))
        if group is None:
            raise CompileError("An allocation outside a placed variable cannot be compiled.")
        sheet, rows = group["sheet"], group["rows"]
        col = FIRST_VALUE_COLUMN + self.model.dimensions[e.dim].position(env[e.dim])
        scale = _literal(Decimal(1).scaleb(e.places))
        units = _address(sheet, rows["units"], col, here=here)
        rank = _address(sheet, rows["rank"], col, here=here)
        drift = _address(sheet, rows["drift"], FIRST_VALUE_COLUMN, here=here)
        return f"({units}+IF({rank}<ABS({drift}),SIGN({drift}),0))/{scale}"

    def _write_helpers(self) -> None:
        """Rows that reproduce the engine's largest-remainder allocation.

        raw: the unrounded value per item; units: rounded to whole units of the
        last place; drift: rounded total less the sum of rounded units; key: how
        far each item's rounding moved against the drift; rank: the item's
        position when ordered by key, then magnitude, then earlier item. An item
        whose rank is below the drift's size takes one unit toward it.
        """

        grey = self._font(color="808080", italic=True)
        for (nid, outer), group in self.allocations.items():
            node, sheet, rows = group["node"], group["sheet"], group["rows"]
            ws = self.wb[sheet]
            keys = self.model.dimensions[node.dim].keys()
            cols = [FIRST_VALUE_COLUMN + i for i in range(len(keys))]
            first, last = cols[0], cols[-1]
            scale = _literal(Decimal(1).scaleb(node.places))
            for kind, r in rows.items():
                _text(ws.cell(r, 1), f"{group['label']} ~ {kind}")
                ws.cell(r, 1).font = grey
                ws.row_dimensions[r].outlineLevel = 1
            row_range = {k: _range(sheet, rows[k], first, rows[k], last, here=sheet) for k in ("raw", "units",
                                                                                                "abs", "key")}
            drift = _address(sheet, rows["drift"], FIRST_VALUE_COLUMN, here=sheet)
            self._formula(ws.cell(rows["drift"], FIRST_VALUE_COLUMN),
                          f"ROUND(ROUND(SUM({row_range['raw']})*{scale},8),0)-SUM({row_range['units']})", None, group["label"])
            for i, (key, col) in enumerate(zip(keys, cols)):
                env = {**group["env"], node.dim: key}
                raw = _address(sheet, rows["raw"], col, here=sheet)
                units = _address(sheet, rows["units"], col, here=sheet)
                k = _address(sheet, rows["key"], col, here=sheet)
                a = _address(sheet, rows["abs"], col, here=sheet)
                self._formula(ws.cell(rows["raw"], col), self._emit(node.body, env, sheet)[0], None, group["label"])
                # Remove binary noise below 1e-8 of the allocated unit before
                # half-away rounding and ranking (e.g. 8333.335 * 100).
                self._formula(ws.cell(rows["units"], col), f"ROUND(ROUND({raw}*{scale},8),0)", None, group["label"])
                self._formula(ws.cell(rows["abs"], col), f"ABS({raw})", None, group["label"])
                self._formula(ws.cell(rows["key"], col), f"SIGN({drift})*ROUND({raw}*{scale}-{units},8)", None,
                              group["label"])
                rank = (f"SUMPRODUCT(({row_range['key']}>{k})+({row_range['key']}={k})*({row_range['abs']}>{a}))")
                if i == 1:
                    # A one-cell range is a scalar, which SUMPRODUCT does not take.
                    before_k = _address(sheet, rows["key"], first, here=sheet)
                    before_a = _address(sheet, rows["abs"], first, here=sheet)
                    rank += f"+IF(AND({before_k}={k},{before_a}={a}),1,0)"
                elif i:
                    before_k = _range(sheet, rows["key"], first, rows["key"], col - 1, here=sheet)
                    before_a = _range(sheet, rows["abs"], first, rows["abs"], col - 1, here=sheet)
                    rank += f"+SUMPRODUCT(({before_k}={k})*({before_a}={a}))"
                self._formula(ws.cell(rows["rank"], col), rank, None, group["label"])


# --- Helpers ------------------------------------------------------------------

def _numeric(v: Any) -> bool:
    return isinstance(v, (int, Decimal)) and not isinstance(v, bool)


def _number(v: Decimal) -> int | float:
    return int(v) if v == v.to_integral_value() and abs(v) < 2 ** 53 else float(v)


def _literal(v: Decimal) -> str:
    text = f"{v.normalize():f}" if v != 0 else "0"
    return text[1:] if text.startswith("-") else text


def _text(cell, value: str) -> None:
    """Write text that is never read as a formula, whatever it starts with."""
    cell.value = value
    cell.data_type = "s"


def _column_letter(col: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(col)


def _address(sheet: str, row: int, col: int, here: str | None = None) -> str:
    local = f"{_column_letter(col)}{row}"
    return local if sheet == here else f"'{sheet}'!{local}"


def _range(sheet: str, r1: int, c1: int, r2: int, c2: int, here: str | None = None) -> str:
    local = f"{_column_letter(c1)}{r1}:{_column_letter(c2)}{r2}"
    return local if sheet == here else f"'{sheet}'!{local}"


def _contiguous(cells: list[tuple[str, int, int]]) -> tuple | None:
    """The span covering `cells` in order, if they are one unbroken row or column on one sheet."""
    if len({c[0] for c in cells}) != 1:
        return None
    sheet = cells[0][0]
    rows, cols = [c[1] for c in cells], [c[2] for c in cells]
    if len(set(rows)) == 1 and cols == list(range(cols[0], cols[0] + len(cols))):
        return (sheet, rows[0], cols[0], rows[0], cols[-1])
    if len(set(cols)) == 1 and rows == list(range(rows[0], rows[0] + len(rows))):
        return (sheet, rows[0], cols[0], rows[-1], cols[0])
    return None


def _cache_values(path: str, wb, cached: dict[tuple[str, str], Decimal]) -> None:
    """Write each formula cell's cached value into the saved sheet XML.

    openpyxl writes formulas without results, so a reader that does not
    recalculate (a previewer, a script reading values) would see nothing.
    """
    by_sheet: dict[str, dict[str, Decimal]] = {}
    for (sheet, coord), value in cached.items():
        by_sheet.setdefault(sheet, {})[coord] = value
    files = {f"xl/worksheets/sheet{i}.xml": ws.title for i, ws in enumerate(wb.worksheets, start=1)}
    with zipfile.ZipFile(path) as zin:
        contents = {info.filename: (info, zin.read(info.filename)) for info in zin.infolist()}
    pattern = re.compile(rb'<c r="([A-Z]+[0-9]+)"([^>]*)><f>(.*?)</f><v\s*/?>(?:</v>)?</c>', re.S)
    for name, title in files.items():
        values = by_sheet.get(title)
        if not values or name not in contents:
            continue
        info, xml = contents[name]

        def fill(m: re.Match) -> bytes:
            value = values.get(m.group(1).decode())
            if value is None:
                return m.group(0)
            if isinstance(value, str):
                return (b'<c r="' + m.group(1) + b'"' + m.group(2) + b' t="str"><f>' + m.group(3) + b"</f><v>"
                        + xml_escape(value).encode() + b"</v></c>")
            return (b'<c r="' + m.group(1) + b'"' + m.group(2) + b"><f>" + m.group(3) + b"</f><v>"
                    + repr(float(value)).encode() + b"</v></c>")

        contents[name] = (info, pattern.sub(fill, xml))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in contents.values():
            zout.writestr(info, data)
