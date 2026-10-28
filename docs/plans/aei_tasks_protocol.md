# Protocol: occupation shares in the Anthropic Economic Index, frozen before the held-out run

Written 2026-10-28, after the development cutoffs and before any held-out cutoff was run.

## Data

- Anthropic Economic Index, Hugging Face `Anthropic/EconomicIndex` at revision
  `4e5f69fab13a9c3f7d0dcc31a6f893a9818738f6`; SHA-256 of every file in `instances/aei_tasks/manifests/sources.json`.
  Licence: the data documentation says "Data released under CC-BY"; the dataset card metadata lists MIT. Both are
  recorded; either permits commercial use with attribution.
- Six releases with Claude.ai conversation shares by O*NET task: 2025-02-10, 2025-03-27 (task_pct_v2), 2025-09-15,
  2026-01-15, 2026-03-24 and 2026-06-26 (April and May 2026, averaged).
- Each release is reduced the same way (`instances/aei_tasks/ingest/run.py`): global Claude.ai task shares; "none" and
  "not_classified" dropped; each task split equally across the O*NET occupations that list it (the Index's own task
  list, O*NET 31.0 for newer tasks) and summed by SOC major group; renormalised. 22 groups have conversations
  (Military Specific never does and is left out).
- Known comparability limits: the classifier, the sample windows (a week to two months) and the product scope change
  between releases; the June 2026 release adds Cowork conversations and publishes calendar months. These changes are
  part of what every method must predict.

## Cutoffs and split

- 4 cutoffs: releases 2 to 5 (2025-09-15, 2026-01-15, 2026-03-24, 2026-06-26), each predicted from the releases
  before it. Development: the first two (the protocol's minimum). Held out: 2026-03-24 and 2026-06-26, 44 predictions.

## Frozen design (`instances/aei_tasks/calibration/adoption.yaml`)

- 22 groups of 1,000 simulated workers; hazards move each group's expected use along a diffusion path; shares are
  rescaled to sum to 100%.
- Default specification: the last release's shares carried forward. Richer specifications (own growth over every
  earlier release with weight 0.5 or 1, damping 1 or 0.5, starting level from the last one or two releases) replace it
  at a cutoff only when backtests on earlier releases favour them by more than one standard error. At the development
  cutoffs fewer than two backtests exist, so the default was used.
- No design change was made on the development cutoffs: every fixed specification scored within 0.02 points of
  carry-forward there.

## Comparators (fixed)

carry-forward (last release), recent average (last two releases), linear trend over every earlier release,
damped-trend exponential smoothing, Bass diffusion fitted to each group's shares (falls back to carry-forward with fewer
than five releases).

## Headline metric

Mean absolute error in percentage points of each group's share of the next release, over groups and held-out cutoffs;
error reduction versus the best comparator; accuracy = 100 x (1 - error / mean actual share).

## Development result (2 cutoffs, 44 predictions)

| | Simulation | Carry-forward | Recent average | Linear trend | Damped trend | Bass |
|---|---:|---:|---:|---:|---:|---:|
| MAE (pp) | 0.596 | 0.596 | 0.696 | 0.714 | 0.596 | 0.596 |

## Predicted held-out result

No improvement over carry-forward: the simulation is expected to equal it (if the default is kept) or be within
about 10% either way (if a trend specification is selected at the later cutoffs). The June 2026 release changed product
scope, so every method's error is expected to be larger at that cutoff. This case is reported as measured whatever the
outcome; it is not expected to support a value claim.

## After the held-out run

Results are reported as measured in `docs/validation_aei_tasks.md` (generated from `runs/aei_tasks/evaluation.json`).
