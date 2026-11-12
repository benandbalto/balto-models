"""Evaluate a model over a set of inputs to produce a run.

Evaluation is pure and deterministic: the same model and inputs always produce
the same values and the same digest. The model's decimal policy governs every
operation, and a run records the engine and model identity, each variable's
lineage, and a digest over structure, inputs, and values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from itertools import product
from typing import Any, Mapping
import hashlib
import json

from .expressions import (
    AllocateRound, Attr, Binary, Compare, Condition, Const, Expr, Extreme, If, Lag, Mapped, Matches, Neg, Power,
    Previous, Prior, Ref, Round, Sum, SumWithin,
)
from .metrics import xirr
from .model import Model, ModelDefinitionError, Variable

ENGINE = {"engineId": "balto-model-engine", "engineVersion": "0.4.0"}

Index = tuple  # item keys, in the variable's dimension order


class EngineError(Exception):
    """A safe, stable run failure. Messages never contain submitted values."""

    def __init__(self, code: str, message: str, key: str | None = None) -> None:
        self.code, self.key = code, key
        super().__init__(message)


@dataclass(frozen=True)
class Run:
    model_id: str
    model_version: str
    engine_version: str
    decimal_policy: dict[str, Any]
    dims: dict[str, tuple[str, ...]]
    values: dict[str, dict[Index, Decimal]]
    lineage: dict[str, dict[str, Any]]
    digest: str
    # Declared tests, reported rather than raised, and post-run metrics.
    tests: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    def value(self, name: str, **index: int | str) -> Decimal:
        dims = self.dims[name]
        if set(index) != set(dims):
            raise KeyError(f"{name} is indexed by {dims}.")
        return self.values[name][tuple(index[d] for d in dims)]

    def series(self, name: str) -> list[Decimal]:
        """A one-dimensional variable's values in dimension order."""
        if len(self.dims[name]) != 1:
            raise KeyError(f"{name} is not one-dimensional.")
        return list(self.values[name].values())


def evaluate(model: Model, inputs: Mapping[str, Any], sources: Mapping[str, Any] | None = None) -> Run:
    """Evaluate the model. Sources and chosen inputs are supplied apart, as declared."""
    steps = _validate(model)
    with localcontext() as ctx:
        ctx.prec = model.policy.precision
        ctx.rounding = model.policy.rounding
        supplied = {"source": sources or {}, "input": inputs}
        for kind, given in supplied.items():
            _refuse_unknown(model, kind, given)
        indices = _IndexSchedule(model)
        values = {name: v for kind, given in supplied.items()
                  for name, v in _read_supplied(model, kind, given, indices).items()}
        ev = _Evaluator(model, values, indices)
        # A check runs as soon as everything it reads exists, so a failed rule is
        # reported as itself rather than as a calculation it would have broken.
        position = {name: i for i, step in enumerate(steps) for name in step.names}
        due: dict[int, list] = {}
        for check in model.checks:
            ready = max((position.get(d, -1) for d in _depends_on(check.condition)), default=-1)
            due.setdefault(ready, []).append(check)
        _run_checks(model, ev, due.get(-1, []))
        for i, step in enumerate(steps):
            for name in step.names:
                values[name] = {}
            if step.dim is None:
                (name,) = step.names
                var = model.variables[name]
                _evaluate_items(model, ev, name, indices.indices(var.dims, var.where))
            else:
                # A recurrence block: every member at one item of the dimension
                # before any member at the next, so a lag always finds its value.
                by_period = {}
                for name in step.names:
                    var = model.variables[name]
                    at = var.dims.index(step.dim)
                    grouped = {}
                    for idx in indices.indices(var.dims, var.where):
                        grouped.setdefault(idx[at], []).append(idx)
                    by_period[name] = grouped
                for key in indices.keys(step.dim):
                    for name in step.names:
                        _evaluate_items(model, ev, name, by_period[name].get(key, []))
            _run_checks(model, ev, due.get(i, []))
        tests = {t.name: _run_test(model, ev, t) for t in model.tests}
        metrics = {x.name: _run_xirr(model, values, x, indices) for x in model.metrics.values()}
    lineage = {
        v.name: {
            "kind": v.kind, "unit": v.unit, "dims": list(v.dims),
            **({"document": dict(v.document)} if v.document else {}),
            **({"expression": str(v.expr), "dependsOn": _depends_on(v.expr, v.name)} if v.expr is not None else {}),
            **({"lags": _lags(v.expr)} if v.expr is not None and _lags(v.expr) else {}),
            **({"mappings": _mappings_used(v.expr)} if v.expr is not None and _mappings_used(v.expr) else {}),
        } for v in model.variables.values()}
    ordered = {name: values[name] for name in model.variables}
    return Run(
        model_id=model.model_id, model_version=model.version,
        engine_version=ENGINE["engineVersion"], decimal_policy=model.policy.describe(),
        dims={v.name: v.dims for v in model.variables.values()},
        values=ordered, lineage=lineage, tests=tests, metrics=metrics,
        digest=_digest({"engine": ENGINE, "model": model.describe(),
                        "values": {n: [[list(i), v] for i, v in vs.items()] for n, vs in ordered.items()},
                        **({"tests": tests} if tests else {}), **({"metrics": metrics} if metrics else {})}),
    )


def _evaluate_items(model: Model, ev: "_Evaluator", name: str, indices: list[Index]) -> None:
    var, out = model.variables[name], ev.values[name]
    for idx in indices:
        try:
            out[idx] = ev.number(var.expr, dict(zip(var.dims, idx)))
        except (DivisionByZero, InvalidOperation) as exc:
            raise EngineError("CALCULATION_UNDEFINED", "A calculation divided by zero or was undefined.",
                              _key(name, idx)) from exc


def _run_test(model: Model, ev: "_Evaluator", test) -> dict[str, Any]:
    """Evaluate a test on every item and report its breaches without failing the run.

    The shortfall is how far an item is from passing: `b - a` for `a >= b`,
    `a - b` for `a <= b`, `|a - b|` for `a = b`, and zero for `a <> b`.
    """
    c = test.condition
    indices = ev.indices.indices(test.dims, test.where)
    breaches: list[tuple[Index, Decimal]] = []
    for idx in indices:
        env = dict(zip(test.dims, idx))
        try:
            a, b = ev.number(c.left, env), ev.number(c.right, env)
        except (DivisionByZero, InvalidOperation) as exc:
            raise EngineError("CALCULATION_UNDEFINED", "A test divided by zero or was undefined.",
                              _key(test.name, idx)) from exc
        if not _compare(c.op, a, b):
            shortfall = {">": b - a, ">=": b - a, "<": a - b, "<=": a - b, "=": abs(a - b)}.get(c.op, Decimal(0))
            breaches.append((idx, shortfall))
    result: dict[str, Any] = {"code": test.code, "message": test.message, "passed": not breaches,
                              "items": len(indices), "breaches": len(breaches)}
    if breaches:
        worst = max(breaches, key=lambda b: b[1])  # the earliest of equal shortfalls
        result["firstBreach"] = list(breaches[0][0])
        result["worstBreach"] = {"item": list(worst[0]), "shortfall": worst[1]}
    return result


def _run_xirr(model: Model, values: dict[str, dict[Index, Decimal]], metric,
              indices: "_IndexSchedule") -> dict[str, Any]:
    keys = indices.keys(metric.dim)
    flows = [values[metric.flows][(k,)] for k in keys]
    days = [_attribute(model, metric.dim, k, metric.date_attr) for k in keys]
    return {"kind": "xirr", "flows": metric.flows, **xirr(flows, days, metric.tolerance)}


def _run_checks(model: Model, ev: "_Evaluator", checks: list) -> None:
    for check in checks:
        for idx in ev.indices.indices(check.dims, check.where):
            if not ev.truth(check.condition, dict(zip(check.dims, idx))):
                raise EngineError(check.code, check.message, _key(check.name, idx))


# --- Definition checks ------------------------------------------------------

def _validate(model: Model) -> list[str]:
    """Check every expression against the model, then order calculations."""
    for var in model.variables.values():
        if var.where and len(var.dims) != 1:
            raise ModelDefinitionError(f"{var.name}: an item filter needs exactly one dimension.")
        if var.expr is not None:
            _check(model, var.name, var.expr, set(var.dims), allow_compare=False)
    for c in model.checks:
        if c.where and len(c.dims) != 1:
            raise ModelDefinitionError(f"Check {c.name}: an item filter needs exactly one dimension.")
        _check(model, c.name, c.condition, set(c.dims), allow_compare=True)
    for t in model.tests:
        if t.where and len(t.dims) != 1:
            raise ModelDefinitionError(f"Test {t.name}: an item filter needs exactly one dimension.")
        _check(model, t.name, t.condition, set(t.dims), allow_compare=True)
    for x in model.metrics.values():
        flows = model.variables.get(x.flows)
        if flows is None or flows.dims != (x.dim,):
            raise ModelDefinitionError(f"Metric {x.name}: flows must be a variable over {x.dim} alone.")
        _numeric_attribute(model, x.name, x.dim, x.date_attr)
    return _schedule(model)


def _check(model: Model, owner: str, e: Expr, bound: set[str], allow_compare: bool,
           recurring: tuple = ()) -> None:
    # `recurring` holds the (variable, dimension) of each enclosing Previous, the
    # only place a Prior may appear.
    if isinstance(e, Condition) and not allow_compare:
        raise ModelDefinitionError(f"{owner}: a comparison is only valid as a condition.")
    if isinstance(e, Compare):
        _check(model, owner, e.left, bound, False, recurring)
        _check(model, owner, e.right, bound, False, recurring)
    elif isinstance(e, Matches):
        if not _reachable(model, e.dim, bound):
            raise ModelDefinitionError(f"{owner} tests {e.dim}, which it is not indexed by.")
    elif isinstance(e, (Ref, Prior)):
        target = model.variables.get(e.name)
        if target is None:
            raise ModelDefinitionError(f"{owner} refers to undeclared variable {e.name}.")
        missing = [d for d in target.dims if not _reachable(model, d, bound)]
        if missing:
            raise ModelDefinitionError(f"{owner} refers to {e.name} without binding {', '.join(missing)}.")
        if isinstance(e, Prior) and (e.name, e.dim) not in recurring:
            raise ModelDefinitionError(f"{owner}: prior({e.name}) is only valid in its own previous() step.")
    elif isinstance(e, Lag):
        target = model.variables.get(e.name)
        if target is None:
            raise ModelDefinitionError(f"{owner} lags undeclared variable {e.name}.")
        if e.dim not in bound or e.dim not in target.dims:
            raise ModelDefinitionError(f"{owner}: lag() must run along a dimension both variables carry.")
        missing = [d for d in target.dims if not _reachable(model, d, bound)]
        if missing:
            raise ModelDefinitionError(f"{owner} lags {e.name} without binding {', '.join(missing)}.")
        _check(model, owner, e.initial, bound, False, recurring)
    elif isinstance(e, Attr):
        if not _reachable(model, e.dim, bound):
            raise ModelDefinitionError(f"{owner} reads {e.dim}.{e.name} without {e.dim} bound.")
        _numeric_attribute(model, owner, e.dim, e.name)
    elif isinstance(e, Previous):
        target = model.variables.get(e.name)
        if e.dim not in bound or target is None or e.dim not in target.dims:
            raise ModelDefinitionError(f"{owner}: previous() must run along a dimension both variables carry.")
        # A variable recurring on itself is evaluated item by item in order, so
        # the dimension must be its own, not one bound by an enclosing sum.
        if e.name == owner and e.dim not in model.variables[owner].dims:
            raise ModelDefinitionError(f"{owner}: a recurrence must run along the variable's own dimension.")
        _check(model, owner, e.initial, bound, False, recurring)
        _check(model, owner, e.step, bound, False, recurring + ((e.name, e.dim),))
    elif isinstance(e, SumWithin):
        dim = model.dimensions.get(e.dim)
        if dim is None or dim.parent is None:
            raise ModelDefinitionError(f"{owner}: sum_within needs a dimension with a parent.")
        if e.dim in bound or not _reachable(model, dim.parent, bound):
            raise ModelDefinitionError(f"{owner} sums within {e.dim} without its {dim.parent} bound.")
        _check(model, owner, e.body, bound | {e.dim}, False, recurring)
    elif isinstance(e, Sum):
        if e.dim not in model.dimensions:
            raise ModelDefinitionError(f"{owner} sums over undeclared dimension {e.dim}.")
        if e.dim in bound:
            raise ModelDefinitionError(f"{owner} sums over {e.dim}, which is already bound.")
        _check(model, owner, e.body, bound | {e.dim}, False, recurring)
    elif isinstance(e, Mapped):
        mapping = model.mappings.get(e.mapping)
        if mapping is None:
            raise ModelDefinitionError(f"{owner} uses undeclared mapping {e.mapping}.")
        if mapping.dim in bound:
            raise ModelDefinitionError(f"{owner} maps over {mapping.dim}, which is already bound.")
        if e.target not in mapping.targets():
            # Almost always a misspelt target; an empty sum would hide it.
            raise ModelDefinitionError(f"{owner}: mapping {e.mapping} assigns nothing to {e.target}.")
        _check(model, owner, e.body, bound | {mapping.dim}, False, recurring)
    elif isinstance(e, AllocateRound):
        if e.dim not in bound:
            raise ModelDefinitionError(f"{owner} allocates over {e.dim}, which it is not indexed by.")
        _check(model, owner, e.body, bound, False, recurring)
    elif isinstance(e, If):
        _check(model, owner, e.condition, bound, True, recurring)
        _check(model, owner, e.then, bound, False, recurring)
        _check(model, owner, e.otherwise, bound, False, recurring)
    else:
        for child in e.children():
            _check(model, owner, child, bound, False, recurring)


def _reachable(model: Model, dim: str, bound: set[str]) -> bool:
    """Whether `dim` is bound, directly or as the parent of a bound dimension."""
    return _resolver(model, dim, bound) is not None


def _resolver(model: Model, dim: str, bound) -> list[str] | None:
    """The bound dimension and the parent steps that reach `dim`, or None."""
    if dim in bound:
        return [dim]
    found = []
    for child in bound:
        path = [child]
        while (parent := model.dimensions[path[-1]].parent) is not None:
            path.append(parent)
            if parent == dim:
                found.append(path)
                break
    if len(found) > 1:
        raise ModelDefinitionError(f"{dim} is reached through more than one bound dimension; bind it directly.")
    return found[0] if found else None


@dataclass(frozen=True)
class _Step:
    """One variable, or a recurrence block evaluated item by item along `dim`."""
    names: tuple[str, ...]
    dim: str | None = None


def _topological(model: Model) -> list[str]:
    """Calculations ordered by their same-item reads. A lag is not such a read."""
    order: list[str] = []
    state: dict[str, int] = {}  # 1 visiting, 2 done

    def visit(name: str, path: list[str]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            cycle = path[path.index(name):] + [name]
            raise ModelDefinitionError(f"Undeclared cycle: {' -> '.join(cycle)}.")
        state[name] = 1
        var = model.variables[name]
        if var.expr is not None:
            for dep in _depends_on(var.expr, name):
                visit(dep, path + [name])
            order.append(name)
        state[name] = 2

    for name in model.variables:
        visit(name, [])
    return order


def _schedule(model: Model) -> list[_Step]:
    """Order calculations into steps, grouping variables that lag one another into blocks.

    Same-item reads must be acyclic. Reads through a lag may form a cycle (a
    balance lags the payment that reads the balance); each such strongly
    connected group is a block, evaluated along its one lag dimension.
    """
    order = _topological(model)
    rank = {name: i for i, name in enumerate(order)}
    calcs = set(order)
    edges = {n: [d for d in _depends_on(model.variables[n].expr, n) if d in calcs]
             + [lg.name for lg in _lag_nodes(model.variables[n].expr) if lg.name in calcs] for n in order}
    components = _strongly_connected(order, edges)
    comp_of = {n: i for i, comp in enumerate(components) for n in comp}
    steps: dict[int, _Step] = {}
    for i, comp in enumerate(components):
        members = tuple(sorted(comp, key=rank.__getitem__))
        internal = [lg for n in members for lg in _lag_nodes(model.variables[n].expr) if lg.name in comp]
        if not internal:
            steps[i] = _Step(members)
            continue
        dims = {lg.dim for lg in internal}
        if len(dims) != 1:
            raise ModelDefinitionError(f"Recurrence block {', '.join(members)} lags along more than one dimension.")
        (dim,) = dims
        for n in members:
            if dim not in model.variables[n].dims:
                raise ModelDefinitionError(f"{n}: every variable in a recurrence block must carry {dim}.")
            _block_safe(model, n, model.variables[n].expr, dim, set(comp), set())
        steps[i] = _Step(members, dim)
    # Order the blocks by their reads, earliest member first for a stable order.
    out: list[_Step] = []
    done: set[int] = set()

    def place(i: int) -> None:
        if i in done:
            return
        done.add(i)
        for n in sorted(components[i], key=rank.__getitem__):
            for dep in sorted(edges[n], key=rank.__getitem__):
                if comp_of[dep] != i:
                    place(comp_of[dep])
        out.append(steps[i])

    for i in sorted(range(len(components)), key=lambda i: min(rank[n] for n in components[i])):
        place(i)
    return out


def _strongly_connected(nodes: list[str], edges: dict[str, list[str]]) -> list[set[str]]:
    """Tarjan's algorithm, iterative so a long chain of figures cannot exhaust the stack."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[set[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(edges[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(edges[nxt])))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = set()
                while True:
                    n = stack.pop()
                    on_stack.discard(n)
                    comp.add(n)
                    if n == node:
                        break
                out.append(comp)
    return out


def _block_safe(model: Model, owner: str, e: Expr, dim: str, members: set[str], summed: set[str]) -> None:
    """A block member may not read other items of the block dimension of a member.

    Members are evaluated one item at a time, so a sum or allocation over the
    block dimension would read items not yet evaluated.
    """
    if isinstance(e, (Ref, Lag)) and e.name in members and dim in summed:
        raise ModelDefinitionError(f"{owner} sums {e.name} over {dim} inside the recurrence block along {dim}.")
    if isinstance(e, AllocateRound) and e.dim == dim:
        raise ModelDefinitionError(f"{owner} allocates over {dim} inside the recurrence block along {dim}.")
    if isinstance(e, Previous) and e.dim == dim and e.name != owner and e.name in members:
        raise ModelDefinitionError(f"{owner}: use lag(), not previous(), to read {e.name} inside the block.")
    inner = summed
    if isinstance(e, (Sum, SumWithin)):
        inner = summed | {e.dim}
    elif isinstance(e, Mapped):
        inner = summed | {model.mappings[e.mapping].dim}
    for child in e.children():
        _block_safe(model, owner, child, dim, members, inner)


def _lag_nodes(e: Expr) -> list[Lag]:
    return [n for n in e.walk() if isinstance(n, Lag)]


def _lags(e: Expr) -> list[str]:
    return list(dict.fromkeys(n.name for n in _lag_nodes(e)))


def _numeric_attribute(model: Model, owner: str, dim: str, name: str) -> None:
    for item in model.dimensions[dim].items:
        value = item.attrs.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise ModelDefinitionError(f"{owner}: every {dim} item needs a numeric {name} attribute.")


def _attribute(model: Model, dim: str, key: Any, name: str) -> Decimal:
    return Decimal(model.dimensions[dim].item(key).attrs[name])


def _mappings_used(e: Expr) -> list[str]:
    return list(dict.fromkeys(n.mapping for n in e.walk() if isinstance(n, Mapped)))


def _depends_on(e: Expr, owner: str | None = None) -> list[str]:
    """Variables `e` reads. A variable's reads of its own prior items are not dependencies."""
    seen: dict[str, None] = {}
    for node in e.walk():
        if isinstance(node, Ref) or (isinstance(node, Prior) and node.name != owner):
            seen.setdefault(node.name, None)
    return list(seen)


# --- Inputs -----------------------------------------------------------------

def _refuse_unknown(model: Model, kind: str, supplied: Mapping[str, Any]) -> None:
    if not isinstance(supplied, Mapping):
        raise EngineError("INPUT_INVALID", f"The {kind} values must be a mapping of variable names.")
    for name in sorted(map(str, supplied)):
        var = model.variables.get(name)
        if var is None or var.kind != kind:
            raise EngineError("INPUT_UNKNOWN", f"A supplied value names no declared {kind}.", name)


def _read_supplied(model: Model, kind: str, supplied: Mapping[str, Any],
                   indices: "_IndexSchedule") -> dict[str, dict[Index, Decimal]]:
    """Read the supplied values of every variable of one kind (source or input)."""
    values: dict[str, dict[Index, Decimal]] = {}
    for var in model.variables.values():
        if var.kind != kind:
            continue
        if var.name not in supplied:
            raise EngineError("INPUT_MISSING", f"A declared {kind} was not supplied.", var.name)
        values[var.name] = _read_input(var, supplied[var.name], indices)
    return values


def _read_input(var: Variable, raw: Any, indices: "_IndexSchedule") -> dict[Index, Decimal]:
    if not var.dims:
        if isinstance(raw, Mapping):
            raise EngineError("INPUT_INVALID", "A scalar input was given per item.", var.name)
        return {(): _bounded(var, raw, var.name)}
    if not isinstance(raw, Mapping):
        raise EngineError("INPUT_INVALID", "A dimensioned input must be given per item.", var.name)
    expected = indices.indices(var.dims, var.where)
    by_index = {(k if isinstance(k, tuple) else (k,)): v for k, v in raw.items()}
    declared = set(expected)
    for idx in by_index:
        if idx not in declared:
            raise EngineError("INPUT_UNKNOWN", "An input names an item it is not declared for.", _key(var.name, idx))
    out = {}
    for idx in expected:
        if idx not in by_index:
            raise EngineError("INPUT_MISSING", "A dimensioned input is missing an item.", _key(var.name, idx))
        out[idx] = _bounded(var, by_index[idx], _key(var.name, idx))
    return out


def _bounded(var: Variable, raw: Any, key: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        raise EngineError("INPUT_INVALID", "An input is not a number.", key)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise EngineError("INPUT_INVALID", "An input is not a number.", key) from exc
    if not value.is_finite():
        raise EngineError("INPUT_INVALID", "An input is not a finite number.", key)
    if (var.minimum is not None and value < var.minimum) or (var.maximum is not None and value > var.maximum):
        raise EngineError("INPUT_OUT_OF_RANGE", "An input is outside its declared bounds.", key)
    return value


# --- Evaluation -------------------------------------------------------------

class _Evaluator:
    def __init__(self, model: Model, values: dict[str, dict[Index, Decimal]], indices: "_IndexSchedule") -> None:
        self.model, self.values = model, values
        self.indices = indices
        self.allocations: dict[tuple, dict[Any, Decimal]] = {}

    def number(self, e: Expr, env: dict[str, Any]) -> Decimal:
        if isinstance(e, Const):
            return e.value
        if isinstance(e, (Ref, Prior)):
            if isinstance(e, Prior):
                # Validation confines a prior to its previous() step, which is
                # never evaluated at the first item.
                dim = self.model.dimensions[e.dim]
                env = {**env, e.dim: dim.items[dim.position(env[e.dim]) - 1].key}
            dims = self.model.variables[e.name].dims
            idx = tuple(self.key(d, env) for d in dims)
            try:
                return self.values[e.name][idx]
            except KeyError:
                raise ModelDefinitionError(
                    f"{e.name} is referenced on {_key(e.name, idx)}, an item it is not declared for.") from None
        if isinstance(e, Binary):
            a, b = self.number(e.left, env), self.number(e.right, env)
            if e.op == "+":
                return a + b
            if e.op == "-":
                return a - b
            if e.op == "*":
                return a * b
            return a / b
        if isinstance(e, Neg):
            return -self.number(e.operand, env)
        if isinstance(e, Sum):
            acc = Decimal(0)
            for key in self.indices.keys(e.dim, e.where):
                acc += self.number(e.body, {**env, e.dim: key})
            return acc
        if isinstance(e, SumWithin):
            dim = self.model.dimensions[e.dim]
            parent = self.key(dim.parent, env)
            acc = Decimal(0)
            for key in self.indices.keys(e.dim, e.where + ((dim.parent, parent),)):
                acc += self.number(e.body, {**env, e.dim: key})
            return acc
        if isinstance(e, Lag):
            dim = self.model.dimensions[e.dim]
            at = dim.position(env[e.dim])
            if at == 0:
                return self.number(e.initial, env)
            return self.number(Ref(e.name), {**env, e.dim: dim.items[at - 1].key})
        if isinstance(e, Power):
            return self.number(e.base, env) ** self.number(e.exponent, env)
        if isinstance(e, Extreme):
            args = [self.number(a, env) for a in e.args]
            return min(args) if e.op == "min" else max(args)
        if isinstance(e, Attr):
            return _attribute(self.model, e.dim, self.key(e.dim, env), e.name)
        if isinstance(e, Previous):
            if self.model.dimensions[e.dim].position(env[e.dim]) == 0:
                return self.number(e.initial, env)
            return self.number(e.step, env)
        if isinstance(e, Mapped):
            mapping = self.model.mappings[e.mapping]
            acc = Decimal(0)
            for key, sign in mapping.items_for(e.target):
                value = self.number(e.body, {**env, mapping.dim: key})
                acc += value if sign > 0 else -value
            return acc
        if isinstance(e, If):
            return self.number(e.then if self.truth(e.condition, env) else e.otherwise, env)
        if isinstance(e, Round):
            return self.number(e.body, env).quantize(Decimal(1).scaleb(-e.places),
                                                     rounding=self.model.policy.rounding)
        if isinstance(e, AllocateRound):
            return self._allocated(e, env)[env[e.dim]]
        raise ModelDefinitionError(f"Unsupported expression node {type(e).__name__}.")

    def key(self, dim: str, env: dict[str, Any]) -> Any:
        """The current item of `dim`: bound directly, or the parent of a bound child."""
        path = _resolver(self.model, dim, env)
        key = env[path[0]]
        for child in path[:-1]:
            key = self.model.dimensions[child].parent_of(key)
        return key

    def truth(self, c: Condition, env: dict[str, Any]) -> bool:
        if isinstance(c, Matches):
            key = self.key(c.dim, env)
            return self.model.dimensions[c.dim].item(key).matches(c.where)
        return _compare(c.op, self.number(c.left, env), self.number(c.right, env))

    def _allocated(self, e: AllocateRound, env: dict[str, Any]) -> dict[Any, Decimal]:
        outer = tuple(sorted((k, v) for k, v in env.items() if k != e.dim))
        cache_key = (id(e), outer)
        if cache_key not in self.allocations:
            keys = self.indices.keys(e.dim)
            raw = [self.number(e.body, {**env, e.dim: k}) for k in keys]
            self.allocations[cache_key] = dict(zip(keys, _largest_remainder(raw, e.places,
                                                                            self.model.policy.rounding)))
        return self.allocations[cache_key]


def _compare(op: str, a: Decimal, b: Decimal) -> bool:
    return {"=": a == b, "<>": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _largest_remainder(values: list[Decimal], places: int, rounding: str) -> list[Decimal]:
    """Round each value so the rounded values sum to the rounded total.

    The drift between independent rounding and the rounded total goes to the
    items whose rounding moved furthest against it: a cent added goes to the
    items rounded down the most, a cent taken to those rounded up the most, so
    a correction never pushes an item past zero. Ties break toward the larger
    magnitude, then the earlier item, which keeps the allocation deterministic.
    """
    if not values:
        return []
    scale = Decimal(1).scaleb(places)
    whole = Decimal(1)
    target = (sum(values, Decimal(0)) * scale).quantize(whole, rounding=rounding)
    units = [(v * scale).quantize(whole, rounding=rounding) for v in values]
    drift = int(target - sum(units))
    if drift:
        step = 1 if drift > 0 else -1
        order = sorted(range(len(values)),
                       key=lambda i: (step * (values[i] * scale - units[i]), abs(values[i])), reverse=True)
        for i in range(abs(drift)):
            units[order[i % len(values)]] += step
    return [u.scaleb(-places) for u in units]


# --- Helpers ----------------------------------------------------------------

class _IndexSchedule:
    """Selections and Cartesian indices owned by exactly one evaluation.

    Match filters by equality, since attribute values can be lists or mappings.
    Sharing products by dimensions/filter keeps the cache proportional to the
    distinct declared selections, rather than the number of variables.
    """

    def __init__(self, model: Model) -> None:
        self.model = model
        self.selections: dict[str, list[tuple[tuple, list]]] = {}
        self.products: dict[tuple[str, ...], list[tuple[tuple, list[Index]]]] = {}

    def keys(self, dim: str, where: tuple = ()) -> list:
        selections = self.selections.setdefault(dim, [])
        for selected, keys in selections:
            if selected == where:
                return keys
        keys = self.model.dimensions[dim].keys(where)
        selections.append((where, keys))
        return keys

    def indices(self, dims: tuple[str, ...], where: tuple = ()) -> list[Index]:
        products = self.products.setdefault(dims, [])
        for selected, indices in products:
            if selected == where:
                return indices
        indices = list(product(*(self.keys(d, where) for d in dims))) if dims else [()]
        products.append((where, indices))
        return indices


def _key(name: str, idx: Index) -> str:
    return f"{name}[{','.join(str(k) for k in idx)}]" if idx else name


def _digest(payload: Any) -> str:
    def norm(v: Any) -> Any:
        if isinstance(v, Decimal):
            return f"{v:f}"
        if isinstance(v, Mapping):
            return {str(k): norm(v[k]) for k in sorted(v, key=str)}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(norm(payload), separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()
