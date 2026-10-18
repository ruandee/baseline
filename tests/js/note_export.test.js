'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {loadPage, until} = require('./harness');

const originalText = 'S: Zoë has a change.\nB: Poor intake.\nA: Change present.\nR: Suggest Run 4AT now.';
function original() {
  return {resourceType: 'DocumentReference', id: 'a1', status: 'current', docStatus: 'preliminary',
    meta: {tag: [{system: 'urn:baseline:tag', code: 'synthetic'}]},
    identifier: [{system: 'urn:baseline:assessment', value: 'a1'}],
    subject: {reference: 'Patient/p1'}, author: [{type: 'Device', display: 'Baseline drafter'}],
    extension: [{url: 'urn:baseline:fhir:StructureDefinition/sbar-source', valueCode: 'template'},
      {url: 'urn:baseline:fhir:StructureDefinition/sbar-sentence', extension: [
        {url: 'text', valueString: 'Poor intake.'}, {url: 'evidence', valueReference: {display: 'fact'}}]}],
    context: {period: {start: '2026-10-17T12:00:00Z'}, related: [{identifier: {
      system: 'urn:baseline:evidence:fact', value: 'fact-1'}}]},
    content: [{attachment: {contentType: 'text/plain; charset=utf-8',
      data: Buffer.from(originalText).toString('base64'), hash: 'oldhash', size: Buffer.byteLength(originalText)}}]};
}

async function panel(handler) {
  const page = loadPage('/check?mode=live&mock=1');
  await until(() => page.main.querySelector('.bl-record'));
  Object.assign(page.ctx, {TextEncoder, TextDecoder, atob, btoa});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../frontend/note-export.js'), 'utf8'), page.ctx);
  const calls = [];
  const h = {el: page.ctx.el, api: async (...args) => { calls.push(args); return handler(calls.length); }};
  const section = page.window.noteExportPanel(h, 'p1', 'a1');
  page.main.replaceChildren(section);
  section.querySelector('button').click();
  await until(() => !section.querySelector('button').disabled);
  return {section, calls};
}

test('exact original preview and human edit remain separate; edits lose inherited evidence claims', async () => {
  const source = original();
  const snapshot = JSON.stringify(source);
  const {section, calls} = await panel(() => source);
  assert.equal(section.querySelector('.bl-note-text').textContent, originalText);
  const editor = section.querySelector('.bl-note-editor');
  assert.equal(editor.tagName, 'TEXTAREA');
  assert.equal(editor.value, originalText);
  const edited = 'S: Zoë says <script>bad()</script>\nR: Human follow-up.';
  editor.value = edited;
  section.querySelector('.bl-edit-preview').click();
  await until(() => section.querySelector('.bl-human-note-json'));
  const note = JSON.parse(section.querySelector('.bl-human-note-json').textContent);
  assert.equal(Buffer.from(note.content[0].attachment.data, 'base64').toString(), edited);
  assert.equal(note.content[0].attachment.size, Buffer.byteLength(edited));
  assert.equal(note.docStatus, 'preliminary');
  assert.match(note.author[0].display, /Human editor.*unverified/);
  assert.equal(note.authenticator, undefined);
  assert.equal(note.content[0].attachment.hash, undefined, 'old hash must not survive editing');
  assert.equal(note.context.related, undefined, 'old citations do not verify human changes');
  assert.equal(note.extension.some((e) => e.url.endsWith('/sbar-sentence')), false);
  assert.equal(note.extension.some((e) => e.url.endsWith('/assessment-provenance')), false);
  assert.equal(note.relatesTo[0].code, 'transforms');
  assert.deepEqual(note.relatesTo[0].target.identifier, source.identifier[0]);
  assert.match(note.text.div, /&lt;script&gt;/);
  assert.doesNotMatch(note.text.div, /<script>/);
  assert.equal(JSON.stringify(source), snapshot, 'validated original is immutable');
  assert.equal(section.querySelector('.bl-note-text').textContent, originalText);
  assert.equal(calls.length, 2, 're-authorize/revalidate before preparing the edited payload');
  calls.forEach((args) => assert.deepEqual(args, ['/v1/patients/p1/assessments/a1/note']));
});

for (const status of [404, 409, 503]) {
  test(`failed freshness check (${status}) removes stale original and edited payloads`, async () => {
    const {section} = await panel((count) => {
      if (count > 1) throw Object.assign(new Error('unavailable'), {status});
      return original();
    });
    section.querySelector('.bl-note-editor').value = 'private human draft';
    section.querySelector('.bl-edit-preview').click();
    await until(() => !section.querySelector('.bl-note-editor'));
    assert.doesNotMatch(section.textContent, /Poor intake|private human draft/);
    assert.equal(section.querySelector('.bl-note-json'), null);
    assert.equal(section.querySelector('.bl-human-note-json'), null);
  });
}

test('same-assessment enrichment change requires reload rather than reusing stale edits', async () => {
  const {section} = await panel((count) => {
    const note = original();
    if (count > 1) note.content[0].attachment.data = Buffer.from('updated server draft').toString('base64');
    return note;
  });
  section.querySelector('.bl-edit-preview').click();
  await until(() => !section.querySelector('.bl-note-editor'));
  assert.match(section.textContent, /source draft changed/);
  assert.doesNotMatch(section.textContent, /Poor intake/);
});
