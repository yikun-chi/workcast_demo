# Plan 03: the real-workload test and the cascade

Written 2026-11-04 before scripts 08 and 09 ran. Results go to `results_03_20261104/`. Runs on the laptop, where the usage files are. No paid API calls. No prompt text, file path, project name or session identifier leaves the machine; outputs are aggregates.

## Inputs

| Input | Location | Fixed by |
|---|---|---|
| Claude Code session logs | `~/.claude/projects/**/*.jsonl` and `~/.claude-harvard/projects/**/*.jsonl`, read-only | file count, byte total and date range recorded in the results summary |
| List prices with cache read and write | `inputs_openrouter/models_2026-11-03.json` | sha256 in `inputs_sha256.txt` |
| Fast-mode and retired-model prices | `inputs_03/anthropic_prices_latest_week.csv`, exported from the iMac `price_weekly` for the latest week | sha256 in `inputs_03/inputs_03_sha256.txt` |
| SWE-bench Verified per-instance results, mini-swe-agent 2.0.0 batch of 2026-02-17 | `inputs_03/swebench/<submission>/{metadata.yaml,per_instance_details.json}` from github.com/SWE-bench/experiments | sha256 per file in `inputs_03/inputs_03_sha256.txt` |

## Script 08: usage file levers

Parse every assistant record with `message.usage`. One API call = one `requestId`; records sharing a requestId (one per content block) count once, with the maximum of each usage field. Fields: timestamp, model, input, cache creation (5-minute and 1-hour), cache read, output, thinking tokens, speed, session file.

Bill at list prices: input at the input price, cache reads at the cache-read price, 5-minute writes at 1.25x input, 1-hour writes at 2x input (Anthropic docs, `sources_02.md`), output at the output price. Fast-mode calls (`speed` other than standard) at the fast variant's price where one is listed, otherwise flagged and billed at standard. Models map from the log name (`claude-opus-5-5`) to the snapshot id (`anthropic/claude-opus-5.5`) by a table in the script.

Measures, overall and by calendar month:

1. Realized cache rate = cache reads / (input + writes + reads).
2. Bill composition: reads, writes, uncached input, output, thinking share of output.
3. Expiry writes. Within a session file, order calls by time. A call is an expiry re-write when the gap from the previous call exceeds the lifetime of that previous call's writes (5 minutes or 1 hour) and the call's cache creation is at least 0.8 times the previous call's cached prefix (reads plus writes). The expiry share is the cost of those writes over the bill.
4. Lever A, cache lifetime: counterfactual where expiry writes are billed as reads (a keep-alive or a lifetime longer than the gap). Reported as the upper bound of lifetime management. Lever A', 1-hour lifetime everywhere: every write at 2x, and only gaps over one hour expire.
5. Lever B, batch: sessions with one assistant call and no tool use are headless single-turn jobs that can wait; their bill at the batch price (50%).
6. Lever V, version lag: tokens on a model after the snapshot listing date of its successor in the family (opus 4.7 to 4.8 to 5 to 5.5; sonnet 5 to 5.5; fable 5 to 5.1), billed at the successor's prices.
7. Lever F, fast mode: fast-mode calls billed at standard price.
8. Stack: V, then F, then A, then B, on the whole file and per month. The share of months at or past 50%.
9. Exploratory, outside the honest stack: Opus tokens at Sonnet prices, labelled as a quality change.

Outputs: `usage_summary.csv` (overall), `usage_by_month.csv`, `usage_by_model.csv`, `levers_file.csv`, `levers_by_month.csv`, `session_distribution.csv` (deciles of session bill and cache rate), `log_08.txt`.

## Script 09: cascade on SWE-bench Verified

Thirteen submissions of the 2026-02-17 batch. For each instance and model: resolved (bool) and cost. Models with fewer than 500 instances are dropped.

For every ordered pair (cheap, expensive) with the cheap member's mean instance cost below the expensive member's:

- Perfect verifier: cost = cost_cheap + (1 - resolved_cheap) x cost_expensive per instance; resolved = resolved_cheap or resolved_expensive.
- Verifier with accuracy a (applied symmetrically to passes and failures): a cheap pass is accepted with probability a (else escalated); a cheap failure is caught with probability a (else accepted and counted unresolved). Expected cost and expected resolution are computed exactly from the per-instance outcomes, with no random draws.
- Saving = 1 - cascade cost / expensive-alone cost. Resolve change = cascade resolve rate - expensive-alone rate.

Report at a in {1.00, 0.95, 0.90, 0.80}. Primary: the best pair by saving at a = 0.90 subject to resolve change at or above 0. Also three-model chains (cheap, mid, expensive) under the same rule.

Outputs: `cascade_pairs.csv`, `cascade_chains.csv`, `cascade_summary.csv`, `models_used.csv`, `log_09.txt`.

## Decision rule

The rationale's table applies. Uninformative conditions: fewer than three months with 100 sessions; fewer than ten models with per-instance costs; cache fields missing on more than 5% of tokens.

## Run

`run_03.sh` runs 08 then 09 on the laptop and writes `results_03_20261104/provenance_manifest_03.md`. Results and the journal entry are committed and pushed the same day.
