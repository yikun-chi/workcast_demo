import { h, badge, emptyState, fmtNum } from "../components/ui.js";

export async function render(root, { instances, href }) {
  document.title = "Emergent Science - WORKCAST simulation";
  root.append(h("div", { class: "hero" },
    h("div", { class: "pill" }, h("span", { class: "dot" }), "Workforce, process, market and adoption simulation"),
    h("h1", null, "Rehearse the decision ", h("em", null, "before"), " you make it."),
    h("p", null, "Each instance starts with observed data and a change or prediction date. Compare actual outcomes, other predictions and simulation predictions, then explore alternative actions.")));
  if (!instances.length) { root.append(emptyState("No instances found.", "Add a folder under instances/<id>/ with an instance.yaml.")); return; }
  const grid = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(460px, 1fr))" } });
  for (const i of instances) {
    const open = () => { location.hash = href(i.id, i.has_evaluation ? "results" : "overview"); };
    const hero = i.hero || null;
    const alternatives = i.alternatives || (i.alternative ? [i.alternative] : []);
    const line = (label, text) => text ? h("div", { class: "small", style: { lineHeight: "1.5" } }, h("b", null, label, ". "), text) : null;
    grid.append(h("div", { class: "card instance-card clickable", onClick: (e) => { if (e.target.closest("button, a")) return; open(); } },
      h("div", { class: "row", style: { justifyContent: "space-between" } }, h("div", { class: "row" }, badge(i.world_type === "workforce" ? "people decision" : i.world_type === "process" ? "process decision" : i.world_type === "market" ? "market decision" : i.world_type === "adoption" ? "adoption decision" : i.world_type || "instance", "accent"), h("span", { class: "muted small" }, i.company || "")), h("span", { class: "mono muted small" }, i.id)),
      h("h2", { class: "problem", style: { fontSize: "19px" } }, i.problem || i.title),
      h("div", { class: "stack", style: { gap: "6px", color: "var(--text-2)" } },
        line("The situation", i.situation),
        line("The data", i.data_used),
        ...alternatives.map((alt, index) => line(`Alternative ${index + 1}`, `${alt.short_title || alt.title}: ${alt.summary || firstSentence(alt.description)}`))),
      hero ? h("div", { class: "stack", style: { gap: "6px", marginTop: "8px" } },
        h("div", { class: "muted small", style: { textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 } }, hero.kicker),
        h("div", { class: "hero-stats", style: { margin: "4px 0" } }, ...(hero.stats || []).filter(s => s.value !== null && s.value !== undefined).slice(0, 4).map(s => h("div", null, h("div", { class: "v", style: { fontSize: "24px" } }, fmtStat(s)), h("div", { class: "l" }, s.label)))),
        hero.alternative?.text ? h("div", { class: "small", style: { borderLeft: "3px solid var(--s2)", paddingLeft: "8px" } }, h("b", null, hero.alternative.kicker, ". "), hero.alternative.text) : null) : null,
      h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "4px" } }, h("button", { class: "btn primary", onClick: open }, i.has_evaluation ? "See the results →" : "Open instance →"))));
  }
  root.append(grid);
}
function firstSentence(t) { const s = String(t || "").trim().replace(/\s+/g, " "); const m = s.match(/^(.+?[.!?])(\s|$)/); return m ? m[1] : s; }
function fmtStat(s) { if (typeof s.value === "number") return `${s.value > 0 && s.unit === "pp" ? "+" : ""}${fmtNum(s.value, Math.abs(s.value) < 10 ? { digits: 2 } : { digits: 1 })}${s.unit ? " " + s.unit : ""}`; return String(s.value); }
