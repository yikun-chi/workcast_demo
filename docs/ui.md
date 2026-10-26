# The UI, page by page

Build-free shell under `ui/` (static HTML, CSS and ES modules), served by `orgsim serve` at `/`. Dark theme by
default with the Workcast logo and wordmark; the header toggle and `?theme=light|dark` switch themes.

## Landing page (instance picker)

Headline, one paragraph on what the platform does, then one card per instance: the company, the business question
as the title, three lines (the situation, the data, the alternative explored), and a computed hero (the headline
numbers next to the ground truth, and the alternative's effect in one sentence). "See the results" opens the
instance on its Results tab. Nothing about build status.

## Inside an instance (seven tabs; Results is the default)

1. **Results.** Two numbered parts. *Part 1, actual outcomes and predictions*: observed before, the change,
   and the results after the change. A combined table compares actual outcomes, other predictions, and simulation
   predictions. Trip.com includes the hybrid group's attrition rate and policy impact in the same table;
   impact is the hybrid group's outcome minus the office-only group's outcome during the same period. The
   historical attrition rate belongs in Before, not in that impact subtraction. Uncertainty and employee-group
   details open inside the comparison section. *Part 2, the alternative action and its impact*: its description and what
   changes, the alternative hero, the chart, the key metrics against the simulation of what actually happened with
   the better value highlighted, a link to change and re-run it. Then the report takeaways with the full narrative
   collapsed, the instance's detailed views, and the source notes.
2. **Scenarios.** Two cards: the baseline (what actually happened) and the alternative, each with what changes.
   Opening one runs it with a seed, edits its parameters (resolved JSON) and sets which model acts in each seat.
3. **Insights.** Interviews with the simulated agents of the baseline or the alternative run: key insights,
   topics raised, sentiment when it varies, baseline-versus-alternative topic comparison, three interviews with a
   "show all" button, and a footnote stating that everything is simulated.
4. **Overview.** The company, the business question, the intro, three cards (the simulation, the input data, how it is
   kept honest), then the details: key facts, org units, roles with O*NET codes, systems, charts.
5. **Runs.** Runs of the two scenarios: timeline of events per tick, agents (with a digital-twin card in workforce
   worlds), trace explorer, run configuration.
6. **Data** (model internals). *Tables*: the normalized input tables. *Graph*: the data as a graph, people on the
   left, the organisation and everything bound to it on the right; a person's own network on click. *Edit*: roles,
   headcounts, persons and archetypes.
7. **Ontology** (model internals). *Concepts*: the concept graph as this instance uses it, with definitions, counts
   and a relations table. *Edit*: the raw bindings, validated on save.

## Files

- `index.html`, `theme.css` (design tokens: zinc surfaces, emerald accent, rose for the alternative; shared classes
  `.card .kpi .badge .btn .table .grid .hero-card .story-flow .story-table .part-no .quote`), `app.js` (hash
  router, tab order in `CORE_PAGES`, version-stamped module loading), `api.js` (fetch wrapper with a fixture mode).
- `components/`: `ui.js` (DOM helper, drawer, formatting), `chart.js` (chart contract on Chart.js, bands, points),
  `grid.js` (paged data grid), `graph.js` (Cytoscape viewer, type colors), `kpi.js`, `markdown.js`.
- `pages/`: `landing`, `results`, `scenarios`, `insights`, `overview`, `runs`, `data` (+ `data_tables`, `data_graph`,
  `data_edit`), `ontology` (+ `ontology_concepts`, `ontology_edit`).
- `assets/logo.svg`: the Workcast mark, also the favicon.
- `dev/smoke.html?instance=<id>`: exercises every page against the live API and prints `DONE errors=N`;
  `?fixtures=1` runs against `dev/fixtures/*.json`.
