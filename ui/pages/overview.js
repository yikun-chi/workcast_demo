/* Overview: the company, what is simulated, the input data (high-level summaries), then the details. */
import { h, replace, badge, card, kv, errorState, loading, drawer, occupationDrawerBody, fmtNum, titleCase } from "../components/ui.js";
import { kpiGrid } from "../components/kpi.js";
import { chartGrid } from "../components/chart.js";

export async function render(root, ctx) {
  const { api, instanceId, instance, href } = ctx;
  const roles = instance.scenario_roles || {};
  const byRole = Object.fromEntries(Object.entries(roles).map(([id, r]) => [r, (instance.scenarios || []).find(s => s.id === id) || { id, title: id }]));
  root.append(h("div", { class: "page-head" },
    h("div", null, h("h1", null, instance.company || instance.title), h("div", { class: "sub" }, instance.company ? instance.title : "")),
    h("div", { class: "row" }, badge(instance.world_type || "", "accent"), instance.clock?.coverage ? badge(`${instance.clock.coverage}`) : null, instance.clock?.tick ? badge(`tick ${instance.clock.tick}`) : null)));
  if (instance.problem) root.append(h("div", { class: "problem", style: { maxWidth: "900px", margin: "0 0 8px" } }, instance.problem));
  if (instance.intro) root.append(h("p", { style: { fontSize: "15px", maxWidth: "900px", lineHeight: "1.55", margin: "0 0 16px" } }, instance.intro));

  // ---- high-level summaries
  const simCard = card("The simulation", h("div", { class: "stack", style: { gap: "8px" } },
    h("div", { class: "small", style: { lineHeight: "1.5" } }, instance.world || ""),
    kv({ clock: `${instance.clock?.tick || "1h"} ticks, ${instance.clock?.coverage || ""}`, baseline: byRole.baseline?.title || "baseline", alternative: byRole.alternative?.title || "none", "scored against": instance.evaluation?.design || instance.evaluation?.tracks?.join("; ") || "reference outcomes" }),
    h("div", { class: "row" }, h("a", { class: "btn sm", href: href(instanceId, "scenarios") }, "Scenarios →"), h("a", { class: "btn sm", href: href(instanceId, "results") }, "Results →"))));
  const dataBody = h("div", null, loading("Loading tables"));
  const dataCard = card("Input data", h("div", { class: "stack", style: { gap: "8px" } }, h("div", { class: "small", style: { lineHeight: "1.5" } }, instance.source || ""), dataBody,
    h("div", { class: "row" }, h("a", { class: "btn sm", href: href(instanceId, "data") }, "Data →"), h("a", { class: "btn sm", href: href(instanceId, "ontology") }, "Ontology →"))));
  const statusCard = card("Results available", h("div", { class: "stack", style: { gap: "8px" } },
    h("div", { class: "small", style: { lineHeight: "1.5" } }, "Compare the saved simulation with actual data, or explore the alternative scenario."),
    h("div", { class: "row" }, badge(instance.has_evaluation ? "scored against actual outcome" : "not scored yet", instance.has_evaluation ? "good dot" : "dot"), badge(instance.has_insights ? "agents interviewed" : "no interviews yet", instance.has_insights ? "good dot" : "dot")),
    instance.bindings_problems?.length ? h("div", { class: "warn-box" }, h("b", null, `${instance.bindings_problems.length} ontology binding problem(s): `), instance.bindings_problems.slice(0, 3).join(" · "), " ", h("a", { href: href(instanceId, "ontology", "edit") }, ctx.readOnly ? "Inspect Ontology →" : "Fix in Ontology → Edit")) : badge("bindings validate", "good dot"),
    h("div", { class: "row" }, ctx.readOnly ? null : h("a", { class: "btn sm", href: href(instanceId, "runs") }, "Runs →"), h("a", { class: "btn sm", href: href(instanceId, "insights") }, "Insights →"))));
  root.append(h("div", { class: "section grid-3" }, simCard, dataCard, statusCard));
  api.tables(instanceId).then(tables => replace(dataBody, tables.length ? h("div", { class: "stack", style: { gap: "3px" } }, ...tables.map(t => h("div", { class: "row small", style: { justifyContent: "space-between" } }, h("a", { class: "mono", href: href(instanceId, "data", "tables", t.name) }, t.name), h("span", { class: "muted" }, t.error ? "error" : `${fmtNum(t.rows)} rows · ${t.columns.length} columns`)))) : h("div", { class: "muted small" }, "No normalized tables yet."))).catch(e => replace(dataBody, h("div", { class: "muted small" }, e.message)));

  // ---- details
  const body = h("div", null, loading("Loading company data"));
  root.append(h("h4", { style: { margin: "6px 0 10px" } }, "Details"), body);
  let summary;
  try { summary = await api.summary(instanceId); } catch (e) { replace(body, errorState(e, instanceId, "Company data (summary.json)")); return; }
  replace(body);
  body.append(h("div", { class: "section" }, h("h4", null, summary.title ? `${summary.title}${summary.period ? ` · ${summary.period}` : ""}` : "Key facts"),
    (summary.facts || []).length ? kpiGrid(summary.facts.map(f => ({ label: f.label, value: f.value, unit: f.unit }))) : h("div", { class: "muted" }, "No facts in summary.json.")));
  const org = summary.org || {};
  const units = org.units || [], rolesList = org.roles || [], systems = org.systems || [], actors = org.external_actors || [];
  body.append(h("div", { class: "section grid-3" },
    card(`Org units (${units.length})`, units.length ? h("div", { class: "stack" }, ...units.map(u => line(typeof u === "string" ? u : u.label || u.id, typeof u === "object" && u.headcount != null ? `${fmtNum(u.headcount)} people` : null))) : h("div", { class: "muted" }, "none")),
    card(`Roles (${rolesList.length})`, rolesList.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "Role"), h("th", { class: "num" }, "Headcount"), h("th", null, "O*NET"))),
      h("tbody", null, ...rolesList.map(r => h("tr", null,
        h("td", { title: r.id }, r.label || r.id),
        h("td", { class: "num" }, r.headcount != null ? fmtNum(r.headcount) : "–"),
        h("td", null, r.onet_code ? h("a", { href: "#", class: "mono", onClick: (e) => { e.preventDefault(); openOccupation(api, r.onet_code, r.label); } }, r.onet_code) : h("span", { class: "muted" }, "–"))))))) : h("div", { class: "muted" }, "none")),
    card(`Systems (${systems.length})${actors.length ? ` · external actors (${actors.length})` : ""}`, h("div", { class: "stack" },
      ...(systems.length ? systems.map(s => line(typeof s === "string" ? s : s.label || s.id, typeof s === "object" && s.capabilities != null ? `${Array.isArray(s.capabilities) ? s.capabilities.length : s.capabilities} capabilities` : null)) : [h("div", { class: "muted" }, "no systems")]),
      ...actors.map(a => line(typeof a === "string" ? a : a.label || a.id, "external actor"))))));
  if (summary.charts && summary.charts.length) body.append(h("div", { class: "section" }, h("h4", null, "Charts"), chartGrid(summary.charts)));
  const extra = Object.fromEntries(Object.entries(summary).filter(([k]) => !["title", "period", "facts", "org", "charts"].includes(k)));
  const extraCards = Object.entries(extra).map(([k, v]) => card(titleCase(k), extraValue(v)));
  if (extraCards.length) body.append(h("div", { class: "section" }, h("h4", null, "More about the data"), h("div", { class: "grid" }, ...extraCards)));
}

function extraValue(v) {
  if (Array.isArray(v)) return v.length ? h("ul", { class: "small", style: { margin: 0, paddingLeft: "18px" } }, ...v.map(x => h("li", null, typeof x === "object" ? JSON.stringify(x) : String(x)))) : h("span", { class: "muted" }, "none");
  if (v && typeof v === "object") return kv(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, typeof x === "number" ? fmtNum(x) : x])));
  return h("span", null, typeof v === "number" ? fmtNum(v) : String(v ?? ""));
}
function line(a, b) { return h("div", { class: "row", style: { justifyContent: "space-between" } }, h("span", null, a), b ? h("span", { class: "muted small" }, b) : null); }
export async function openOccupation(api, code, roleLabel) {
  drawer.open(h("span", null, roleLabel ? `${roleLabel} · ` : "", h("span", { class: "mono" }, code)), await occupationDrawerBody(api, code));
}
