const $ = id => document.getElementById(id);
let patients = [], selected = null, epoch = 0, cursor = null, evidenceEpoch = 0;
const labels = {recent_changes:'Changes this shift',active_documented_concerns:'Documented observations',patient_reported_concerns:'Patient reports',documented_medication_events:'Medication events'};
const text = (tag, value, cls) => { const el = document.createElement(tag); el.textContent = value; if(cls) el.className=cls; return el; };
const human = value => String(value || 'unknown').replaceAll('_',' ');
const date = value => value ? new Date(value).toLocaleString('en-GB',{timeZone:'UTC',dateStyle:'medium',timeStyle:'short'})+' UTC' : 'Time not documented';
function notify(message) { $('notice').textContent=message; $('notice').hidden=!message; }
function root(){ return '/v1/patients/'+encodeURIComponent(selected.patient_id); }
async function request(path, body, token=selected.token){
  const response=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok) throw new Error(response.status===401?'Demo session expired. Generate a new session link.':human(data.error?.code || 'request failed'));
  return data;
}
function cutoffs(){const d=$('shift-date').value; if(!/^\d{4}-\d{2}-\d{2}$/.test(d))throw new Error('Choose a shift date.');return {shift_start:d+'T00:00:00Z',shift_end:d+'T23:59:59Z'};}
function card(claim, onEvidence){
  const el=text('article','','claim'), top=text('div','','claim-top');
  top.append(text('span',human(claim.epistemic_status || claim.source_kind),'claim-tag'),text('span',date(claim.effective_at || claim.effective_from),'muted'));
  el.append(top,text('p',claim.text ?? claim.quote));
  for(const id of claim.evidence_ids || [claim.evidence_id]){if(!id)continue;const b=text('button','↗ View source','source-button'); b.onclick=()=>onEvidence(id); el.append(b);}
  return el;
}
function renderAnswer(target, data){
  target.replaceChildren();
  if(!data.claims.length) target.append(text('div','No supported answer in the available record. This does not mean the condition is absent.','empty'));
  let section='';
  for(const c of data.claims){ if(c.section!==section){section=c.section;target.append(text('h3',labels[section] || human(section)));}target.append(card(c,showEvidence)); }
  for(const u of data.unknowns) target.append(text('div',human(u.topic)+': '+human(u.reason),'warning'));
  for(const c of data.conflicts) target.append(text('div','Unresolved conflict: '+human(c.topic)+'. Review both source observations.','warning'));
  if(!data.coverage.index_complete || data.coverage.truncated || data.coverage.degraded_mode) target.append(text('div','Coverage is limited: '+(!data.coverage.index_complete?'some sources are still processing. ':'')+(data.coverage.truncated?'only part of the record was retrieved. ':'')+(data.coverage.degraded_mode === 'hash_embedding_baseline' ? 'Basic text matching is enabled; relevant context may be missed.' : data.coverage.degraded_mode ? 'Search is running with reduced capabilities.' : ''),'warning'));
  target.append(text('p','Evidence-based extract · '+data.versions.model+' · Known at '+date(data.known_at),'muted'));
}
async function showEvidence(id){
  const own=epoch, ticket=++evidenceEpoch;
  $('evidence-body').replaceChildren(text('p','Loading source…','muted'));if(!$('evidence-dialog').open)$('evidence-dialog').showModal();
  try{const e=await request(root()+'/evidence/'+encodeURIComponent(id));if(own!==epoch || ticket!==evidenceEpoch)return;
    const dl=document.createElement('dl');for(const [name,val] of [['Source',human(e.source_kind)],['Author',human(e.author_role)],['Recorded',date(e.recorded_at)],['Available to system',date(e.ingested_at)],['Source version',e.source_version_id]])dl.append(text('dt',name),text('dd',val));
    $('evidence-body').replaceChildren(text('blockquote',e.quote),dl);
  }catch(e){if(own===epoch && ticket===evidenceEpoch)$('evidence-body').replaceChildren(text('p',e.message,'warning'));}
}
async function loadPatient(index){
  selected=patients[index];const own=++epoch;cursor=null;++evidenceEpoch;$('evidence-dialog').close();notify('');
  $('patient-name').textContent=selected.name || selected.profile;$('patient-id').textContent='Fictional record · '+selected.patient_id;
  $('revision').textContent='Loading';$('summary-status').textContent='';$('answer').replaceChildren();$('question').value='';$('more').hidden=true;
  document.querySelectorAll('.patient-button').forEach((b,i)=>{b.classList.toggle('selected',i===index);b.setAttribute('aria-pressed',String(i===index));});
  $('summary').replaceChildren(text('div','Preparing handoff…','empty'));$('timeline').replaceChildren(text('div','Loading observations…','empty'));
  try{const times=cutoffs();const [summary,timeline]=await Promise.all([request(root()+'/summaries',times),request(root()+'/timeline?as_of='+encodeURIComponent(times.shift_end))]);if(own!==epoch)return;
    renderAnswer($('summary'),summary);$('summary-status').textContent=human(summary.status);$('revision').textContent='Revision '+summary.memory_revision;
    $('timeline').replaceChildren();appendTimeline(timeline);
  }catch(e){if(own!==epoch)return;notify(e.message);$('summary').replaceChildren(text('div','Unable to load this record. Check the connection and retry.','empty'));$('timeline').replaceChildren();$('revision').textContent='Unavailable';}
}
function appendTimeline(data){for(const item of data.events)$('timeline').append(card(item,showEvidence));if(!$('timeline').children.length)$('timeline').append(text('div','No observations available for this time.','empty'));cursor=data.next_cursor;$('more').hidden=!cursor;if(!data.coverage.index_complete)$('timeline').append(text('div','Some sources are still processing.','warning'));}
function connect(entries){
  if(!Array.isArray(entries)||!entries.length||entries.length>100||entries.some(p=>typeof p.token!=='string'||typeof p.patient_id!=='string'||!p.profile))throw new Error('Invalid demo session. Import the fixture loader JSON.');
  patients=entries;$('patients').replaceChildren();entries.forEach((p,i)=>{const b=text('button','','patient-button');b.append(text('span',String(i+1).padStart(2,'0'),'avatar'));const name=text('span',p.name||human(p.profile));name.append(text('small','Fictional patient · View handoff'));b.append(name);b.onclick=()=>loadPatient(i);$('patients').append(b);});
  $('patient-count').textContent=entries.length;$('setup').hidden=true;$('workspace').hidden=false;loadPatient(0);
}
$('session-file').onchange=async e=>{try{connect(JSON.parse(await e.target.files[0].text()));}catch(err){notify(err.message);}e.target.value='';};
$('question-form').onsubmit=async e=>{e.preventDefault();if(!selected)return;const q=$('question').value.trim();if(!q)return;const own=epoch,b=$('question-form').querySelector('button');b.disabled=true;$('answer').replaceChildren(text('p','Finding supporting evidence…','muted'));try{const data=await request(root()+'/questions',{question:q,as_of:cutoffs().shift_end});if(own===epoch)renderAnswer($('answer'),data);}catch(err){if(own===epoch)$('answer').replaceChildren(text('div',err.message,'warning'));}finally{b.disabled=false;}};
document.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{$('question').value=b.dataset.question;$('question-form').requestSubmit();});
$('refresh').onclick=()=>loadPatient(patients.indexOf(selected));$('shift-date').onchange=$('refresh').onclick;
$('disconnect').onclick=()=>{++epoch;++evidenceEpoch;patients=[];selected=null;cursor=null;$('evidence-dialog').close();for(const id of ['summary','timeline','answer','evidence-body','patients'])$(id).replaceChildren();$('workspace').hidden=true;$('setup').hidden=false;notify('');};
$('close-evidence').onclick=()=>{$('evidence-dialog').close();++evidenceEpoch;};
for(const kind of ['summary','timeline'])$(kind+'-tab').onclick=()=>{for(const k of ['summary','timeline']){$(k+'-tab').setAttribute('aria-selected',String(k===kind));$(k+'-panel').hidden=k!==kind;}};
$('more').onclick=async()=>{const own=epoch;$('more').disabled=true;try{const data=await request(root()+'/timeline?cursor='+encodeURIComponent(cursor));if(own===epoch)appendTimeline(data);}catch(e){if(own===epoch)notify(e.message);}finally{$('more').disabled=false;}};
function consumeSession(){if(location.hash){const fragment=location.hash.slice(1);history.replaceState(null,'',location.pathname);try{connect(JSON.parse(decodeURIComponent(fragment)));}catch(e){notify(e.message);}}}
window.addEventListener('hashchange',consumeSession);
consumeSession();
