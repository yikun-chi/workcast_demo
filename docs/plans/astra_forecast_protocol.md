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
