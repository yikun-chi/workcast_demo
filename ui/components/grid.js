/* Data grid with search, column sort, pagination and CSV export.
   Server mode: fetchPage({offset, limit, q, sort, desc}) -> {columns, rows, total}
   Static mode: pass rows/columns and the grid does search/sort/page client-side. */
import { h, replace, fmtCell, downloadCsv, debounce, loading, errorState, emptyState } from "./ui.js";

export function dataGrid(opts) {
  const state = { offset: 0, limit: opts.pageSize || 50, q: "", sort: opts.sort || "", desc: !!opts.desc, columns: opts.columns || [], rows: [], total: 0, loading: false };
  const root = h("div", { class: "data-grid" });
  const toolbar = h("div", { class: "grid-toolbar" });
  const search = h("input", { class: "input sm", type: "search", placeholder: opts.searchPlaceholder || "Search…", style: { width: "220px" } });
  const totalEl = h("span", { class: "muted small" });
  const exportBtn = h("button", { class: "btn sm", title: "Export the current page as CSV" }, "Export CSV");
  const sizeSel = h("select", { class: "select sm" }, ...[25, 50, 100, 200].map(n => h("option", { value: n, selected: n === state.limit }, `${n} / page`)));
  if (opts.search !== false) toolbar.append(search);
  if (opts.extraControls) toolbar.append(...[].concat(opts.extraControls));
  toolbar.append(h("span", { class: "spacer" }), totalEl, sizeSel, exportBtn);
  const wrap = h("div", { class: "table-wrap", style: opts.maxHeight ? { maxHeight: opts.maxHeight } : null });
  const pager = h("div", { class: "pager" });
  root.append(toolbar, wrap, pager);

  async function getPage() {
    if (opts.fetchPage) return opts.fetchPage({ offset: state.offset, limit: state.limit, q: state.q, sort: state.sort, desc: state.desc ? 1 : 0 });
    let rows = opts.rows || [];
    const s = state.q.toLowerCase();
    if (s) rows = rows.filter(r => Object.values(r).some(v => String(v ?? "").toLowerCase().includes(s)));
    if (state.sort) { const k = state.sort, d = state.desc ? -1 : 1; rows = [...rows].sort((a, b) => { const x = a[k], y = b[k]; if (x === y) return 0; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : 1) * d; }); }
    return { columns: state.columns.length ? state.columns : Object.keys(rows[0] || {}), total: rows.length, rows: rows.slice(state.offset, state.offset + state.limit) };
  }

  async function load() {
    state.loading = true; replace(wrap, loading());
    try {
      const page = await getPage();
      state.rows = page.rows || []; state.total = page.total ?? state.rows.length;
      if (page.columns && page.columns.length) state.columns = page.columns;
      else if (!state.columns.length && state.rows.length) state.columns = Object.keys(state.rows[0]);
      renderTable(); renderPager();
    } catch (e) { replace(wrap, errorState(e)); replace(pager); }
    state.loading = false;
  }

  function renderTable() {
    if (!state.rows.length) { replace(wrap, emptyState(state.q ? "No rows match the search." : (opts.emptyText || "No rows."))); return; }
    const thead = h("thead", null, h("tr", null, ...state.columns.map(c => {
      const sorted = state.sort === c;
      return h("th", { class: `sortable ${isNumCol(c) ? "num" : ""}`, title: c, onClick: () => { if (sorted) state.desc = !state.desc; else { state.sort = c; state.desc = false; } state.offset = 0; load(); } },
        opts.columnLabels?.[c] || c, sorted ? h("span", { class: "sort-ind" }, state.desc ? "▼" : "▲") : null);
    })));
    const tbody = h("tbody");
    for (const r of state.rows) {
      const tr = h("tr", { class: opts.isSelected && opts.isSelected(r) ? "selected" : "", style: opts.onRowClick ? { cursor: "pointer" } : null, onClick: opts.onRowClick ? () => opts.onRowClick(r) : null });
      for (const c of state.columns) {
        const v = r[c];
        const custom = opts.render?.[c];
        tr.append(h("td", { class: typeof v === "number" ? "num" : "", title: typeof v === "object" ? "" : String(v ?? "") }, custom ? custom(v, r) : fmtCell(v)));
      }
      tbody.append(tr);
    }
    replace(wrap, h("table", { class: "table" }, thead, tbody));
  }
  function isNumCol(c) { return state.rows.length > 0 && state.rows.every(r => r[c] === null || typeof r[c] === "number"); }

  function renderPager() {
    const pages = Math.max(1, Math.ceil(state.total / state.limit)); const cur = Math.floor(state.offset / state.limit) + 1;
    totalEl.textContent = `${state.total.toLocaleString("en-US")} rows`;
    const go = (p) => { state.offset = (p - 1) * state.limit; load(); };
    replace(pager,
      h("button", { class: "btn sm", disabled: cur <= 1, onClick: () => go(1) }, "«"),
      h("button", { class: "btn sm", disabled: cur <= 1, onClick: () => go(cur - 1) }, "‹"),
      h("span", null, `Page ${cur} of ${pages.toLocaleString("en-US")}`),
      h("button", { class: "btn sm", disabled: cur >= pages, onClick: () => go(cur + 1) }, "›"),
      h("button", { class: "btn sm", disabled: cur >= pages, onClick: () => go(pages) }, "»"),
      h("span", { class: "spacer" }),
      h("span", null, `Showing ${state.total ? state.offset + 1 : 0}–${Math.min(state.total, state.offset + state.rows.length)}`));
  }

  search.addEventListener("input", debounce(() => { state.q = search.value.trim(); state.offset = 0; load(); }, 300));
  sizeSel.addEventListener("change", () => { state.limit = +sizeSel.value; state.offset = 0; load(); });
  exportBtn.addEventListener("click", () => downloadCsv(`${opts.exportName || "export"}_page${Math.floor(state.offset / state.limit) + 1}.csv`, state.columns, state.rows));

  load();
  return Object.assign(root, { reload: load, setParams: (p) => { Object.assign(state, p); state.offset = 0; load(); }, state });
}
