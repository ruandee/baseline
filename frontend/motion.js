// /check?type=motion. Camera/pose data stays on this device; only final numbers are submitted.
window.renderMotion = async function(host) {
  const params = checkParams();
  const resident = params.mode === 'resident';
  document.body.setAttribute('data-motion-page', '');
  const panel = el('section', '', {class: 'bl-motion', 'data-mode': params.mode,
    'aria-label': 'Movement check'});
  const field = (text, control) => {
    const label = el('label', text, {class: 'bl-motion-field'});
    label.append(control);
    return label;
  };
  const title = el('h1', resident ? "Let's move together" : 'Movement check');
  const copy = el('p', 'With someone nearby, sit in a chair facing or sideways to a steady phone. '
    + 'Keep your shoulders, hips and feet in view. Stand up and take three steps during the 10-second check.');
  const privacy = el('p', 'Video stays on this phone. Only client-derived measurements and quality counts are sent.');
  const select = el('select', '', {'aria-label': 'Person'});
  for (const person of state.session.patients) {
    const option = el('option', person.name, {value: person.id});
    if (person.id === params.patient) option.selected = true;
    select.append(option);
  }
  const baseline = el('input', '', {type: 'checkbox'});
  const baselineLabel = el('label', ' Use as a baseline capture', {class: 'bl-motion-checkbox'}); baselineLabel.prepend(baseline);
  baselineLabel.hidden = resident;
  const permission = el('fieldset', '', {class: 'bl-motion-permission'}); permission.hidden = resident;
  permission.append(el('legend', 'Movement-check permission'));
  const decision = el('select', '', {'aria-label': 'Permission decision'});
  for (const [value, label] of [['granted', 'The person agrees'], ['declined', 'The person declines'],
    ['withdrawn', 'Permission withdrawn']]) decision.append(el('option', label, {value}));
  const decidedBy = el('select', '', {'aria-label': 'Decision maker'});
  for (const [value, label] of [['resident', 'The person'],
    ['substitute_decision_maker', 'Substitute decision maker']]) decidedBy.append(el('option', label, {value}));
  const reference = el('input', '', {type: 'text', maxlength: '200',
    'aria-label': 'Substitute decision maker reference, required when applicable'});
  const confirmed = el('input', '', {type: 'checkbox'});
  const confirmLabel = el('label', ' I have confirmed this movement-check decision.',
    {class: 'bl-motion-checkbox'});
  confirmLabel.prepend(confirmed);
  const savePermission = el('button', 'Record movement permission', {type: 'button'});
  savePermission.disabled = true;
  confirmed.addEventListener('change', () => { savePermission.disabled = !confirmed.checked; });
  permission.append(field('Permission decision', decision), field('Decision maker', decidedBy),
    field('Substitute decision maker reference (required when applicable)', reference),
    confirmLabel, savePermission);
  const video = el('video', '', {playsinline: '', muted: '', 'aria-label': 'Local camera preview'});
  video.muted = true; video.playsInline = true;
  const status = el('p', 'Camera is off.', {role: 'status', class: 'bl-motion-status'});
  const prepare = el('button', 'Prepare local motion model', {type: 'button'});
  const start = el('button', 'Start 10-second check', {type: 'button'}); start.disabled = true;
  const cancel = el('button', 'Cancel / turn camera off', {type: 'button'});
  start.setAttribute('class', 'bl-motion-start');
  const actions = el('div', '', {class: 'bl-motion-actions'});
  actions.append(prepare, start, cancel);
  const result = el('section', '', {'aria-label': 'Movement result'});
  const capture = new MotionCapture(video);
  panel.append(title, copy, privacy, field('Person', select), permission, baselineLabel,
    actions, status, video, result);
  host.replaceChildren(panel);
  let disposed = false, operation = 0;
  const readiness = () => api(`/v1/patients/${select.value}/motion-checks/readiness`);
  const failure = () => {
    capture.cancel(); start.disabled = true;
    status.textContent = resident ? 'Please ask your care team before trying again.'
      : 'This capture could not continue. Check recorded motion consent and local camera/model availability.';
  };
  savePermission.addEventListener('click', async () => {
    if (!confirmed.checked) return;
    savePermission.disabled = true;
    const op = ++operation;
    capture.cancel(); start.disabled = true;
    try {
      const body = {scope: 'motion_check', status: decision.value, decided_by: decidedBy.value};
      if (decidedBy.value === 'substitute_decision_maker') {
        if (!reference.value.trim()) throw new Error('Reference required');
        body.sdm_reference = reference.value.trim();
      }
      await api(`/v1/patients/${select.value}/consents`, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      if (op !== operation || disposed) return;
      status.textContent = 'Movement permission recorded. Camera is off.';
      capture.cancel(); start.disabled = true;
    } catch (_) { status.textContent = 'Permission could not be recorded. Check the decision-maker details and your care-team access.'; }
    finally { confirmed.checked = false; savePermission.disabled = true; }
  });
  select.addEventListener('change', () => { operation++; capture.cancel(); start.disabled = true; result.replaceChildren(); });
  prepare.addEventListener('click', async () => {
    prepare.disabled = true;
    const op = ++operation;
    try {
      await readiness();
      if (disposed || op !== operation) return;
      status.textContent = 'Preparing the pose model on this device. Camera is still off.';
      await capture.warm();
      if (!disposed && op === operation) { start.disabled = false; status.textContent = 'Ready. Tap Start when you are seated.'; }
    } catch (_) { if (!disposed && op === operation) failure(); }
    finally { prepare.disabled = false; }
  });
  start.addEventListener('click', async () => {
    start.disabled = true; select.disabled = true; baseline.disabled = true;
    const patient = select.value, op = ++operation;
    try {
      await readiness();
      if (disposed || op !== operation) return;
      status.textContent = 'Camera active for 10 seconds. Stand up and take three steps.';
      const measured = await capture.capture();
      if (disposed || op !== operation) return;
      if (!measured) {
        status.textContent = "Camera off. No movement measurements were submitted."; return;
      }
      status.textContent = 'Camera off. Sending measurements only.';
      const data = await api(`/v1/patients/${patient}/motion-checks`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...measured, device_id: checkDeviceId(params),
          device_ts: new Date().toISOString(), prompt_version: 'pose-chair-steps-v1',
          is_baseline: !resident && baseline.checked})});
      if (disposed || op !== operation) return;
      result.replaceChildren();
      if (resident || !data.features) {
        result.append(el('p', 'Thank you.')); // PSWs/residents never see measurements or scores.
      } else {
        result.append(el('h2', 'Client-derived measurements (unverified)'));
        for (const [name, label, unit] of [['sit_to_stand_s', 'Time to half-rise', 's'],
          ['trunk_sway', 'Trunk sway', 'ratio'], ['step_cadence_spm', 'Step cadence', 'steps/min']]) {
          const value = data.features[name];
          result.append(el('p', `${label}: ${value === null ? 'Unknown' : value.toFixed(2) + ' ' + unit}`));
        }
        if (!data.usable) result.append(el('p', 'Incomplete or insufficient-quality movement. No change assessment was made.'));
      }
      status.textContent = resident ? 'Thank you.' : 'Measurements saved; camera is off.';
    } catch (_) { if (!disposed && op === operation) failure(); }
    finally {
      select.disabled = false; baseline.disabled = false;
      if (!disposed && capture.ready) start.disabled = false;
    }
  });
  cancel.addEventListener('click', () => {
    operation++; capture.cancel(); start.disabled = true; status.textContent = 'Camera off. No video was sent.';
  });
  window.addEventListener('pagehide', () => { disposed = true; operation++; capture.cancel(); }, {once: true});
};
