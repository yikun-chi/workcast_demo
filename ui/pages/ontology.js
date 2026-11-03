/* Ontology tab: Concepts = how the concepts of this instance connect (Organization has OrgUnits, Person located_at
   Location, ...) with definitions and counts; Edit = the instance's bindings (roles to O*NET, activities to DWAs, ...). */
import { h, subtabs } from "../components/ui.js";

const VIEWS = [{ id: "concepts", label: "Concepts", mod: "./ontology_concepts.js" }, { id: "edit", label: "Edit", mod: "./ontology_edit.js" }];

export async function render(root, ctx) {
  const { instanceId, params, navigate, href } = ctx;
  const views = ctx.readOnly ? VIEWS.filter(v => v.id !== "edit") : VIEWS;
  const view = views.find(v => v.id === params[0]) || views[0];
  root.append(h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } }, h("h1", { style: { margin: 0 } }, "Ontology"),
    subtabs(views, view.id, (id) => navigate(href(instanceId, "ontology", id)))));
  root.append(h("p", { class: "muted small" }, ctx.readOnly ? "Explore how people, roles, and objects relate in this simulation." : "Define how people, roles, and objects relate to one another."));
  const mod = await import(view.mod);
  const host = h("div", null); root.append(host);
  return mod.render(host, { ...ctx, params: params.slice(1) });
}
