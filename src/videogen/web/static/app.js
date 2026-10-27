const $ = (id) => document.getElementById(id);
const clone = (value) => structuredClone(value);
const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const state = { project: null, draft: null, target: 'hook', dirty: false, stamp: 0,
  preview: null, mode: 'frame', time: 0, busy: false, job: null, xhr: null,
  history: [], future: [], saving: null, load: 0, setupReady: false, dragging: false, deferredPreview: null, renderIntent: null, maxUpload: 2 * 1024 ** 3 };
const styleKeys = ['width_fraction', 'size_fraction', 'top_fraction', 'center_fraction', 'alignment',
  'text_color', 'background_color', 'background_enabled', 'auto_size'];
const subtitleKeys = [...styleKeys, 'active_word_color', 'outline_color', 'outline_fraction'];
const pick = (object, keys) => Object.fromEntries(keys.filter((key) => key in object).map((key) => [key, object[key]]));
let pollTimer;

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((error) => `${error.loc?.slice(1).join('.')}: ${error.msg}`).join('\n') : data.detail;
    throw new Error(detail || `Permintaan gagal (${response.status}).`);
  }
  return data;
}

function notify(message = '', error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}

function clock(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${(value % 60).toFixed(2).padStart(5, '0')}`;
}

function invalidFields() {
  return [...$('editor-fields').querySelectorAll('input,textarea,select')].filter((element) => {
    const relevant = !element.matches(':disabled') && !element.closest('[hidden]');
    const invalid = relevant && (!element.checkValidity() || (element.type === 'number' && !Number.isFinite(element.valueAsNumber)));
    element.setAttribute('aria-invalid', String(invalid));
    return invalid;
  });
}

function validFields() { return invalidFields().length === 0; }

function focusControl(id, target) {
  if (target && target !== state.target) setTarget(target);
  $(id).scrollIntoView({ block: 'nearest' });
  $(id).focus();
}

function fieldIssue() {
  const element = invalidFields()[0];
  if (!element) return null;
  const name = { 'position-x': 'Posisi X', 'position-y': 'Posisi Y', 'font-size': 'Ukuran teks',
    'text-width': 'Lebar teks', 'hook-duration': 'Durasi hook', 'outline-size': 'Ketebalan stroke', 'hook-text': 'Judul hook' }[element.id] || 'Nilai pengaturan';
  let message = `${name} belum valid. Periksa nilai yang ditandai.`;
  if (element.type === 'number' && !Number.isFinite(element.valueAsNumber)) message = `${name} harus berupa angka. Isi kolom yang ditandai.`;
  else if (element.validity.rangeUnderflow) message = `${name} minimal ${element.min}.`;
  else if (element.validity.rangeOverflow) message = `${name} maksimal ${element.max}.`;
  else if (element.validity.stepMismatch) message = `${name} harus berupa angka bulat.`;
  return { title: 'Periksa pengaturan', message, tone: 'warning', action: 'Perbaiki nilai', run: () => focusControl(element.id) };
}

function hookIssue() {
  if (!state.draft?.hook.enabled) return null;
  const hook = state.draft.hook;
  const rows = hook.text.trim().split('\n');
  if (!hook.text.trim()) return { title: 'Hook masih kosong', message: 'Isi judul hook, atau matikan Tampilkan hook jika hanya ingin subtitle.', tone: 'warning', action: 'Isi hook', run: () => focusControl('hook-text', 'hook') };
  if (hook.manual && (rows.length > 3 || rows.some((line) => !line.trim()))) return { title: 'Periksa baris hook', message: 'Hook manual memakai satu sampai tiga baris tanpa baris kosong. Atur pemenggalan sebelum preview atau render.', tone: 'warning', action: 'Atur baris hook', run: () => focusControl('hook-text', 'hook') };
  return null;
}

function previewCurrent() {
  return Boolean(state.preview && !state.dirty && state.preview.version === state.project?.draft_version);
}

function fixSubtitle() {
  setTarget('subtitle');
  const first = state.preview?.result.layout.validation_errors[0];
  if (first) setTime(first.timestamp ?? first.start ?? 0, true);
  focusControl('font-size');
}

function workflow(issue) {
  let info;
  if (!state.project?.ready) info = state.busy ? { title: 'Menyiapkan transkrip', message: 'Tunggu transkripsi selesai. Setelah itu hook dan subtitle dapat diedit.' } : { title: 'Mulai dengan video', message: 'Pilih video untuk membuat transkrip, lalu atur hook dan subtitle.' };
  else if (state.dragging) info = { title: 'Atur posisi teks', message: 'Lepaskan drag untuk menerapkan posisi. Escape membatalkan pergeseran.' };
  else if (state.renderIntent) info = { title: 'Menyiapkan render', message: state.saving ? 'Menyimpan perubahan hook dan subtitle sebelum render.' : 'Memperbarui preview dan memeriksa seluruh subtitle. Render dimulai otomatis setelah semuanya valid.' };
  else if (state.saving) info = { title: 'Menyimpan draft', message: 'Tunggu sebentar. Render MP4 dapat dipilih setelah penyimpanan selesai.' };
  else if (state.busy) info = { title: state.job?.operation === 'render' ? 'Video sedang dirender' : 'Pekerjaan sedang berjalan', message: 'Progress tampil di bawah preview. Tunggu sampai selesai atau pilih Batalkan.' };
  else if (issue) info = issue;
  else if (hookIssue()) info = hookIssue();
  else if (previewCurrent() && !state.preview.result.layout.all_cues_valid) info = { title: 'Subtitle belum muat', message: 'Ada cue subtitle yang tidak muat. Kecilkan ukuran teks atau perbesar lebarnya, lalu klik Render MP4 untuk memeriksa ulang.', tone: 'warning', action: 'Perbaiki subtitle', run: fixSubtitle };
  else if (previewCurrent()) info = { title: 'Siap dirender', message: 'Preview terbaru sudah valid. Klik Render MP4 untuk menghasilkan video.', tone: 'success' };
  else info = { title: state.dirty ? 'Perubahan siap diproses' : 'Draft tersimpan', message: state.dirty ? 'Klik Render MP4. Perubahan akan disimpan dan preview diperiksa otomatis sebelum video dirender.' : 'Klik Render MP4. Preview akan diperbarui dan diperiksa otomatis sebelum video dirender.' };
  $('workflow-title').textContent = info.title;
  $('workflow-message').textContent = info.message;
  $('workflow-status').dataset.tone = info.tone || 'info';
  $('workflow-action').hidden = !info.action;
  $('workflow-action').textContent = info.action || '';
  $('workflow-action').onclick = info.run || null;
  return info;
}

function buttons() {
  const ready = Boolean(state.project?.ready);
  const waiting = state.busy || Boolean(state.saving) || state.dragging || Boolean(state.renderIntent);
  $('video-file').disabled = waiting || !state.setupReady;
  $('drop-zone').classList.toggle('busy', waiting || !state.setupReady);
  $('editor-fields').disabled = !ready;
  const issue = fieldIssue();
  const hookInvalid = hookIssue();
  const layoutInvalid = previewCurrent() && !state.preview.result.layout.all_cues_valid;
  $('save').disabled = !ready || !state.dirty || Boolean(state.saving) || state.dragging || Boolean(state.renderIntent) || Boolean(issue);
  $('preview').disabled = !ready || waiting || Boolean(issue) || Boolean(hookInvalid);
  $('render').disabled = !ready || waiting || Boolean(issue) || Boolean(hookInvalid) || layoutInvalid;
  $('scrub').disabled = !ready;
  $('next-cue').disabled = !ready || waiting;
  $('copy-transcript').disabled = !ready;
  $('source-view').disabled = !ready;
  $('prepare-playback').disabled = waiting;
  $('undo').disabled = !ready || !state.history.length;
  $('redo').disabled = !ready || !state.future.length;
  $('retry-transcribe').hidden = !state.project?.source_ready || ready;
  $('retry-transcribe').disabled = waiting || !state.setupReady;
  for (const element of $('project-list').querySelectorAll('button')) element.disabled = waiting;
  $('save-status').textContent = state.saving ? 'Menyimpan…' : state.dirty ? 'Ada perubahan belum disimpan' : ready ? 'Semua perubahan tersimpan' : 'Video menjadi cerita.';
  $('save').textContent = state.saving ? 'Menyimpan…' : ready && !state.dirty ? 'Draft tersimpan' : 'Simpan draft';
  $('save').title = !ready ? 'Selesaikan transkripsi terlebih dahulu.' : issue?.message || (!state.dirty ? 'Semua perubahan sudah tersimpan.' : 'Simpan perubahan tanpa merender video.');
  $('render-label').textContent = state.renderIntent ? 'Menyiapkan render…' : state.busy && state.job?.operation === 'render' ? 'Merender…' : 'Render MP4';
  const next = workflow(issue);
  $('render').title = next.message;
  $('preview').title = hookInvalid?.message || issue?.message || 'Simpan perubahan dan periksa satu frame tanpa merender video.';
  $('preview').textContent = previewCurrent() ? 'Perbarui frame' : 'Perbarui preview';
}

function setTarget(target) {
  state.target = target;
  $('hook-tab').setAttribute('aria-selected', String(target === 'hook'));
  $('subtitle-tab').setAttribute('aria-selected', String(target === 'subtitle'));
  $('scope-label').textContent = target === 'hook' ? 'Hook' : 'Seluruh video';
  $('hook-fields').hidden = target !== 'hook';
  $('subtitle-scope').hidden = target !== 'subtitle';
  for (const id of ['active-color-field', 'outline-color-field', 'outline-size-field']) $(id).hidden = target !== 'subtitle';
  $('auto-size-field').hidden = target !== 'hook';
  inspector();
  handles();
  buttons();
}

function inspector() {
  if (!state.draft) return;
  const hook = state.draft.hook;
  const style = state.draft[`${state.target}_style`];
  const media = state.project.media;
  $('hook-text').value = hook.text;
  $('hook-enabled').checked = hook.enabled;
  $('hook-manual').checked = hook.manual;
  $('hook-duration').value = hook.duration;
  $('hook-full').checked = hook.full_video;
  $('hook-duration').disabled = hook.full_video;
  const fallback = state.target === 'hook' ? Math.max(18, Math.ceil(media.display_height * .022), Math.round(Math.min(media.display_height * .03, media.display_width * .06))) : Math.max(18, Math.round(Math.min(media.display_height * .045, media.display_width * .08)));
  $('font-size').max = media.display_height;
  $('font-size').value = style.size_fraction == null ? fallback : Math.max(1, Math.round(style.size_fraction * media.display_height));
  $('text-width').value = +(style.width_fraction * 100).toFixed(2);
  $('position-x').value = +(style.center_fraction * 100).toFixed(2);
  $('position-y').value = +(style.top_fraction * 100).toFixed(2);
  $('alignment').value = style.alignment;
  $('text-color').value = style.text_color;
  $('background-color').value = style.background_color;
  $('background-enabled').checked = style.background_enabled;
  $('auto-size').checked = style.auto_size;
  $('active-color').value = style.active_word_color || '#ffff00';
  $('outline-color').value = style.outline_color || '#101010';
  $('outline-size').value = +((style.outline_fraction ?? .025) * 100).toFixed(2);
  $('font-name').textContent = style.font?.family || 'Helvetica Neue';
  $('font-style').textContent = style.font?.style || 'Bold';
}

function changed(mutator, redraw = false) {
  if (!state.draft) return;
  state.history.push(clone(state.draft));
  state.history = state.history.slice(-60);
  state.future = [];
  mutator(state.draft);
  invalidate();
  if (redraw) { inspector(); buttons(); }
}

function invalidate() {
  state.renderIntent = null;
  state.dirty = true;
  state.stamp += 1;
  $('preview-state').textContent = 'Gaya berubah. Frame ini belum menampilkan perubahan terakhir.';
  $('preview-state').parentElement.classList.add('stale');
  $('validation').hidden = true;
  handles();
  buttons();
}

function undo(redo = false) {
  const from = redo ? state.future : state.history;
  const to = redo ? state.history : state.future;
  if (!from.length) return;
  to.push(clone(state.draft));
  state.draft = from.pop();
  invalidate();
  inspector();
  buttons();
}

async function saveDraft() {
  if (state.saving) {
    try { await state.saving; return !state.dirty; } catch { return false; }
  }
  if (!state.dirty) return true;
  if (!validFields()) return false;
  const projectId = state.project.id;
  const stamp = state.stamp;
  const draft = clone(state.draft);
  const payload = { version: state.project.draft_version,
    hook: pick(draft.hook, ['text', 'enabled', 'manual', 'duration', 'full_video']),
    hook_style: pick(draft.hook_style, styleKeys), subtitle_style: pick(draft.subtitle_style, subtitleKeys) };
  state.saving = api(`/api/projects/${projectId}/draft`, { method: 'PUT', body: JSON.stringify(payload) });
  buttons();
  try {
    const response = await state.saving;
    if (state.project?.id !== projectId) return false;
    state.project.draft_version = response.draft_version;
    state.dirty = stamp !== state.stamp;
    if (!state.dirty) state.draft = clone(response.draft);
    return !state.dirty;
  } catch (error) {
    notify(error.message, true);
    return false;
  } finally {
    state.saving = null;
    buttons();
  }
}

async function refreshProjects() {
  const projects = await api('/api/projects');
  $('project-list').replaceChildren();
  $('empty-projects').hidden = projects.length > 0;
  for (const project of projects) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `project-item${state.project?.id === project.id ? ' selected' : ''}`;
    button.disabled = state.busy;
    const film = document.createElement('span');
    film.className = 'film-icon';
    film.textContent = project.name.toLowerCase().endsWith('.mov') ? 'MOV' : 'MP4';
    const text = document.createElement('span');
    const name = document.createElement('strong');
    name.textContent = project.name;
    name.title = project.name;
    const date = document.createElement('small');
    date.textContent = project.ready ? new Date(project.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' }) : 'Belum ditranskripsi';
    text.append(name, date);
    button.append(film, text);
    button.addEventListener('click', () => openProject(project.id));
    $('project-list').append(button);
  }
}

async function openProject(id, followJob = true) {
  if (state.dirty && !window.confirm('Perubahan belum disimpan. Buka proyek lain dan buang perubahan ini?')) return;
  const load = ++state.load;
  try {
    const project = await api(`/api/projects/${id}`);
    if (load !== state.load) return;
    state.project = project;
    state.renderIntent = null;
    state.draft = project.ready ? clone(project.draft) : null;
    state.dirty = false;
    state.stamp += 1;
    state.history = [];
    state.future = [];
    state.preview = null;
    state.time = 0;
    state.sourceFailed = false;
    $('document-name').textContent = project.name;
    $('canvas-empty').hidden = project.ready;
    $('stage').hidden = !project.ready;
    $('preview-image').hidden = true;
    $('frame-placeholder').hidden = false;
    $('validation').hidden = true;
    $('frame-time').textContent = '';
    $('preview-state').textContent = project.ready ? 'Atur hook dan subtitle, lalu perbarui preview.' : 'Transkripsikan video untuk mulai mengedit.';
    $('source-video').pause();
    $('source-video').src = `/api/projects/${id}/media${project.playback_ready ? '?proxy=true' : ''}`;
    $('playback-fallback').hidden = true;
    if (project.ready) {
      const media = project.media;
      $('stage').style.setProperty('--aspect', media.display_width / media.display_height);
      resizeStage();
      $('dimensions').textContent = `${media.display_width} × ${media.display_height}`;
      $('scrub').max = Math.max(0, media.duration - .01);
      $('duration-label').textContent = clock(media.duration);
      inspector();
      transcript();
    } else {
      $('dimensions').textContent = 'Menunggu transkrip';
      $('transcript').replaceChildren();
      $('transcript-empty').hidden = false;
    }
    setTime(0);
    setMode('frame');
    results();
    try { localStorage.setItem('videogen-project', id); } catch { /* Storage is optional. */ }
    await refreshProjects();
    buttons();
    if (followJob && project.last_job_id) {
      const job = await api(`/api/jobs/${project.last_job_id}`);
      if (!terminal.has(job.status)) watchJob(job);
      else if (job.status !== 'completed') showJob(job);
    }
  } catch (error) { notify(error.message, true); }
}

function transcript() {
  $('transcript-empty').hidden = true;
  $('transcript').replaceChildren();
  for (const word of state.project.words) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = word.text;
    const offset = state.project.media.audio_start - state.project.media.video_start;
    const timestamp = Math.max(0, word.start + offset);
    button.dataset.start = timestamp;
    button.dataset.end = word.end + offset;
    button.title = `${clock(timestamp)} — ${clock(word.end + offset)}`;
    button.addEventListener('click', () => {
      setTime(timestamp, true);
      if (state.mode === 'frame' && !state.busy) makePreview();
    });
    $('transcript').append(button);
  }
}

function setTime(value, seek = false) {
  state.time = Math.min(Math.max(0, value), Math.max(0, (state.project?.media?.duration || 1) - .01));
  $('scrub').value = state.time;
  $('time-label').textContent = clock(state.time);
  for (const button of $('transcript').children) button.classList.toggle('active', +button.dataset.start <= state.time && state.time < +button.dataset.end);
  if (seek && Number.isFinite($('source-video').duration)) $('source-video').currentTime = state.time;
}

function setMode(mode) {
  state.mode = mode;
  $('frame-view').setAttribute('aria-pressed', String(mode === 'frame'));
  $('source-view').setAttribute('aria-pressed', String(mode === 'source'));
  $('source-video').hidden = mode !== 'source';
  $('preview-image').hidden = mode !== 'frame' || !state.preview;
  $('frame-placeholder').hidden = mode !== 'frame' || Boolean(state.preview);
  $('playback-fallback').hidden = mode !== 'source' || !state.sourceFailed;
  if (mode === 'frame') $('source-video').pause();
  else {
    $('preview-state').textContent = 'Video sumber tanpa overlay. Gunakan preview hasil untuk memeriksa teks.';
    setTime(state.time, true);
  }
  if (mode === 'frame' && state.preview) {
    $('preview-state').textContent = previewCurrent() ? 'Frame hasil dengan hook dan subtitle.' : 'Frame ini belum menampilkan perubahan terakhir.';
    $('preview-state').parentElement.classList.toggle('stale', !previewCurrent());
  }
  handles();
}

async function makePreview(renderAfter = false) {
  if (state.busy || !state.project?.ready) return;
  if (!renderAfter) state.renderIntent = null;
  if (!await saveDraft()) { state.renderIntent = null; buttons(); return; }
  if (renderAfter && !state.renderIntent) { buttons(); return; }
  try {
    const job = await api(`/api/projects/${state.project.id}/previews`, { method: 'POST', body: JSON.stringify({ version: state.project.draft_version, timestamp: state.time }) });
    setMode('frame');
    watchJob(job);
  } catch (error) { state.renderIntent = null; notify(error.message, true); buttons(); }
}

async function render() {
  if ($('render').disabled) return;
  const intent = { projectId: state.project.id, stamp: state.stamp };
  state.renderIntent = intent;
  buttons();
  if (!await saveDraft()) { state.renderIntent = null; buttons(); return; }
  if (state.renderIntent !== intent) { buttons(); return; }
  if (previewCurrent() && state.preview.result.layout.all_cues_valid) await beginRender(state.preview);
  else await makePreview(true);
}

async function beginRender(preview) {
  const intent = state.renderIntent;
  if (!intent || intent.projectId !== state.project?.id || intent.stamp !== state.stamp || !previewCurrent()) {
    state.renderIntent = null;
    buttons();
    return;
  }
  try {
    const job = await api(`/api/projects/${state.project.id}/renders`, { method: 'POST', body: JSON.stringify({ version: state.project.draft_version, preview_job_id: preview.id }) });
    state.renderIntent = null;
    watchJob(job);
  } catch (error) { state.renderIntent = null; notify(error.message, true); buttons(); }
}

function showJob(job) {
  $('job-panel').hidden = false;
  const names = { transcribe: 'Membuat transkrip', preview: 'Membuat preview', render: 'Merender video', playback: 'Menyiapkan video untuk browser' };
  $('job-title').textContent = terminal.has(job.status) ? ({ completed: 'Selesai', failed: 'Pekerjaan gagal', cancelled: 'Dibatalkan', interrupted: 'Pekerjaan terputus' }[job.status]) : names[job.operation];
  $('job-message').textContent = (job.message || '').split('\nLog:')[0];
  if (typeof job.percent === 'number') {
    $('job-progress').value = job.percent;
    $('job-percent').textContent = `${job.percent}%`;
  } else {
    $('job-progress').removeAttribute('value');
    $('job-percent').textContent = '';
  }
  $('cancel').hidden = terminal.has(job.status);
  $('cancel').disabled = job.status === 'cancelling';
  $('job-log').hidden = !['failed', 'interrupted'].includes(job.status);
  $('job-log').href = `/api/jobs/${job.id}/log`;
}

function watchJob(job) {
  state.busy = true;
  state.job = job;
  clearTimeout(pollTimer);
  notify();
  showJob(job);
  buttons();
  pollJob(job.id);
}

function showPreview(job) {
  if (state.dragging) { state.deferredPreview = job; return; }
  if (job.version !== state.project?.draft_version || state.dirty) {
    notify('Ada perubahan baru. Klik Render MP4 untuk memeriksa dan merender versi terbaru.');
    return;
  }
  state.preview = { ...job, draftSnapshot: clone(state.draft) };
  $('preview-image').src = job.result.image_url;
  $('frame-time').textContent = `Frame ${clock(job.result.layout.timestamp)}`;
  $('preview-state').parentElement.classList.remove('stale');
  const errors = job.result.layout.validation_errors;
  $('validation').hidden = job.result.layout.all_cues_valid;
  $('validation').textContent = errors.length ? `${errors.length} cue belum muat. Cue pertama pada ${clock(errors[0].timestamp ?? errors[0].start ?? 0)}.\n${errors[0].reason}\nKecilkan ukuran atau perbesar lebar subtitle, lalu klik Render MP4.` : '';
  setMode('frame');
}

async function pollJob(id) {
  try {
    const job = await api(`/api/jobs/${id}`);
    if (state.job?.id !== id) return;
    state.job = job;
    showJob(job);
    if (!terminal.has(job.status)) {
      pollTimer = setTimeout(() => pollJob(id), 600);
      return;
    }
    state.busy = false;
    if (job.status === 'completed' && state.project?.id === job.project_id) {
      if (job.operation === 'transcribe') {
        await openProject(job.project_id, false);
        notify('Transkrip siap. Tulis hook atau matikan hook untuk hanya subtitle.');
      } else if (job.operation === 'preview') {
        showPreview(job);
        if (state.renderIntent) {
          if (state.preview?.id === job.id && job.result.layout.all_cues_valid) {
            await beginRender(job);
            return;
          }
          state.renderIntent = null;
        }
      } else if (job.operation === 'render') {
        const updated = await api(`/api/projects/${job.project_id}`);
        state.project.revisions = updated.revisions;
        results(job.result.revision_id);
        $('results').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
        notify('Video selesai dirender. Hasil sebelumnya tetap tersimpan.');
      } else if (job.operation === 'playback') {
        state.project.playback_ready = true;
        state.sourceFailed = false;
        $('source-video').src = job.result.video_url;
        $('playback-fallback').hidden = true;
        setMode('source');
      }
    } else if (job.status === 'failed' || job.status === 'interrupted') {
      state.renderIntent = null;
      notify(job.message.split('\nLog:')[0], true);
    } else if (job.status === 'cancelled') state.renderIntent = null;
    await refreshProjects();
    buttons();
  } catch (error) {
    notify(`Koneksi terputus: ${error.message} Status akan diperiksa kembali.`, true);
    pollTimer = setTimeout(() => pollJob(id), 2000);
  }
}

async function upload(file) {
  if (!file || state.busy || state.saving || !state.setupReady) return;
  if (!/\.(mp4|mov)$/i.test(file.name)) { notify('Pilih video MP4 atau MOV.', true); return; }
  if (file.size > state.maxUpload || !file.size) { notify('File kosong atau melebihi batas unggahan.', true); return; }
  if (state.dirty && !window.confirm('Draft belum disimpan. Buang perubahan dan pilih video baru?')) return;
  state.busy = true;
  state.dirty = false;
  notify();
  buttons();
  showJob({ operation: 'transcribe', status: 'uploading', message: 'Mengunggah video', percent: 0 });
  $('job-title').textContent = 'Mengunggah video';
  const xhr = new XMLHttpRequest();
  state.xhr = xhr;
  xhr.open('POST', `/api/projects?filename=${encodeURIComponent(file.name)}`);
  xhr.setRequestHeader('Content-Type', 'application/octet-stream');
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) {
      const value = Math.floor(event.loaded / event.total * 100);
      $('job-progress').value = value;
      $('job-percent').textContent = `${value}%`;
      if (value === 100) $('job-message').textContent = 'Unggahan diterima. Menyiapkan transkripsi…';
    }
  };
  xhr.onload = async () => {
    state.xhr = null;
    if (xhr.status !== 202) {
      state.busy = false;
      let message = 'Unggahan gagal.';
      try { message = JSON.parse(xhr.responseText).detail || message; } catch { /* Keep readable network error. */ }
      notify(message, true);
      $('job-panel').hidden = true;
      buttons();
      await refreshProjects();
      return;
    }
    const job = JSON.parse(xhr.responseText);
    await openProject(job.project_id, false);
    watchJob(job);
  };
  xhr.onerror = xhr.onabort = () => {
    state.xhr = null;
    state.busy = false;
    $('job-panel').hidden = true;
    notify('Unggahan terputus. Pilih video kembali.', true);
    buttons();
    refreshProjects().catch(() => {});
  };
  xhr.send(file);
  $('video-file').value = '';
}

function results(selected) {
  const revisions = state.project?.revisions || [];
  $('results').hidden = !revisions.length;
  $('revision-list').replaceChildren();
  for (const [index, revision] of revisions.entries()) {
    const option = document.createElement('option');
    option.value = revision.id;
    option.textContent = `${revisions.length - index} · ${new Date(revision.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`;
    $('revision-list').append(option);
  }
  if (revisions.length) {
    $('revision-list').value = selected || revisions[0].id;
    selectRevision();
  } else {
    $('result-video').pause();
    $('result-video').removeAttribute('src');
    $('result-video').load();
  }
}

function selectRevision() {
  const base = `/api/projects/${state.project.id}/revisions/${$('revision-list').value}`;
  $('result-video').src = `${base}/mp4`;
  for (const kind of ['mp4', 'txt', 'srt']) $(`download-${kind}`).href = `${base}/${kind}?download=true`;
}

function resizeStage() {
  if (!state.project?.media) return;
  const well = document.querySelector('.canvas-well');
  const padding = getComputedStyle(well);
  const width = well.clientWidth - parseFloat(padding.paddingLeft) - parseFloat(padding.paddingRight);
  const height = well.clientHeight - parseFloat(padding.paddingTop) - parseFloat(padding.paddingBottom);
  const aspect = state.project.media.display_width / state.project.media.display_height;
  const fitted = Math.min(width, height * aspect);
  $('stage').style.width = `${Math.max(1, fitted)}px`;
  $('stage').style.height = `${Math.max(1, fitted / aspect)}px`;
}

function handles() {
  const layout = state.preview?.result.layout;
  for (const target of ['hook', 'subtitle']) {
    const element = $(`${target}-handle`);
    element.hidden = !layout || state.mode !== 'frame' || !layout[`${target}_visible`];
    if (element.hidden) continue;
    const boxes = target === 'hook' ? layout.panel_bounds : [layout.subtitle_bounds].filter(Boolean);
    if (!boxes.length) { element.hidden = true; continue; }
    const x = Math.min(...boxes.map((box) => box.x));
    const y = Math.min(...boxes.map((box) => box.y));
    const right = Math.max(...boxes.map((box) => box.x + box.width));
    const bottom = Math.max(...boxes.map((box) => box.y + box.height));
    const media = state.project.media;
    const before = state.preview.draftSnapshot?.[`${target}_style`];
    const after = state.draft[`${target}_style`];
    const dx = before ? (after.center_fraction - before.center_fraction) * media.display_width : 0;
    const dy = before ? (after.top_fraction - before.top_fraction) * media.display_height : 0;
    Object.assign(element.style, { left: `${(x + dx) / media.display_width * 100}%`, top: `${(y + dy) / media.display_height * 100}%`, width: `${(right - x) / media.display_width * 100}%`, height: `${(bottom - y) / media.display_height * 100}%` });
    element.classList.toggle('selected', state.target === target);
  }
}

function dragHandle(target) {
  const element = $(`${target}-handle`);
  let drag = null;
  const finish = (cancel = false) => {
    if (!drag) return;
    const saved = drag;
    drag = null;
    state.dragging = false;
    element.classList.remove('dragging');
    if (element.hasPointerCapture(saved.id)) element.releasePointerCapture(saved.id);
    if (!cancel && (Math.abs(saved.dx) + Math.abs(saved.dy) > .002)) changed((draft) => {
      draft[`${target}_style`].center_fraction = saved.style.center_fraction + saved.dx;
      draft[`${target}_style`].top_fraction = saved.style.top_fraction + saved.dy;
    }, true);
    const pending = state.deferredPreview;
    state.deferredPreview = null;
    if (pending) showPreview(pending);
    handles();
    buttons();
  };
  element.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || !state.draft) return;
    event.preventDefault();
    state.renderIntent = null;
    setTarget(target);
    const rect = $('stage').getBoundingClientRect();
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, rect, dx: 0, dy: 0,
      style: clone(state.draft[`${target}_style`]), left: parseFloat(element.style.left), top: parseFloat(element.style.top) };
    element.setPointerCapture(event.pointerId);
    state.dragging = true;
    element.classList.add('dragging');
    element.focus();
    buttons();
  });
  element.addEventListener('pointermove', (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    drag.dx = (event.clientX - drag.x) / drag.rect.width;
    drag.dy = (event.clientY - drag.y) / drag.rect.height;
    element.style.left = `${drag.left + drag.dx * 100}%`;
    element.style.top = `${drag.top + drag.dy * 100}%`;
  });
  element.addEventListener('pointerup', () => finish());
  element.addEventListener('pointercancel', () => finish(true));
  element.addEventListener('lostpointercapture', () => finish(true));
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { finish(true); return; }
    const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    setTarget(target);
    changed((draft) => {
      draft[`${target}_style`].center_fraction += move[0] * (event.shiftKey ? .01 : .001);
      draft[`${target}_style`].top_fraction += move[1] * (event.shiftKey ? .01 : .001);
    }, true);
  });
}

for (const button of document.querySelectorAll('button')) button.type = 'button';
$('hook-tab').onclick = () => setTarget('hook');
$('subtitle-tab').onclick = () => setTarget('subtitle');
$('save').onclick = () => saveDraft();
$('undo').onclick = () => undo();
$('redo').onclick = () => undo(true);
$('preview').onclick = () => makePreview();
$('render').onclick = render;
$('frame-view').onclick = () => setMode('frame');
$('source-view').onclick = () => setMode('source');
$('revision-list').onchange = selectRevision;
$('video-file').onchange = (event) => upload(event.target.files[0]);
$('scrub').oninput = (event) => setTime(+event.target.value, true);
$('scrub').onchange = () => { if (state.mode === 'frame' && !state.busy) makePreview(); };
$('source-video').ontimeupdate = () => { if (state.mode === 'source') setTime($('source-video').currentTime); };
$('source-video').onerror = () => { state.sourceFailed = true; if (state.mode === 'source') $('playback-fallback').hidden = false; };
$('preview-image').onload = handles;
$('next-cue').onclick = () => {
  const starts = state.preview?.result.layout.cue_starts || state.project.words.map((word) => word.start + state.project.media.audio_start - state.project.media.video_start);
  setTime(starts.find((time) => time > state.time + .03) ?? starts[0] ?? 0, true);
  if (state.mode === 'frame') makePreview();
};
$('copy-transcript').onclick = async () => {
  try { await navigator.clipboard.writeText(state.project.transcript); notify('Transkrip disalin.'); }
  catch { notify('Clipboard tidak tersedia. Pilih dan salin teks transkrip secara manual.', true); }
};
$('cancel').onclick = async () => {
  if (state.xhr) { state.xhr.abort(); return; }
  if (state.job) {
    try { showJob(await api(`/api/jobs/${state.job.id}/cancel`, { method: 'POST' })); }
    catch (error) { notify(error.message, true); }
  }
};
$('prepare-playback').onclick = async () => {
  try { watchJob(await api(`/api/projects/${state.project.id}/playback`, { method: 'POST' })); }
  catch (error) { notify(error.message, true); }
};
$('retry-transcribe').onclick = async () => {
  try { watchJob(await api(`/api/projects/${state.project.id}/transcribe`, { method: 'POST' })); }
  catch (error) { notify(error.message, true); }
};
$('center').onclick = () => changed((draft) => {
  draft[`${state.target}_style`].center_fraction = .5;
  draft[`${state.target}_style`].top_fraction = state.target === 'hook' ? .15 : .74;
}, true);
const hookControls = { 'hook-text': ['text', 'value'], 'hook-enabled': ['enabled', 'checked'], 'hook-manual': ['manual', 'checked'], 'hook-duration': ['duration', 'valueAsNumber'], 'hook-full': ['full_video', 'checked'] };
for (const [id, [key, property]] of Object.entries(hookControls)) $(id).addEventListener('input', () => {
  if (!$(id).checkValidity() || (property === 'valueAsNumber' && !Number.isFinite($(id).valueAsNumber))) { buttons(); return; }
  changed((draft) => { draft.hook[key] = $(id)[property]; });
  $('hook-duration').disabled = state.draft.hook.full_video;
});
const styleControls = {
  'font-size': ['size_fraction', (element) => element.valueAsNumber / state.project.media.display_height],
  'text-width': ['width_fraction', (element) => element.valueAsNumber / 100],
  'position-x': ['center_fraction', (element) => element.valueAsNumber / 100],
  'position-y': ['top_fraction', (element) => element.valueAsNumber / 100],
  'alignment': ['alignment', (element) => element.value], 'text-color': ['text_color', (element) => element.value],
  'background-color': ['background_color', (element) => element.value], 'background-enabled': ['background_enabled', (element) => element.checked],
  'auto-size': ['auto_size', (element) => element.checked], 'active-color': ['active_word_color', (element) => element.value],
  'outline-color': ['outline_color', (element) => element.value], 'outline-size': ['outline_fraction', (element) => element.valueAsNumber / 100]
};
for (const [id, [key, get]] of Object.entries(styleControls)) $(id).addEventListener('input', () => {
  const element = $(id);
  if (!element.checkValidity() || (element.type === 'number' && !Number.isFinite(element.valueAsNumber))) { buttons(); return; }
  changed((draft) => { draft[`${state.target}_style`][key] = get(element); });
});
for (const type of ['dragenter', 'dragover']) $('drop-zone').addEventListener(type, (event) => { event.preventDefault(); $('drop-zone').classList.add('dragging'); });
for (const type of ['dragleave', 'drop']) $('drop-zone').addEventListener(type, (event) => { event.preventDefault(); $('drop-zone').classList.remove('dragging'); if (type === 'drop') upload(event.dataTransfer.files[0]); });
dragHandle('hook');
dragHandle('subtitle');
new ResizeObserver(resizeStage).observe(document.querySelector('.canvas-well'));
window.addEventListener('beforeunload', (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });

async function start() {
  try {
    const status = await api('/api/status');
    state.setupReady = status.setup.ready;
    state.maxUpload = status.max_upload_bytes;
    $('upload-limit').textContent = `MP4 / MOV · maks. ${Math.round(state.maxUpload / 1024 ** 2)} MB`;
    $('setup').replaceChildren();
    for (const [name, check] of Object.entries(status.setup.checks)) {
      const element = document.createElement('span');
      element.classList.toggle('missing', !check.ready);
      element.textContent = `${check.ready ? '✓' : '!'} ${name === 'ffmpeg' ? 'FFmpeg' : name === 'model' ? 'Model transkripsi' : 'Font subtitle'} ${check.ready ? 'siap' : 'belum tersedia'}`;
      element.title = check.message || check.path || '';
      $('setup').append(element);
    }
    $('setup').hidden = status.setup.ready;
    if (!status.setup.ready) notify('Lengkapi FFmpeg, model, dan font sesuai README sebelum memproses video.', true);
    await refreshProjects();
    let previous = status.active_job?.project_id;
    try { previous ||= localStorage.getItem('videogen-project'); } catch { /* Storage is optional. */ }
    if (previous) await openProject(previous, false);
    if (status.active_job) watchJob(status.active_job);
    buttons();
  } catch (error) { notify(`Aplikasi belum siap: ${error.message}`, true); }
}
start();
