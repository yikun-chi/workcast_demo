# Rationale 01: how much AI spend could a buyer cut at equal benchmark quality?

Written 2026-11-03, before any savings were computed.

## Question

Sumer wants to say "cut your AI spend by up to 50% without losing productivity". The existing 48% figure is forecast error, so that figure gives this claim zero support. This analysis asks a different question. Across coding spend on OpenRouter, what share could a buyer have saved by moving each model's tokens to a cheaper model that scores at least as high on independent coding benchmarks?

## Working hypotheses

- **H-overpay.** Buyers pay well above the cheapest equal-quality option. Savings reach 50% or more.
- **H-partial.** A real gap exists, and savings land between 15% and 50%.
- **H-efficient.** Higher prices mostly buy higher scores. Savings stay under 15%.
- **H-token-illusion.** List prices show savings that vanish in practice, because cheaper models use more tokens for the same session.

## The crucial test

Primary: spend-weighted saving under the dominance rule in plan 01. This separates H-overpay, H-partial and H-efficient.

Check: median cost of comparable sessions, from OpenRouter's session-cost dataset. This tests H-token-illusion.

| Result | Hypothesis left standing | What the site may say |
|---|---|---|
| Primary at or above 50%, session check at or above 50% | H-overpay | "Up to 50%", tied to benchmark parity on public data |
| Primary at or above 50%, session check below 50% | H-token-illusion | The session-check number, with no 50% |
| Primary from 15% to 50% | H-partial | The measured number |
| Primary below 15% | H-efficient | No savings number |

## What this test can settle

Benchmark parity stands in for productivity. It measures model scores on standard tasks, and it leaves real work output unmeasured. Whatever the result, the phrase "without losing productivity" stays unsupported. The supported wording is "at equal benchmark scores". A customer pilot with a productivity measure is the only route to the productivity claim.

## When the test is uninformative

- Coverage: if models with scores on both benchmarks make up under 50% of window spend, the primary number is uninformative.
- Session check: under 5 usable pairs, or under 30% of latest-week spend, makes that check uninformative.
