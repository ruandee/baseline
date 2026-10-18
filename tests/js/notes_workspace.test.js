/* Offline controller tests: actual app.js, scoped synthetic responses, held requests. */
'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../../frontend/app.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const held = () => { let resolve; const promise = new Promise(r => {resolve=r;}); return {promise,resolve}; };
function element() {
  return {value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,dataset:{},attrs:{},children:[],listeners:{},
    classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},
    addEventListener(k,f){this.listeners[k]=f;},querySelector(){return null;},remove(){},
    focus(){this.focused=true;},scrollIntoView(){},close(){this.open=false;},showModal(){this.open=true;},
    append(...nodes){this.children.push(...nodes);}};
}
const patient = id => ({id,name:'Synthetic '+id,reference:'ref-'+id,questions:['What changed?']});
const session = patients => ({token:'synthetic-token',as_of:'2026-01-02T08:00:00Z',patients});
const timeline = events => ({events,next_cursor:null,memory_revision:4,coverage:{index_complete:true}});
const answer = text => ({status:'partial',claims:[{text,section:'recent_changes',epistemic_status:'documented',evidence_ids:['e1']}],
  evidence:[{evidence_id:'e1'}],unknowns:[{topic:'sleep',reason:'missing_documentation'}],conflicts:[],
  coverage:{index_complete:true},as_of:'2026-01-02T08:00:00Z',known_at:'2026-01-02T08:00:00Z',memory_revision:4,versions:{model:'stub'}});
function page(route, people=[patient('p1'),patient('p2')], search='') {
  const nodes=new Map(); const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const filters=['all','nursing_note','patient_report','observation','medication_event'].map(f=>({...element(),dataset:{filter:f}}));
  const tabs=element(), filterList=element(), listeners={}; const calls=[];
  const document={getElementById:get,querySelector:s=>s==='.filters'?filterList:tabs,
    querySelectorAll:()=>filters,addEventListener:(k,f)=>(listeners[k]||=[]).push(f),createElement:element};
  const fetch=async(url,opts={})=>{calls.push({url,opts});let data=await route(url,opts);
    if(data===undefined)data=url==='/demo/session'?session(people):timeline([]);
    return {ok:data.ok!==false,status:data.status||200,json:async()=>data};};
  vm.runInNewContext(code,{document,fetch,URLSearchParams,Intl,Date,window:{location:{search},matchMedia:()=>({matches:false})}});
  return {get,calls,filters,tabs,filterList,clickRetry(name){
    const target={closest:s=>s==='[data-retry]'?{dataset:{retry:name}}:null};
    (listeners.click||[]).forEach(f=>f({target}));
  },select(id){get('patients').listeners.click({target:{closest:()=>({dataset:{patient:id}})}});}};
}

test('timeline filter includes medication events; tabs implement roving keyboard focus',async()=>{
  const h=page(url=>url.includes('/timeline')?timeline([
    {quote:'Medication mentioned, not an order.',source_kind:'medication_event',evidence_id:'e1'},
    {quote:'Resident reported sleep.',source_kind:'patient_report',evidence_id:'e2'}]):undefined);
  await tick();await tick();
  const button=h.filters.find(f=>f.dataset.filter==='medication_event');
  h.filterList.listeners.click({target:{closest:()=>button}});
  assert(h.get('timeline').innerHTML.includes('Medication mentioned, not an order.'));
  assert(!h.get('timeline').innerHTML.includes('Resident reported sleep.'));
  h.tabs.listeners.keydown({key:'End',preventDefault(){}});
  assert.equal(h.get('handover-tab').attrs.tabindex,'0');
  assert.equal(h.get('timeline-tab').attrs.tabindex,'-1');
  assert.equal(h.get('handover-tab').focused,true);
  assert.equal(h.get('timeline-view').hidden,true);
});

test('held question cannot paint after switching resident; request preserves bearer and cutoff',async()=>{
  const pending=held();const h=page((url)=>url.endsWith('/questions')?pending.promise:undefined);
  await tick();h.get('question').value='What changed?';
  h.get('question-form').listeners.submit({preventDefault(){}});
  const request=h.calls.find(c=>c.url.endsWith('/questions'));
  assert.equal(request.url,'/v1/patients/p1/questions');
  assert.equal(request.opts.headers.Authorization,'Bearer synthetic-token');
  assert.deepEqual(JSON.parse(request.opts.body),{question:'What changed?',as_of:'2026-01-02T08:00:00Z'});
  const old=h.get('conversation').children.at(-1);h.select('p2');
  pending.resolve(answer('old-patient-secret'));await tick();
  assert(!old.innerHTML.includes('old-patient-secret'));
  assert(!h.get('conversation').innerHTML.includes('old-patient-secret'));
});

test('handover keeps UTC shift payload and rejects stale resident response',async()=>{
  const pending=held();const h=page(url=>url.endsWith('/summaries')?pending.promise:undefined);
  await tick();h.get('shift-start').value='2026-01-02T00:00';h.get('shift-end').value='2026-01-03T00:00';
  h.get('handover-form').listeners.submit({preventDefault(){}});
  const request=h.calls.find(c=>c.url.endsWith('/summaries'));
  assert.deepEqual(JSON.parse(request.opts.body),{shift_start:'2026-01-02T00:00:00.000Z',shift_end:'2026-01-03T00:00:00.000Z'});
  h.select('p2');pending.resolve(answer('stale-summary'));await tick();
  assert(!h.get('summary').innerHTML.includes('stale-summary'));
});

test('source retries reauthorize and latest source wins; exact quote is escaped',async()=>{
  const first=held();let n=0;
  const h=page(url=>url.includes('/evidence/')?(++n===1?first.promise:{quote:'<script>exact</script>',source_kind:'nursing_note',author_role:'nurse',source_version_id:'version-2',start:1,end:9}):undefined);
  await tick();
  h.get('evidence-content').dataset.evidenceId='e1';h.clickRetry('evidence');
  h.get('evidence-content').dataset.evidenceId='e2';h.clickRetry('evidence');
  await tick();first.resolve({quote:'stale-source',source_kind:'nursing_note'});await tick();
  const html=h.get('evidence-content').innerHTML;
  assert(html.includes('&lt;script&gt;exact&lt;/script&gt;'));
  assert(html.includes('Source identifiers and exact span'));
  assert(!html.includes('stale-source'));
  assert.equal(h.calls.filter(c=>c.url.includes('/evidence/')).length,2);
  assert(h.calls.filter(c=>c.url.includes('/evidence/')).every(c=>c.opts.headers.Authorization==='Bearer synthetic-token'));
});

test('session error exposes retry and empty assignment never requests undefined patient',async()=>{
  let n=0;const h=page(url=>url==='/demo/session'?(++n===1?{ok:false,status:503,error:{code:'dependency_unavailable'}}:session([])):undefined);
  await tick();assert(h.get('global-error').innerHTML.includes('data-retry="session"'));
  h.clickRetry('session');await tick();
  assert(h.get('patients').innerHTML.includes('No residents are assigned'));
  assert.equal(h.calls.length,2);
  assert.equal(h.get('global-error').hidden,true);
});

test('failed timeline offers scoped retry without replacing clinical unknowns with negatives',async()=>{
  let n=0;const h=page(url=>url.includes('/timeline')?(++n===1?{ok:false,status:503,error:{code:'dependency_unavailable'}}:timeline([])):undefined);
  await tick();await tick();assert(h.get('timeline').innerHTML.includes('data-retry="timeline"'));
  h.clickRetry('timeline');await tick();
  assert(h.get('timeline').innerHTML.includes('Missing documentation does not establish a negative finding'));
  assert(h.calls.filter(c=>c.url.includes('/timeline')).every(c=>c.url.startsWith('/v1/patients/p1/timeline?')&&c.url.includes('as_of=')));
});


test('authorized deep link selects exactly the linked assigned resident, never the first roster entry',async()=>{
  const h=page(()=>undefined,undefined,'?patient=p2');await tick();await tick();
  assert.equal(h.get('patient-name').textContent,'Synthetic p2');
  assert.equal(h.calls.length,2);
  assert(h.calls[1].url.startsWith('/v1/patients/p2/timeline?'));
  assert(!h.calls.some(c=>c.url.includes('/patients/p1/')));
});

test('unavailable, blank or ambiguous deep link never opens or fetches another resident',async()=>{
  for(const search of ['?patient=unassigned','?patient=','?patient=p1&patient=p2']){
    const h=page(()=>undefined,undefined,search);await tick();await tick();
    assert.equal(h.get('patient-name').textContent,'Resident unavailable');
    assert.equal(h.get('global-error').hidden,false);
    assert(h.get('global-error').innerHTML.includes('not assigned to you'));
    assert.equal(h.calls.length,1,'only the authorized session roster is fetched');
    h.get('question').value='Can you retrieve this?';
    h.get('question-form').listeners.submit({preventDefault(){}});
    h.get('refresh').listeners.click();await tick();
    assert.equal(h.calls.length,1,'no question or timeline request without explicit authorized selection');
    h.select('p2');await tick();
    assert.equal(h.get('global-error').hidden,true);
    assert(h.calls[1].url.startsWith('/v1/patients/p2/timeline?'));
  }
});

test('roster without optional reference/questions stays usable without inventing reference or suggestions',async()=>{
  const h=page(()=>undefined,[{id:'p1',name:'Synthetic resident'}],'?patient=p1');await tick();await tick();
  assert.equal(h.get('global-error').hidden,true);
  assert(h.get('patient-reference').textContent.includes('Reference not provided'));
  assert.equal(h.get('suggestions').innerHTML,'');
  assert(h.calls[1].url.startsWith('/v1/patients/p1/timeline?'));
});
