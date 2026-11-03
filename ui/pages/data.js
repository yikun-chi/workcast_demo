/* Browse actual input records; schemas and local editors live under Input. */
import { h, subtabs } from "../components/ui.js";

export async function render(root, ctx) {
  const {instanceId, params, navigate, href, readOnly} = ctx;
  const views = [{id: "tables", label: "Records", mod: "./data_tables.js"},
    ...(!readOnly ? [{id: "graph", label: "Object relations", mod: "./data_graph.js"}] : [])];
  const known = views.find(v => v.id === params[0]) || (params[0] === "people" && !readOnly ? views[1] : null);
  const view = known || views[0];
  const rest = known ? params.slice(1) : readOnly && ["graph", "people"].includes(params[0]) ? [] : params;
  root.append(h("div", {class: "page-head"}, h("div", null, h("h1", null, "Data"),
    h("p", {class: "sub"}, "Browse the saved input records. Select any row to inspect every field."))));
  if (views.length > 1) root.append(subtabs(views, view.id, id => navigate(href(instanceId, "data", id))));
  const host = h("div", null); root.append(host);
  return (await import(view.mod)).render(host, {...ctx, params: rest});
}
