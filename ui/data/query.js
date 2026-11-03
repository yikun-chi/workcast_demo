/* Static table queries. Paging reads only needed chunks; searches/sorts scan every
   row in a worker and retain row positions, never the entire table in memory. */
export function tableReader(table, loadChunk) {
  const cache = new Map();
  let indexedKey = null, indexed = null;
  async function chunk(number) {
    if (!cache.has(number)) {
      const pending = Promise.resolve(loadChunk(number)).catch(e => { cache.delete(number); throw e; });
      cache.set(number, pending);
    }
    const result = await cache.get(number);
    cache.delete(number); cache.set(number, Promise.resolve(result));
    while (cache.size > 8) cache.delete(cache.keys().next().value);
    return result;
  }
  async function index(q, sort, desc, filters, progress) {
    const key = JSON.stringify([q, sort, desc, filters]);
    if (indexedKey === key) return indexed;
    const matches = [], sortValues = [];
    const column = table.columns.indexOf(sort);
    for (let c = 0; c < table.chunks.length; c++) {
      const rows = await chunk(c);
      for (let r = 0; r < rows.length; r++) {
        const row = rows[r];
        const selected = Object.entries(filters).every(([key, value]) => {
          if (key === "from_tick") return row[table.columns.indexOf("tick")] >= Number(value);
          if (key === "to_tick") return row[table.columns.indexOf("tick")] <= Number(value);
          return String(row[table.columns.indexOf({agent: "agent_id", case: "case_id", activity: "activity"}[key])]) === String(value);
        });
        if (selected && (!q || row.some(v => String(v ?? "").toLowerCase().includes(q)))) {
          matches.push(c * table.chunk_size + r);
          if (column >= 0) sortValues.push(row[column]);
        }
      }
      progress?.(`Searching and sorting records: ${Math.round((c + 1) / table.chunks.length * 100)}%`);
    }
    let positions = matches;
    if (column >= 0) {
      const order = Array.from({length: matches.length}, (_, i) => i);
      order.sort((a, b) => {
        const x = sortValues[a], y = sortValues[b];
        if (x === y) return a - b;
        if (x == null) return 1;
        if (y == null) return -1;
        return (x < y ? -1 : 1) * (desc ? -1 : 1);
      });
      positions = order.map(i => matches[i]);
    }
    indexedKey = key; indexed = positions;
    return positions;
  }
  return async (params = {}, progress) => {
    const offset = Math.max(0, Number(params.offset) || 0);
    const limit = Math.max(1, Math.min(1000, Number(params.limit) || 50));
    const q = String(params.q || "").toLowerCase(), sort = params.sort || "";
    const desc = params.desc === 1 || params.desc === "1" || params.desc === true;
    const filters = Object.fromEntries(["agent", "case", "activity", "from_tick", "to_tick"].filter(k => params[k] !== undefined && params[k] !== null && params[k] !== "").map(k => [k, params[k]]));
    const positions = q || sort || Object.keys(filters).length ? await index(q, sort, desc, filters, progress) : null;
    const total = positions ? positions.length : table.total;
    const chosen = positions ? positions.slice(offset, offset + limit) : Array.from({length: Math.max(0, Math.min(limit, total - offset))}, (_, i) => offset + i);
    const chunks = new Map();
    for (const p of chosen) {
      const c = Math.floor(p / table.chunk_size);
      if (!chunks.has(c)) chunks.set(c, await chunk(c));
    }
    const rows = chosen.map(p => Object.fromEntries(table.columns.map((name, col) => [name, chunks.get(Math.floor(p / table.chunk_size))[p % table.chunk_size][col]])));
    return {name: table.name, columns: table.columns, total, offset, limit, rows};
  };
}
