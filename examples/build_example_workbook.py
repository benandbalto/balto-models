"""Write the synthetic example deal's workbook: `python3 build_example_workbook.py out.xlsx`.

`--no-sensitivity` skips the return sensitivity grid, which reruns the model once per cell.
"""

import os
import sys

from balto_valuation.example import example_deal, example_inputs
from balto_valuation.workbook import irr_sensitivity, write_workbook

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "value-add-acquisition-example.xlsx"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    deal, inputs = example_deal(), example_inputs()
    sensitivity = None
    if "--no-sensitivity" not in sys.argv:
        sensitivity = irr_sensitivity(deal, inputs, ["0.0475", "0.05", "0.0525", "0.055", "0.0575"], [36, 48, 60, 72, 84])
    _, run, _ = write_workbook(deal, inputs, path, sensitivity=sensitivity)
    for name, metric in run.metrics.items():
        print(f"{name}: {float(metric['rate']):.2%}" if metric["status"] == "ok" else f"{name}: {metric['status']}")
    print(f"Wrote {path} (run {run.digest[:12]})")
