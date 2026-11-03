/* Small DOM helpers and shared UI primitives: h(), empty/error/loading states, badges, drawer, toast, formatting. */

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "html") el.innerHTML = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}
export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function replace(el, ...children) { clear(el); return append(el, children); }

// ---------- formatting ----------
export function fmtNum(v, opts = {}) {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v !== "number") { const n = Number(v); if (Number.isNaN(n) || String(v).trim() === "") return String(v); v = n; }
  if (!Number.isFinite(v)) return String(v);
  if (opts.pct) return (v * 100).toFixed(opts.digits ?? 1) + "%";
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  const abs = Math.abs(v);
  const digits = opts.digits ?? (abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3);
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function fmtMetric(v, unit) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number" && !unit && Math.abs(v) <= 1 && !Number.isInteger(v)) return fmtNum(v, { pct: true });
  return fmtNum(v) + (unit ? ` ${unit}` : "");
}
export function fmtDate(s) {
  if (!s) return "–";
  const d = new Date(s); if (Number.isNaN(d.getTime())) return String(s);
  return d.toISOString().replace("T", " ").slice(0, 16);
}
export function titleCase(s) { return String(s || "").replace(/[_:]/g, " ").replace(/\b\w/g, c => c.toUpperCase()); }
export function fmtCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "number") return fmtNum(v);
  return String(v);
}

// ---------- states ----------
export function emptyState(title, hint) {
  return h("div", { class: "empty" }, h("div", { class: "empty-title" }, title), hint ? h("div", { class: "small" }, hint) : null);
}
export function notGenerated(instanceId, what) {
  return emptyState(what ? `${what} not generated yet.` : "Not generated yet.",
    h("span", null, "Run ", h("code", null, `orgsim demo ${instanceId}`), " to produce it."));
}
export function errorState(err, instanceId, what) {
  if (err && err.notFound && instanceId) return notGenerated(instanceId, what);
  console.warn(err);
  return h("div", { class: "error-box" }, h("b", null, "Request failed: "), err && err.message ? err.message : String(err), err && err.url ? h("div", { class: "small mono" }, err.url) : null);
}
export function loading(label = "Loading") { return h("div", { class: "loading" }, h("span", { class: "spinner" }), label); }

// ---------- primitives ----------
export function badge(text, kind) { return h("span", { class: `badge ${kind || ""}` }, text); }
export function kv(obj, opts = {}) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of Object.entries(obj || {})) {
    if (opts.skip && opts.skip.includes(k)) continue;
    dl.append(h("dt", null, k), h("dd", null, typeof v === "object" && v !== null ? h("code", null, JSON.stringify(v)) : fmtCell(v)));
  }
  return dl;
}
export function card(title, body, opts = {}) {
  return h("div", { class: `card ${opts.class || ""}` }, title ? h("div", { class: "card-title" }, h("span", null, title), opts.right || null) : null, body);
}
export function subtabs(items, active, onChange) {
  const wrap = h("div", { class: "subtabs" });
  for (const it of items) wrap.append(h("button", { class: `btn sm ${it.id === active ? "active" : ""}`, onClick: () => onChange(it.id) }, it.label));
  return wrap;
}
export function segmented(items, active, onChange) {
  const wrap = h("div", { class: "btn-group" });
  for (const it of items) wrap.append(h("button", { class: `btn sm ${it.id === active ? "active" : ""}`, onClick: () => onChange(it.id) }, it.label));
  return wrap;
}
export function debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ---------- drawer ----------
const drawer = {
  el: () => document.getElementById("drawer"),
  open(title, body) {
    replace(document.getElementById("drawer-title"), title);
    replace(document.getElementById("drawer-body"), body);
    this.el().classList.add("open"); this.el().setAttribute("aria-hidden", "false");
    document.getElementById("drawer-backdrop").classList.add("open");
  },
  close() { this.el().classList.remove("open"); this.el().setAttribute("aria-hidden", "true"); document.getElementById("drawer-backdrop").classList.remove("open"); },
};
export { drawer };
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("drawer-close")?.addEventListener("click", () => drawer.close());
  document.getElementById("drawer-backdrop")?.addEventListener("click", () => drawer.close());
  document.addEventListener("keydown", e => { if (e.key === "Escape") drawer.close(); });
});

// ---------- toast ----------
export function toast(msg, kind = "", ms = 3200) {
  const host = document.getElementById("toasts"); if (!host) return;
  const t = h("div", { class: `toast ${kind}` }, msg);
  host.append(t); setTimeout(() => t.remove(), ms);
}

// ---------- csv ----------
export function downloadCsv(filename, columns, rows) {
  const esc = v => { const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lines = [columns.map(esc).join(",")]; for (const r of rows) lines.push(columns.map(c => esc(r[c])).join(","));
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = h("a", { href: URL.createObjectURL(blob), download: filename }); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

// ---------- O*NET occupation drawer (shared by Overview and Input editors) ----------
export async function occupationDrawerBody(api, code) {
  const body = h("div", null, loading("Loading O*NET occupation"));
  api.onetOccupation(code).then(occ => {
    replace(body,
      h("p", { class: "muted" }, occ.description),
      h("div", { class: "row", style: { marginBottom: "12px" } },
        badge(`${occ.counts.tasks} tasks`), badge(`${occ.counts.dwas} DWAs`), badge(`${occ.counts.iwas} IWAs`), badge(`${occ.counts.gwas} GWAs`)),
      h("h4", null, "Tasks"),
      h("ul", { class: "small", style: { paddingLeft: "18px", margin: "6px 0 14px" } }, ...occ.tasks.map(t => h("li", null, t.task, " ", h("span", { class: "muted" }, `(${t.task_type || "task"})`)))),
      h("h4", null, "Detailed work activities"),
      h("div", { class: "table-wrap", style: { marginTop: "6px" } }, h("table", { class: "table" },
        h("thead", null, h("tr", null, h("th", null, "DWA"), h("th", null, "IWA"), h("th", null, "GWA"))),
        h("tbody", null, ...occ.dwas.map(d => h("tr", null, h("td", { title: d.dwa, style: { whiteSpace: "normal" } }, d.dwa), h("td", { title: d.iwa }, d.iwa), h("td", { title: d.gwa }, d.gwa)))))));
  }).catch(e => replace(body, errorState(e)));
  return body;
}
