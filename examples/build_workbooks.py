"""Write the live-formula workbook for every model's synthetic example.

    PYTHONPATH=src python3 examples/build_workbooks.py workbooks
    PYTHONPATH=src python3 examples/build_workbooks.py --check workbooks   # CI

Every deal, figure and name in these workbooks is invented. The files are
normalized (fixed timestamps), so rebuilding unchanged models gives identical
bytes. The committed copies in workbooks/ are produced by this script.
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

FIXED = "2000-01-01T00:00:00Z"
# The "Prepared" date on overview sheets; bump it when the examples change materially.
os.environ["SOURCE_DATE_EPOCH"] = "1794182400"  # 2026-11-09
SPONSOR = "Synthetic example"
WORKBOOKS = (
    "value-add-acquisition.xlsx",
    "multifamily-development.xlsx",
    "seattle-multifamily-development.xlsx",
)


def normalize(path: Path) -> None:
    """Pin the zip entry dates and document timestamps so builds are reproducible."""
    with zipfile.ZipFile(path) as source:
        entries = [(info.filename, source.read(info)) for info in source.infolist()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in entries:
            if name == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>" + FIXED.encode(), data)
            target.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
    path.write_bytes(buffer.getvalue())


def build(out: Path) -> list[Path]:
    from balto_development.example import example_deal as development_deal, example_inputs as development_inputs
    from balto_development.workbook import write_workbook as write_development
    from balto_development import seattle, seattle_example
    from balto_valuation.example import example_deal, example_inputs
    from balto_valuation.workbook import write_workbook

    out.mkdir(parents=True, exist_ok=True)
    paths = [out / name for name in WORKBOOKS]
    write_workbook(example_deal(), example_inputs(), str(paths[0]), sponsor=SPONSOR)
    write_development(development_deal(), development_inputs(), str(paths[1]))
    seattle.write_workbook(seattle_example.example_deal(), seattle_example.example_inputs(), str(paths[2]))
    for path in paths:
        normalize(path)
    return paths


def contents(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as book:
        return {name: book.read(name) for name in book.namelist()}


def check(committed: Path) -> int:
    """Rebuild into a temporary directory and compare each workbook's parts with the committed copy."""
    with tempfile.TemporaryDirectory() as tmp:
        stale = [path.name for path in build(Path(tmp))
                 if not (committed / path.name).exists() or contents(path) != contents(committed / path.name)]
    for name in stale:
        print(f"stale: {committed / name}; rebuild with examples/build_workbooks.py", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--check"]:
        sys.exit(check(Path(args[1] if len(args) > 1 else "workbooks")))
    for written in build(Path(args[0] if args else "workbooks")):
        print(written)
