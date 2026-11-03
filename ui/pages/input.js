/* Input describes the fields and their types. Record values belong in Data. */
import { h, card, fmtNum, subtabs } from "../components/ui.js";

export async function render(root, ctx) {
  const {api, instanceId, instance, params, href, navigate, readOnly} = ctx;
  const views = [{id: "schema", label: "Input schema"}, ...(!readOnly ? [
    {id: "bindings", label: "Edit bindings", mod: "./ontology_edit.js"},
    {id: "people", label: "Edit roles and people", mod: "./data_edit.js"},
  ] : [])];
  const view = views.find(v => v.id === params[0]) || views[0];
  root.append(h("div", {class: "page-head"}, h("div", null, h("h1", null, "Input"),
    h("p", {class: "sub"}, "The tables and fields supplied to the simulation. Open Data to inspect their records."))));
  if (views.length > 1) root.append(subtabs(views, view.id, id => navigate(href(instanceId, "input", id))));
  if (view.mod) return (await import(view.mod)).render(root, ctx);
  const tables = await api.tables(instanceId);
  const schemas = h("div", {class: "stack input-schemas"});
  root.append(h("p", {class: "small"}, instance.source || ""), schemas);
  for (const t of tables) {
    const fields = t.schema || (t.columns || []).map(name => ({name}));
    const rows = fields.map(c => h("tr", null, h("td", {class: "mono"}, c.name),
      h("td", null, c.type || "Not specified"), h("td", null, c.nullable == null ? "Not specified" : c.nullable ? "Yes" : "No")));
    const table = h("table", {class: "table schema-table"},
      h("thead", null, h("tr", null, h("th", null, "Field"), h("th", null, "Type"), h("th", null, "Allows missing values"))),
      h("tbody", null, ...rows));
    const summary = h("div", {class: "row"},
      h("span", {class: "muted small"}, `${fmtNum(t.rows)} records · ${fields.length} fields`),
      h("a", {class: "btn sm", href: href(instanceId, "data", "tables", t.name)}, "View records →"));
    schemas.append(card(t.name, h("div", {class: "stack"}, summary, h("div", {class: "table-wrap"}, table))));
  }
}
