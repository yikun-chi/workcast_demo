/* Ontology graph viewer on Cytoscape.js 3.30.4 (global `cytoscape`). Colors and shapes by node type with a legend. */
import { h } from "./ui.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* Fixed type -> {color token, shape}. Shape is the secondary (non-color) encoding. */
export const TYPE_STYLE = {
  Organization: { c: "--s7", shape: "star" },
  OrgUnit: { c: "--s1", shape: "round-rectangle" },
  Person: { c: "--s5", shape: "ellipse" },
  Role: { c: "--s2", shape: "round-rectangle" },
  Occupation: { c: "--s4", shape: "round-hexagon" },
  GWA: { c: "#8a9bb0", shape: "round-triangle" },
  IWA: { c: "#6fb3c9", shape: "round-triangle" },
  DWA: { c: "--s3", shape: "round-triangle" },
  Task: { c: "#b0b7c3", shape: "triangle" },
  Activity: { c: "--s6", shape: "round-diamond" },
  WorkItem: { c: "--s8", shape: "rectangle" },
  Artifact: { c: "#c29a6b", shape: "round-tag" },
  System: { c: "#8f6fe8", shape: "barrel" },
  Capability: { c: "#b79ff0", shape: "round-rectangle" },
  Location: { c: "#5fa8a0", shape: "round-pentagon" },
  ExternalActor: { c: "#d08f3f", shape: "ellipse" },
  Message: { c: "#9aa4ad", shape: "vee" },
  Policy: { c: "#d7a300", shape: "round-octagon" },
  Event: { c: "#7f8c8d", shape: "diamond" },
  LatentState: { c: "#c76f98", shape: "concave-hexagon" },
};
export function typeColor(type) { const s = TYPE_STYLE[type]; if (!s) return "#999"; return s.c.startsWith("--") ? css(s.c) : s.c; }
export function typeShape(type) { return (TYPE_STYLE[type] || {}).shape || "ellipse"; }

export function legend(types, counts) {
  return h("div", { class: "legend" }, ...types.map(t => h("span", null, h("span", { class: "sw", style: { background: typeColor(t) } }), t, counts && counts[t] != null ? h("span", { class: "muted" }, ` ${counts[t]}`) : null)));
}

/** Create a graph viewer in container. Returns a controller. */
export function graphViewer(container, { onSelect } = {}) {
  const el = h("div", { class: "cy" }); container.append(el);
  const text = css("--text"), muted = css("--muted"), border = css("--border-strong"), accent = css("--accent"), surface = css("--surface");
  const cy = cytoscape({
    container: el, minZoom: 0.05, maxZoom: 4,
    style: [
      { selector: "node", style: {
        "background-color": (n) => typeColor(n.data("type")), shape: (n) => typeShape(n.data("type")),
        label: "data(short)", color: text, "font-size": 9, "font-family": css("--font"), "text-valign": "bottom", "text-margin-y": 3,
        "text-wrap": "ellipsis", "text-max-width": "110px", "min-zoomed-font-size": 7,
        width: (n) => sizeFor(n), height: (n) => sizeFor(n), "border-width": 1.5, "border-color": surface, "text-background-color": surface, "text-background-opacity": 0.75, "text-background-padding": "1px", "text-background-shape": "round-rectangle" } },
      { selector: "edge", style: { width: 1, "line-color": border, "target-arrow-color": border, "target-arrow-shape": "triangle", "arrow-scale": 0.7, "curve-style": "straight", opacity: 0.8, label: "", "font-size": 7, color: muted } },
      { selector: "edge.labeled", style: { label: "data(type)", "text-rotation": "autorotate", "text-background-color": surface, "text-background-opacity": 0.8, "text-background-padding": "1px" } },
      { selector: ".dim", style: { opacity: 0.12, "text-opacity": 0 } },
      { selector: ".hit", style: { "border-color": accent, "border-width": 3, "z-index": 10 } },
      { selector: "node:selected", style: { "border-color": accent, "border-width": 3, "overlay-color": accent, "overlay-opacity": 0.12, "overlay-padding": 6 } },
      { selector: "edge.adj", style: { "line-color": accent, "target-arrow-color": accent, width: 2, opacity: 1 } },
      { selector: ".hidden", style: { display: "none" } },
    ],
  });
  function sizeFor(n) { const t = n.data("type"); const sz = n.data("raw")?.properties?.size; if (typeof sz === "number" && sz > 0 && t !== "Organization") return Math.max(12, Math.min(46, 8 + 2.4 * Math.sqrt(sz))); if (t === "Organization") return 34; if (["OrgUnit", "Role", "System", "Occupation"].includes(t)) return 24; if (["Task", "GWA", "IWA", "DWA"].includes(t)) return 12; return 18; }

  cy.on("tap", "node", (e) => { const n = e.target; cy.elements().removeClass("adj"); n.connectedEdges().addClass("adj"); onSelect && onSelect(n.data("raw"), n); });
  cy.on("tap", (e) => { if (e.target === cy) { cy.elements().removeClass("adj"); onSelect && onSelect(null); } });

  let layoutName = "cose";
  const api = {
    cy,
    setData(graph) {
      if (cy.destroyed()) return;
      cy.elements().remove();
      const ids = new Set(graph.nodes.map(n => n.id));
      cy.add(graph.nodes.map(n => ({ group: "nodes", data: { id: n.id, type: n.type, label: n.label, short: n.label.length > 28 ? n.label.slice(0, 26) + "…" : n.label, raw: n } })));
      cy.add(graph.edges.filter(e => ids.has(e.source) && ids.has(e.target)).map((e, i) => ({ group: "edges", data: { id: `e${i}`, source: e.source, target: e.target, type: e.type, raw: e } })));
      api.runLayout();
    },
    runLayout(name) {
      if (name) layoutName = name;
      if (cy.destroyed()) return;
      const visible = cy.elements(":visible");
      const n = visible.nodes().length;
      const opts = layoutName === "cose"
        ? { name: "cose", animate: false, nodeRepulsion: () => 12000, idealEdgeLength: () => 60, gravity: 0.6, numIter: n > 400 ? 400 : 1000, nodeDimensionsIncludeLabels: false, padding: 30, randomize: true }
        : layoutName === "breadthfirst"
          ? { name: "breadthfirst", directed: false, spacingFactor: n > 200 ? 0.8 : 1.1, padding: 30, roots: visible.nodes().filter(x => x.data("type") === "Organization") }
          : { name: "concentric", padding: 30, minNodeSpacing: 14, concentric: (node) => ({ Organization: 10, OrgUnit: 8, Role: 7, Person: 6, System: 6, Occupation: 5, Activity: 5, Capability: 4, Artifact: 4, DWA: 3, IWA: 2, GWA: 1, Task: 2 })[node.data("type")] ?? 3, levelWidth: () => 1 };
      visible.layout(opts).run();
      cy.fit(visible, 30);
    },
    setTypeVisibility(hiddenTypes) {
      if (cy.destroyed()) return;
      cy.batch(() => {
        cy.nodes().forEach(n => n.toggleClass("hidden", hiddenTypes.has(n.data("type"))));
        cy.edges().forEach(e => e.toggleClass("hidden", e.source().hasClass("hidden") || e.target().hasClass("hidden")));
      });
    },
    setEdgeLabels(on) { if (cy.destroyed()) return; cy.edges().toggleClass("labeled", on); },
    highlight(q) {
      if (cy.destroyed()) return null;
      const s = (q || "").trim().toLowerCase();
      cy.batch(() => {
        cy.elements().removeClass("dim hit");
        if (!s) return;
        const hits = cy.nodes().filter(n => n.data("label").toLowerCase().includes(s) || n.id().toLowerCase().includes(s));
        cy.elements().not(hits).not(hits.connectedEdges()).addClass("dim");
        hits.addClass("hit");
      });
      return s ? cy.nodes(".hit").length : null;
    },
    select(id) { const n = cy.getElementById(id); if (n.length) { cy.elements().unselect(); n.select(); cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.2) }, { duration: 250 }); n.connectedEdges().addClass("adj"); } },
    fit() { cy.fit(cy.elements(":visible"), 30); },
    neighbors(id) { const n = cy.getElementById(id); return n.length ? n.connectedEdges().map(e => ({ edge: e.data("raw"), other: (e.source().id() === id ? e.target() : e.source()).data("raw") })) : []; },
    destroy() { cy.destroy(); },
  };
  return api;
}
