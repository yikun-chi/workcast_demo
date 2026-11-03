/* The cross-scenario conclusions. Detailed evidence is loaded on demand. */
import {h, replace, errorState, loading, fmtNum} from '../components/ui.js';

export const value = (v, unit = '') => v == null ? '—' : unit === 'pp' ? `${fmtNum(v,{digits:2})} percentage points` : unit === '$m' ? `$${fmtNum(v, {digits: 1})}m` : `${fmtNum(v, {digits: unit === '%' || unit === 'pp' ? 2 : Math.abs(v) < 10 ? 2 : 0})}${unit === '%' ? '%' : unit ? ` ${unit}` : ''}`;
export async function render(root, ctx) {
  const body = h('div', null, loading('Loading insights')); root.append(body);
  let d;
  try { d = await ctx.api.insightsSummary(ctx.instanceId); } catch(e) { replace(body, errorState(e, ctx.instanceId, 'Insights')); return; }
  const p = d.primary;
  const diff = Math.abs(p.simulation - p.actual) - Math.abs(p.other - p.actual);
  const subject=p.subject.charAt(0).toUpperCase()+p.subject.slice(1);
  let verdict=`${subject}: the prediction is ${p.simulation > p.actual ? 'too high' : 'too low'}.`;
  let comparison=p.other == null ? '' : Math.abs(diff)<1e-8 ? 'Same prediction as the other method.' : diff<0 ? 'Closer to the actual outcome than the other prediction.' : 'The other prediction is closer to the actual outcome.';
  if(p.error){
    const improvement=100*(1-p.error.simulation/p.error.other);
    verdict=Math.abs(improvement)<0.01 ? `${subject}: no improvement over the other prediction.` : `${subject}: ${Math.abs(improvement).toFixed(0)}% ${improvement>0?'less':'more'} prediction error.`;
    comparison=`${p.error.scope}: simulation ${value(p.error.simulation,p.error.unit)} vs other prediction ${value(p.error.other,p.error.unit)}.`;
  }
  const shortOther = p.other_label.split(':')[0].replace(/ \(.*/, '');
  replace(body, h('div', {class:'page-head'}, h('div', null, h('div', {class:'muted small'}, ctx.instance.company), h('h1', null, 'Insights'), h('div', {class:'sub'}, ctx.instance.problem))),
    h('section', {class:'card insight-primary'}, h('div', {class:'kicker'}, 'Simulation vs actual outcome'), h('h2', null, verdict), h('p', {class:'small'},comparison), h('p', {class:'muted'}, p.label, p.averaged ? ' · average across prediction dates' : ''),
      h('div', {class:'insight-values'}, ...[['Actual outcome', p.actual, ''], ['Other prediction', p.other, shortOther], ['Simulation prediction', p.simulation, '']].map(([label,v,note]) => h('div', null, h('div', {class:'small muted'}, label), h('div', {class:'insight-number'}, value(v,p.unit)), h('div', {class:'small muted'}, note)))),
      h('p', {class:'evidence-note'}, d.caveat)),
    h('section', {class:'section insight-alternatives'}, h('div', {class:'row'}, h('h2', null, 'What changes under alternatives?'), h('span', {class:'muted small'}, 'Simulation comparisons · unobserved actions')),
      h('div', {class:'grid-2'}, ...d.alternatives.map(a => h('div', {class:'card'}, h('h3', null, a.title),
        ...a.metrics.filter(m => !m.reverse_delta || !a.metrics.some(x => x.is_change)).map(m => {
          const delta = m.is_change ? m.value : (m.value - m.reference) * (m.reverse_delta ? -1 : 1);
          const unit = m.unit === '%' && !m.is_change ? 'pp' : m.unit;
          return h('div', {class:'alternative-outcome'}, h('strong', null, Math.abs(delta) < (m.display_threshold || 0.05) ? 'Essentially unchanged' : `${delta > 0 && !m.is_change && !m.reverse_delta ? '+' : ''}${value(delta,unit)}`), h('span', null, m.label));
        }),
        h('details', {class:'compact-details'}, h('summary', null, 'Comparison details'), h('p', {class:'small muted'}, a.note), ...a.metrics.map(m => h('p', {class:'small'}, m.reverse_delta ? 'Human effort for the work performed' : m.label, ': ', m.is_change ? value(m.value,m.unit) : `${value(m.reference,m.unit)} → ${value(m.value,m.unit)}`))),
        a.id === 'ai_assistant' ? h('p',{class:'evidence-note'},'Assumed AI assistance; saved effort is not a measured cash saving.') : null,
        h('a', {class:'small', href:ctx.href(ctx.instanceId,'scenarios',a.id)}, 'View scenario →'))))));
  const evidenceBody = h('div', {class:'disclosure-body'});
  const details = h('details', {class:'disclosure'}, h('summary', null, 'Evidence, methods and all comparisons'), evidenceBody);
  let loaded = false;
  details.addEventListener('toggle', async () => {
    if (!details.open || loaded) return; loaded = true;
    replace(evidenceBody, loading());
    try {
      const mod = await import('./comparison_details.js');
      replace(evidenceBody);
      if (p.error) evidenceBody.append(h('p', {class:'small'}, `${p.error.scope}: simulation ${value(p.error.simulation,p.error.unit)}; other prediction ${value(p.error.other,p.error.unit)}. This averages individual errors, rather than comparing the average levels above.`));
      await mod.render(evidenceBody, ctx);
    } catch(e) { replace(evidenceBody,errorState(e)); loaded=false; }
  });
  body.append(details);
  if (ctx.params[0]) details.open = true;
}
