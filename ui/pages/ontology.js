/* Ontology is the shared vocabulary and relations between concepts, not objects. */
import { h } from "../components/ui.js";

export async function render(root, ctx) {
  root.append(h("div", {class: "page-head"}, h("div", null, h("h1", null, "Ontology"),
    h("p", {class: "sub"}, "Concepts and their relationships: for example, a Person has a Role. Individual records are in Data."))));
  return (await import("./ontology_concepts.js")).render(root, ctx);
}
