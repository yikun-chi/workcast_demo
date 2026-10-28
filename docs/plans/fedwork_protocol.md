# Federal workforce separations after the 2025 changes: frozen protocol

Frozen on 2026-10-28. The held-out cutoff (December 2024) had not been scored when this file was committed.

## Data

**Source.** OPM Federal Workforce Data, through its public API (no key). The files and their versions are pinned with SHA-256 in `instances/fedwork/manifests/sources.json`.
- Monthly separation files, 2018-01 to 2026-08.
- December employment snapshots, 2018 to 2024.

**Licence.** No licence statement is published. These are U.S. government works, released under OPM's Data Release Policy (December 2024).

**Gaps in the data.**
- Adverse-action codes, including probationary terminations and removals, are withheld by OPM.
- The data excludes the Postal Service, the intelligence agencies and others.

## The change and the scored window

**The change:**
- 20 January 2025: return-to-office memorandum.
- 28 January to 12 February 2025: deferred resignation offer to full-time employees, with separations effective 30 September 2025.

**Scored outcome.** Separations by agency and month, February to December 2025. Months are the effective month of the personnel action, as recorded in the pinned file versions.

**Agencies scored.**
- Agencies with 1,000 or more employees in December 2024 are scored separately (40 agencies).
- Smaller agencies are scored together as one group.

## Design

**Cohort twins.** The twins at a cutoff are the December snapshot's cells: agency × age band × length-of-service band × permanent appointment × full-time × supervisor (about 14,000 twins).

**Separation types.** Each twin has a monthly separation rate for five types: quit, retirement, termination, transfer and other.

**Rates.**
- Rates are fitted on records that were both effective and published by the cutoff.
- Each rate is shrunk toward agency-scaled demographic rates.
- A month-of-year pattern per agency and type is shrunk toward the government-wide pattern.

**Prediction.** The world steps weekly from 1 January after the cutoff. The prediction is expected separations, averaged over 20 runs.

**Policy channels.** These enter only through the announced dates, and only for the held-out cutoff. The priors are in `instances/fedwork/calibration/priors.yaml`, with sources public before 20 January 2025.

- **Return to office.** Quits and retirements are multiplied by 1.14 (range 1.07 to 1.21). Source: Ding, Jin, Ma, Xing & Yang, the RTO brain-drain study, reported in December 2024.
- **Deferred resignation.** On 12 February, each full-time twin accepts with probability (M − 1 + c) × P(leave voluntarily within W months).
  - M = 1.89 (range 1.61 to 1.89): the early-retirement window effect from Lumsdaine, Stock & Wise (1990).
  - W = 7.5 months (range 7.5 to 12).
  - c = 0.5 (range 0 to 1, authored): the share of would-be leavers who move their exit to 30 September.
- **Timing.** Acceptors leave on 30 September. Until then, voluntary hazards of everyone else are scaled by (1 − c).
- **Not simulated.** Probationary firings, reductions in force, the hiring freeze's effect on in-year hires, and later offers by individual agencies. None of these was announced as a quantity on 20-28 January 2025.

## Development split

There are three development cutoffs: December 2021, 2022 and 2023. They had no announced change, and each predicts February to December of the following year. All development windows end by December 2024. `instances/fedwork/ingest/audit/select_spec.py` writes `calibration/selection.json`.

**Selection rule.** The rule was set before running: the lowest mean error in each agency's monthly separations (agency-month WAPE).

**Candidates.** 54 twin specifications: rate window (12, 24, 36 months) × shrinkage (0, 120, 1,200 person-months) × month pattern (none, government, agency) × stock (depleting, constant).

**Selected specification.**
- 12-month window, shrinkage 1,200, agency month pattern, depleting stock.
- Mean development WAPE 19.25% (23.5%, 19.3% and 14.9% by cutoff).

The first selection run offered only the none and government month patterns; its best was 21.26%. The agency pattern was then added as a candidate, still on development data only.

**Exponential-smoothing comparator.** Its constants were chosen on the same cutoffs: α 0.1, β 0, γ 0.3, φ 0.9, with development WAPE 18.33%.

In the development years, the best comparator (exponential smoothing) is more accurate than the twin baseline.

## Comparators

All are fixed in `instances/fedwork/evaluation/comparators.py` and read only records visible at the cutoff:
- same month last year;
- last 12-month average;
- recent trend (36 months with month effects);
- exponential smoothing (damped additive Holt-Winters);
- programme calculation, for the held-out cutoff only. It takes the same month last year, raises quits and retirements by the 14% RTO effect, and adds a September lump of (M − 1) × each agency's own voluntary leaving over W months × its full-time staff.

## Headline metrics

**Agency-month error.** Error in each agency's monthly separations, February to December 2025. This is the sum of absolute errors over agency-months divided by actual separations. Accuracy is 100 − that error.

**Other measures reported:**
- the same error over all four cutoffs;
- agency totals over the window;
- the government-wide total.

## Predicted result, before scoring

These come from `instances/fedwork/ingest/audit/predict_heldout.py`, which reads no record after December 2024. The figures cover February to December 2025.

**Simulation, 5 runs.**
- Total separations: 246,562 (range 230,289 to 270,173).
- Of these, deferred resignations: 102,971.
- September: 116,093.

**Comparator totals:**

| Comparator | Total | September |
|---|---:|---:|
| Same month last year | 203,364 | |
| Last 12-month average | 202,064 | |
| Recent trend | 175,666 | |
| Exponential smoothing | 203,817 | |
| Programme calculation | 295,026 | 95,206 |

**Expectations.**
- The simulation and the programme calculation should beat the series methods if the resignation offer produced a large September spike.
- The simulation should beat the programme calculation only if its twin-level allocation across agencies and months is closer.
- Agencies with large reductions in force or later agency-specific offers will be missed by every method.

## Retrospective caveat

This evaluation is retrospective. The team that chose the design knew the 2025 events in outline: a large deferred-resignation take-up and reductions in force at several agencies. The priors take published values as printed. The specification was chosen only on development years without a policy change.
