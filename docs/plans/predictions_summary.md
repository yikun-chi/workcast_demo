# Summary of all WORKCAST predictions

As of 2026-11-01. Every figure was read from the record named beside it. All results are backtests; the first live forecast is due Monday 2026-11-02.

**Two definitions of accuracy are in use.** The forecast board uses 100% minus token-weighted error. The other cases use 100 × (1 − error ÷ mean actual). Do not compare them across cases as one scale.

## 1. AI demand: forecast board (sumervaid.com/predict)

**Prediction:** tokens used by each of the 100 leading OpenRouter apps, 1, 2, 4 and 8 weeks ahead.

**Held-out weeks**, 7 weekly cutoffs, 2026-09-07 to 2026-10-19. Accuracy, higher is better. Sources: `board/results/astra_run3_test.json`, `astra_run4_test.json`, `astra_run5_test.json`.

| Method | 1 wk | 2 wk | 4 wk | Average | Status |
|---|---:|---:|---:|---:|---|
| E3: walk-forward blend with Timestral + Astra | 77.1 | 74.8 | 76.8 | 76.2 | Best found; third use of these weeks; not live |
| D4: simulation + Astra + damped trend | 77.0 | 74.4 | 77.0 | 76.1 | **What the board publishes**; first scored on these weeks |
| T3: Timestral adjusted by Astra | 77.1 | 74.4 | 76.4 | 76.0 | Second use of these weeks |
| Damped trend | 77.0 | 74.6 | 76.1 | 75.9 | Strongest standard method |
| GPT-6 Astra alone | 76.3 | 73.5 | 76.0 | 75.3 | |
| WORKCAST simulation alone | 76.4 | 73.0 | 76.0 | 75.1 | |
| Timestral alone | 76.3 | 72.5 | 72.7 | 73.8 | |
| Recent trend | 69.6 | 70.4 | 71.9 | 70.6 | |
| No change | 71.6 | 69.8 | 65.3 | 68.9 | |
| Market growth | 68.1 | 67.2 | 66.3 | 67.2 | |

Limits:
- 7 overlapping weeks; horizons cover 7, 6 and 4 cutoffs; no 8-week score yet.
- The top four methods sit within 0.3 points, and single weeks swing by much more.
- Runs 1 to 4 cost $24.02 of the $25 Astra cap (`board/results/astra_ledger.json` plus the live dry-run ledger). Run 5 cost nothing.

**Backtest of the simulation alone,** 16 cutoffs, 1,600 forecasts, 2025-07-07 to 2026-08-31 (`board/results/fair_inputs.json`). Error, lower is better.

| Method | 1 wk | 2 wk | 4 wk | 8 wk |
|---|---:|---:|---:|---:|
| Damped trend, full history | 22.2 | 25.4 | 31.2 | 42.6 |
| Damped trend, last 12 weeks | 22.5 | 25.5 | 31.2 | 42.1 |
| WORKCAST simulation | 25.8 | 29.0 | 34.8 | 43.6 |
| No change | 32.7 | 35.0 | 39.7 | 45.1 |

**The simulation loses to the damped trend at every horizon here.** Its advantage over no change is real. Its lead over standard methods is not, once the damped trend is included.

**Spend** (`docs/validation_openrouter.md`): combined 8-week spend error $9.84M against $18.95M for no change, 48.1% less. Each company's spend error 36.3% against 41.6%. The 90% range contained 87.2% of outcomes. The damped trend has not been scored on spend.

## 2. Other retrodictions

Records: `docs/validation_*.md` and `value_cases/` on branch `value-cases` (PR #2).

| Case | Prediction | WORKCAST | Best comparator | Result | Evidence |
|---|---|---|---|---|---|
| Trip.com, 1,612 employees | Hybrid-work effect on attrition | -2.39 pp (actual -2.40), 99.6% accurate | Rule of thumb -2.45, 97.8% accurate | 80% less error | Retrospective; the rule of thumb was already very close |
| Purchase-to-pay (BPI 2019) | On-time completion after a 60% team expansion | Error 1.35 pp | 2.47 pp | 45% less | Retrospective |
| Ctrip trial | Work-from-home effect on performance score | +0.225 (actual +0.204) | Earlier research +0.360 | 86% less error | Frozen design; **see below** |
| Census BTOS | AI adoption by sector | Error 1.37 pp, 85% accurate | Bass diffusion 1.52 | 9.9% less | Frozen design, held out |
| Stack Overflow after ChatGPT | Question volume | 5,719 questions, 87.2% accurate | Damped trend 9,352 | 38.9% less | Frozen design, held out; data terms unchecked |
| Anthropic Economic Index | Occupation shares of AI use, next release | 0.86 pp, 81.2% accurate | No change 0.86 | **Tie** | 2 held-out cutoffs |
| Federal workforce, 2025 | Agency separations after 2025 changes | 46.3% error, 53.7% accurate | Programme calculation 40.9% | **Loss, 13.2% worse** | Frozen design, held out |

**Ctrip is selectively reported in the client copy.** The 86% is the one effect the simulation won. In the same record:
- Effect on calls: -78.5% against earlier research (+7.6% predicted, +13.4% actual).
- Effect on quits: -18.7 pp actual, -1.3 pp predicted, so the simulation missed nearly all of the effect.

**Unfinished:** branches `banks-retrodiction` (CFPB complaints, NYC 311), `demand-retrodiction` (NYC congestion, JOLTS quits) and `backoffice-retrodiction` (airline operations, Wikipedia traffic) have no finished validation record. The developer-survey case was a NO-GO.

## 3. Value cases in the client copy

Illustrative figures for a 3,000-person firm (`value_cases/out/value_cases_client.md`): Trip.com $2.4M; Ctrip $12.9M a year; purchase-to-pay $760K a year; AI spend $134K a year; licences $18K a year; Stack Overflow $81K per $1M of volume-linked cost.

## 4. Fix before investors see these

1. **"21% less error"** in the README and PR #1 is wrong once the damped trend is included. Removed from the website only.
2. **The AI-spend claims** (48%, $134K) have not been tested against the damped trend.
3. **The Ctrip headline** needs the two losing effects beside it, or the $12.9M dropped. That figure also rests on an assumed 40% of salary.
4. **The one-pager says** each result is against "the best of that set". Check that against item 2 before reuse.
5. **Licences:** confirm the Trip.com data licence and the Stack Exchange API terms.
6. **The live record is the only clean test.** Every backtest above is retrospective or re-uses data to some degree.
