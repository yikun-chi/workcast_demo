# ui

Build-free shell for every instance, served by `orgsim serve` at `/`. Page-by-page guide: [UI guide](../docs/ui.md); JSON shapes:
[contracts](../docs/contracts.md).

- `index.html` (logo, wordmark, pinned cdnjs libraries), `theme.css` (design tokens, dark default), `app.js` (hash
  router, `CORE_PAGES` routes and primary/More navigation, version-stamped module loading), `api.js` (fetch wrapper; `?fixtures=1` serves
  `dev/fixtures/*.json`)
- `components/`: `ui.js`, `chart.js`, `grid.js`, `graph.js`, `kpi.js`, `markdown.js`
- `pages/`: `landing`, `results`, `scenarios`, `insights`, `overview`, `runs`, `data*`, `ontology*`
- `assets/logo.svg`: the Workcast mark and favicon
- `dev/smoke.html?instance=<id>`: exercises every page against the live API and prints `DONE errors=N`
