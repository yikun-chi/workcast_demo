import {h, replace, titleCase} from './ui.js';
import {scopeCatalog} from '../data/scopes.js';

const readable = s => titleCase(String(s).replace(/^ou:/, '')).replace(/\bIt\b/g, 'IT').replace(/\bAp\b/g, 'AP');

export function historyFocus({entities, memberships, onChange}) {
  const catalog = scopeCatalog(entities, memberships);
  const kind = entities[0]?.kind || 'Entity';
  const entityLabel = kind==='App' && catalog.entities.some(e=>e.kind==='Recorded entity') ? 'App or system'
    : ['Person','App','Agency','Group','Worker or system'].includes(kind) ? kind : 'Entity';
  const unitLabel = kind === 'App' ? 'Category' : 'Department';
  const roleLabel = kind === 'App' ? 'App type' : 'Role';
  const groupsSupported = !['Agency','Group'].includes(kind);
  const units = groupsSupported ? catalog.options('org_unit') : [];
  const roles = groupsSupported ? catalog.options('role') : [];
  let filters = {org_unit:'',role:'',agent:''};
  const unit = h('select',{class:'select','aria-label':unitLabel,onChange:()=>{
    filters.org_unit=unit.value;filters.agent='';
    if(!catalog.options('role',{org_unit:unit.value}).includes(filters.role))filters.role='';
    commit();
  }});
  const role = h('select',{class:'select','aria-label':roleLabel,onChange:()=>{filters.role=role.value;filters.agent='';commit();}});
  const person = h('select',{class:'select','aria-label':'History entity',onChange:()=>{filters.agent=person.value;commit();}});
  const search = h('input',{class:'input',type:'search',placeholder:`Find ${entityLabel.toLowerCase()}…`,'aria-label':`Find ${entityLabel.toLowerCase()}`,onInput:drawPeople});
  const feedback = h('span',{class:'small muted',role:'status'});
  const summary = h('div',{class:'focus-summary',role:'status'});
  const reset = h('button',{class:'btn sm',onClick:()=>set({})},'Show whole simulation');
  const root = h('section',{class:'history-focus','aria-label':'Focus simulation history'},
    h('div',{class:'row',style:{justifyContent:'space-between'}},h('h4',null,'Zoom in'),reset),
    h('div',{class:'focus-fields'},
      units.length?h('label',{class:'stack'},unitLabel,unit):null,
      roles.length>1?h('label',{class:'stack'},roleLabel,role):null,
      h('label',{class:'stack'},entityLabel,person),
      h('label',{class:'stack'},'Search',search)),
    summary,feedback);
  function options(select, values, label, selected) {
    replace(select,h('option',{value:''},label),...values.map(v=>h('option',{value:v},readable(v))));select.value=selected;
  }
  function drawPeople() {
    const available=catalog.members(filters), query=search.value.trim().toLowerCase();
    const found=available.filter(e=>`${e.id} ${e.label} ${e.role || ''}`.toLowerCase().includes(query));
    const rows=available.filter(e=>e.id===filters.agent || found.includes(e));
    replace(person,h('option',{value:''},filters.org_unit || filters.role?'All in this focus':'Whole simulation'),
      ...rows.map(e=>h('option',{value:e.id},`${e.label}${e.role?` · ${readable(e.role)}`:''}`)));
    person.value=filters.agent;
    replace(feedback,query?`${found.length} matching ${entityLabel.toLowerCase()} ${found.length===1?'record':'records'}.`:'');
    reset.hidden=!Object.values(filters).some(Boolean)&&!search.value;
  }
  function commit() {
    options(unit,units,kind==='App'?'All categories':'All departments',filters.org_unit);
    options(role,catalog.options('role',{org_unit:filters.org_unit}),`All ${roleLabel.toLowerCase()}s`,filters.role);
    const available=catalog.members(filters);
    const entity=available.find(e=>e.id===filters.agent) || null;
    filters.agent=entity?.id || '';
    drawPeople();
    const label=[filters.org_unit&&readable(filters.org_unit),filters.role&&readable(filters.role),entity?.label].filter(Boolean).join(' → ') || 'Whole simulation';
    replace(summary,h('strong',null,label),h('span',{class:'small muted'},entity?'Following one saved entity':filters.org_unit||filters.role?`${available.length} named entities · matching recorded events`:'Animation and event table share this focus.'));
    reset.hidden=!Object.values(filters).some(Boolean)&&!search.value;
    onChange({entity,filters:{...filters},label});
  }
  function set(value) {filters={org_unit:'',role:'',agent:'',...value};search.value='';commit();}
  return {root,entityLabel,unitLabel,catalog,set,
    selectEntity(id) {
      const entity=catalog.entities.find(e=>e.id===id || e.id===`group:${id}`);
      const keepGroup=catalog.members(filters).some(e=>e.id===entity?.id);
      set({...(keepGroup?filters:{}),agent:entity?.id || ''});
    }
  };
}
