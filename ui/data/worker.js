import { tableReader } from "./query.js";

const readers = new Map();
self.onmessage = async ({data: {id, table, params, base, checksums}}) => {
  try {
    const key = base + JSON.stringify(table);
    if (!readers.has(key)) readers.set(key, tableReader(table, async number => {
      const path = table.chunks[number];
      const response = await fetch(new URL(path, base));
      if (!response.ok) throw new Error(`Cannot load table records (${response.status}). Reload to retry.`);
      const bytes = await response.arrayBuffer();
      const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(x => x.toString(16).padStart(2, "0")).join("");
      if (hash !== checksums[number]) throw new Error("The data snapshot changed. Reload the page to get the current version.");
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      return new Response(stream).json();
    }));
    while (readers.size > 2) readers.delete(readers.keys().next().value);
    const result = await readers.get(key)(params, message => self.postMessage({id, progress: message}));
    self.postMessage({id, result});
  } catch (e) { self.postMessage({id, error: e.message || String(e)}); }
};
