/* Shorts screen (Phase 4): a 30-second 9:16 video made with Wan 2.2 models. Uses the helpers of index.html ($, api, esc, act, toast, dialog, textDlg, confirmDlg, hd, fmtDate). */
(() => {
const css = document.createElement('style');
css.textContent = `
.sh-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start;margin-top:12px}
.sh-side{position:sticky;top:64px;max-height:calc(100vh - 80px);overflow:auto}
.sh-beat{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:12px 0;background:var(--panel)}
.sh-beat textarea{min-height:44px;font-size:15px}
.sh-shot{display:grid;grid-template-columns:104px 1fr;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
.sh-thumb{width:104px;aspect-ratio:9/16;background:var(--bg);border:1px solid var(--line);border-radius:8px;overflow:hidden;display:grid;place-items:center;color:var(--mute);font-size:11px;text-align:center}
.sh-thumb video,.sh-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.sh-wrap{position:relative}
.sh-busy{position:absolute;top:5px;right:5px;width:22px;height:22px;border-radius:50%;background:rgba(255,255,255,.92);display:grid;place-items:center;box-shadow:0 1px 4px rgba(0,0,0,.3);color:var(--accent,#4f46e5);z-index:2}
.sh-busy .spin{width:13px;height:13px}
.sh-keys{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
.sh-key{border:1px solid var(--line);border-radius:10px;padding:6px;background:var(--panel);font-size:12px}
.sh-key img{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:6px;display:block;background:var(--bg)}
.sh-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sh-final video{max-height:560px;border-radius:10px;background:#000}
.sh-step{display:flex;gap:8px;align-items:center;margin:6px 0}.sh-step .n{width:22px;height:22px;border-radius:50%;border:1px solid var(--line);display:grid;place-items:center;font-size:12px;flex:none}
.sh-step.done .n{background:var(--ok);color:#fff;border-color:var(--ok)}.sh-step.next .n{border-color:var(--accent);color:var(--accent);font-weight:700}
.sh-pipe{display:block;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;cursor:pointer}
.sh-pipe:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
.sh-pipe.off{opacity:.55}
.sh-sugg button{margin:2px 4px 2px 0}
@media (max-width:980px){.sh-grid{grid-template-columns:1fr}.sh-side{position:static;max-height:none;order:-1}}
`;
document.head.append(css);

const call = (path, opts = {}) => api('/shorts' + path, opts);
const mm = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const vid = (url, extra = '') => url ? `<video src="${esc(url)}" controls preload="metadata" playsinline ${extra}></video>` : '';
let S = null, SID = null, pollT = null, myRoute = 0;

/* ───────── list ───────── */
window.viewShorts = async function () {
  const my = route_id;
  $('#app').innerHTML = `<div class="row"><h2 style="margin:0">Shorts</h2><span class="mute">Vertical videos made with Wan 2.2</span><span class="sp"></span><button class="primary" id="sh-new">+ New short</button></div>
    <div class="card mt" id="sh-list"><div class="pad"><div class="skel"></div><div class="skel"></div></div></div>`;
  $('#sh-new').onclick = newShort;
  const rows = await call('').catch(e => { toast(e.message, {bad: true}); return []; });
  if (my !== route_id) return;
  $('#sh-list').innerHTML = rows.length ? `<table><thead><tr><th>Short</th><th>Pipeline</th><th>Shots</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>${rows.map(r => `
    <tr class="click" onclick="location.hash='#/short/${r.id}'"><td><b>${esc(r.title)}</b></td><td>${esc(r.pipeline)}</td><td>${r.shots}</td><td>${badge(r.status === 'made' ? 'done' : 'info', r.status)}</td><td class="mute small">${fmtDate(r.updated_at)}</td><td><button class="small bad" data-del="${r.id}" data-title="${esc(r.title)}">Delete</button></td></tr>`).join('')}</tbody></table>`
    : `<div class="big-empty"><h2>Make your first short</h2><p class="mute" style="max-width:560px;margin:0 auto 16px">Pick a Wan model, give an idea or an approved story, and the app plans 11 to 13 fast shots, speaks the narration, makes every clip and puts a 30-second 9:16 video together.</p><button class="primary" onclick="newShort()">+ New short</button></div>`;
  $('#sh-list').querySelectorAll('[data-del]').forEach(b => b.onclick = async e => {
    e.stopPropagation();
    if (await confirmDlg('Delete short', `Delete "${b.dataset.title}"? All its clips, pictures and voice are removed.`, 'Delete', true)) {
      await call('/' + b.dataset.del, {method: 'DELETE'});
      viewShorts();
    }
  });
};

async function newShort() {
  const [opts, stories] = await Promise.all([call('/options'), call('/stories').catch(() => [])]);
  const pipes = Object.entries(opts.pipelines);
  const html = `<div class="wide-dlg"></div>
    <h4 style="margin-top:0">Which model</h4>${pipes.map(([k, p], i) => `<label class="sh-pipe ${p.available === false ? 'off' : ''}"><input type="radio" name="pipe" value="${k}" ${k === 'keyframe' ? 'checked' : ''}> <b>${esc(p.label)}</b>
      <div class="mute small">${esc(p.about)}</div>${p.available === false ? `<div class="err small">The gateway does not list: ${esc(p.missing.join(', '))}</div>` : ''}</label>`).join('')}
    <div id="sh-src"><h4>What is it about</h4>
      <label class="f">Where the idea comes from<select id="sh-kind"><option value="idea">Write an idea</option><option value="story" ${stories.length ? '' : 'disabled'}>An approved story${stories.length ? '' : ' (none yet)'}</option></select></label>
      <label class="f mt-s" id="sh-idea-l">The idea, in a sentence or two<textarea id="sh-idea" placeholder="A delivery rider finds a wallet with a lakh rupees in it. What does he do?"></textarea></label>
      <label class="f mt-s" id="sh-story-l" hidden>The story<select id="sh-story">${stories.map(s => `<option value="${esc(s.id)}">${esc(s.title)} (${esc(s.project)})</option>`).join('')}</select></label></div>
    <div id="sh-fast-l" class="mt-s"><label class="f">Video size<select id="sh-size14"><option value="480x832">480p (480x832, about 12 min for a 5 s shot)</option><option value="720x1280">720p (720x1280, sharper, about 2.3x slower)</option></select></label>
      <label class="row mt-s"><input type="checkbox" id="sh-fast"> Fast draft: Wan speed LoRA (about 3x quicker, slightly softer and less motion; leave off for the final)</label></div>
    <div id="sh-look-l"><h4>Look and voice</h4>
      <label class="f">Picture style<select id="sh-style">${(opts.visual_styles || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('')}</select></label>
      <label class="f mt-s">Narration voice<select id="sh-voice">${(() => { window._shVoices = opts.voices; return voiceOptions({engine: 'maya-tts', voice: 'Siddhant'}); })()}</select></label>
<label class="f mt-s">Narration tone or persona<select id="sh-tone">${toneOptions(opts.tones, '')}</select></label>
      <label class="f mt-s">Language edge (only when the script calls for it)<select id="sh-edge">${edgeOptions(opts.tones, 'clean')}</select></label>
      <label class="f mt-s">Narration speed<select id="sh-vspeed">${[[0.85, 'Slower (0.85x)'], [0.92, 'A little slower (0.92x)'], [1, 'Normal (1x)'], [1.08, 'A little faster (1.08x)'], [1.15, 'Faster (1.15x)']].map(([k, t]) => `<option value="${k}" ${Math.abs((1 || 1) - k) < 0.01 ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label class="f mt-s">Narration language<select id="sh-lang">${(opts.languages || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)}${m.maya_only ? ' (Maya voice only)' : ''}</option>`).join('')}</select></label></div>
    <div id="sh-dur-l"><h4>Length</h4>
    <div class="f">Video length
      <span><input type="number" id="sh-dur-m" value="0" min="0" max="3" step="1" style="width:60px"> min <input type="number" id="sh-dur-s" value="30" min="0" max="59" step="1" style="width:60px"> sec</span>
      <span class="small mute">From 5 seconds to 3 minutes (30 seconds if you leave it). The story is written to fit: a short one gets a hook and a blow, a long one gets a re-hook every 20 seconds or so. The voice, shot count and timeline adjust automatically.</span></div></div>`;
  const dlg = dialog({title: 'New short', html, buttons: [{label: 'Cancel', value: null}, {label: 'Create', primary: true,
    collect: l => { const dur = Math.max(5, Math.min(180, (parseInt(l.querySelector('#sh-dur-m').value) || 0) * 60 + (parseInt(l.querySelector('#sh-dur-s').value) || 0))) || 30; return {pipeline: l.querySelector('input[name=pipe]:checked').value, kind: l.querySelector('#sh-kind').value, text: l.querySelector('#sh-idea').value, candidate_id: l.querySelector('#sh-story').value, settings: {target_s: dur, visual_style: l.querySelector('#sh-style').value, language: l.querySelector('#sh-lang').value, tone_id: l.querySelector('#sh-tone').value, edge: l.querySelector('#sh-edge').value, voice_speed: +l.querySelector('#sh-vspeed').value, voice: (() => { const [engine, voice] = l.querySelector('#sh-voice').value.split('|'); return {engine, voice}; })(), speed_lora: l.querySelector('input[name=pipe]:checked').value === 'keyframe' && l.querySelector('#sh-fast').checked, size_14b: l.querySelector('#sh-size14').value}}; },
    validate: v => v.pipeline !== 'remix' && v.kind === 'idea' && v.text.trim().length < 10 ? 'Write the idea in a sentence or two.' : (v.pipeline !== 'remix' && v.settings.language !== 'hinglish' && v.settings.voice.engine !== 'maya-tts' ? 'A narration language other than Hinglish needs a Maya voice. Pick a Maya voice or Hinglish.' : '')}]});
  setTimeout(() => {
    const k = document.querySelector('#sh-kind'), p = () => document.querySelectorAll('input[name=pipe]');
    const sync = () => { const remix = document.querySelector('input[name=pipe]:checked')?.value === 'remix'; $('#sh-src').hidden = remix; $('#sh-fast-l').hidden = document.querySelector('input[name=pipe]:checked')?.value !== 'keyframe'; $('#sh-look-l').hidden = remix; $('#sh-dur-l').hidden = remix; const st = k.value === 'story'; $('#sh-idea-l').hidden = st; $('#sh-story-l').hidden = !st; };
    const tn = document.querySelector('#sh-tone'), sp = document.querySelector('#sh-vspeed');
    if (tn && sp) tn.onchange = () => { const t = opts.tones.tones.find(x => x.id === tn.value); if (t) sp.value = String(t.speed); };
    if (k) { k.onchange = sync; p().forEach(r => r.onchange = sync); sync(); }
  }, 30);
  const v = await dlg;
  if (!v) return;
  const r = await act(null, () => call('', {method: 'POST', json: v.pipeline === 'remix' ? {pipeline: 'remix', kind: 'idea', text: '', settings: v.settings} : v}), 'Created. Next: plan the short.');
  if (r) location.hash = '#/short/' + r.id;
}
window.newShort = newShort;

/* ───────── one short ───────── */
window.viewShort = async function (id) {
  SID = id; S = null; myRoute = route_id;
  $('#app').innerHTML = `<div class="card pad"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
  if (!window._shVoices) { try { const o = await api('/shorts/options'); window._shVoices = o.voices; window._shTags = o.tags; window._shOpts = o; window._shChars = await api('/characters').catch(() => []); } catch { /* the voice list stays empty; the settings show the current voice */ } }
  await refresh(true);
};

async function refresh(force) {
  clearTimeout(pollT);
  const my = myRoute;
  try { S = await call('/' + SID); } catch (e) { if (my === myRoute) toast(e.message, {bad: true}); return; }
  if (my !== myRoute) return;
  const a = document.activeElement;
  if (force || !(a && a.closest && a.closest('#app') && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName))) render();
  if (S.job && S.job.state === 'running') pollT = setTimeout(() => refresh(), 2000);
}

async function post(btn, path, json, ok) {
  const r = await act(btn, () => call('/' + SID + path, {method: 'POST', json: json || {}}), ok);
  await refresh(true);
  return r;
}
async function patch(path, json) {
  try { S = await call('/' + SID + path, {method: 'PATCH', json}); render(); } catch (e) { toast(e.message, {bad: true}); }
}
async function upload(path, file, btn) {
  const fd = new FormData(); fd.append('file', file);
  await act(btn, async () => { S = await call('/' + SID + path, {method: 'POST', form: fd}); return true; }, 'Uploaded');
  await refresh(true);
}
const pick = (accept, cb) => { const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.onchange = () => i.files[0] && cb(i.files[0]); i.click(); };

const making = list => (list || []).some(a => a.status === 'running' || a.status === 'queued');
const busyDot = (on, what) => on ? `<span class="sh-busy" title="${esc(what)} is being made in the background"><span class="spin"></span></span>` : '';
const busyTxt = (on, what) => on ? `<span class="mute small"><span class="spin"></span> ${esc(what)}…</span>` : '';

function jobBox() {
  const j = S.job || {};
  if (j.state === 'running') {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    return `<div class="jobbox"><div class="row"><span class="spin"></span><b>${esc(j.label || 'working')}</b><span class="sp"></span><span class="mute small">${hd(j.elapsed_s || 0)}${j.eta_s ? ' · about ' + hd(j.eta_s) + ' left' : ''}</span>
      <button class="small bad" onclick="shStop()">Stop</button></div>${bar(pct)}</div>`;
  }
  if (j.state === 'error') return `<div class="errbox">The last step stopped: ${esc(j.error)}</div>`;
  if (j.state === 'done' && j.note) return `<div class="hint" style="margin-bottom:12px">${esc(j.note)}</div>`;
  return '';
}
window.shStop = async () => { await call('/' + SID + '/cancel', {method: 'POST'}); await refresh(true); };

function render() {
  const s = S, remix = s.pipeline === 'remix', busy = s.job && s.job.state === 'running';
  const next = s.auto.steps.find(x => !x.done);
  $('#app').innerHTML = `
    <div class="row"><a href="#/shorts">← Shorts</a><h2 style="margin:0 0 0 8px">${esc(s.title)}</h2>${badge('info', s.pipeline_label)}<span class="sp"></span>
      ${s.estimate_s ? `<span class="mute small" title="Estimated model time for every clip, one request at a time">about ${hd(s.estimate_s)} of model time</span>` : ''}
      <button class="small" onclick="shRename()">Rename</button><button class="small bad" onclick="shDelete()">Delete</button></div>
    ${jobBox()}
    <div class="nextbar"><div><b>${s.auto.done ? 'Everything is made.' : 'Next: ' + esc(next.label)}</b> <span class="mute small">${s.auto.steps.map(x => (x.done ? '✓ ' : '· ') + esc(x.label)).join('  ')}</span></div>
      <button class="primary" ${busy ? 'disabled' : ''} onclick="shAuto(this)">${s.auto.done ? 'Run again' : 'Auto-run'}</button></div>
    <div class="sh-grid"><div>${remix ? remixView() : planView()}${finalView()}</div><div class="sh-side">${sideView()}</div></div>`;
  wire();
}

window.shRename = async () => { const t = await textDlg('Rename', 'Title', S.title); if (t) await patch('/plan', {title: t}); };
window.shDelete = async () => { if (await confirmDlg('Delete this short', 'All its pictures, clips and voice are deleted too.', 'Delete', true)) { await act(null, () => call('/' + SID, {method: 'DELETE'}), 'Deleted'); location.hash = '#/shorts'; } };
window.shAuto = btn => post(btn, '/auto', {}, 'Auto-run started');

/* side panel: settings */
function sideView() {
  const s = S, st = s.settings, remix = s.pipeline === 'remix';
  const v = window._shOpts || {};
  return `<div class="card pad"><h2>Settings</h2>
    ${remix ? '' : `<label class="f">Start pictures<select id="st-mode">${[['qwen', 'The image model draws a picture for every shot'], ['anchor', 'My picture of the main character, the rest drawn'], ['per_shot', 'My pictures for chosen shots, the rest drawn'], ['wan', 'No pictures: Wan decides (fast, rougher)']].map(([k, t]) => `<option value="${k}" ${st.image_mode === k ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
    ${castBlock()}
    ${st.image_mode === 'wan' ? '' : `<label class="f mt-s">Image model<select id="st-imodel">${(v.image_models || [{id: st.image_model, label: st.image_model}]).map(m => `<option value="${esc(m.id)}" ${st.image_model === m.id ? 'selected' : ''}>${esc(m.label)}${m.licence === 'restricted' ? ' (licence restricted)' : ''}</option>`).join('')}</select></label>`}
    <label class="f mt-s">Picture style<select id="st-style">${(v.visual_styles || [{id: '', label: 'Let the planner choose'}]).map(m => `<option value="${esc(m.id)}" title="${esc(m.description || '')}" ${(st.visual_style || '') === m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
      <span class="small mute">${esc(((v.visual_styles || []).find(m => m.id === (st.visual_style || '')) || {}).description || '')} Re-plan to apply to the story; pictures and clips redraw with it.</span></label>
    <div class="mt-s small">${s.images.anchor ? `<img src="/api/shorts/file/${s.id}/${esc(s.images.anchor)}" style="width:70px;border-radius:6px;vertical-align:middle"> <button class="small" id="st-anchor">Change</button> <button class="small bad" id="st-anchor-x">Remove</button>` : `<button class="small" id="st-anchor">Upload the main character's picture</button>`}</div>
    <label class="f mt-s">Describe that character in a line (used in the shots that show them)<textarea id="st-char" style="min-height:48px">${esc(st.character_text || '')}</textarea></label>
    <label class="f mt-s">Format<select id="st-format">${[['auto', 'Detect from the story (recommended)'], ['story', 'Story: dramatised, follows a person'], ['documentary', 'Documentary: real subjects, narrator'], ['explainer', 'Explainer: facts and numbers'], ['comparison', 'Comparison: sides against each other']].map(([k, t]) => `<option value="${k}" ${(st.format || 'auto') === k ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <span class="small mute">Only the next plan uses it.${(s.plan || {}).format ? ` This plan is a <b>${esc(s.plan.format)}</b>.` : ''}</span></label>
    <label class="f mt-s">Tone (optional)<input id="st-tone" value="${esc(st.tone || '')}" placeholder="funny, tense, warm..."></label>`}
    <label class="f mt-s">Length (seconds, 5 to 180)<input type="number" id="st-target" value="${st.target_s || 30}" min="5" max="180" step="1" style="width:80px">
      <span class="small mute">Only the next plan is written to this length.</span></label>
    <label class="f mt-s">Script writer<select id="st-script"><option value="room" ${(st.script_engine || 'room') === 'room' ? 'selected' : ''}>Writers' room (story bible, retention map, beat drafts, punch-up)</option><option value="single" ${st.script_engine === 'single' ? 'selected' : ''}>One call (old, fast)</option></select></label>
    <label class="f mt-s">Audio<select id="st-vmode"><option value="narration" ${(st.voice_mode || 'narration') === 'narration' ? 'selected' : ''}>Narration voice (generated)</option><option value="none" ${st.voice_mode === 'none' ? 'selected' : ''}>No voice — video only (silent or background music)</option></select></label>
    ${(st.voice_mode || 'narration') !== 'none' ? `<label class="f mt-s">Voice<select id="st-voice">${voiceOptions(st.voice)}</select></label>
<label class="f mt-s">Narration tone or persona<select id="st-toneid">${toneOptions(v.tones, st.tone_id)}</select>
        <span class="small mute">Only the next plan writes in it. Change the speed below to match if you want.</span></label>
      <label class="f mt-s">Language edge<select id="st-edge">${edgeOptions(v.tones, st.edge)}</select></label>
      <label class="f mt-s">Narration speed<select id="st-vspeed">${[[0.85, 'Slower (0.85x)'], [0.92, 'A little slower (0.92x)'], [1, 'Normal (1x)'], [1.08, 'A little faster (1.08x)'], [1.15, 'Faster (1.15x)']].map(([k, t]) => `<option value="${k}" ${Math.abs((st.voice_speed || 1) - k) < 0.01 ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label class="f mt-s">Narration language<select id="st-lang">${(v.languages || []).map(m => `<option value="${esc(m.id)}" ${(st.language || 'hinglish') === m.id ? 'selected' : ''}>${esc(m.label)}${m.maya_only ? ' (Maya voice only)' : ''}</option>`).join('')}</select>
        <span class="small mute">Only the next plan writes in it. Voices made in another language are made again.</span></label>` : ''}
    ${s.pipeline === 'quick' ? `<label class="f mt-s">Picture size<select id="st-size"><option value="480x832" ${st.size === '480x832' ? 'selected' : ''}>480x832 (about 20 min)</option><option value="704x1280" ${st.size === '704x1280' ? 'selected' : ''}>704x1280 sharper (about an hour)</option></select></label>
      <label class="row mt-s"><input type="checkbox" id="st-chain" ${st.chain ? 'checked' : ''}> A shot marked "continues" starts from the last frame of the one before</label>` : ''}
    ${s.pipeline === 'keyframe' ? `<label class="f mt-s">Video size<select id="st-size14"><option value="480x832" ${st.size_14b !== '720x1280' ? 'selected' : ''}>480p (480x832, about 12 min for 5 s)</option><option value="720x1280" ${st.size_14b === '720x1280' ? 'selected' : ''}>720p (720x1280, sharper, about 2.3x slower)</option></select></label>
      <label class="row mt-s"><input type="checkbox" id="st-fast" ${st.speed_lora ? 'checked' : ''}> Fast draft: Wan speed LoRA (about 5x quicker, softer detail; leave off for the final)</label>` : ''}
    ${s.keyframes_on ? `<label class="row mt-s"><input type="checkbox" id="st-review" ${st.review_keyframes ? 'checked' : ''}> Stop to look at the start pictures before animating</label>` : ''}
    ${s.pipeline !== 'remix' ? `<label class="f mt-s">Final video size<select id="st-up"><option value="" ${!st.upscale ? 'selected' : ''}>1080x1920 (as made)</option><option value="2k" ${st.upscale === '2k' ? 'selected' : ''}>2K, 1440x2560 (every clip upscaled by the model server, minutes per clip)</option></select></label>` : ''}
    <label class="row mt-s"><input type="checkbox" id="st-cap" ${st.captions ? 'checked' : ''}> Burn captions into the video</label>
    <label class="row mt-s"><input type="checkbox" id="st-bed" ${st.bed ? 'checked' : ''}> Quiet sound bed under the voice</label>
    <div class="row mt-s"><label class="f">Steps (empty = full quality)<input type="number" id="st-steps" value="${st.steps || ''}" min="1" max="100"></label><label class="f">Seed<input type="number" id="st-seed" value="${st.seed}"></label></div>
  </div>
  <div class="card pad mt"><h2>Steps</h2>${s.auto.steps.map((x, i) => `<div class="sh-step ${x.done ? 'done' : (!s.auto.steps.slice(0, i).some(y => !y.done) ? 'next' : '')}"><span class="n">${x.done ? '✓' : i + 1}</span>${esc(x.label)}</div>`).join('')}
    <div class="mute small mt-s">Every shot is under ${(S.limits || {}).max_shot_s || 3} seconds on screen; the short is ${S.settings.target_s || 30} seconds. All clips are made at full quality, one request at a time.</div></div>`;
}
function toneOptions(tones, cur) {
  const T = (tones || {}).tones || [];
  return ['Tones', 'Story personas', 'Personas'].map(g => `<optgroup label="${g}">${T.filter(t => t.group === g).map(t => `<option value="${esc(t.id)}" title="${esc(t.sound + ' - best for: ' + t.best)}" ${(cur || tones.default) === t.id ? 'selected' : ''}>${esc(t.label)} - energy ${t.energy}/5</option>`).join('')}</optgroup>`).join('');
}
function edgeOptions(tones, cur) {
  return ((tones || {}).edges || []).map(e => `<option value="${esc(e.id)}" ${(cur || 'clean') === e.id ? 'selected' : ''}>${esc(e.label)}</option>`).join('');
}

function voiceOptions(cur) {
  const V = window._shVoices || {};
  const out = [];
  for (const [eng, e] of Object.entries(V)) for (const [vn, g] of Object.entries(e.voices)) out.push(`<option value="${eng}|${vn}" ${cur && cur.engine === eng && cur.voice === vn ? 'selected' : ''}>${esc(e.label)} · ${esc(vn)} (${g})</option>`);
  return out.length ? out.join('') : `<option>${esc(cur ? cur.engine + ' ' + cur.voice : '')}</option>`;
}

/* quick / keyframe pipelines */
function planView() {
  const s = S, p = s.plan || {};
  const has = s.shots.length > 0;
  return `<div class="card pad"><div class="row"><h2 style="margin:0">The plan</h2><span class="sp"></span><button class="primary" id="b-plan" ${s.job.state === 'running' ? 'disabled' : ''}>${has ? 'Plan again' : 'Plan the short'}</button></div>
    ${has ? `<div class="mute small mt-s">${esc(p.logline || '')}</div>
      <div class="grid g2 mt-s"><label class="f">The main character<textarea data-plan="character" style="min-height:60px">${esc(p.character || '')}</textarea></label>
      <label class="f">The main place<textarea data-plan="place" style="min-height:60px">${esc(p.place || '')}</textarea></label></div>
      <label class="f mt-s">The look (added to every shot)<input data-plan="look" value="${esc(p.look || '')}"></label>
      <label class="f mt-s">The subjects${p.format ? ` (${esc(p.format)})` : ''}: who and what the story is about, one per line as Name: how it looks<textarea data-plan="subjects" style="min-height:90px" placeholder="Chinese J-20 stealth fighter: twin-engine, dark grey, canards, red and yellow star roundel">${esc((p.subjects || []).map(x => x.name + ': ' + x.visual).join('\n'))}</textarea></label>
      <div class="row mt-s"><button class="small" id="b-subjects" title="Read the story again and write the subject list. The shots stay as they are; write the shots of a beat again to use it.">Find the subjects</button><span class="mute small">Every shot that shows one gets its look added to the picture prompt.</span></div>` : `<p class="mute">The model writes a hook, four to six beats of Hinglish narration and the shots. It takes a minute or two.</p>`}</div>
    ${has ? checksView() + voiceView() + (s.keyframes_on ? keyframesView() : '') + beatsView() : ''}`;
}

/* step 1 after the plan: the voice. Start pictures, clips and the final video wait for it, because the shot lengths follow the real voice */
function voiceView() {
  const s = S, v = s.voice || {}, off = (s.settings.voice_mode || 'narration') === 'none', busy = s.job.state === 'running';
  if (off) return `<div class="card pad mt"><div class="row"><h2 style="margin:0">Voice</h2>${badge('info', 'no narration')}</div><div class="mute small mt-s">Video only: no voice is made, so nothing waits for it.</div></div>`;
  const ok = !s.voice_gate;
  return `<div class="card pad mt"><div class="row"><h2 style="margin:0">Voice</h2>${ok ? badge('good', 'ready') : badge('problem', 'step to do first')}<span class="mute small">${v.have || 0} of ${v.total || 0} beats</span><span class="sp"></span>
    <button class="${ok ? 'small' : 'primary'}" id="b-voice-plan" ${busy ? 'disabled' : ''}>${ok ? 'Make all the voices again' : 'Make the voice for every beat'}</button></div>
    <div class="mute small mt-s">${ok ? 'Every beat has its voice. The shots now follow the real length of the voice.' : esc(s.voice_gate) + ' The start pictures, the clips and the final video unlock when this is done. Listen to each beat below and change its words or its feeling if needed.'}</div></div>`;
}

function checksView() {
  const c = S.checks;
  if (!c) return '';
  const fix = c.issues.find(i => i.fix === 'fit_shots');
  const rethink = c.issues.some(i => i.fix === 'reshoot_all');
  return `<div class="card pad mt"><div class="row"><h2 style="margin:0">Checks</h2>${c.ok ? badge('good', 'ready to make') : badge('problem', c.blockers + ' to fix')}<span class="sp"></span>
    ${fix ? `<button id="b-fit" class="small">Write the shots again to fit</button>` : ''}${rethink ? `<button id="b-rethink" class="small">Plan all the pictures again</button>` : ''}${c.issues.some(i => i.fix === 'make_voice') ? `<button id="b-voice-chk" class="small primary" ${S.job.state === 'running' ? 'disabled' : ''}>Make the voice</button>` : ''}</div>
    ${c.issues.length ? c.issues.map(i => `<div class="${i.level === 'block' ? 'errbox' : 'warnbox'}">${esc(i.text)}</div>`).join('') : '<div class="mute small mt-s">Every shot is under three seconds, the short is ${S.settings.target_s || 30} seconds, and the words pass.</div>'}
    ${S.timeline ? `<div class="mute small mt-s">${S.timeline.estimated ? 'Timing is an estimate until the voice is made.' : 'Timing follows the real voice.'} ${S.timeline.shots.length} shots, ${S.timeline.total_s}s, voice speed x${S.timeline.tempo}.</div>` : ''}</div>`;
}

function castBlock() {
  const st = S.settings;
  const chars = (window._shChars || []).filter(c => c.kind === 'person' && c.status === 'ready');
  const places = (window._shChars || []).filter(c => c.kind === 'place' && c.status === 'ready');
  const cast = st.cast || [];
  const slot = i => {
    const e = cast[i] || {}, ch = chars.find(c => c.id === e.character_id);
    if (!ch) return `<button class="small mt-s" data-castpick="${i}">+ ${i === 0 ? 'Choose main character' : 'Add second character (optional)'}</button>`;
    const lkName = (ch.looks.find(l => l.id === e.look_id) || {}).name || 'canon look';
    return `<div class="row mt-s" style="gap:8px;align-items:center">
      ${ch.thumb ? `<img src="${esc(ch.thumb)}" style="width:52px;height:52px;object-fit:cover;border-radius:6px;flex-shrink:0">` : `<div style="width:52px;height:52px;background:#e0e0e0;border-radius:6px;flex-shrink:0"></div>`}
      <div style="flex:1;min-width:0"><b class="small">${esc(ch.name)}</b><div class="mute small">${esc(lkName)}</div></div>
      <button class="small" data-castpick="${i}">Change</button><button class="small bad" data-castrem="${i}">Remove</button></div>`;
  };
  return `<div class="mt-s"><b class="small">Cast from the Characters library</b>${slot(0)}${slot(1)}
    <label class="f mt-s">Place<select id="st-place"><option value="">no fixed place</option>${places.map(c => `<option value="${esc(c.id)}" ${c.id === st.place_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
    <div class="mute small">${chars.length ? 'Their faces come from the approved library pictures, so they look the same in every shot. Choose the cast before planning.' : 'No ready characters yet: <a href="#/characters">make one in Characters</a> (approve a portrait and a full-body picture).'}</div></div>`;
}

async function castPickerDialog(slot) {
  const chars = (window._shChars || []).filter(c => c.kind === 'person' && c.status === 'ready');
  if (!chars.length) { toast('No ready characters yet — make one in Characters first.', {bad: true}); return null; }

  let chosen = null; // {character_id, look_id}

  const thumbImg = (url, w, h) => url
    ? `<img src="${esc(url)}" style="width:${w}px;height:${h}px;object-fit:cover;border-radius:6px;display:block">`
    : `<div style="width:${w}px;height:${h}px;background:#ccc;border-radius:6px"></div>`;

  const charGrid = () => `<div style="display:flex;flex-wrap:wrap;gap:12px;max-height:65vh;overflow-y:auto;padding:4px">
    ${chars.map(c => `<div class="cp-char" data-cid="${esc(c.id)}" style="cursor:pointer;border:2px solid #e0e0e0;border-radius:8px;padding:10px;text-align:center;width:120px;box-sizing:border-box">
      <div style="display:flex;justify-content:center">${thumbImg(c.thumb, 100, 100)}</div>
      <div class="small" style="margin-top:6px;font-weight:600">${esc(c.name)}</div>
      <div class="mute small">${c.looks.length} look${c.looks.length !== 1 ? 's' : ''}</div>
    </div>`).join('')}
  </div>`;

  const lookGrid = c => {
    const items = [
      {id: '', label: 'Canon look', thumb: c.thumb},
      ...c.looks.filter(l => l.thumb).map(l => ({id: l.id, label: l.name, thumb: l.thumb}))
    ];
    return `<div style="display:flex;gap:12px;height:65vh">
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-content:flex-start;overflow-y:auto;flex:1;padding:4px">
        ${items.map(it => `<div class="cp-look" data-lid="${esc(it.id)}" data-url="${esc(it.thumb)}" style="cursor:pointer;border:2px solid #e0e0e0;border-radius:8px;padding:8px;text-align:center;width:130px;box-sizing:border-box">
          <div style="display:flex;justify-content:center">${thumbImg(it.thumb, 110, 145)}</div>
          <div class="small" style="margin-top:6px">${esc(it.label)}</div>
        </div>`).join('')}
      </div>
      <div style="flex:0 0 220px;display:flex;flex-direction:column;align-items:center;background:#f5f5f5;border-radius:8px;padding:10px;overflow:hidden">
        <div class="mute small" id="cp-prev-lbl">Click a look to preview</div>
        <img id="cp-prev-img" src="" style="max-width:200px;max-height:calc(65vh - 40px);border-radius:6px;margin-top:8px;display:none;object-fit:contain">
      </div>
    </div>`;
  };

  const setTitle = t => { const h = document.querySelector('.dlg h2'); if (h) h.textContent = t; };
  const setBody = html => { const b = document.querySelector('.dlg .dlg-body'); if (b) b.innerHTML = html; };

  const wireLooks = c => {
    document.querySelector('#cp-back').onclick = () => { chosen = null; setTitle(slot === 0 ? 'Choose the main character' : 'Choose second character'); setBody(charGrid()); setTimeout(wireChars, 0); };
    document.querySelectorAll('.dlg .cp-look').forEach(card => {
      card.onclick = () => {
        document.querySelectorAll('.dlg .cp-look').forEach(x => x.style.borderColor = '#e0e0e0');
        card.style.borderColor = '#4f46e5';
        chosen = {character_id: c.id, look_id: card.dataset.lid};
        const img = document.querySelector('#cp-prev-img'), lbl = document.querySelector('#cp-prev-lbl');
        if (card.dataset.url) { img.src = card.dataset.url; img.style.display = 'block'; lbl.textContent = card.querySelector('.small').textContent; }
      };
    });
  };

  const wireChars = () => {
    document.querySelectorAll('.dlg .cp-char').forEach(card => {
      card.onclick = () => {
        const c = chars.find(x => x.id === card.dataset.cid); if (!c) return;
        chosen = {character_id: c.id, look_id: ''};
        setTitle(c.name + ' — choose a look');
        setBody(`<button class="small" id="cp-back" style="margin-bottom:10px">← All characters</button>${lookGrid(c)}`);
        setTimeout(() => wireLooks(c), 0);
      };
    });
  };

  const p = dialog({
    title: slot === 0 ? 'Choose the main character' : 'Choose second character',
    html: charGrid(),
    buttons: [
      {label: 'Cancel', value: null},
      {label: 'Select', primary: true,
       collect: () => chosen,
       validate: v => v ? null : 'Choose a character first'}
    ]
  });
  setTimeout(wireChars, 0);
  return p;
}

function keyframesView() {
  const s = S;
  const done = s.shots.filter(x => x.keyframe).length;
  return `<div class="card pad mt"><div class="row"><h2 style="margin:0">Start pictures (storyboard)</h2><span class="mute small">${done} of ${s.shots.length}</span><span class="sp"></span>
    <button class="small" id="b-keys" ${S.voice_gate || S.job.state === 'running' ? `disabled title="${esc(S.voice_gate || '')}"` : ''}>${done ? 'Make the missing ones' : 'Draw the start pictures'}</button>
    <button class="small ${s.keyframes_confirmed ? '' : 'primary'}" id="b-keys-ok">${s.keyframes_confirmed ? 'Confirmed ✓ (undo)' : 'Pictures are good'}</button></div>
    <p class="mute small">One picture per shot, drawn from the picture prompt under it (edit the prompt, then press Again). Your own pictures are used as they are. Look at them now: animating is the long wait.</p>
    <div class="sh-keys">${s.shots.map(x => { const k = x.keyframes.find(y => y.id === x.keyframe) || x.keyframes.filter(y => y.status === 'done').pop();
      const kb = making(x.keyframes);
      return `<div class="sh-key"><div class="mute row">${esc(x.id)} · ${x.seconds}s · ${esc(x.begins)}<span class="sp"></span>${busyTxt(kb, 'drawing')}</div><div class="sh-wrap">${busyDot(kb, 'This picture')}${k && k.url ? `<img src="${esc(k.url)}" loading="lazy" ${x.keyframe ? '' : 'style="opacity:.55"'}>${x.keyframe ? '' : '<div class="warn small">old picture: the prompt changed after it was drawn. Press Again, or Make clips will draw it first.</div>'}` : `<div class="sh-thumb" style="width:100%">${x.keyframes.some(y => y.status === 'failed') ? 'failed' : 'not made'}</div>`}</div>
        <textarea data-still="${x.id}" style="min-height:70px;font-size:12px;width:100%" ${x.begins === 'upload' || x.begins === 'anchor' ? 'disabled title="This shot uses your own picture"' : ''}>${esc(x.still || x.prompt)}</textarea>
        ${(x.must_show || []).length ? `<div class="mute small" style="margin-top:3px" title="What the picture has to show. Check these when you look at it.">✔ ${esc(x.must_show.join(' · '))}</div>` : ''}
        <div class="row" style="margin-top:4px"><button class="small" data-rewrite-pic="${x.id}" title="The model writes this picture prompt again; you say what should change">Rewrite prompt…</button></div>
        ${k && k.url ? `<div class="row" style="margin-top:4px"><input data-fix="${x.id}" placeholder="Change one thing…" style="flex:1;font-size:12px"><button class="small" data-fixgo="${x.id}">Fix</button></div>` : ''}
        <label class="row small" style="margin-top:4px;gap:5px"><input type="checkbox" data-neg-on="${x.id}" ${x.avoid ? 'checked' : ''}> negative prompt</label>
        <input data-neg="${x.id}" value="${esc(x.avoid || '')}" placeholder="Keep out: e.g. text, extra jets, people" style="width:100%;font-size:12px" ${x.avoid ? '' : 'disabled'}>
        <div class="row" style="margin-top:4px"><button class="small" data-key="${x.id}">Again</button><button class="small" data-up="${x.id}">My picture</button></div></div>`; }).join('')}</div></div>`;
}

function beatsView() {
  const s = S, tl = s.timeline;
  const busy = s.job.state === 'running';
  const clipsHeader = `<div class="card pad mt"><div class="row"><h2 style="margin:0">Shots &amp; clips</h2><span class="sp"></span>
    <button class="small" id="b-move-all" ${busy ? 'disabled' : ''} title="The model writes what moves in every shot (what Wan is asked to do with each picture)">Write motion again…</button>
    <button class="small" id="b-pics-all" ${busy ? 'disabled' : ''} title="The model writes what the image model is asked to draw, for every shot">Write picture prompts again…</button>
    <button class="small" id="b-clips-missing" ${busy || s.voice_gate ? 'disabled' : ''} ${s.voice_gate ? `title="${esc(s.voice_gate)}"` : ''}>Make missing clips</button>
    <button class="primary" id="b-clips-all" ${busy || s.voice_gate ? 'disabled' : ''}>Make all clips</button></div></div>`;
  const sr = (s.script || {}).report;
  const scriptNote = `<div class="row small mt-s"><button class="small" id="b-rewrite-all" ${busy ? 'disabled' : ''} title="Write every scene's words again (same scenes, same pictures), then punch the script up">Rewrite the whole script…</button>${sr ? `<span class="mute">Script: critic score ${esc(sr.score)}/10 after ${esc(sr.rounds)} punch-up round(s)${(sr.problems || []).length ? '. Left to fix: ' + esc(sr.problems.join(' / ')) : ''}.</span>` : ''}</div>`;
  return clipsHeader + scriptNote + s.beats.map((b, bi) => {
    const v = s.voice.beats.find(x => x.beat === b.id) || {};
    const take = (v.attempts || []).filter(a => a.status === 'done' && a.current).pop();
    const shots = s.shots.filter(x => x.beat === b.id);
    return `<div class="sh-beat"><div class="row"><b>${bi + 1}. ${esc(b.name)}</b><span class="mute small">${esc([b.job, b.feeling].filter(Boolean).join(' · '))}</span><span class="sp"></span>
        <select data-tag="${b.id}" class="small" style="width:auto">${['', 'neutral', ...(window._shTags || [])].map(t => `<option value="${t}" ${t === (b.tag || '') ? 'selected' : ''}>${t || 'voice: none'}</option>`).join('')}</select>
        ${busyTxt(making(v.attempts), 'making the voice')}<button class="small" data-rewrite="${b.id}" ${busy ? 'disabled' : ''} title="Write this scene again; you say what should change">Rewrite…</button><button class="small" data-voice="${b.id}">${take ? 'Voice again' : 'Make the voice'}</button></div>
      <textarea data-beat="${b.id}">${esc(b.sentences.map(x => x.text).join('\n'))}</textarea>
      <div class="row small mt-s">${take ? `<audio controls src="${esc(take.url)}" style="height:30px"></audio><span class="mute">${take.seconds}s spoken</span>` : '<span class="mute">no voice yet</span>'}</div>
      ${shots.map(x => shotView(x)).join('')}</div>`;
  }).join('');
}

function shotView(x) {
  const clip = x.clips.find(c => c.id === x.clip) || null;
  const key = x.keyframes.find(c => c.id === x.keyframe) || null;
  const needsKey = S.keyframes_on && !key;
  const media = clip && clip.url ? vid(clip.url, 'muted loop') : key && key.url ? `<img src="${esc(key.url)}">` : (x.clips.some(c => c.status === 'failed') ? 'failed' : 'no clip yet');
  const failed = x.clips.filter(c => c.status === 'failed').pop();
  const cb = making(x.clips), kb = making(x.keyframes);
  return `<div class="sh-shot"><div class="sh-wrap"><div class="sh-thumb">${media}</div>${busyDot(cb || kb, cb ? 'This clip' : 'The start picture')}</div><div>
    <div class="row small"><b>${esc(x.id)}</b><span class="mute">${x.seconds}s · starts: ${esc(x.begins)}</span>${x.old_clip ? badge('warn', 'clip is old') : ''}<span class="sp"></span>
      <label><input type="checkbox" data-shot-flag="character" data-id="${x.id}" ${x.character ? 'checked' : ''}> shows the main character</label>
      <label><input type="checkbox" data-shot-flag="continues" data-id="${x.id}" ${x.continues ? 'checked' : ''}> continues</label>
      <label title="The person in this shot's picture speaks the voice with lip sync (InfiniteTalk). Needs a library character in the shot and the beat's voice."><input type="checkbox" data-shot-flag="avatar" data-id="${x.id}" ${x.avatar ? 'checked' : ''}> talking avatar</label>
      ${x.motion && x.motion.file ? `<span class="small">${badge('good', 'moves like: ' + esc(x.motion.title || 'a video'))} <a href="#" data-motion-clear="${x.id}">remove</a></span>` : `<button class="small" data-motion="${x.id}" title="A video (file, YouTube or Instagram link) drives how the person in this shot moves (Wan Animate). 2 to 3 seconds of it are used.">movement from a video…</button>`}</div>
    ${x.avatar || (x.motion && x.motion.file) ? '' : `<div class="mute small">What moves (sent to Wan with the start picture; name the things that move, do not describe the picture)</div>
    <textarea data-move="${x.id}" style="min-height:64px;font-size:13px" placeholder="Not written yet: press Rewrite motion…">${esc(x.move || '')}</textarea>
    <div class="row small"><button class="small" data-rewrite-move="${x.id}" ${S.job.state === 'running' ? 'disabled' : ''} title="The model writes what moves in this shot; you say what should change">Rewrite motion…</button></div>`}
    <div class="mute small">${S.keyframes_on ? 'The scene as planned (used only to plan the picture and when Wan draws the picture itself)' : 'The scene as planned'}</div>
    <textarea data-shot="${x.id}" style="min-height:64px;font-size:13px">${esc(x.prompt)}</textarea>
    <div class="row small mt-s"><label class="row">Camera <input data-shot-cam="${x.id}" value="${esc(x.camera)}" style="width:150px"></label>
      <button class="small" data-clip="${x.id}" ${S.voice_gate ? `disabled title="${esc(S.voice_gate)}"` : needsKey ? 'disabled title="Draw the start picture first (Again button above)"' : ''}>${clip ? 'Make again' : 'Make this clip'}</button><button class="small" data-up="${x.id}">My picture</button>
      ${busyTxt(cb, 'making the clip')}${busyTxt(kb && !cb, 'drawing the start picture')}
      ${needsKey && !kb ? `<span class="mute">↑ draw start picture first</span>` : ''}
      ${clip ? `<label><input type="checkbox" data-approve="${clip.id}" ${clip.approved ? 'checked' : ''}> keep this one</label>` : ''}
      ${failed && !clip ? `<span class="err">${esc(failed.error)}</span>` : ''}</div></div></div>`;
}

/* remix pipeline */
function rxCharacter(r) {
  const chars = (window._shChars || []).filter(c => c.kind === 'person' && c.status === 'ready'), ch = chars.find(c => c.id === r.character_id);
  return `<div class="row" style="gap:6px"><label class="f" style="flex:1">Character from the library<select id="rx-char"><option value="">none: I upload a picture</option>${chars.map(c => `<option value="${esc(c.id)}" ${c.id === r.character_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
    ${ch && ch.looks.length ? `<label class="f">Look<select id="rx-look"><option value="">canon (full body)</option>${ch.looks.map(l => `<option value="${esc(l.id)}" ${l.id === r.look_id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select></label>` : ''}</div>
    ${r.character_id && !r.character_ok ? '<div class="warnbox">This character has no approved full-body picture yet: approve one in Characters.</div>' : ''}
    ${r.character_id && r.character_ok ? '<div class="mute small">Its approved picture performs the motion. A new approved picture makes an earlier clip old.</div>' : ''}`;
}

function remixView() {
  const s = S, r = s.remix, ck = r.check;
  const sugg = (r.suggest || []).map(w => `<button class="small" data-sugg="${w.start}" title="${w.cuts} cuts, ${w.slow_s}s slow">from ${mm(w.start)} · ${w.cuts} cuts${w.slow_s ? ' · ' + w.slow_s + 's slow' : ' · fast'}</button>`).join('');
  return `<div class="card pad"><h2>1. The video</h2>
    <div class="row"><input id="rx-url" placeholder="YouTube or Instagram link, https://..." value="${esc(r.url || '')}" style="flex:1;min-width:240px"><button class="primary" id="rx-fetch">Fetch the video</button><button id="rx-upload" class="small">or upload a file</button></div>
    ${r.source ? `<div class="mt-s small">${esc((r.info || {}).title || '')} · ${mm((r.info || {}).duration_s || 0)} long · ${(r.cuts || []).length} cuts found</div>
      <div class="mt-s">${vid(r.source_url, 'style="max-height:260px"')}</div>
      ${(r.info && r.info.duration_s < 30) ? `<div class="row mt-s"><label class="f">Fit to 9:16<select id="rx-fit"><option value="crop" ${r.fit === 'crop' ? 'selected' : ''}>Crop the sides</option><option value="pad" ${r.fit === 'pad' ? 'selected' : ''}>Keep it all, black bars</option></select></label></div>
      ${r.driving.length ? '<div class="mt-s small ok">Whole video ready as the motion guide.</div>' : ''}` : `<h4>Pick the 30 seconds</h4><div class="sh-sugg small">Suggested (the fastest-cut stretches): ${sugg || '<span class="mute">none found</span>'}</div>
      <div class="row mt-s"><label class="f">Start (seconds)<input type="number" id="rx-start" value="${r.start}" min="0" step="1"></label>
        <label class="f">Fit to 9:16<select id="rx-fit"><option value="crop" ${r.fit === 'crop' ? 'selected' : ''}>Crop the sides</option><option value="pad" ${r.fit === 'pad' ? 'selected' : ''}>Keep it all, black bars</option></select></label>
        <label class="f">Requests<select id="rx-seg"><option value="1" ${r.segments === 1 ? 'selected' : ''}>One (30 s)</option><option value="2" ${r.segments === 2 ? 'selected' : ''}>Two (15 s each)</option></select></label>
        <button id="rx-window" class="primary">Cut this window</button></div>
      ${r.driving.length ? `<div class="mt-s small ok">Window ready: from ${mm(r.start)}, ${r.window_cuts ? r.window_cuts.length : 0} cuts. ${(r.slow || []).length ? '<span class="warn">' + r.slow.length + ' stretch(es) over three seconds without a cut.</span>' : 'Fast-cut all the way.'}</div>` : ''}`}` : ''}
    <p class="mute small">The character in your picture performs the motion of this video. The video's own background is not kept: the background comes from your picture and the description below.</p></div>
    <div class="card pad mt"><h2>2. The character</h2>
      ${rxCharacter(r)}<div class="row mt-s">${!r.character_id && s.images.anchor ? `<img src="/api/shorts/file/${s.id}/${esc(s.images.anchor)}" style="width:90px;border-radius:8px">` : ''}${r.character_id ? '' : `<button id="st-anchor2">${s.images.anchor ? 'Change the picture' : 'or upload a picture of your own'}</button>`}</div>
      ${r.character_id ? `<label class="f mt-s">Background place from the library (optional)<select id="rx-place"><option value="">none: describe it below</option>${(window._shChars || []).filter(c => c.kind === 'place' && c.status === 'ready').map(c => `<option value="${esc(c.id)}" ${c.id === r.place_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>` : ''}
      <label class="f mt-s">Describe the character and the background (what they wear, where they are)${r.auto_prompt ? ' - leave empty to use the description written from the library' : ''}<textarea id="rx-prompt" placeholder="${esc(r.auto_prompt || '')}">${esc(r.prompt)}</textarea></label>
      ${r.auto_prompt ? `<div class="row small mt-s"><button class="small" id="rx-auto" title="Copy the description written from the library into the box so you can change it">Edit the library description</button><span class="mute">${r.prompt.trim() ? 'Your own text is sent.' : 'The library description is sent: ' + esc(r.auto_prompt.slice(0, 160)) + (r.auto_prompt.length > 160 ? '…' : '')}</span></div>` : ''}
      <div class="row mt-s"><label class="f" style="flex:1">What the motion looks like (optional)<input id="rx-motion" value="${esc(r.motion_prompt)}"></label><label class="f">Pose strength (0 to 10)<input type="number" id="rx-pose" value="${r.pose_strength}" min="0" max="10" step="0.5"></label></div></div>
    <div class="card pad mt"><h2>3. Sound</h2>
      <label class="f">Sound<select id="rx-audio"><option value="none" ${r.audio === 'none' ? 'selected' : ''}>The quiet sound bed only</option><option value="voiceover" ${r.audio === 'voiceover' ? 'selected' : ''}>A voice-over I write (Hinglish, under 80 words)</option><option value="original" ${r.audio === 'original' ? 'selected' : ''}>The video's own sound</option></select></label>
      ${r.audio === 'voiceover' ? `<label class="f mt-s">Voice-over<textarea id="rx-script" style="min-height:90px">${esc(r.script)}</textarea></label><div class="row mt-s"><button id="b-voice-all" class="small">Make the voice-over</button>${s.voice.beats[0] && s.voice.beats[0].chosen ? `<audio controls src="${esc((s.voice.beats[0].attempts.filter(a => a.status === 'done' && a.current).pop() || {}).url || '')}" style="height:30px"></audio>` : '<span class="mute small">not made yet</span>'}</div>` : ''}</div>
    <div class="card pad mt"><h2>4. Rights</h2>
      <label class="row"><input type="checkbox" id="rx-r1" ${r.rights_video ? 'checked' : ''}> I have the right to use this video.</label>
      <label class="row mt-s"><input type="checkbox" id="rx-r2" ${r.rights_character ? 'checked' : ''}> The picture I uploaded is my own, an invented or a licensed character, not a private person (not needed for a library character).</label>
      <div class="mute small mt-s">The downloaded video is only used as the motion guide. It is kept on this machine, never exported and never uploaded.</div></div>
    <div class="card pad mt"><div class="row"><h2 style="margin:0">Animate</h2>${ck.ok ? badge('good', 'ready') : badge('problem', ck.blockers + ' to fix')}<span class="sp"></span><button class="primary" id="rx-make" ${ck.ok && s.job.state !== 'running' ? '' : 'disabled'}>Animate (about ${hd(s.estimate_s)})</button></div>
      ${ck.issues.map(i => `<div class="${i.level === 'block' ? 'errbox' : 'warnbox'}">${esc(i.text)}</div>`).join('')}
      <div class="mt-s mute small">One request cannot be stopped half-way without losing it.</div>
      ${(r.part_clips || []).map((cl, n) => cl.filter(c => c.url).slice(-1).map(c => `<div class="mt-s small">Part ${n + 1}: ${vid(c.url, 'style="max-height:260px"')}</div>`).join('')).join('')}</div>`;
}

function finalView() {
  const f = S.final, last = f.attempts.filter(a => a.status === 'done').pop();
  const miss = f.checklist && !f.checklist.ready ? f.checklist.missing : [];
  return `<div class="card pad mt sh-final"><div class="row"><h2 style="margin:0">The short</h2><span class="sp"></span><button class="primary" id="b-final" ${miss.length || S.voice_gate || (S.job.state === 'running') ? 'disabled' : ''}>${last ? 'Put together again' : 'Put the short together'}</button></div>
    ${miss.length ? `<div class="mute small mt-s">Still missing: ${esc(miss.slice(0, 6).join(', '))}${miss.length > 6 ? ' and ' + (miss.length - 6) + ' more' : ''}</div>` : ''}
    ${last ? `<div class="mt-s">${vid(last.url)}</div><div class="row mt-s small"><a href="${esc(last.url)}" download>Download the MP4</a><span class="mute">${last.duration_s}s · 1080x1920${last.bed ? ' · with sound bed' : ''}</span></div>` : '<p class="mute small">The 30-second 9:16 video appears here.</p>'}
    ${f.attempts.filter(a => a.status === 'failed').slice(-1).map(a => `<div class="errbox">${esc(a.error)}</div>`).join('')}</div>`;
}

async function motionDialog(shotId) {
  const html = `<p class="small">The person in this shot will move like the person in the video: 2 to 3 seconds of it are used. The video is only a movement guide; it stays on this machine and is never exported or uploaded. The background and clothes come from your start picture.</p>
    <label class="f">YouTube or Instagram link<input id="m-url" placeholder="https://..."></label>
    <label class="f mt-s">or a video file<input type="file" id="m-file" accept="video/*"></label>
    <label class="f mt-s">Start at (seconds)<input type="number" id="m-start" value="0" min="0" step="0.5"></label>
    <label class="row mt-s"><input type="checkbox" id="m-ok"> I have the right to use this video.</label>`;
  const v = await dialog({title: 'Movement from a video', html, buttons: [{label: 'Cancel', value: null}, {label: 'Use it', primary: true,
    collect: l => ({url: l.querySelector('#m-url').value.trim(), file: l.querySelector('#m-file').files[0], start: +l.querySelector('#m-start').value || 0, ok: l.querySelector('#m-ok').checked}),
    validate: x => !x.ok ? 'Tick the box to confirm.' : (!x.url && !x.file) ? 'Paste a link or choose a file.' : ''}]});
  if (!v) return;
  const fd = new FormData(); fd.append('rights', 'true'); fd.append('start', v.start); if (v.file) fd.append('file', v.file); else fd.append('url', v.url);
  await act(null, async () => { const r = await call('/' + SID + '/shots/' + shotId + '/motion', {method: 'POST', form: fd}); if (v.file) { S = r; render(); } else await refresh(true); return true; }, v.file ? 'Movement ready' : 'Fetching the video');
}

/* ───────── wiring ───────── */
function wire() {
  const q = s => document.querySelector(s), all = s => [...document.querySelectorAll(s)];
  const on = (sel, fn) => { const e = q(sel); if (e) e.onclick = () => fn(e); };
  const st = (id, key, conv = v => v) => { const e = q(id); if (e) e.onchange = () => patch('/settings', {[key]: conv(e.type === 'checkbox' ? e.checked : e.value)}); };
  st('#st-target', 'target_s', v => +v); st('#st-script', 'script_engine'); st('#st-mode', 'image_mode'); st('#st-imodel', 'image_model'); st('#st-style', 'visual_style'); st('#st-char', 'character_text'); st('#st-tone', 'tone'); st('#st-format', 'format'); st('#st-size', 'size'); st('#st-chain', 'chain'); st('#st-fast', 'speed_lora'); st('#st-lang', 'language'); st('#st-toneid', 'tone_id'); st('#st-edge', 'edge'); st('#st-vspeed', 'voice_speed', v => +v); st('#st-size14', 'size_14b'); st('#st-review', 'review_keyframes');
  st('#st-up', 'upscale'); st('#st-cap', 'captions'); st('#st-bed', 'bed'); st('#st-steps', 'steps', v => v === '' ? null : +v); st('#st-seed', 'seed', v => +v || 0);
  const vm = q('#st-vmode'); if (vm) vm.onchange = () => patch('/settings', {voice_mode: vm.value});
  const vs = q('#st-voice'); if (vs) vs.onchange = () => { const [engine, voice] = vs.value.split('|'); patch('/settings', {voice: {engine, voice}}); };
  on('#st-anchor', () => pick('image/*', f => upload('/images/anchor', f))); on('#st-anchor2', () => pick('image/*', f => upload('/images/anchor', f)));
  on('#st-anchor-x', async () => { S = await call('/' + SID + '/images/anchor', {method: 'DELETE'}); render(); });
  on('#b-plan', b => post(b, '/plan', {}, 'Planning started'));
  on('#b-fit', b => post(b, '/fit', {}, 'Writing the shots again'));
  on('#b-rethink', b => post(b, '/rethink', {}, 'Planning all the pictures again'));
  on('#b-voice-chk', b => post(b, '/voice', {only_missing: true}, 'Making the voice'));
  on('#b-voice-plan', b => post(b, '/voice', {only_missing: !!S.voice_gate}, 'Making the voice'));
  on('#b-keys', b => post(b, '/keyframes', {}, 'Keyframes started'));
  on('#b-keys-ok', b => post(b, '/keyframes/confirm', {confirmed: !S.keyframes_confirmed}));
  on('#b-final', b => post(b, '/final', {}, 'Putting the short together'));
  on('#b-voice-all', b => post(b, '/voice', {only_missing: false}, 'Making the voice'));
  on('#b-subjects', b => post(b, '/subjects', {}, 'Finding the subjects'));
  all('[data-plan]').forEach(e => e.onchange = () => patch('/plan', {[e.dataset.plan]: e.value}));
  all('[data-beat]').forEach(e => e.onchange = () => patch('/narration', {beats: [{id: e.dataset.beat, sentences: e.value.split('\n')}]}));
  all('[data-tag]').forEach(e => e.onchange = () => { const ta = q(`[data-beat="${e.dataset.tag}"]`); patch('/narration', {beats: [{id: e.dataset.tag, sentences: ta.value.split('\n'), tag: e.value}]}); });
  all('[data-move]').forEach(e => e.onchange = () => patch('/shots/' + e.dataset.move, {move: e.value}));
  all('[data-rewrite-move]').forEach(e => e.onclick = async () => {
    const t = await textDlg(`Rewrite the motion of ${e.dataset.rewriteMove}`, 'What should move, and how? (for example: he turns his head fast, the camera pans left)', '', true);
    if (t === null || t.trim().length < 3) return;
    post(e, '/motion/write', {shot_id: e.dataset.rewriteMove, instruction: t.trim()}, 'Writing the motion');
  });
  on('#b-move-all', async b => {
    const t = await textDlg('Write the motion of every shot again', 'Anything to change in all of them? (optional)', '', true);
    if (t === null) return;
    post(b, '/motion/write', {instruction: t.trim()}, 'Writing the motion');
  });
  all('[data-rewrite-pic]').forEach(e => e.onclick = async () => {
    const t = await textDlg(`Rewrite the picture prompt of ${e.dataset.rewritePic}`, 'What should the picture show or fix? (for example: exactly three jets, missiles under the wings)', '', true);
    if (t === null || t.trim().length < 3) return;
    post(e, '/pictures/write', {shot_id: e.dataset.rewritePic, instruction: t.trim()}, 'Writing the picture prompt');
  });
  on('#b-pics-all', async b => {
    const t = await textDlg('Write all picture prompts again', 'Anything to change in every picture? (optional)', '', true);
    if (t === null) return;
    post(b, '/pictures/write', {instruction: t.trim()}, 'Writing the picture prompts');
  });
  all('[data-rewrite]').forEach(e => e.onclick = async () => {
    const i = S.beats.findIndex(b => b.id === e.dataset.rewrite);
    const t = await textDlg(`Rewrite scene ${i + 1}: ${S.beats[i].name}`, 'What should change? (for example: make it scarier, let her say his name, shorter and colder)', '', true);
    if (t === null || t.trim().length < 3) return;
    post(e, '/rewrite', {beat_id: e.dataset.rewrite, instruction: t.trim()}, 'Rewriting the scene');
  });
  on('#b-rewrite-all', async b => {
    const t = await textDlg('Rewrite the whole script', 'What should change? (optional; leave blank for a sharper, more concrete version)', '', true);
    if (t === null) return;
    post(b, '/rewrite', {instruction: t.trim()}, 'Rewriting the script');
  });
  all('[data-voice]').forEach(e => e.onclick = () => post(e, '/voice', {beat_ids: [e.dataset.voice], only_missing: false}, 'Making the voice'));
  all('[data-shot]').forEach(e => e.onchange = () => patch('/shots/' + e.dataset.shot, {prompt: e.value}));
  all('[data-castpick]').forEach(b => b.onclick = async () => {
    const slot = +b.dataset.castpick;
    const result = await castPickerDialog(slot);
    if (!result) return;
    const cast = [...(S.settings.cast || [])];
    cast[slot] = result;
    S = await act(null, () => call('/' + SID + '/settings', {method: 'PATCH', json: {cast: cast.filter(Boolean)}})) || S;
    render();
  });
  all('[data-castrem]').forEach(b => b.onclick = async () => {
    const slot = +b.dataset.castrem;
    const cast = (S.settings.cast || []).filter((_, i) => i !== slot);
    S = await act(null, () => call('/' + SID + '/settings', {method: 'PATCH', json: {cast}})) || S;
    render();
  });
  st('#st-place', 'place_id');
  all('[data-fixgo]').forEach(e => e.onclick = () => { const t = document.querySelector(`[data-fix="${e.dataset.fixgo}"]`).value; if (t.trim().length < 4) { toast('Say what to change', {bad: true}); return; } post(e, '/shots/' + e.dataset.fixgo + '/fix', {instruction: t}, 'Changing the picture'); });
  all('[data-still]').forEach(e => e.onchange = () => patch('/shots/' + e.dataset.still, {still: e.value}));
  all('[data-shot-cam]').forEach(e => e.onchange = () => patch('/shots/' + e.dataset.shotCam, {camera: e.value}));
  all('[data-motion]').forEach(e => e.onclick = () => motionDialog(e.dataset.motion));
  all('[data-motion-clear]').forEach(e => e.onclick = async ev => { ev.preventDefault(); await call('/shots/' + e.dataset.motionClear + '/motion', {method: 'DELETE'}); refresh(true); });
  all('[data-shot-flag]').forEach(e => e.onchange = () => patch('/shots/' + e.dataset.id, {[e.dataset.shotFlag]: e.checked}));
  all('[data-clip]').forEach(e => e.onclick = () => post(e, '/clips', {shot_ids: [e.dataset.clip], only_missing: false}, 'Making the clip'));
  on('#b-clips-all', b => post(b, '/clips', {only_missing: false}, 'Making all clips'));
  on('#b-clips-missing', b => post(b, '/clips', {only_missing: true}, 'Making missing clips'));
  all('[data-neg-on]').forEach(e => e.onchange = () => { const t = document.querySelector(`[data-neg="${e.dataset.negOn}"]`); t.disabled = !e.checked; if (e.checked) t.focus(); });
  all('[data-key]').forEach(e => e.onclick = async () => {
    const id = e.dataset.key, on = document.querySelector(`[data-neg-on="${id}"]`), t = document.querySelector(`[data-neg="${id}"]`);
    const want = on && on.checked && t ? t.value.trim() : '';
    const sh = S.shots.find(x => x.id === id);
    if (sh && (sh.avoid || '') !== want) { try { await call('/' + SID + '/shots/' + id, {method: 'PATCH', json: {avoid: want}}); } catch (err) { toast(err.message, {bad: true}); return; } }
    post(e, '/keyframes', {shot_ids: [id], only_missing: false}, 'Making the keyframe');
  });
  all('[data-up]').forEach(e => e.onclick = () => pick('image/*', f => upload('/images/shot/' + e.dataset.up, f, e)));
  all('[data-approve]').forEach(e => e.onchange = async () => { await call('/item/' + e.dataset.approve + '/approve', {method: 'POST', json: {confirmed: e.checked}}); refresh(true); });
  // remix
  on('#rx-fetch', b => { const u = q('#rx-url').value.trim(); if (!u) return toast('Paste the YouTube link first', {bad: true}); post(b, '/remix/fetch', {url: u}, 'Fetching the video'); });
  on('#rx-upload', () => pick('video/*', f => upload('/remix/upload', f)));
  const win = start => act(null, async () => { S = await call('/' + SID + '/remix/window', {method: 'POST', json: {start, fit: q('#rx-fit').value, segments: +q('#rx-seg').value}}); render(); return true; }, 'Window ready');
  on('#rx-window', () => win(+q('#rx-start').value || 0));
  all('[data-sugg]').forEach(e => e.onclick = () => win(+e.dataset.sugg));
  { const fitEl = q('#rx-fit'); if (fitEl && S.remix && S.remix.info && S.remix.info.duration_s < 30) fitEl.onchange = () => win(0); }
  const rx = (id, key, conv = v => v) => { const e = q(id); if (e) e.onchange = () => patch('/remix', {[key]: conv(e.type === 'checkbox' ? e.checked : e.value)}); };
  rx('#rx-char', 'character_id'); rx('#rx-look', 'look_id');
  rx('#rx-prompt', 'prompt'); rx('#rx-place', 'place_id'); on('#rx-auto', () => patch('/remix', {prompt: S.remix.auto_prompt})); rx('#rx-motion', 'motion_prompt'); rx('#rx-pose', 'pose_strength', v => +v); rx('#rx-audio', 'audio'); rx('#rx-script', 'script'); rx('#rx-r1', 'rights_video'); rx('#rx-r2', 'rights_character');
  on('#rx-make', b => post(b, '/remix/make', {}, 'Animating'));
}

/* option lists (voices, tags) */
(async () => {
  try { const o = await api('/shorts/options'); window._shVoices = o.voices; window._shTags = o.tags; window._shOpts = o; window._shChars = await api('/characters').catch(() => []); } catch { /* the screen works without; the voice list fills in on the next load */ }
})();
})();
