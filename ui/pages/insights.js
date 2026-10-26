/* Insights: simulated interviews with the agents of the baseline and the alternative run, about the key metrics.
   Topics, sentiment and key insights are extracted from each agent's simulated record. Reads runs/<id>/insights.json. */
import { h, replace, badge, card, errorState, loading, emptyState, toast, fmtNum, fmtDate, segmented } from "../components/ui.js";
import { chartCard, sweepCharts } from "../components/chart.js";

export async function render(root, ctx) {
  const { api, instanceId, href } = ctx;
  root.append(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Insights"), h("div", { class: "sub" }, "Explore how simulated employees experience each scenario. These are simulated perspectives, not real employee interviews."))));
  const body = h("div", null, loading("Loading insights")); root.append(body);
  let d = null;
  try { d = await api.insights(instanceId); } catch (e) { if (!e.notFound) { replace(body, errorState(e, instanceId, "Insights")); return; } }
  const st = { role: "baseline" };
  const selectScenario = () => { st.role = Object.entries(d?.scenarios || {}).find(([, b]) => b?.interviews && !b.error)?.[0] || "baseline"; };
  selectScenario();
  const regen = h("button", { class: "btn sm", onClick: async () => { regen.disabled = true; regen.textContent = "Interviewing…"; try { d = await api.buildInsights(instanceId, { n: 24 }); selectScenario(); toast("Insights rebuilt", "good"); draw(); } catch (e) { toast(e.message, "bad"); } regen.disabled = false; regen.textContent = "Re-interview"; } }, d ? "Re-interview" : "Interview the agents");
  if (!d) { replace(body, emptyState("No interviews yet.", h("span", null, "Interview the agents of the latest baseline and alternative runs. ", regen))); return; }

  function draw() {
    const blocks = Object.entries(d.scenarios || {}).filter(([, b]) => b && !b.error && b.interviews);
    const sel = h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "12px" } },
      h("div", { class: "row" }, segmented(Object.entries(d.scenarios || {}).map(([role, b]) => ({ id: role, label: `${role === "baseline" ? "Baseline" : "Alternative"}: ${b.title || b.scenario}` })), st.role, (id) => { st.role = id; draw(); }),
        badge(d.method === "template" ? "template voice" : d.method, d.method === "template" ? "" : "accent"), d.generated ? h("span", { class: "muted small" }, `generated ${fmtDate(d.generated)}`) : null),
      regen);
    const b = d.scenarios[st.role];
    replace(body, sel);
    if (!b || b.error || !b.interviews) { body.append(emptyState(`No interviews for the ${st.role}.`, b?.error || "Run the scenario first, then re-interview.")); return; }
    const runLink = b.run_id ? h("a", { href: href(instanceId, "runs", b.scenario, b.run_id) }, `run ${b.run_id}`) : null;
    body.append(h("div", { class: "row small muted", style: { marginBottom: "10px" } }, `${b.n_interviews} interviews from `, runLink, ` · groups: ${Object.entries(b.groups || {}).map(([g, n]) => `${g} ${n}`).join(", ")} · sentiment basis: ${b.sentiment_basis || ""}`));

    // key insights
    const ins = [...(b.key_insights || []), ...((st.role === "alternative" && d.comparison?.key_insights) || [])];
    body.append(h("div", { class: "section report", style: { maxWidth: "none" } }, h("h4", null, "Key insights"), ins.length ? h("ol", { class: "takeaways" }, ...ins.map((t, i) => h("li", null, h("span", { class: "n" }, String(i + 1).padStart(2, "0")), h("span", null, t)))) : h("div", { class: "muted small" }, "none")));

    // topics + sentiment charts
    const groups = Object.values(b.groups || {}).every(n => n >= 3) ? Object.keys(b.groups || {}) : [];
    const topics = (b.topics || []).slice(0, 12);
    const topicChart = { id: "topics", type: "hbar", title: "Topics raised, share of interviews", x: topics.map(t => t.label), x_label: "share of interviews", y_label: "",
      series: groups.length > 1 ? groups.map(g => ({ name: g, y: topics.map(t => t.by_group?.[g] ?? 0) })) : [{ name: "all interviews", y: topics.map(t => t.share) }] };
    const sent = b.sentiment?.distribution || {};
    const sentChart = { id: "sentiment", type: "bar", title: "Sentiment", x: ["negative", "neutral", "positive"], x_label: "", y_label: "interviews",
      series: groups.length > 1 ? groups.map(g => ({ name: g, y: ["negative", "neutral", "positive"].map(k => b.sentiment.by_group?.[g]?.[k] ?? 0) })) : [{ name: "all interviews", y: ["negative", "neutral", "positive"].map(k => sent[k] ?? 0) }] };
    const cmp = d.comparison && d.comparison.topics ? { id: "topics_cmp", type: "hbar", title: "Topics: baseline vs alternative (share of interviews)", x: d.comparison.topics.map(t => t.label), x_label: "share", y_label: "",
      series: [{ name: `baseline`, y: d.comparison.topics.map(t => t.baseline) }, { name: `alternative`, y: d.comparison.topics.map(t => t.alternative) }] } : null;
    const sentVaries = Object.values(sent).filter(v => v > 0).length > 1;
    body.append(h("details", { class: "disclosure", onToggle: () => window.dispatchEvent(new Event("resize")) }, h("summary", null, "Topics and sentiment"), h("div", { class: "disclosure-body grid-2" }, chartCard(topicChart, { tall: true }), sentVaries ? chartCard(sentChart) : null, cmp ? chartCard(cmp, { tall: true }) : null)));
    setTimeout(sweepCharts, 10);

    // interviews
    const list = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))" } });
    const SHOW = 3; let expanded = false;
    const moreBtn = b.interviews.length > SHOW ? h("button", { class: "btn sm", onClick: () => { expanded = !expanded; fill(); moreBtn.textContent = expanded ? "Show fewer" : `Show all ${b.interviews.length} interviews`; } }, `Show all ${b.interviews.length} interviews`) : null;
    function fill() { replace(list); for (const iv of (expanded ? b.interviews : b.interviews.slice(0, SHOW))) list.append(interviewCard(iv, b)); }
    fill();
    body.append(h("div", { class: "section" }, h("div", { class: "row", style: { justifyContent: "space-between" } }, h("h4", null, `Interviews (${b.interviews.length})`), moreBtn), list,
      h("div", { class: "muted small", style: { marginTop: "10px" } }, d.note || "", d.method === "template" ? " Answers are rendered from each agent's simulated record; a language-model voice over the same facts can be enabled with an API key." : "")));
  }
  function interviewCard(iv, b) {
    {
      return h("div", { class: "card" },
        h("div", { class: "row", style: { justifyContent: "space-between" } }, h("div", { class: "row" }, h("b", { class: "mono" }, iv.agent_id), badge(iv.role || "", "accent"), badge(iv.group || "")), badge(iv.sentiment, iv.sentiment === "negative" ? "warn" : iv.sentiment === "positive" ? "good" : "")),
        h("div", { class: "muted small", style: { margin: "4px 0 6px", lineHeight: "1.45" } }, iv.profile || "", iv.outcome ? h("span", null, " · ", h("b", null, iv.outcome)) : null),
        ...iv.qa.map(q => h("div", { class: "quote" }, h("div", { class: "q" }, q.question), h("div", null, q.answer), q.topics?.length ? h("div", { class: "row", style: { gap: "4px", marginTop: "4px" } }, ...q.topics.map(t => badge((b.topics || []).find(x => x.id === t)?.label || t))) : null)));
    }
  }
  draw();
}
