/* Exploratory comparisons have no observed AI outcome; every number comes from matched simulations. */
import { h, badge, card, fmtNum, fmtMetric, emptyState } from "./ui.js";
import { chartCard } from "./chart.js";

const number = (value, unit) => value == null ? "–" : fmtMetric(value, unit);
export function explorationPanel(view, ctx) {
  const panel = h("div", { class: "exploration-panel", "data-scenario": view.id });
  panel.append(h("div", { class: "row", style: { margin: "14px 0 8px" } }, h("h3", null, view.title), badge("Exploratory AI scenario", "accent")),
    h("p", { class: "small", style: { maxWidth: "1000px", lineHeight: "1.6", color: "var(--text-2)" } }, view.description),
    h("div", { class: "row", style: { marginBottom: "12px" } }, h("a", { class: "btn primary", href: ctx.href(ctx.instanceId, "scenarios", view.id) }, ctx.readOnly ? "View saved AI assumptions →" : "Adjust AI assumptions and compare →")));

  const rows = [];
  for (const iv of view.interventions || []) {
    if (iv.type !== "ai_assist") continue;
    for (const [key, label] of [["coverage", "Share of eligible work using AI"], ["time_saved", "Task time saved before review"], ["review_overhead", "Human review effort"], ["rework_rate", "Assisted tasks needing correction"], ["rework_effort", "Effort to correct a task"]]) {
      rows.push(h("tr", null, h("td", null, label), h("td", { class: "v" }, `${fmtNum(100 * iv[key], { digits: 1 })}%`)));
    }
    const effort = 1 - iv.coverage * (iv.time_saved - iv.review_overhead - iv.rework_rate * iv.rework_effort);
    rows.push(h("tr", null, h("td", null, h("b", null, "Human effort across eligible tasks, including review and correction")), h("td", { class: "v" }, `${fmtNum(100 * effort, { digits: 1 })}% of current effort`)));
  }
  panel.append(card("Assumptions for this comparison", [h("p", { class: "muted small" }, view.assumption_basis),
    h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("tbody", null, ...rows))),
    h("p", { class: "muted small" }, "Time saved, review effort, and correction effort are measured relative to the time a task takes without AI. Coverage and correction rate are shares of tasks.")]));

  if (view.state !== "ready") {
    panel.append(emptyState(view.state === "stale" ? "Settings or inputs changed. Run a new comparison to see the impact." : "No saved AI comparison yet.",
      "Open the AI assumptions and select Compare with current policy."));
  } else {
    panel.append(h("h4", { style: { marginTop: "18px" } }, "Simulation predictions with and without AI"),
      h("p", { class: "muted small" }, `${view.runs} matched comparisons use the same seeds, time periods, and reference conditions. There is no measured AI outcome in this dataset.`));
    const effort = view.metrics.find(m => m.id === "human_hours");
    if (effort) panel.append(chartCard({ id: `ai-effort-${view.id}`, type: "bar", title: "Modeled human effort, review and correction included", x: ["Current policy", view.title],
      x_label: "", y_label: "human hours", series: [{ name: "Human effort", y: [effort.baseline, effort.alternative] }],
      note: "Effort estimates describe work performed over the simulated period." + (view.metrics.some(m => m.id === "completion") ? " Work volumes can also change as queues respond." : " Released time is capacity for other work.") }));
    panel.append(card(null, h("div", { class: "table-wrap" }, h("table", { class: "table metric-table ai-comparison" },
      h("thead", null, h("tr", null, h("th", null, "Outcome"), h("th", { class: "src" }, "Current policy · simulation prediction"),
        h("th", { class: "src" }, `${view.title} · simulation prediction`), h("th", { class: "src" }, "AI − current policy"))),
      h("tbody", null, ...view.metrics.map(m => h("tr", null, h("td", null, m.label),
        h("td", { class: "v" }, number(m.baseline, m.unit)), h("td", { class: "v" }, number(m.alternative, m.unit)),
        h("td", { class: "v" }, `${m.delta > 0 ? "+" : ""}${number(m.delta, m.unit === "%" ? "pp" : m.unit)}`))))))),
      h("p", { class: "muted small" }, `Included in the AI effort estimate: ${number(view.review_hours, "hours")} of review and ${number(view.rework_hours, "hours")} of correction.`),
      h("details", { class: "disclosure" }, h("summary", null, "Variation across matched simulations"),
        h("div", { class: "disclosure-body" }, h("p", { class: "muted small" }, "These ranges contain the middle 90% of paired differences at the selected assumptions. They do not measure uncertainty about how effective AI would actually be."),
          ...view.metrics.map(m => h("p", { class: "small" }, `${m.label}: ${number(m.delta_range[0], m.unit === "%" ? "pp" : m.unit)} to ${number(m.delta_range[1], m.unit === "%" ? "pp" : m.unit)}`)))));
  }
  panel.append(h("p", { class: "muted small", style: { lineHeight: "1.6" } }, view.note),
    h("details", { class: "disclosure" }, h("summary", null, "Research context for the assumptions"), h("div", { class: "disclosure-body" },
      ...(view.sources || []).map(s => h("p", { class: "small" }, h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title), " — ", s.note)))));
  return panel;
}
