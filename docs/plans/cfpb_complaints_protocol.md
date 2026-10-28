# Frozen protocol: CFPB consumer complaints (cfpb_complaints)

Written 2026-10-28, after the development cutoffs and before any held-out cutoff was run. Committed before the
held-out run; the held-out cutoffs are run once with exactly this design.

## Case

- **Data:** CFPB Consumer Complaint Database, `complaints.csv.zip` retrieved 2026-10-28 (sha256
  `92df301d0179817ba450346c0e552c14efc3ee1ac5e9341f30849fe204350e5e`, `instances/cfpb_complaints/manifests/sources.json`).
  Licence: "All complaint data we publish is freely available for anyone to use, analyze, and build on"
  (https://www.consumerfinance.gov/data-research/consumer-complaints/, read 2026-10-28). 18,033,360 complaints received
  2017-01-02 to 2026-10-28 after normalization.
- **Change:** no clean dated change is usable. The SVB failure (10 March 2023) produced no complaint signal: SVB Financial
  Group has 1 complaint in March 2023 (`instances/cfpb_complaints/ingest/audit/explore.py`). The design is therefore
  rolling-origin cutoffs; each new 12-week period is the "change". The held-out period (2022-05 to 2026-09) contains the
  tenfold rise in complaint volume (weekly mean 9,519 in 2021, 139,587 in 2026; same audit script).
- **Cutoffs:** 72 Mondays, 2021-01-04 to 2026-06-15, four weeks apart (`evaluation/protocol.yaml`). Development: the first
  18 (2021-01-04 to 2022-04-25). Held out: the remaining 54 (2022-05-23 to 2026-06-15). The last scored week ends
  2026-09-06, more than 15 days before retrieval.
- **Population:** the 50 companies with the most complaints in the 13 weeks before each cutoff.

## Frozen design (`instances/cfpb_complaints/calibration/service.yaml`)

Service world (`orgsim/worlds/service.py`). Agents: each company's products with at least 5% of its complaints in the
26 weeks before the cutoff (requester segments; the rest pooled per company), and the company (organisation).

- Demand per segment, from complaints received before the cutoff only: starting level = mean of the last 4 weeks
  (holiday weeks removed); growth starts at half the segment's own 8-week log growth and fades by 0.6 a week; U.S. federal
  holiday-week effects estimated from the segment history (pooled, volume-weighted median) and applied to the forecast
  weeks. No annual pattern, forward drift, reversion or cross-company pooling. Point prediction: the central path.
  Ranges: 20 seeds; a random walk in log demand per company (shared by its products) whose spread by weeks ahead
  matches the company-level errors of 8 inner backtests ending before the cutoff, plus Poisson arrivals.
- On-time share per company: each product's on-time rate over the last 4 weeks whose 15-day deadline passed before the
  cutoff, shrunk to the company rate with pseudo-count 5, weighted by the predicted product volumes. No load response.
- Only input after the cutoff: the U.S. federal holiday calendar.

## Comparators (fixed before scoring)

Applied to each company's own weekly series as known at the cutoff: last week carried forward; average of the last 4
weeks; average of the last 52 weeks; same week last year (seasonal naive); log-linear trend of the last 26 weeks;
exponential smoothing (ETS on log counts, no / additive / damped trend chosen by AICc, `orgsim/evaluation/forecast.py`).
For the on-time share the same six forecasts of the company's weekly on-time share, from weeks past their deadline.

## Headline metric

Error in each company's weekly complaints over the 12 weeks after the cutoff: WAPE over company-weeks per cutoff,
averaged over the 54 held-out cutoffs. Reported as error reduction versus the best classical comparator and as
accuracy = 100 x (1 - WAPE). Secondary: the same for the 47 companies other than the three nationwide credit bureaus;
on-time share MAE in percentage points.

## Development results (18 dev cutoffs; `scripts/service_dev.py`, log `logs/cfpb_dev5.log` on the iMac)

| Outcome | Simulation | Last week | 4-week average | 52-week average | Same week last year | Trend | ETS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Weekly complaints per company (WAPE) | 22.87% | 24.62% | 23.78% | 38.58% | 49.75% | 38.79% | 23.86% |
| Same, excluding the three bureaus | 18.75% | 22.13% | 19.45% | 21.78% | 29.94% | 25.25% | 19.11% |
| On-time share (MAE, points) | 0.723 | 0.779 | 0.711 | 1.011 | 1.204 | 0.915 | 0.774 |

Dev error reduction on weekly complaints: 3.8% versus the 4-week average. Choices made on dev, in order: per-cutoff
backtest selection with the one-standard-error rule (round 1) mostly fell back to the flat 4-week level and did not beat
a fixed specification; annual pattern, forward drift, reversion toward the 26-week level, pooling across companies and
size tiers each raised the dev error; the estimated on-time load response raised the on-time error (0.99 vs 0.78 points)
and was switched off. Variants and their overrides: `instances/cfpb_complaints/calibration/dev_variants.yaml`.

## Predicted held-out result (written before running it)

Weekly complaints: simulation WAPE between 20% and 30%; error reduction versus the best comparator between 0% and 5%,
best comparator the 4-week average or ETS. The 2023-2026 growth in bureau complaints may favour the own-growth term, but
bureau volatility dominates the WAPE. On-time share: the simulation about 2% worse than the 4-week average (it loses).

## Alternative

`bureau_surge`: complaints to the three credit bureaus 25% above the simulated path for 12 weeks, at the last 4 cutoffs
with the same seeds. A demand-side assumption; with no load response the on-time shares move only through the mix.

## Post-run changes

None yet. Any bug fix after the held-out run is recorded here with before and after numbers; no further tuning.
