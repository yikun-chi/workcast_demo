/* One scenario, one saved run. Cross-scenario comparisons live in Insights. */
import {h, replace, badge, loading, errorState, emptyState, kv} from '../components/ui.js';
import {chartCard, sweepCharts} from '../components/chart.js';
import {eventViewer} from '../components/event_viewer.js';
import {scenarioInterviews} from '../components/scenario_interviews.js';
import {value} from './insights.js';

const disclosure = (title, body) => h('details', {class:'disclosure',onToggle:()=>window.dispatchEvent(new Event('resize'))}, h('summary',null,title),h('div',{class:'disclosure-body'},body));
const json = d => h('pre',{class:'code-block',style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},JSON.stringify(d,null,2));
function metrics(items) { return h('div',{class:'result-metrics'},...items.filter(m=>m.value!=null).map(m=>h('div',{class:'card'},h('div',{class:'small muted'},m.label),h('div',{class:'result-number'},value(m.value,m.unit))))); }
function plot(path, onSelect) {
  const card=chartCard({type:'line',title:path.label,x:path.times,y_label:path.unit,series:[{name:path.label,y:path.values}]}, {options:{animation:false,onClick:(_e,points)=>{if(points.length) onSelect?.(points[0].index);}}});
  const chart=card.querySelector('canvas')?._chart;
  chart?.data.datasets.forEach(dataset=>{dataset.tension=0;dataset.spanGaps=false;});
  chart?.update('none');
  return card;
}
export async function render(root, ctx) {
  const body=h('div',null,loading('Loading saved scenarios'));root.append(body);
  let catalog;
  try {catalog=await ctx.api.scenarioResults(ctx.instanceId);} catch(e){replace(body,errorState(e,ctx.instanceId,'Results'));return;}
  const item=catalog.find(x=>x.scenario.id===ctx.params[0]);
  if(ctx.params[0] && !item){replace(body,emptyState('Scenario not found.',h('a',{href:ctx.href(ctx.instanceId,'results')},'Choose a scenario')));return;}
  if(!item){
    replace(body,h('div',{class:'page-head'},h('div',null,h('h1',null,'Results'),h('div',{class:'sub'},'Choose a scenario to inspect its metrics, history and simulated interviews.'))),
      h('div',{class:'grid-2'},...catalog.map(x=>h('article',{class:'card scenario-result-card'},badge(x.scenario.role==='baseline'?'Reference scenario':'Alternative'),h('h2',null,x.scenario.display_title || x.scenario.short_title),h('p',{class:'muted'},x.scenario.card_summary),
        h('a',{class:'btn',href:ctx.href(ctx.instanceId,'results',x.scenario.id)},x.run?'View results →':'View status →')))));
    return;
  }
  const run=ctx.params[1] ? {...item.run,scenario:item.scenario.id,run_id:ctx.params[1]} : item.run;
  replace(body,h('a',{href:ctx.href(ctx.instanceId,'results')},'← Results'),h('div',{class:'page-head'},h('div',null,h('h1',null,item.scenario.display_title || item.scenario.short_title),h('div',{class:'sub'},'Scenario results · one saved simulation run'))));
  if(!run){body.append(emptyState('No completed run yet.',h('a',{href:ctx.href(ctx.instanceId,'scenarios',item.scenario.id)},'Open scenario')));return;}
  let d;
  const pending=loading('Loading metrics and history');body.append(pending);
  try {d=await ctx.api.runFile(ctx.instanceId,run.scenario,run.run_id,'history');}catch(e){replace(pending,errorState(e));return;}
  pending.remove();
  body.append(h('p',{class:'small muted'},`${String(d.start || '').slice(0,10)} → ${String(d.end || '').slice(0,10)}. ${d.note}`),metrics(d.metrics));
  let timer=null, selected=null, step=0, zoom=false;
  const history=h('div',{class:'stack'}), historySection=disclosure('Explore simulation history',history);
  const entityView=h('div',{class:'stack'}), trendHost=h('div'), snapshot=h('div',{role:'status','aria-live':'polite'});
  const choose=h('select',{class:'select','aria-label':'History entity'},h('option',{value:''},'Overall simulation'),...d.entities.map(e=>h('option',{value:e.id},`${e.label}${e.role ? ` · ${e.role}` : ''}`)));
  const slider=h('input',{type:'range',min:0,max:0,value:0,'aria-label':'Simulation time',style:{width:'100%'}});
  const play=h('button',{class:'btn sm'},'Play trend');
  const zoomButton=h('button',{class:'btn sm'},'Zoom around selected step');
  function paths(){return selected?.series || d.series;}
  function stop(){clearInterval(timer);timer=null;play.textContent='Play trend';}
  function visibility(){if(document.hidden)stop();}
  document.addEventListener('visibilitychange',visibility);
  function showStep(){
    const ps=paths(), time=ps[0]?.times[step];
    replace(snapshot,h('strong',null,time || 'No time series saved'),h('div',{class:'row small'},...ps.map(p=>h('span',null,`${p.label}: ${value(p.values[step],p.unit)}`))));
    slider.value=step;
    const position=zoom ? step-Math.max(0,step-3) : step;
    trendHost.querySelectorAll('canvas').forEach(canvas=>{
      const chart=canvas._chart;if(!chart?.ctx)return;
      chart.data.datasets.forEach(dataset=>{dataset.pointRadius=dataset.data.map((_,i)=>i===position?7:0);dataset.pointBorderWidth=2;});chart.update('none');
    });
  }
  function drawTrends(){
    replace(trendHost,...paths().map(p=>{
      const start=zoom?Math.max(0,step-3):0,end=zoom?Math.min(p.times.length,step+4):p.times.length;
      const chart=plot({...p,times:p.times.slice(start,end),values:p.values.slice(start,end)},i=>{step=start+i;showStep();});
      chart.addEventListener('dblclick',()=>{zoom=true;zoomButton.textContent='Show full history';drawTrends();});
      return chart;
    }));
    if(!paths().length) trendHost.append(h('p',{class:'muted'},'No state series was saved for this entity. Inspect its recorded events above.'));
    showStep();sweepCharts();
  }
  function select(id){
    stop(); selected=d.entities.find(e=>e.id===id || e.id===`group:${id}`) || null;choose.value=selected?.id || '';step=0;zoom=false;zoomButton.textContent='Zoom around selected step';
    slider.max=Math.max(0,(paths()[0]?.times.length || 1)-1);slider.disabled=!paths().length;play.disabled=Number(slider.max)===0;zoomButton.disabled=Number(slider.max)<2;
    replace(entityView,selected?metrics(selected.metrics):null, selected?disclosure('Entity details · all saved fields',json(selected.details)):null);
    showStep();drawTrends();
    replay.setEntity(selected);
  }
  choose.addEventListener('change',()=>select(choose.value));
  slider.addEventListener('input',()=>{stop();step=+slider.value;showStep();if(zoom)drawTrends();});
  play.addEventListener('click',()=>{replay.pause();if(timer){stop();return;}if(step>=Number(slider.max))step=0;play.textContent='Pause trend';timer=setInterval(()=>{if(!historySection.open || !historySection.isConnected || step>=Number(slider.max)){stop();return;}step++;showStep();if(zoom)drawTrends();},700);});
  zoomButton.addEventListener('click',()=>{zoom=!zoom;zoomButton.textContent=zoom?'Show full history':'Zoom around selected step';drawTrends();});
  history.append(h('p',{class:'small muted'},'Replay recorded activity for the whole simulation or choose one entity.'),h('label',{class:'stack'},'Entity',choose),entityView);
  const replay=eventViewer({api:ctx.api,instanceId:ctx.instanceId,run,onPlay:stop,
    emptyNote:d.trace_rows===0?'This run saves group-level paths rather than an event log. Explore the saved paths in State trends below.':undefined});
  const events=disclosure(`Recorded events · ${d.trace_rows.toLocaleString()} across the full run`,replay.root);events.open=true;
  const stateDetails=disclosure('State trends and snapshots',h('div',{class:'stack'},h('p',{class:'small muted'},'Saved state values at the model’s recorded resolution. Click a chart point to select it, or double-click to zoom.'),h('div',{class:'row'},play,zoomButton),slider,snapshot,trendHost));
  history.append(events,stateDetails);
  historySection.addEventListener('toggle',()=>{if(historySection.open && events.open)replay.activate();else replay.pause();if(!historySection.open)stop();});
  events.addEventListener('toggle',()=>{if(historySection.open && events.open)replay.activate();else replay.pause();});
  stateDetails.addEventListener('toggle',()=>{if(!stateDetails.open)stop();});
  // The first trend is visible immediately, with drilldown kept one click away.
  if(d.series[0]){
    const overview=plot(d.series[0],i=>{historySection.open=true;stateDetails.open=true;select('');step=i;showStep();stateDetails.scrollIntoView({behavior:'smooth',block:'start'});});
    overview.append(h('button',{class:'btn sm',onClick:()=>{historySection.open=true;historySection.scrollIntoView({behavior:'smooth',block:'start'});}},'Explore time and entities →'));
    body.append(overview);
  }
  body.append(historySection);select('');
  const matching=d.raw_metrics?.separations
    ? {...item,interviews:null,interview_note:'Employee interviews are unavailable for this agency-level model. The saved legacy cohort voices do not describe the agency separation paths shown here.'}
    : item.run?.run_id===run.run_id?item:{...item,interviews:null,interview_note:'No simulated interviews were saved for this run.'};
  body.append(disclosure('Simulated interviews',scenarioInterviews(matching,id=>{historySection.open=true;select(id);historySection.scrollIntoView({behavior:'smooth',block:'start'});},id=>d.entities.some(e=>e.id===id || e.id===`group:${id}`))),
    disclosure('All metrics and saved configuration',h('div',{class:'stack'},kv({run:run.run_id,seed:d.seed}),disclosure('Metrics',json(d.raw_metrics)),disclosure('Configuration',json(d.configuration)))),
    h('p',{class:'small'},h('a',{href:ctx.href(ctx.instanceId,'scenarios',item.scenario.id)},'View scenario assumptions →')));
  return ()=>{stop();document.removeEventListener('visibilitychange',visibility);replay.destroy();sweepCharts();};
}
