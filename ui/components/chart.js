/* Chart renderer for the contract chart object, on Chart.js 4.4.x (global `Chart` from cdnjs).
   {id, type: bar|hbar|line|scatter, title, x_label, y_label, x: [...], series: [{name, y: [...]}], note, x_log?, y_log?} */
import { h } from "./ui.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export function palette() { return [1, 2, 3, 4, 5, 6, 7, 8].map(i => css(`--s${i}`)); }
function withAlpha(hex, a) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return hex;
  return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${a})`;
}
function theme() {
  return { text: css("--text-2"), muted: css("--muted"), grid: css("--grid-line"), surface: css("--surface"), font: css("--font") };
}

const live = new Set();
/** Render a chart object into a container element; returns the Chart instance. */
export function renderChart(container, chart, opts = {}) {
  const t = theme(); const pal = palette();
  const area = h("div", { class: `chart-area ${opts.tall ? "tall" : ""}` }, h("canvas", { role: "img", "aria-label": chart.title || chart.id || "chart" }));
  container.append(area);
  const canvas = area.querySelector("canvas");
  const type = chart.type || "bar";
  const isH = type === "hbar";
  const labels = (chart.x || []).map(String);
  const stacked = !!opts.stacked;
  const n = (chart.series || []).length;

  const datasets = (chart.series || []).flatMap((s, i) => {
    const color = s.color || pal[i % pal.length];
    if (type === "line" && s.point) return [{ label: s.name, data: s.y, borderColor: color, backgroundColor: color, pointRadius: 7, pointHoverRadius: 9, pointStyle: "rectRot", pointBorderWidth: 2, showLine: false }];
    if (type === "line" && Array.isArray(s.band) && s.band.length === 2) {
      return [
        { label: `${s.name} (band)`, data: s.band[1], borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: withAlpha(color, 0.16), tension: 0.25, spanGaps: true },
        { label: `${s.name} (band)`, data: s.band[0], borderWidth: 0, pointRadius: 0, fill: false, tension: 0.25, spanGaps: true },
        { label: s.name, data: s.y, borderColor: color, backgroundColor: withAlpha(color, 0.15), borderWidth: 2, borderDash: s.dashed ? [5, 4] : undefined, pointRadius: 0, pointHoverRadius: 5, tension: 0.25, fill: false, spanGaps: true },
      ];
    }
    if (type === "scatter") {
      const xs = Array.isArray(s.x) ? s.x : chart.x;
      return [{ label: s.name, data: (s.y || []).map((y, k) => ({ x: Number(xs?.[k]), y })), backgroundColor: withAlpha(color, 0.85), borderColor: t.surface, borderWidth: 1.5, pointRadius: 5, pointHoverRadius: 7 }];
    }
    if (type === "line") {
      return [{ label: s.name, data: s.y, borderColor: color, backgroundColor: stacked ? withAlpha(color, 0.55) : withAlpha(color, 0.15), borderWidth: stacked ? 1 : 2, borderDash: s.dashed ? [5, 4] : undefined, pointRadius: stacked ? 0 : (labels.length > 40 ? 0 : 3), pointHoverRadius: 5, tension: 0.25, fill: stacked ? (i === 0 ? "origin" : "-1") : false, spanGaps: true }];
    }
    return [{ label: s.name, data: s.y, backgroundColor: s.outlined ? "transparent" : color, borderColor: s.outlined ? color : t.surface, borderWidth: s.outlined ? 2 : 0, borderRadius: 4, borderSkipped: isH ? "left" : "bottom", maxBarThickness: 36, categoryPercentage: 0.72, barPercentage: n > 1 ? 0.9 : 0.8 }];
  });

  const axisTitle = (txt) => ({ display: !!txt, text: txt || "", color: t.muted, font: { size: 11.5, family: t.font } });
  const tick = { color: t.muted, font: { size: 11, family: t.font }, maxRotation: 0, autoSkip: true };
  const valueFmt = (v) => typeof v === "number" ? (Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : v.toLocaleString("en-US", { maximumFractionDigits: 3 })) : v;

  const config = {
    type: type === "hbar" ? "bar" : type,
    data: { labels: type === "scatter" ? undefined : labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      indexAxis: isH ? "y" : "x",
      interaction: { mode: type === "scatter" ? "nearest" : "index", intersect: type === "scatter", axis: isH ? "y" : "x" },
      plugins: {
        legend: { display: n > 1, position: "top", align: "end", labels: { color: t.text, boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded", font: { size: 11.5, family: t.font }, padding: 12, filter: (item) => !/\(band\)$/.test(item.text || "") } },
        tooltip: { backgroundColor: css("--text"), titleColor: css("--bg"), bodyColor: css("--bg"), padding: 10, cornerRadius: 6, boxPadding: 4, usePointStyle: true, filter: (c) => !/\(band\)$/.test(c.dataset.label || ""),
          callbacks: { label: (c) => ` ${c.dataset.label ?? ""}: ${type === "scatter" ? `(${valueFmt(c.parsed.x)}, ${valueFmt(c.parsed.y)})` : valueFmt(isH ? c.parsed.x : c.parsed.y)}` } },
      },
      scales: {
        x: { type: type === "scatter" ? "linear" : (isH ? "linear" : "category"), stacked, title: axisTitle(chart.x_label), ticks: isH || type === "scatter" ? { ...tick, callback: (v) => valueFmt(v) } : { ...tick }, grid: { color: isH ? t.grid : "transparent", drawBorder: false }, border: { display: false }, beginAtZero: isH },
        y: isH ? { type: "category", stacked, title: axisTitle(chart.y_label), ticks: { ...tick, autoSkip: false }, grid: { color: "transparent", drawBorder: false }, border: { display: false } }
               : { stacked, title: axisTitle(chart.y_label), ticks: { ...tick, callback: (v) => valueFmt(v) }, grid: { color: t.grid, drawBorder: false }, border: { display: false }, beginAtZero: true },
      },
    },
  };
  if (type === "line" && labels.length > 24) config.options.scales.x.ticks.maxTicksLimit = 12;
  if (typeof chart.y_min === "number") { config.options.scales.y.min = chart.y_min; config.options.scales.y.beginAtZero = false; }
  if (typeof chart.y_max === "number") config.options.scales.y.max = chart.y_max;
  if (chart.x_log) { config.options.scales.x.type = "logarithmic"; config.options.scales.x.beginAtZero = false; }
  if (chart.y_log) { config.options.scales.y.type = "logarithmic"; config.options.scales.y.beginAtZero = false; }
  if (opts.options) deepMerge(config.options, opts.options);

  const inst = new Chart(canvas, config);
  live.add(inst);
  canvas._chart = inst;
  return inst;
}

/** Card with title, chart, note. */
export function chartCard(chart, opts = {}) {
  const el = h("div", { class: "card chart-card" });
  el.append(h("div", { class: "chart-title" }, chart.title || chart.id || ""));
  if (!chart.series || !chart.series.length || !(chart.series.some(s => (s.y || []).length))) {
    el.append(h("div", { class: "empty", style: { padding: "24px" } }, "No data in this chart."));
  } else {
    try { renderChart(el, chart, opts); } catch (e) { console.warn(e); el.append(h("div", { class: "error-box" }, `Could not render chart: ${e.message}`)); }
  }
  if (chart.note) el.append(h("div", { class: "chart-note" }, chart.note));
  return el;
}

export function chartGrid(charts, opts = {}) {
  const g = h("div", { class: opts.cols === 1 ? "stack" : "grid-2" });
  for (const c of charts || []) g.append(chartCard(c, opts));
  return g;
}

/** Destroy every chart whose canvas is no longer in the document. */
export function sweepCharts() {
  for (const c of [...live]) { if (!c.canvas || !document.body.contains(c.canvas)) { try { c.destroy(); } catch { /* ignore */ } live.delete(c); } }
}
/** Re-color charts after a theme change. */
export function restyleCharts() {
  const t = theme(); const pal = palette();
  for (const c of live) {
    if (!document.body.contains(c.canvas)) continue;
    c.data.datasets.forEach((d, i) => { const col = pal[i % pal.length]; if (c.config.type === "line") { d.borderColor = col; d.backgroundColor = d.fill ? withAlpha(col, 0.55) : withAlpha(col, 0.15); } else if (c.config.type === "scatter") d.backgroundColor = withAlpha(col, 0.85); else { d.backgroundColor = col; } });
    for (const ax of Object.values(c.options.scales)) { ax.ticks.color = t.muted; if (ax.title) ax.title.color = t.muted; if (ax.grid && ax.grid.color !== "transparent") ax.grid.color = t.grid; }
    c.options.plugins.legend.labels.color = t.text; c.update("none");
  }
}
function deepMerge(a, b) { for (const [k, v] of Object.entries(b)) { if (v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object") deepMerge(a[k], v); else a[k] = v; } return a; }

if (typeof Chart !== "undefined") {
  Chart.defaults.font.family = theme().font || Chart.defaults.font.family;
  Chart.defaults.color = theme().text;
}
