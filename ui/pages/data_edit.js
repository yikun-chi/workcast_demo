/* Input, roles and people editor: roles with headcounts and O*NET codes, and the persons or archetypes declared in the bindings. */
import { h, replace, card, errorState, emptyState, toast, drawer, occupationDrawerBody, debounce } from "../components/ui.js";
import { problemsBox } from "./ontology_edit.js";

export async function render(root, { api, instanceId, refreshInstance }) {
  root.append(h("div", { class: "page-head" }, h("div", null, h("div", { class: "sub" }, "Edit the people-level data declared in the bindings: roles (with headcount and O*NET occupation) and persons or archetypes. The normalized tables themselves are produced by the ingest and are read-only here."))));
  const body = h("div", null); root.append(body);
  let b;
  try { b = await api.bindings(instanceId); } catch (e) { replace(body, errorState(e, instanceId, "Bindings")); return; }
  b.roles ||= []; b.persons ||= []; b.org_units ||= [];
  const status = h("div", null);
  const save = async () => {
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    try { const r = await api.saveBindings(instanceId, b); replace(status, problemsBox(r.problems)); toast("Bindings saved", "good"); refreshInstance?.(); }
    catch (e) { replace(status, errorState(e)); toast("Save failed", "bad"); }
    saveBtn.disabled = false; saveBtn.textContent = "Save";
  };
  const saveBtn = h("button", { class: "btn primary", onClick: save }, "Save");
  const unitOpts = () => b.org_units.map(u => u.id);
  const jsonInput = (value, onChange) => { const ta = h("textarea", { class: "input", rows: 2, style: { fontSize: "12px", minHeight: "32px" } }, JSON.stringify(value ?? {})); ta.addEventListener("input", debounce(() => { try { onChange(JSON.parse(ta.value || "{}")); ta.style.borderColor = ""; } catch { ta.style.borderColor = "var(--bad)"; } }, 300)); return ta; };
  const onetBtn = (getCode) => h("button", { class: "btn sm", title: "Look up this O*NET code", onClick: async () => { const c = getCode(); if (!c) return toast("Enter an O*NET-SOC code first (e.g. 43-3031.00)", "bad"); drawer.open(h("span", { class: "mono" }, c), await occupationDrawerBody(api, c)); } }, "O*NET");

  const rolesCard = card(null, null), personsCard = card(null, null);
  function drawRoles() {
    const tbl = h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Role id"), h("th", null, "Label"), h("th", null, "Org unit"), h("th", { class: "num" }, "Headcount"), h("th", null, "O*NET-SOC code"), h("th", null, "Attributes (JSON)"), h("th"))),
      h("tbody", null, ...b.roles.map((r, i) => h("tr", null,
        h("td", null, h("input", { class: "input sm mono", value: r.id || "", style: { width: "150px" }, onInput: (e) => { r.id = e.target.value; } })),
        h("td", null, h("input", { class: "input sm", value: r.label || "", style: { width: "180px" }, onInput: (e) => { r.label = e.target.value; } })),
        h("td", null, h("select", { class: "select sm", onChange: (e) => { r.org_unit = e.target.value || undefined; } }, h("option", { value: "" }, "–"), ...unitOpts().map(u => h("option", { value: u, selected: r.org_unit === u }, u)))),
        h("td", { class: "num" }, h("input", { class: "input sm num", type: "number", min: 0, value: r.headcount ?? "", style: { width: "80px" }, onInput: (e) => { r.headcount = e.target.value === "" ? undefined : +e.target.value; } })),
        h("td", null, h("div", { class: "row", style: { gap: "4px" } }, (() => { const inp = h("input", { class: "input sm mono", value: r.onet_code || "", placeholder: "43-3031.00", style: { width: "110px" }, onInput: (e) => { r.onet_code = e.target.value || null; } }); return [inp, onetBtn(() => inp.value.trim())]; })())),
        h("td", null, jsonInput(r.properties || {}, v => { r.properties = v; })),
        h("td", null, h("button", { class: "btn sm danger", onClick: () => { b.roles.splice(i, 1); drawRoles(); drawPersons(); } }, "Remove"))))));
    replace(rolesCard, h("div", { class: "card-title" }, h("span", null, `Roles (${b.roles.length})`), h("button", { class: "btn sm", onClick: () => { b.roles.push({ id: `role:new_${b.roles.length + 1}`, label: "New role", onet_code: null, headcount: 1 }); drawRoles(); } }, "+ Add role")),
      b.roles.length ? h("div", { class: "table-wrap" }, tbl) : emptyState("No roles yet.", "Add a role and bind it to an O*NET-SOC occupation."));
  }
  function drawPersons() {
    const tbl = h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Person / archetype id"), h("th", null, "Label"), h("th", null, "Role"), h("th", null, "Org unit"), h("th", null, "Attributes (JSON)"), h("th"))),
      h("tbody", null, ...b.persons.map((p, i) => h("tr", null,
        h("td", null, h("input", { class: "input sm mono", value: p.id || "", style: { width: "170px" }, onInput: (e) => { p.id = e.target.value; } })),
        h("td", null, h("input", { class: "input sm", value: p.label || "", style: { width: "190px" }, onInput: (e) => { p.label = e.target.value; } })),
        h("td", null, h("select", { class: "select sm", onChange: (e) => { p.role = e.target.value || undefined; } }, h("option", { value: "" }, "–"), ...b.roles.map(r => h("option", { value: r.id, selected: p.role === r.id }, r.label || r.id)))),
        h("td", null, h("select", { class: "select sm", onChange: (e) => { p.org_unit = e.target.value || undefined; } }, h("option", { value: "" }, "–"), ...unitOpts().map(u => h("option", { value: u, selected: p.org_unit === u }, u)))),
        h("td", null, jsonInput(p.properties || {}, v => { p.properties = v; })),
        h("td", null, h("button", { class: "btn sm danger", onClick: () => { b.persons.splice(i, 1); drawPersons(); } }, "Remove"))))));
    replace(personsCard, h("div", { class: "card-title" }, h("span", null, `Persons and archetypes (${b.persons.length})`), h("button", { class: "btn sm", onClick: () => { b.persons.push({ id: `person:new_${b.persons.length + 1}`, label: "New archetype", role: b.roles[0]?.id }); drawPersons(); } }, "+ Add person")),
      b.persons.length ? h("div", { class: "table-wrap" }, tbl) : emptyState("No persons or archetypes declared.", "Individuals come from the normalized population table; archetypes can be declared here."));
  }
  drawRoles(); drawPersons();
  replace(body, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "12px" } }, h("div", { class: "muted small" }, `Org units: ${b.org_units.length ? b.org_units.map(u => u.label || u.id).join(", ") : "none (add them in Input → Edit bindings)"}.`), h("div", { class: "row" }, status, saveBtn)),
    h("div", { class: "stack" }, rolesCard, personsCard));
}
