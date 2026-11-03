/* Data tab: Tables = the normalized input tables; Graph = the data as a graph (the organisation, its units, teams, roles,
   locations, systems, activities, and every person with their connections); Edit = roles, headcounts and archetypes. */
import { h, subtabs, card, fmtNum } from "../components/ui.js";

const VIEWS = [{ id: "tables", label: "Tables", mod: "./data_tables.js" }, { id: "graph", label: "Graph", mod: "./data_graph.js" }, { id: "edit", label: "Edit", mod: "./data_edit.js" }];

export async function render(root, ctx) {
  const { instanceId, params, navigate, href } = ctx;
  if (ctx.readOnly) {
    const tables = await ctx.api.tables(instanceId);
    root.append(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Data"),
      h("p", { class: "sub" }, "Sources and table definitions behind the saved simulation."))),
      h("p", { class: "small" }, ctx.instance.source || ""),
      h("p", { class: "muted small" }, "This public view includes aggregate results and table schemas. Individual input records and full run traces are available in the downloadable research snapshot."),
      h("div", { class: "stack" }, ...tables.map(t => card(t.name, h("div", { class: "stack" },
        h("span", { class: "muted small" }, `${fmtNum(t.rows)} rows`),
        h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, h("th", null, "Column"), h("th", null, "Type"))),
          h("tbody", null, ...(t.columns || []).map(c => h("tr", null,
            h("td", null, typeof c === "string" ? c : c.name), h("td", { class: "muted" }, typeof c === "string" ? "" : c.dtype || c.type || "")))))))))));
    return;
  }
  const known = VIEWS.find(v => v.id === params[0]) || (params[0] === "people" ? VIEWS[1] : null);
  const view = known || (params[0] ? VIEWS[0] : VIEWS[0]);
  const rest = known ? params.slice(1) : params;          // a bare table name still opens that table
  root.append(h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } }, h("h1", { style: { margin: 0 } }, "Data"),
    subtabs(VIEWS, view.id, (id) => navigate(href(instanceId, "data", id)))));
  root.append(h("p", { class: "muted small" }, "Edit the people, digital twins, and objects in your company."));
  const mod = await import(view.mod);
  const host = h("div", null); root.append(host);
  return mod.render(host, { ...ctx, params: rest });
}
