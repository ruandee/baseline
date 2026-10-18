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
  const EXT = 'urn:baseline:fhir:StructureDefinition/';

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

  function humanDraft(original, text) {
    if (!text.trim() || text.length > 20000) throw new Error('Enter a draft of up to 20,000 characters.');
    const note = JSON.parse(JSON.stringify(original));
    const bytes = new TextEncoder().encode(text);
    const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    note.id = `human-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
    note.identifier = [{system: 'urn:baseline:human-draft', value: note.id}];
    note.date = new Date().toISOString();
    note.docStatus = 'preliminary';
    delete note.authenticator;
    note.author = [{display: 'Human editor (unverified local draft)'}];
    note.description = 'Human-edited local draft. Not model-verified, signed, saved or sent. '
      + 'The original assessment is provenance only, not evidence for the edited wording.';
    note.meta.tag.push({system: 'urn:baseline:tag', code: 'human-edited-unverified',
                        display: 'Human-edited; not verified or signed'});
    // Never carry the server's sentence-to-evidence claims onto arbitrary human wording.
    note.extension = [{url: EXT + 'sbar-source', valueCode: 'human-edited-unverified'}];
    note.relatesTo = [{code: 'transforms', target: {type: 'DocumentReference',
      identifier: original.identifier[0], display: 'Original validated SBAR draft (basis only)'}}];
    if (note.context) delete note.context.related;
    note.text = {status: 'generated', div: '<div xmlns="http://www.w3.org/1999/xhtml">'
      + text.split('\n').map((line) => `<p>${escape(line) || '<br/>'}</p>`).join('') + '</div>'};
    note.content = [{attachment: {contentType: 'text/plain; charset=utf-8', language: 'en',
      data: btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join('')), size: bytes.length,
      title: 'Human-edited SBAR draft (unverified, preliminary)', creation: note.date}}];
    return note;
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
        const originalText = decodeAttachment(note);
        if (originalText === null) throw new Error('Draft attachment is unavailable.');
        output.replaceChildren(
          h.el('p', `Not sent. ${note.resourceType}, docStatus ${note.docStatus}, status `
            + `${note.status}; ${citationSummary(note)}.`, {class: 'bl-status', 'data-state': 'ok'}),
          h.el('h3', 'Note text (exact SBAR)'),
          h.el('pre', originalText, {class: 'bl-note-text'}),
          h.el('h3', 'FHIR R4 DocumentReference payload'),
          h.el('pre', JSON.stringify(note, null, 2), {class: 'bl-note-json'}));
        const editorId = `bl-human-draft-${assessmentId}`;
        const editor = h.el('textarea', '', {id: editorId, rows: '12', maxlength: '20000',
                                             class: 'bl-note-editor'});
        editor.value = originalText;
        const preview = h.el('button', 'Preview edited draft', {type: 'button', class: 'bl-edit-preview'});
        const editedOutput = h.el('div', '', {class: 'bl-human-preview', hidden: ''});
        output.append(h.el('label', 'Edit a local human draft', {for: editorId}), editor,
          h.el('p', 'Edits stay in this page. They are not model-verified, signed, saved or sent. '
            + 'Original citations do not verify edited wording.', {class: 'bl-muted'}), preview, editedOutput);
        preview.addEventListener('click', async () => {
          preview.disabled = true;
          editedOutput.hidden = false;
          editedOutput.replaceChildren(h.el('p', 'Checking the current draft…'));
          try {
            const latest = await h.api(
              `/v1/patients/${encodeURIComponent(patientId)}/assessments/${encodeURIComponent(assessmentId)}/note`);
            if (JSON.stringify(latest) !== JSON.stringify(note)) {
              output.replaceChildren(h.el('p', 'The source draft changed. Reload it before editing.',
                {class: 'bl-status', 'data-state': 'error'}));
              return;
            }
            const edited = humanDraft(note, editor.value);
            editedOutput.replaceChildren(
              h.el('p', 'Human-edited, unverified preliminary draft. Not signed, saved or sent.',
                {class: 'bl-status', 'data-state': 'pending'}),
              h.el('pre', JSON.stringify(edited, null, 2), {class: 'bl-human-note-json'}));
          } catch (error) {
            // Do not retain an old payload on revocation, source change or failed revalidation.
            output.replaceChildren(h.el('p', UNAVAILABLE[error.status]
              || `Draft unavailable (${error.message}). Reload before editing.`,
              {class: 'bl-status', 'data-state': 'error'}));
          } finally {
            preview.disabled = false;
          }
        });
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
