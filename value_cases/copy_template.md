## Worked value case

The value case uses an illustrative firm of {{firm_employees}} employees. Every proof point comes from a scored backtest against real company data. Every dollar figure shows its working. Real client figures will replace the estimates during our scoping conversations.

### 1. Skip the pilot. Keep the result.

**Classical approach.** Run a pilot, wait {{c1_trial_months}} months, then decide. Firms testing several options run several pilots and wait {{c1_months_classical}} months.

**Our result.** Trip.com ran a {{c1_trial_months}}-month randomised trial of hybrid work with {{c1_trip_employees}} employees. Working only from data collected before the trial, our digital twins predicted the trial's effect on attrition at {{c1_effect_sim}} points. The trial measured {{c1_effect_actual}}. That is **{{c1_accuracy}} accuracy**, with **{{c1_error_reduction}} less error** than the best published rule of thumb.

**What it saves.** Deciding in {{c1_months_ours}} months instead of {{c1_months_classical}} puts the winning intervention to work {{c1_months_sooner}} months sooner. For a {{firm_employees}}-person firm, that is **about {{c1_value}}** in resignations that never happen.

**How we got there.** {{firm_employees}} employees × {{c1_effect_used}} points fewer resignations per {{c1_trial_months}} months × {{c1_months_sooner}} months sooner = {{c1_departures_avoided}} resignations avoided. {{c1_departures_avoided}} × {{c1_replacement_cost}} replacement cost = {{c1_value_exact}}. Replacement cost is half of a {{c1_salary}} salary, the low end of Gallup's estimate of {{c1_replacement_low}} to {{c1_replacement_high}} salary. Assumes the winning intervention performs like Trip.com's.

### 2. Stop paying for idle AI licences.

**Classical approach.** License by job title, then discover the idle seats at renewal. Usage forecasts simply carry last month forward.

**Our result.** Across {{c2_predictions}} backtested usage forecasts, our simulation predicted next week's usage at **{{c2_acc_sim}} accuracy against {{c2_acc_classical}}** for the standard forecast: **{{c2_error_reduction}} less error**. For sporadic, on-and-off users, the ones most likely to leave a seat idle, it cut error by **{{c2_oneoff_error_reduction}}**.

**What it saves.** **About {{c2_value}} in year one**, by moving low-use seats to the people who will use them.

**How we got there.** {{c2_seats}} seats × {{c2_price}} per user per month (Microsoft Copilot list price) × {{c2_months_per_year}} = {{c2_annual_spend}} a year. Assume {{c2_low_use_share}} is low-use: {{c2_low_use_spend}}. Recovering {{c2_recovered_share}} of that = {{c2_value}}.

### 3. Launch leadership programmes that land.

**Classical approach.** Pick leaders by seniority, launch, and find out who changed behaviour from a survey months later.

**Our result.** In the Trip.com trial, our twins predicted how many employees would take up the new way of working at **{{c3_accuracy}} accuracy** ({{c3_takeup_sim}} predicted, {{c3_takeup_actual}} actual), working only from data collected before it began. They called the change in work satisfaction to within {{c3_satisfaction_gap}} points on a {{c3_scale}}-point scale.

**What it saves.** Choosing which leaders join first, in which groups, raises the share of employees showing the target behaviour from {{c3_share_before}} to {{c3_share_after}}: **about {{c3_value}} a year**.

**How we got there.** {{c3_share_gain}} of {{firm_employees}} employees = {{c3_more_employees}} more employees showing the behaviour. {{c3_more_employees}} × {{c3_value_per_employee}} of annual value per employee = {{c3_value}}. The {{c3_value_per_employee}} is a placeholder for the client's own value of the behaviour.

### 4. Budget AI tokens to the dollar.

**Classical approach.** Take last month's token bill and carry it forward. In our backtests, that missed actual AI spend by {{c4_miss_classical}}.

**Our result.** Across {{c4_backtests}} backtests on the {{c4_apps}} largest AI apps on OpenRouter, our simulation forecast AI spend at **{{c4_acc_sim}} accuracy against {{c4_acc_classical}}**: it missed by {{c4_miss_sim}} where the classical forecast missed by {{c4_miss_classical}}. That is **{{c4_error_reduction}} less error**.

**What it saves.** On {{c4_spend}} of annual token spend, **about {{c4_saving}} a year** in commitment discounts captured, and **{{c4_variance_gap}} less budget variance**.

**How we got there.** Budget variance: {{c4_spend}} × {{c4_miss_classical_1dp}} = {{c4_variance_classical}} classical miss; {{c4_spend}} × {{c4_miss_sim_1dp}} = {{c4_variance_sim}} our miss; difference {{c4_variance_gap_exact}}. Savings: buying committed capacity at a {{c4_discount}} discount against our forecast instead of the classical one saves {{c4_saving_per_million}} per {{c4_one_million}} of annual spend in the backtest. × {{c4_spend_in_millions}} = {{c4_saving_exact}}. Unused commitments are lost and overflow pays full price, as with Microsoft's provisioned-throughput reservations.

### 5. Right-size operations before you hire.

**Classical approach.** Staff to volume. When the backlog grows, add people.

**Our result.** A multinational's purchase-to-pay team expanded its workforce by {{c5_expansion}}. Our simulation predicted the share of orders completed on time afterwards at **{{c5_acc_sim}} accuracy against {{c5_acc_classical}}** for the best classical method: **{{c5_error_reduction}} less error**. Run without the expansion, the simulation showed completion unchanged ({{c5_completion_observed}} with the new hires, {{c5_completion_no_expansion}} without). The bottleneck was never headcount.

**What it saves.** For a finance operations team that grew from {{c5_team_before}} to {{c5_team_after}}, **about {{c5_value}} a year** in wages that bought no faster processing.

**How we got there.** {{c5_added}} added roles × {{c5_wage}} median wage for bookkeeping, accounting and auditing clerks (U.S. Bureau of Labor Statistics, {{c5_wage_year}} wage data) = {{c5_value_exact}}. Wages only; benefits and recruiting would raise it.
