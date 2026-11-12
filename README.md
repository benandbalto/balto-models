# balto-models

Multifamily underwriting models that build Excel workbooks with live formulas:
value-add acquisitions and ground-up development (including a Seattle version
with the MFTE and MHA affordability programs).

Balto generates live Excel formulas from the same model it runs in Python. We
test that the two produce matching results, so the workbook is not a pasted
copy of the numbers. It is the model itself, and you can trace and change it.

## Try a model in Excel

Download a model, open it in desktop Excel, and change a blue input to see the
related calculations update. Start on the **Assumptions** sheet; some models
have blue inputs on other sheets too. Every
deal in these files is invented.

| Download | What it shows |
|---|---|
| [Value-add acquisition](https://raw.githubusercontent.com/benandbalto/balto-models/main/workbooks/value-add-acquisition.xlsx) | 64-unit mixed-income property: market-rate, 60% AMI and Section 8 units, interior renovations at turnover, refinance in year 3, sale in year 5, LP/GP waterfall |
| [Multifamily development](https://raw.githubusercontent.com/benandbalto/balto-models/main/workbooks/multifamily-development.xlsx) | 40-unit ground-up project: development budget, construction draws and interest, lease-up, permanent loan, funding gap, LP/GP waterfall |
| [Seattle development with MFTE and MHA](https://raw.githubusercontent.com/benandbalto/balto-models/main/workbooks/seattle-multifamily-development.xlsx) | 120-home Seattle mid-rise that opens on an Executive Summary comparing six program choices (none, MHA payment or performance, MFTE, and both): affordable homes, tenant rent savings, the City's MHA payment and MFTE tax exemption, and feasibility |

Excel recalculates each file when it opens it. If Excel opens it in Protected
View, click Enable Editing first.

## Underwrite with an AI agent

An AI agent can build these models and talk through the results with you. You
don't need to code. Allow about 20 minutes for the first setup; it works on
Windows, macOS and Linux.

1. **Install an AI coding agent** that can run commands on your computer:
   [Claude Code](https://claude.com/product/claude-code) or
   [OpenAI Codex](https://developers.openai.com/codex). Chat in a web browser
   can't run the models.
2. **Paste this prompt:**

> Set up https://github.com/benandbalto/balto-models in my Documents folder
   > by following its AGENTS.md. Then build the sample value-add acquisition
   > model, make a copy with the senior loan's interest rate half a percentage
   > point higher, and open both workbooks in Excel. Show me a short table
   > comparing the loan amount, DSCR and IRR.

   The agent checks what is installed, asks before installing anything it
   needs, builds the models, and compares the results.
3. **Underwrite a real deal.** Start a new agent session with the
   `balto-models` folder open, and tell it where your deal documents are, for
   example "Underwrite the deal in Documents/Deals/Elm Street", with your own
   folder in place of that one. It reads the offering memorandum, rent roll,
   T12 and term sheet, and records the source or assumption behind each
   input. Then keep going in conversation: "Use the lender's terms", "Show
   DSCR by year", "Make a downside case and compare it".

The models and workbooks stay on your computer. Your agent does send what it
reads to its AI provider, so check that your NDA and your firm allow that
before pointing it at a deal.

**[Read the getting-started guide](docs/getting-started.md)** for the full
walkthrough, example requests, and how to check the agent's work.

## The models

| Model | Id and version | Covers |
|---|---|---|
| Value-add acquisition | `value-add-acquisition` 0.5.0 | Unit-type cohorts, line-item operating budget, closing costs, phased capital budget, senior and subordinate debt (including an assumed loan), refinance, sale, LP/GP waterfall, commercial space |
| Multifamily development | `multifamily-development` 0.2.0 | Ground-up: development budget, construction draws and interest, lease-up, loan sizing, funding gaps, waterfall |
| Seattle development | `seattle-multifamily-development` 0.1.0 | The development model plus Seattle's MFTE (Program 7) tax exemption and MHA payment or performance, each toggled, with property tax and policy outcomes; see [the program rules](docs/seattle-mfte-mha.md) |

The models are used to underwrite real deals and change often. A changed
formula changes the model's version.

## Manual setup

Without an agent, you need Python 3.12 or newer and git.

macOS or Linux:

```sh
git clone https://github.com/benandbalto/balto-models
cd balto-models
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[excel]'
.venv/bin/python underwrite.py new value-add-acquisition deals/sample/model.json
.venv/bin/python underwrite.py run deals/sample/model.json
```

Windows (PowerShell):

```powershell
git clone https://github.com/benandbalto/balto-models
cd balto-models
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[excel]"
.venv\Scripts\python underwrite.py new value-add-acquisition deals\sample\model.json
.venv\Scripts\python underwrite.py run deals\sample\model.json
```

`run` prints the headline results and writes `model.xlsx` beside the model
file. `new` copies a model's synthetic example into a JSON file. Edit its
`deal` structure and `inputs`, then `check` or `run` it again. `inputs` lists
every input with its unit and bounds, and `find` and `values` read any
calculated figure. [AGENTS.md](AGENTS.md) describes the file format, including
how to record sources. `deals/` is ignored by git.

## For developers

### How it works

A model is a set of named variables declared over dimensions (months, years,
unit types, loans). Each variable is an input, a source, or a single
calculation written once in a small, closed expression language. The engine
evaluates a model with exact decimal arithmetic and returns a `Run`. The run
holds every value, the lineage of each one, and a SHA-256 digest over the
model's structure and values. Each expression has exactly one Excel
equivalent, so the workbook compiler writes every calculation as a formula
rather than a pasted number. A parity check recalculates the compiled
workbook independently (with pycel) and compares it with the Python run.

The engine and models use only the Python standard library. Writing workbooks
needs `openpyxl`; parity checks also need `pycel`
(`pip install -e '.[parity]'`). Versions follow each model's
`MODEL_VERSION`; a changed formula changes the version and the run digest.

| Model | Example | Workbook |
|---|---|---|
| Value-add | `balto_valuation.example` | `balto_valuation.workbook.write_workbook` |
| Development | `balto_development.example` | `balto_development.workbook.write_workbook` |
| Seattle development | `balto_development.seattle_example` | `balto_development.seattle.write_workbook` |

### Python

```python
from balto_model_engine import evaluate
from balto_valuation import build_model
from balto_valuation.example import example_deal, example_inputs
from balto_valuation.workbook import write_workbook

deal, inputs = example_deal(), example_inputs()
run = evaluate(build_model(deal), inputs)
print(run.metrics["levered_irr"]["rate"])

write_workbook(deal, inputs, "value-add.xlsx", sponsor="Example Partners")
```

```sh
PYTHONPATH=src python3 examples/build_workbooks.py out    # all four example workbooks
```

### JSON service

`python3 -m balto_valuation.service` reads one JSON request on stdin and
writes one JSON response. On Linux it runs under 45-second CPU and 768 MB
memory limits; on macOS it applies the CPU limit only. It makes no network calls and writes only to a
temporary directory. `describe` returns a model's inputs with their units and
bounds. `validate`
checks a snapshot. `run` returns the run and a base64 workbook.
`underwrite.py` is a thin command line over this service.

```sh
python3 underwrite.py new development /tmp/development.json
python3 -c 'import json; f = json.load(open("/tmp/development.json")); print(json.dumps({"contractVersion": "1", "operation": "describe", "snapshot": {"deal": f["deal"], "inputs": f["inputs"]}}))' \
  | PYTHONPATH=src python3 -m balto_valuation.service
```

### Tests

```sh
python3 -m pip install -r requirements-test.txt
PYTHONPATH=src python3 -m unittest discover -s tests/engine
PYTHONPATH=src python3 -m unittest discover -s tests/valuation
```

Without `openpyxl` and `pycel`, the workbook and parity tests are skipped.

## Data

Every example and test fixture here is synthetic. Rent limits, utility
allowances, fair market rents and basis limits are placeholders shaped like
published tables, not official figures. Nothing here is a real deal, a quote,
or investment, tax or legal advice.

## Get involved

Balto develops these models in a private repository and releases them here,
so changes land there first. We still want to hear what you build:

- **Something gives an unexpected answer?** Open an issue with a model file
  that reproduces it and the result you expected. Use invented or anonymized
  figures, never a confidential deal.
- **Built a fork, a new financing structure, or a model for a deal type we
  don't cover?** Open an issue that links to it. We port what fits and
  credit you.
- **Pull requests** are welcome as proposals. We apply them by hand in the
  source repository and credit the author.

## License

Copyright 2026 Great Expectations SPC

Licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE).
