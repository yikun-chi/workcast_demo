import { h, badge, emptyState, fmtNum } from "../components/ui.js";

export async function render(root, { instances, href }) {
  document.title = "Emergent Science - WORKCAST simulation";
  root.append(h("div", { class: "hero" },
    h("div", { class: "pill" }, h("span", { class: "dot" }), "Workforce and process simulation"),
    h("h1", null, "Rehearse the decision ", h("em", null, "before"), " you make it."),
    h("p", null, "Each instance is a real company rebuilt as a simulation: its people as digital twins, its process on an hourly clock. We simulate what happened and put it next to what really happened, then explore the alternative the company did not try.")));
  if (!instances.length) { root.append(emptyState("No instances found.", "Add a folder under instances/<id>/ with an instance.yaml.")); return; }
  const grid = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(460px, 1fr))" } });
  for (const i of instances) {
    const open = () => { location.hash = href(i.id, "results"); };
    const hero = i.hero || null;
    const alt = i.alternative || null;
    const line = (label, text) => text ? h("div", { class: "small", style: { lineHeight: "1.5" } }, h("b", null, label, ". "), text) : null;
    grid.append(h("div", { class: "card instance-card clickable", onClick: (e) => { if (e.target.closest("button, a")) return; open(); } },
      h("div", { class: "row", style: { justifyContent: "space-between" } }, h("div", { class: "row" }, badge(i.world_type === "workforce" ? "people decision" : i.world_type === "process" ? "process decision" : i.world_type || "instance", "accent"), h("span", { class: "muted small" }, i.company || "")), h("span", { class: "mono muted small" }, i.id)),
      h("h2", { class: "problem", style: { fontSize: "19px" } }, i.problem || i.title),
      h("div", { class: "stack", style: { gap: "6px", color: "var(--text-2)" } },
        line("The situation", i.situation),
        line("The data", i.data_used),
        line("The alternative explored", alt ? `${alt.short_title || alt.title}: ${alt.summary || firstSentence(alt.description)}` : null)),
      hero ? h("div", { class: "stack", style: { gap: "6px", marginTop: "8px" } },
        h("div", { class: "muted small", style: { textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 } }, hero.kicker),
        h("div", { class: "hero-stats", style: { margin: "4px 0" } }, ...(hero.stats || []).filter(s => s.value !== null && s.value !== undefined).slice(0, 4).map(s => h("div", null, h("div", { class: "v", style: { fontSize: "24px" } }, fmtStat(s)), h("div", { class: "l" }, s.label)))),
        hero.alternative?.text ? h("div", { class: "small", style: { borderLeft: "3px solid var(--s2)", paddingLeft: "8px" } }, h("b", null, hero.alternative.kicker, ". "), hero.alternative.text) : null) : null,
      h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "4px" } }, h("button", { class: "btn primary", onClick: open }, "See the results →"))));
  }
  root.append(grid);
}
function firstSentence(t) { const s = String(t || "").trim().replace(/\s+/g, " "); const m = s.match(/^(.+?[.!?])(\s|$)/); return m ? m[1] : s; }
function fmtStat(s) { if (typeof s.value === "number") return `${s.value > 0 && s.unit === "pp" ? "+" : ""}${fmtNum(s.value, Math.abs(s.value) < 10 ? { digits: 2 } : { digits: 1 })}${s.unit ? " " + s.unit : ""}`; return String(s.value); }
