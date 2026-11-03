/* Voices belong to a specific saved run, never a comparison between runs. */
import {h, replace, badge} from './ui.js';
import {chartCard} from './chart.js';
export function scenarioInterviews(item, onEntity, canOpen = () => true) {
  const b = item.interviews;
  if (!b?.interviews?.length) return h('p', {class:'muted small'}, item.interview_note || 'No simulated interviews were saved for this run.');
  const list = h('div', {class:'grid-2'});
  let expanded = false;
  function draw() {
    replace(list, ...(expanded ? b.interviews : b.interviews.slice(0,3)).map(iv => h('article', {class:'card'},
      h('div', {class:'row'}, canOpen(iv.agent_id) ? h('button', {class:'btn sm', onClick:()=>onEntity(iv.agent_id)}, iv.agent_id) : h('strong',null,iv.agent_id), badge(iv.role || iv.group || 'Simulated entity')),
      h('p', {class:'small muted'}, iv.profile || '', iv.outcome ? ` · ${iv.outcome}` : ''),
      ...iv.qa.map(q=>h('div', {class:'quote'}, h('div', {class:'q'},q.question),h('div',null,q.answer))))));
  }
  draw();
  const topics = b.topics || [];
  return h('div', {class:'stack'}, h('p', {class:'evidence-note'}, 'Simulated interviews generated from this run’s records. These are not statements by real people.'),
    ...(b.key_insights || []).map(t=>h('p', {class:'small'},t)), list,
    b.interviews.length > 3 ? h('button', {class:'btn sm', onClick:e=>{expanded=!expanded;draw();e.target.textContent=expanded?'Show fewer':`Show all ${b.interviews.length} interviews`;}},`Show all ${b.interviews.length} interviews`) : null,
    h('details', null, h('summary', null, 'Topics and sentiment'),
      chartCard({type:'hbar', title:'Topics raised in simulated interviews',x:topics.map(t=>t.label),x_label:'Share of interviews',series:[{name:'Share',y:topics.map(t=>t.share)}]}),
      h('p', {class:'small muted'}, `Sentiment: ${Object.entries(b.sentiment?.distribution || {}).map(([key,n])=>`${key} ${n}`).join(' · ')}. ${b.sentiment_basis || ''}`)),
    h('p', {class:'muted small'}, item.interview_note || ''));
}
