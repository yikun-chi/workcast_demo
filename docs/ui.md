# The UI, page by page

Build-free shell under `ui/` (static HTML, CSS and ES modules), served by `orgsim serve` at `/`. Dark theme by
default with the Workcast logo and wordmark; the header toggle and `?theme=light|dark` switch themes.

## Landing page (instance picker)

Headline, one paragraph on what the platform does, then one card per instance: the company, the business question
as the title, three lines (the situation, the data, the alternative explored), and a computed hero (the headline
numbers next to the ground truth, and the alternative's effect in one sentence). "See the results" opens the
instance on its Results tab. Nothing about build status.

## Inside an instance (Results is the default)

1. **Results.** Two numbered parts. *Part 1, actual outcomes and predictions*: observed before, the change,
   and the results after the change. A combined table compares actual outcomes, other predictions, and simulation
   predictions. Trip.com includes the hybrid group's attrition rate and policy impact in the same table;
   impact is the hybrid group's outcome minus the office-only group's outcome during the same period. The
   historical attrition rate belongs in Before, not in that impact subtraction. Uncertainty and employee-group
   details open inside the comparison section. *Part 2, the alternative action and its impact*: its description and what
   changes, the alternative hero, the chart, the key metrics against the simulation of what actually happened with
   the better value highlighted, a link to change and re-run it. Then the report takeaways with the full narrative
   collapsed, the instance's detailed views, and the source notes.
   Trip.com and procurement have a selector for the original alternative and an AI assistant.
   AI comparisons show explicit workload assumptions, matched simulation results, and research context.
   They show no observed AI outcome. Stale comparisons prompt a new run.
2. **Scenarios.** Cards for the baseline (what actually happened) and each named alternative, with what changes.
   Opening one runs it with a seed, edits its parameters (resolved JSON) and sets which model acts in each seat.
   AI scenarios provide five plain-language numeric controls and an effort preview. Save, then **Compare with
   current policy** to refresh the matched AI Results panel. A single run remains available under Run details.
3. **Insights.** Interviews with the simulated agents of the baseline or the alternative run: key insights,
   topics raised, sentiment when it varies, baseline-versus-alternative topic comparison, three interviews with a
   "show all" button, and a footnote stating that everything is simulated.
4. **Overview.** The company, the business question, the intro, three cards (the simulation, the input data, how it is
   kept honest), then the details: key facts, org units, roles with O*NET codes, systems, charts.
5. **Runs.** Runs of all named scenarios: timeline of events per tick, agents (with a digital-twin card in workforce
   worlds), trace explorer, run configuration.
6. **Input** (model internals). Input schemas: table names, record counts, field names,
   types and missing-value allowance, with links to the records. The local application
   also hosts bindings and role/person editors here; old edit URLs resolve to Input.
7. **Data** (model internals). Actual normalized records, with search, column sorting,
   pagination and CSV export. Select a row (or focus it and press Enter) to open every
   field, with unrounded values and explicit missing values. Employee datasets open
   on the population table; process datasets open on worker records. Other datasets
   expose their actual units, such as apps, sectors or workforce cohorts. Local mode
   also has *Object relations*, showing individual people and their connections.
8. **Ontology** (model internals). Concept definitions and relations, such as Person
   → has_role → Role, with usage counts. Individual objects belong in Data.

The public site uses the same modules with run/edit controls hidden. It includes
all normalized table rows, not a sample. Default paging loads compressed chunks on
demand; search/sort examines the entire selected table in a web worker with progress
feedback. No simulation or backend request runs when browsing records. Raw downloads
and saved run traces remain in the release archives.

## Files

- `index.html`, `theme.css` (design tokens: zinc surfaces, emerald accent, rose for the alternative; shared classes
  `.card .kpi .badge .btn .table .grid .hero-card .story-flow .story-table .part-no .quote`), `app.js` (hash
  router, tab order in `CORE_PAGES`, version-stamped module loading), `api.js` (fetch wrapper with a fixture mode).
- `components/`: `ui.js` (DOM helper, drawer, formatting), `chart.js` (chart contract on Chart.js, bands, points),
  `grid.js` (paged data grid), `graph.js` (Cytoscape viewer, type colors), `kpi.js`, `markdown.js`.
- `pages/`: `landing`, `results`, `scenarios`, `insights`, `overview`, `runs`, `input`,
  `data` (+ `data_tables`, `data_graph`), `ontology` (+ `ontology_concepts`). Input
  hosts the existing `data_edit` and `ontology_edit` modules in local mode.
- `data/`: static table client, worker and shared query logic; tests in `tests/js/`.
- `assets/logo.svg`: the Workcast mark, also the favicon.
- `dev/smoke.html?instance=<id>`: exercises every page against the live API and prints `DONE errors=N`;
  `?fixtures=1` runs against `dev/fixtures/*.json`.
