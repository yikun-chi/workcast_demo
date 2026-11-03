import { h, replace, badge, errorState, loading, emptyState, fmtNum, drawer, downloadCsv } from "../components/ui.js";
import { dataGrid } from "../components/grid.js";

export async function render(root, ctx) {
  const { api, instanceId, params, href } = ctx;
  root.append(h("p", {class: "muted small"}, "Search across all records, sort columns, or export a page as CSV. Select a row for complete record details.",
    ctx.readOnly ? " Searching or sorting a large table may take a moment." : ""));
  const list = h("div", { class: "card tight table-list" }, loading("Loading tables"));
  const right = h("div", null, emptyState("Select a table."));
  root.append(h("div", { class: "data-layout" }, h("div", null, list), right));

  let tables;
  try { tables = await api.tables(instanceId); } catch (e) { replace(list, errorState(e, instanceId, "Tables")); return; }
  if (!tables.length) { replace(list, emptyState("No tables yet.", h("span", null, "Run ", h("code", null, `orgsim ingest ${instanceId}`), " to normalize the raw data."))); replace(right); return; }

  const preferred = ["population.parquet", "user_roles.csv", "apps.parquet", "groups.parquet"];
  const selected = params[0] || preferred.find(name => tables.some(t => t.name === name)) || tables[0].name;
  replace(list, h("div", { class: "muted small", style: { padding: "4px 10px 6px" } }, `${tables.length} table${tables.length === 1 ? "" : "s"}`),
    ...tables.map(t => h("a", { class: `item ${t.name === selected ? "active" : ""}`, href: href(instanceId, "data", "tables", t.name), title: t.error || t.name },
      h("div", null, h("div", { class: "mono", style: { fontSize: "12.5px", wordBreak: "break-all" } }, t.name), h("div", { class: "meta" }, t.error ? `error: ${t.error}` : `${fmtNum(t.rows)} rows · ${t.columns.length} columns`)))));

  const t = tables.find(x => x.name === selected);
  if (!t) { replace(right, emptyState(`Unknown table ${selected}.`)); return; }
  if (t.error) { replace(right, errorState(new Error(t.error))); return; }
  replace(right,
    h("div", { class: "row", style: { marginBottom: "10px", justifyContent: "space-between" } },
      h("div", { class: "row" }, h("h2", { class: "mono" }, t.name), badge(`${fmtNum(t.rows)} rows`, "accent"), badge(`${t.columns.length} columns`)),
      h("a", {class: "small", href: href(instanceId, "input")}, "View input schema →")),
    dataGrid({
      columns: t.columns, pageSize: 50, exportName: `${instanceId}_${t.name.replace(/[^\w.-]+/g, "_")}`, maxHeight: "calc(100vh - 290px)",
      fetchPage: async ({ offset, limit, q, sort, desc, onProgress }) => api.table(instanceId, t.name, { offset, limit, q, sort, desc }, onProgress),
      onRowClick: row => {
        const key = ["person_id", "user", "case_id", "app_id", "group_id", "id"].find(c => row[c] != null);
        drawer.open(key ? `Record: ${row[key]}` : "Record details", h("div", {class: "stack record-detail"},
          h("p", {class: "muted small"}, `${t.name} · All ${t.columns.length} fields from this saved input record.`),
          h("button", {class: "btn sm", onClick: () => downloadCsv(`${instanceId}_record.csv`, t.columns, [row])}, "Export this record"),
          h("table", {class: "table record-fields"}, h("tbody", null, ...t.columns.map(c => h("tr", null,
            h("th", {scope: "row"}, c), h("td", {class: row[c] == null ? "muted" : ""},
              row[c] == null ? "Missing" : typeof row[c] === "object" ? JSON.stringify(row[c], null, 2) : String(row[c]))))))));
      },
    }));
}
