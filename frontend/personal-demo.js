// Direct-link volunteer demo. Uses the genuine authorized overview and recording APIs.
window.renderPersonalDemo = async function(main) {
  personalDemoDisclosure();
  main.replaceChildren();
  const person = (state.session.patients || []).find((p) => p.capture_mode === 'live'
    && p.scripted_cohort !== true);
  if (!person) {
    main.append(el('h1', 'Live voice demo'), el('p', 'No live volunteer record is assigned to this account.'));
    return;
  }
  const heading = el('h1', person.name);
  const intro = el('section', '', {class: 'workspace-panel'});
  const phonePath = `/check?mode=live&demo=personal&patient=${encodeURIComponent(person.id)}`;
  const phoneUrl = location.origin + phonePath;
  const link = el('a', 'Open phone recorder', {href: phonePath, class: 'workspace-primary'});
  const address = el('input', '', {type: 'text', readonly: '', 'aria-label': 'Phone recording link'});
  address.value = phoneUrl;
  const copy = el('button', 'Copy phone link', {type: 'button', class: 'workspace-secondary'});
  const copied = el('p', '', {role: 'status'});
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(phoneUrl); copied.textContent = 'Phone link copied.'; }
    catch (_) { copied.textContent = 'Copy the phone link shown above and open it on your phone.'; }
  });
  const links = el('div', '', {class: 'workspace-actions'}); links.append(link, copy);
  intro.append(el('p', 'LIVE VOICE DEMO', {class: 'workspace-eyebrow'}), heading,
    el('p', 'Record on your phone. Review the actual measurements here.'),
    el('ol', '', {'data-personal': 'steps'}), address, links, copied);
  ['Confirm your name, English counting setup and voice permission.',
   'On the phone, choose Enroll rested baseline and record five separate rested takes.',
   'Choose Start check-ins. Record again as often as needed; every result is measured.']
    .forEach((text) => intro.querySelector('ol').append(el('li', text)));
  const result = el('section', '', {class: 'workspace-panel', 'aria-live': 'polite',
    'aria-label': 'Latest measured voice check', 'data-personal': 'result'});
  const status = el('p', 'Connecting…', {role: 'status', 'data-personal': 'status'});
  const refreshButton = el('button', 'Refresh result', {type: 'button', class: 'workspace-secondary'});
  const setupHost = el('section', '', {class: 'workspace-panel'});
  main.append(intro, status, refreshButton, result, setupHost);
  let stopped = false, inFlight = false, timer = null, setup = null;
  const dispose = () => {
    stopped = true; clearInterval(timer);
    document.removeEventListener('visibilitychange', visibility);
    if (setup) setup.dispose();
  };
  state.unitStop = dispose;
  window.addEventListener('pagehide', dispose, {once: true});
  async function refresh() {
    if (stopped || inFlight) return;
    inFlight = true; refreshButton.disabled = true;
    try {
      const [overview, profile] = await Promise.all([
        api(`/v1/patients/${person.id}/overview?days=30`),
        api(`/v1/patients/${person.id}/check-profile`),
      ]);
      if (stopped) return;
      heading.textContent = profile.first_name || person.name;
      const assessment = overview.latest_assessment;
      const speech = assessment?.modality === 'speech' || !assessment?.modality
        ? assessment?.change : assessment?.modalities?.speech?.current ? assessment.modalities.speech : null;
      result.replaceChildren(el('h2', 'Latest measured voice check'));
      if (!assessment || !speech) {
        result.append(el('p', 'No current usable voice assessment. Complete setup and record on the phone; an unusable recording does not produce an assessment.'));
      } else {
        result.append(assessment.verdict
          ? verdictChip({latest_verdict: assessment.verdict, over_budget: assessment.over_budget})
          : chip('Assessment unavailable', 'unknown'), el('p', `Received ${formatTime(assessment.ts)}`),
          el('p', Number.isInteger(speech.params?.baseline_checks)
            ? `${speech.params.baseline_checks} eligible prior baseline checks used`
            : 'Eligible prior baseline count unavailable'));
        if (assessment.no_escalate_profile) result.append(el('p', 'External escalation is disabled for this demo volunteer.'));
        if (assessment.suggested_action?.id && assessment.suggested_action.id !== 'none') {
          result.append(el('p', assessment.suggested_action.label));
        }
        const grid = el('div', '', {class: 'bl-features'});
        FEATURES.forEach((feature) => grid.append(featureCell(feature,
          {features: Object.fromEntries(Object.entries(speech.per_feature || {}).map(([key, f]) => [key, f.value])), change: speech})));
        result.append(grid, el('a', 'Open full history and evidence',
          {href: `/resident/${encodeURIComponent(person.id)}`, class: 'workspace-secondary'}));
      }
      status.textContent = `Connected · updated ${new Date().toLocaleTimeString()} · checking every 2 seconds`;
    } catch (_) {
      if (!stopped) {
        result.replaceChildren(el('p', 'The current result is unavailable. No finding can be inferred.'));
        status.textContent = 'Reconnecting… Check your connection or refresh the result.';
      }
    } finally { inFlight = false; refreshButton.disabled = stopped; }
  }
  function visibility() {
    clearInterval(timer);
    if (!stopped && document.visibilityState === 'visible') {
      refresh(); timer = setInterval(refresh, 2000);
    }
  }
  refreshButton.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', visibility);
  await refresh();
  if (stopped) return;
  visibility();
  setup = await window.checkSetup(setupHost, person.id, () => {});
  if (stopped) setup.dispose();
};
