/* Ontology, Concepts view: the concept graph as this instance uses it. Nodes are concepts (Person, Role, Activity,
   Location, ...), edges the relations they may have; each carries a definition and how many of it the instance has.
   Reads /api/instances/{id}/ontology/concepts. The Bindings view shows the entities themselves. */
import { h, replace, badge, card, errorState, loading, debounce } from "../components/ui.js";
import { graphViewer, typeColor } from "../components/graph.js";

export async function render(root, ctx) {
  const { api, instanceId, href } = ctx;
  const st = { data: null, viewer: null, showUnused: false, layout: "cose", edgeLabels: true };

  const unusedChk = h("label", { class: "check" }, h("input", { type: "checkbox", onChange: (e) => { st.showUnused = e.target.checked; applyVisibility(); renderTable(); } }), "show concepts this instance does not use");
  const layoutSel = h("select", { class: "select sm", onChange: () => { st.layout = layoutSel.value; st.viewer?.runLayout(st.layout); } },
    ...[["cose", "Layout: force (cose)"], ["concentric", "Layout: concentric"], ["breadthfirst", "Layout: breadth-first"]].map(([v, l]) => h("option", { value: v }, l)));
  const edgeBtn = h("button", { class: "btn sm active", onClick: () => { st.edgeLabels = !st.edgeLabels; st.viewer?.setEdgeLabels(st.edgeLabels); edgeBtn.classList.toggle("active", st.edgeLabels); } }, "Relation labels");
  const search = h("input", { class: "input sm", type: "search", placeholder: "Search concepts…", style: { width: "180px" } });
  const fitBtn = h("button", { class: "btn sm", onClick: () => st.viewer?.fit() }, "Fit");

  root.append(h("div", { class: "page-head" },
    h("div", null, h("div", { class: "sub" }, "Concepts: what a Person, Role, Activity, Location or Policy is in this instance and how they connect. Counts come from the bindings, the O*NET subgraph and the normalized data (people, teams, hand-offs). Glossary: Occupation, GWA, IWA, DWA and Task are the O*NET work vocabulary (occupation, then generalized, intermediate and detailed work activities, then task statements) that lets roles in different companies be compared.")),
    h("div", { class: "toolbar" }, unusedChk, edgeBtn, layoutSel, search, fitBtn)));
  const stats = h("div", { class: "statsbar", style: { marginBottom: "10px" } });
  const canvas = h("div", { class: "onto-canvas" });
  const side = h("div", { class: "onto-side" });
  const detail = card("Concept", h("div", { class: "muted small" }, "Click a concept to read its definition, its relations and how many of it this instance has."));
  const layersCard = card("Layers", h("div", { class: "muted small" }, "–"));
  side.append(detail, layersCard);
  const tableCard = card("Relations", loading("Loading"));
  root.append(stats, h("div", { class: "onto-layout" }, canvas, side), h("div", { style: { marginTop: "14px" } }, tableCard));

  const overlay = h("div", { style: { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 5, background: "var(--surface)" } }, loading("Loading concept graph"));
  canvas.append(overlay);
  try { st.viewer = graphViewer(canvas, { onSelect: (n) => showConcept(n ? n.type : null) }); } catch (e) { replace(canvas, errorState(e)); return; }
  search.addEventListener("input", debounce(() => st.viewer.highlight(search.value), 200));

  let destroyed = false;
  try { st.data = await api.concepts(instanceId); } catch (e) { replace(overlay, errorState(e, instanceId, "Concepts")); return; }
  if (destroyed) return;
  const d = st.data;
  const byType = Object.fromEntries(d.concepts.map(c => [c.type, c]));
  overlay.style.display = "none";
  replace(stats, badge(`${d.stats.concepts_used} of ${d.stats.concepts} concepts used`, "accent"), badge(`${d.stats.relations_used} of ${d.stats.relations} relations used`, "accent"),
    h("a", { class: "badge", href: href(instanceId, "data") }, "Inspect actual records in Data →"), d.error ? badge(`bindings: ${d.error}`, "warn") : null);
  replace(layersCard.lastChild, h("div", { class: "stack small", style: { gap: "6px" } },
    ...Object.entries(d.layers || {}).map(([k, v]) => h("div", null, badge(k, k === "runtime" ? "warn" : k === "onet" ? "" : "accent"), " ", h("span", { class: "muted" }, v)))));

  st.viewer.setData(d.schema);
  st.viewer.setEdgeLabels(true);
  applyVisibility();
  renderTable();

  function applyVisibility() {
    const hidden = new Set(st.showUnused ? [] : d.concepts.filter(c => !c.used).map(c => c.type));
    st.viewer.setTypeVisibility(hidden);
    st.viewer.runLayout(st.layout);
  }

  function showConcept(type) {
    if (!type) { replace(detail.lastChild, h("div", { class: "muted small" }, "Click a concept to read its definition, its relations and how many of it this instance has.")); return; }
    const c = byType[type] || { type, description: "", layer: "", count: 0, used: false };
    const out = d.relations.filter(r => r.source === type && (st.showUnused || r.used)), inc = d.relations.filter(r => r.target === type && (st.showUnused || r.used));
    const relRow = (r, dir) => { const other = dir === "out" ? r.target : r.source; return h("div", { class: "small", style: { padding: "4px 0", borderBottom: "1px solid var(--border)" } },
      h("div", { class: "row", style: { gap: "6px" } }, h("span", { class: "muted" }, dir === "out" ? "→" : "←"), h("code", null, r.type), h("a", { href: "#", style: { borderLeft: `3px solid ${typeColor(other)}`, paddingLeft: "5px" }, onClick: (e) => { e.preventDefault(); st.viewer.select(`type:${other}`); showConcept(other); } }, other), r.count ? h("span", { class: "muted mono" }, r.count.toLocaleString()) : null),
      h("div", { class: "muted" }, r.description)); };
    replace(detail.lastChild, h("div", { class: "stack" },
      h("div", { class: "row" }, h("span", { class: "sw", style: { display: "inline-block", width: "12px", height: "12px", borderRadius: "3px", background: typeColor(type) } }), h("h3", { style: { margin: 0 } }, type), c.layer ? badge(c.layer, c.layer === "runtime" ? "warn" : c.layer === "onet" ? "" : "accent") : null, c.used ? null : badge("not used here", "")),
      h("div", null, c.description),
      h("div", { class: "row small" }, h("span", { class: "muted" }, "In this instance:"), h("b", null, c.layer === "runtime" ? "created during runs" : c.count.toLocaleString())),
      h("h4", null, `Relations out (${out.length})`), out.length ? h("div", null, ...out.map(r => relRow(r, "out"))) : h("div", { class: "muted small" }, "none"),
      h("h4", null, `Relations in (${inc.length})`), inc.length ? h("div", null, ...inc.map(r => relRow(r, "in"))) : h("div", { class: "muted small" }, "none")));
  }

  function renderTable() {
    const rows = d.relations.filter(r => st.showUnused || r.used);
    const cell = (t) => h("td", null, h("a", { href: "#", style: { borderLeft: `3px solid ${typeColor(t)}`, paddingLeft: "5px" }, onClick: (e) => { e.preventDefault(); e.stopPropagation(); st.viewer.select(`type:${t}`); showConcept(t); } }, t));
    replace(tableCard.lastChild, h("div", { class: "table-wrap", style: { maxHeight: "480px" } }, h("table", { class: "table concept-table" },
      h("thead", null, h("tr", null, h("th", null, "Concept"), h("th", null, "Relation"), h("th", null, "Concept"), h("th", { class: "desc" }, "Meaning"), h("th", { style: { textAlign: "right" }, title: "edges of this relation type in the instance (bindings + data)" }, "count"))),
      h("tbody", null, ...rows.map(r => h("tr", { class: r.used ? "" : "muted", onClick: () => { st.viewer.select(`type:${r.source}`); showConcept(r.source); } },
        cell(r.source), h("td", null, h("code", null, r.type)), cell(r.target), h("td", { class: "desc" }, r.description),
        h("td", { class: "mono", style: { textAlign: "right" } }, r.count ? r.count.toLocaleString() : h("span", { class: "muted" }, byType[r.source]?.layer === "runtime" || byType[r.target]?.layer === "runtime" ? "runs" : "–"))))))),
      h("div", { class: "muted small", style: { marginTop: "6px" } }, `${rows.length} of ${d.relations.length} relations. Counts are per relation type; a type joining several concept pairs shows the same total on each row.`));
  }

  root._concepts = st;
  return () => { destroyed = true; try { st.viewer?.destroy(); } catch { /* ignore */ } };
}
