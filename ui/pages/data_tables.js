import { h, replace, badge, errorState, loading, emptyState, fmtNum } from "../components/ui.js";
import { dataGrid } from "../components/grid.js";

export async function render(root, ctx) {
  const { api, instanceId, params, href } = ctx;
  root.append(h("div", { class: "page-head" }, h("div", null, h("div", { class: "sub" }, "Tables: every normalized input table under instances/<id>/data/normalized. Search, sort, page, and export the current page as CSV."))));
  const list = h("div", { class: "card tight table-list" }, loading("Loading tables"));
  const right = h("div", null, emptyState("Select a table."));
  root.append(h("div", { class: "data-layout" }, h("div", null, list), right));

  let tables;
  try { tables = await api.tables(instanceId); } catch (e) { replace(list, errorState(e, instanceId, "Tables")); return; }
  if (!tables.length) { replace(list, emptyState("No tables yet.", h("span", null, "Run ", h("code", null, `orgsim ingest ${instanceId}`), " to normalize the raw data."))); replace(right); return; }

  const selected = params[0] ? decodeURIComponent(params[0]) : tables[0].name;
  replace(list, h("div", { class: "muted small", style: { padding: "4px 10px 6px" } }, `${tables.length} table${tables.length === 1 ? "" : "s"}`),
    ...tables.map(t => h("a", { class: `item ${t.name === selected ? "active" : ""}`, href: href(instanceId, "data", "tables", t.name), title: t.error || t.name },
      h("div", null, h("div", { class: "mono", style: { fontSize: "12.5px", wordBreak: "break-all" } }, t.name), h("div", { class: "meta" }, t.error ? `error: ${t.error}` : `${fmtNum(t.rows)} rows · ${t.columns.length} columns`)))));

  const t = tables.find(x => x.name === selected);
  if (!t) { replace(right, emptyState(`Unknown table ${selected}.`)); return; }
  if (t.error) { replace(right, errorState(new Error(t.error))); return; }
  replace(right,
    h("div", { class: "row", style: { marginBottom: "10px", justifyContent: "space-between" } },
      h("div", { class: "row" }, h("h2", { class: "mono" }, t.name), badge(`${fmtNum(t.rows)} rows`, "accent"), badge(`${t.columns.length} columns`)),
      h("div", { class: "muted small" }, "Click a column header to sort")),
    dataGrid({
      columns: t.columns, pageSize: 50, exportName: `${instanceId}_${t.name.replace(/[^\w.-]+/g, "_")}`, maxHeight: "calc(100vh - 290px)",
      fetchPage: async ({ offset, limit, q, sort, desc }) => api.table(instanceId, t.name, { offset, limit, q, sort, desc }),
    }));
}
