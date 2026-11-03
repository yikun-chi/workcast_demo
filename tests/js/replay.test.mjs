import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayBuilder} from '../../ui/data/replay.js';
import {tableReader} from '../../ui/data/query.js';
import {scopeCatalog} from '../../ui/data/scopes.js';
const columns=['tick','sim_time','agent_id','activity','action_type','attributes'];
const rows=[
 [48,'2020-01-03T00:00:00.000','p1','Invoice','complete','{"amount":42}'],
 [0,'2020-01-01T00:00:00.000','p10','Invoice','start','{}'],
 [0,'2020-01-01T00:00:00.000','p1','Invoice','start','{}'],
 [0,'2020-01-01T00:00:00.000','p1','Invoice','complete','{}'],
 [0,'2020-01-01T00:00:00.000','p1','Invoice','complete','{}'],
 [0,'2020-01-01T00:00:00.000','','Queue','state','{}']];
test('replay aggregates across chunk boundaries without fabricating quiet steps',()=>{
 const b=replayBuilder(columns);b.add(rows.slice(0,3));b.add(rows.slice(3));const d=b.finish();
 assert.equal(d.total,6);assert.deepEqual(d.frames.map(f=>f.tick),[0,48]);
 assert.deepEqual(d.frames.map(f=>f.total),[5,1]);assert.equal(d.frames[0].entities,2);
 assert.equal(d.frames[0].activities.reduce((n,a)=>n+a.count,0),5);
 assert.equal(d.frames[0].samples.length,3);
 assert.deepEqual(d.frames[0].activities.map(a=>[a.activity,a.action_type,a.count]),[['Invoice','complete',2],['Invoice','start',2],['Queue','state',1]]);
 assert.equal(d.frames[1].samples[0].attributes,'{"amount":42}');
});
test('entity replay uses exact IDs and handles empty or single-frame logs',()=>{
 const b=replayBuilder(columns,{agent:'p1'});b.add(rows);const d=b.finish();assert.equal(d.total,4);
 assert(d.frames.every(f=>f.entities===1));assert(d.frames.flatMap(f=>f.samples).every(r=>r.agent_id==='p1'));
 const empty=replayBuilder(columns,{agent:'absent'});empty.add(rows);assert.deepEqual(empty.finish(),{agent:'absent',org_unit:'',role:'',total:0,frames:[]});
 const one=replayBuilder(columns);one.add([rows[0]]);assert.equal(one.finish().frames.length,1);
});
test('preview cap never reduces the recorded counts',()=>{
 const b=replayBuilder(columns);b.add(Array.from({length:20},(_,i)=>[0,'2020-01-01','p'+i,'Activity '+i,'state','{}']));
 const f=b.finish().frames[0];assert.equal(f.total,20);assert.equal(f.entities,20);assert.equal(f.activities.length,20);assert.equal(f.samples.length,8);
});
test('clicking an activity can retrieve exactly its action and time',async()=>{
 const query=tableReader({name:'trace',columns,total:rows.length,chunk_size:3,chunks:['a','b']},async i=>rows.slice(i*3,i*3+3));
 const result=await query({agent:'p1',activity:'Invoice',action:'complete',from_tick:0,to_tick:0});
 assert.equal(result.total,2);assert(result.rows.every(r=>r.action_type==='complete'&&r.tick===0));
});

test('department and role scopes match event-time membership in replay and table',async()=>{
 const cols=[...columns,'org_unit','role'];
 const events=[
  [...rows[0],'IT','Engineer'],[...rows[1],'IT Ops','Engineer'],
  [...rows[2],'IT','Manager'],[...rows[3],'IT','Engineer'],
  [...rows[4],'Airfare','Engineer'],[...rows[5],'IT','Engineer']];
 const params={org_unit:'IT',role:'Engineer'};
 const b=replayBuilder(cols,params);b.add(events.slice(0,3));b.add(events.slice(3));
 const query=tableReader({name:'trace',columns:cols,total:events.length,chunk_size:3,chunks:['a','b']},async i=>events.slice(i*3,i*3+3));
 assert.equal(b.finish().total,3);assert.equal((await query(params)).total,3);
 assert(b.finish().frames.flatMap(f=>f.samples).every(r=>r.org_unit==='IT'&&r.role==='Engineer'));
 assert.equal((await query({...params,agent:'p1'})).total,2);
 assert.equal((await query({...params,role:'Manager'})).total,1); // filter cache must change
 const none=replayBuilder(cols,{...params,agent:'p10'});none.add(events);assert.equal(none.finish().total,0);
});

test('focus choices retain exact membership tuples, including movement between departments',()=>{
 const catalog=scopeCatalog([{id:'p1',label:'One'},{id:'p10',label:'Ten'},{id:'no-events',label:'No events'}],[
  {agent_id:'p1',org_unit:'IT',role:'Engineer'},
  {agent_id:'p1',org_unit:'Airfare',role:'Manager'},
  {agent_id:'p10',org_unit:'IT Ops',role:'Manager'},
  {agent_id:'system',org_unit:'IT',role:'Automated'},
  {agent_id:'',org_unit:'IT',role:'Unknown'}]);
 assert.deepEqual(catalog.members({org_unit:'IT',role:'Manager'}),[]);
 assert.deepEqual(catalog.members({org_unit:'IT',role:'Engineer'}).map(e=>e.id),['p1']);
 assert.deepEqual(catalog.options('role',{org_unit:'IT'}),['Automated','Engineer','Unknown']);
 assert(catalog.entities.some(e=>e.id==='system'));
 assert(catalog.members().some(e=>e.id==='no-events'));
 assert.equal(catalog.entities.length,4);
});
