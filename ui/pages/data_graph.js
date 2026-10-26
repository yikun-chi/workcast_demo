/* Data, Graph view: the data of this instance as a graph. Left: the people (normalized input rows, paged from
   /api/instances/{id}/people). Right: the structure (the organisation, its units and teams, roles, locations, systems,
   activities and policies from the bindings, plus the O*NET vocabulary behind the roles) or, once a person is selected,
   that person's neighbourhood (teammates in a workforce world, hand-off partners in a process world). */
import { h, replace, badge, card, kv, errorState, loading, fmtNum } from "../components/ui.js";
import { graphViewer, typeColor, TYPE_STYLE } from "../components/graph.js";
import { dataGrid } from "../components/grid.js";

export async function render(root, ctx) {
  const { api, instanceId, instance, params, href } = ctx;
  const peopleHref = (...rest) => href(instanceId, "data", "people", ...rest);
  const st = { instanceId, personId: params?.[0] || null, graph: null, bind: null, group: null, viewer: null, mode: "structure", ego: null, hidden: new Set(["GWA", "IWA", "DWA", "Task", "Occupation", "Capability", "Artifact"]) };
  let destroyed = false;

  root.append(h("div", { class: "page-head" },
    h("div", null, h("div", { class: "sub" }, "The data as a graph: the organisation and everything bound to it on the right, the people on the left. Click a person for their own network; rows are the normalized input data, connections come from the data (teams, hand-offs), not from runs."))));

  const stats = h("div", { class: "statsbar", style: { marginBottom: "10px" } });
  const left = h("div", { class: "stack" });
  const canvas = h("div", { class: "onto-canvas people-canvas" });
  const typeBar = h("div", { class: "row small", style: { gap: "4px" } });
  const detail = card("Selection", h("div", { class: "muted small" }, "Click a person in the table to see their connections, or a division, team or role in the graph to list its members."));
  const right = h("div", { class: "stack" }, typeBar, canvas, detail);
  root.append(stats, h("div", { class: "people-layout" }, left, right));

  const overlay = h("div", { style: { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 5, background: "var(--surface)" } }, loading("Loading"));
  canvas.append(overlay);
  try { st.viewer = graphViewer(canvas, { onSelect: onNodeTap }); } catch (e) { replace(canvas, errorState(e)); return; }

  try { st.graph = await api.peopleGraph(st.instanceId); } catch (e) { replace(overlay, errorState(e, st.instanceId, "People")); replace(left, errorState(e, st.instanceId, "People")); return; }
  try { st.bind = await api.ontology(st.instanceId, false); } catch { st.bind = null; }
  if (destroyed) return;
  const g = st.graph;
  const groupById = Object.fromEntries(g.groups.map(x => [x.id, x]));
  const colLabels = Object.fromEntries(g.columns.map(c => [c.id, c.label]));
  overlay.style.display = "none";

  replace(stats, badge(`${fmtNum(g.persons_total)} people`, "accent"),
    ...Object.entries(g.stats.groups_by_type || {}).map(([t, n]) => badge(`${n} ${t === "OrgUnit" ? "units/teams" : t.toLowerCase() + (n === 1 ? "" : "s")}`)),
    ...(g.person_links || []).map(pl => badge(`${fmtNum(pl.count)} ${pl.type} links`, "")),
    h("span", { class: "muted small", style: { marginLeft: "6px" } }, g.notes?.[0] || ""));

  // ---------- people table ----------
  const gridHost = h("div", null);
  const filterBar = h("div", { class: "row small", style: { minHeight: "22px" } });
  left.append(card("People", h("div", { class: "stack", style: { gap: "6px" } }, filterBar, gridHost)));
  function buildGrid() {
    const grp = st.group ? groupById[st.group] : null;
    replace(filterBar, grp ? h("span", { class: "row" }, h("span", { class: "muted" }, "Filtered to"), badge(`${grp.label} (${fmtNum(grp.size)})`, "accent"), h("a", { href: "#", onClick: (e) => { e.preventDefault(); st.group = null; buildGrid(); showStructure(); } }, "clear")) : h("span", { class: "muted" }, `All ${fmtNum(g.persons_total)} people. Click a row for the person's connections.`));
    replace(gridHost, dataGrid({
      columns: g.columns.map(c => c.id), columnLabels: colLabels, pageSize: 25, maxHeight: "calc(100vh - 360px)", exportName: `${st.instanceId}_people`,
      fetchPage: ({ offset, limit, q, sort, desc }) => api.people(st.instanceId, { offset, limit, q, sort, desc, group: st.group || "" }),
      onRowClick: (r) => selectPerson(r.person_id), isSelected: (r) => r.person_id === st.personId,
      render: { managerial: (v) => v ? "yes" : "no", children_ind: (v) => v ? "yes" : "no", grad: (v) => v ? "yes" : "no", volunteer: (v) => v ? "yes" : "no", female: (v) => v == null ? "" : v ? "yes" : "no" },
    }));
  }
  buildGrid();

  // ---------- structure graph ----------
  function structureGraph() {
    // bindings entity graph (organisation, units, locations, roles, activities, systems, policies, O*NET) merged with the data-layer teams
    const title = instance?.company || instance?.title || st.instanceId;
    const bind = st.bind || { nodes: [], edges: [] };
    const orgId = (bind.nodes.find(n => n.type === "Organization") || {}).id || "org:root";
    const nodes = bind.nodes.length ? bind.nodes.map(n => ({ ...n })) : [{ id: orgId, type: "Organization", label: title, properties: {} }];
    const edges = bind.edges.map(e => ({ ...e }));
    const have = new Set(nodes.map(n => n.id));
    for (const x of g.groups) {
      const props = { kind: x.kind, size: x.size, ...(x.properties || {}) };
      if (have.has(x.id)) { const n = nodes.find(y => y.id === x.id); n.properties = { ...(n.properties || {}), ...props }; continue; }
      nodes.push({ id: x.id, type: x.type, label: x.kind === "team" ? x.id : x.label, properties: props }); have.add(x.id);
    }
    const seen = new Set(edges.map(e => `${e.source}|${e.type}|${e.target}`));
    for (const l of g.links) { const k = `${l.source}|${l.type}|${l.target}`; if (!seen.has(k) && have.has(l.source) && have.has(l.target)) { edges.push({ source: l.source, target: l.target, type: l.type, properties: {} }); seen.add(k); } }
    for (const x of g.groups) if (!x.parent && x.type === "OrgUnit" && !seen.has(`${x.id}|part_of|${orgId}`)) edges.push({ source: x.id, target: orgId, type: "part_of", properties: {} });
    return { nodes, edges };
  }
  function renderTypeBar(graph) {
    const counts = {}; for (const n of graph.nodes) counts[n.type] = (counts[n.type] || 0) + 1;
    const types = Object.keys(TYPE_STYLE).filter(t => counts[t]);
    replace(typeBar, h("span", { class: "muted" }, "show:"), ...types.map(t => { const on = !st.hidden.has(t); return h("label", { class: "check", style: { gap: "4px", opacity: on ? 1 : 0.55 } }, h("input", { type: "checkbox", checked: on, onChange: (e) => { if (e.target.checked) st.hidden.delete(t); else st.hidden.add(t); st.viewer.setTypeVisibility(st.hidden); st.viewer.runLayout(); renderTypeBar(graph); } }), h("span", { class: "sw", style: { display: "inline-block", width: "9px", height: "9px", borderRadius: "2px", background: typeColor(t) } }), `${t} ${counts[t]}`); }));
  }
  function showStructure() {
    st.mode = "structure"; st.ego = null;
    const sg = structureGraph();
    st.viewer.setData(sg); st.viewer.setTypeVisibility(st.hidden); st.viewer.runLayout(); st.viewer.setEdgeLabels(false); renderTypeBar(sg);
    const grp = st.group ? groupById[st.group] : null;
    if (grp) showGroup(grp); else replace(detail.lastChild, h("div", { class: "stack small" },
      h("div", null, "Structure: the organisation, its units and teams (size = headcount), roles, locations, systems, activities and policies. Click a unit, team or role to list its members; click a person in the table for their own network. O*NET vocabulary is hidden by default (toggle above)."),
      h("div", { class: "row", style: { gap: "4px" } }, ...(g.person_links || []).map(pl => h("span", { class: "badge" }, `${pl.type}: ${fmtNum(pl.count)} links, ${pl.basis}`))),
      ...(g.notes || []).slice(1).map(n => h("div", { class: "muted" }, n))));
  }
  function showGroup(grp) {
    st.group = grp.id; buildGrid();
    replace(detail.lastChild, h("div", { class: "stack" },
      h("div", { class: "row" }, badge(grp.type, ""), badge(grp.kind), h("span", { class: "mono small muted" }, grp.id)),
      h("h3", { style: { margin: 0 } }, grp.label),
      kv({ members: grp.size, parent: grp.parent ? (groupById[grp.parent]?.label || grp.parent) : "", location: grp.location || undefined, ...(grp.properties || {}) }, { skip: [] }),
      h("div", { class: "muted small" }, "The table on the left now lists this group's members.")));
  }

  // ---------- person (ego network) ----------
  async function selectPerson(pid) {
    st.personId = pid; st.mode = "ego";
    history.replaceState(null, "", peopleHref(pid));
    replace(detail.lastChild, loading(`Loading ${pid}`));
    let ego;
    try { ego = await api.peopleEgo(st.instanceId, pid, 60); } catch (e) { replace(detail.lastChild, errorState(e)); return; }
    if (destroyed || st.personId !== pid) return;
    st.ego = ego;
    st.viewer.setData(ego); st.viewer.setTypeVisibility(new Set()); st.viewer.setEdgeLabels(true); st.viewer.select(pid); replace(typeBar, h("span", { class: "muted" }, `network of ${pid}`));
    buildGrid();
    const p = ego.person || {};
    const attrs = {}; for (const c of g.columns) if (p[c.id] !== undefined && p[c.id] !== null && c.id !== "person_id") attrs[c.label] = p[c.id];
    const cons = ego.connections || [];
    const isProcess = g.world_type === "process";
    replace(detail.lastChild, h("div", { class: "stack" },
      h("div", { class: "row", style: { justifyContent: "space-between" } }, h("div", { class: "row" }, badge("Person", ""), h("h3", { style: { margin: 0 } }, pid), p.role_label ? badge(p.role_label, "accent") : null), h("button", { class: "btn sm", onClick: () => { st.personId = null; history.replaceState(null, "", peopleHref()); buildGrid(); showStructure(); } }, "← Structure")),
      kv(attrs),
      h("h4", null, `Connections (${fmtNum(ego.connections_total ?? cons.length)})`),
      h("div", { class: "muted small" }, isProcess ? "Hand-off partners: how often a purchase-order item passed between this user and the other (to = this user handed off to them)." : "Teammates (same_manager): the people in the same team, who share the manager and the weekly comparison."),
      cons.length ? h("div", { class: "table-wrap", style: { maxHeight: "260px" } }, h("table", { class: "table" },
        h("thead", null, h("tr", null, h("th", null, "Person"), h("th", null, "Role"), isProcess ? h("th", { style: { textAlign: "right" } }, "hand-offs") : h("th", null, "Arm"), isProcess ? h("th", { style: { textAlign: "right" } }, "to / from") : null)),
        h("tbody", null, ...cons.map(c => h("tr", { style: { cursor: "pointer" }, onClick: () => selectPerson(c.person_id) },
          h("td", { class: "mono" }, c.person_id), h("td", null, c.role || ""), isProcess ? h("td", { class: "mono", style: { textAlign: "right" } }, fmtNum(c.weight)) : h("td", null, c.arm || ""), isProcess ? h("td", { class: "mono muted", style: { textAlign: "right" } }, `${fmtNum(c.to)} / ${fmtNum(c.from)}`) : null))))) : h("div", { class: "muted small" }, "No connections in the data."),
      ego.connections_total > cons.length ? h("div", { class: "muted small" }, `Showing the ${cons.length} strongest of ${fmtNum(ego.connections_total)}.`) : null));
  }

  function onNodeTap(node) {
    if (!node) return;
    if (node.type === "Person") { if (node.id !== st.personId) selectPerson(node.id); return; }
    if (groupById[node.id]) { if (st.mode === "structure") showGroup(groupById[node.id]); return; }
    if (st.mode === "structure") replace(detail.lastChild, h("div", { class: "stack" }, h("div", { class: "row" }, badge(node.type, ""), h("span", { class: "mono small muted" }, node.id)), h("h3", { style: { margin: 0 } }, node.label), kv(node.properties || {})));
  }

  if (st.personId) await selectPerson(st.personId); else showStructure();
  root._people = st;
  return () => { destroyed = true; try { st.viewer?.destroy(); } catch { /* ignore */ } };
}
