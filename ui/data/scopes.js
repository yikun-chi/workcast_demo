/* Match event-time membership tuples, never separate department/role sets. */
export function scopeCatalog(entities, memberships = []) {
  const byId = new Map(entities.map(e => [e.id, e]));
  for (const row of memberships) {
    if (row.agent_id && !byId.has(row.agent_id)) byId.set(row.agent_id, {
      id: row.agent_id, label: row.agent_id, kind: 'Recorded entity', role: row.role,
      metrics: [], series: [], details: {agent_id: row.agent_id}
    });
  }
  const matches = (row, filters) => ['org_unit', 'role'].every(k => !filters[k] || row[k] === filters[k]);
  return {
    entities: [...byId.values()],
    options(field, filters = {}) {
      return [...new Set(memberships.filter(row => matches(row, filters)).map(row => row[field]).filter(Boolean))].sort();
    },
    members(filters = {}) {
      if (!filters.org_unit && !filters.role) return [...byId.values()];
      const ids = new Set(memberships.filter(row => matches(row, filters)).map(row => row.agent_id));
      return [...byId.values()].filter(e => ids.has(e.id));
    }
  };
}
