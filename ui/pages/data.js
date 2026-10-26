/* Data tab: Tables = the normalized input tables; Graph = the data as a graph (the organisation, its units, teams, roles,
   locations, systems, activities, and every person with their connections); Edit = roles, headcounts and archetypes. */
import { h, subtabs } from "../components/ui.js";

const VIEWS = [{ id: "tables", label: "Tables", mod: "./data_tables.js" }, { id: "graph", label: "Graph", mod: "./data_graph.js" }, { id: "edit", label: "Edit", mod: "./data_edit.js" }];

export async function render(root, ctx) {
  const { instanceId, params, navigate, href } = ctx;
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
