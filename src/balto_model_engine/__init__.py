"""Balto model engine: dimensional models as code, evaluated to runs."""

from .calendar import annual_calendar, excel_serial, monthly_calendar
from .evaluate import ENGINE, EngineError, Run, evaluate
from .expressions import (
    Expr, allocate_round, attr, const, if_, lag, mapped, matches, max_, min_, power, previous, ref, round_to,
    sum_over, sum_within, total,
)
from .metrics import xirr
from .model import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError

__all__ = [
    "ENGINE", "DecimalPolicy", "annual_calendar", "Dimension", "EngineError", "Expr", "Item", "Model",
    "ModelDefinitionError", "Run", "allocate_round", "attr", "const", "evaluate", "excel_serial", "if_", "lag", "mapped",
    "matches", "max_", "min_", "monthly_calendar", "power", "previous", "ref", "round_to", "sum_over", "sum_within", "total", "xirr",
]
