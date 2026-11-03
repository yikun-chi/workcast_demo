# The shared browser UI

Build-free HTML, CSS and ES modules under `ui/`, served locally by `orgsim serve`
and publicly from the same source via GitHub Pages. Dark/light themes share the
same layout. The landing page selects an instance and opens **Insights**.

## Reading order

1. **Insights** answers “How close was the simulation?” and “What changes under
   alternatives?” Lead with one outcome, actual/other/simulation values, and a
   scoped verdict. Alternative cards show changes against their own matched
   reference runs. Material evidence limits stay visible. Methods, before/change
   context, all metrics, uncertainty, source notes and detailed comparison views
   open under **Evidence, methods and all comparisons**. An average prediction
   level and average per-period error are different statistics; never conflate them.
2. **Scenarios** shows concise cards: title, one sentence, **View details**. Details
   hold the assumptions, not the overview cards. In the interactive app, **Add new
   scenario** opens a form, copies an existing scenario through inheritance and
   opens the editor. Public mode displays a disabled card with an explanation.
   Local AI scenarios retain the five assumption controls, effort preview and
   **Compare with current policy** action; this refreshes the comparison in Insights.
3. **Results** starts with scenario cards. A selected scenario shows key metrics
   and a trend for one saved run. Expand **Explore simulation history** to select
   the whole simulation or an entity, play/step through saved states, select chart
   points and zoom. A button provides the same zoom action as double-clicking.
   Recorded events support search, sorting, entity/time filtering and a complete
   event drawer. Interviews, entity fields, all metrics and configuration are
   expandable. Comparisons across scenarios belong in Insights.

Results identifies the run, population and period. Its one-run numbers can differ
from evaluation averages in Insights. Saved interviews pin the chosen run where
available; otherwise the latest completed scenario run is selected. Interview text
is labeled simulated. Workforce runs expose saved people/states, procurement exposes
workers and events, markets expose apps/weeks, federal cohorts expose agencies/months,
and adoption models expose group/period paths. Legacy federal employee-style voices
do not describe the agency separation paths and are excluded from the interview view.
Playback never interpolates missing
person or hourly histories. Sampled work events remain labeled as sampled.

## Model internals

- **Input:** schemas with field names, types and missing-value allowance; local
  bindings and role/person editors. No record grid is substituted for the schema.
- **Data:** all normalized records with whole-table search/sort, paging and CSV
  export. Click a row, or focus it and press Enter, for every field with unrounded
  values and explicit missing values. Local Object relations shows individual
  entities and their links.
- **Ontology:** concept definitions and relations, such as Person → has_role → Role.

## Static browsing

The public site rejects mutations and hides run/edit controls. All normalized input
records and one selected run per named scenario are exported as checksummed gzip
resources. Paging loads only needed chunks; whole-table searches/sorts run in a
worker with progress. Expanding a history loads saved outputs; it never reruns a
simulation. Bulk ensembles and raw download archives remain release attachments.

## File ownership

- `app.js`: routes and tab order. Old Overview/report URLs redirect to Insights;
  Runs URLs redirect to scenario Results. Old model-edit URLs redirect to Input.
- `api.js`: local, fixture and public adapters. `/results` is still the evaluation
  comparison payload; `/insights` is still the saved interview payload.
- `pages/insights.js`, `comparison_details.js`: concise conclusions and lazy evidence.
- `pages/scenarios.js`: overview cards, creation and scenario editing.
- `pages/results.js`, `components/scenario_interviews.js`: selected-run exploration.
- `pages/input.js`, `data*.js`, `ontology*.js`: model internals; Input hosts the
  existing `data_edit` and `ontology_edit` modules.
- `components/`: shared DOM, drawers, grids, charts, graphs and Markdown.
- `data/`: static queries, client and worker; verification in `tests/js/`.
- `orgsim/evaluation/presentation.py`, `history.py`: read-only artifact projections.
  `instances/<id>/ui/presentation.yaml` owns authored labels and metric selection,
  never manually entered result values.
- `dev/smoke.html?instance=<id>`: live-browser checks; require `DONE errors=0`.
  Fixture data is only for development, never published evidence.
