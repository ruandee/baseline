'use strict';
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = (value) => String(value ?? '').replaceAll('_', ' ');
const initials = (name) => name.split(' ').map(p => p[0]).join('');
const date = (value, time = false) => value ? new Intl.DateTimeFormat('en-GB', {timeZone:'UTC', day:'2-digit',month:'short',year:'numeric', ...(time ? {hour:'2-digit',minute:'2-digit',hour12:false} : {})}).format(new Date(value)) + (time ? ' UTC' : '') : 'Time not documented';
const kinds = {nursing_note:'Nursing note', patient_report:'Patient report', observation:'Observation', medication_event:'Medication event'};
const state = {session:null, patient:null, events:[], filter:'all', cursor:null, generation:0, questionBusy:false, summaryBusy:false, timelineBusy:false, evidenceSequence:0};
const friendlyErrors = {invalid_identity:'Your demo session expired. Reload the page to reconnect.', dependency_unavailable:'The record service is temporarily unavailable. Please retry.', rate_limited:'Too many requests. Please wait a minute and try again.', not_found:'This record is unavailable or no longer assigned to you.', cursor_expired:'The record changed. Refresh the timeline to continue.', memory_changed:'The record changed during the request. Please try again.', invalid_request:'Check the request fields and dates, then try again.'};
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...(state.session ? {Authorization:`Bearer ${state.session.token}`} : {}), ...options.headers}}); }
  catch { throw new Error('Cannot reach the record service. Check your connection, then retry.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(friendlyErrors[data.error?.code] || data.error?.message || `Request failed (${response.status}). Please try again.`);
  return data;
}
function notice(text, retry = '') {return `<div class="notice" role="status">${escapeHtml(text)}${retry ? `<button class="secondary" type="button" data-retry="${escapeHtml(retry)}">Try again</button>` : ''}</div>`;}
function coverage(c) {
  if (!c) return '';
  const notes = [];
  if (!c.index_complete) notes.push('Some sources are still being processed. This view may be incomplete.');
  if (c.truncated) notes.push('Evidence was limited. This is not an exhaustive review of the record.');
  if (c.degraded_mode) notes.push(c.degraded_mode === 'hash_embedding_baseline' ? 'Demo search relies on wording in the record; synonyms may be missed.' : `Limited retrieval: ${pretty(c.degraded_mode)}.`);
  return notes.map(notice).join('');
}
function renderRoster() {
  const query = $('patient-search').value.trim().toLowerCase();
  const patients = state.session.patients.filter(p => `${p.name} ${p.reference}`.toLowerCase().includes(query));
  $('patient-count').textContent = patients.length;
  $('patients').innerHTML = patients.length ? patients.map(p => `<button class="patient-button ${state.patient?.id === p.id ? 'selected' : ''}" data-patient="${escapeHtml(p.id)}" aria-pressed="${state.patient?.id === p.id}"><span class="avatar">${escapeHtml(initials(p.name))}</span><span><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.reference ? p.reference.toUpperCase() : 'Reference not provided')}</small></span>${state.patient?.id === p.id ? '<span class="arrow">›</span>' : ''}</button>`).join('') : '<p class="empty">No residents match your search. Try a name or reference.</p>';
}
function setTab(name) {
  for (const tab of ['timeline','handover']) {
    $(tab+'-tab').classList.toggle('active', tab === name);
    $(tab+'-tab').setAttribute('aria-selected', String(tab === name));
    $(tab+'-tab').setAttribute('tabindex', tab === name ? '0' : '-1');
    $(tab+'-view').hidden = tab !== name;
  }
}
function selectPatient(id) {
  const patient = state.session?.patients.find(p => p.id === id);
  if (!patient) return;
  state.patient = patient;
  $('global-error').hidden=true;
  state.generation++; state.evidenceSequence++; state.events=[]; state.cursor=null; state.filter='all';
  state.questionBusy=false; state.summaryBusy=false; state.timelineBusy=false;
  $('evidence-dialog').close();
  $('patient-name').textContent = state.patient.name;
  $('patient-avatar').textContent = initials(state.patient.name);
  $('patient-reference').textContent = state.patient.reference ? state.patient.reference.toUpperCase() : 'Reference not provided';
  $('scope-name').textContent = state.patient.name + '’s';
  $('question').value=''; $('ask').disabled=false; $('generate-summary').disabled=false;
  $('generate-summary').textContent='Create handover';
  $('revision').textContent='Loading record';
  $('record-cutoff').textContent=`Records as of ${date(state.session.as_of,true)}. Notes may be incomplete.`;
  $('timeline-coverage').innerHTML='';
  $('summary').innerHTML='<div class="summary-empty"><h3>No handover yet</h3><p>Choose a shift to review documented changes, conflicts and unknowns.</p></div>';
  $('conversation').innerHTML='<div class="welcome"><h3>What would you like to check?</h3><p>Choose a question below or write your own. Open a cited source to inspect its exact words.</p></div><div id="suggestions" class="suggestions"></div>';
  $('suggestions').innerHTML=state.patient.questions.filter((_,i) => [0,1,4].includes(i)).map(q => `<button class="suggestion" data-question="${escapeHtml(q)}">${escapeHtml(q)} <span>↗</span></button>`).join('');
  document.querySelectorAll('.filter').forEach(b => {b.classList.toggle('active',b.dataset.filter==='all');b.setAttribute('aria-pressed',String(b.dataset.filter==='all'));});
  renderRoster(); setTab('timeline'); loadTimeline();
}
async function loadTimeline(more = false) {
  if (!state.patient || state.timelineBusy) return;
  const generation=state.generation;
  state.timelineBusy=true; $('refresh').disabled=true; $('load-more').disabled=true;
  if (!more) {$('timeline').innerHTML='<div class="loading">Reading the record…</div>'; $('load-more').hidden=true;}
  const params = new URLSearchParams({limit:'50',as_of:state.session.as_of});
  if (more && state.cursor) params.set('cursor',state.cursor);
  try {
    const result = await api(`/v1/patients/${state.patient.id}/timeline?${params}`);
    if (generation !== state.generation) return;
    state.events=more ? [...state.events,...result.events] : result.events;
    state.cursor=result.next_cursor;
    $('revision').textContent=`Revision ${result.memory_revision}`;
    $('timeline-coverage').innerHTML=coverage(result.coverage);
    renderTimeline();
  } catch(error) {if (generation === state.generation) $('timeline').innerHTML=notice(error.message,'timeline');}
  finally {if(generation===state.generation){state.timelineBusy=false;$('refresh').disabled=false;$('load-more').disabled=false;}}
}
function renderTimeline() {
  const events=state.events.filter(e => state.filter==='all' || e.source_kind===state.filter).sort((a,b) => (b.effective_from || '').localeCompare(a.effective_from || ''));
  let lastDay='';
  $('timeline').innerHTML=events.length ? events.map(e => {
    const day=date(e.effective_from);
    const heading=day!==lastDay ? `<div class="day-heading">${escapeHtml(day)}</div>` : '';
    lastDay=day;
    const historical=e.effective_to && new Date(e.effective_to)<new Date(state.session.as_of);
    const attribution=e.source_kind==='patient_report' ? 'Patient reported' : e.source_kind==='nursing_note' ? 'Attributed nursing note' : e.source_kind==='medication_event' ? 'Documented medication event' : 'Documented observation';
    return `${heading}<article class="event" data-kind="${escapeHtml(e.source_kind)}"><span class="event-dot">${e.source_kind==='patient_report'?'◦':'·'}</span><div class="event-top"><b>${escapeHtml(kinds[e.source_kind] || pretty(e.source_kind))}</b><span>${e.effective_from ? escapeHtml(new Date(e.effective_from).toISOString().slice(11,16))+' UTC' : 'Unknown time'}</span></div><p>${escapeHtml(e.quote)}</p><div class="event-bottom"><span class="tag ${e.source_kind==='patient_report'?'patient':''}">${attribution}</span>${historical?'<span class="tag">Historical · interval ended</span>':''}${e.polarity==='uncertain'?'<span class="tag">Uncertain</span>':''}<button class="source-link" data-evidence="${escapeHtml(e.evidence_id)}">View source ↗</button></div></article>`;
  }).join('') : '<p class="empty">No records match this view. Missing documentation does not establish a negative finding.</p>';
  $('load-more').hidden=!state.cursor;
}
function renderAnswer(answer, summary=false) {
  let section='';
  const status={answered:'Evidence found',partial:'Partial evidence',insufficient_evidence:'Insufficient evidence',conflicting_evidence:'Conflicting evidence'}[answer.status] || pretty(answer.status);
  const claims=answer.claims.map(c => {
    let heading='';
    if(summary && section!==c.section){section=c.section;heading=`<h4 class="summary-section">${escapeHtml(pretty(section))}</h4>`;}
    return `${heading}<div class="claim"><span class="tag ${c.epistemic_status==='patient_reported'?'patient':''}">${escapeHtml(pretty(c.epistemic_status))}</span><p>${escapeHtml(c.text)}</p><div>${c.evidence_ids.map(id => `<button class="citation" data-evidence="${escapeHtml(id)}">↗ Source ${answer.evidence.findIndex(e=>e.evidence_id===id)+1}</button>`).join('')}</div><div class="claim-meta">${escapeHtml(date(c.effective_at,true))}</div></div>`;
  }).join('');
  return `<div class="answer-title">✳ ${escapeHtml(status)}</div>${coverage(answer.coverage)}${claims}${answer.unknowns.map(u=>`<div class="unknown"><b>${escapeHtml(pretty(u.topic))}</b> · ${escapeHtml(pretty(u.reason))}. Missing documentation does not establish a negative finding.</div>`).join('')}${answer.conflicts.map(c=>`<div class="unknown"><b>Unresolved conflict: ${escapeHtml(c.topic)}</b><p>These sources disagree; no resolution is documented.</p>${c.evidence_ids.map(id=>`<button class="citation" data-evidence="${escapeHtml(id)}">Compare source ↗</button>`).join('')}</div>`).join('')}<div class="answer-meta">Record as of ${escapeHtml(date(answer.as_of,true))}<br>Known at ${escapeHtml(date(answer.known_at,true))} · Revision ${answer.memory_revision}<br><details class="evidence-technical"><summary>Generation details</summary>${escapeHtml(answer.versions.model || 'Offline demo')}</details></div>`;
}
async function askQuestion(question) {
  question=question.trim();
  if (!question || !state.patient || state.questionBusy) return;
  const generation=state.generation, patient=state.patient;
  state.questionBusy=true;$('ask').disabled=true;$('question').value='';
  const welcome=$('conversation').querySelector('.welcome'); if(welcome) welcome.remove();
  $('suggestions')?.remove();
  const bubble=document.createElement('div');bubble.className='question-bubble';bubble.textContent=question;
  const block=document.createElement('div');block.className='answer-block';block.innerHTML='<div class="loading">Following the evidence…</div>';
  $('conversation').append(bubble,block);block.scrollIntoView({block:'nearest'});
  try {const answer=await api(`/v1/patients/${patient.id}/questions`,{method:'POST',body:JSON.stringify({question,as_of:state.session.as_of})});if(generation===state.generation) block.innerHTML=renderAnswer(answer);}
  catch(error){if(generation===state.generation){block.innerHTML=notice(error.message,'question');$('question').value=question;}}
  finally {if(generation===state.generation){state.questionBusy=false;$('ask').disabled=false;}}
}
async function generateSummary(event) {
  event.preventDefault();if(!state.patient || state.summaryBusy)return;
  const start=$('shift-start').value,end=$('shift-end').value;
  if(!start || !end || start>end){$('summary').innerHTML=notice('Choose a shift end after the shift start.');return;}
  const generation=state.generation;
  state.summaryBusy=true;$('generate-summary').disabled=true;$('generate-summary').textContent='Building your handover…';
  $('summary').innerHTML='<div class="loading">Gathering source-linked context...</div>';
  try {const answer=await api(`/v1/patients/${state.patient.id}/summaries`,{method:'POST',body:JSON.stringify({shift_start:new Date(start+'Z').toISOString(),shift_end:new Date(end+'Z').toISOString()})});if(generation===state.generation)$('summary').innerHTML=`<div class="answer-block">${renderAnswer(answer,true)}</div>`;}
  catch(error){if(generation===state.generation)$('summary').innerHTML=notice(error.message,'summary');}
  finally{if(generation===state.generation){state.summaryBusy=false;$('generate-summary').disabled=false;$('generate-summary').textContent='Create handover';}}
}
async function showEvidence(id) {
  const generation=state.generation,sequence=++state.evidenceSequence;
  if (!state.patient) return;
  $('evidence-content').dataset.evidenceId=id;
  $('evidence-content').innerHTML='<div class="loading">Checking source access…</div>';
  if(!$('evidence-dialog').open)$('evidence-dialog').showModal();
  try {const e=await api(`/v1/patients/${state.patient.id}/evidence/${id}`);
    if(generation!==state.generation || sequence!==state.evidenceSequence)return;
    $('evidence-content').innerHTML=`<span class="tag">${escapeHtml(kinds[e.source_kind] || pretty(e.source_kind))}</span><blockquote>${escapeHtml(e.quote)}</blockquote><dl class="evidence-grid"><dt>Attributed to</dt><dd>${escapeHtml(pretty(e.author_role))}</dd><dt>Recorded</dt><dd>${escapeHtml(date(e.recorded_at,true))}</dd><dt>Ingested</dt><dd>${escapeHtml(date(e.ingested_at,true))}</dd></dl><details class="evidence-technical"><summary>Source identifiers and exact span</summary><dl class="evidence-grid"><dt>Source version</dt><dd>${escapeHtml(e.source_version_id)}</dd><dt>Exact span</dt><dd>Characters ${e.start}–${e.end} (end exclusive)</dd></dl></details>`;
  } catch(error){if(generation===state.generation && sequence===state.evidenceSequence)$('evidence-content').innerHTML=notice(error.message,'evidence');}
}
let bootBusy=false;
let shiftWindowInitialized=false, shiftWindowEdited=false;
for (const id of ['shift-start','shift-end']) {
  for (const event of ['input','change']) $(id).addEventListener(event,()=>{shiftWindowEdited=true;});
}
function initializeShiftWindow(session) {
  if (session.snapshot_mode!=='current') return;
  $('handover-window-help').textContent='Default: last 24 hours. Adjust to your shift (UTC).';
  if (shiftWindowInitialized || shiftWindowEdited) return;
  const end=new Date(session.as_of);
  if (Number.isNaN(end.getTime())) return;
  $('shift-end').value=end.toISOString().slice(0,16);
  $('shift-start').value=new Date(end.getTime()-24*60*60*1000).toISOString().slice(0,16);
  shiftWindowInitialized=true;
}
async function boot(){
  if (bootBusy) return;
  bootBusy=true;
  try {
    state.session=await api('/demo/session',{headers:{'X-PM-Demo':'1'}});
    // Reference and suggested questions are optional roster presentation fields.
    state.session.patients=state.session.patients.map(p=>({...p,
      name:typeof p.name==='string' && p.name.trim() ? p.name : 'Name not provided',
      reference:typeof p.reference==='string' ? p.reference : '',
      questions:Array.isArray(p.questions) ? p.questions.filter(q=>typeof q==='string') : [],
    }));
    initializeShiftWindow(state.session);
    $('nav-count').textContent=state.session.patients.length;
    $('connection').textContent='Workspace connected';
    $('global-error').hidden=true;
    const linkedIds=new URLSearchParams(window.location.search).getAll('patient');
    const linkedPatient=linkedIds.length===1 && state.session.patients.find(p=>p.id===linkedIds[0]);
    if (linkedIds.length && !linkedPatient) {
      renderRoster();
      $('global-error').hidden=false;
      $('global-error').innerHTML=notice('The requested resident is unavailable or is not assigned to you. Choose an assigned resident to continue.');
      $('patient-name').textContent='Resident unavailable';
      $('patient-reference').textContent='No record has been opened from this link.';
      $('timeline').innerHTML='<p class="empty">Choose an assigned resident to see their record.</p>';
    } else if (linkedPatient) selectPatient(linkedPatient.id);
    else if (state.session.patients.length) selectPatient(state.session.patients[0].id);
    else {
      $('patients').innerHTML='<p class="empty">No residents are assigned to this workspace. Contact your care-team administrator.</p>';
      $('patient-name').textContent='No assigned residents';
      $('patient-count').textContent='0';
    }
  } catch(error){
    $('connection').textContent='Connection unavailable';
    $('global-error').hidden=false;
    $('global-error').innerHTML=notice(error.message,'session');
    $('patients').innerHTML='<p class="empty">Resident list unavailable. Try reconnecting above.</p>';
  } finally {bootBusy=false;}
}
$('patient-search').addEventListener('input',()=>{if(state.session)renderRoster();});
$('patients').addEventListener('click',e=>{const b=e.target.closest('[data-patient]');if(b){selectPatient(b.dataset.patient);if(window.matchMedia?.('(max-width:1050px)').matches)$('resident-picker').open=false;}});
$('timeline-tab').addEventListener('click',()=>setTab('timeline'));
$('handover-tab').addEventListener('click',()=>setTab('handover'));
$('refresh').addEventListener('click',()=>loadTimeline());
$('load-more').addEventListener('click',()=>loadTimeline(true));
document.querySelector('.filters').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;state.filter=b.dataset.filter;document.querySelectorAll('.filter').forEach(f=>{f.classList.toggle('active',f===b);f.setAttribute('aria-pressed',String(f===b));});renderTimeline();});
$('question-form').addEventListener('submit',e=>{e.preventDefault();askQuestion($('question').value);});
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();askQuestion(e.target.value);}});
$('handover-form').addEventListener('submit',generateSummary);
document.addEventListener('click',e=>{const evidence=e.target.closest('[data-evidence]');if(evidence)showEvidence(evidence.dataset.evidence);const suggestion=e.target.closest('[data-question]');if(suggestion)askQuestion(suggestion.dataset.question);});
document.addEventListener('click',e=>{
  const retry=e.target.closest('[data-retry]');if(!retry)return;
  if(retry.dataset.retry==='session')boot();
  if(retry.dataset.retry==='timeline')loadTimeline();
  if(retry.dataset.retry==='question')askQuestion($('question').value);
  if(retry.dataset.retry==='summary')generateSummary({preventDefault(){}});
  if(retry.dataset.retry==='evidence')showEvidence($('evidence-content').dataset.evidenceId);
});
$('close-evidence').addEventListener('click',()=>$('evidence-dialog').close());
$('evidence-dialog').addEventListener('click',e=>{if(e.target===$('evidence-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
boot();

document.querySelector('[role=tablist]').addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const name=e.key==='Home'?'timeline':e.key==='End'?'handover':$('timeline-tab').getAttribute('aria-selected')==='true'?'handover':'timeline';setTab(name);$(name+'-tab').focus();}});
