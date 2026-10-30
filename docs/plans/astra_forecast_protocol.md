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
