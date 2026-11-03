# Worked value case: client copy

Drafted 2026-10-28. Proof points are scored backtests in this repository (`docs/validation.md`: Trip.com, purchase-to-pay; `docs/validation_openrouter.md`: OpenRouter). Not committed: marketing copy, kept out of the PR.

---

## Worked value case

The value case uses an illustrative firm of 3,000 employees. Every proof point comes from a scored backtest against real company data. Every dollar figure shows its working. Real client figures will replace the estimates during our scoping conversations.

### 1. Skip the pilot. Keep the result.

**Classical approach.** Run a pilot, wait six months, then decide. Firms testing several options run several pilots and wait nine months.

**Our result.** Trip.com ran a six-month randomised trial of hybrid work with 1,612 employees. Working only from data collected before the trial, our digital twins predicted the trial's effect on attrition at 2.39 points. The trial measured 2.40. That is **99.6% accuracy**, with **80% less error** than the best published rule of thumb.

**What it saves.** Deciding in four months instead of nine puts the winning intervention to work five months sooner. For a 3,000-person firm, that is **about $2.4 million** in resignations that never happen.

**How we got there.** 3,000 employees × 2.4 points fewer resignations per six months × 5/6 = 60 resignations avoided. 60 × $40,000 replacement cost = $2,400,000. Replacement cost is half of an $80,000 salary, the low end of Gallup's estimate of one-half to two times salary. Assumes the winning intervention performs like Trip.com's.

### 2. Stop paying for idle AI licences.

**Classical approach.** License by job title, then discover the idle seats at renewal. Usage forecasts simply carry last month forward.

**Our result.** Across 1,600 backtested usage forecasts, our simulation predicted next week's usage at **74% accuracy against 67%** for the standard forecast: **21% less error**. For sporadic, on-and-off users, the ones most likely to leave a seat idle, it cut error by **37%**.

**What it saves.** **About $90,000 in year one**, by moving low-use seats to the people who will use them.

**How we got there.** 3,000 seats × $30 per user per month (Microsoft 365 Copilot list price) × 12 = $1,080,000 a year. Assume one seat in three is low-use: $360,000. Recovering a quarter of that = $90,000.

### 3. Launch leadership programmes that land.

**Classical approach.** Pick leaders by seniority, launch, and find out who changed behaviour from a survey months later.

**Our result.** In the Trip.com trial, our twins predicted how many employees would take up the new way of working at **94% accuracy** (55% predicted, 52% actual), working only from data collected before it began. They called the change in work satisfaction to within 0.02 points on a 10-point scale.

**What it saves.** Choosing which leaders join first, in which groups, raises the share of employees showing the target behaviour from 30% to 38%: **about $72,000 a year**.

**How we got there.** 8% of 3,000 employees = 240 more employees showing the behaviour. 240 × $300 of annual value per employee = $72,000. The $300 is a placeholder for the client's own value of the behaviour.

### 4. Budget AI tokens to the dollar.

**Classical approach.** Take last month's token bill and carry it forward. In our backtests, that missed actual AI spend by 30%.

**Our result.** Across 16 backtests on the 100 largest AI apps on OpenRouter, our simulation forecast AI spend at **84% accuracy against 70%**: it missed by 16% where the classical forecast missed by 30%. That is **48% less error**.

**What it saves.** On $650,000 of annual token spend, **about $39,000 a year** in commitment discounts captured, and **$95,000 less budget variance**.

**How we got there.** Budget variance: $650,000 × 30.3% = $196,800 classical miss; $650,000 × 15.7% = $102,200 our miss; difference $94,600. Savings: buying committed capacity at a 40% discount against our forecast instead of the classical one saves $60,594 per $1 million of annual spend in the backtest. × 0.65 = $39,400. Unused commitments are lost and overflow pays full price, as with Microsoft's provisioned-throughput reservations.

### 5. Right-size operations before you hire.

**Classical approach.** Staff to volume. When the backlog grows, add people.

**Our result.** A multinational's purchase-to-pay team expanded its workforce by 60%. Our simulation predicted the share of orders completed on time afterwards at **90% accuracy against 81%** for the best classical method: **45% less error**. Run without the expansion, the simulation showed completion unchanged (11.79% with the new hires, 11.78% without). The bottleneck was never headcount.

**What it saves.** For a finance operations team that grew from 25 to 40, **about $760,000 a year** in wages that bought no faster processing.

**How we got there.** 15 added roles × $50,670 median wage for bookkeeping, accounting and auditing clerks (U.S. Bureau of Labor Statistics, May 2025) = $760,050. Wages only; benefits and recruiting would raise it.

---

## Sources

- Trip.com and purchase-to-pay results: `docs/validation.md`. OpenRouter results: `docs/validation_openrouter.md` and the README lead block.
- Gallup, 13 March 2019: replacing an employee costs one-half to two times annual salary. https://www.gallup.com/workplace/247391/fixable-problem-costs-businesses-trillion.aspx
- Microsoft 365 Copilot, $30 per user per month billed yearly: https://www.microsoft.com/en-us/microsoft-365/enterprise/microsoft-365-plans-and-pricing
- BLS, bookkeeping, accounting and auditing clerks, median $50,670 (May 2025): https://www.bls.gov/ooh/office-and-administrative-support/bookkeeping-accounting-and-auditing-clerks.htm
- Reservation mechanics: https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/azure-openai

## Internal notes (not for the client page)

- **Case 1.** The 80% compares against the earlier-study rule of thumb (2.45 points, 97.8% accurate). Calling it a "rule of thumb" is fair, but the rule of thumb was close too. "Working only from data collected before the trial" describes the calibration inputs; the evaluation is still retrospective (earlier prior revisions were compared against outcomes).
- **Case 2.** Accuracy is per-company weekly token use on OpenRouter, used here as the proof point for usage forecasting. The one-in-three low-use share is an assumption.
- **Case 3.** Take-up is the share of offered home days used. Leadership targeting itself is not tested. The $300 per employee is a placeholder.
- **Case 4.** 16% vs 30% is measured on the combined spend of 100 apps, not within one company.
- **Case 5.** The no-expansion run is a simulated alternative. Concurrent changes in order mix mean the observed change is not a staffing-only effect. 90% and 81% are 1 minus mean absolute error over mean actual completion (1.35 and 2.47 points on 13.1%).
