# Plan: 10-15 more scored retrodictions for the client value case

Drafted 2026-10-28. Goal: more proof points of the form "classical approaches do X; the simulation was better by Y at Z% accuracy; this is expected to save $; here is the calculation", each built on public data and sealed like `value_cases/`.

## How a case qualifies

1. **Public data with a change in the middle** (a policy, a staffing change, a price change, a launch). There must be an observed before period and a scored after period.
2. **A decision a buyer recognises:** headcount, a policy rollout, budget, capacity, or pricing.
3. **Classical comparators** fixed in advance: carry-forward, historical average, trend, and where one exists, the field's standard method.
4. **Calibration on before-data only**, the same rule as the three existing instances. A test checks that deleting after-data leaves the prediction unchanged.
5. **Sealing:** the dataset snapshot is hashed, the evaluation JSON is copied into `value_cases/sources/internal/`, and every figure in the copy goes through `sealed/case_numbers.csv`.
6. **Every result is reported as measured.** Cases where the simulation does not beat the comparators stay out of the client copy, but the record is kept.

## Candidates

Data availability, licence and change dates are being verified from primary sources in `docs/plans/retrodiction_data_check.md`. The table below is the design, not yet the verified status.

| # | Client headline | Public data | The change | World type (reuse) | Classical comparator | Value logic |
|---|---|---|---|---|---|---|
| 1 | Loan turnaround after a process change | BPI Challenge 2012 (Dutch bank loan applications) | Volume and handling changes in the log | process (bpi19 code) | Carry-forward, historical average | Faster decisions: applications won, staff hours |
| 2 | Lending workflow after a system change | BPI Challenge 2017 | Documented system and process changes in 2016 | process | Same | Same |
| 3 | Expense processing after a policy change | BPI Challenge 2020 (TU/e travel and expenses) | 2018 procedure change | process | Same | Back-office hours, late reimbursements |
| 4 | Permit backlogs across five municipalities | BPI Challenge 2015 | Municipal process changes | process | Same | Backlog, staff |
| 5 | IT service desk staffing | BPI Challenge 2013 (Volvo IT incidents) | Volume shifts | process | Same | Agent headcount, SLA misses |
| 6 | Collections after a fines process change | Road Traffic Fine Management log | Legal and process changes | process | Same | Cash collected |
| 7 | Attrition after a return-to-office mandate | OPM federal workforce data, 2025 | Deferred resignation programme and RTO memo (2025) | workforce (trip code) | Carry-forward of separations, trend | Replacement cost (Gallup) |
| 8 | Remote call-centre productivity | Bloom et al. (2015) Ctrip randomised trial | Randomised work from home | workforce | Earlier-study scaling, no change | Output per worker, attrition cost |
| 9 | Quit-rate forecasting by industry | BLS JOLTS | Labour-market shifts | market/forecast | AR, carry-forward | Hiring budget |
| 10 | AI adoption forecast by sector | Census BTOS AI use rate | Biweekly since 2023 | market | Trend, carry-forward | Licence and training budget |
| 11 | Developer AI tool adoption by role | Stack Overflow Developer Survey 2023-2025 | Annual waves | workforce/adoption | Last wave carried forward | Licence targeting |
| 12 | Which tasks AI takes on next | Anthropic Economic Index releases | Successive releases | market | Last release carried forward | Reskilling budget |
| 13 | A knowledge business after ChatGPT | Stack Exchange question volumes | ChatGPT launch, 30 Nov 2022 | market | Trend | Revenue at risk |
| 14 | Demand after a price change | NYC TLC trips | Congestion pricing, 5 Jan 2025 | market | Seasonal carry-forward | Pricing revenue |
| 15 | Demand planning with promotions | M5 (Walmart) | Promotions, SNAP days | market | Seasonal naive, ETS | Inventory cost |
| 16 | Which AI model wins after a launch | OpenRouter (already ingested) | Each model launch | market (openrouter) | Provider history, no change | Model budget |

## Build order

Cheapest and most certain first:

- **Batch A: process logs (1-6).** The `process` world and the bpi19 ingest already exist. Each case is an ingest, a protocol and an evaluation.
- **Batch B: workforce (7-8).** These reuse the `workforce` world, and they make the strongest HR proof points: an RTO mandate and a randomised trial.
- **Batch C: AI adoption and demand (9-16).** This batch needs a light forecasting world for aggregate series. It reuses the market world's calibration, drift and range code.

## Cost

- **Data:** all candidates are free or free-key downloads, pending the check.
- **Compute:** iMac SSD.
- **Paid API:** none unless an LLM seat is chosen. That would need key, model and cost approval first.

## Sealing

Each case adds:
- its snapshot hashes to `value_cases/sources/`;
- its inputs to `03_extract_inputs.py`;
- its figures to `04_compute_cases.py`;
- its paragraph to `copy_template.md`.

`05_render_copy.py` refuses any figure without a sealed row.
