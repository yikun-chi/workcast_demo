/* Input, bindings editor: the raw bindings of this instance (bindings.yaml as JSON): org units, locations, roles bound to
   O*NET occupations, activities mapped to DWAs, systems, capabilities, policies, latent states. Validated on save. */
import { h, replace, errorState, toast, debounce } from "../components/ui.js";

export async function render(root, { api, instanceId, refreshInstance }) {
  root.append(h("div", { class: "page-head" }, h("div", null, h("div", { class: "sub" }, "Edit the bindings that attach this company's roles, activities, systems and policies to the shared concepts. Keys: organization, org_units, locations, roles, persons, activities, process_edges, systems, artifacts, external_actors, relationships, policies, latent_states."))));
  const body = h("div", null); root.append(body);
  let b;
  try { b = await api.bindings(instanceId); } catch (e) { replace(body, errorState(e, instanceId, "Bindings")); return; }
  const ta = h("textarea", { class: "input", rows: 30, spellcheck: "false" }, JSON.stringify(b, null, 2));
  const status = h("div", null, h("span", { class: "muted small" }, "bindings.yaml shown as JSON; saving validates O*NET codes and DWA ids against the release."));
  const parseErr = h("div", null);
  ta.addEventListener("input", debounce(() => { try { JSON.parse(ta.value); replace(parseErr); ta.style.borderColor = ""; } catch (e) { replace(parseErr, h("div", { class: "error-box" }, `Invalid JSON: ${e.message}`)); ta.style.borderColor = "var(--bad)"; } }, 300));
  const saveBtn = h("button", { class: "btn primary", onClick: async () => {
    let doc; try { doc = JSON.parse(ta.value); } catch (e) { return toast(`Invalid JSON: ${e.message}`, "bad"); }
    saveBtn.disabled = true;
    try { const r = await api.saveBindings(instanceId, doc); replace(status, problemsBox(r.problems)); toast("Bindings saved", "good"); refreshInstance?.(); }
    catch (e) { replace(status, errorState(e)); }
    saveBtn.disabled = false;
  } }, "Save bindings");
  const fmtBtn = h("button", { class: "btn", onClick: () => { try { ta.value = JSON.stringify(JSON.parse(ta.value), null, 2); } catch (e) { toast(`Invalid JSON: ${e.message}`, "bad"); } } }, "Format");
  replace(body, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "12px" } }, status, h("div", { class: "row" }, fmtBtn, saveBtn)), parseErr, h("div", { class: "card tight" }, ta));
}

export function problemsBox(problems) {
  if (!problems || !problems.length) return h("div", { class: "badge good dot" }, "bindings validate");
  return h("div", { class: "warn-box" }, h("b", null, `${problems.length} problem${problems.length === 1 ? "" : "s"}`), h("ul", { style: { margin: "4px 0 0", paddingLeft: "18px" } }, ...problems.map(p => h("li", null, String(p)))));
}
