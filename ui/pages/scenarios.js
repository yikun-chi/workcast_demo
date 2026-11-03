/* Scenarios: current policy and named alternatives. Click into one to run it or edit its
   parameters and which model sits in each seat. Other scenario files stay runnable from the CLI. */
import { h, replace, badge, card, errorState, loading, emptyState, toast, kv } from "../components/ui.js";

export async function render(root, ctx) {
  const { api, instanceId, instance, params, href, navigate } = ctx;
  let list;
  const body = h("div", null, loading()); root.append(body);
  try { list = await api.scenarios(instanceId); } catch (e) { replace(body, errorState(e, instanceId, "Scenarios")); return; }
  const shown = list.filter(s => s.role && s.role !== "other");
  const others = list.filter(s => !s.role || s.role === "other");
  if (params[0]) { const s = list.find(x => x.id === params[0]); if (s) { replace(body); await detail(body, ctx, s); return; } }
  replace(body);
  body.append(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Scenarios"), h("div", { class: "sub" }, "Choose a scenario to adjust staffing, work policy, or AI assistance. Save your assumptions and compare simulation predictions."))));
  if (!shown.length) { body.append(emptyState("No scenarios yet.", h("span", null, "Add ", h("code", null, `instances/${instanceId}/scenarios/baseline.yaml`), " and name it in instance.yaml under scenarios."))); return; }
  const resolved = await Promise.all(shown.map(s => api.scenario(instanceId, s.id).catch(() => null)));
  const runs = await api.runs(instanceId).catch(() => []);
  body.append(h("div", { class: "grid-2" }, ...shown.map((s, i) => heroCard(s, resolved[i], runs.filter(r => r.scenario === s.id), ctx))));
  if (others.length) body.append(h("details", { class: "muted small", style: { marginTop: "12px" } }, h("summary", null, "Additional scenario files"), `${others.length} more scenario file${others.length === 1 ? "" : "s"} (${others.map(o => o.id).join(", ")}) in instances/${instanceId}/scenarios stay available from the command line: orgsim run ${instanceId} --scenario <id>.`));
}

function heroCard(s, r, runs, ctx) {
  const { instanceId, href } = ctx;
  const isBase = s.role === "baseline";
  const complete = runs.filter(x => x.complete);
  const ivs = r?.interventions || [];
  return h("div", { class: `card instance-card scenario-hero ${isBase ? "" : "alt"}` },
    h("div", { class: "row", style: { justifyContent: "space-between" } }, badge(isBase ? "baseline: what actually happened" : "alternative", isBase ? "good" : "accent"), h("span", { class: "mono muted small" }, s.id)),
    h("h2", null, s.short_title || s.title || s.id),
    h("div", { class: "world" }, s.description || h("span", { class: "muted" }, "no description")),
    h("div", null, h("h4", null, isBase ? "No interventions" : `What changes (${ivs.length})`),
      ivs.length ? h("ul", { style: { margin: "4px 0 0", paddingLeft: "18px" }, class: "small" }, ...ivs.map(iv => h("li", null, describeIntervention(iv)))) : h("div", { class: "muted small" }, isBase ? "The reference world: real staffing, real arrivals, real policy." : "none")),
    h("details", { class: "small" }, h("summary", null, "Simulation details"), r?.horizon_days != null ? badge(`horizon ${r.horizon_days} d`) : null, r?.seeds ? badge(`seeds ${r.seeds.join(", ")}`) : null, badge(`${complete.length} completed run${complete.length === 1 ? "" : "s"}`)),
    h("div", { class: "row", style: { justifyContent: "space-between", marginTop: "6px" } },
      h("a", { class: "btn primary", href: href(instanceId, "scenarios", s.id) }, "Configure scenario →"),
      h("a", { class: "btn sm", href: href(instanceId, "results") }, "Saved results (precomputed) →")));
}

export function describeIntervention(iv) {
  if (typeof iv === "string") return iv;
  if (iv.type === "headcount_shift") return `Staffing: ${iv.multiplier} × current headcount (${iv.role === "all" ? "all roles" : iv.role})`;
  if (iv.type === "wfh_offer") return `Work from home: ${Array.isArray(iv.who) ? iv.who.map(w => whoLabel(w)).join(" and ") : whoLabel(iv.who)}; ${(iv.days || []).join(", ") || "no days"}`;
  if (iv.type === "ai_assist") return `AI assistance for ${(iv.activities || []).map(a => a.replaceAll("_", " ")).join(", ")}; ${Math.round(iv.coverage * 100)}% coverage, with human review and correction.`;
  const t = iv.type || "intervention";
  const rest = Object.entries(iv).filter(([k]) => !["type", "label"].includes(k)).map(([k, v]) => `${k} ${Array.isArray(v) ? v.join("/") : typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
  const nice = { wfh_offer: "Work-from-home offer", headcount_shift: "Headcount change", capacity: "Capacity change", automate: "Automation", delay: "Step duration", no_policy: "Policy withdrawn" }[t] || t;
  return h("span", null, h("b", null, iv.label || nice), rest ? h("span", { class: "muted" }, ` · ${rest}`) : null);
}

function whoLabel(who) {
  return { all: "everyone", treat: "employees offered hybrid work", control: "office-only employees", managers: "managers", nonmanagers: "non-managers" }[who] || who;
}

async function detail(body, ctx, s) {
  const { api, instanceId, href, navigate } = ctx;
  const isBase = s.role === "baseline";
  let r = null, seats = {}, bindings = {};
  try { r = await api.scenario(instanceId, s.id); } catch (e) { body.append(errorState(e)); return; }
  try { seats = (await api.seats(instanceId)) || {}; } catch { seats = {}; }
  try { bindings = (await api.bindings(instanceId)) || {}; } catch { bindings = {}; }
  body.append(h("div", { class: "page-head" },
    h("div", null, h("div", { class: "row small", style: { marginBottom: "4px" } }, h("a", { href: href(instanceId, "scenarios") }, "← Scenarios"), badge(isBase ? "baseline" : "alternative", isBase ? "good" : "accent"), h("span", { class: "mono muted" }, s.id)), h("h1", null, s.title || s.id), h("div", { class: "sub" }, s.description || ""))));

  // One draft backs both the plain-language controls and the advanced editor.
  const ta = h("textarea", { class: "input", rows: 16, spellcheck: "false", "aria-label": "Scenario JSON" }, JSON.stringify(r, null, 2));
  let savedDraft = ta.value;
  const editStatus = h("div", { class: "muted small", role: "status" }, "Configuration loaded. Saved results are from previous runs.");
  const controls = h("div", { class: "stack" });
  function changed() {
    replace(editStatus, ta.value === savedDraft ? "Configuration saved. Existing results are unchanged." : "Unsaved changes. Save before running. Existing results are unchanged.");
  }
  function drawControls() {
    let draft;
    try {
      draft = JSON.parse(ta.value);
      if (!draft || typeof draft !== "object" || Array.isArray(draft)) throw new Error("Expected an object");
    } catch {
      replace(controls, h("div", { class: "warn-box" }, "Fix the scenario JSON in Advanced parameters to use these controls."));
      return;
    }
    replace(controls);
    const interventions = Array.isArray(draft.interventions) ? draft.interventions : [];
    const editable = interventions.filter(iv => ["headcount_shift", "wfh_offer", "ai_assist"].includes(iv.type));
    // The baseline's WFH offer is a world policy, overridden by policy interventions.
    if (!draft.exploration && draft.world?.policy?.type === "wfh_offer" && !interventions.some(iv => ["wfh_offer", "no_policy"].includes(iv.type))) editable.unshift(draft.world.policy);
    const sync = () => { ta.value = JSON.stringify(draft, null, 2); changed(); };
    for (const iv of editable) {
      if (iv.type === "headcount_shift") {
        const amount = h("input", { class: "input", type: "number", min: 0, step: "any", value: iv.multiplier, onInput: () => {
          if (amount.value !== "" && amount.checkValidity()) { iv.multiplier = Number(amount.value); sync(); }
          else replace(editStatus, "Enter a staffing multiplier of zero or more before saving.");
        } });
        controls.append(h("label", { class: "stack" }, h("b", null, "Staffing multiplier"), amount,
          h("span", { class: "muted small" }, `1 means current staffing; 1.5 means 50% more people. Applies to ${iv.role === "all" ? "all roles" : iv.role}.`)));
        amount.required = true;
      } else if (iv.type === "ai_assist") {
        const labels = Object.fromEntries((bindings.activities || []).map(a => [a.id, a.label || a.id]));
        controls.append(h("p", { class: "small" }, "AI-assisted work: ", (iv.activities || []).map(a => labels[a] || a.replaceAll("_", " ")).join(", ")),
          h("p", { class: "muted small" }, draft.exploration?.assumption_basis || "These are exploratory assumptions, not measured AI outcomes."));
        const preview = h("div", { class: "small" });
        const updatePreview = () => {
          const factor = 1 - iv.coverage * (iv.time_saved - iv.review_overhead - iv.rework_rate * iv.rework_effort);
          replace(preview, `Across the selected tasks, modeled human effort is ${(100 * factor).toFixed(1)}% of current effort, including review and correction.`);
        };
        for (const [key, label, max, help] of [
          ["coverage", "Share of eligible work using AI (%)", 100, "The rest of the work uses the current process."],
          ["time_saved", "Task time saved before review (%)", 100, "Time saved on an assisted task, before checking or correcting the output."],
          ["review_overhead", "Human review effort (%)", 200, "Review time as a share of the task's usual effort without AI."],
          ["rework_rate", "Assisted tasks needing correction (%)", 100, "Corrections add effort before the task completes."],
          ["rework_effort", "Effort to correct a task (%)", 300, "100% means a correction takes as long as doing the original task without AI."]
        ]) {
          const input = h("input", { class: "input", type: "number", min: 0, max, step: "any", required: true,
            value: 100 * iv[key], "data-ai-parameter": key, onInput: () => {
              if (input.value !== "" && input.checkValidity()) { iv[key] = Number(input.value) / 100; sync(); updatePreview(); }
              else replace(editStatus, `Enter ${label.toLowerCase()} between 0 and ${max}.`);
            } });
          controls.append(h("label", { class: "stack" }, h("b", null, label), input, h("span", { class: "muted small" }, help)));
        }
        updatePreview(); controls.append(preview);
      } else {
        const choices = ["all", "treat", "control", "managers", "nonmanagers", ["treat", "nonmanagers"]];
        if (!choices.some(w => JSON.stringify(w) === JSON.stringify(iv.who))) choices.push(iv.who);
        const who = h("select", { class: "select", onChange: () => { iv.who = JSON.parse(who.value); sync(); } },
          ...choices.filter(w => w !== undefined).map(w => h("option", { value: JSON.stringify(w), selected: JSON.stringify(w) === JSON.stringify(iv.who) }, Array.isArray(w) ? w.map(whoLabel).join(" and ") : whoLabel(w))));
        const days = h("div", { class: "row" });
        const selected = new Set((iv.days || []).map(d => String(d).slice(0, 3).toLowerCase()));
        const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
        for (const day of weekdays) {
          const check = h("input", { type: "checkbox", checked: selected.has(day.toLowerCase()), onChange: () => {
            if (check.checked) selected.add(day.toLowerCase()); else selected.delete(day.toLowerCase());
            iv.days = weekdays.filter(d => selected.has(d.toLowerCase())); sync();
          } });
          days.append(h("label", { class: "row small" }, check, day));
        }
        controls.append(h("label", { class: "stack" }, h("b", null, "Who can work from home?"), who),
          h("fieldset", null, h("legend", null, "Work-from-home days"), days));
      }
    }
    if (!editable.length) controls.append(h("div", { class: "muted" }, interventions.length ? "This scenario uses additional settings available in Advanced parameters." : "Current operating conditions, with no added intervention. Full settings are available in Advanced parameters."));
  }
  ta.addEventListener("input", () => { changed(); drawControls(); });
  drawControls();
  const saveBtn = h("button", { class: "btn primary", onClick: async () => {
    for (const input of controls.querySelectorAll("input")) if (!input.reportValidity()) return;
    let d;
    try {
      d = JSON.parse(ta.value);
      if (!d || typeof d !== "object" || Array.isArray(d)) throw new Error("Scenario must be a JSON object");
    } catch (e) { return toast(`Invalid JSON: ${e.message}`, "bad"); }
    const submitted = ta.value;
    saveBtn.disabled = true;
    try { await api.saveScenario(instanceId, s.id, d); savedDraft = submitted; changed(); toast("Scenario saved. Existing results are unchanged.", "good"); }
    catch (e) { toast(e.message, "bad"); }
    saveBtn.disabled = false;
  } }, "Save scenario");

  // ---- run
  const seed = h("input", { class: "input sm", type: "number", value: (r?.seeds || [1])[0] ?? 1, min: 0, style: { width: "80px" }, title: "Seed" });
  const status = h("div", { class: "small muted" });
  const runBtn = h("button", { class: "btn primary", onClick: async () => {
    for (const input of controls.querySelectorAll("input")) if (!input.reportValidity()) return;
    if (ta.value !== savedDraft || saveBtn.disabled) return toast("Save your scenario changes before running.", "bad");
    runBtn.disabled = true; replace(status, h("span", { class: "spinner", style: { width: "12px", height: "12px" } }), " launching…");
    try {
      const before = new Set((await api.runs(instanceId)).map(x => `${x.scenario}/${x.run_id}`));
      const res = await api.launchRun(instanceId, s.id, +seed.value);
      toast(`Run launched for ${s.id} (seed ${res.seed})`, "good");
      replace(status, h("span", { class: "spinner", style: { width: "12px", height: "12px" } }), ` running (pid ${res.pid ?? "?"})… waiting for the run to appear`);
      const t0 = Date.now(); let found = null;
      while (Date.now() - t0 < 300000) {
        await new Promise(rs => setTimeout(rs, 2000));
        const runs = await api.runs(instanceId);
        found = runs.find(x => x.scenario === s.id && !before.has(`${x.scenario}/${x.run_id}`));
        if (found && found.complete) break;
        if (found) replace(status, h("span", { class: "spinner", style: { width: "12px", height: "12px" } }), ` run ${found.run_id} in progress…`);
      }
      if (found) replace(status, badge(found.complete ? "complete" : "started", found.complete ? "good dot" : "warn dot"), " ", h("a", { href: href(instanceId, "runs", s.id, found.run_id) }, `Open run ${found.run_id} →`));
      else replace(status, h("span", { class: "warn-box" }, "No new run appeared within 5 minutes. Check runs/<id>/<scenario>/launch.log."));
    } catch (e) { replace(status, errorState(e)); }
    runBtn.disabled = false;
  } }, "Run ▶");
  const runs = (await api.runs(instanceId).catch(() => [])).filter(x => x.scenario === s.id);
  const compareStatus = h("div", { class: "small muted", role: "status" });
  const isExploration = !!r?.exploration;
  async function watchComparison(jobId) {
    try {
      while (body.isConnected) {
        const job = await api.explorationStatus(instanceId);
        if (job.job_id !== jobId) { replace(compareStatus, "Another comparison has started. Check the saved results when it finishes."); break; }
        if (job.state === "complete") {
          replace(compareStatus, badge("Comparison complete", "good"), " ", h("a", { href: href(instanceId, "results", s.id) }, "View AI comparison →"));
          break;
        }
        if (job.state === "failed") { replace(compareStatus, job.error || "Comparison failed. Check your assumptions and retry."); break; }
        replace(compareStatus, "Comparing matched simulations. This can take several minutes; you can leave this page and return later.");
        await new Promise(resolve => setTimeout(resolve, 5000));
      }
    } catch (e) { replace(compareStatus, errorState(e)); }
    compareBtn.disabled = false;
  }
  const compareBtn = h("button", { class: "btn primary", onClick: async () => {
    for (const input of controls.querySelectorAll("input")) if (!input.reportValidity()) return;
    if (ta.value !== savedDraft || saveBtn.disabled) return toast("Save your assumptions before comparing.", "bad");
    compareBtn.disabled = true;
    try { const job = await api.exploreScenario(instanceId, s.id); watchComparison(job.job_id); }
    catch (e) { replace(compareStatus, errorState(e)); compareBtn.disabled = false; }
  } }, "Compare with current policy");
  body.append(card("Configure scenario", h("div", { class: "stack" },
    controls,
    h("div", { class: "row" }, saveBtn, isExploration ? compareBtn : runBtn),
    editStatus, isExploration ? compareStatus : status,
    h("div", { class: "muted small" }, isExploration ? "Compare uses the saved assumptions and matching reference simulations, then updates the AI comparison in Results." : "Run uses the saved configuration. Saving or running does not refresh the precomputed Results report."),
    h("a", { href: isExploration ? href(instanceId, "results", s.id) : href(instanceId, "results") }, "View saved results →"))));
  if (isExploration) {
    const job = await api.explorationStatus(instanceId).catch(() => null);
    if (job?.scenario === s.id && ["queued", "running"].includes(job.state)) { compareBtn.disabled = true; watchComparison(job.job_id); }
  }
  body.append(h("details", { class: "section" }, h("summary", null, "Run details: seed and history"),
    card("Run settings and history", h("div", { class: "stack" },
      h("label", { class: "row small" }, "Random seed", seed),
      isExploration ? h("div", { class: "row" }, runBtn, status) : null,
      runs.length ? h("div", { class: "table-wrap", style: { maxHeight: "200px" } }, h("table", { class: "table" },
        h("thead", null, h("tr", null, h("th", null, "Run"), h("th", null, "Status"), h("th", { class: "num" }, "Events"))),
        h("tbody", null, ...runs.slice(0, 12).map(x => h("tr", null,
          h("td", { class: "mono" }, h("a", { href: href(instanceId, "runs", x.scenario, x.run_id) }, x.run_id)),
          h("td", null, badge(x.complete ? "complete" : "running", x.complete ? "good dot" : "warn dot")),
          h("td", { class: "num" }, x.summary?.events ?? "–")))))) : h("div", { class: "muted small" }, "No runs yet.")))));
  body.append(h("details", { class: "section" }, h("summary", null, "Advanced parameters: full scenario JSON"),
    card("Edit parameters", h("div", { class: "stack" },
      h("div", { class: "muted small" }, `The resolved scenario as JSON. Saving writes ${s.id}.yaml. These settings and the controls above share the same draft; use Save scenario above to save either.`),
      ta, r?.world ? kv(r.world) : null))));

  // ---- seats
  seats.default ||= { adapter: "rule" }; seats.seats ||= {};
  const seatCard = card(null, null);
  const ADAPTERS = ["rule", "llm", "local"];
  const MODELS = { llm: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"], local: ["orgsim-ft-v1", "llama-3.1-8b-instruct", "qwen2.5-7b-instruct"], rule: [] };
  const roleIds = (bindings.roles || []).map(x => x.id);
  const seatStatus = h("div", null);
  function seatRow(name, cfg, onRemove) {
    const adapterSel = h("select", { class: "select sm", onChange: () => { cfg.adapter = adapterSel.value; if (cfg.adapter === "rule") { delete cfg.model; delete cfg.base_url; } else if (!cfg.model) cfg.model = MODELS[cfg.adapter][0]; draw(); } }, ...ADAPTERS.map(a => h("option", { value: a, selected: (cfg.adapter || "rule") === a }, a)));
    const modelList = h("datalist", { id: `models-${name.replace(/\W/g, "_")}` }, ...(MODELS[cfg.adapter || "rule"] || []).map(m => h("option", { value: m })));
    const modelInp = h("input", { class: "input sm mono", list: modelList.id, value: cfg.model || "", placeholder: cfg.adapter === "rule" ? "n/a (rule-based)" : "model id", disabled: (cfg.adapter || "rule") === "rule", style: { width: "190px" }, onInput: (e) => { cfg.model = e.target.value; } });
    const urlInp = h("input", { class: "input sm mono", value: cfg.base_url || "", placeholder: "http://localhost:8000/v1/chat/completions", style: { width: "280px", display: cfg.adapter === "local" ? "" : "none" }, onInput: (e) => { cfg.base_url = e.target.value; } });
    const prompt = h("textarea", { class: "input", rows: 2, placeholder: "system prompt (llm/local)", style: { width: "280px", minHeight: "30px", display: cfg.adapter === "rule" ? "none" : "" }, onInput: (e) => { cfg.system_prompt = e.target.value; } }, cfg.system_prompt || "");
    return h("tr", null,
      h("td", null, h("span", { class: "mono" }, name), name === "default" ? h("div", { class: "muted small" }, "fallback for every seat") : null),
      h("td", null, adapterSel), h("td", null, modelInp, modelList), h("td", null, h("div", { class: "stack", style: { gap: "4px" } }, urlInp, prompt)),
      h("td", null, badge(cfg.adapter === "llm" ? "hosted LLM" : cfg.adapter === "local" ? "local model" : "rule", cfg.adapter === "llm" ? "accent" : cfg.adapter === "local" ? "warn" : "")),
      h("td", null, onRemove ? h("button", { class: "btn sm danger", onClick: onRemove }, "Remove") : null));
  }
  function draw() {
    const names = Object.keys(seats.seats);
    const addSel = h("select", { class: "select sm" }, h("option", { value: "" }, "add seat for role…"), ...roleIds.filter(x => !names.includes(x)).map(x => h("option", { value: x }, x)), h("option", { value: "__custom" }, "custom seat id…"));
    addSel.addEventListener("change", () => { let id = addSel.value; if (id === "__custom") id = prompt("Seat id (role id, team, or executive):") || ""; if (!id) return; seats.seats[id] = { adapter: "llm", model: MODELS.llm[0] }; draw(); });
    const save = h("button", { class: "btn primary", onClick: async () => { save.disabled = true; try { await api.saveSeats(instanceId, seats); toast("Seats saved", "good"); replace(seatStatus, badge("saved", "good dot")); } catch (e) { replace(seatStatus, errorState(e)); } save.disabled = false; } }, "Save seats");
    replace(seatCard, h("div", { class: "card-title" }, h("span", null, "Seats: which model acts in each role"), h("div", { class: "row" }, seatStatus, addSel, save)),
      h("div", { class: "muted small", style: { marginBottom: "8px" } }, "Shared by every scenario of this instance (policies/seats.yaml). Every seat follows the same interface (observe → decide → propose); the kernel validates and applies. A hosted or local model falls back to the rule policy when it fails, and the fallback is recorded in the trace."),
      h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Seat"), h("th", null, "Adapter"), h("th", null, "Model"), h("th", null, "Endpoint / prompt"), h("th", null, "Kind"), h("th"))),
        h("tbody", null, seatRow("default", seats.default), ...names.map(n => seatRow(n, seats.seats[n], () => { delete seats.seats[n]; draw(); }))))));
  }
  draw();
  body.append(h("details", { class: "section" }, h("summary", null, "Model seats: advanced configuration"), seatCard));
}
