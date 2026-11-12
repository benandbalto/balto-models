# Instructions for AI agents

You are helping a real estate professional underwrite a deal with these
models. They may not be technical. Do the setup and the commands yourself,
speak in underwriting terms (rent, NOI, DSCR, IRR, basis, credits), and show
figures rather than code. They will steer you in conversation; keep the model
file and the workbook up to date as they do.

## Set up (once)

The models run natively on Windows, macOS and Linux. Windows does not need
WSL. Ask before installing anything, and say what it is for.

1. **Python 3.12 or newer.** Check with `python3 --version` (macOS, Linux)
   or `py --version` (Windows). If it is missing or older, install it: on
   Windows `winget install Python.Python.3.12`, on macOS the installer from
   https://www.python.org/downloads/. On a work laptop without admin rights,
   the python.org installer's "just for me" option needs none.
2. **git**, to clone and update. On Windows `winget install Git.Git`; on
   macOS, running `git` offers to install the command line developer tools.
3. **Clone and install**, from the folder the user chose:

   ```sh
   git clone https://github.com/benandbalto/balto-models
   cd balto-models
   python3 -m venv .venv                      # Windows: py -m venv .venv
   .venv/bin/python -m pip install -e '.[excel]'
   .venv/bin/python underwrite.py models
   ```

Use the venv's Python for every command below: `.venv/bin/python` on macOS
and Linux, `.venv\Scripts\python` on Windows. The examples use the first. Run
`git pull` when the user asks for the latest models; a model's version and
results can change.

## The sample

When the user asks for "the sample" or wants to try the models first, use a
model's synthetic example in `deals/sample/` inside this repository, which git
ignores:

```sh
.venv/bin/python underwrite.py new value-add-acquisition deals/sample/model.json
.venv/bin/python underwrite.py run deals/sample/model.json
```

To change an assumption, copy the file (for example to
`model-rate-plus-50bp.json`), edit the input, `run` the copy, and compare the
two in a short table. The value-add senior loan's interest rate is
`senior.rate`; `find FILE senior.` lists the rest of the loan's inputs and
results.

**Opening a workbook in Excel:** `open FILE.xlsx` on macOS, `start "" FILE.xlsx`
on Windows. Otherwise give the user the full path. Excel recalculates the
workbook on open; if Excel shows Protected View, the user needs to click
Enable Editing.

## The workflow

All work goes through `underwrite.py`. A deal is one JSON model file, kept in
the user's deal folder, never in this repository.

```sh
.venv/bin/python underwrite.py new MODEL DEAL/underwriting/model.json
.venv/bin/python underwrite.py inputs DEAL/underwriting/model.json
.venv/bin/python underwrite.py check DEAL/underwriting/model.json
.venv/bin/python underwrite.py run DEAL/underwriting/model.json     # writes model.xlsx beside it
.venv/bin/python underwrite.py find DEAL/underwriting/model.json dscr
.venv/bin/python underwrite.py values DEAL/underwriting/model.json annual.dscr noi
```

1. **Read the deal folder.** List what is there and read it: offering
   memorandum, rent roll, trailing-12 operating statement, budget, loan term
   sheet, scope of work, appraisal, regulatory agreement. Tell the user what you found and what is missing.
2. **Pick the model** (below) and confirm it with the user in one line.
3. **Start the model file** with `new`. It is a copy of the model's synthetic
   example, so every figure in it is invented until you replace it.
4. **Set the structure first** (the `deal` object): name, closing date, hold
   horizon, unit types, rent cohorts, operating expense lines, loans, capital
   phases, commercial spaces. The development model has phases and spending
   periods instead.
   The structure decides which inputs exist; read the example and the
   structure's classes (below) before editing it.
5. **Fill every input** (`inputs`). Run `inputs` to see each one with its
   unit and bounds. Replace every example figure with one from the documents
   or an assumption the user agrees with. Rates are decimals (`0.055` for
   5.5%); money is in dollars; months count from closing.
6. **Record a source for every input you set** in `sources`, so the
   workbook's Input Basis sheet shows where each number came from:

   ```json
   "sources": {
     "purchase_price": {"kind": "document", "reason": "Asking price in the OM",
                        "references": ["OM.pdf p.4"]},
     "vacancy_floor": {"kind": "assumption", "reason": "Submarket average; user agreed"}
   }
   ```

   Use `document` for a figure read from a file (give the file and page),
   `assumption` for a judgment, and `market` for a market or published figure.
   Put a short description of the scenario in `notes`.
7. **Check, then run.** `check` validates the inputs and prints the headline
   results and any flagged checks. `run` also writes the Excel workbook next
   to the model file. Fix anything invalid; explain every flagged check in
   plain words. A flag is a finding, not always an error.
8. **Report** the headline results, the assumptions that matter most, what you
   had to assume, and anything that looks off (a DSCR below the loan's
   minimum, a funding shortfall, rents above a regulatory limit). Give the
   workbook's path so the user can open it.

## While the user underwrites

- To answer a question about a figure, use `find` to locate the variable and
  `values` to read it. Do not read numbers out of the `.xlsx`: some of its
  stored values may be missing until Excel recalculates it.
- When the user changes an assumption, edit the input, update its source, run
  again, and say what changed in the results.
- Keep scenarios as separate files beside the base case (`model-downside.json`,
  `model-lender-terms.json`), each with its own workbook, and compare them in
  a short table when asked.
- Sensitivities: copy the model file, change one input at a time, `check`
  each, and tabulate the results. Do not edit the model code to do this.
- If the user asks for something the model does not cover, say so plainly.
  Do not change the model code to fit a deal unless they ask you to.

## Model file tips

- **Dates and hold.** In the value-add model, `closing` must be the last
  day of a month (use 2027-02-28 for a March 1 close). `horizon_years` is the
  hold plus one year, because the sale is priced on the buyer's first year:
  a five-year hold (`sale_month` 60) needs `horizon_years` 6. The maximum is
  11, so the longest hold is 10 years.
- **Changing the structure.** Adding or removing a unit type, cohort, expense
  line, loan or capital phase changes the inputs. After each change, `check`
  reports one problem at a time: `INPUT_UNKNOWN` names an input to delete,
  `INPUT_MISSING` one to add. Repeat until it passes.
- **Inputs that do not apply** (refinance terms with `refi_included` 0, rent
  limits with no restricted units, the waterfall when the user has no
  partnership terms) are still required. Leave a neutral value, record the
  source as `{"kind": "assumption", "reason": "Not used: no refinance"}`, and
  quote results at the levels that do apply (property and total equity rather
  than LP and GP).
- **Meanings.** `inputs` shows units and bounds, not definitions. When an
  input's meaning is not obvious, search for its name under `src/` and read
  the code; do not guess. For example, `other_income` is per occupied unit,
  and the value-add sale price capitalizes the buyer's first-year cash flow
  after reserves, not NOI.
- **Numbers.** Write decimals as strings (`"0.055"`) so they stay exact;
  plain numbers work too. Sources are keyed by input name; use `deal.FIELD`
  (for example `deal.closing`) for a structure field. `run` warns about a
  source whose key matches no input.
- **What a scenario changes.** Growth rates such as `market_growth` are one
  rate for the whole hold, so "flat for two years, then 3%" can only be
  approximated; say how you approximated it. The senior loan is re-sized in
  every scenario, so a downside also borrows less; point that out when you
  compare.

## Choosing a model

| `underwrite.py new` name | Use for | Structure to read |
|---|---|---|
| `value-add-acquisition` | Existing market-rate or mixed-income property: rent growth, renovation premiums, senior and subordinate loans, refinance, sale, LP/GP waterfall. Commercial space supported. | `src/balto_valuation/deal.py`, `src/balto_valuation/example.py` |
| `multifamily-development` | Ground-up market-rate development: budget, construction draws and interest, lease-up, permanent loan, waterfall | `src/balto_development/deal.py`, `src/balto_development/example.py` |
| `seattle-multifamily-development` | Ground-up development in Seattle that may use the MFTE tax exemption or must meet MHA (payment or performance): program toggles, restricted homes and rents, property tax, policy outcomes. Read [the program rules](docs/seattle-mfte-mha.md) and cite current City sources for every program input. | `src/balto_development/seattle.py`, `src/balto_development/seattle_example.py` |

If the deal fits none of them, say so and suggest the closest.

## Rules

- **Deal files stay private.** Keep the user's documents and model files in
  their deal folder, outside this repository. Never copy them into this
  repository, commit them, or push them anywhere.
- **Do not invent figures.** If a document does not give a number, say so and
  ask, or propose an assumption and label it as one in `sources`.
- **Every example figure is synthetic.** Never leave one in a deal's model
  file without telling the user.
- **Placeholder tables.** Rent limits, utility allowances, fair market rents
  and basis limits in the examples are placeholders. For a real deal, use the
  current published figures for the property's area and say where they came
  from.
- **Not advice.** The results are a model of the inputs, not an appraisal,
  a quote, or investment, tax or legal advice. Say so if the user is about to
  rely on a figure for a commitment.
