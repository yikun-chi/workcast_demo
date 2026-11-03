# Protocol: Stack Overflow questions after ChatGPT, frozen before the held-out run

Written 2026-10-28, after the development cutoffs and before any held-out cutoff was run.

## Data

- Weekly counts of new Stack Overflow questions, Monday to Sunday, 2021-03-08 to 2026-10-25 (294 weeks), from the
  public Stack Exchange API v2.3 (`/questions?filter=total`), one saved response per week, SHA-256 in
  `instances/so_chatgpt/manifests/sources.json`. Counts exclude deleted questions (the API, like the data dumps, omits
  them), so older weeks have had longer to lose deleted questions.
- Licence: Stack Overflow content is CC BY-SA (2.5, 3.0 or 4.0 by posting date). The API terms require visible
  attribution to the Stack Exchange network and bind users to the Stack Exchange Terms of Service. The official data
  dump has required a login since 2024 and its terms exclude training language models; it is not used. Commercial use
  of the counts should be checked against the Terms of Service before client use.
- History starts 2021-03-08 because the API's anonymous daily quota (300 requests) ran out; earlier weeks can be
  added by rerunning the fetcher, which would change the no-AI baseline fit.
- Change: ChatGPT was released on 2022-11-30; the week of 2022-11-28 (period 90) is the change week.

## Cutoffs and split

- 47 cutoffs: the launch week (period 90, 2022-11-28) and every 4 weeks from period 98 (2023-01-23) to period 278
  (2026-07-06). A cutoff c uses weeks 0..c-1 only.
- Development: the first quarter, 12 cutoffs (periods 90 and 98 to 138, through 2023-10-30). Held out: 35 cutoffs from
  2023-11-27 to 2026-07-06.
- Scored blocks: questions posted in weeks 1-13 and weeks 14-26 after the cutoff (headline), and weeks 27-52 (reported;
  from the launch week this is the "6-12 months after the launch" question).

## Frozen design (`instances/so_chatgpt/calibration/adoption.yaml`)

- 1,000 simulated would-be askers. Each week an asker who still posts may switch to an AI assistant and a switched
  asker may come back, with hazards that move the expected switched share along a diffusion path; the rule seat draws
  each choice. Questions that reach the site = the no-AI baseline times the share still posting.
- No-AI baseline: log-linear trend plus 3 annual Fourier harmonics, fitted on the 90 weeks before the launch only.
- Switched share: 1 - questions / baseline, from the launch week on. Its path: the starting level, recent growth
  (26-week window), drift weight, damping and hazard form (logistic imitation or constant external hazard) are chosen at
  each cutoff from up to 10 backtests two weeks apart whose targets fall before it, by the one-standard-error rule
  against the default (the recent switched share held flat). Range widths come from the same backtests.
- Development change: the growth window was set to 26 weeks (13 weeks was also tried; 26 gave lower development error).

## Comparators (fixed)

carry-forward (last week), recent average (last 4 weeks), linear trend (last 26 weeks, extended), damped-trend
exponential smoothing (ETS A,Ad,N on the weekly counts), Bass diffusion fitted to the switched share since the launch
(times the same no-AI baseline), and same week last year (seasonal naive).

## Headline metric

Mean absolute error of the 13-week question totals (weeks 1-13 and 14-26 after each cutoff), over held-out cutoffs;
error reduction versus the best comparator; accuracy = 100 x (1 - error / mean actual 13-week total).

## Development result (12 cutoffs, 24 predictions)

| | Simulation | Carry-forward | Recent average | Linear trend | Damped trend | Bass | Same week last year |
|---|---:|---:|---:|---:|---:|---:|---:|
| MAE, 13-week totals | 23,489 | 38,354 | 41,838 | 33,829 | 29,442 | 28,578 | 142,396 |

At the launch week nobody foresaw the fall: the simulation's switched share was zero (no adoption observed yet).

## Predicted held-out result

The simulation's error is 10-25% below the best comparator (expected: Bass or the damped trend), with accuracy around
85%. Risks: by 2025 the weekly volume is a small fraction of the baseline, so the switched share is near its ceiling and
small changes in the baseline extrapolation (a 2021-2022 trend carried four years forward) move the prediction; the
simulation may lose in late cutoffs. Results will be reported as measured.

## After the held-out run

Results are reported as measured in `docs/validation_so_chatgpt.md` (generated from `runs/so_chatgpt/evaluation.json`).
Any bug fixed afterwards is recorded below with before and after numbers; no further tuning.

The held-out cutoffs were run once on 2026-10-28 with the frozen design. No bug was found and nothing was changed after the run.
