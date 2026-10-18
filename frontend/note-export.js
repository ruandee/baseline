// BL-33: "Send to sign-off queue" PREVIEW for the resident page (decision 020).
//
// The button fetches GET /v1/patients/{id}/assessments/{aid}/note and shows the preliminary
// FHIR R4 DocumentReference it returns. It is NOT EHR writeback: nothing is sent to any
// clinical system or real sign-off queue; this module only issues that one GET.
//
// Mount hook (for the /resident page owner, BL-19): load this script before baseline.js and,
// where the page has the current assessment, append the panel:
//
//   const note = window.noteExportPanel && data.latest_assessment
//     && window.noteExportPanel(h, ctx.id, data.latest_assessment.id);
//   if (note) main.append(note);
//
// `h` needs `api(path)` (rejecting with an Error carrying `status`) and `el(tag, text, attrs)`,
// as baseline.js already passes to window.renderResident.
(function () {
  const UNAVAILABLE = {
    404: 'This assessment is not available to this account.',
    409: 'No current draft note: the SBAR was invalidated by a source change or does not exist. '
       + 'A new usable check is needed first.'};
  const FACT = 'urn:baseline:evidence:fact';
  const CHECK = 'urn:baseline:evidence:voice-check';

  function decodeAttachment(note) {
    const data = note && note.content && note.content[0] && note.content[0].attachment
      && note.content[0].attachment.data;
    if (typeof data !== 'string') return null;
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    return new TextDecoder('utf-8').decode(bytes);
  }

  function citationSummary(note) {
    const related = (note.context && note.context.related) || [];
    const facts = related.filter((r) => r.identifier && r.identifier.system === FACT).length;
    const checks = related.filter((r) => r.identifier && r.identifier.system === CHECK).length;
    return `${facts} source fact citation(s), ${checks} voice-check citation(s)`;
  }

  window.noteExportPanel = function (h, patientId, assessmentId) {
    const section = h.el('section', '', {class: 'bl-section bl-note-export'});
    const button = h.el('button', 'Send to sign-off queue (preview)', {type: 'button'});
    const notice = h.el('p', 'Preview only: shows the draft note payload. Nothing is sent to an '
      + 'EHR or a real sign-off queue.', {class: 'bl-muted'});
    const output = h.el('div', '', {hidden: ''});
    section.append(h.el('h2', 'Draft note'), notice, button, output);
    button.addEventListener('click', async () => {
      button.disabled = true;
      output.hidden = false;
      output.replaceChildren(h.el('p', 'Loading the draft note…'));
      try {
        const note = await h.api(
          `/v1/patients/${encodeURIComponent(patientId)}/assessments/${encodeURIComponent(assessmentId)}/note`);
        output.replaceChildren(
          h.el('p', `Not sent. ${note.resourceType}, docStatus ${note.docStatus}, status `
            + `${note.status}; ${citationSummary(note)}.`, {class: 'bl-status', 'data-state': 'ok'}),
          h.el('h3', 'Note text (exact SBAR)'),
          h.el('pre', decodeAttachment(note) || '(no attachment text)', {class: 'bl-note-text'}),
          h.el('h3', 'FHIR R4 DocumentReference payload'),
          h.el('pre', JSON.stringify(note, null, 2), {class: 'bl-note-json'}));
      } catch (error) {
        // Never fall back to an older payload: an unavailable note is shown as unavailable.
        output.replaceChildren(h.el('p', UNAVAILABLE[error.status]
          || `Could not load the draft note (${error.message}).`,
        {class: 'bl-status', 'data-state': 'error'}));
      } finally {
        button.disabled = false;
      }
    });
    return section;
  };
})();
