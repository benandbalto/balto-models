"""Model definitions: dimensions, variables, and checks.

A model is Python code that declares named variables. Each variable is a
source (verbatim external data, carried with the document it came from), an
input (a value chosen for the run), or a calculation (one expression over other
variables), and carries a unit and the dimensions it ranges over. The
expression is written once per variable and evaluated for every item of its
dimensions; there is no per-cell logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from .expressions import Compare, Condition, Expr, Number


class ModelDefinitionError(Exception):
    """The model itself is malformed. A programming error, never an input error."""


@dataclass(frozen=True)
class DecimalPolicy:
    precision: int
    rounding: str

    def describe(self) -> dict[str, Any]:
        return {"calculationPrecision": self.precision, "roundingMode": self.rounding}


class Item:
    """One member of a dimension, with attributes a sum may filter on."""

    def __init__(self, key: int | str, **attrs: object) -> None:
        if isinstance(key, bool) or not isinstance(key, (int, str)):
            raise ModelDefinitionError("A dimension item key must be an int or a string.")
        self.key, self.attrs = key, dict(attrs)

    def matches(self, where: Mapping[str, object] | tuple) -> bool:
        pairs = where.items() if isinstance(where, Mapping) else where
        return all(self.attrs.get(k) == v for k, v in pairs)


@dataclass
class Dimension:
    """Ordered items. With a `parent`, each item names the parent item it belongs to.

    A child item carries its parent's key as the attribute named after the
    parent dimension (a unit's `unit_type`). A reference from a child to a
    variable over the parent reads the child's own parent item, and
    `sum_within` adds the children of the current parent item.
    """
    name: str
    items: list[Item]
    parent: str | None = None

    def __post_init__(self) -> None:
        keys = [i.key for i in self.items]
        if len(set(keys)) != len(keys):
            raise ModelDefinitionError(f"Dimension {self.name} repeats an item key.")
        self._position = {k: i for i, k in enumerate(keys)}

    def item(self, key: int | str) -> Item:
        return self.items[self._position[key]]

    def position(self, key: int | str) -> int:
        return self._position[key]

    def parent_of(self, key: int | str) -> int | str:
        return self.item(key).attrs[self.parent]

    def keys(self, where: Mapping[str, object] | tuple = ()) -> list[int | str]:
        return [i.key for i in self.items if i.matches(where)]


@dataclass
class Variable:
    name: str
    unit: str
    dims: tuple[str, ...]
    kind: str  # "source" | "input" | "calculation"
    expr: Expr | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    # An input may be declared on only the items matching these attributes.
    where: tuple = ()
    # A source's document identity, such as its file name and digest.
    document: tuple = ()


@dataclass
class Check:
    """A declared rule. Every item where the condition is false fails the run."""
    name: str
    dims: tuple[str, ...]
    where: tuple
    condition: Condition
    code: str
    message: str


@dataclass
class Test:
    """A declared test reported as a result. A breach never fails the run.

    A covenant or a set-aside can be breached in a downside scenario, and the
    scenario must still finish so it can be compared; the run records where the
    test first failed, for how many items, and by how much.
    """
    name: str
    dims: tuple[str, ...]
    where: tuple
    condition: Compare
    code: str
    message: str


@dataclass
class Xirr:
    """An IRR computed after evaluation from a dated series of flows (Excel `XIRR`)."""
    name: str
    flows: str
    dim: str
    date_attr: str
    tolerance: Decimal


@dataclass
class SourceMapping:
    """A reviewed correspondence from each item of a dimension to a target.

    Every item is assigned a target or explicitly excluded (None), so nothing in
    a source is silently dropped. A sign of -1 reverses an item whose source
    books it the other way round from its target, such as bad debt booked as an
    expense against a contra-revenue line.
    """
    name: str
    dim: str
    assign: tuple  # ((item key, target or None, sign), ...) in dimension order

    def items_for(self, target: str) -> list[tuple[int | str, int]]:
        return [(key, sign) for key, t, sign in self.assign if t == target]

    def targets(self) -> set[str]:
        return {t for _, t, _ in self.assign if t is not None}


@dataclass
class Model:
    model_id: str
    version: str
    policy: DecimalPolicy
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    variables: dict[str, Variable] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    mappings: dict[str, SourceMapping] = field(default_factory=dict)
    tests: list[Test] = field(default_factory=list)
    metrics: dict[str, Xirr] = field(default_factory=dict)

    def dimension(self, dim: Dimension) -> Dimension:
        if dim.name in self.dimensions:
            raise ModelDefinitionError(f"Dimension {dim.name} is declared twice.")
        if dim.parent is not None:
            if dim.parent not in self.dimensions:
                raise ModelDefinitionError(f"Dimension {dim.name}: parent {dim.parent} is not declared.")
            parents = set(self.dimensions[dim.parent].keys())
            for item in dim.items:
                if item.attrs.get(dim.parent) not in parents:
                    raise ModelDefinitionError(f"Dimension {dim.name}: every item must name a {dim.parent} item.")
        self.dimensions[dim.name] = dim
        return dim

    def input(self, name: str, *, unit: str, dims: tuple[str, ...] = (),
              minimum: Number | None = None, maximum: Number | None = None,
              where: Mapping[str, object] | None = None) -> None:
        self._add(Variable(name, unit, self._dims(dims), "input",
                           minimum=None if minimum is None else Decimal(str(minimum)),
                           maximum=None if maximum is None else Decimal(str(maximum)),
                           where=tuple(sorted((where or {}).items()))))

    def source(self, name: str, *, unit: str, document: Mapping[str, str], dims: tuple[str, ...] = ()) -> None:
        if not isinstance(document, Mapping) or not document.get("name"):
            raise ModelDefinitionError(f"Source {name} must name the document it comes from.")
        self._add(Variable(name, unit, self._dims(dims), "source",
                           document=tuple(sorted((str(k), str(v)) for k, v in document.items()))))

    def calc(self, name: str, *, unit: str, expr: Expr, dims: tuple[str, ...] = (),
             where: Mapping[str, object] | None = None) -> None:
        """A calculation; with `where` (one dimension), only over the items whose attributes match."""
        if not isinstance(expr, Expr):
            raise ModelDefinitionError(f"{name} must be defined by an expression.")
        self._add(Variable(name, unit, self._dims(dims), "calculation", expr=expr,
                           where=tuple(sorted((where or {}).items()))))

    def check(self, name: str, *, condition: Condition, code: str, message: str,
              dims: tuple[str, ...] = (), where: Mapping[str, object] | None = None) -> None:
        if not isinstance(condition, Condition):
            raise ModelDefinitionError(f"Check {name} needs a comparison as its condition.")
        self.checks.append(Check(name, self._dims(dims), tuple(sorted((where or {}).items())),
                                 condition, code, message))

    def test(self, name: str, *, condition: Compare, code: str, message: str,
             dims: tuple[str, ...] = (), where: Mapping[str, object] | None = None) -> None:
        if not isinstance(condition, Compare):
            raise ModelDefinitionError(f"Test {name} needs a comparison as its condition.")
        if any(t.name == name for t in self.tests):
            raise ModelDefinitionError(f"Test {name} is declared twice.")
        self.tests.append(Test(name, self._dims(dims), tuple(sorted((where or {}).items())),
                               condition, code, message))

    def xirr(self, name: str, *, flows: str, dim: str, date_attr: str, tolerance: Number = "1e-10") -> None:
        """Declare an IRR over `flows` along `dim`, dated by each item's `date_attr` (an Excel serial day)."""
        if name in self.metrics:
            raise ModelDefinitionError(f"Metric {name} is declared twice.")
        (dim,) = self._dims((dim,))
        self.metrics[name] = Xirr(name, flows, dim, date_attr, Decimal(str(tolerance)))

    def mapping(self, name: str, *, dim: str, assign: Mapping[int | str, str | None],
                signs: Mapping[int | str, int] | None = None) -> None:
        if name in self.mappings:
            raise ModelDefinitionError(f"Mapping {name} is declared twice.")
        (dim,) = self._dims((dim,))
        keys = self.dimensions[dim].keys()
        if set(assign) != set(keys):
            raise ModelDefinitionError(f"Mapping {name} must assign or exclude every item of {dim}, and no others.")
        signs = dict(signs or {})
        for key, sign in signs.items():
            if sign not in (1, -1) or isinstance(sign, bool):
                raise ModelDefinitionError(f"Mapping {name}: a sign is 1 or -1.")
            if assign.get(key) is None:
                raise ModelDefinitionError(f"Mapping {name}: an excluded item carries no sign.")
        for target in assign.values():
            if target is not None and (not isinstance(target, str) or not target):
                raise ModelDefinitionError(f"Mapping {name}: a target is a non-empty name or None.")
        self.mappings[name] = SourceMapping(name, dim, tuple((k, assign[k], signs.get(k, 1)) for k in keys))

    def _dims(self, dims: tuple[str, ...]) -> tuple[str, ...]:
        for d in dims:
            if d not in self.dimensions:
                raise ModelDefinitionError(f"Dimension {d} is not declared.")
        if len(set(dims)) != len(dims):
            raise ModelDefinitionError("A variable names a dimension twice.")
        return tuple(dims)

    def _add(self, var: Variable) -> None:
        if var.name in self.variables:
            raise ModelDefinitionError(f"{var.name} is defined more than once.")
        self.variables[var.name] = var

    def describe(self) -> dict[str, Any]:
        """Canonical structure, digested into every run so a formula change shows."""
        return {
            "modelId": self.model_id, "modelVersion": self.version,
            "decimalPolicy": self.policy.describe(),
            "dimensions": {
                d.name: [{"key": i.key, **{k: i.attrs[k] for k in sorted(i.attrs)}} for i in d.items]
                for d in self.dimensions.values()},
            "hierarchy": {d.name: d.parent for d in self.dimensions.values() if d.parent is not None},
            "variables": [{
                "name": v.name, "unit": v.unit, "dims": list(v.dims), "kind": v.kind,
                **({"expression": str(v.expr)} if v.expr is not None else {}),
                **({"minimum": v.minimum} if v.minimum is not None else {}),
                **({"maximum": v.maximum} if v.maximum is not None else {}),
                **({"where": dict(v.where)} if v.where else {}),
                **({"document": dict(v.document)} if v.document else {}),
            } for v in self.variables.values()],
            "checks": [{"name": c.name, "dims": list(c.dims), "where": dict(c.where),
                        "condition": str(c.condition), "code": c.code} for c in self.checks],
            "mappings": {mp.name: {"dim": mp.dim, "assign": [list(a) for a in mp.assign]}
                         for mp in self.mappings.values()},
            # Present only when declared, so a model without them keeps its structure.
            **({"tests": [{"name": t.name, "dims": list(t.dims), "where": dict(t.where),
                           "condition": str(t.condition), "code": t.code} for t in self.tests]}
               if self.tests else {}),
            **({"metrics": {x.name: {"kind": "xirr", "flows": x.flows, "dim": x.dim, "dateAttr": x.date_attr,
                                     "tolerance": x.tolerance} for x in self.metrics.values()}}
               if self.metrics else {}),
        }
