# AI token demand: every validation and prediction result

As of 2026-11-01. All figures were read from the files named in each section. Error is the token-weighted error across the 100 leading apps (WAPE, lower is better); accuracy is 100 minus error. Every forecast at every cutoff used only data published before that cutoff.

## 1. Live board (sumervaid.com/predict)

- Forecasts published so far: none. The first is due Monday 2 November 2026, and is skipped if the data arrive more than two days late.
- Method: E3 (section 4), from the first live forecast. If the language model is unavailable the record says so and publishes the fallback blend.
- Each record is read-only, carries the code commit and input hashes, and is anchored in Bitcoin with OpenTimestamps.

## 2. Backtest of the simulation alone: 16 cutoffs, 1,600 forecasts

Cutoffs four weeks apart, 2025-07-07 to 2026-08-31. Sources: `docs/validation_openrouter.md`, `board/results/fair_inputs.json`. Retrospective: the model's structure was chosen with these periods available.

Token error by horizon (the damped trend rows come from `fair_inputs.json`; the rest from the validation record):

| Method | 1 wk | 2 wk | 4 wk | 8 wk |
|---|---:|---:|---:|---:|
| Damped trend, full history | 22.2 | 25.4 | 31.2 | 42.6 |
| Damped trend, last 12 weeks | 22.5 | 25.5 | 31.2 | 42.1 |
| WORKCAST simulation | 25.8 | 29.0 | 34.8 | 43.6 |
| No change | 32.7 | 35.0 | 39.7 | 45.1 |
| Recent trend | 33.1 | 35.7 | 44.4 | 65.8 |
| Market growth | 34.3 | 36.8 | 43.2 | 53.1 |

The damped trend beats the simulation alone at every horizon. The simulation beats the three simpler standards at every horizon.

Company-level results over 8 weeks (simulation vs the best of no change, recent trend, market growth):

| Measure | Simulation | Best standard |
|---|---:|---:|
| Error in each company's 8-week tokens | 43.6% | 45.1% (no change) |
| Error in each company's 8-week spend | 36.3% | 41.6% (no change) |
| Median company's error | 33.7% | 35.5% |
| Growth or decline called correctly | 68.8% | 64.9% |
| Actual tokens inside the simulation's 90% range | 87.2% | – |

Combined 8-week spend of the 100 leading apps (business validation):

- Average actual spend per window: $62.6M at list prices.
- Simulation mean absolute error $9.84M (15.7% of spend); best standard (no change) $18.95M (30.3%): 48.1% less error.
- Committed-capacity saving against this forecast instead of the best standard, per $1M of annual spend: $12,219 at a 20% discount, $36,560 at 40%, $60,900 at 60%.
- **Not yet scored against the damped trend.** The re-scoring with the damped trend as a platform comparator is running (`logs/evaluate_damped.log`); the spend figures above may change.

Model mix (which models an app's workload moves to), from `evaluation.json` accuracy.model_shares:

- Share distance (lower is better): simulation 53.5, no change 54.3.
- Share of use going to models launched after the cutoff: actual 35.7%, simulation 8.0%, no change 0%. The simulation captures little of the shift to new models. Not a selling point as it stands.

## 3. Language-model and combination runs, weekly cutoffs after the model's training cutoff

Protocol and freezes: `docs/plans/astra_forecast_protocol.md`. Results: `board/results/astra_run*.json`. Total language-model spend across all runs: $24.02 of the $25 cap.

### Run 1: the language model alone against the simulation (5 cutoffs, 2026-05-11 to 2026-08-31)

| Method | 1 wk | 2 wk | 4 wk | 8 wk |
|---|---:|---:|---:|---:|
| Language model (2 samples, mean) | 23.1 | 27.6 | 32.3 | 40.8 |
| WORKCAST simulation | 25.3 | 29.2 | 35.1 | 45.5 |
| Recent trend | 26.2 | 28.3 | 35.4 | 47.2 |
| No change | 28.6 | 31.3 | 36.9 | 45.4 |
| Market growth | 29.7 | 32.4 | 38.6 | 42.2 |

### Run 2: frozen design C3 (median of six forecasts), 13 held-out weekly cutoffs

| Method | 1 wk | 2 wk | 4 wk | 8 wk |
|---|---:|---:|---:|---:|
| Language model | 17.4 | 21.1 | 26.4 | 33.7 |
| Damped trend | 18.4 | 20.6 | 25.5 | 34.3 |
| C3 (frozen) | 20.5 | 22.6 | 26.1 | 33.8 |
| WORKCAST simulation | 21.6 | 24.3 | 31.0 | 43.4 |
| Recent trend | 24.4 | 27.8 | 33.0 | 42.9 |
| No change | 29.7 | 32.5 | 37.2 | 47.2 |
| Market growth | 29.7 | 32.2 | 35.7 | 43.4 |

C3 lost to the language model and the damped trend. Reported as a loss.

### Run 3: development, 18 weekly cutoffs (2026-05-04 to 2026-08-31)

Mean over horizons 1, 2 and 4. D4's weights were fitted on these cutoffs, so its figure is in-sample.

| Method | 1 wk | 2 wk | 4 wk | 8 wk | Mean (1, 2, 4) |
|---|---:|---:|---:|---:|---:|
| D4 (in-sample) | 18.8 | 21.9 | 26.7 | 35.2 | 22.44 |
| Damped trend | 19.7 | 22.2 | 27.2 | 36.5 | 23.02 |
| Language model | 19.0 | 22.9 | 28.0 | 35.7 | 23.30 |
| WORKCAST simulation | 22.7 | 25.6 | 32.1 | 44.0 | 26.80 |
| Recent trend | 24.9 | 27.9 | 33.6 | 44.1 | 28.83 |
| Market growth | 29.7 | 32.3 | 36.5 | 43.1 | 32.82 |
| No change | 29.4 | 32.1 | 37.1 | 46.7 | 32.88 |

D4 weights per horizon (1, 2, 4, 8 weeks): simulation 0.1/0.2/0.2/0.1; language model 0.7/0.5/0.3/0.7; damped trend 0.2/0.3/0.5/0.2.

### Run 4: Timestral as the base (same 18 development cutoffs)

| Method | 1 wk | 2 wk | 4 wk | 8 wk | Mean (1, 2, 4) |
|---|---:|---:|---:|---:|---:|
| T3: Timestral adjusted by the language model, simulation in view | 18.7 | 22.4 | 27.7 | 35.6 | 22.95 |
| T2: Timestral adjusted by the language model | 18.8 | 22.7 | 27.8 | 36.1 | 23.11 |
| T4: mean of T3 and Timestral | 19.5 | 24.7 | 33.2 | 52.9 | 25.79 |
| T1: Timestral alone | 20.9 | 27.2 | 39.1 | 70.6 | 29.10 |

Timestral alone is the weakest model-based forecast here; the language model's adjustment recovers most of the gap.

### Run 5: recombination of saved forecasts, no new calls (same 18 development cutoffs)

| Design | Mean (1, 2, 4) |
|---|---:|
| E3: mean of the walk-forward blend (simulation, language model, damped trend) and T3 | 22.85 |
| E2: walk-forward blend over the four | 23.06 |
| E1: walk-forward blend over three | 23.34 |
| E4: E2 with a level correction | 24.24 |
| E5: E1 with a level correction | 24.53 |

The level corrections made things worse.

## 4. The held-out test: 7 weekly cutoffs, 2026-09-07 to 2026-10-19

Horizons 1, 2 and 4 cover 7, 6 and 4 cutoffs; no 8-week horizon had elapsed. Each design was frozen in the protocol before being scored here. These weeks were used three times (Runs 3, 4 and 5), so E3's and T3's results are weaker evidence than D4's.

| Method | 1 wk | 2 wk | 4 wk | Mean | Accuracy |
|---|---:|---:|---:|---:|---:|
| E3 (Run 5; the board's method) | 22.9 | 25.2 | 23.2 | 23.77 | 76.2 |
| D4 (Run 3) | 23.0 | 25.6 | 23.0 | 23.90 | 76.1 |
| T3 (Run 4) | 22.9 | 25.6 | 23.6 | 24.05 | 76.0 |
| Damped trend | 23.0 | 25.4 | 23.9 | 24.07 | 75.9 |
| Language model | 23.7 | 26.5 | 24.0 | 24.72 | 75.3 |
| WORKCAST simulation | 23.6 | 27.0 | 24.0 | 24.87 | 75.1 |
| Timestral alone | 23.7 | 27.5 | 27.3 | 26.18 | 73.8 |
| Recent trend | 30.4 | 29.6 | 28.1 | 29.37 | 70.6 |
| No change | 28.4 | 30.2 | 34.7 | 31.08 | 68.9 |
| Market growth | 31.9 | 32.8 | 33.7 | 32.79 | 67.2 |

Reading: the top four methods sit within 0.3 points of each other, and single weeks swing by more than that (the combined method's 1-week accuracy ranged from 58.6% to 89.7% across the 25 scored weeks). The real gain over the simple standards is 5 to 9 points. The gain over the damped trend is not yet established.

## 5. Equal-information check

`board/results/fair_inputs.json`: the damped trend given the full history since January 2025 (what the simulation sees) instead of 12 weeks. Backtest 1-week error 22.2 vs 22.5; on the held-out weeks 23.1 vs 23.0. Its short window was not holding it back.

## 6. What is settled and what is not

Settled:
- Every method beats no change, recent trend and market growth by a wide margin at every horizon.
- The simulation alone loses to the damped trend on tokens in the 1,600-forecast backtest.
- Blends that include the language model and the damped trend have the best held-out mean, by a small margin.

Not settled:
- Whether the blend beats the damped trend: the margin is inside week-to-week noise.
- Spend against the damped trend: re-scoring in progress.
- The 8-week horizon for any blend: only the live board will show it.
- Model-mix prediction: the simulation captures 8 of the 36 points of share that went to new models.

Claims to retire or re-state once the re-scoring lands: "21% less error one week ahead" (README, PR #1) and the AI-spend figures (48%, $134K a year), both measured against the three simple standards only.
