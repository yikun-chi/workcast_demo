# Rationale 03: does an honest 50% survive contact with a real workload?

Written 2026-11-04, before any script in this round ran. PI instruction: "I need 50%+ savings on a customer budget. I want to honestly reach that goal. Figure it out, test everything."

## Question

Round 02 found that the cache rate halves the bill on the same model, from a market-level starting point (60% in January 2026) to the September agent norm (88%). That is a statement about OpenRouter's aggregate. No customer has been measured. This round asks two questions.

1. On a real agentic workload, what does each quality-neutral lever save, with the starting point measured from the usage file instead of assumed? The workload is five months of Claude Code sessions on this laptop (June to November 2026, 1,689 session files plus 33 under a second account), which is the closest thing to a customer usage file this project has. Only aggregates leave the machine.
2. Can a verifier-based cascade (cheap model first, escalate on failure) cut agent-coding spend by half at equal or better task resolution? Round 02's text-only router scored at chance. A cascade uses the outcome of the cheap attempt, which the arena data could not give. SWE-bench Verified publishes per-instance resolution and per-instance cost for thirteen models run through one scaffold on one date (mini-swe-agent 2.0.0, 2026-02-17), which allows the cascade to be computed instance by instance.

## Working hypotheses

- **H-already-cached.** A coding agent already caches near the September norm, so the round 02 cache-rate lever gives this customer under 10%. The honest cache lever on such a workload is cache lifetime management: prefixes re-written after the cache expires between turns.
- **H-stack-real.** The quality-neutral stack measured on the file (cache lifetime, batch on headless single-turn jobs, version lag, fast-mode pricing) reaches 50%.
- **H-cascade.** With a verifier at least 90% accurate, a two-model cascade cuts SWE-bench spend by at least 50% against the expensive model alone, with the resolve rate at or above the expensive model's.
- **H-none-real.** Nothing quality-neutral reaches 50% on the real file and no cascade reaches 50% at equal resolution. The claim then stays conditional on the customer's measured starting point, as round 02 left it.

## Crucial tests

1. Realized cache rate by month on the file. Under 0.80 supports the round 02 lever for this customer; 0.85 or above supports H-already-cached.
2. Expiry re-writes: the share of the bill spent writing prefixes that were cached before a gap longer than the cache lifetime. The counterfactual with the gap removed (keep-alive or a longer lifetime) is the cache lifetime lever.
3. The stack on the file, levers applied in order, against the 50% line.
4. The cascade matrix: every ordered pair of the thirteen models, saving against the expensive member alone and the change in resolve rate, at verifier accuracies of 100%, 95%, 90% and 80%.

## Decision table

| Result | Hypothesis left standing | What the site may say |
|---|---|---|
| Stack on the file at or past 50% | H-stack-real | "Half the bill, measured on a five-month agent workload" with the workload described as one user |
| Stack under 50%, cascade at or past 50% at 90% verifier accuracy with resolve rate held | H-cascade | "For test-verified coding work, half the bill" with the verifier condition stated |
| Both under 50% | H-none-real | Round 02 wording only |

## What this round cannot settle

One user's workload is one user. The file holds sessions from a researcher who runs many headless agent swarms, which is not a typical employee. SWE-bench instances are Python repository tasks with hidden tests; a customer's verifier is weaker than hidden tests, which is why verifier accuracy is a parameter and not an assumption. Productivity stays unmeasured; every lever here leaves the model's outputs unchanged or, for the cascade, measures resolution directly.

## When the round is uninformative

- Fewer than three months with at least 100 sessions each.
- Fewer than ten models with per-instance costs in the SWE-bench batch.
- Usage records without cache fields for more than 5% of tokens.
