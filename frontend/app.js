'use strict';
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = (value) => String(value ?? '').replaceAll('_', ' ');
const initials = (name) => name.split(' ').map(p => p[0]).join('');
const date = (value, time = false) => value ? new Intl.DateTimeFormat('en-GB', {timeZone:'UTC', day:'2-digit',month:'short',year:'numeric', ...(time ? {hour:'2-digit',minute:'2-digit',hour12:false} : {})}).format(new Date(value)) + (time ? ' UTC' : '') : 'Time not documented';
const kinds = {nursing_note:'Nursing note', patient_report:'Patient report', observation:'Observation', medication_event:'Medication event'};
const state = {session:null, patient:null, events:[], filter:'all', cursor:null, generation:0, questionBusy:false, summaryBusy:false, timelineBusy:false, evidenceSequence:0};
const friendlyErrors = {invalid_identity:'Your demo session expired. Reload the page to reconnect.', dependency_unavailable:'The database or source storage is unavailable. Check Docker and retry.', rate_limited:'Too many requests. Please wait a minute and try again.', not_found:'This record is unavailable or no longer assigned to you.', cursor_expired:'The record changed. Refresh the timeline to continue.', memory_changed:'The record changed during the request. Please try again.', invalid_request:'Check the request fields and dates, then try again.'};
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...(state.session ? {Authorization:`Bearer ${state.session.token}`} : {}), ...options.headers}}); }
  catch { throw new Error('Cannot reach the local backend. Check that the workspace server is running, then retry.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(friendlyErrors[data.error?.code] || data.error?.message || `Request failed (${response.status}). Please try again.`);
  return data;
}
function notice(text) {return `<div class="notice" role="status">${escapeHtml(text)}</div>`;}
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
  $('patients').innerHTML = patients.length ? patients.map(p => `<button class="patient-button ${state.patient?.id === p.id ? 'selected' : ''}" data-patient="${escapeHtml(p.id)}" aria-pressed="${state.patient?.id === p.id}"><span class="avatar">${initials(p.name)}</span><span><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.reference.toUpperCase())}</small></span>${state.patient?.id === p.id ? '<span class="arrow">›</span>' : ''}</button>`).join('') : '<p class="empty">No matching patients.</p>';
}
function setTab(name) {
  for (const tab of ['timeline','handover']) {
    $(tab+'-tab').classList.toggle('active', tab === name);
    $(tab+'-tab').setAttribute('aria-selected', String(tab === name));
    $(tab+'-view').hidden = tab !== name;
  }
}
function selectPatient(id) {
  state.patient = state.session.patients.find(p => p.id === id);
  state.generation++; state.evidenceSequence++; state.events=[]; state.cursor=null; state.filter='all';
  state.questionBusy=false; state.summaryBusy=false; state.timelineBusy=false;
  $('evidence-dialog').close();
  $('patient-name').textContent = state.patient.name;
  $('patient-avatar').textContent = initials(state.patient.name);
  $('patient-reference').textContent = `${state.patient.reference.toUpperCase()} · Synthetic patient`;
  $('scope-name').textContent = state.patient.name + '’s';
  $('question').value=''; $('ask').disabled=false; $('generate-summary').disabled=false;
  $('generate-summary').innerHTML='Generate handover <span>↗</span>';
  $('revision').textContent='Loading record';
  $('timeline-coverage').innerHTML='';
  $('summary').innerHTML='<div class="summary-empty"><span>≋</span><h3>Ready for the next shift.</h3><p>Bring together documented changes, patient reports, conflicts, and unknowns.</p></div>';
  $('conversation').innerHTML='<div class="welcome"><div class="welcome-icon">✳</div><h3>Start with a question.</h3><p>Explore what’s documented.<br>See exactly where it came from.</p></div><div id="suggestions" class="suggestions"></div>';
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
  } catch(error) {if (generation === state.generation) $('timeline').innerHTML=notice(error.message);}
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
    const attribution=e.source_kind==='patient_report' ? 'Patient reported' : e.source_kind==='nursing_note' ? 'Attributed nursing note' : 'Documented observation';
    return `${heading}<article class="event" data-kind="${escapeHtml(e.source_kind)}"><span class="event-dot">${e.source_kind==='patient_report'?'◦':'·'}</span><div class="event-top"><b>${escapeHtml(kinds[e.source_kind] || pretty(e.source_kind))}</b><span>${e.effective_from ? escapeHtml(new Date(e.effective_from).toISOString().slice(11,16))+' UTC' : 'Unknown time'}</span></div><p>${escapeHtml(e.quote)}</p><div class="event-bottom"><span class="tag ${e.source_kind==='patient_report'?'patient':''}">${attribution}</span>${historical?'<span class="tag">Historical · interval ended</span>':''}${e.polarity==='uncertain'?'<span class="tag">Uncertain</span>':''}<button class="source-link" data-evidence="${escapeHtml(e.evidence_id)}">View source ↗</button></div></article>`;
  }).join('') : '<p class="empty">No records match this view.</p>';
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
  return `<div class="answer-title">✳ ${escapeHtml(status)}</div>${coverage(answer.coverage)}${claims}${answer.unknowns.map(u=>`<div class="unknown"><b>${escapeHtml(pretty(u.topic))}</b> · ${escapeHtml(pretty(u.reason))}. Missing documentation does not establish a negative finding.</div>`).join('')}${answer.conflicts.map(c=>`<div class="unknown"><b>Unresolved conflict: ${escapeHtml(c.topic)}</b><p>These sources disagree; no resolution is documented.</p>${c.evidence_ids.map(id=>`<button class="citation" data-evidence="${escapeHtml(id)}">Compare source ↗</button>`).join('')}</div>`).join('')}<div class="answer-meta">Record as of ${escapeHtml(date(answer.as_of,true))}<br>Known at ${escapeHtml(date(answer.known_at,true))} · Revision ${answer.memory_revision}<br>${escapeHtml(answer.versions.model || 'Offline demo')}</div>`;
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
  catch(error){if(generation===state.generation){block.innerHTML=notice(error.message);$('question').value=question;}}
  finally {if(generation===state.generation){state.questionBusy=false;$('ask').disabled=false;}}
}
async function generateSummary(event) {
  event.preventDefault();if(!state.patient || state.summaryBusy)return;
  const start=$('shift-start').value,end=$('shift-end').value;
  if(!start || !end || start>end){$('summary').innerHTML=notice('Choose a shift end after the shift start.');return;}
  const generation=state.generation;
  state.summaryBusy=true;$('generate-summary').disabled=true;$('generate-summary').textContent='Building your handover…';
  $('summary').innerHTML='<div class="loading">Gathering source-linked context…</div>';
  try {const answer=await api(`/v1/patients/${state.patient.id}/summaries`,{method:'POST',body:JSON.stringify({shift_start:new Date(start+'Z').toISOString(),shift_end:new Date(end+'Z').toISOString()})});if(generation===state.generation)$('summary').innerHTML=`<div class="answer-block">${renderAnswer(answer,true)}</div>`;}
  catch(error){if(generation===state.generation)$('summary').innerHTML=notice(error.message);}
  finally{if(generation===state.generation){state.summaryBusy=false;$('generate-summary').disabled=false;$('generate-summary').innerHTML='Generate handover <span>↗</span>';}}
}
async function showEvidence(id) {
  const generation=state.generation,sequence=++state.evidenceSequence;
  $('evidence-content').innerHTML='<div class="loading">Checking source access…</div>';
  if(!$('evidence-dialog').open)$('evidence-dialog').showModal();
  try {const e=await api(`/v1/patients/${state.patient.id}/evidence/${id}`);
    if(generation!==state.generation || sequence!==state.evidenceSequence)return;
    $('evidence-content').innerHTML=`<span class="tag">${escapeHtml(kinds[e.source_kind] || pretty(e.source_kind))}</span><blockquote>${escapeHtml(e.quote)}</blockquote><dl class="evidence-grid"><dt>Attributed to</dt><dd>${escapeHtml(pretty(e.author_role))}</dd><dt>Recorded</dt><dd>${escapeHtml(date(e.recorded_at,true))}</dd><dt>Ingested</dt><dd>${escapeHtml(date(e.ingested_at,true))}</dd><dt>Source version</dt><dd>${escapeHtml(e.source_version_id)}</dd><dt>Exact span</dt><dd>Characters ${e.start}–${e.end} (end exclusive)</dd></dl>`;
  } catch(error){if(generation===state.generation && sequence===state.evidenceSequence)$('evidence-content').innerHTML=notice(error.message);}
}
async function boot(){
  try {state.session=await api('/demo/session',{headers:{'X-PM-Demo':'1'}});$('nav-count').textContent=state.session.patients.length;$('connection').innerHTML='<i></i> Local workspace connected';$('global-error').hidden=true;selectPatient(state.session.patients[0].id);}
  catch(error){$('connection').textContent='Connection unavailable';$('global-error').hidden=false;$('global-error').textContent=error.message+' Reload this page to retry.';$('patients').innerHTML='<p class="empty">Patients unavailable.</p>';}
}
$('patient-search').addEventListener('input',()=>{if(state.session)renderRoster();});
$('patients').addEventListener('click',e=>{const b=e.target.closest('[data-patient]');if(b)selectPatient(b.dataset.patient);});
$('timeline-tab').addEventListener('click',()=>setTab('timeline'));
$('handover-tab').addEventListener('click',()=>setTab('handover'));
$('refresh').addEventListener('click',()=>loadTimeline());
$('load-more').addEventListener('click',()=>loadTimeline(true));
document.querySelector('.filters').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;state.filter=b.dataset.filter;document.querySelectorAll('.filter').forEach(f=>{f.classList.toggle('active',f===b);f.setAttribute('aria-pressed',String(f===b));});renderTimeline();});
$('question-form').addEventListener('submit',e=>{e.preventDefault();askQuestion($('question').value);});
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();askQuestion(e.target.value);}});
$('handover-form').addEventListener('submit',generateSummary);
document.addEventListener('click',e=>{const evidence=e.target.closest('[data-evidence]');if(evidence)showEvidence(evidence.dataset.evidence);const suggestion=e.target.closest('[data-question]');if(suggestion)askQuestion(suggestion.dataset.question);});
$('close-evidence').addEventListener('click',()=>$('evidence-dialog').close());
$('evidence-dialog').addEventListener('click',e=>{if(e.target===$('evidence-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
boot();

document.querySelector('[role=tablist]').addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const name=e.key==='Home'?'timeline':e.key==='End'?'handover':$('timeline-tab').getAttribute('aria-selected')==='true'?'handover':'timeline';setTab(name);$(name+'-tab').focus();}});
