# Project overview

WORKCAST models how people and work processes respond to organizational changes.
Each instance follows the same sequence: **observed before → change → actual outcome,
other prediction, and simulation prediction → alternative behavior**. Before-period
data supplies context and calibration; only after-change predictions are scored.
Interviews describe simulated agents, not statements from real employees.

Trip.com and procurement each include two alternatives: the original policy alternative and an AI
assistant. In Insights’ expanded evidence, use **Explore alternative actions** to switch between them.
AI assumptions are editable in Scenarios; **Compare with current policy** runs a
matched comparison. The AI cases estimate workload and operational effects under
stated assumptions; they have no observed AI outcome in these datasets.

| Instance | Decision or change | Simulation approach | Evidence |
|---|---|---|---|
| `trip` | Trip.com hybrid work | Employee states and attrition | [Validation](validation.md) |
| `bpi19` | Procurement staffing | Work queues, capacity and handoffs | [Validation](validation.md) |
| `openrouter` | AI token demand and spending | App demand and model routing | [Validation](validation_openrouter.md) |
| `ctrip` | Ctrip call-centre home working (2010) | Employee output and attrition | [Validation](validation_ctrip.md) |
| `fedwork` | Federal workforce policy changes | Cohort separation hazards | [Validation](validation_fedwork.md) |
| `btos_ai` | Business adoption of AI | Sector adoption dynamics | [Validation](validation_btos_ai.md) |
| `so_chatgpt` | Stack Overflow after ChatGPT | Adoption and displaced question volume | [Validation](validation_so_chatgpt.md) |
| `aei_tasks` | AI assistant task mix | Occupation-level adoption dynamics | [Validation](validation_aei_tasks.md) |

Trip.com is a retrospective evaluation: neither group's post-change outcomes enter
the current calibration, but the inherited prior history includes outcome-based
selection. Procurement predictions use actual incoming orders and the operating
state at each prediction date. OpenRouter also supplies historical future prices
and model launches, so its archived results are conditional market scenarios. These
are conditional predictions, not an advance prediction of all demand or proof that
staffing alone caused the observed changes.

## Data and licensing

Trip.com replication data, BPI Challenge 2019, and O*NET 31.0 are attributed in their
[Trip.com](../instances/trip/manifests/sources.json),
[BPI](../instances/bpi19/manifests/sources.json), and
[O*NET](../data/manifests/onet_31_0.json) manifests, which record CC BY 4.0 terms.
Source downloads retain their original licenses. Reading PDFs stay local and are
excluded from Git. A code license has not been selected for this repository.

See the [documentation index](README.md) for the evidence and technical guides.
