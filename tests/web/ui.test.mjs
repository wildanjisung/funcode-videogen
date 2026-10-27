import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { JSDOM } from 'jsdom';

const html = await readFile(new URL('../../src/videogen/web/static/index.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../../src/videogen/web/static/app.js', import.meta.url), 'utf8');
const projectId = 'a'.repeat(32);
const previewId = 'b'.repeat(32);
const renderId = 'c'.repeat(32);

function fixture() {
  const style = { schema_version: 3, width_fraction: .84, size_fraction: null, top_fraction: .15,
    center_fraction: .5, alignment: 'center', text_color: '#000000', background_color: '#FFFFFF',
    background_enabled: true, auto_size: false };
  return { id: projectId, name: 'Example.mp4', ready: true, source_ready: true, draft_version: 3,
    created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z', last_job_id: null,
    media: { display_width: 720, display_height: 1280, duration: 8, audio_start: 0, video_start: 0 },
    words: [{ text: 'story', start: .1, end: 1 }], transcript: 'story', revisions: [],
    draft: { hook: { text: 'JUDUL AWAL', enabled: true, manual: false, duration: 2, full_video: false },
      hook_style: style, subtitle_style: { ...style, top_fraction: .74, background_enabled: false,
        text_color: '#FFFFFF', active_word_color: '#FFFF00', outline_color: '#101010', outline_fraction: .025 } } };
}

async function until(check) {
  for (let tries = 0; tries < 150; tries++) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.ok(check(), 'UI did not reach the expected state');
}

async function editor(t, options = {}) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:8765', runScripts: 'outside-only' });
  const { window } = dom;
  t.after(() => window.close());
  window.structuredClone = structuredClone;
  window.ResizeObserver = class { observe() {} disconnect() {} };
  window.matchMedia = () => ({ matches: true });
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.HTMLMediaElement.prototype.pause = () => {};
  window.HTMLMediaElement.prototype.load = () => {};
  window.localStorage.setItem('videogen-project', projectId);
  const project = fixture();
  const calls = [];
  const job = (operation, id) => ({ id, project_id: projectId, operation, status: 'running', version: project.draft_version, message: '', result: null });
  let preview;
  window.fetch = async (path, request = {}) => {
    const method = request.method || 'GET';
    const body = request.body ? JSON.parse(request.body) : undefined;
    calls.push({ path, method, body });
    let data;
    if (path === '/api/status') data = { setup: { ready: true, checks: {} }, active_job: null, max_upload_bytes: 10000000 };
    else if (path === '/api/projects') data = [project];
    else if (path === `/api/projects/${projectId}`) data = project;
    else if (path.endsWith('/draft')) {
      if (options.saveError) return { ok: false, status: 409, json: async () => ({ detail: 'Draft berubah di tab lain. Muat ulang proyek.' }) };
      assert.equal(body.version, project.draft_version);
      for (const key of ['hook', 'hook_style', 'subtitle_style']) if (body[key]) Object.assign(project.draft[key], body[key]);
      project.draft_version++;
      data = project;
    } else if (path.endsWith('/previews')) {
      preview = { ...job('preview', previewId), status: 'completed', result: { image_url: '/api/previews/' + previewId,
        layout: { timestamp: 0, all_cues_valid: !options.invalidLayout, validation_errors: options.invalidLayout ? [{ start: 1.2, reason: 'Subtitle tidak muat' }] : [],
          cue_starts: [.1, 1.2], panel_bounds: [], subtitle_bounds: null, hook_visible: false, subtitle_visible: false, words_sha256: 'abc' } } };
      data = job('preview', previewId);
    } else if (path === '/api/jobs/' + previewId) {
      if (options.waitPreview) await options.waitPreview;
      data = preview;
    } else if (path.endsWith('/renders')) {
      assert.equal(body.version, preview.version);
      assert.equal(body.preview_job_id, previewId);
      data = job('render', renderId);
    } else if (path === '/api/jobs/' + renderId) {
      data = { ...job('render', renderId), status: 'completed', result: { revision_id: '123456789abc' } };
    } else throw new Error('Unexpected API request: ' + method + ' ' + path);
    return { ok: true, status: 200, json: async () => structuredClone(data) };
  };
  window.eval(script);
  const $ = (id) => window.document.getElementById(id);
  await until(() => $('document-name').textContent === project.name && !$('editor-fields').disabled);
  const input = (id, value) => { $(id).value = value; $(id).dispatchEvent(new window.Event('input', { bubbles: true })); };
  return { $, input, window, calls, project };
}

test('saved draft explains why Save is inactive and offers automatic preparation for render', async (t) => {
  const { $ } = await editor(t);
  assert.equal($('save').disabled, true);
  assert.match($('save-status').textContent, /tersimpan/i);
  assert.equal($('render').disabled, false);
  assert.match($('workflow-message').textContent, /preview.*otomatis/i);
});

test('typing hook keeps Save available after fractional position input', async (t) => {
  const { $, input } = await editor(t);
  input('position-x', '50.12');
  input('hook-text', 'HOOK BARU');
  assert.equal($('position-x').validity.stepMismatch, false);
  assert.equal($('save').disabled, false);
  assert.equal($('render').disabled, false);
});

test('Render saves hook, validates a fresh preview, then renders exactly once', async (t) => {
  const { $, input, calls } = await editor(t);
  input('hook-text', 'HOOK BARU');
  $('render').click();
  $('render').click();
  await until(() => calls.some((call) => call.path.endsWith('/renders')));
  const mutations = calls.filter((call) => ['PUT', 'POST'].includes(call.method));
  assert.deepEqual(mutations.map((call) => call.path.split('/').at(-1)), ['draft', 'previews', 'renders']);
  assert.equal(mutations[0].body.hook.text, 'HOOK BARU');
});

test('a malformed numeric field identifies its name and can be focused without losing the value', async (t) => {
  const { $, input, window } = await editor(t);
  input('position-x', '');
  assert.equal($('render').disabled, true);
  assert.equal($('save').disabled, true);
  assert.match($('workflow-message').textContent, /Posisi X/);
  $('workflow-action').click();
  assert.equal(window.document.activeElement, $('position-x'));
  assert.equal($('position-x').value, '');
});

test('an empty hook is savable as a draft but explains how to enable rendering', async (t) => {
  const { $, input, window } = await editor(t);
  input('hook-text', '');
  assert.equal($('save').disabled, false);
  assert.equal($('render').disabled, true);
  assert.match($('workflow-message').textContent, /hook/i);
  $('workflow-action').click();
  assert.equal(window.document.activeElement, $('hook-text'));
});

test('invalid cue layout stops automatic rendering and provides a correction action', async (t) => {
  const { $, calls } = await editor(t, { invalidLayout: true });
  $('render').click();
  await until(() => !$('validation').hidden);
  assert.equal(calls.some((call) => call.path.endsWith('/renders')), false);
  assert.equal($('render').disabled, true);
  assert.match($('workflow-message').textContent, /subtitle|cue/i);
  assert.equal($('workflow-action').hidden, false);
});

test('editing while automatic preview is pending never renders an older hook', async (t) => {
  let release;
  const waitPreview = new Promise((resolve) => { release = resolve; });
  t.after(() => release());
  const { $, input, calls } = await editor(t, { waitPreview });
  $('render').click();
  await until(() => calls.some((call) => call.path === '/api/jobs/' + previewId));
  input('hook-text', 'VERSI LEBIH BARU');
  release();
  await until(() => $('job-title').textContent === 'Selesai');
  assert.equal(calls.some((call) => call.path.endsWith('/renders')), false);
  assert.equal($('save').disabled, false);
});

test('save conflict remains visible and does not start preview or rendering', async (t) => {
  const { $, input, calls } = await editor(t, { saveError: true });
  input('hook-text', 'HOOK BARU');
  $('render').click();
  await until(() => $('notice').textContent.includes('tab lain'));
  assert.equal(calls.some((call) => call.path.endsWith('/previews') || call.path.endsWith('/renders')), false);
  assert.equal($('notice').hidden, false);
});

test('manual preview does not render until the user explicitly chooses Render MP4', async (t) => {
  const { $, calls } = await editor(t);
  $('preview').click();
  await until(() => $('workflow-title').textContent === 'Siap dirender');
  assert.equal(calls.some((call) => call.path.endsWith('/renders')), false);
  assert.equal($('render').disabled, false);
  const count = calls.filter((call) => call.path.endsWith('/previews')).length;
  $('render').click();
  await until(() => calls.some((call) => call.path.endsWith('/renders')));
  assert.equal(calls.filter((call) => call.path.endsWith('/previews')).length, count);
});
