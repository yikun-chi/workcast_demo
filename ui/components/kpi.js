import { h, fmtNum } from "./ui.js";

/** One KPI tile. {label, value, unit, sub, accent} */
export function kpiTile({ label, value, unit, sub, accent, format }) {
  const v = format ? format(value) : (typeof value === "number" ? fmtNum(value) : (value ?? "–"));
  if (value instanceof Node) return h("div", { class: `kpi ${accent ? "accent" : ""}` }, h("div", { class: "kpi-label", title: label }, label), value, sub ? h("div", { class: "kpi-sub" }, sub) : null);
  return h("div", { class: `kpi ${accent ? "accent" : ""}` },
    h("div", { class: "kpi-label", title: label }, label),
    h("div", { class: "kpi-value", style: typeof value === "string" && v.length > 10 ? { fontSize: v.length > 24 ? "14px" : "18px", lineHeight: "1.3" } : null, title: typeof v === "string" ? v : null }, v, unit ? h("span", { class: "kpi-unit" }, unit) : null),
    sub ? h("div", { class: "kpi-sub" }, sub) : null);
}

/** {Control: 7.9, Treatment: 6.3} or {Control: {n, quits}, ...} -> compact rows inside a tile */
function nestedValue(obj) {
  const fmt = (x) => typeof x === "number" ? fmtNum(x) : String(x);
  const rows = Object.entries(obj).map(([k, v]) => v && typeof v === "object"
    ? h("div", { style: { fontSize: "12.5px", lineHeight: "1.45", marginTop: "4px" } }, h("div", { style: { fontWeight: 600 } }, k),
        h("div", { class: "muted", style: { fontVariantNumeric: "tabular-nums" } }, Object.entries(v).slice(0, 6).map(([kk, vv]) => `${kk} ${vv && typeof vv === "object" ? "…" : fmt(vv)}`).join(" · ")))
    : h("div", { class: "row", style: { justifyContent: "space-between", gap: "10px", fontSize: "13px", lineHeight: "1.5" } }, h("span", { class: "muted" }, k), h("span", { style: { fontWeight: 600, fontVariantNumeric: "tabular-nums" } }, fmt(v))));
  return h("div", { class: "stack", style: { gap: "2px", marginTop: "4px" } }, ...rows);
}

export function kpiGrid(items) {
  return h("div", { class: "kpi-grid" }, ...items.map(kpiTile));
}

/** headline dict {label: number} -> tiles */
export function headlineTiles(headline, opts = {}) {
  const items = Object.entries(headline || {}).map(([k, v]) => {
    if (v && typeof v === "object" && "value" in v) return { label: v.label || k, value: v.value, unit: v.unit, sub: v.sub };
    if (v && typeof v === "object") return { label: k, value: nestedValue(v) };
    const isShare = typeof v === "number" && v > 0 && v < 1 && !Number.isInteger(v) && /share|rate|within|ratio|prob/i.test(k);
    return { label: k, value: v, format: isShare ? x => fmtNum(x, { pct: true }) : undefined, ...opts };
  });
  return kpiGrid(items);
}
