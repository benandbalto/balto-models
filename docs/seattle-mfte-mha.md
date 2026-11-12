# Seattle development with MFTE and MHA

`seattle-multifamily-development` (deal kind `seattle_development`) is the
multifamily development model with Seattle's two affordability programs and
property tax added. Each run can toggle:

- `mfte_elected`: whether the project is in the Multifamily Tax Exemption.
- `mha_applies` and `mha_performance`: Mandatory Housing Affordability, either
  the payment (fee in lieu) or the performance option.

Budget, lease-up, construction and permanent debt, funding, the LP/GP waterfall
and the live workbook are shared with `multifamily-development`. The example in
[`seattle_example.py`](../src/balto_development/seattle_example.py) is
invented; its program terms are the published 2026 values.

Program facts below were researched in November 2026 from City ordinances and
Office of Housing and SDCI publications. Rates and rules change: cite the
current source for every input. This is a model, not legal advice.

## Program rules the model applies

### MHA (residential, SMC 23.58C)

**Applies** to projects that add units in a zone with an (M), (M1) or (M2)
suffix, or in a Downtown or South Lake Union zone with MHA. There is no
minimum project size. Low-income housing (as SMC defines it) is exempt.

**Payment** = rate × (residential + live-work gross floor area − underground
parking). Common areas and above-grade parking count.

- The rate is set by area (Low, Medium or High) and suffix, adjusts every
  March 1 by Seattle shelter CPI, and **locks at vesting** (complete MUP or
  building permit application).
- Payment is due before the first building permit that includes the
  structural frame. There is no deferral.
- 2026 rates ($/sq ft, effective 2026-03-01):

| Area | (M) | (M1) | (M2) |
|---|---|---|---|
| Low | 10.78 | 17.33 | 19.26 |
| Medium | 20.41 | 30.81 | 34.28 |
| High | 31.97 | 45.83 | 50.46 |

**Performance** set-aside, as a share of units:

| Area | (M) | (M1) | (M2) |
|---|---|---|---|
| Low | 5% | 8% | 9% |
| Medium | 6% | 9% | 10% |
| High | 7% | 10% | 11% |

- **Rounding:** if fewer than 2 units are required, provide 2 units, or 1 unit
  with three or more bedrooms. Otherwise, round up, or provide the whole
  number and pay for the fraction as `full payment × fraction / required
  units`.
- **Rents:** 60% AMI, or 40% AMI for units of 400 sq ft net or less. The rent
  limit includes the utility allowance and mandatory recurring fees.
- **Term:** a 75-year covenant, so MHA units stay restricted through any sale.
- **Monitoring fee:** $190 per unit per year as codified (CPI-adjusted since
  2024).
- **Option choice:** the option can change until the structural permit issues.

Downtown and South Lake Union zones have their own rate and set-aside tables
(Table A of 23.58C.040 and 23.58C.050).

### MFTE (Program 7, SMC 5.73, Ordinance 127316)

- **Eligibility:** effective 2025-11-14; the program sunsets 2029-09-01. It is
  for new construction or commercial conversion with at least 4 units per
  structure, anywhere zoned for multifamily. Apply at least 180 days before the
  temporary certificate of occupancy (TCO).
- **Set-aside:** 20% of units if at least 12% of units have two or more
  bedrooms or at least 3% have three or more; otherwise 25%. Round up; the test
  applies per structure.
- **AMI levels by unit type:**

| Unit type | AMI |
|---|---|
| Congregate sleeping room | 40% |
| Studio of 320 sq ft or less | 50% |
| Studio over 320 sq ft | 60% |
| 1BR | 70%, or 75% with a standard bedroom |
| 2BR | 80%, 85% or 90% (by standard vs alternative bedrooms) |
| 3BR+ | 85% or 90% |

- **Rents:** the Office of Housing (OH) gross limit is 30% of income (household
  size 1.0 for studios, 1.5 per bedroom), less OH's utility estimate, $25
  renter's insurance if required, and mandatory fees. Annual increases on
  occupied MFTE units are capped (4.6% for 2026).
- **Exemption:** 12 years from January 1 after the final certificate. It covers
  the **whole residential improvement value**, not only the MFTE units. Land,
  commercial space and live-work stay taxable. Restrictions end when the
  exemption ends. One 12-year extension is possible, at AMI 5 points lower.
- **Fees:** $2,000 + $200 per unit, capped at $10,000. Include this in soft
  costs. There is no annual City monitoring fee; the manager's compliance work
  is a cost (`mfte_compliance_cost`).
- **Floor distribution:** at a 20% set-aside, no more than 25% of the units on
  a floor may be MFTE units (30% at 25%), unless they sit on the middle floors.
- **Penalty:** cancellation brings back taxes plus interest plus a 20% penalty.

### Stacking

MHA performance units and MFTE units are **always different units**
(SMC 23.58C.050.C.5; confirmed by the 2024 UW and 2025 BERK evaluations).

- MHA payment combines freely with MFTE; this is the common pairing.
- Performance plus MFTE restricts about 25–37% of units.
- About 95% of MHA projects pay the fee.

### 2026 inputs

- **Utility estimates** (OH, effective 2025-02-01), monthly, for MFTE, MHA and
  Incentive Zoning units when tenants pay utilities:

| Tenant pays | Studio | 1BR | 2BR | 3BR |
|---|---|---|---|---|
| All utilities (energy, water, sewer, garbage) | 160 | 185 | 285 | 435 |
| Electricity and heat | 50 | 65 | 85 | 120 |
| Implied water, sewer and garbage (difference) | 110 | 120 | 200 | 315 |

  Renter's insurance adds $25 when required and not offered by the owner.

- **Levy rate:** levy code 0010 is $9.90845 per $1,000 (2025: $9.19418).
- **Rent limits:** the OH 2026–27 gross limits (effective 2026-05-15) are the
  same for MHA and MFTE P7. Examples:

| Unit | 60% AMI | 90% AMI |
|---|---|---|
| Studio | 1,726 | 2,589 |
| 1BR | 1,850 | 2,775 |
| 2BR | 2,220 | 3,330 |
| 3BR | 2,565 | 3,847 |

- **HUD median family income:** $164,400 (FY2026).

## Model conventions

- **Units are explicit inputs.** Give whole MFTE and MHA units per unit type.
  The model computes the MFTE set-aside rate from `bedrooms` and the MHA
  required units. Shortfalls are economic tests (`MFTE_SET_ASIDE`,
  `MHA_PERFORMANCE_SHORTFALL`) and stay visible.
- **Structural checks.** More restricted units than units of a type, fractional
  units or flags, and out-of-order program events are structural errors.
- **Water, sewer and garbage (WSG)** is an owner expense on occupied homes at
  `wsg_cost`, growing with `opex_growth`, of which `wsg_recovery_rate` is
  billed back as income. Keep WSG out of `annual_opex`. The example uses the
  implied OH WSG estimate as cost and an 80% recovery on every home; restricted
  rents are already net of the full utility estimate, so billing them is
  allowed.
- **Restricted rents** are net monthly inputs, grown at
  `affordable_rent_growth` and never above market. MFTE units are restricted
  from first occupancy until the exemption ends. Restricted and market units
  lease up in proportion.
- **MHA payment** is a dated project cost at `mha_payment_month`, eligible for
  construction draws like other spending. Under performance, only the
  fractional-unit payment is charged. MHA homes carry the City monitoring
  fee and the manager's compliance cost; MFTE homes carry only the manager's
  compliance cost. All are per restricted unit-year, from occupancy.
- **Property tax** is modeled outside `annual_opex`:
  - land × levy rate in every month;
  - improvements × levy rate from `improvement_tax_month`;
  - both grow at `assessed_value_growth`;
  - MFTE removes `residential_improvement_share` of the improvement tax while
    exempt.
  - Do not also carry property tax in soft costs or `annual_opex`.
- **Stabilized NOI** for permanent loan sizing is closed-form at the
  stabilization month, including any exemption then in force.
- **Sale value** = forward-12-month NOI *without* MFTE (market rents on MFTE
  units, full tax, no MFTE compliance cost) ÷ exit cap, plus the present value
  of the remaining MFTE net benefit. That benefit is the forward average
  monthly (tax saved − rent given up net of management fee − compliance cost),
  discounted at `mfte_exit_discount_rate` over the months left in the
  exemption. The temporary exemption is therefore never capitalized in
  perpetuity. MHA units stay restricted in the buyer's NOI.
- **One structure.** The project is treated as one structure for the
  per-structure rules.

## Executive Summary tab

The workbook opens on an **Executive Summary** written for public-sector
readers. It compares six program combinations: no programs (the baseline), MHA
payment, MHA performance, MFTE only, MFTE + MHA payment, and MFTE + MHA
performance.

For each combination it shows:

- **Homes:** restricted homes by program, and their share of all homes.
- **Tenant benefit:** stabilized-year rent savings, in total and per
  restricted home.
- **Public finance:** the MHA payment to the City, the MFTE exemption in its
  first full year and over its 12-year term, and tenant rent savings per $1
  of exemption.
- **Feasibility:** development cost per home, yield on cost, peak equity, the
  levered and LP IRRs, and the IRR change against the baseline.

Below the comparison, a rents table shows each home type's market rent and its
MFTE and MHA rent and discount.

The "This workbook" column is live and checked by workbook parity. The six
comparison columns are separate engine runs made when the workbook is built,
and the sheet labels them that way.

## Not modeled

Treat these as review items, not silent assumptions:

- MFTE extension years and relocation payments at expiry. With a 10-year
  maximum horizon, the 12-year exemption never ends inside the model.
- A turnover vacancy drag on restricted units.
- An exit-cap premium for buildings with affordable units.
- Per-structure tests for multi-building sites, and the MFTE per-floor limit.
- MHA-C (commercial floor area over 4,000 sq ft).
- HB 1217 rent caps on market units. New construction is exempt for 12 years
  after its certificate of occupancy.
- **Pending legislation.** The "MHA Accelerator" (CM Foster, September 2026;
  vote expected January 2027) would cut payments by 60–80% for qualifying
  projects. Until it is enacted, model it as a separate case with a reduced
  `mha_payment_rate` and a basis citing the bill.

## Sources

Search these titles on the City of Seattle and King County websites:

- SDCI, Mandatory Housing Affordability program page and MHA payment rates
  (effective 2026-03-01).
- SDCI Tip 257, MHA (updated 2026-02-27).
- Office of Housing, 2025 MHA Annual Report.
- BERK, MHA five-year evaluation (2025).
- Ordinance 127316 (MFTE Program 7) and Seattle Municipal Code chapters 5.73
  and 23.58C.
- Office of Housing, MFTE Program 7 rent and income limits, effective
  2026-05-15.
- Office of Housing, utility and renter's insurance estimate schedule,
  effective 2025-02-01.
- University of Washington, MFTE program evaluation (2024).
- King County Assessor, 2026 levy rates by city and school district.

## Open items to verify before relying on a case


- Exact SMC text: Municode was unreachable, so these rules were read from
  ordinances and a code mirror.
- The 2026 CPI-adjusted MHA monitoring fee.
- Whether the first exempt tax bill falls in the year after the final
  certificate.
- The SMC 23.84A definition of low-income housing used for the MHA exemption.
- Whether doing MFTE cancels the design-review waiver that comes with choosing
  MHA performance.
