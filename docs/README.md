# Documentation

Start with the [operational quickstart](../README.md) to install and run the application.
Agents should read [agent.md](../agent.md), the single guide to project context,
design principles, file placement and verification. This page is the documentation index.

| Topic | Guide |
|---|---|
| Installation, keys, data, deployment and verification | [Setup and reproduction](setup.md) |
| Restore exact datasets/runs or publish a new snapshot | [Release snapshots](setup.md#release-snapshots) |
| Refresh the public site through Actions and Pages | [Deployment](setup.md#deployment) |
| Product framing, instance catalog and evidence scope | [Project overview](overview.md) |
| Application services and scientific models | [Architecture](architecture.md) |
| Task-planner architecture, framework adapters and replay | [Task planners](task-planners.md) |
| Instance files, run artifacts, HTTP and planner interfaces | [Contracts](contracts.md) |
| Insights, Scenarios, Results and model internals | [UI guide](ui.md) |
| Add an instance | [Instance template](../instances/_template/README.md) |
| Authored runnable inputs | [Examples](../examples/README.md) |
| Project context, contributor rules and where files belong | [Agent guide](../agent.md) |
| Behavioral assumptions and sources | [Research foundations](literature/foundations.md) |

## Instance evidence

| Instance | Validation |
|---|---|
| Trip.com hybrid work (`trip`) | [Trip.com and procurement](validation.md) |
| Procurement staffing (`bpi19`) | [Trip.com and procurement](validation.md) |
| AI demand (`openrouter`) | [OpenRouter](validation_openrouter.md) |
| Ctrip call-centre home working (`ctrip`) | [Ctrip](validation_ctrip.md) |
| Federal workforce (`fedwork`) | [Federal workforce](validation_fedwork.md) |
| Business AI adoption (`btos_ai`) | [Census BTOS](validation_btos_ai.md) |
| Stack Overflow question volume (`so_chatgpt`) | [Stack Overflow](validation_so_chatgpt.md) |
| AI-assistant occupation mix (`aei_tasks`) | [Economic Index](validation_aei_tasks.md) |

Validation pages and instance reports are generated from evaluations. Update their
builders when changing wording; regenerate them after scoring new inputs. A report
snapshot does not install its underlying data or prove a prospective prediction.
Each page describes its evidence boundaries.

## Supporting material

[Frozen protocols](plans/README.md) record research decisions and data checks;
they are not setup instructions. Their original paths are retained because
evaluations and report builders cite them.

The [prediction board](../board/README.md) is a separate ensemble and publishing
tool. [Value cases](../value_cases/README.md) are financial illustrations built from
sealed source snapshots. Neither replaces the eight instances' validation or the
separate authored workflow. Current instance/data follow-ups are tracked in
[GitHub issues assigned to Sumer](https://github.com/yikun-chi/workcast_demo/issues?q=is%3Aissue+is%3Aopen+assignee%3Asumervaid).
