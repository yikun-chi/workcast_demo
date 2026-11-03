let worker, nextId = 0;
const pending = new Map();

export function queryTable(table, params, base, files, onProgress, operation = "query") {
  if (!worker) {
    worker = new Worker(new URL("./worker.js", import.meta.url), {type: "module"});
    worker.onmessage = ({data}) => {
      const request = pending.get(data.id);
      if (!request) return;
      if (data.progress) { request.onProgress?.(data.progress); return; }
      pending.delete(data.id);
      if (data.error) request.reject(new Error(data.error)); else request.resolve(data.result);
    };
    worker.onerror = () => {
      for (const request of pending.values()) request.reject(new Error("The data viewer could not load. Reload to retry."));
      pending.clear(); worker.terminate(); worker = null;
    };
  }
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject, onProgress});
    worker.postMessage({id, table, params, base, operation, checksums: table.chunks.map(path => files[path])});
  });
}

export const queryReplay = (table, params, base, files, onProgress) => queryTable(table, params, base, files, onProgress, "replay");
