# Ctrip work-from-home experiment: frozen protocol

Frozen on 2026-10-28, before the experiment period was scored. This file is committed before `orgsim evaluate ctrip` is run for the first time.

## Data

- **Source.** Bloom, Liang, Roberts & Ying (2015, QJE) replication files. The deposit is Harvard Dataverse doi:10.7910/DVN/PZQOB1 under CC0.
- **Copy used.** That Dataverse file needs a guestbook form, so the ingest downloads the authors' public copy linked from their research page. Its SHA-256 is pinned in `instances/ctrip/manifests/sources.json`.
- **Panel.** Weekly, from 2010 week 1 to 2011 week 33.
- **Before period.** 2010 weeks 1-48.
- **Change.** 6 December 2010, during week 49, which is a transition week and is not scored.
- **After period.** Weeks 201050-201133. This period is scored once.

## What the simulation uses

- **Twins.** 249 twins, one per experiment participant (131 home, 118 office).
- **Covariates.** Each twin takes its covariates from the pre-experiment tables.
- **Performance level.** Each twin's level of the performance score and of log weekly calls comes from its 2010 weeks.
- **Exit hazard.** A weekly exit hazard estimated from 2010 staff outside the experiment.
- **Seasonality.** A same-week-of-2010 pattern for 2011 weeks.

Everything above is computed by `instances/ctrip/ingest/run.py` from weeks before 201049 and written to `calibration/fit.json`.

## Development split

The specification was chosen on 2010 data only. `instances/ctrip/ingest/audit/select_spec.py` uses two pseudo-changes, at weeks 201027 and 201037, and writes `calibration/selection.json`.

**Level estimators compared:**
- the 2010 mean;
- the last 4, 8 or 13 weeks;
- a shrunken mean.

The selection rule was set before running: lowest summed relative person-week MAE. The shrunken mean won (score 3.874 against 4.000 for the plain mean).

**Exit-hazard spell threshold.** The candidates were 0, 8, 13 and 20 weeks. The rule was lowest mean absolute error in the share leaving. The threshold of 0 won (2.29 pp).

An exit means at least four weeks of absence at the end of a window. This rule was set to remove the end-of-window artefact visible in the 2010 panel.

## Sourced priors

All priors are in `instances/ctrip/calibration/priors.yaml`. Every source was published before February 2013.

| Prior | Value | Source |
|---|---|---|
| Telecommuting effect on supervisor-rated or objective performance | d = 0.36 [0.18, 0.54] | Gajendran & Harrison 2007 |
| Telecommuting effect on turnover intent | d = −0.17 [−0.22, −0.12] | Gajendran & Harrison 2007 |
| Intent-to-quit correlation | 0.38 | Griffeth, Hom & Gaertner 2000 |
| Tenure and age effects on quitting | −0.20 and −0.09 | Griffeth, Hom & Gaertner 2000 |

**How the priors enter the simulation:**
- The performance effect is applied in between-person SDs of each measure.
- The quit effect shifts each twin's latent quit liability over the 38-week horizon.

## Comparators

These were fixed in `instances/ctrip/evaluation/comparators.py` and read 2010 data only:

- **No change:** each group keeps its 2010 mean, and quits run at the 2010 exit rate.
- **Same weeks last year:** each 2010 mean is adjusted by the 2010 seasonal pattern.
- **Recent trend:** a linear fit to each group's 2010 weekly means, extended forward.
- **Earlier research:** the meta-analytic effects applied directly. Performance rises 0.36 SD of the person-week measure. Quits come from Φ(Φ⁻¹(p0) + 0.38 × −0.17).

## Headline metrics

1. **Calls effect.** The effect of working from home on weekly calls answered by order takers. It is the home group's change from its 2010 mean minus the office group's change, converted from logs to percent.
2. **Quit effect.** The effect on quits by the end of the experiment: the home group's share minus the office group's share, in percentage points.

**Accuracy for levels.** Accuracy is 100 × (1 − |error| / actual). It is reported for weekly calls in the home group and for the home group's quit share.

**Error reduction.** Error reduction is measured against the best comparator for each metric.

## Predicted result, before scoring

These are the simulation's own predictions from 10 runs, with outcomes unseen:

| Metric | Mean | Range across runs |
|---|---|---|
| Calls effect | +8.4% | 5.4 to 11.2 |
| Performance-score effect | +0.23 SD | |
| Quit effect | −1.3 pp | home 16.2%, office 17.5% |
| Home group weekly calls | about 496 | |

**Expectations:**
- Calls: the simulation should beat no change if working at home raised calls. Whether it beats earlier research (+16.6%) depends on the true effect's size.
- Quits: the simulation, no change and earlier research all predict small effects. If the true effect is large, every method will miss it.

## Retrospective caveat

This evaluation is retrospective. The team that chose the design knew the published result in outline: higher output and lower quits in the home group. The priors' central values are the published meta-analytic estimates, taken as printed, and were not adjusted toward the experiment.

## After scoring

- 2026-10-28: the held-out run was scored once (`runs/ctrip/evaluation.json`). Presentation change only: percent accuracy, 100 × (1 − |error| / actual), is not reported for the performance-score levels, whose actual values are near zero on a z-score scale (the home group's actual level was −0.017), so the ratio is meaningless. No prediction, prior or comparator changed; the rerun reproduces the same predictions with the same seeds.
