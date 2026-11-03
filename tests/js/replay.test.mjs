import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayBuilder} from '../../ui/data/replay.js';
import {tableReader} from '../../ui/data/query.js';
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
 const b=replayBuilder(columns,'p1');b.add(rows);const d=b.finish();assert.equal(d.total,4);
 assert(d.frames.every(f=>f.entities===1));assert(d.frames.flatMap(f=>f.samples).every(r=>r.agent_id==='p1'));
 const empty=replayBuilder(columns,'absent');empty.add(rows);assert.deepEqual(empty.finish(),{agent:'absent',total:0,frames:[]});
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
