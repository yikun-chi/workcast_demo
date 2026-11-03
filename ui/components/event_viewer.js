/* Animated replay and a table are two views of the same saved event log. */
import {h,replace,loading,errorState,emptyState,drawer,fmtNum} from './ui.js';
import {dataGrid} from './grid.js';

const ACTIONS={arrive:'Arrived',decide:'Decision',start:'Started',complete:'Completed',handoff:'Handoff',state:'State update'};
const NAMES={wfh_takeup:'Home or office choice',latent_state:'Employee state update',weekly_tokens:'Weekly AI usage',model_mix:'Model usage mix','<END>':'End of work item'};
const nice=s=>NAMES[s] || String(s || 'Event').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const formatTime=time=>String(time || '').replace('T',' ').slice(0,16);
const fields=row=>{const out={...row};try{out.attributes=JSON.parse(out.attributes);}catch{}return out;};
let viewerId=0;

export function eventViewer({api,instanceId,run,emptyNote,onPlay}) {
  let entity=null, replayData=null, position=0, playing=false, timer=null, active=false, destroyed=false, generation=0, mode='animation';
  const cache=new Map();
  const id=`event-viewer-${++viewerId}`;
  const root=h('div',{class:'event-viewer'}), content=h('div',{id,role:'tabpanel'}), status=h('div',{class:'small muted',role:'status'});
  const animationTab=h('button',{id:`${id}-animation`,class:'btn sm active',role:'tab','aria-controls':id,'aria-selected':'true',onClick:()=>setMode('animation')},'Animation');
  const tableTab=h('button',{id:`${id}-table`,class:'btn sm',role:'tab','aria-controls':id,'aria-selected':'false',onClick:()=>setMode('table')},'Event table');
  const scope=h('span',{class:'small muted'},'Overall simulation');
  const tabs=h('div',{class:'row event-viewer-tabs',role:'tablist','aria-label':'Recorded event view'},animationTab,tableTab);
  root.append(h('div',{class:'row',style:{justifyContent:'space-between'}},tabs,scope),content);
  tabs.addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault();setMode(e.key==='Home'?'animation':e.key==='End'?'table':mode==='animation'?'table':'animation');
    (mode==='animation'?animationTab:tableTab).focus();
  });
  root.addEventListener('focusin',e=>{if(e.target.closest('.replay-activity,.replay-event'))pause();});

  const play=h('button',{class:'btn primary replay-play',disabled:true,onClick:()=>playing?pause():start()},'▶ Play');
  const previous=h('button',{class:'btn sm',disabled:true,'aria-label':'Previous recorded time',onClick:()=>seek(position-1)},'←');
  const next=h('button',{class:'btn sm',disabled:true,'aria-label':'Next recorded time',onClick:()=>seek(position+1)},'→');
  const restart=h('button',{class:'btn sm',disabled:true,onClick:()=>seek(0)},'Restart');
  const speed=h('select',{class:'select sm','aria-label':'Replay speed',onChange:()=>{if(playing){clearTimeout(timer);schedule();}}},
    ...[[1,'1×'],[2,'2×'],[4,'4×']].map(([v,label])=>h('option',{value:v},label)));
  const slider=h('input',{type:'range',min:0,max:0,value:0,disabled:true,'aria-label':'Recorded event time',onInput:()=>seek(Number(slider.value))});
  const clock=h('div',{class:'replay-clock'}), counts=h('div',{class:'replay-counts'}), gap=h('div',{class:'small muted replay-gap'});
  const timeline=h('div',{class:'replay-timeline'}), cursor=h('div',{class:'replay-cursor'}), activityBoard=h('div',{class:'replay-activities'}), feed=h('div',{class:'replay-feed'});
  const controls=h('div',{class:'row replay-controls'},play,previous,next,restart,h('span',{class:'spacer'}),h('label',{class:'row small'},'Speed',speed));
  const stage=h('div',{class:'replay-stage'},h('div',{class:'replay-stage-head'},
    h('div',null,h('div',{class:'kicker'},'Recorded simulation time'),clock,gap),counts),
    h('div',{class:'replay-track'},timeline,cursor,slider),
    h('div',{class:'row small muted',style:{justifyContent:'space-between'}},h('span',null,'Recorded steps · quiet gaps skipped'),h('span',{class:'replay-step'})),
    activityBoard);
  const animation=h('div',{class:'stack'},controls,status,stage,
    h('div',null,h('h4',null,'Event examples at this time'),h('p',{class:'small muted'},'Click an activity to see all its events, or an example to open the full record.'),feed),
    h('p',{class:'evidence-note'},'Playback of saved events. Activity pulses summarize recorded counts; they do not represent individual people or a new simulation.'));
  const table=h('div',{class:'stack'}), tableBody=h('div');
  const from=h('input',{class:'input sm',type:'number',min:0,placeholder:'From elapsed hour','aria-label':'From elapsed hour'});
  const to=h('input',{class:'input sm',type:'number',min:0,placeholder:'To elapsed hour','aria-label':'To elapsed hour'});
  let activity='',action='';
  const tableScope=h('p',{class:'small muted'});
  table.append(h('div',{class:'row'},from,to,h('button',{class:'btn sm',onClick:drawTable},'Apply time range'),
    h('button',{class:'btn sm',onClick:()=>{from.value='';to.value='';activity='';action='';drawTable();}},'Show all times')),tableScope,tableBody);

  function pause(){playing=false;clearTimeout(timer);timer=null;play.textContent=position===((replayData?.frames.length || 0)-1)?'↻ Replay':'▶ Play';root.classList.remove('is-playing');status.setAttribute('aria-live','polite');}
  function schedule(){timer=setTimeout(()=>{
    if(!playing || destroyed || !root.isConnected || globalThis.document.hidden){pause();return;}
    if(position>=replayData.frames.length-1){pause();return;}
    position++;drawFrame(true);
    if(position===replayData.frames.length-1)pause();else schedule();
  },900/Number(speed.value));}
  function start(){
    if(!replayData?.frames.length || destroyed)return;
    onPlay?.();if(position>=replayData.frames.length-1)position=0;
    playing=true;play.textContent='❚❚ Pause';root.classList.add('is-playing');status.setAttribute('aria-live','off');drawFrame(true);schedule();
  }
  function seek(value){position=Math.max(0,Math.min((replayData?.frames.length || 1)-1,value));pause();drawFrame(false);}
  function openRecord(row){pause();drawer.open('Recorded event',h('pre',{class:'code-block',style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},JSON.stringify(fields(row),null,2)));}
  function drawTimeline(){
    const ns='http://www.w3.org/2000/svg',svg=globalThis.document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 1000 48');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
    const frames=replayData.frames, max=frames.reduce((m,f)=>Math.max(m,f.total),1);
    // At most 250 bars; peaks summarize the denser native frame sequence.
    const bin=Math.max(1,Math.ceil(frames.length/250));
    for(let i=0;i<frames.length;i+=bin){
      const n=Math.max(...frames.slice(i,i+bin).map(f=>f.total)),height=3+43*Math.sqrt(n/max),rect=globalThis.document.createElementNS(ns,'rect');
      rect.setAttribute('x',1000*i/frames.length);rect.setAttribute('y',48-height);rect.setAttribute('width',Math.max(1,1000*bin/frames.length-1));rect.setAttribute('height',height);svg.append(rect);
    }
    replace(timeline,svg);slider.max=Math.max(0,frames.length-1);
  }
  function drawFrame(animate){
    const frame=replayData?.frames[position];if(!frame)return;
    stage.classList.toggle('animate-frame',animate);
    replace(clock,h('time',{dateTime:frame.time},formatTime(frame.time)));
    const elapsed=position?frame.tick-replayData.frames[position-1].tick:0;
    replace(gap,elapsed>1?`${fmtNum(elapsed)} hours since the previous recorded step`:'');
    replace(counts,h('div',null,h('strong',null,fmtNum(frame.total)),h('span',null,'recorded events')),h('div',null,h('strong',null,fmtNum(frame.entities)),h('span',null,'named entities')));
    slider.value=position;slider.setAttribute('aria-valuetext',formatTime(frame.time));cursor.style.left=`${replayData.frames.length>1?100*position/(replayData.frames.length-1):0}%`;
    replace(stage.querySelector('.replay-step'),`${position+1} / ${replayData.frames.length}`);
    previous.disabled=position===0;next.disabled=position===replayData.frames.length-1;restart.disabled=position===0;slider.disabled=replayData.frames.length<2;
    replace(activityBoard,...frame.activities.map((a,i)=>h('button',{class:'replay-activity','data-action':a.action_type,style:{animationDelay:`${Math.min(i,8)*35}ms`},onClick:()=>{
      pause();from.value=frame.tick;to.value=frame.tick;activity=a.activity;action=a.action_type;setMode('table');
    }},h('span',{class:'activity-pulse','aria-hidden':'true'}),h('span',{class:'activity-label'},h('strong',null,nice(a.activity)),h('span',{class:'small muted'},ACTIONS[a.action_type] || nice(a.action_type))),h('span',{class:'activity-count'},fmtNum(a.count)))));
    replace(feed,...frame.samples.map((row,i)=>{
      const attrs=fields(row).attributes;
      const summary=attrs && typeof attrs==='object' ? Object.entries(attrs).filter(([,v])=>typeof v==='number'||typeof v==='boolean'||typeof v==='string').slice(0,3).map(([k,v])=>`${nice(k)}: ${typeof v==='number'?fmtNum(v):String(v).slice(0,90)}`).join(' · ') : '';
      return h('button',{class:'replay-event',style:{animationDelay:`${i*35}ms`},onClick:()=>openRecord(row)},h('span',{class:'replay-event-dot','aria-hidden':'true'}),
        h('span',null,h('strong',null,nice(row.activity)),h('span',{class:'small muted'},`${row.agent_id || 'System'} · ${ACTIONS[row.action_type] || nice(row.action_type)}`),summary?h('span',{class:'small'},summary):null));
    }));
    replace(status,`${fmtNum(frame.total)} ${frame.total===1?'event':'events'} at this time · showing ${frame.samples.length} ${frame.samples.length===1?'example':'examples'}. ${entity?'Filtered to the selected entity.':''}`);
  }
  function drawTable(){
    replace(tableScope,`${entity?`Events for ${entity.label}`:'Events across the whole simulation'}${activity?` · ${nice(activity)} · ${ACTIONS[action] || nice(action)}`:''}.`);
    replace(tableBody,dataGrid({fetchPage:params=>api.runFile(instanceId,run.scenario,run.run_id,'trace',{...params,agent:entity?.id,from_tick:from.value,to_tick:to.value,activity,action}),pageSize:25,maxHeight:'480px',onRowClick:openRecord}));
  }
  function setMode(nextMode){
    pause();mode=nextMode;
    for(const [tab,name] of [[animationTab,'animation'],[tableTab,'table']]){tab.classList.toggle('active',mode===name);tab.setAttribute('aria-selected',String(mode===name));tab.tabIndex=mode===name?0:-1;}
    content.setAttribute('aria-labelledby',`${id}-${mode}`);
    replace(content,mode==='animation'?animation:table);
    if(active){if(mode==='table')drawTable();else if(replayData)drawFrame(false);else load();}
  }
  async function load(){
    const current=++generation;pause();replayData=null;position=0;
    play.disabled=true;previous.disabled=true;next.disabled=true;restart.disabled=true;slider.disabled=true;
    stage.hidden=true;feed.parentElement.hidden=true;replace(status,loading('Preparing recorded events'));
    const key=entity?.id || '';
    try{
      const result=cache.get(key) || await api.runFile(instanceId,run.scenario,run.run_id,'replay',{agent:key,onProgress:message=>{if(current===generation)replace(status,loading(message));}});
      if(destroyed || current!==generation)return;
      cache.set(key,result);while(cache.size>3)cache.delete(cache.keys().next().value);
      replayData=result;
      if(!result.frames.length){replace(status,emptyState('No recorded events for this selection.',emptyNote || 'This run saves aggregate state paths. Explore those in State trends below.'));return;}
      stage.hidden=false;feed.parentElement.hidden=false;play.disabled=result.frames.length<2;
      drawTimeline();drawFrame(false);
      if(result.frames.length===1)replace(status,`${fmtNum(result.total)} saved events at one recorded time. There are no later events to animate.`);
    }catch(error){if(current===generation && !destroyed)replace(status,errorState(error),h('button',{class:'btn sm',onClick:load},'Retry replay'));}
  }
  function visibility(){if(globalThis.document.hidden)pause();}
  globalThis.document.addEventListener('visibilitychange',visibility);
  setMode('animation');
  return {root,pause,
    activate(){if(!active){active=true;if(mode==='animation')load();else drawTable();}},
    setEntity(value){entity=value;replace(scope,entity?entity.label:'Overall simulation');generation++;pause();replayData=null;from.value='';to.value='';activity='';action='';if(active){if(mode==='animation')load();else drawTable();}},
    destroy(){destroyed=true;generation++;pause();globalThis.document.removeEventListener('visibilitychange',visibility);cache.clear();}
  };
}
