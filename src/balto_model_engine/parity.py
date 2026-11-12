"""Recalculate a compiled workbook independently and compare it with the run.

The workbook's formulas are evaluated by `pycel`, an Excel formula evaluator
that knows nothing of the engine, so a compiled formula that does not mean what
its expression means shows as a difference. Flexing an input sets the cell in
the recalculation and compares against a fresh engine run with the same input,
which is what an analyst does in Excel.

Excel arithmetic is binary floating point and its `ROUND` rounds half away from
zero, so parity is a declared tolerance, not equality.

`pycel` is a test dependency, imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping
import numbers
import os
import re
import tempfile
import warnings
import zipfile

from .evaluate import Run, _key, evaluate
from .model import Model
from .workbook import Compiled


@dataclass(frozen=True)
class Tolerance:
    """A cell matches when `|excel - run| <= absolute + relative * |run|`."""
    absolute: Decimal = Decimal("0.000001")
    relative: Decimal = Decimal("1e-9")


@dataclass
class ParityReport:
    compared: int = 0
    worst: Decimal = Decimal(0)
    worst_cell: str | None = None
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def check_parity(path: str, compiled: Compiled, model: Model, run: Run, *,
                 tolerance: Tolerance = Tolerance(), flex: Mapping[str, Mapping[tuple, Any]] | None = None,
                 inputs: Mapping[str, Any] | None = None, sources: Mapping[str, Any] | None = None) -> ParityReport:
    """Recalculate the saved workbook at `path` and compare every calculation with the run.

    With `flex`, each named input item is set in the recalculation first, and the
    comparison is against `evaluate(model, inputs with the flex applied, sources)`.
    """
    from pycel import ExcelCompiler

    # pycel trusts a formula cell's cached value until something changes, so
    # recalculate a copy with every cached result removed.
    handle, bare = tempfile.mkstemp(suffix=".xlsx")
    os.close(handle)
    try:
        _strip_cached(path, bare)
        with warnings.catch_warnings():
            # pycel builds Python from formulas with deprecated ast calls.
            warnings.simplefilter("ignore", DeprecationWarning)
            xl = ExcelCompiler(filename=bare, plugins=("balto_model_engine.excel_functions",))
            _build_graph(xl, compiled, model)
            return _compare(xl, compiled, model, run, tolerance, flex, inputs, sources)
    finally:
        os.unlink(bare)


def _build_graph(xl, compiled: Compiled, model: Model) -> None:
    """Load every compared cell into pycel's dependency graph in one pass.

    pycel 1.0b30 finishes each graph extension by logging `len(graph.edges())`,
    which walks every edge. Evaluating cell by cell extends the graph once per
    new cell, so a 30,000-cell workbook spent most of its time counting edges.
    Seeding all addresses together extends it once.
    """
    addresses = [_pycel(address) for name, var in model.variables.items() if var.kind == "calculation"
                 for address in compiled.cells[name].values()]
    addresses += [_pycel(address) for address in compiled.derived]
    addresses += [_pycel(address) for address in compiled.metrics.values()]
    xl._gen_graph(addresses)


def _compare(xl, compiled: Compiled, model: Model, run: Run, tolerance: Tolerance, flex, inputs, sources
             ) -> ParityReport:
    expected = run
    if flex:
        if inputs is None:
            raise ValueError("Flexing needs the run's inputs to rerun the model.")
        changed = {name: dict(value) if isinstance(value, Mapping) else value for name, value in inputs.items()}
        # pycel propagates a changed input only through cells it has already
        # read, so read the whole workbook first.
        for name, var in model.variables.items():
            if var.kind == "calculation":
                for address in compiled.cells[name].values():
                    xl.evaluate(_pycel(address))
        for name, items in flex.items():
            if model.variables[name].kind != "input":
                raise ValueError(f"{name} is not an input.")
            for idx, value in items.items():
                address = _pycel(compiled.cells[name][idx])
                xl.evaluate(address)
                xl.set_value(address, float(Decimal(str(value))))
                if idx == ():
                    changed[name] = value
                else:
                    changed[name][idx[0] if len(idx) == 1 else idx] = value
        expected = evaluate(model, changed, sources)
    report = ParityReport()
    for name, var in model.variables.items():
        if var.kind != "calculation":
            continue
        for idx, address in compiled.cells[name].items():
            want = expected.values[name][idx]
            got = xl.evaluate(_pycel(address))
            report.compared += 1
            if not isinstance(got, (int, float)) or isinstance(got, bool):
                report.mismatches.append({"cell": address, "figure": _key(name, idx), "excel": got,
                                          "run": want})
                continue
            gap = abs(Decimal(repr(float(got))) - want)
            if gap > report.worst:
                report.worst, report.worst_cell = gap, _key(name, idx)
            if gap > tolerance.absolute + tolerance.relative * abs(want):
                report.mismatches.append({"cell": address, "figure": _key(name, idx), "excel": got,
                                          "run": want})
    # Presentation formulas outside the layout show what they promise for this run.
    for address, expect in compiled.derived.items():
        want = expect(expected)
        got = xl.evaluate(_pycel(address))
        report.compared += 1
        if isinstance(want, str) or want is None:
            if got != want and not (want is None and got in (None, "")):
                report.mismatches.append({"cell": address, "figure": "derived", "excel": got, "run": want})
            continue
        want = Decimal(want)
        if not isinstance(got, numbers.Number) or isinstance(got, bool) or \
                abs(Decimal(repr(float(got))) - want) > tolerance.absolute + tolerance.relative * abs(want):
            report.mismatches.append({"cell": address, "figure": "derived", "excel": got, "run": want})
    # A placed XIRR recalculates on the workbook's own flows and dates.
    for name, address in compiled.metrics.items():
        want = expected.metrics[name].get("rate")
        got = xl.evaluate(_pycel(address))
        report.compared += 1
        if want is None or not isinstance(got, float) or abs(Decimal(repr(got)) - want) > Decimal("1e-8"):
            if not (want is None and not isinstance(got, float)):
                report.mismatches.append({"cell": address, "figure": name, "excel": got, "run": want})
    return report


_CACHED = re.compile(rb"(</f>)<v>[^<]*</v>")


def _strip_cached(source: str, target: str) -> None:
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("xl/worksheets/"):
                data = _CACHED.sub(rb"\1<v></v>", data)
            zout.writestr(info, data)


def _pycel(address: str) -> str:
    # pycel addresses a cell as Sheet!A1 without quotes.
    if "!" not in address:
        raise ValueError("A compiled address always names its sheet.")
    sheet, cell = address.rsplit("!", 1)
    return f"{sheet.strip(chr(39))}!{cell}"
