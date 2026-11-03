import { assetUrl } from "../api.js";
/* Results, in two parts. Part 1: actual outcome vs simulated. Before the change (actual only), the change
   itself, after the change (actual and the simulation's prediction), then how closely the simulation tracks reality.
   Part 2: the alternative action and its impact, against the simulation of what actually happened.
   Reads /api/instances/{id}/results (the world module's results_view). */
import { h, replace, badge, card, errorState, loading, emptyState, fmtMetric, fmtNum, fmtDate, segmented } from "../components/ui.js";
import { explorationPanel } from "../components/exploration.js";
import { chartCard, sweepCharts } from "../components/chart.js";
import { renderMarkdown } from "../components/markdown.js";

const SOURCE_COLOR = { actual: "#8b8f98", baseline: "--s1", alternative: "--s2" };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const colorOf = (id) => { const c = SOURCE_COLOR[id] || "--s3"; return c.startsWith("--") ? css(c) : c; };
const fmtV = (v, unit) => { if (v === null || v === undefined) return "–"; if (unit === "share") return fmtNum(v, { pct: true }); if (unit) return fmtMetric(v, unit); return fmtNum(v, Math.abs(v) < 10 ? { digits: 3 } : {}); };
const fmtError = (v, unit) => fmtV(unit === "share" ? v * 100 : v, unit === "%" || unit === "share" ? "pp" : unit);

export async function render(root, ctx) {
  const { api, instanceId, instance, href } = ctx;
  root.append(h("div", { class: "page-head" }, h("div", null, h("div", { class: "muted small" }, instance?.company || ""), h("h1", null, instance?.problem || "Results"))));
  const body = h("div", null, loading("Loading results")); root.append(body);
  let d;
  try { d = await api.results(instanceId); } catch (e) { replace(body, errorState(e, instanceId, "Results")); return; }
  replace(body);
  const src = Object.fromEntries(d.sources.map(s => [s.id, s]));
  const alt = d.scenarios?.alternative;
  const hero = d.hero || {};
  const story = d.story;
  const stat = (s) => h("div", null, h("div", { class: "v" }, typeof s.value === "number" ? `${s.value > 0 && s.unit === "pp" ? "+" : ""}${fmtNum(s.value, Math.abs(s.value) < 10 ? { digits: 2 } : { digits: 1 })}${s.unit ? " " + s.unit : ""}` : String(s.value ?? "–")), h("div", { class: "l" }, s.label));
  const bigV = (v, unit) => v === null || v === undefined ? h("span", { class: "v", style: { fontSize: "28px" } }, "–") : h("span", { class: "v", style: { fontSize: "28px" } }, fmtV(v, unit));
  const chartFor = (id, sources) => { const c = (d.charts || []).find(x => x.id === id); if (!c) return null; const series = c.series.filter(s => sources.includes(s.source)).map(s => ({ ...s, ...(sources.includes("alternative") && s.paired_y?.length ? { y: s.paired_y, ...(s.paired_band ? { band: s.paired_band } : {}) } : {}), color: colorOf(s.source), outlined: s.source === "actual" && c.type === "bar" })); return series.length ? { ...c, series } : null; };
  const legend = (ids) => h("div", { class: "row small", style: { gap: "14px" } }, ...ids.map(id => h("span", { class: "row", style: { gap: "6px" } }, h("span", { class: "sw", style: { display: "inline-block", width: "10px", height: "10px", borderRadius: "3px", background: colorOf(id) } }), h("b", null, src[id]?.short || id), h("span", { class: "muted" }, `· ${src[id]?.kind_label || ""}`))));

  function metricsTable(ids, opts = {}) {
    const rows = d.metrics.filter(m => ids.some(id => m.values[id] !== null && m.values[id] !== undefined));
    if (!rows.length) return emptyState("No metrics.");
    return card(null, h("div", { class: "table-wrap" }, h("table", { class: "table metric-table" },
      h("thead", null, h("tr", null, h("th", null, "Metric"), ...ids.map(id => h("th", { class: "src" }, h("span", { class: "sw", style: { display: "inline-block", width: "9px", height: "9px", borderRadius: "2px", background: colorOf(id), marginRight: "6px" } }), src[id]?.short || id, h("div", { class: "muted small", style: { fontWeight: 400 } }, src[id]?.kind_label || ""))), opts.delta ? h("th", { class: "src" }, opts.delta) : null)),
      h("tbody", null, ...rows.map(m => {
        const vals = ids.map(id => opts.highlight && id === "baseline" && typeof m.paired_baseline === "number" ? m.paired_baseline : m.values[id]);
        const nums = vals.filter(v => typeof v === "number");
        const best = opts.highlight && nums.length > 1 ? (m.better === "lower" ? Math.min(...nums) : Math.max(...nums)) : null;
        const delta = opts.delta && typeof vals[0] === "number" && typeof vals[1] === "number" ? vals[1] - vals[0] : null;
        const good = delta === null ? null : (m.better === "lower" ? delta < 0 : delta > 0);
        return h("tr", null, h("td", null, h("div", null, m.label, " ", h("span", { class: "muted small" }, m.better === "lower" ? "↓ lower is better" : "↑ higher is better")), m.note ? h("div", { class: "muted small" }, m.note) : null),
          ...ids.map((id, i) => { const v = vals[i]; const iv = opts.highlight && id === "baseline" && "paired_baseline" in m ? null : (m.intervals || {})[id]; return h("td", { class: `v ${typeof v === "number" && v === best ? "best" : ""}` }, fmtV(v, m.unit), iv ? h("span", { class: "iv" }, `${fmtV(iv[0], m.unit)} – ${fmtV(iv[1], m.unit)}`) : null); }),
          opts.delta ? h("td", { class: "v" }, delta === null ? "–" : badge(`${delta > 0 ? "+" : "−"}${fmtV(Math.abs(delta), m.unit)}`, opts.neutral || Math.abs(delta) < 1e-9 ? "" : good ? "good" : "warn")) : null);
      })))),
      h("div", { class: "muted small", style: { marginTop: "6px" } }, opts.foot || ""));
  }

  // ---------- Part 1: actual outcome vs simulated
  const p1 = h("section", { class: "section" });
  p1.append(h("div", { class: "row", style: { gap: "10px", alignItems: "baseline", marginBottom: "4px" } }, h("span", { class: "part-no" }, "1"), h("h2", null, "Before the change, the change, and the outcomes")),
    d.design ? h("p", { class: "small", style: { maxWidth: "980px", color: "var(--text-2)", lineHeight: "1.5" } }, d.design) : null);
  if (story) {
    const m0 = story.metrics[0];
    const colL = story.columns || { before_actual: "Actual outcome", before_sim: "Simulation prediction", after_actual: "Actual outcome", after_sim: "Simulation prediction" };
    const pair = (a, b, la, lb, unit) => h("div", { class: "hero-stats", style: { gridTemplateColumns: "1fr 1fr", margin: "8px 0 0" } }, h("div", null, bigV(a, unit), h("div", { class: "l" }, la)), h("div", null, bigV(b, unit), h("div", { class: "l" }, lb)));
    p1.append(h("div", { class: "story-flow" },
      h("div", { class: "card hero-card" }, h("div", { class: "kicker" }, story.before.label), h("div", { class: "muted small" }, story.before.sublabel || ""), story.before.stats ? h("div", { class: "hero-stats" }, ...story.before.stats.map(stat)) : h("div", null, h("div", { class: "small", style: { marginTop: "8px", fontWeight: 600 } }, m0.label), h("div", { class: "hero-stats", style: { gridTemplateColumns: "1fr", margin: "8px 0 0" } }, h("div", null, bigV(m0.before_actual, m0.unit), h("div", { class: "l" }, "Actual outcome"))))),
      h("div", { class: "card", style: { borderColor: "var(--accent)" } }, h("div", { class: "kicker", style: { color: "var(--accent)" } }, "The change"), h("div", { style: { fontWeight: 650, fontSize: "15px", margin: "4px 0" } }, story.change.label), h("div", { class: "hero-stats", style: { gridTemplateColumns: "1fr", gap: "6px", margin: "6px 0" } }, ...(story.change.stats || []).map(x => h("div", null, h("div", { class: "v", style: { fontSize: "22px" } }, String(x.value)), h("div", { class: "l" }, x.label)))), h("div", { class: "muted small" }, story.change.description || "")),
      h("div", { class: "card hero-card" }, h("div", { class: "kicker" }, story.after.label), h("div", { class: "muted small" }, story.after.sublabel || ""), h("div", { class: "small", style: { marginTop: "8px", fontWeight: 600 } }, m0.label), pair(m0.after_actual, m0.after_sim, "Actual outcome", "Simulation prediction", m0.unit))));
    p1.append(h("h4", null, "Outcomes before and after the change"), card(null, [h("div", { class: "table-wrap" }, h("table", { class: "table metric-table story-table" },
      h("thead", null, h("tr", null, h("th", { rowspan: 2 }, "Metric"), h("th", { class: "src grp" }, story.before.label), h("th", { colspan: 2, class: "src grp after" }, story.after.label), h("th", { rowspan: 2, class: "src" }, "prediction − actual, after")),
        h("tr", null, h("th", { class: "src" }, colL.before_actual), h("th", { class: "src" }, colL.after_actual), h("th", { class: "src sim" }, colL.after_sim))),
      h("tbody", null, ...story.metrics.map(m => { const cell = (v, key) => { const iv = (m.intervals || {})[key]; return h("td", { class: `v ${key.endsWith("_sim") ? "simc" : ""}` }, fmtV(v, m.unit), iv ? h("span", { class: "iv" }, `${fmtV(iv[0], m.unit)} – ${fmtV(iv[1], m.unit)}`) : null); };
        const err = typeof m.after_sim === "number" && typeof m.after_actual === "number" && m.better ? m.after_sim - m.after_actual : null;
        return h("tr", null, h("td", null, h("div", null, m.label, " ", m.better ? h("span", { class: "muted small" }, m.better === "lower" ? "↓ lower is better" : "↑ higher is better") : null), m.note ? h("div", { class: "muted small" }, m.note) : null),
          cell(m.before_actual, "before_actual"), cell(m.after_actual, "after_actual"), cell(m.after_sim, "after_sim"),
          h("td", { class: "v" }, err === null ? "–" : badge(`${err > 0 ? "+" : "−"}${fmtError(Math.abs(err), m.unit)}`, ""))); })))),
      h("div", { class: "muted small", style: { marginTop: "6px" } }, "The shaded column shows the simulation prediction. Small grey ranges contain the middle 90% of simulation results. A dash means the source does not provide that observation.")]));
    if (story.comparator_explanation) {
      const e = story.comparator_explanation;
      p1.append(h("h4", { style: { marginTop: "14px" } }, "How the other predictions are calculated"),
        card(null, h("div", null, ...e.paragraphs.map(p => h("p", { class: "small" }, p)),
          h("p", { style: { fontWeight: 600 } }, e.formula),
          h("div", { class: "small" }, ...e.sources.map((s, i) => h("span", null, i ? " · " : "Sources: ", h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label)))))));
    }
    if ((story.baselines || []).length) {
      const eff = story.baseline_basis === "effect";
      const rows = story.metrics.filter(m => m.better && typeof m.after_actual === "number" && typeof m.after_sim === "number" && story.baselines.some(b => typeof b.values?.[m.id] === "number") && (!eff || typeof (m.reference_actual ?? m.before_actual) === "number")).map(m => ({
        label: eff ? m.effect_label || `Impact on ${m.label.toLowerCase()}` : m.label,
        note: eff ? `${fmtV(m.after_actual, m.unit)} hybrid − ${fmtV(m.reference_actual ?? m.before_actual, m.unit)} office-only, during the same period` : "",
        kind: eff ? "impact" : "outcome",
        unit: eff && m.unit === "%" ? "pp" : m.unit,
        actual: eff ? m.after_actual - (m.reference_actual ?? m.before_actual) : m.after_actual,
        predictions: [eff ? (typeof m.engine_effect === "number" ? m.engine_effect : m.after_sim - (typeof m.before_sim === "number" ? m.before_sim : m.before_actual)) : m.after_sim,
          ...story.baselines.map(b => typeof b.values?.[m.id] === "number" ? b.values[m.id] : null)]
      }));
      if (story.level_comparison) {
        const c = story.level_comparison;
        rows.unshift({ label: `${c.label} — hybrid group`, note: "Share of employees who left during the six months after the change.", kind: "outcome", unit: c.unit, actual: c.actual,
          predictions: [c.simulated, ...story.baselines.map(b => c.predictions.find(p => p.label === b.label)?.value ?? null)] });
      }
      const errCell = (pred, a, unit, best) => pred === null ? h("td", { class: "v" }, "–") : h("td", { class: `v ${best ? "best" : ""}` }, fmtV(pred, unit), h("span", { class: "iv" }, `error ${fmtError(Math.abs(pred - a), unit)}`));
      p1.append(h("div", { class: "comparison-section" }, h("h4", { style: { marginTop: "14px" } }, "Actual outcomes and predictions"),
        eff ? h("p", { class: "small muted" }, "The attrition rate shows how many people left. The policy impact is the difference between the hybrid and office-only groups during the same six months. Both are compared with predictions below.") : null,
        card(null, [h("div", { class: "table-wrap" }, h("table", { class: "table metric-table prediction-comparison" },
          h("thead", null, h("tr", null, h("th", null, "Measure"), h("th", { class: "src" }, "Actual outcome"), h("th", { class: "src sim" }, "Simulation prediction"), ...story.baselines.map(b => h("th", { class: "src", title: b.label }, b.label)))),
          h("tbody", null, ...rows.map(m => { const errs = m.predictions.map(v => v === null ? Infinity : Math.abs(v - m.actual)); const best = Math.min(...errs);
            return h("tr", { "data-comparison": m.kind }, h("td", null, m.label, m.note ? h("div", { class: "muted small" }, m.note) : null), h("td", { class: "v" }, fmtV(m.actual, m.unit)), ...m.predictions.map((v, i) => errCell(v, m.actual, m.unit, errs[i] === best))); })))),
          h("div", { class: "muted small", style: { marginTop: "6px" } }, `The closest prediction in each row is highlighted.${eff ? " pp means percentage points. The earlier attrition rate is historical context; policy impact uses the simultaneous office-only group." : ""}`),
          eff && d.effects?.length ? h("details", { style: { marginTop: "12px" } }, h("summary", { class: "small muted", style: { cursor: "pointer" } }, "Uncertainty ranges and employee groups"),
            h("div", { class: "grid", style: { marginTop: "10px", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" } }, ...d.effects.map(metricCard))) : null])));
    }
    if (story.business_validation?.length) {
      p1.append(h("h4", { style: { marginTop: "14px" } }, "Prediction accuracy across periods"),
        card(null, [h("div", { class: "table-wrap" }, h("table", { class: "table metric-table" },
          h("thead", null, h("tr", null, h("th", null, "Outcome"), h("th", { class: "src" }, "Simulation error"),
            h("th", { class: "src" }, "Best non-simulation error"), h("th", { class: "src" }, "Error reduction"))),
          h("tbody", null, ...story.business_validation.map(v => {
            const m = story.metrics.find(m => m.id === v.id) || {};
            const baseline = story.baselines.find(b => b.id === v.best_baseline);
            return h("tr", null, h("td", null, m.label || v.id),
              h("td", { class: `v ${v.beats_best_baseline ? "best" : ""}` }, fmtV(v.simulation_mae, m.unit === "%" ? "pp" : m.unit)),
              h("td", { class: `v ${!v.beats_best_baseline ? "best" : ""}` }, fmtV(v.baseline_mae[v.best_baseline], m.unit === "%" ? "pp" : m.unit), h("span", { class: "iv" }, baseline?.label || v.best_baseline)),
              h("td", { class: "v" }, v.error_reduction_pct == null ? "–" : `${fmtNum(v.error_reduction_pct, { digits: 1 })}%`));
          })))), h("div", { class: "muted small", style: { marginTop: "6px" } },
          "Mean absolute error across the prediction windows. Lower is better. The comparison uses the most accurate of the three non-simulation methods for each outcome.")]));
    }
    const fid = (story.fidelity || []).filter(x => x.value !== null && x.value !== undefined);
    const heroChart = chartFor(story.chart, ["actual", "baseline"]);
    p1.append(h("div", { class: "grid-2", style: { margin: "12px 0", alignItems: "stretch" } },
      h("div", { class: "card hero-card" }, h("div", { class: "kicker" }, "How close is the simulation prediction?"), h("div", { class: "hero-stats" }, ...fid.map(stat)), h("div", { class: "claim" }, hero.claim || "")),
      heroChart ? chartCard(heroChart, { tall: true }) : null));
  } else {
    const heroChart = chartFor(hero.chart, ["actual", "baseline"]);
    p1.append(legend(["actual", "baseline"]), h("div", { class: "grid-2", style: { margin: "12px 0", alignItems: "stretch" } },
      h("div", { class: "card hero-card" }, h("div", { class: "kicker" }, hero.kicker || ""), h("div", { class: "hero-stats" }, ...(hero.stats || []).filter(s => s.value !== null && s.value !== undefined).map(stat)), h("div", { class: "claim" }, hero.claim || "")),
      heroChart ? chartCard(heroChart, { tall: true }) : null));
    p1.append(h("h4", null, "Key metrics: simulated against what actually happened"), metricsTable(["actual", "baseline"], { delta: "simulated − actual", neutral: true, foot: "Small grey ranges are the 90% interval across seeds." }));
  }
  if ((d.effects || []).length && !(story?.baseline_basis === "effect" && story.baselines?.length)) {
    p1.append(h("h4", { style: { marginTop: "14px" } }, "Policy impact: simulation prediction vs actual outcome"), h("div", { class: "muted small", style: { marginBottom: "8px" } }, "Each number compares employees offered hybrid work with office-only employees during the same six months. Negative attrition means fewer people left. One percentage point is one employee in every hundred."),
      h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" } }, ...d.effects.map(metricCard)));
  }
  const mainChart = story ? story.chart : hero.chart;
  const otherP1 = (d.charts || []).filter(c => c.id !== mainChart).map(c => chartFor(c.id, ["actual", "baseline"])).filter(c => c && c.series.some(s => s.source === "actual"));
  if (otherP1.length) p1.append(h("h4", { style: { marginTop: "14px" } }, "More comparisons, after the change"), h("div", { class: "grid-2" }, ...otherP1.map(c => chartCard(c))));
  if (story) p1.append(h("details", { style: { marginTop: "12px" } }, h("summary", { class: "small muted", style: { cursor: "pointer" } }, "All metrics after the change: simulated against actual"), h("div", { style: { marginTop: "8px" } }, metricsTable(["actual", "baseline"], { delta: "simulated − actual", neutral: true, foot: "Small grey ranges are 5th-95th percentiles across runs." }))));
  body.append(p1);

  // ---------- Part 2: the alternative action and its impact
  if (alt) {
    const section = h("section", { class: "section alternative-exploration", style: { marginTop: "26px" } });
    section.append(h("div", { class: "row", style: { gap: "10px", alignItems: "baseline", marginBottom: "10px" } }, h("span", { class: "part-no alt" }, "2"), h("h2", null, "Explore alternative actions")));
    const p2 = h("div", { "data-scenario": alt.id });
    const ha = hero.alternative || {};
    p2.append(h("h3", { style: { marginTop: "14px" } }, alt.short_title || alt.title),
      h("p", { class: "small", style: { maxWidth: "980px", color: "var(--text-2)", lineHeight: "1.5" } }, alt.description || "", " ", h("span", { class: "muted" }, `Both predictions use the same simulation; only the alternative setting changes (${src.alternative?.runs || "?"} runs).`)),
      legend(["baseline", "alternative"]));
    const altChart = chartFor(ha.chart || mainChart, ["baseline", "alternative"]);
    p2.append(h("div", { class: "grid-2", style: { margin: "12px 0", alignItems: "stretch" } },
      h("div", { class: "card hero-card alt" }, h("div", { class: "kicker" }, ha.kicker || `Alternative: ${alt.short_title}`), h("div", { class: "hero-stats" }, ...(ha.stats || []).filter(s => s.value !== null && s.value !== undefined).map(stat)), h("div", { class: "claim" }, ha.text || ""),
        h("div", { class: "row", style: { marginTop: "10px" } }, h("a", { class: "btn sm", href: href(instanceId, "scenarios", alt.id) }, ctx.readOnly ? "View saved alternative assumptions →" : "Change the alternative and re-run →"))),
      altChart ? chartCard(altChart, { tall: true }) : null));
    p2.append(h("h4", null, "Key metrics: the alternative against the simulation of what actually happened"), metricsTable(["baseline", "alternative"], { highlight: true, delta: "alternative − as happened", foot: "Both columns use matching seeds and time windows. The better simulated value is highlighted; the last column is the alternative's impact." }));
    const otherP2 = (d.charts || []).filter(c => c.id !== (ha.chart || mainChart)).map(c => chartFor(c.id, ["baseline", "alternative"])).filter(c => c && c.series.some(s => s.source === "alternative"));
    if (otherP2.length) p2.append(h("h4", { style: { marginTop: "14px" } }, "More comparisons"), h("div", { class: "grid-2" }, ...otherP2.map(c => chartCard(c))));
    const panels = { [alt.id]: p2 };
    const choices = [{ id: alt.id, label: alt.short_title || alt.title }];
    for (const view of d.explorations || []) {
      panels[view.id] = explorationPanel(view, ctx);
      choices.push({ id: view.id, label: view.title });
    }
    const selected = panels[ctx.params?.[0]] ? ctx.params[0] : alt.id;
    const select = (id) => {
      for (const [key, panel] of Object.entries(panels)) panel.hidden = key !== id;
      setTimeout(() => { window.dispatchEvent(new Event("resize")); sweepCharts(); }, 10);
    };
    if (choices.length > 1) section.append(segmented(choices, selected, select));
    section.append(...Object.values(panels));
    body.append(section);
    select(selected);
  }
  setTimeout(sweepCharts, 10);

  // ---------- narrative, detailed views, sources
  const n = d.narrative || {};
  if ((n.takeaways || []).length || (n.sections || []).length) {
    body.append(h("section", { class: "section", style: { marginTop: "26px" } }, h("h4", null, "Summary"), h("article", { class: "report", style: { maxWidth: "none" } },
      (n.takeaways || []).length ? h("ol", { class: "takeaways" }, ...n.takeaways.map((t, i) => h("li", null, h("span", { class: "n" }, String(i + 1).padStart(2, "0")), h("span", null, t)))) : null,
      (n.sections || []).length ? h("details", { style: { marginTop: "10px" } }, h("summary", { class: "small muted", style: { cursor: "pointer" } }, `Full narrative (${n.sections.length} sections)${n.generated ? ` · generated ${fmtDate(n.generated)}` : ""}`),
        ...n.sections.map(s => h("section", { class: "report-section" }, h("h2", null, s.heading || ""), renderMarkdown(s.body || "")))) : null)));
  }
  const plugins = d.plugins || [];
  if (plugins.length) body.append(h("section", { class: "section" }, h("h4", null, "Detailed views"), ...plugins.map(p => h("details", { style: { marginBottom: "10px" } }, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, p.title), h("iframe", { class: "plugin-frame", src: ctx.readOnly ? assetUrl(p.url) : p.url, title: p.title, loading: "lazy", style: { height: "720px", width: "100%", border: "1px solid var(--border)", borderRadius: "10px", background: "var(--surface)" } })))));
  body.append(h("div", { class: "muted small", style: { marginTop: "12px" } }, ...d.sources.map(s => h("div", null, h("b", null, s.short), ` (${s.kind_label}): `, s.note))));
}

export function metricCard(m) {
  const better = m.better || "higher";
  const diff = typeof m.simulated === "number" && typeof m.actual === "number" ? m.simulated - m.actual : null;
  const f = (v) => m.unit ? fmtMetric(v, m.unit) : fmtNum(v, Math.abs(v) < 10 ? { digits: 3 } : {});
  const big = (v) => v === null || v === undefined ? "–" : h("span", { style: { whiteSpace: "nowrap" } }, m.unit ? fmtNum(v) : fmtNum(v, Math.abs(v) < 10 ? { digits: 3 } : {}), m.unit ? h("span", { class: "muted", style: { fontSize: "12px", fontWeight: 500, marginLeft: "3px" } }, m.unit) : null);
  return h("div", { class: "card metric-card" },
    h("div", { class: "mc-head" }, h("div", { class: "card-title", style: { marginBottom: 0 } }, m.label || m.id), badge(h("span", { class: better === "lower" ? "arrow-down" : "arrow-up" }), ` ${better} is better`, "")),
    h("div", { class: "vals" },
      h("div", { class: "v sim" }, h("div", { class: "l" }, "Simulation prediction"), h("div", { class: "n" }, big(m.simulated))),
      h("div", { class: "v" }, h("div", { class: "l" }, "Actual impact"), h("div", { class: "n" }, big(m.actual))),
      h("div", { class: "v" }, h("div", { class: "l" }, "No change"), h("div", { class: "n" }, big(m.baseline)))),
    h("div", { class: "row", style: { justifyContent: "space-between", marginTop: "8px" } },
      h("div", { class: "interval", style: { margin: 0 } }, Array.isArray(m.interval) && m.interval.length === 2 ? `Simulation range (90%): ${f(m.interval[0])} – ${f(m.interval[1])}` : "no interval", Array.isArray(m.trial_ci95) ? h("span", { class: "muted", style: { marginLeft: "8px" } }, `· Actual estimate range (95%): ${f(m.trial_ci95[0])} – ${f(m.trial_ci95[1])}`) : null),
      diff !== null ? badge(`${diff >= 0 ? "+" : "−"}${fmtMetric(Math.abs(diff), m.unit)} vs actual outcome${m.within_trial_ci95 === true ? " · within actual estimate range" : m.within_trial_ci95 === false ? " · outside actual estimate range" : ""}`, m.within_trial_ci95 === false ? "warn" : "good") : null));
}
