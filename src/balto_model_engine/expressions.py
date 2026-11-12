"""The engine's closed expression set.

Every calculation in every model is built from these nodes and nothing else.
The set is deliberately small: each node must have one evaluation here and, for
the workbook compiler, one Excel equivalent. A new node is an engine release,
never a per-model convenience.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterator, Union

Number = Union[int, str, Decimal]


class Expr:
    """Base node. Operators build new nodes; nothing is evaluated here."""

    # Comparison operators build Compare nodes, so identity is the only safe
    # hash; nodes are never used as set members by value.
    __hash__ = object.__hash__

    def __add__(self, other): return Binary("+", self, _lift(other))
    def __radd__(self, other): return Binary("+", _lift(other), self)
    def __sub__(self, other): return Binary("-", self, _lift(other))
    def __rsub__(self, other): return Binary("-", _lift(other), self)
    def __mul__(self, other): return Binary("*", self, _lift(other))
    def __rmul__(self, other): return Binary("*", _lift(other), self)
    def __truediv__(self, other): return Binary("/", self, _lift(other))
    def __rtruediv__(self, other): return Binary("/", _lift(other), self)
    def __neg__(self): return Neg(self)

    def __eq__(self, other): return Compare("=", self, _lift(other))  # type: ignore[override]
    def __ne__(self, other): return Compare("<>", self, _lift(other))  # type: ignore[override]
    def __lt__(self, other): return Compare("<", self, _lift(other))
    def __le__(self, other): return Compare("<=", self, _lift(other))
    def __gt__(self, other): return Compare(">", self, _lift(other))
    def __ge__(self, other): return Compare(">=", self, _lift(other))

    def __bool__(self):
        # `if ref("a") == 0:` in model code would silently take a branch at
        # definition time; conditions belong in if_().
        raise TypeError("An expression has no truth value; use if_() for conditions.")

    def children(self) -> tuple["Expr", ...]:
        return ()

    def walk(self) -> Iterator["Expr"]:
        yield self
        for child in self.children():
            yield from child.walk()

    # Rendering precedence: higher binds tighter.
    precedence = 9


class Const(Expr):
    def __init__(self, value: Number) -> None:
        if isinstance(value, (bool, float)):
            raise TypeError("A constant must be an int, a decimal string, or a Decimal.")
        self.value = Decimal(str(value)) if not isinstance(value, Decimal) else value

    def __str__(self) -> str:
        return f"{self.value:f}"


class Ref(Expr):
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class Binary(Expr):
    PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}

    def __init__(self, op: str, left: Expr, right: Expr) -> None:
        self.op, self.left, self.right = op, left, right
        self.precedence = self.PRECEDENCE[op]

    def children(self):
        return (self.left, self.right)

    def __str__(self) -> str:
        left = _paren(self.left, self.left.precedence < self.precedence)
        # Subtraction and division are not associative, so an equal-precedence
        # right operand keeps its parentheses.
        right = _paren(self.right, self.right.precedence < self.precedence
                       or (self.right.precedence == self.precedence and self.op in "-/"))
        return f"{left} {self.op} {right}"


class Neg(Expr):
    precedence = 3

    def __init__(self, operand: Expr) -> None:
        self.operand = operand

    def children(self):
        return (self.operand,)

    def __str__(self) -> str:
        return f"-{_paren(self.operand, self.operand.precedence < self.precedence)}"


class Condition(Expr):
    """A node with a truth value: valid only as an if_() or check condition."""
    precedence = 0


class Compare(Condition):

    def __init__(self, op: str, left: Expr, right: Expr) -> None:
        self.op, self.left, self.right = op, left, right

    def children(self):
        return (self.left, self.right)

    def __str__(self) -> str:
        return f"{self.left} {self.op} {self.right}"


class Matches(Condition):
    """True when the current item of `dim` has every given attribute value.

    Attributes are structure, fixed when the model is defined, so a compiled
    workbook resolves the condition per cell rather than evaluating it.
    """

    def __init__(self, dim: str, where: dict[str, object]) -> None:
        self.dim, self.where = dim, tuple(sorted(where.items()))

    def __str__(self) -> str:
        return f"{self.dim}{_filter(self.where)}"


class If(Expr):
    def __init__(self, condition: Condition, then: Expr, otherwise: Expr) -> None:
        self.condition, self.then, self.otherwise = condition, then, otherwise

    def children(self):
        return (self.condition, self.then, self.otherwise)

    def __str__(self) -> str:
        return f"if({self.condition}, {self.then}, {self.otherwise})"


class Sum(Expr):
    """Sum of `body` over the items of `dim`, optionally filtered by item attributes."""

    def __init__(self, dim: str, body: Expr, where: dict[str, object]) -> None:
        self.dim, self.body = dim, body
        self.where = tuple(sorted(where.items()))

    def children(self):
        return (self.body,)

    def __str__(self) -> str:
        return f"sum({self.dim}{_filter(self.where)}: {self.body})"


class SumWithin(Expr):
    """Sum of `body` over the items of `dim` that belong to the current item of its parent."""

    def __init__(self, dim: str, body: Expr, where: dict[str, object]) -> None:
        self.dim, self.body = dim, body
        self.where = tuple(sorted(where.items()))

    def children(self):
        return (self.body,)

    def __str__(self) -> str:
        return f"sum_within({self.dim}{_filter(self.where)}: {self.body})"


class Prior(Expr):
    """`name` at the previous item of `dim`. Only valid inside a Previous step."""

    def __init__(self, name: str, dim: str) -> None:
        self.name, self.dim = name, dim

    def __str__(self) -> str:
        return f"prior({self.name})"


class Previous(Expr):
    """A recurrence along an ordered dimension.

    At the first item of `dim` the value is `initial`; at every other item it is
    `step`, in which `prior(name)` is `name` at the previous item. A variable may
    recur on itself this way, which is how a balance or a rent carries forward
    month to month without a declared solve block.
    """

    def __init__(self, name: str, dim: str, initial: Expr, step: Expr) -> None:
        self.name, self.dim, self.initial, self.step = name, dim, initial, step

    def children(self):
        return (self.initial, self.step)

    def __str__(self) -> str:
        return f"previous({self.dim}, initial={self.initial}, step={self.step})"


class Lag(Expr):
    """`name` at the previous item of `dim`; `initial` at the first item.

    Unlike `previous()`, a lag may read any variable, including one that reads
    the lagging variable in the same item. A lag is not a same-item dependency,
    so variables linked only through lags form a recurrence block that the
    engine evaluates item by item along `dim` (a loan's balance, its interest
    and the cash that repays it). In a workbook it is the previous column.
    """

    def __init__(self, name: str, dim: str, initial: Expr) -> None:
        self.name, self.dim, self.initial = name, dim, initial

    def children(self):
        return (self.initial,)

    def __str__(self) -> str:
        return f"lag({self.name}, {self.dim}, initial={self.initial})"


class Power(Expr):
    """`base` raised to `exponent`. A fractional power of a negative base is undefined."""

    def __init__(self, base: Expr, exponent: Expr) -> None:
        self.base, self.exponent = base, exponent

    def children(self):
        return (self.base, self.exponent)

    def __str__(self) -> str:
        return f"power({self.base}, {self.exponent})"


class Extreme(Expr):
    """The least (`min`) or greatest (`max`) of two or more expressions."""

    def __init__(self, op: str, args: tuple[Expr, ...]) -> None:
        self.op, self.args = op, args

    def children(self):
        return self.args

    def __str__(self) -> str:
        return f"{self.op}({', '.join(str(a) for a in self.args)})"


class Attr(Expr):
    """A numeric attribute of the current item of `dim`, such as a month's day count.

    Attributes are structure, so a compiled workbook reads them from the
    dimension's header rather than from a calculation.
    """

    def __init__(self, dim: str, name: str) -> None:
        self.dim, self.name = dim, name

    def __str__(self) -> str:
        return f"{self.dim}.{self.name}"


class Mapped(Expr):
    """Sum of `body` over the source items a mapping assigns to `target`, each with its sign."""

    def __init__(self, mapping: str, target: str, body: Expr) -> None:
        self.mapping, self.target, self.body = mapping, target, body

    def children(self):
        return (self.body,)

    def __str__(self) -> str:
        return f"mapped({self.mapping} -> {self.target}: {self.body})"


class Round(Expr):
    """Round to `places` decimal places with the model's rounding mode."""

    def __init__(self, body: Expr, places: int) -> None:
        self.body, self.places = body, places

    def children(self):
        return (self.body,)

    def __str__(self) -> str:
        return f"round({self.body}, {self.places})"


class AllocateRound(Expr):
    """Round each item of `dim` so the items sum to their rounded total.

    Independent rounding gains or loses cents against the total; this is the
    largest-remainder allocation, so a line's months always tie to its annual.
    """

    def __init__(self, body: Expr, dim: str, places: int) -> None:
        self.body, self.dim, self.places = body, dim, places

    def children(self):
        return (self.body,)

    def __str__(self) -> str:
        return f"allocate_round({self.body}, {self.dim}, {self.places})"


def _lift(value) -> Expr:
    return value if isinstance(value, Expr) else Const(value)


def _filter(where: tuple) -> str:
    # The rendering is digested, so attribute values keep their type: True and
    # "True" select different items and must not read alike.
    return "".join(f"[{k}={v!r}]" for k, v in where)


def _paren(e: Expr, wrap: bool) -> str:
    return f"({e})" if wrap else str(e)


# --- The public constructors models are written with. -----------------------

def const(value: Number) -> Const:
    return Const(value)


def ref(name: str) -> Ref:
    return Ref(name)


def if_(condition: Condition, then: Expr | Number, otherwise: Expr | Number) -> If:
    if not isinstance(condition, Condition):
        raise TypeError("if_() takes a comparison as its condition.")
    return If(condition, _lift(then), _lift(otherwise))


def sum_over(dim: str, body: Expr, **where: object) -> Sum:
    return Sum(dim, body, where)


def total(*names: str) -> Expr:
    """The sum of named variables, in the order given."""
    if not names:
        return Const(0)
    out: Expr = Ref(names[0])
    for name in names[1:]:
        out = out + Ref(name)
    return out


def round_to(body: Expr, places: int) -> Round:
    return Round(_lift(body), places)


def allocate_round(body: Expr, dim: str, places: int) -> AllocateRound:
    return AllocateRound(_lift(body), dim, places)


def lag(name: str, dim: str, *, initial: Expr | Number) -> Lag:
    """`name` one item back along `dim`, or `initial` at the first item."""
    return Lag(name, dim, _lift(initial))


def power(base: Expr | Number, exponent: Expr | Number) -> Power:
    return Power(_lift(base), _lift(exponent))


def min_(*args: Expr | Number) -> Extreme:
    if len(args) < 2:
        raise TypeError("min_() takes at least two expressions.")
    return Extreme("min", tuple(_lift(a) for a in args))


def max_(*args: Expr | Number) -> Extreme:
    if len(args) < 2:
        raise TypeError("max_() takes at least two expressions.")
    return Extreme("max", tuple(_lift(a) for a in args))


def attr(dim: str, name: str) -> Attr:
    """The numeric attribute `name` of the current item of `dim`."""
    return Attr(dim, name)


def mapped(mapping: str, target: str, body: Expr) -> Mapped:
    """The items `mapping` assigns to `target`, summed with their signs."""
    return Mapped(mapping, target, _lift(body))


def sum_within(dim: str, body: Expr, **where: object) -> SumWithin:
    """The items of `dim` under the current item of its parent dimension, optionally filtered."""
    return SumWithin(dim, _lift(body), where)


def matches(dim: str, **where: object) -> Matches:
    """A condition on the current item of `dim`'s attributes."""
    if not where:
        raise TypeError("matches() needs at least one attribute.")
    return Matches(dim, where)


def previous(name: str, dim: str, *, initial: Expr | Number, step=None) -> Previous:
    """`initial` at the first item of `dim`; elsewhere `step(prior)`, prior being `name` one item back.

    Without a step the value is simply `name` at the previous item.
    """
    prior = Prior(name, dim)
    body = prior if step is None else step(prior)
    return Previous(name, dim, _lift(initial), _lift(body))
