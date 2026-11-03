/* Build exact, ordered playback frames while streaming a saved trace. */
const compare = (a,b) => a < b ? -1 : a > b ? 1 : 0;
export function replayBuilder(columns, agent = '') {
  const index = Object.fromEntries(columns.map((key,i)=>[key,i]));
  const frames = new Map(); let total=0;
  return {
    add(rows) {
      for (const row of rows) {
        if(agent && row[index.agent_id] !== agent) continue;
        const tick=row[index.tick], time=row[index.sim_time], who=row[index.agent_id];
        if(!frames.has(tick)) frames.set(tick,{tick,time,total:0,entities:new Set(),groups:new Map()});
        const frame=frames.get(tick);frame.total++;total++;
        if(time < frame.time) frame.time=time;
        if(who) frame.entities.add(who);
        const activity=row[index.activity], action=row[index.action_type], key=JSON.stringify([activity,action]);
        if(!frame.groups.has(key))frame.groups.set(key,{activity,action_type:action,count:0,sample:row});
        frame.groups.get(key).count++;
      }
    },
    finish() {
      return {agent,total,frames:[...frames.values()].sort((a,b)=>a.tick-b.tick).map(frame=>{
        const groups=[...frame.groups.values()].sort((a,b)=>b.count-a.count || compare(a.activity,b.activity) || compare(a.action_type,b.action_type));
        return {tick:frame.tick,time:frame.time,total:frame.total,entities:frame.entities.size,
          activities:groups.map(({sample,...group})=>group),
          samples:groups.slice(0,8).map(group=>Object.fromEntries(columns.map((key,i)=>[key,group.sample[i]])))};
      })};
    }
  };
}
