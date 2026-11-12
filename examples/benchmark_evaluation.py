"""Repeatable synthetic evaluation benchmark.

Run with PYTHONPATH=src. Save a baseline
with --output, then use --baseline to compare every Run field after a change.
Wall time, traced memory and profiling are separate runs to avoid conflating
instrumentation overhead with ordinary evaluation latency.
"""

import argparse
import cProfile
from dataclasses import asdict, replace
import gc
import json
from pathlib import Path
import pickle
import pstats
from statistics import median
from time import perf_counter
import tracemalloc

from balto_model_engine import evaluate
from balto_valuation import build_model
from balto_valuation.example import example_deal, example_inputs


def fixture(copies):
    deal, inputs = example_deal(), example_inputs()
    if copies == 1:
        return deal, inputs
    cohorts = {c.key for c in deal.cohorts}
    for name, value in list(inputs.items()):
        if isinstance(value, dict) and set(value) <= cohorts:
            inputs[name] = {f"{key}_{i}": amount for i in range(copies)
                            for key, amount in value.items()}
    return replace(deal, cohorts=tuple(replace(c, key=f"{c.key}_{i}")
                                      for i in range(copies) for c in deal.cohorts)), inputs


def benchmark(copies, repeats):
    deal, inputs = fixture(copies)
    start = perf_counter()
    model = build_model(deal)
    assembly = perf_counter() - start
    expected = evaluate(model, inputs)
    elapsed = []
    for _ in range(repeats):
        start = perf_counter()
        actual = evaluate(model, inputs)
        elapsed.append(perf_counter() - start)
        assert actual == expected, "Repeated evaluations changed the run."
    del actual
    gc.collect()
    tracemalloc.start()
    actual = evaluate(model, inputs)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert actual == expected
    profile = cProfile.Profile()
    profile.runcall(evaluate, model, inputs)
    stats = pstats.Stats(profile).stats
    calls = {
        "dimension_selections": sum(row[1] for (file, _, function), row in stats.items()
                                    if file.endswith("/model.py") and function == "keys"),
        "index_requests": sum(row[1] for (file, _, function), row in stats.items()
                              if file.endswith("/evaluate.py") and function in ("_indices", "indices")),
    }
    metric_seconds = sum(row[2] for (file, _, _), row in stats.items()
                         if file.endswith("/metrics.py"))
    return {"cohorts": len(deal.cohorts), "variables": len(model.variables),
            "values": sum(len(v) for v in expected.values.values()),
            "assembly_seconds": assembly, "evaluation_seconds": elapsed,
            "median_seconds": median(elapsed), "peak_bytes": peak,
            "profile_calls": calls, "profile_metric_self_seconds": metric_seconds,
            "digest": expected.digest}, asdict(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-selection-calls", type=int)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    results, runs = {}, {}
    for name, copies in (("example", 1), ("large_cohort", 4)):
        results[name], runs[name] = benchmark(copies, args.repeats)
    # Local synthetic snapshots only; never load an untrusted pickle.
    if args.baseline:
        baseline_runs = pickle.loads(args.baseline.with_suffix(".pickle").read_bytes())
        assert runs == baseline_runs, "A Run field differs from the baseline."
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    args.output.with_suffix(".pickle").write_bytes(pickle.dumps(runs))
    print(json.dumps(results, indent=2))
    if args.max_selection_calls is not None:
        assert all(r["profile_calls"]["dimension_selections"] <= args.max_selection_calls
                   for r in results.values()), "Dimension selection calls exceed --max-selection-calls."


if __name__ == "__main__":
    main()
