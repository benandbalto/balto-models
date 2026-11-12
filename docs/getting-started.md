# Getting started: underwrite a deal with an AI agent

This guide is for acquisitions, development and asset management people who
want a working pro forma for a deal without building one by hand. You will
point an AI agent at a folder of deal documents. It builds the model, writes
an Excel workbook with live formulas, and then works through the deal with you
in conversation.

You do not need to know how to code. You type requests in plain English; the
agent runs the commands. Allow about 20 minutes the first time.

## What you need

- A Windows, Mac or Linux computer. The models run natively on all three;
  Windows does not need WSL.
- An AI coding agent that can work with files and run commands on your
  computer, such as [Claude Code](https://claude.com/product/claude-code) or
  [OpenAI Codex](https://developers.openai.com/codex). Chat-only assistants
  in a browser cannot run the models.
- Desktop Excel to open the workbooks.
- A folder with the deal's documents.

**Before you start, check whether you may share the documents.** The models
run on your computer and the workbooks stay there. Your agent, however, sends
what it reads to its AI provider. Check that your agreement with the seller or
broker, and your firm's policy, allow that.

## 1. Install the agent

Install Claude Code or Codex from the links above and sign in. Both have a
desktop app and a terminal version; either works.

## 2. Set up and try the sample

Paste this into the agent:

> Set up https://github.com/benandbalto/balto-models in my Documents folder
> by following its AGENTS.md. Then build the sample value-add acquisition
> model, make a copy with the senior loan's interest rate half a percentage
> point higher, and open both workbooks in Excel. Show me a short table
> comparing the loan amount, DSCR and IRR.

The agent checks for Python 3.12 or newer and git, asks before installing
anything, then downloads the models and prepares them to write Excel files.

- **Windows:** if installation is blocked on a work laptop, ask IT for help.
  Python's installer also offers a "just for me" option that doesn't need
  administrator rights.
- **Mac:** if macOS asks to install "command line developer tools", accept;
  they include git.

You end up with two workbooks of an invented 64-unit property and a short
table showing what a higher interest rate does to the loan, the debt coverage
and the returns. In Excel, click **Enable Editing** if asked. The figures
recalculate on open. Change a blue number on the Assumptions sheet and watch
the related figures update.

For your own deals, start a new agent session and choose the `balto-models`
folder inside Documents as its working folder; look for **Open folder** or a
similar option in your agent. If you can't find it, ask the agent how to open
that folder. It needs to read its instructions in `AGENTS.md`.

## 3. Get your deal folder ready

Keep your deal folder anywhere outside `balto-models`, for example
`Documents/Deals/Elm Street`. Useful contents, as PDFs, spreadsheets or text:

- offering memorandum or broker package;
- rent roll and trailing-12 operating statement (T12);
- loan term sheet or lender quote;
- renovation scope and budget, or a development budget;
- for income-restricted units: regulatory agreement, utility allowances and
  rent limits.

A missing document doesn't stop the agent. It will say what it couldn't find
and ask you, or propose an assumption.

## 4. Ask for a model

> Underwrite the deal in Documents/Deals/Elm Street. It's a 64-unit
> value-add acquisition; we'd hold for five years.

Use your own folder and deal details. If you're not sure of the folder's
location, ask the agent to help you find it.

The agent reads the documents and picks one of the models:

| Model | For |
|---|---|
| Value-add acquisition | Existing market-rate or mixed-income property with renovation, refinance and sale |
| Multifamily development | Ground-up construction |
| Seattle development | Ground-up construction in Seattle with the MFTE and MHA affordability programs |

The agent fills in the model from your documents, recording where each number
came from. It then writes the files to an `underwriting` folder inside your
deal folder:

- `model.json`: the model's inputs and their sources, one file per scenario;
- `model.xlsx`: the workbook, with live formulas for the calculations. Its
  Input Basis sheet lists the recorded source or assumption for each input.

Last, it reports the headline results: total cost, equity, cap rate, DSCR,
IRR and equity multiple. It also tells you which assumptions it had
to make.

## 5. Underwrite in conversation

Ask the way you would ask an analyst. For example:

- "What did you assume for vacancy and where did the expenses come from?"
- "Use the lender's terms: 65% LTV, 6.1% rate, 30-year amortization."
- "Show me DSCR by year."
- "Make a downside case: rent growth one percentage point lower and an exit cap 50 bps wider.
  Compare it with the base case."
- "Run IRR at purchase prices from $9.0M to $10.0M in $250k steps."
- "Why is the funding check flagged?"
- "Write a one-page summary of the deal and the key risks."

The agent edits the inputs, reruns the model and tells you what changed. Each
scenario gets its own file and workbook, so the base case stays as it was.

## Checking the work

Treat the agent like a fast junior analyst whose work needs review:

- Open the workbook. Blue numbers are inputs; click a calculated cell to see
  its formula in Excel's formula bar.
- Read the Input Basis sheet. Every figure should come from a document you
  recognize or an assumption you agreed to.
- The models start from **invented example figures**, and the agent replaces
  them. Ask it to confirm that no example figure is left: "Is anything still
  from the example?"
- Rent limits, utility allowances, fair market rents and basis limits must be
  the current published ones for the property. The examples use placeholders.
- These are models of your inputs, not appraisals, lender quotes or
  investment, tax or legal advice.

## Keeping up to date

The models change. To get the latest, ask the agent to "update balto-models".
A new model version can change the results for the same inputs, so rerun open
deals afterwards and compare.

## Troubleshooting

| Problem | What to do |
|---|---|
| The agent says Python is too old | Ask it to install Python 3.12 or newer. |
| An input is "invalid" | The agent will see which input and why; ask it to explain and fix it. |
| The workbook shows zeros or blanks | Click Enable Editing if Excel opened it in Protected View, and set calculation to automatic (Formulas > Calculation Options > Automatic). |
| Windows blocks installing Python | Use the python.org installer with "just for me", or ask IT to allow Python 3.12. |
| The agent edits the model code | Tell it to stop and undo the change. Deals need only the model file. |
