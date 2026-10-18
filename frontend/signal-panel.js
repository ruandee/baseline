// Explicit per-modality nurse readback. Missing measurements never become normal findings.
(function () {
  const LABEL = {unavailable: 'Not available', enrolling: 'Baseline incomplete',
    none: 'Similar to recorded baseline', provisional: 'Possible change', change: 'Measured change'};
  window.signalPanel = function (h, ctx, data) {
    const assessment = data.latest_assessment;
    const entries = Object.entries((assessment && assessment.modalities) || {}).filter(([name]) => name !== 'speech');
    if (!entries.length) return null;
    const section = h.el('section', '', {class: 'bl-section bl-signal-panel'});
    section.append(h.el('h2', 'Other measured signals'),
      h.el('p', 'Engineering comparisons with recorded baselines. Review the original observations.'));
    if (assessment.corroborated) section.append(h.el('p', 'Corroborated by current signal modalities.', {class: 'bl-signal-corroborated'}));
    for (const [name, result] of entries) {
      const card = h.el('article', '', {class: 'bl-signal'});
      const params = result.params || {};
      card.append(h.el('h3', name === 'vitals' ? 'Resting vital observations' : name),
        h.el('p', LABEL[result.status] || 'Unknown', {class: 'bl-signal-status'}));
      if (result.ts) card.append(h.el('p', `Measured ${h.formatTime(result.ts)}${result.current ? '' : ' (outside this comparison window)'}`));
      if (params.threshold_status === 'engineering_unvalidated') card.append(h.el('p', 'Thresholds are engineering assumptions; clinical validation has not been performed.'));
      for (const [feature, score] of Object.entries(result.per_feature || {})) {
        const meta = (params.feature_meta || {})[feature] || {label: feature, unit: ''};
        card.append(h.el('p', `${meta.label}: ${score.value} ${meta.unit || ''}`, {class: 'bl-signal-value'}));
      }
      for (const feature of params.unavailable_features || []) {
        const meta = (params.feature_meta || {})[feature] || {label: feature};
        card.append(h.el('p', `${meta.label}: unavailable`, {class: 'bl-muted'}));
      }
      for (const id of result.evidence_ids || []) {
        if (id.startsWith('check:')) continue; // voice capture is handled by its existing panel
        const open = h.el('button', 'Open observation source', {type: 'button', class: 'bl-link bl-signal-source'});
        const output = h.el('div', '', {class: 'bl-signal-source-output'});
        open.addEventListener('click', async () => {
          open.disabled = true; output.replaceChildren(h.el('p', 'Loading observation?'));
          try {
            const current = await h.api(`/v1/patients/${encodeURIComponent(ctx.id)}/overview?days=30`);
            if (!current.latest_assessment || current.latest_assessment.id !== assessment.id) throw new Error('Assessment changed; reload before reviewing sources.');
            const evidence = await h.api(`/v1/patients/${encodeURIComponent(ctx.id)}/evidence/${encodeURIComponent(id)}`);
            output.replaceChildren(h.el('p', `${evidence.source_kind} ? ${evidence.author_role} ? recorded ${h.formatTime(evidence.recorded_at)}`),
              h.el('blockquote', evidence.quote, {class: 'bl-source-quote'}));
          } catch (error) {
            output.replaceChildren(h.el('p', `Observation unavailable (${error.message}).`, {class: 'bl-status', 'data-state': 'error'}));
          } finally { open.disabled = false; }
        });
        card.append(open, output);
      }
      section.append(card);
    }
    return section;
  };
})();
