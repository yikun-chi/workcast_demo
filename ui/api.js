/* Fetch wrapper for /api with a fixture mode (?fixtures=1) that serves ui/dev/fixtures/*.json instead. */

export const READ_ONLY = document.querySelector('meta[name="workcast-mode"]')?.content === "static";
export const FIXTURES = !READ_ONLY && new URLSearchParams(location.search).get("fixtures") === "1";
export const assetUrl = (path) => new URL(`../${path.replace(/^\//, "")}`, import.meta.url).href;
const FIX_BASE = "/ui/dev/fixtures/";

export class ApiError extends Error {
  constructor(status, message, url) { super(message); this.status = status; this.url = url; }
  get notFound() { return this.status === 404; }
}

async function realFetch(path, opts = {}) {
  const res = await fetch(path, { headers: { "Accept": "application/json", ...(opts.body ? { "Content-Type": "application/json" } : {}) }, ...opts });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText || `HTTP ${res.status}`, path);
  return data;
}

// ---------- fixture layer ----------
const fixCache = new Map();
async function fixture(name) {
  if (!fixCache.has(name)) {
    fixCache.set(name, (async () => {
      const res = await fetch(FIX_BASE + name + ".json");
      if (!res.ok) throw new ApiError(404, `fixture ${name}.json not found`, FIX_BASE + name);
      return res.json();
    })());
  }
  const v = await fixCache.get(name);
  return JSON.parse(JSON.stringify(v)); // defensive copy
}
const fixWrites = new Map(); // simulated PUT storage

function paginate(rows, q) {
  const offset = +(q.get("offset") || 0), limit = +(q.get("limit") || 50);
  let out = rows;
  const s = (q.get("q") || "").toLowerCase();
  if (s) out = out.filter(r => Object.values(r).some(v => String(v ?? "").toLowerCase().includes(s)));
  const sort = q.get("sort");
  if (sort) {
    const desc = q.get("desc") === "1";
    out = [...out].sort((a, b) => { const x = a[sort], y = b[sort]; if (x === y) return 0; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : 1) * (desc ? -1 : 1); });
  }
  return { total: out.length, offset, limit, rows: out.slice(offset, offset + limit) };
}

async function fixtureFetch(path, opts = {}) {
  const url = new URL(path, location.origin);
  const q = url.searchParams;
  const parts = url.pathname.replace(/^\/api\//, "").split("/").filter(Boolean);
  const method = (opts.method || "GET").toUpperCase();
  await new Promise(r => setTimeout(r, 120)); // visible loading state

  if (parts[0] === "health") return { ok: true, instances: ["bpi19", "trip"] };
  if (parts[0] === "onet") {
    if (parts[1] === "occupations") return fixture(`onet_${parts[2]}`);
    if (parts[1] === "dwas") {
      const s = (q.get("q") || "").toLowerCase(); if (!s) return [];
      const occ = await fixture("onet_43-3031.00"); const occ2 = await fixture("onet_13-1023.00");
      return [...occ.dwas, ...occ2.dwas].filter(d => d.dwa.toLowerCase().includes(s)).slice(0, 25);
    }
    return { version: "31.0" };
  }
  if (parts[0] !== "instances") throw new ApiError(404, "unknown fixture route", path);
  if (parts.length === 1) return fixture("instances");
  const id = parts[1]; const rest = parts.slice(2);
  const empty = id !== "bpi19"; // the second instance shows empty states in fixture mode
  if (rest.length === 0) {
    const inst = await fixture("instance");
    if (empty) { const all = await fixture("instances"); const i = all.find(x => x.id === id) || all[1]; return { ...i, scenarios: [{ id: "baseline", title: "Baseline", description: "Observed trial as run.", extends: null, file: "baseline.yaml" }], bindings_problems: [] }; }
    return inst;
  }
  const key = rest.join("/");
  if (method === "PUT") {
    fixWrites.set(id + ":" + key, JSON.parse(opts.body));
    if (key === "ontology/bindings") return { saved: true, problems: ["(fixture) saved in memory only", "role:batch_job has no onet_code"] };
    return { saved: true };
  }
  if (method === "POST" && key === "runs") {
    const body = JSON.parse(opts.body || "{}");
    const runs = await fixture("runs");
    const newRun = { scenario: body.scenario || "baseline", run_id: `${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}_s${body.seed ?? 1}`, complete: false, summary: {} };
    const existing = fixWrites.get(id + ":runs") || runs;
    fixWrites.set(id + ":runs", [...existing, newRun]);
    setTimeout(() => { newRun.complete = true; newRun.summary = { ticks: 336, events: 1317, headline: { "Completed within 14d": 0.709, "Payment blocks": 55, "Median cycle time (d)": 9.9, "Labor hours": 1402.5 } }; }, 4000);
    return { launched: true, pid: 4242, scenario: newRun.scenario, seed: body.seed ?? 1 };
  }
  if (key === "ontology/schema") return fixture("ontology_schema");
  if (key === "ontology/concepts") { const schema = await fixture("ontology_schema"); return { schema, concepts: schema.nodes.map(n => ({ type: n.type, description: n.properties?.description || "", layer: "bound", count: 1, used: true })), relations: schema.edges.map(e => ({ source: e.source.replace(/^type:/, ""), type: e.type, target: e.target.replace(/^type:/, ""), description: e.properties?.description || "", count: 1, used: true })), layers: {}, stats: { concepts_used: schema.nodes.length, concepts: schema.nodes.length, relations_used: schema.edges.length, relations: schema.edges.length } }; }
  if (key === "ontology/bindings") return fixWrites.get(id + ":" + key) || (empty ? {} : fixture("ontology_bindings"));
  if (key === "ontology") { if (empty) return { nodes: [{ id: `org:${id}`, type: "Organization", label: "Trip.com", properties: {} }], edges: [], stats: { nodes: 1, edges: 0, nodes_by_type: { Organization: 1 }, edges_by_type: {} } }; return fixture(q.get("tasks") === "1" ? "ontology_tasks" : "ontology"); }
  if (empty && !["seats", "scenarios"].includes(rest[0])) throw new ApiError(404, `missing instances/${id}/... (fixture mode: ${id} is intentionally empty)`, path);
  if (rest[0] === "people") throw new ApiError(404, "people view has no fixture (run against the live API)", path);
  if (key === "summary") return fixture("summary");
  if (key === "tables") return fixture("tables");
  if (rest[0] === "tables") { const t = await fixture(`table_${rest.slice(1).join("/")}`); const p = paginate(t.rows, q); return { name: t.name, columns: t.columns, ...p }; }
  if (key === "scenarios") return empty ? [{ id: "baseline", title: "Baseline", description: "Observed trial as run.", extends: null, file: "baseline.yaml" }] : fixture("scenarios");
  if (rest[0] === "scenarios") return fixWrites.get(id + ":" + key) || fixture(`scenario_${rest[1]}`);
  if (key === "seats") return fixWrites.get(id + ":" + key) || (empty ? { default: { adapter: "rule" }, seats: {} } : fixture("seats"));
  if (key === "runs") return fixWrites.get(id + ":runs") || fixture("runs");
  if (rest[0] === "runs") {
    const name = rest[3];
    if (name === "summary") return fixture("run_summary");
    if (name === "config") return fixture("run_config");
    if (name === "metrics") throw new ApiError(404, "no metrics.json", path);
    const t = await fixture("trace");
    if (name === "trace") {
      let rows = t.rows;
      const a = q.get("agent"), c = q.get("case"), act = q.get("activity"), f = +(q.get("from_tick") ?? -1), to = +(q.get("to_tick") ?? -1);
      if (a) rows = rows.filter(r => r.agent_id === a);
      if (c) rows = rows.filter(r => r.case_id === c);
      if (act) rows = rows.filter(r => r.activity === act);
      if (f >= 0) rows = rows.filter(r => r.tick >= f);
      if (to >= 0) rows = rows.filter(r => r.tick <= to);
      const p = paginate(rows, q); return { columns: t.columns, ...p };
    }
    if (name === "timeline") {
      const by = q.get("by") || "activity", bucket = Math.max(1, +(q.get("bucket") || 1));
      const buckets = new Map();
      for (const r of t.rows) { const b = Math.floor(r.tick / bucket) * bucket; if (!buckets.has(b)) buckets.set(b, { time: r.sim_time, counts: {} }); const e = buckets.get(b); e.counts[r[by]] = (e.counts[r[by]] || 0) + 1; }
      const ticks = [...buckets.keys()].sort((x, y) => x - y);
      const keys = [...new Set(t.rows.map(r => r[by]))];
      return { by, bucket, ticks, times: ticks.map(k => buckets.get(k).time), series: Object.fromEntries(keys.map(k => [k, ticks.map(tk => buckets.get(tk).counts[k] || 0)])) };
    }
    if (name === "agents") {
      const g = new Map();
      for (const r of t.rows) { const k = `${r.agent_id}|${r.role}|${r.org_unit}`; if (!g.has(k)) g.set(k, { agent_id: r.agent_id, role: r.role, org_unit: r.org_unit, events: 0, hours: 0, wait: 0, acts: {} }); const e = g.get(k); e.events++; e.hours += r.duration_h; e.wait += r.wait_h; e.acts[r.activity] = (e.acts[r.activity] || 0) + 1; }
      const rows = [...g.values()].map(e => ({ agent_id: e.agent_id, role: e.role, org_unit: e.org_unit, events: e.events, hours: +e.hours.toFixed(2), wait: +e.wait.toFixed(1), top_activities: Object.fromEntries(Object.entries(e.acts).sort((a, b) => b[1] - a[1]).slice(0, 5)) })).sort((a, b) => b.events - a.events);
      return { total: rows.length, rows };
    }
  }
  if (key === "evaluation") return fixture("evaluation");
  if (key === "results" || key === "insights") throw new ApiError(404, `${key} has no fixture (run against the live API)`, path);
  if (key === "report") return fixture("report");
  throw new ApiError(404, `no fixture for ${key}`, path);
}

// Public snapshots use the same page modules, with no backend or mutation route.
const staticCache = new Map();
async function snapshotFile(name) {
  if (!staticCache.has(name)) staticCache.set(name, realFetch(assetUrl(`public-data/${name}.json`)));
  return staticCache.get(name);
}
async function staticFetch(path, opts = {}) {
  if ((opts.method || "GET").toUpperCase() !== "GET") throw new ApiError(405, "This site displays saved results. Editing and rerunning are unavailable.", path);
  const url = new URL(path, location.origin);
  const route = url.pathname.replace(/^\/api/, "");
  const index = await snapshotFile("index");
  let value;
  if (route === "/instances") value = index.instances;
  else if (route === "/health") value = { ok: true, read_only: true, instances: index.instances.map(i => i.id) };
  else if (route.startsWith("/onet/occupations/")) value = index.occupations[decodeURIComponent(route.split("/").pop())];
  else {
    const match = route.match(/^\/instances\/([^/]+)(.*)$/);
    if (match && index.instances.some(i => i.id === match[1])) {
      const snapshot = await snapshotFile(match[1]);
      const runMatch = match[2].match(/^\/runs\/([^/]+)\/([^/]+)\/(history|trace)$/);
      if (runMatch) {
        const run = snapshot.run_data?.[`${runMatch[1]}/${runMatch[2]}`];
        if (!run) throw new ApiError(404, "This run is not included in the public snapshot. Choose a published scenario run.", path);
        if (runMatch[3] === "trace") {
          const {queryTable} = await import("./data/client.js");
          return queryTable(run.trace, Object.fromEntries(url.searchParams), assetUrl("public-data/"), index.files, opts.onProgress);
        }
        const resource = assetUrl(`public-data/${run.history}`);
        if (!staticCache.has(resource)) staticCache.set(resource, (async () => {
          const response = await fetch(resource);
          if (!response.ok) throw new ApiError(response.status, "Cannot load saved history", resource);
          const bytes = await response.arrayBuffer();
          const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(x => x.toString(16).padStart(2, "0")).join("");
          if (hash !== index.files[run.history]) throw new Error("The saved history changed. Reload the page.");
          return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
        })().catch(e => { staticCache.delete(resource); throw e; }));
        return structuredClone(await staticCache.get(resource));
      }
      if (match[2].startsWith("/tables/")) {
        const name = decodeURIComponent(match[2].slice("/tables/".length));
        const table = snapshot.tables?.[name];
        if (!table) throw new ApiError(404, "This table is not included in the public snapshot.", path);
        const {queryTable} = await import("./data/client.js");
        return queryTable(table, Object.fromEntries(url.searchParams), assetUrl("public-data/"), index.files, opts.onProgress);
      }
      value = snapshot.responses[match[2] || "/"];
    }
  }
  if (value === undefined) throw new ApiError(404, "This resource is not included in the public snapshot.", path);
  return structuredClone(value);
}
const doFetch = READ_ONLY ? staticFetch : FIXTURES ? fixtureFetch : realFetch;

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString(); return s ? `?${s}` : "";
}

export const api = {
  readOnly: READ_ONLY,
  get: (path, params) => doFetch(`/api${path}${qs(params)}`),
  put: (path, body) => doFetch(`/api${path}`, { method: "PUT", body: JSON.stringify(body) }),
  post: (path, body) => doFetch(`/api${path}`, { method: "POST", body: JSON.stringify(body) }),

  health: () => api.get("/health"),
  instances: () => api.get("/instances"),
  instance: (id) => api.get(`/instances/${id}`),
  ontology: (id, tasks) => api.get(`/instances/${id}/ontology`, { tasks: tasks ? 1 : 0 }),
  ontologySchema: (id) => api.get(`/instances/${id}/ontology/schema`),
  bindings: (id) => api.get(`/instances/${id}/ontology/bindings`),
  saveBindings: (id, body) => api.put(`/instances/${id}/ontology/bindings`, body),
  summary: (id) => api.get(`/instances/${id}/summary`),
  tables: (id) => api.get(`/instances/${id}/tables`),
  table: (id, name, params, onProgress) => READ_ONLY
    ? staticFetch(`/api/instances/${id}/tables/${encodeURIComponent(name)}${qs(params)}`, {onProgress})
    : api.get(`/instances/${id}/tables/${encodeURIComponent(name)}`, params),
  scenarios: (id) => api.get(`/instances/${id}/scenarios`),
  scenario: (id, sid) => api.get(`/instances/${id}/scenarios/${sid}`),
  saveScenario: (id, sid, body) => api.put(`/instances/${id}/scenarios/${sid}`, body),
  createScenario: (id, body) => api.post(`/instances/${id}/scenarios`, body),
  seats: (id) => api.get(`/instances/${id}/seats`),
  saveSeats: (id, body) => api.put(`/instances/${id}/seats`, body),
  runs: (id) => api.get(`/instances/${id}/runs`),
  launchRun: (id, scenario, seed) => api.post(`/instances/${id}/runs`, { scenario, seed }),
  exploreScenario: (id, scenario) => api.post(`/instances/${id}/explorations`, { scenario }),
  explorationStatus: (id) => api.get(`/instances/${id}/exploration-status`),
  runFile: (id, sid, run, name, params = {}) => READ_ONLY
    ? staticFetch(`/api/instances/${id}/runs/${sid}/${run}/${name}${qs(Object.fromEntries(Object.entries(params).filter(([k]) => k !== "onProgress")))}`, {onProgress: params.onProgress})
    : api.get(`/instances/${id}/runs/${sid}/${run}/${name}`, Object.fromEntries(Object.entries(params).filter(([k]) => k !== "onProgress"))),
  evaluation: (id) => api.get(`/instances/${id}/evaluation`),
  results: (id) => api.get(`/instances/${id}/results`),
  insightsSummary: (id) => api.get(`/instances/${id}/insights-summary`),
  scenarioResults: (id) => api.get(`/instances/${id}/scenario-results`),
  insights: (id) => api.get(`/instances/${id}/insights`),
  buildInsights: (id, body) => api.post(`/instances/${id}/insights`, body || {}),
  report: (id) => api.get(`/instances/${id}/report`),
  concepts: (id) => api.get(`/instances/${id}/ontology/concepts`),
  people: (id, params) => api.get(`/instances/${id}/people`, params),
  peopleGraph: (id) => api.get(`/instances/${id}/people/graph`),
  peopleEgo: (id, pid, limit) => api.get(`/instances/${id}/people/${encodeURIComponent(pid)}/ego`, { limit }),
  onetOccupation: (code) => api.get(`/onet/occupations/${code}`),
  onetDwas: (q) => api.get(`/onet/dwas`, { q, limit: 25 }),
};
