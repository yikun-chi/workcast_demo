/* Router + state for the orgsim shell. Hash routes: #/  |  #/<instance>/<page>[/<rest...>] */
import { api, FIXTURES } from "./api.js";
import { h, replace, badge, toast, errorState, loading, drawer } from "./components/ui.js";
import { sweepCharts, restyleCharts } from "./components/chart.js";

/* Seven core pages per instance. Editing lives inside Ontology and Data; the report, the scenario comparison and the
   instance's detailed views are all under Results; Insights holds the simulated interviews. */
export const CORE_PAGES = [
  { id: "results", label: "Results", mod: "./pages/results.js" },
  { id: "scenarios", label: "Scenarios", mod: "./pages/scenarios.js" },
  { id: "insights", label: "Insights", mod: "./pages/insights.js" },
  { id: "overview", label: "Overview", mod: "./pages/overview.js" },
  { id: "runs", label: "Runs", mod: "./pages/runs.js" },
  { id: "data", label: "Data", mod: "./pages/data.js", internals: true },
  { id: "ontology", label: "Ontology", mod: "./pages/ontology.js", internals: true },
];
const LEGACY = { edit: "ontology", report: "results" };

const state = { instances: null, instance: null, instanceId: null, cleanup: null, route: null };
const mods = new Map();
const VERSION = new URL(import.meta.url).searchParams.get("v") || "";   // set by the server from the UI files' mtime; defeats stale module caches
async function load(path) { if (!mods.has(path)) mods.set(path, import(VERSION ? `${path}?v=${VERSION}` : path)); return mods.get(path); }

export function navigate(hash) { location.hash = hash; }
export function href(instanceId, page, ...rest) { return `#/${[instanceId, page, ...rest].filter(x => x !== undefined && x !== null && x !== "").map(encodeURIComponent).join("/")}`; }

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean).map(decodeURIComponent);
  if (!parts.length) return { page: "landing" };
  return { instanceId: parts[0], page: parts[1] || "results", rest: parts.slice(2) };
}

async function getInstances(force) {
  if (!state.instances || force) state.instances = await api.instances();
  return state.instances;
}

function renderHeader() {
  const host = document.getElementById("header-instance");
  replace(host);
  if (!state.instanceId || !state.instances) return;
  const sel = h("select", { class: "select sm", title: "Switch instance", onChange: (e) => navigate(href(e.target.value, state.route.page === "landing" ? "results" : state.route.page)) },
    ...state.instances.map(i => h("option", { value: i.id, selected: i.id === state.instanceId }, i.company || i.title)));
  host.append(h("span", { class: "header-sep" }), h("span", { class: "muted small" }, "Company"), sel,
    state.instance?.world_type ? badge(state.instance.world_type, "accent") : null);
}

function renderTabs() {
  const tabs = document.getElementById("tabs");
  replace(tabs);
  if (!state.instanceId) return;
  for (const p of CORE_PAGES) {
    if (p.internals && !tabs.querySelector(".tab-sep")) tabs.append(h("span", { class: "tab-sep muted small", title: "The model behind the results: the data and the ontology" }, "model internals"));
    tabs.append(h("a", { class: `tab ${state.route.page === p.id ? "active" : ""}`, href: href(state.instanceId, p.id) }, p.label));
  }
}

async function render() {
  const route = parseRoute(); state.route = route;
  const main = document.getElementById("main");
  if (typeof state.cleanup === "function") { try { state.cleanup(); } catch (e) { console.warn(e); } }
  state.cleanup = null;
  drawer.close();
  main.className = "app-main";
  replace(main, loading());
  try {
    const instances = await getInstances();
    if (route.page === "landing") {
      state.instanceId = null; state.instance = null;
      renderHeader(); renderTabs();
      const mod = await load("./pages/landing.js");
      replace(main); state.cleanup = await mod.render(main, { api, instances, navigate, href });
    } else {
      if (state.instanceId !== route.instanceId || !state.instance) {
        state.instanceId = route.instanceId;
        try { state.instance = await api.instance(route.instanceId); }
        catch (e) { state.instance = instances.find(i => i.id === route.instanceId) || null; if (!state.instance) throw e; }
      }
      renderHeader(); renderTabs();
      document.title = `${state.instance.title} · Workcast`;
      const ctx = { api, instanceId: route.instanceId, instance: state.instance, instances, params: route.rest, page: route.page, navigate, href, refreshInstance: async () => { state.instance = await api.instance(route.instanceId); renderTabs(); return state.instance; } };
      if (LEGACY[route.page]) { navigate(href(route.instanceId, LEGACY[route.page])); return; }
      {
        const page = CORE_PAGES.find(p => p.id === route.page);
        if (!page) { replace(main, errorState(new Error(`Unknown page "${route.page}"`))); return; }
        const mod = await load(page.mod);
        replace(main); state.cleanup = await mod.render(main, ctx);
      }
    }
  } catch (e) {
    replace(main, errorState(e));
  } finally {
    setTimeout(sweepCharts, 50);
  }
}

// ---------- theme ----------
function initTheme() {
  const btn = document.getElementById("theme-toggle");
  const saved = new URLSearchParams(location.search).get("theme") || (() => { try { return localStorage.getItem("orgsim.theme"); } catch { return null; } })();
  document.documentElement.dataset.theme = saved || "dark";
  const label = () => { const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches); btn.textContent = dark ? "Light" : "Dark"; };
  label();
  btn.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("orgsim.theme", document.documentElement.dataset.theme); } catch { /* ignore */ }
    label(); restyleCharts();
    window.dispatchEvent(new CustomEvent("orgsim:theme"));
  });
}

function init() {
  initTheme();
  if (FIXTURES) replace(document.getElementById("fixture-badge"), badge("fixture data", "warn"));
  window.addEventListener("hashchange", render);
  window.addEventListener("error", (e) => { if (e.message) console.error("[orgsim]", e.message); });
  render();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
export { api, toast };
