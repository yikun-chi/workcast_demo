# Protocol: AI adoption by sector (Census BTOS), frozen before the held-out run

Written 2026-10-28, after the development cutoffs and before any held-out cutoff was run.

## Data

- U.S. Census Bureau, Business Trends and Outlook Survey, `AI Core Questions.xlsx` (public domain), SHA-256 in
  `instances/btos_ai/manifests/sources.json`.
- Outcome: the published share of businesses answering "Yes" to "In the last two weeks, did this business use
  Artificial Intelligence (AI) in producing goods or services?", by two-digit NAICS sector, 54 biweekly periods from
  2023-09-11 to 2025-09-22 (collection start).
- One wording regime only. Census changed the wording on 2025-11-17 ("in any of its business functions") and started a
  new series because of a level shift; current files also relabel the question "Super Intelligence or SI". No period
  after the change is used for calibration or scoring.
- Scored groups: the 15 sectors published in at least 90% of periods (23, 31, 42, 44, 48, 51, 52, 53, 54, 56, 61, 62,
  71, 72, 81). Sectors 11, 21, 22, 55 and the unclassified group are mostly suppressed and left out. The national share
  is an input (the economy-wide adoption sectors imitate), not scored.

## Cutoffs and split

- 14 cutoffs, periods 20 to 46 every 2 periods (2024-06-17 to 2025-06-16 by collection start). A cutoff c uses periods
  0..c-1 only.
- Development: the first quarter, cutoffs 20, 22, 24, 26. Held out: cutoffs 28 to 46 (10 cutoffs).
- Horizons: 6 periods (about 3 months) and 13 periods (about 6 months) after the last observed period. The 6-month
  target is published for cutoffs up to 40, so held-out scoring has 10 cutoffs at 3 months and 7 at 6 months.

## Frozen design (`instances/btos_ai/calibration/adoption.yaml`)

- Each sector is 1,000 simulated firms. Each period non-users start using AI and users stop with hazards that move the
  expected share along a logistic diffusion path; the rule seat draws each firm's choice.
- Path: the log-odds of each sector's share grows each period by the national share's log-odds growth, estimated by
  least squares over every period before the cutoff (imitation of economy-wide adoption, undamped). The starting
  level is the mean log-odds of the sector's last 6 periods, moved forward to the last period by that growth.
- Ranges: the 5th-95th percentile of 20 runs per cutoff; shock sizes by horizon come from backtests at up to 10
  earlier cutoffs whose targets fall before the cutoff.
- Development changes, all made on cutoffs 20-26 only: (1) growth window from 12 periods to all history; (2) the
  anchor of the one-standard-error rule from "recent level held flat" to the logistic default above; (3) per-cutoff
  selection among richer grids removed, because it chose the flat level or damping at every development cutoff and
  raised the development error from 1.01 to between 1.10 and 1.51 points.

## Comparators (fixed)

carry-forward (last period), recent average (last 6 periods), linear trend (least squares over every period before the
cutoff, extended), damped-trend exponential smoothing (ETS A,Ad,N with parameters chosen by one-step error), and the
Bass diffusion curve fitted by least squares to every period before the cutoff (the standard adoption model).

## Headline metric

Mean absolute error, in percentage points, of each sector's AI use rate, over sectors, held-out cutoffs and both
horizons; error reduction versus the best comparator; accuracy = 100 x (1 - error / mean actual share).

## Development result

| | Simulation | Carry-forward | Recent average | Linear trend | Damped trend | Bass |
|---|---:|---:|---:|---:|---:|---:|
| MAE, both horizons (pp) | 1.006 | 1.278 | 1.511 | 1.020 | 1.280 | 1.135 |

(120 predictions; 90% range coverage 88%.)

## Predicted held-out result

The simulation's error is between 0.9 and 1.5 points, about 85% accuracy. Against the best comparator (expected to be
the linear trend) the simulation is expected to be roughly equal to 15% better: adoption accelerated in 2025 and the
logistic path grows in proportion to each sector's level, which a straight line does not. A loss to the linear trend is
plausible and will be reported as measured.

## After the held-out run

Results are reported as measured in `docs/validation_btos_ai.md` (generated from `runs/btos_ai/evaluation.json`).
Any bug fixed afterwards is recorded below with before and after numbers; no further tuning.

The held-out cutoffs were run once on 2026-10-28 with the frozen design. No bug was found and nothing was changed after the run.
