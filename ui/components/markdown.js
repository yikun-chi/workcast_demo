/* Markdown -> element via marked 12.x (global `marked` from cdnjs). Report content is first-party; scripts are stripped anyway. */
import { h } from "./ui.js";

export function renderMarkdown(md) {
  let html = "";
  try { html = typeof marked !== "undefined" ? marked.parse(String(md || ""), { gfm: true, breaks: false }) : escapeHtml(md); }
  catch (e) { html = `<pre>${escapeHtml(md)}</pre>`; }
  const el = h("div", { class: "md" });
  el.innerHTML = html;
  el.querySelectorAll("script, iframe, object, embed").forEach(n => n.remove());
  el.querySelectorAll("*").forEach(n => { for (const a of [...n.attributes]) if (/^on/i.test(a.name) || (a.name === "href" && /^javascript:/i.test(a.value))) n.removeAttribute(a.name); });
  el.querySelectorAll("a[href^='http']").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
  return el;
}
function escapeHtml(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
