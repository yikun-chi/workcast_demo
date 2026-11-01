# Protocol (draft): GPT-6 Astra as a forecaster of organisational change

Drafted 2026-10-30. Not run. Requires Sumer's approval of key, model and cost cap before any call.

## Question

Does OpenAI's GPT-6 Astra, asked directly, forecast the outcomes of large organisational and market changes better than WORKCAST's simulation and the classical methods, when it cannot have seen the outcome?

## The contamination rule

- **Model:** `gpt-6-astra`, released 3 September 2026. Its knowledge cutoff is 30 April 2026 (OpenAI models page, checked 2026-10-30).
- **Scoring:** a test counts only if every outcome it scores was recorded after 30 April 2026. Earlier cases (Trip.com 2021/2024, Ctrip 2010-11, purchase-to-pay 2018, federal 2025, and Stack Overflow and Census before May 2026) were published before the cutoff. On those, Astra would be recalling the answer, not forecasting it.
- **Recall check (optional, separate):** ask Astra about the six published cases to measure how much of the answer it already knows. This is reported as recall only, never as forecasting accuracy.

## Clean tests (outcomes after the cutoff)

| Test | Change | Cutoff given to Astra | Scored outcome | Comparators |
|---|---|---|---|---|
| Federal workforce (OPM) | Continuing 2026 restructuring after the 2025 resignation programme | Data through April 2026 | Monthly separations by agency group, May to August 2026 | Simulation re-run at the same cutoff; seasonal naive, exponential smoothing, programme calculation |
| AI spend (OpenRouter) | Model launches and price changes | Each cutoff from 11 May 2026 to 31 August 2026 (5 windows) | Each leading app's 8-week tokens | Simulation (already scored); carry-forward, trend, market growth |
| Stack Overflow questions | Continuing AI substitution | 30 April 2026 | Weekly questions, May to October 2026 | Simulation re-run; damped trend, carry-forward |
| AI use by sector (Census, new question wording from November 2025) | AI adoption | 30 April 2026 | Biweekly AI use by sector, May to October 2026 | Simulation re-run; adoption curve, damped trend |

## Prompting

- **What Astra sees:** the same pre-cutoff data the simulation sees, as tables, plus the dated description of the change. It gets no outcome data.
- **What it returns:** point forecasts and a 90% range, as JSON.
- **Repeats:** two samples per prompt. The point forecast is their mean, and the spread is reported.
- **Settings:** the temperature and reasoning effort are fixed in this file before the run.
- **Recording:**
  - every request and response is cached, with token usage and cost (same adapter as the buyer seat, `orgsim/policies/llm.py`);
  - the API's `model` field and system fingerprint are recorded, to confirm the snapshot.

## Scoring

The same error metric as each case's validation, on the same targets. The report covers Astra against the simulation and against the best classical method, as measured, including if Astra wins.

## Cost

- **Price:** $10 per million input tokens and $50 per million output tokens (OpenAI models page). Reasoning tokens are billed as output.
- **Calls:** about 110: federal 41 agency groups × 2 samples; OpenRouter 5 windows × 3; Stack Overflow and Census about 10.
- **Estimate:** about $0.60 a call, so about $65 in total. Proposed hard cap: $100.
- **Key:** to be named and confirmed before the first call.

## Run 1 (frozen 2026-10-30, before any call): OpenRouter windows after the cutoff

- **Authority:** Sumer, 2026-10-30, "Ask Astra for the forecasts made after its knowledge cutoff dates and add them into the website as backtests".
- **Key and cap:** OpenAI project key ending uuMA (iMac credential broker); hard cap $25.
- **Windows:** the five protocol cutoffs after 30 April 2026: 2026-05-11, 2026-06-08, 2026-07-06, 2026-08-03, 2026-08-31. Each has an 8-week horizon, and every scored week is after the model's knowledge cutoff.
- **Input:** the 100 apps WORKCAST forecasts at that cutoff. For each app: its name, category, and weekly tokens for the 12 weeks before the cutoff (a week outside the top 200 is marked as such). Also the weekly market total for the same 12 weeks, and the cutoff date stated as today.
- **Output:** for each app, its cumulative tokens over the first 1, 2, 4 and 8 weeks after the cutoff, as JSON.
- **Model settings:** `gpt-6-astra`, reasoning effort medium, 2 samples per window. The forecast is the mean of the two samples.
- **Score:** the token-weighted error of each app's first-h-week tokens, h = 1, 2, 4, 8 (WAPE). This is the board's metric, on the same actuals (outside top 200 = half the 200th app's volume), compared with WORKCAST's central path and the standard forecasts at the same cutoffs.
- **Prediction (written before the run):** no strong prior. Astra sees the same history as the carry-forward and trend comparators, plus general knowledge of the apps, and its forecast will likely sit near theirs. WORKCAST's edge in the backtest comes from calibrated drift and survival of one-off apps, which a direct forecast may or may not reproduce.

## Run 1 result (2026-10-30)

- **Run:** 10 calls, $1.91 (`board/results/astra_run1_ledger.json`). Every app was answered in every window.
- **Results:** in `board/results/astra_run1_results.json`; responses are cached on the iMac in `/Volumes/PsychDynamicsData/workcast_board/astra/responses/`.
- **Outcome:** GPT-6 Astra had lower mean error than WORKCAST at all four horizons over the five windows, and lower than the best standard forecast at all four. It was not uniform. Astra was far ahead at the 2026-07-06 cutoff and far behind at 2026-08-31.
- **Caveat:** five windows is a small sample.
- **Shown:** on sumervaid.com/predict as measured.
- **Next test, to be pre-registered on the live board:** WORKCAST, Astra and their average, each forecasting the same weeks in advance.

## Run 2 (frozen 2026-10-30, before any Run 2 call): WORKCAST with Astra inside, against every gold standard

- **Authority:** Sumer, 2026-10-30, "I want our method to INCLUDE Astra and to beat all existing gold-standards". Same key (uuMA). The cap stays $25 in total, including Run 1's $1.91.
- **Cutoffs:** every Monday from 2026-05-04 to 2026-08-31 (18), each with an 8-week horizon. All scored weeks are after Astra's knowledge cutoff.
  - Development: the 5 Run 1 cutoffs (2026-05-11, 06-08, 07-06, 08-03, 08-31), whose results have been seen.
  - Held out: the other 13 weekly cutoffs, which are never scored before the design is frozen.
- **Gold standards** (the method must beat each one at the headline horizons):
  - last four weeks carried forward;
  - each app's recent trend;
  - market growth;
  - a damped-trend exponential smoothing model fitted to each app's 12-week history (log scale, parameters by least squares on that history);
  - GPT-6 Astra alone (Run 1 prompt, 2 samples).
- **Candidate designs**, all including Astra, listed here before any Run 2 result:
  - C1: mean of WORKCAST and Astra.
  - C2: geometric mean of WORKCAST and Astra.
  - C3: median of WORKCAST, Astra and the four statistical standards.
  - C4: Astra as refiner. Astra receives the Run 1 input plus WORKCAST's forecast for each app and returns the final forecast (2 samples, mean).
  - C5: mean of WORKCAST, Astra and carry-forward.
- **Selection:** the candidate with the lowest mean error across horizons 1, 2, 4 and 8 on the development cutoffs. It is then frozen in this file and committed before the held-out cutoffs are scored.
- **Metric:** the board's token-weighted error (WAPE) on each app's first-h-week tokens. A week outside the top 200 counts at half the 200th app's volume.
- **Headline:** mean held-out error at 1, 2, 4 and 8 weeks, for the frozen design against every gold standard.

**Run 2 development note (2026-10-30).** In the first development pass, the damped-trend standard's unbounded trend produced 1,475% error at 8 weeks, from apps re-entering the top 200. A broken standard would flatter every other method, so its trend is now bounded at ±15% a week (the bound the recent-trend standard uses), and development was re-scored. All Astra answers were cached, so no new calls were needed. Development was spent $4.20 so far (Run 1 included).

### FROZEN DESIGN: C3 (2026-10-30, before any held-out cutoff was scored)

- **Choice:** C3, the median of WORKCAST, GPT-6 Astra (Run 1 prompt, mean of 2 samples), the four-week carry-forward, recent trend, market growth and the bounded damped-trend model, taken per app and per horizon.
- **Development record** (`board/results/astra_run2_dev.json`, mean error over horizons 1, 2, 4 and 8):
  - C3: 29.1%
  - C4: 29.3%
  - C1: 30.3%
  - C2: 30.5%
  - C5: 30.7%
  - damped trend: 30.8%
  - Astra: 31.0%
  - WORKCAST: 33.8%
  - recent trend: 34.2%
  - carry-forward: 35.5%
  - market growth: 35.7%
- **Prediction for the 13 held-out cutoffs:** C3 has the lowest mean error across horizons. At 1 week the margin over Astra and the damped trend may vanish (development: 23.0% vs 23.1% and 23.2%).
- **Report:** every horizon, including any where a gold standard beats C3.

### Run 2 held-out result (13 weekly cutoffs, scored once after the freeze)

Source: `board/results/astra_run2_test.json`. Mean error across 1, 2, 4 and 8 weeks:

| Method | Mean error |
|---|---:|
| GPT-6 Astra alone | 24.7% |
| Damped trend | 24.7% |
| C3 (frozen) | 25.8% |
| WORKCAST alone | 30.1% |
| Recent trend | 32.0% |
| Market growth | 35.3% |
| Carry-forward | 36.6% |

**The prediction failed.**
- C3 beat WORKCAST alone and three of the five gold standards.
- It tied Astra at 8 weeks (33.8% vs 33.7%).
- It lost to Astra and the damped trend overall.

Cumulative spend for Runs 1 and 2 is $9.19 (`board/results/astra_ledger.json`). The development choice is not revised after this result. Any new design needs new held-out data: cutoffs after 2026-08-31 at the horizons already observed, or the live board.

## Run 3 (frozen 2026-10-30, before any Run 3 call or score): a combination built to beat every standard

- **Authority:** Sumer, 2026-10-30, "Find a way to beat everything". Same key; total cap $25 ($9.19 spent before this run).
- **Components** (all available at forecast time):
  - W: WORKCAST central path.
  - A: GPT-6 Astra (Run 1 prompt, mean of 2 samples).
  - D: the bounded damped-trend model.
- **Candidate designs** (all include W and A):
  - D1: equal-weight mean of W, A and D.
  - D2: equal-weight geometric mean of W, A and D.
  - D3: online inverse-error weights. At each cutoff, each component's weight per horizon is proportional to 1 / its mean error over earlier cutoffs whose horizon had fully elapsed by that cutoff, with equal weights until three such cutoffs exist. Only information available at the cutoff is used.
  - D4: fixed stacking weights per horizon, chosen on the development cutoffs on a 0.1 simplex grid over (W, A, D), with each weight at least 0.1.
- **Development:** the 18 weekly cutoffs from 2026-05-04 to 2026-08-31, all seen in Run 2. Selection is by the lowest mean error over horizons 1, 2 and 4 (the horizons the test can score); horizon 8 is reported too.
- **Held out:** the weekly cutoffs from 2026-09-07 to 2026-10-19, never forecast or scored before. Each is scored at every horizon fully published when the test runs (1, 2 and 4 weeks where available).
- **Standards the frozen design must beat**, at each horizon and on the mean:
  - Astra alone;
  - the damped trend;
  - WORKCAST alone;
  - carry-forward;
  - recent trend;
  - market growth.
- **Prediction:** the frozen design beats all six on the held-out mean. At one horizon it may lose narrowly to Astra or the damped trend.

### RUN 3 FROZEN DESIGN: D4 (2026-10-30, before any held-out cutoff was forecast or scored)

- **Design:** fixed stacking weights per horizon over (WORKCAST, Astra, damped trend), chosen on the 18 development cutoffs (`board/results/astra_run3_dev.json`):

  | Horizon | WORKCAST | Astra | Damped trend |
  |---|---:|---:|---:|
  | 1 week | 0.1 | 0.7 | 0.2 |
  | 2 weeks | 0.2 | 0.5 | 0.3 |
  | 4 weeks | 0.2 | 0.3 | 0.5 |
  | 8 weeks | 0.1 | 0.7 | 0.2 |

- **Development mean error over horizons 1, 2 and 4** (in-sample for D4, which is optimistic):

  | Method | Error |
  |---|---:|
  | D4 | 22.44 |
  | D3 | 22.73 |
  | D1 | 22.79 |
  | D2 | 22.98 |
  | Damped trend | 23.02 |
  | Astra | 23.30 |
  | WORKCAST | 26.80 |
  | Recent trend | 28.83 |
  | Market growth | 32.82 |
  | Carry-forward | 32.88 |

- **Prediction for the held-out cutoffs:** D4 has the lowest mean error. Its in-sample margin is small (0.6 points over the damped trend), so a held-out loss at one horizon is plausible.

### Run 3 held-out result (7 weekly cutoffs, 2026-09-07 to 2026-10-19, scored once)

Source: `board/results/astra_run3_test.json`. Error is the mean over cutoffs; horizons 1, 2 and 4 have 7, 6 and 4 cutoffs, and no 8-week horizon has elapsed yet.

| Method | 1 week | 2 weeks | 4 weeks | Mean |
|---|---:|---:|---:|---:|
| D4 (frozen) | 23.04 | 25.62 | 23.02 | 23.90 |
| Damped trend | 22.98 | 25.37 | 23.85 | 24.07 |
| Astra | 23.67 | 26.50 | 23.98 | 24.72 |
| WORKCAST | 23.61 | 26.97 | 24.03 | 24.87 |
| Recent trend | 30.4 | 29.6 | 28.1 | 29.37 |
| Carry-forward | 28.4 | 30.2 | 34.7 | 31.08 |
| Market growth | 31.9 | 32.8 | 33.7 | 32.79 |

The result matches the prediction:
- D4 has the lowest mean error of all methods.
- It beats Astra, WORKCAST, recent trend, carry-forward and market growth at every horizon.
- It loses narrowly to the damped trend at 1 week (+0.06) and 2 weeks (+0.25), and beats it at 4 weeks (-0.83) and on the mean.

Caveats:
- The sample is small, with overlapping windows.
- At 1 week, D4 minus the damped trend ranges from -4.3 to +6.5 points across cutoffs.
- The 8-week claim needs the live board.

Spend for Runs 1-3 is $11.70 (`board/results/astra_ledger.json`).

## Run 4 (frozen 2026-10-30, before any Run 4 forecast or score): Timestral predicts, Astra adjusts

- **Authority:** Sumer, 2026-10-30, "Use timestral for predictions, Astra to adjust try again". Same key; total cap $25 ($12.05 spent before this run).
- **Base model:** Mistral Timestral 1.0 209M (`mistralai/Timestral-209M`, open weights, Modified MIT licence), zero-shot, on CPU.
  - Input: each app's full weekly history before the cutoff (from 2025-01-06), on a log scale. A week outside the top 200 enters at half the 200th app's volume.
  - Output: the weekly median and the 10% and 90% quantiles for 8 weeks; cumulative forecasts are sums of the weekly medians, back on the token scale.
  - Mistral has not published Timestral's training data or cutoff. OpenRouter app-level series are unlikely to be in it; this is stated as unverified.
- **Candidate designs:**
  - T1: Timestral alone.
  - T2: Astra adjusts Timestral. Astra gets the Run 1 input plus Timestral's cumulative median and 10-90% range for each app, and returns the final cumulative forecast.
  - T3: as T2, with WORKCAST's cumulative forecast added as a further input.
  - T4: the mean of T3 and Timestral.
- **Astra calls:** 1 sample per prompt, to stay within the cap.
- **Development:** the 18 weekly cutoffs from 2026-05-04 to 2026-08-31. Selection is by the lowest mean error over horizons 1, 2 and 4.
- **Test:** the 7 weekly cutoffs from 2026-09-07 to 2026-10-19. These were already used as the held-out test for Run 3's D4, so this is a re-used test set, scored once for the frozen Run 4 design and labelled as such. The fully clean test is the live board.
- **Standards the frozen design must beat:** Timestral alone, Run 3's combined method (D4), the damped trend, Astra alone, WORKCAST alone, carry-forward, recent trend and market growth.
- **Prediction:** the frozen design beats Timestral alone and every other standard on the mean. Whether it beats the damped trend at 1 week is uncertain.

### RUN 4 FROZEN DESIGN: T3 (2026-10-30, before any test cutoff was forecast or scored)

- **Selection:** T3 has the lowest development mean error over horizons 1, 2 and 4 among T1-T4 (`board/results/astra_run4_dev.json`, 18 cutoffs):

  | Method | 1 week | 2 weeks | 4 weeks | 8 weeks | Mean (1, 2, 4) |
  |---|---:|---:|---:|---:|---:|
  | D4 (Run 3; weights fitted on these cutoffs, so in-sample) | 18.8 | 21.9 | 26.7 | 35.2 | 22.44 |
  | **T3** | 18.7 | 22.4 | 27.7 | 35.6 | 22.95 |
  | Damped trend | 19.7 | 22.2 | 27.2 | 36.5 | 23.02 |
  | T2 | 18.8 | 22.7 | 27.8 | 36.1 | 23.11 |
  | Astra | 19.0 | 22.9 | 28.0 | 35.7 | 23.30 |
  | T4 | 19.5 | 24.7 | 33.2 | 52.9 | 25.79 |
  | WORKCAST | 22.7 | 25.6 | 32.1 | 44.0 | 26.80 |
  | Recent trend | 24.9 | 27.9 | 33.6 | 44.1 | 28.83 |
  | T1 (Timestral alone) | 20.9 | 27.2 | 39.1 | 70.6 | 29.10 |
  | Market growth | 29.7 | 32.3 | 36.5 | 43.1 | 32.82 |
  | Carry-forward | 29.4 | 32.1 | 37.1 | 46.7 | 32.88 |

- **What development shows:**
  - Timestral alone is weak on these series: worse than WORKCAST and the damped trend at every horizon, and far worse at 8 weeks.
  - Astra's adjustment recovers most of that gap. T3 is 0.35 points better than Astra alone and 0.07 points better than the damped trend.
  - T3 does not beat D4 in development, though D4's figure is in-sample.
- **Revised prediction for the test cutoffs (written before them, replacing the Run 4 prediction above):**
  - T3 beats Timestral alone, WORKCAST, carry-forward, recent trend and market growth.
  - Against D4, the damped trend and Astra, the margins are within the cutoff-to-cutoff noise, so the test is expected to be close and may be lost.
- **Spend:** the development calls cost $9.97 (36 calls, at most $0.301 each). The total across all Astra runs is $22.02 against the $25 cap.
- **Guard change:** for the test stage, the per-call reservation in the cap guard is set to $0.60, which is twice the largest observed call. It was $2.50.

### Run 4 test result (7 re-used weekly cutoffs, 2026-09-07 to 2026-10-19, scored once)

Source: `board/results/astra_run4_test.json`. Horizons 1, 2 and 4 have 7, 6 and 4 cutoffs; no 8-week horizon has elapsed.

| Method | 1 week | 2 weeks | 4 weeks | Mean |
|---|---:|---:|---:|---:|
| D4 (Run 3, frozen) | 23.0 | 25.6 | 23.0 | 23.90 |
| **T3 (frozen)** | 22.9 | 25.6 | 23.6 | 24.05 |
| Damped trend | 23.0 | 25.4 | 23.9 | 24.07 |
| Astra | 23.7 | 26.5 | 24.0 | 24.72 |
| WORKCAST | 23.6 | 27.0 | 24.0 | 24.87 |
| T1 (Timestral alone) | 23.7 | 27.5 | 27.3 | 26.18 |
| Recent trend | 30.4 | 29.6 | 28.1 | 29.37 |
| Carry-forward | 28.4 | 30.2 | 34.7 | 31.08 |
| Market growth | 31.9 | 32.8 | 33.7 | 32.79 |

The result matches the revised prediction:
- T3 beats Timestral alone, Astra, WORKCAST, recent trend, carry-forward and market growth on the mean.
- T3 beats the damped trend by 0.02 points, which is a tie.
- T3 loses to D4 on the mean by 0.15 points, all of it at 4 weeks. It has the lowest 1-week error of any method (22.9).

Conclusion: a Timestral base does not improve on Run 3's combination. The board keeps D4. Timestral alone is the weakest of the model-based forecasts here: on these series, the zero-shot foundation model is beaten by a bounded damped trend.

Spend: the test calls cost $2.00. The total across all Astra runs is $24.02 against the $25 cap ($23.67 in `board/results/astra_ledger.json`, plus $0.35 in the live dry-run ledger).

## Run 5 (frozen 2026-11-01, before any Run 5 forecast or score): the most accuracy from forecasts already paid for

- **Authority:** Sumer, 2026-11-01, "max out the prediction". No API calls: only saved forecasts are recombined, and the script has no key.
- **Components:** WORKCAST (W), the language model (A), the damped trend (D) and Run 4's T3, all saved per cutoff. T3 is read from the saved responses by ledger position; the gate below checks the position.
- **Every design is walk-forward:** at a cutoff, the weights and corrections use only earlier cutoffs whose horizon had fully elapsed by that cutoff. Before three such cutoffs exist, weights are equal and no correction applies.
- **Candidate designs:**
  - E1: per-horizon stack over W, A, D, on a 0.1 weight grid.
  - E2: as E1 over W, A, D, T3.
  - E3: the mean of E1 and T3.
  - E4: E2 with a level correction: half the log ratio of total actual to total forecast over the last four elapsed cutoffs.
  - E5: E1 with the same level correction.
- **Selection:** lowest mean error over horizons 1, 2 and 4 on the 18 development cutoffs. D4's development score is in-sample, so D4 is not a selection candidate.
- **Test:** the same 7 weekly cutoffs, scored once for the frozen design. This is the third use of these weeks, so the result is labelled as re-used and is weak evidence.
- **Standards:** D4, T3, damped trend, language model alone, WORKCAST alone, Timestral alone, carry-forward, recent trend, market growth.
- **Gate:** D4 and T3 errors recomputed from saved forecasts must match Runs 3 and 4; any gap from today's data refresh is reported.
- **Rule for the live board:** the board stays on D4 unless Sumer decides otherwise. A design that needs T3 also adds a paid weekly call.
- **Prediction:** a gain of a few tenths of a point at most, within week-to-week noise.
