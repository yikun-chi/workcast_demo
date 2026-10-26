import { h, replace, badge, card, errorState, loading, emptyState, fmtNum, fmtDate, segmented, debounce, kv, drawer } from "../components/ui.js";
import { headlineTiles } from "../components/kpi.js";
import { renderChart, sweepCharts } from "../components/chart.js";
import { dataGrid } from "../components/grid.js";

export async function render(root, ctx) {
  const { api, instanceId, instance, params, href, navigate } = ctx;
  root.append(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Runs"), h("div", { class: "sub" }, "Runs of the baseline and the alternative on the hourly clock: who did what, when, and what it cost in hours and waiting."))));
  const listBox = h("div", null, loading("Loading runs")); root.append(listBox);
  let runs;
  try { runs = await api.runs(instanceId); } catch (e) { replace(listBox, errorState(e, instanceId, "Runs")); return; }
  const roles = instance?.scenario_roles || null;
  const hiddenCount = roles ? runs.filter(r => !roles[r.scenario] && !(r.scenario === params[0] && r.run_id === params[1])).length : 0;
  if (roles) runs = runs.filter(r => roles[r.scenario] || (r.scenario === params[0] && r.run_id === params[1]));
  if (!runs.length) { replace(listBox, emptyState("No runs yet.", h("span", null, "Launch one from ", h("a", { href: href(instanceId, "scenarios") }, "Scenarios"), " or run ", h("code", null, `orgsim run ${instanceId} --scenario baseline`), "."))); return; }

  const headKeys = [...new Set(runs.flatMap(r => Object.keys(r.summary?.headline || {})))].slice(0, 6);
  const selSid = params[0], selRun = params[1];
  const selected = runs.find(r => r.scenario === selSid && r.run_id === selRun) || null;
  const table = h("table", { class: "table" },
    h("thead", null, h("tr", null, h("th", null, "Scenario"), h("th", null, "Run"), h("th", null, "Status"), h("th", { class: "num" }, "Events"), h("th", { class: "num" }, "Ticks"), ...headKeys.map(k => h("th", { class: "num", title: k }, k)))),
    h("tbody", null, ...runs.map(r => h("tr", { class: selected === r ? "selected" : "", style: { cursor: "pointer" }, onClick: () => navigate(href(instanceId, "runs", r.scenario, r.run_id)) },
      h("td", null, roles?.[r.scenario] ? badge(roles[r.scenario], roles[r.scenario] === "baseline" ? "good" : "accent") : null, " ", r.scenario), h("td", { class: "mono" }, r.run_id),
      h("td", null, badge(r.complete ? "complete" : "running", r.complete ? "good dot" : "warn dot")),
      h("td", { class: "num" }, r.summary?.events != null ? fmtNum(r.summary.events) : "–"), h("td", { class: "num" }, r.summary?.ticks != null ? fmtNum(r.summary.ticks) : "–"),
      ...headKeys.map(k => h("td", { class: "num" }, fmtHead(k, r.summary?.headline?.[k])))))));
  replace(listBox, h("div", { class: "card tight", style: { marginBottom: "16px" } }, h("div", { class: "card-title" }, h("span", null, `${runs.length} run${runs.length === 1 ? "" : "s"}`), h("span", { class: "muted small" }, `Select a run to explore its trace${hiddenCount ? ` · ${hiddenCount} runs of other scenario files (evaluation protocol, CLI what-ifs) are not listed` : ""}`)), h("div", { class: "table-wrap", style: { maxHeight: "300px" } }, table)));

  if (!selected) {
    const first = runs.find(r => r.complete) || runs[0];
    root.append(h("div", { class: "empty" }, h("div", { class: "empty-title" }, "Select a run above."), h("button", { class: "btn sm", onClick: () => navigate(href(instanceId, "runs", first.scenario, first.run_id)) }, `Open ${first.scenario} / ${first.run_id}`)));
    return;
  }
  await runDetail(root, ctx, selected);
}

function fmtHead(k, v) { if (v == null) return "–"; if (typeof v === "object") return Object.entries(v).map(([a, b]) => `${a} ${typeof b === "number" ? fmtNum(b) : (b && typeof b === "object" ? "…" : b)}`).join(" · "); if (typeof v === "number" && v > 0 && v < 1 && !Number.isInteger(v) && /share|rate|within|ratio|prob|frac/i.test(k)) return fmtNum(v, { pct: true }); return typeof v === "number" ? fmtNum(v) : String(v); }

async function runDetail(root, { api, instanceId }, run) {
  const { scenario: sid, run_id: rid } = run;
  const head = h("div", { class: "section" }, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "10px" } },
    h("div", { class: "row" }, h("h2", null, `${sid} / `, h("span", { class: "mono" }, rid)), badge(run.complete ? "complete" : "running", run.complete ? "good dot" : "warn dot")),
    h("div", { class: "row muted small" }, run.summary?.ticks != null ? `${fmtNum(run.summary.ticks)} ticks` : null, run.summary?.events != null ? ` · ${fmtNum(run.summary.events)} events` : null)));
  root.append(head);
  if (!run.complete) { root.append(h("div", { class: "warn-box" }, "This run has no summary.json yet; it may still be running. Trace views below read whatever has been flushed so far.")); }

  // headline tiles
  const headline = run.summary?.headline || {};
  const tilesBox = h("div", null, Object.keys(headline).length ? headlineTiles(headline) : null);
  root.append(tilesBox);
  if (!Object.keys(headline).length && run.complete) api.runFile(instanceId, sid, rid, "summary").then(s => { if (s?.headline && Object.keys(s.headline).length) replace(tilesBox, headlineTiles(s.headline)); }).catch(() => {});

  // timeline
  const tl = { by: "activity", bucket: (run.summary?.ticks || 0) > 1500 ? 24 : 6 };
  const tlArea = h("div", null, loading("Loading timeline"));
  const tlControls = h("div", { class: "row" },
    h("span", { class: "muted small" }, "stack by"), segmented([{ id: "activity", label: "Activity" }, { id: "role", label: "Role" }, { id: "action_type", label: "Action type" }], tl.by, (v) => { tl.by = v; drawTl(); }),
    h("span", { class: "muted small", style: { marginLeft: "8px" } }, "bucket"), segmented([{ id: 1, label: "1h" }, { id: 6, label: "6h" }, { id: 24, label: "24h" }], tl.bucket, (v) => { tl.bucket = v; drawTl(); }));
  const tlCard = h("div", { class: "card chart-card section" }, h("div", { class: "card-title" }, h("span", null, "Timeline: events per tick"), tlControls), tlArea);
  root.append(tlCard);
  async function drawTl() {
    replace(tlControls, h("span", { class: "muted small" }, "stack by"), segmented([{ id: "activity", label: "Activity" }, { id: "role", label: "Role" }, { id: "action_type", label: "Action type" }], tl.by, (v) => { tl.by = v; drawTl(); }),
      h("span", { class: "muted small", style: { marginLeft: "8px" } }, "bucket"), segmented([{ id: 1, label: "1h" }, { id: 6, label: "6h" }, { id: 24, label: "24h" }], tl.bucket, (v) => { tl.bucket = v; drawTl(); }));
    replace(tlArea, loading("Loading timeline"));
    try {
      const d = await api.runFile(instanceId, sid, rid, "timeline", { by: tl.by, bucket: tl.bucket });
      const names = Object.entries(d.series || {}).sort((a, b) => sum(b[1]) - sum(a[1]));
      if (!names.length) { replace(tlArea, emptyState("No trace events yet.")); return; }
      const top = names.slice(0, 8); const rest = names.slice(8);
      const series = top.map(([n, ys]) => ({ name: n || "(exogenous)", y: ys }));
      if (rest.length) series.push({ name: `Other (${rest.length})`, y: d.ticks.map((_, i) => rest.reduce((s, [, ys]) => s + (ys[i] || 0), 0)) });
      const labels = d.ticks.map((t, i) => tl.bucket >= 24 && d.times?.[i] ? d.times[i].slice(0, 10) : `t+${t}h`);
      replace(tlArea);
      renderChart(tlArea, { type: "line", x: labels, series, x_label: tl.bucket >= 24 ? "Simulated day" : "Hours since run start", y_label: `Events per ${tl.bucket}h` }, { stacked: true, tall: true, options: { plugins: { legend: { display: true } }, elements: { line: { tension: 0.2 } }, scales: { x: { ticks: { maxTicksLimit: 14 } } } } });
      tlArea.append(h("div", { class: "chart-note" }, `${d.ticks.length} buckets · ${names.length} ${tl.by.replace("_", " ")} values${rest.length ? ` · smallest ${rest.length} folded into "Other"` : ""}`));
      setTimeout(sweepCharts, 10);
    } catch (e) { replace(tlArea, errorState(e)); }
  }
  drawTl();

  // agents
  const agentsBox = h("div", { class: "section" }, h("h4", null, "Agents"), loading("Loading agents"));
  root.append(agentsBox);
  const traceState = { agent: "", case: "", activity: "", from_tick: "", to_tick: "" };
  let traceGrid = null;
  try {
    const a = await api.runFile(instanceId, sid, rid, "agents", { limit: 500 });
    let twinMeta = null;
    try { twinMeta = await api.runFile(instanceId, sid, rid, "twins", { limit: 1 }); } catch { twinMeta = null; }
    const hasTwins = !!(twinMeta && twinMeta.total);
    const rows = (a.rows || []).map(r => ({ agent: r.agent_id || "(exogenous)", role: r.role, unit: r.org_unit, events: r.events, hours: r.hours, wait: r.wait, top_activities: r.top_activities }));
    const openTwin = async (agentId) => {
      const body = h("div", null, loading("Loading digital twin"));
      drawer.open(h("span", null, "Digital twin · ", h("span", { class: "mono" }, agentId)), body);
      try {
        const t = await api.runFile(instanceId, sid, rid, "twins", { agent: agentId, limit: 1 });
        const tw = (t.rows || [])[0];
        if (!tw) { replace(body, emptyState("No twin record for this agent.")); return; }
        const outcome = tw.quit_week ? badge(`resigned in week ${tw.quit_week}`, "warn") : badge("stayed to the end", "good");
        replace(body,
          h("p", { class: "small", style: { lineHeight: "1.5" } }, tw.profile),
          h("div", { class: "row", style: { gap: "6px", marginBottom: "10px" } }, badge(tw.role), badge(tw.org_unit || "–"), badge(`team ${tw.team_id}`), badge(`arm ${tw.arm}`), badge(`seat ${tw.seat}`), outcome),
          h("h5", null, "Trait layer (fixed for the run)"), kv(tw.traits || {}),
          h("h5", null, "Policy exposure"), kv({ offered: tw.offered ? "yes" : "no", eligible_days: tw.eligible_days, wfh_days: tw.wfh_days, take_up: tw.eligible_days ? fmtNum(tw.wfh_days / tw.eligible_days, { pct: true }) : "–" }),
          h("h5", null, "Latent states at the end"), kv({ ...(tw.final_states || {}), weekly_quit_hazard: tw.final_quit_hazard_week }),
          h("p", { class: "muted small" }, "The same twin feeds every seat policy: a rule seat draws from these weights, an LLM seat reads this profile, its traits and last week's states before choosing."));
      } catch (e) { replace(body, errorState(e)); }
    };
    replace(agentsBox, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } }, h("h4", null, `Agents (${a.total ?? rows.length})`), h("span", { class: "muted small" }, hasTwins ? "Click an agent to filter the trace below; use the twin button for its digital-twin card" : "Click an agent to filter the trace below")),
      rows.length ? dataGrid({ rows: hasTwins ? rows.map(r => ({ ...r, twin: r.agent })) : rows, columns: hasTwins ? ["agent", "role", "unit", "events", "hours", "wait", "top_activities", "twin"] : ["agent", "role", "unit", "events", "hours", "wait", "top_activities"], columnLabels: { unit: "org unit", hours: "labor hours", wait: "wait hours (sum)", top_activities: "top activities", twin: "digital twin" }, pageSize: 25, sort: "events", desc: true, exportName: `${instanceId}_${sid}_${rid}_agents`, maxHeight: "360px",
        render: { hours: v => fmtNum(v, { digits: 1 }), wait: v => fmtNum(v, { digits: 1 }), twin: v => v && v !== "(exogenous)" ? h("button", { class: "btn sm ghost", onClick: (e) => { e.stopPropagation(); openTwin(v); } }, "twin") : h("span", { class: "muted" }, "–"), top_activities: v => h("span", { class: "row", style: { gap: "4px", flexWrap: "nowrap" }, title: Object.entries(v || {}).map(([k, n]) => `${k}: ${n}`).join("\n") }, ...Object.entries(v || {}).slice(0, 3).map(([k, n]) => badge(`${k} ${n}`))) },
        onRowClick: (r) => { traceState.agent = r.agent === "(exogenous)" ? "" : r.agent; agentInp.value = traceState.agent; applyTrace(); traceBox.scrollIntoView({ behavior: "smooth", block: "start" }); } })
        : emptyState("No agent activity recorded."));
  } catch (e) { replace(agentsBox, h("h4", null, "Agents"), errorState(e)); }

  // trace explorer
  const agentInp = h("input", { class: "input sm", placeholder: "agent id", style: { width: "140px" } });
  const caseInp = h("input", { class: "input sm", placeholder: "case id", style: { width: "160px" } });
  const actInp = h("input", { class: "input sm", placeholder: "activity (exact)", style: { width: "200px" } });
  const fromInp = h("input", { class: "input sm", type: "number", placeholder: "from tick", style: { width: "100px" } });
  const toInp = h("input", { class: "input sm", type: "number", placeholder: "to tick", style: { width: "100px" } });
  const clearBtn = h("button", { class: "btn sm ghost", onClick: () => { for (const i of [agentInp, caseInp, actInp, fromInp, toInp]) i.value = ""; applyTrace(); } }, "Clear filters");
  const applyTrace = debounce(() => { traceState.agent = agentInp.value.trim(); traceState.case = caseInp.value.trim(); traceState.activity = actInp.value.trim(); traceState.from_tick = fromInp.value; traceState.to_tick = toInp.value; traceGrid?.setParams({}); }, 300);
  for (const i of [agentInp, caseInp, actInp, fromInp, toInp]) i.addEventListener("input", applyTrace);
  const traceBox = h("div", { class: "section" }, h("h4", null, "Trace explorer"),
    h("div", { class: "muted small", style: { marginBottom: "8px" } }, "Every row is one action on the hourly clock. Filters are applied server-side; click a case id to follow that work item."));
  root.append(traceBox);
  traceGrid = dataGrid({
    search: false, pageSize: 50, exportName: `${instanceId}_${sid}_${rid}_trace`, maxHeight: "520px",
    extraControls: [h("span", { class: "muted small" }, "filter"), agentInp, caseInp, actInp, fromInp, toInp, clearBtn],
    columnLabels: { duration_h: "labor h", wait_h: "wait h", sim_time: "sim time" },
    render: {
      sim_time: v => h("span", { class: "mono small" }, fmtDate(v)),
      case_id: (v) => v ? h("a", { href: "#", class: "mono", onClick: (e) => { e.preventDefault(); caseInp.value = v; applyTrace(); } }, v) : h("span", { class: "muted" }, "–"),
      agent_id: (v) => v ? h("a", { href: "#", onClick: (e) => { e.preventDefault(); agentInp.value = v; applyTrace(); } }, v) : h("span", { class: "muted" }, "–"),
      action_type: v => badge(v, { complete: "good", decide: "accent", wait: "warn", handoff: "", arrive: "", exogenous: "", start: "" }[v] ?? ""),
      provenance: v => h("span", { class: "muted small" }, v),
      attributes: v => { let o = v; if (typeof v === "string") { try { o = JSON.parse(v); } catch { o = v; } } const s = typeof o === "object" && o ? Object.entries(o).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join(" · ") : String(o ?? ""); return h("span", { class: "small", title: s, style: { maxWidth: "320px", display: "inline-block", overflow: "hidden", textOverflow: "ellipsis", verticalAlign: "bottom" } }, s || h("span", { class: "muted" }, "–")); },
      duration_h: v => fmtNum(v, { digits: 2 }), wait_h: v => fmtNum(v, { digits: 1 }),
    },
    fetchPage: async ({ offset, limit }) => {
      const d = await api.runFile(instanceId, sid, rid, "trace", { offset, limit, agent: traceState.agent, case: traceState.case, activity: traceState.activity, from_tick: traceState.from_tick === "" ? -1 : traceState.from_tick, to_tick: traceState.to_tick === "" ? -1 : traceState.to_tick });
      const cols = (d.columns || []).filter(c => c !== "sim_time"); // tick + sim_time together first
      return { columns: ["tick", "sim_time", ...cols.filter(c => c !== "tick")], rows: d.rows, total: d.total };
    },
  });
  traceBox.append(traceGrid);

  // config
  api.runFile(instanceId, sid, rid, "config").then(cfg => root.append(h("div", { class: "section" }, h("details", null, h("summary", { class: "muted small", style: { cursor: "pointer" } }, "Run configuration (scenario + seed)"), h("pre", { class: "small" }, JSON.stringify(cfg, null, 2)))))).catch(() => {});
}
const sum = (a) => a.reduce((s, x) => s + x, 0);
