#!/usr/bin/env python3
"""Underwrite a deal from one JSON file: start from a model's example, edit, run.

    python3 underwrite.py models                         # the models
    python3 underwrite.py new value-add-acquisition ~/Deals/Elm/model.json
    python3 underwrite.py inputs ~/Deals/Elm/model.json  # every input, unit, bound and value
    python3 underwrite.py check ~/Deals/Elm/model.json   # validate and print results
    python3 underwrite.py run ~/Deals/Elm/model.json     # also write model.xlsx beside it
    python3 underwrite.py find ~/Deals/Elm/model.json dscr
    python3 underwrite.py values ~/Deals/Elm/model.json levered_irr noi

A model file holds the model's deal structure and inputs, plus optional notes
and sources. Each source records where an input came from and is written to
the workbook's Input Basis sheet:

    {"deal": {...}, "inputs": {...},
     "notes": "Broker OM pricing, 2026 T12",
     "sources": {"purchase_price": {"kind": "document", "reason": "Asking price",
                                    "references": ["OM.pdf p.4"]}}}

The new command starts from a model's synthetic example, so every figure in a
fresh file is invented and needs replacing with the deal's own.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

MODELS = {
    "value-add-acquisition": ("value_add", "Value-add acquisition: market-rate or mixed-income, renovation, refinance, sale, LP/GP waterfall"),
    "multifamily-development": ("development", "Multifamily development: ground-up budget, construction loan, lease-up, waterfall"),
    "seattle-multifamily-development": ("seattle_development", "Seattle development: ground-up with MFTE and MHA (payment or performance) toggles and policy outcomes"),
}
ALIASES = {"value-add": "value-add-acquisition",
           "development": "multifamily-development", "seattle": "seattle-multifamily-development"}
# Figures printed after check and run, when the model has them (the workbook shows them all).
ACQUISITION = ("total_uses", "senior.amount", "senior.ltv_amount", "senior.dscr_amount", "equity_at_close", "price_per_unit", "going_in_cap_rate", "yield_on_cost",
               "sale.price", "equity_multiple", "lp_multiple", "levered_profit", "capital_calls_after_close")
HEADLINES = {
    "value_add": ACQUISITION,
    "development": ("project_cost", "total_equity_required", "peak_equity", "total_interest", "total_funding_gap"),
    "seattle_development": ("project_cost", "mha.payment", "policy.restricted_homes", "policy.rent_savings",
                            "policy.mfte_exemption_annual", "policy.mfte_exemption_term", "policy.yield_on_cost",
                            "peak_equity", "total_funding_gap"),
}
SHOWN_ROWS = 40
MULTIPLES = ("dscr", "multiple", "coverage")


def service(operation: str, snapshot: dict, context: dict | None = None) -> dict:
    request = {"contractVersion": "1", "operation": operation, "snapshot": snapshot, "context": context or {}}
    env = os.environ | {"PYTHONPATH": os.pathsep.join(filter(None, (str(SRC), os.environ.get("PYTHONPATH"))))}
    done = subprocess.run([sys.executable, "-m", "balto_valuation.service"], input=json.dumps(request),
                          text=True, encoding="utf-8", capture_output=True, env=env)
    if not done.stdout:
        raise SystemExit(done.stderr.strip() or "The model service returned nothing.")
    response = json.loads(done.stdout)
    if response["status"] == "invalid":
        finding = response["finding"]
        where = f" ({finding['key']})" if finding.get("key") else ""
        cause = diagnose(operation, snapshot, context or {}) if finding.get("code") == "VALIDATION_ERROR" else ""
        raise SystemExit(f"Invalid {finding.get('code', '')}{where}: {finding['message']}" + (f" Cause: {cause}" if cause else ""))
    if response["status"] != "succeeded":
        raise SystemExit(f"Model failed: {response.get('error') or response}")
    return response["result"]


def diagnose(operation: str, snapshot: dict, context: dict) -> str:
    """Repeat the service's operation in this process to recover the reason it withholds."""
    import tempfile
    import traceback
    from balto_model_engine import evaluate
    from balto_valuation import service as engine
    kind = snapshot["deal"].get("kind")
    try:
        if kind == "development":
            from balto_development.deal import read_deal
            from balto_development.model import build_model
            from balto_development.workbook import write_workbook
            deal = read_deal(snapshot["deal"])
        elif kind == "seattle_development":
            from balto_development.deal import read_deal
            from balto_development.seattle import build_model, write_workbook
            deal = read_deal(snapshot["deal"], kind)
        else:
            from balto_valuation.model import build_model
            from balto_valuation.workbook import write_workbook
            deal = engine.read_deal(snapshot["deal"])
        model = build_model(deal)
        if operation == "run":
            with tempfile.TemporaryDirectory() as directory:
                write_workbook(deal, snapshot["inputs"], str(Path(directory) / "model.xlsx"))
        else:
            evaluate(model, snapshot["inputs"])
    except Exception as error:  # Any reason is more useful than none.
        where = traceback.extract_tb(error.__traceback__)[-1]
        return f"{type(error).__name__}: {error} (at {Path(where.filename).name}:{where.lineno})"
    return ""


def plain(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot write {type(value).__name__}")


def example(model: str) -> dict:
    kind = MODELS[model][0]
    if kind == "value_add":
        from balto_valuation.example import example_deal, example_inputs
    elif kind == "seattle_development":
        from balto_development.seattle_example import example_deal, example_inputs
    else:
        from balto_development.example import example_deal, example_inputs
    deal = dataclasses.asdict(example_deal())
    if kind != "value_add":
        deal = {"kind": kind} | deal
    return json.loads(json.dumps({"deal": deal, "inputs": example_inputs()}, default=plain))


def load(path: Path) -> tuple[dict, dict]:
    """Return the service snapshot and workbook context for a model file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - {"deal", "inputs", "notes", "sources"}
    if unknown or not {"deal", "inputs"} <= set(data):
        raise SystemExit(f"{path}: expected deal, inputs and optional notes and sources; found {sorted(data)}")
    sources = data.get("sources", {})
    for key, source in sources.items():
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or not isinstance(source.get("reason"), str):
            raise SystemExit(f'{path}: source for {key} needs "kind" and "reason" text (and optional "references")')
    return {"deal": data["deal"], "inputs": data["inputs"]}, {"note": data.get("notes", ""), "basis": sources}


def describe(snapshot: dict) -> list[dict]:
    return service("describe", snapshot)["model"]["variables"]


def number(value: str, unit: str, name: str = "") -> str:
    """Format a value for reading: multiples and coverage as 1.25x, other rates and ratios as percent."""
    amount = Decimal(value)
    if unit.split("/")[0] in ("ratio", "nominal_ratio") and any(word in name for word in MULTIPLES):
        return f"{amount:.2f}x"
    if unit.split("/")[0] in ("rate", "ratio", "nominal_ratio"):
        return f"{amount * 100:.2f}%"
    return f"{amount:,.2f}" if amount != amount.to_integral() else f"{amount:,.0f}"


def kind(snapshot: dict) -> str:
    return snapshot["deal"].get("kind", "value_add")


def summary(snapshot: dict, run: dict) -> None:
    print(f"{run['modelId']} {run['modelVersion']}  digest {run['digest'][:12]}")
    units = {variable["name"]: variable.get("unit") for variable in describe(snapshot)}
    for name in HEADLINES[kind(snapshot)]:
        rows = run["values"].get(name)
        if rows and len(rows) == 1:
            print(f"  {name}: {number(rows[0]['value'], units.get(name) or '', name)}")
    for name, metric in run["metrics"].items():
        if metric.get("status") == "ok" and "rate" in metric:
            print(f"  {name}: {number(metric['rate'], 'rate')}")
        else:
            print(f"  {name}: {metric.get('status')}")
    for name in ("fundingStatus", "returnAvailability"):
        if name in run:
            print(f"  {name}: {run[name]}")
    if not run["tests"]:
        return
    failed = {name: test for name, test in run["tests"].items() if not test.get("passed")}
    passed = len(run["tests"]) - len(failed)
    print(f"Checks: {passed} passed, {len(failed)} flagged")
    for name, test in failed.items():
        first = test.get("firstBreach")
        print(f"  {name}: {test.get('message', test.get('code', ''))}" + (f" First: {first}" if first else ""))


def index(row: dict) -> str:
    return ", ".join(str(part) for part in row["index"]) or "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("models", help="list the models")
    new = commands.add_parser("new", help="start a model file from a model's synthetic example")
    new.add_argument("model", choices=[*MODELS, *ALIASES], metavar="MODEL",
                     help="one of: " + ", ".join(MODELS))
    new.add_argument("file", type=Path)
    for name, text in (("inputs", "list every input with unit, bounds and current value"),
                       ("check", "validate and print results"), ("run", "validate and write the workbook")):
        command = commands.add_parser(name, help=text)
        command.add_argument("file", type=Path)
    commands.choices["run"].add_argument("--out", type=Path, help="workbook path (default: beside the model file)")
    find = commands.add_parser("find", help="find inputs and calculations by name")
    find.add_argument("file", type=Path)
    find.add_argument("text")
    values = commands.add_parser("values", help="print the calculated values of named variables")
    values.add_argument("file", type=Path)
    values.add_argument("names", nargs="+")
    values.add_argument("--all", action="store_true", help=f"print every row, not the first {SHOWN_ROWS}")
    args = parser.parse_args()
    args.file = args.file.expanduser() if getattr(args, "file", None) else None

    if args.command == "models":
        for name, (_, text) in MODELS.items():
            print(f"{name:32} {text}")
        return
    if args.command == "new":
        args.model = ALIASES.get(args.model, args.model)
        if args.file.exists():
            raise SystemExit(f"{args.file} already exists; choose another name or delete it first.")
        args.file.parent.mkdir(parents=True, exist_ok=True)
        args.file.write_text(json.dumps(example(args.model) | {"notes": "", "sources": {}}, indent=2) + "\n",
                             encoding="utf-8")
        print(f"Wrote {args.file} from the synthetic {args.model} example. Replace its figures with the deal's.")
        return

    snapshot, context = load(args.file)
    if args.command == "inputs":
        given = snapshot["inputs"]
        for variable in describe(snapshot):
            if variable["kind"] != "input":
                continue
            low, high = variable.get("minimum"), variable.get("maximum")
            bounds = f"{low}..{high}" if low and high else f">= {low}" if low else f"<= {high}" if high else "-"
            current = given.get(variable["name"])
            shown = f"{len(current)} rows" if isinstance(current, list) else current
            dims = f"[{', '.join(variable['dims'])}]" if variable["dims"] else ""
            print(f"{variable['name']}{dims}  unit={variable.get('unit')}  bounds={bounds}  value={shown}")
    elif args.command == "find":
        for variable in describe(snapshot):
            if args.text.lower() in variable["name"].lower():
                dims = f"[{', '.join(variable['dims'])}]" if variable["dims"] else ""
                print(f"{variable['name']}{dims}  {variable['kind']}  unit={variable.get('unit')}")
    elif args.command == "values":
        units = {variable["name"]: variable.get("unit") for variable in describe(snapshot)}
        run = service("validate", snapshot)["run"]
        for name in args.names:
            if name in run["metrics"]:
                metric = run["metrics"][name]
                print(f"{name}: {number(metric['rate'], 'rate') if 'rate' in metric else metric.get('status')}")
                continue
            if name not in run["values"]:
                raise SystemExit(f"No variable {name}; search with: underwrite.py find {args.file} TEXT")
            rows = run["values"][name]
            if len(rows) == 1 and not rows[0]["index"]:
                print(f"{name}: {number(rows[0]['value'], units.get(name) or '', name)} ({units.get(name)})")
                continue
            print(f"{name} ({units.get(name)})")
            for row in rows if args.all else rows[:SHOWN_ROWS]:
                print(f"  {index(row)}: {number(row['value'], units.get(name) or '', name)}")
            if len(rows) > SHOWN_ROWS and not args.all:
                print(f"  ... {len(rows) - SHOWN_ROWS} more rows (add --all)")
    elif args.command == "check":
        summary(snapshot, service("validate", snapshot)["run"])
    else:
        names = {variable["name"] for variable in describe(snapshot)}
        unknown = sorted(key for key in context["basis"] if key not in names and not key.startswith("deal."))
        if unknown:
            print(f"Warning: sources for unknown inputs (check the spelling): {', '.join(unknown)}")
        result = service("run", snapshot, context)
        out = args.out.expanduser() if args.out else args.file.with_suffix(".xlsx")
        out.write_bytes(base64.b64decode(result["workbookBase64"]))
        summary(snapshot, result["run"])
        print(f"Wrote {out}. Open it in desktop Excel, which recalculates it on open.")


if __name__ == "__main__":
    main()
