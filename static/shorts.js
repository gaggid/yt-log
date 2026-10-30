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
  $('#sh-list').innerHTML = rows.length ? `<table><thead><tr><th>Short</th><th>Pipeline</th><th>Shots</th><th>Status</th><th>Updated</th></tr></thead><tbody>${rows.map(r => `
    <tr class="click" onclick="location.hash='#/short/${r.id}'"><td><b>${esc(r.title)}</b></td><td>${esc(r.pipeline)}</td><td>${r.shots}</td><td>${badge(r.status === 'made' ? 'done' : 'info', r.status)}</td><td class="mute small">${fmtDate(r.updated_at)}</td></tr>`).join('')}</tbody></table>`
    : `<div class="big-empty"><h2>Make your first short</h2><p class="mute" style="max-width:560px;margin:0 auto 16px">Pick a Wan model, give an idea or an approved story, and the app plans 11 to 13 fast shots, speaks the narration, makes every clip and puts a 30-second 9:16 video together.</p><button class="primary" onclick="newShort()">+ New short</button></div>`;
};

async function newShort() {
  const [opts, stories] = await Promise.all([call('/options'), call('/stories').catch(() => [])]);
  const pipes = Object.entries(opts.pipelines);
  const html = `<div class="wide-dlg"></div>
    <h4 style="margin-top:0">Which model</h4>${pipes.map(([k, p], i) => `<label class="sh-pipe ${p.available === false ? 'off' : ''}"><input type="radio" name="pipe" value="${k}" ${i === 0 ? 'checked' : ''}> <b>${esc(p.label)}</b>
      <div class="mute small">${esc(p.about)}</div>${p.available === false ? `<div class="err small">The gateway does not list: ${esc(p.missing.join(', '))}</div>` : ''}</label>`).join('')}
    <div id="sh-src"><h4>What is it about</h4>
      <label class="f">Where the idea comes from<select id="sh-kind"><option value="idea">Write an idea</option><option value="story" ${stories.length ? '' : 'disabled'}>An approved story${stories.length ? '' : ' (none yet)'}</option></select></label>
      <label class="f mt-s" id="sh-idea-l">The idea, in a sentence or two<textarea id="sh-idea" placeholder="A delivery rider finds a wallet with a lakh rupees in it. What does he do?"></textarea></label>
      <label class="f mt-s" id="sh-story-l" hidden>The story<select id="sh-story">${stories.map(s => `<option value="${esc(s.id)}">${esc(s.title)} (${esc(s.project)})</option>`).join('')}</select></label></div>
    <h4>Length</h4>
    <label class="f">Video duration (seconds)<input type="number" id="sh-dur" value="30" min="10" max="30" step="1" style="width:80px">
      <span class="small mute">10–30 seconds. The voice, shot count and timeline all adjust automatically.</span></label>`;
  const dlg = dialog({title: 'New short', html, buttons: [{label: 'Cancel', value: null}, {label: 'Create', primary: true,
    collect: l => { const dur = Math.max(10, Math.min(30, parseInt(l.querySelector('#sh-dur').value) || 30)); return {pipeline: l.querySelector('input[name=pipe]:checked').value, kind: l.querySelector('#sh-kind').value, text: l.querySelector('#sh-idea').value, candidate_id: l.querySelector('#sh-story').value, settings: {target_s: dur}}; },
    validate: v => v.pipeline !== 'remix' && v.kind === 'idea' && v.text.trim().length < 10 ? 'Write the idea in a sentence or two.' : ''}]});
  setTimeout(() => {
    const k = document.querySelector('#sh-kind'), p = () => document.querySelectorAll('input[name=pipe]');
    const sync = () => { const remix = document.querySelector('input[name=pipe]:checked')?.value === 'remix'; $('#sh-src').hidden = remix; const st = k.value === 'story'; $('#sh-idea-l').hidden = st; $('#sh-story-l').hidden = !st; };
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
    <div class="mt-s small">${s.images.anchor ? `<img src="/api/shorts/file/${s.id}/${esc(s.images.anchor)}" style="width:70px;border-radius:6px;vertical-align:middle"> <button class="small" id="st-anchor">Change</button> <button class="small bad" id="st-anchor-x">Remove</button>` : `<button class="small" id="st-anchor">Upload the main character's picture</button>`}</div>
    <label class="f mt-s">Describe that character in a line (used in the shots that show them)<textarea id="st-char" style="min-height:48px">${esc(st.character_text || '')}</textarea></label>
    <label class="f mt-s">Tone (optional)<input id="st-tone" value="${esc(st.tone || '')}" placeholder="funny, tense, warm..."></label>`}
    <label class="f mt-s">Audio<select id="st-vmode"><option value="narration" ${(st.voice_mode || 'narration') === 'narration' ? 'selected' : ''}>Narration voice (generated)</option><option value="none" ${st.voice_mode === 'none' ? 'selected' : ''}>No voice — video only (silent or background music)</option></select></label>
    ${(st.voice_mode || 'narration') !== 'none' ? `<label class="f mt-s">Voice<select id="st-voice">${voiceOptions(st.voice)}</select></label>` : ''}
    ${s.pipeline === 'quick' ? `<label class="f mt-s">Picture size<select id="st-size"><option value="480x832" ${st.size === '480x832' ? 'selected' : ''}>480x832 (about 20 min)</option><option value="704x1280" ${st.size === '704x1280' ? 'selected' : ''}>704x1280 sharper (about an hour)</option></select></label>
      <label class="row mt-s"><input type="checkbox" id="st-chain" ${st.chain ? 'checked' : ''}> A shot marked "continues" starts from the last frame of the one before</label>` : ''}
    ${s.keyframes_on ? `<label class="row mt-s"><input type="checkbox" id="st-review" ${st.review_keyframes ? 'checked' : ''}> Stop to look at the start pictures before animating</label>` : ''}
    <label class="row mt-s"><input type="checkbox" id="st-cap" ${st.captions ? 'checked' : ''}> Burn captions into the video</label>
    <label class="row mt-s"><input type="checkbox" id="st-bed" ${st.bed ? 'checked' : ''}> Quiet sound bed under the voice</label>
    <div class="row mt-s"><label class="f">Steps (empty = full quality)<input type="number" id="st-steps" value="${st.steps || ''}" min="1" max="100"></label><label class="f">Seed<input type="number" id="st-seed" value="${st.seed}"></label></div>
  </div>
  <div class="card pad mt"><h2>Steps</h2>${s.auto.steps.map((x, i) => `<div class="sh-step ${x.done ? 'done' : (!s.auto.steps.slice(0, i).some(y => !y.done) ? 'next' : '')}"><span class="n">${x.done ? '✓' : i + 1}</span>${esc(x.label)}</div>`).join('')}
    <div class="mute small mt-s">Every shot is under ${(S.limits || {}).max_shot_s || 3} seconds on screen; the short is ${S.settings.target_s || 30} seconds. All clips are made at full quality, one request at a time.</div></div>`;
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
      <label class="f mt-s">The look (added to every shot)<input data-plan="look" value="${esc(p.look || '')}"></label>` : `<p class="mute">The model writes a hook, four to six beats of Hinglish narration and the shots. It takes a minute or two.</p>`}</div>
    ${has ? checksView() + (s.keyframes_on ? keyframesView() : '') + beatsView() : ''}`;
}

function checksView() {
  const c = S.checks;
  if (!c) return '';
  const fix = c.issues.find(i => i.fix === 'fit_shots');
  return `<div class="card pad mt"><div class="row"><h2 style="margin:0">Checks</h2>${c.ok ? badge('good', 'ready to make') : badge('problem', c.blockers + ' to fix')}<span class="sp"></span>
    ${fix ? `<button id="b-fit" class="small">Write the shots again to fit</button>` : ''}</div>
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
    <button class="small" id="b-keys">${done ? 'Make the missing ones' : 'Draw the start pictures'}</button>
    <button class="small ${s.keyframes_confirmed ? '' : 'primary'}" id="b-keys-ok">${s.keyframes_confirmed ? 'Confirmed ✓ (undo)' : 'Pictures are good'}</button></div>
    <p class="mute small">One picture per shot, drawn from the picture prompt under it (edit the prompt, then press Again). Your own pictures are used as they are. Look at them now: animating is the long wait.</p>
    <div class="sh-keys">${s.shots.map(x => { const k = x.keyframes.find(y => y.id === x.keyframe) || x.keyframes.filter(y => y.status === 'done').pop();
      return `<div class="sh-key"><div class="mute">${esc(x.id)} · ${x.seconds}s · ${esc(x.begins)}</div>${k && k.url ? `<img src="${esc(k.url)}" loading="lazy">` : `<div class="sh-thumb" style="width:100%">${x.keyframes.some(y => y.status === 'failed') ? 'failed' : 'not made'}</div>`}
        <textarea data-still="${x.id}" style="min-height:70px;font-size:12px;width:100%" ${x.begins === 'upload' || x.begins === 'anchor' ? 'disabled title="This shot uses your own picture"' : ''}>${esc(x.still || x.prompt)}</textarea>
        ${k && k.url ? `<div class="row" style="margin-top:4px"><input data-fix="${x.id}" placeholder="Change one thing…" style="flex:1;font-size:12px"><button class="small" data-fixgo="${x.id}">Fix</button></div>` : ''}
        <div class="row" style="margin-top:4px"><button class="small" data-key="${x.id}">Again</button><button class="small" data-up="${x.id}">My picture</button></div></div>`; }).join('')}</div></div>`;
}

function beatsView() {
  const s = S, tl = s.timeline;
  return s.beats.map((b, bi) => {
    const v = s.voice.beats.find(x => x.beat === b.id) || {};
    const take = (v.attempts || []).filter(a => a.status === 'done' && a.current).pop();
    const shots = s.shots.filter(x => x.beat === b.id);
    return `<div class="sh-beat"><div class="row"><b>${bi + 1}. ${esc(b.name)}</b><span class="mute small">${esc(b.feeling || '')}</span><span class="sp"></span>
        <select data-tag="${b.id}" class="small" style="width:auto">${['', 'neutral', ...(window._shTags || [])].map(t => `<option value="${t}" ${t === (b.tag || '') ? 'selected' : ''}>${t || 'voice: none'}</option>`).join('')}</select>
        <button class="small" data-voice="${b.id}">${take ? 'Voice again' : 'Make the voice'}</button></div>
      <textarea data-beat="${b.id}">${esc(b.sentences.map(x => x.text).join('\n'))}</textarea>
      <div class="row small mt-s">${take ? `<audio controls src="${esc(take.url)}" style="height:30px"></audio><span class="mute">${take.seconds}s spoken</span>` : '<span class="mute">no voice yet</span>'}</div>
      ${shots.map(x => shotView(x)).join('')}</div>`;
  }).join('');
}

function shotView(x) {
  const clip = x.clips.find(c => c.id === x.clip) || null;
  const key = x.keyframes.find(c => c.id === x.keyframe) || null;
  const media = clip && clip.url ? vid(clip.url, 'muted loop') : key && key.url ? `<img src="${esc(key.url)}">` : (x.clips.some(c => c.status === 'failed') ? 'failed' : 'no clip yet');
  const failed = x.clips.filter(c => c.status === 'failed').pop();
  return `<div class="sh-shot"><div class="sh-thumb">${media}</div><div>
    <div class="row small"><b>${esc(x.id)}</b><span class="mute">${x.seconds}s · starts: ${esc(x.begins)}</span>${x.old_clip ? badge('warn', 'clip is old') : ''}<span class="sp"></span>
      <label><input type="checkbox" data-shot-flag="character" data-id="${x.id}" ${x.character ? 'checked' : ''}> shows the main character</label>
      <label><input type="checkbox" data-shot-flag="continues" data-id="${x.id}" ${x.continues ? 'checked' : ''}> continues</label>
      <label title="The person in this shot's picture speaks the voice with lip sync (InfiniteTalk). Needs a library character in the shot and the beat's voice."><input type="checkbox" data-shot-flag="avatar" data-id="${x.id}" ${x.avatar ? 'checked' : ''}> talking avatar</label>
      ${x.motion && x.motion.file ? `<span class="small">${badge('good', 'moves like: ' + esc(x.motion.title || 'a video'))} <a href="#" data-motion-clear="${x.id}">remove</a></span>` : `<button class="small" data-motion="${x.id}" title="A video (file, YouTube or Instagram link) drives how the person in this shot moves (Wan Animate). 2 to 3 seconds of it are used.">movement from a video…</button>`}</div>
    <textarea data-shot="${x.id}" style="min-height:64px;font-size:13px">${esc(x.prompt)}</textarea>
    <div class="row small mt-s"><label class="row">Camera <input data-shot-cam="${x.id}" value="${esc(x.camera)}" style="width:150px"></label>
      <button class="small" data-clip="${x.id}">${clip ? 'Make again' : 'Make this clip'}</button><button class="small" data-up="${x.id}">My picture</button>
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
      <h4>Pick the 30 seconds</h4><div class="sh-sugg small">Suggested (the fastest-cut stretches): ${sugg || '<span class="mute">none found</span>'}</div>
      <div class="row mt-s"><label class="f">Start (seconds)<input type="number" id="rx-start" value="${r.start}" min="0" step="1"></label>
        <label class="f">Fit to 9:16<select id="rx-fit"><option value="crop" ${r.fit === 'crop' ? 'selected' : ''}>Crop the sides</option><option value="pad" ${r.fit === 'pad' ? 'selected' : ''}>Keep it all, black bars</option></select></label>
        <label class="f">Requests<select id="rx-seg"><option value="1" ${r.segments === 1 ? 'selected' : ''}>One (30 s)</option><option value="2" ${r.segments === 2 ? 'selected' : ''}>Two (15 s each)</option></select></label>
        <button id="rx-window" class="primary">Cut this window</button></div>
      ${r.driving.length ? `<div class="mt-s small ok">Window ready: from ${mm(r.start)}, ${r.window_cuts ? r.window_cuts.length : 0} cuts. ${(r.slow || []).length ? `<span class="warn">${r.slow.length} stretch(es) over three seconds without a cut.</span>` : 'Fast-cut all the way.'}</div>` : ''}` : ''}
    <p class="mute small">The character in your picture performs the motion of this video. The video's own background is not kept: the background comes from your picture and the description below.</p></div>
    <div class="card pad mt"><h2>2. The character</h2>
      ${rxCharacter(r)}<div class="row mt-s">${!r.character_id && s.images.anchor ? `<img src="/api/shorts/file/${s.id}/${esc(s.images.anchor)}" style="width:90px;border-radius:8px">` : ''}${r.character_id ? '' : `<button id="st-anchor2">${s.images.anchor ? 'Change the picture' : 'or upload a picture of your own'}</button>`}</div>
      <label class="f mt-s">Describe the character and the background (what they wear, where they are)<textarea id="rx-prompt">${esc(r.prompt)}</textarea></label>
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
  return `<div class="card pad mt sh-final"><div class="row"><h2 style="margin:0">The short</h2><span class="sp"></span><button class="primary" id="b-final" ${miss.length || (S.job.state === 'running') ? 'disabled' : ''}>${last ? 'Put together again' : 'Put the short together'}</button></div>
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
  st('#st-mode', 'image_mode'); st('#st-imodel', 'image_model'); st('#st-char', 'character_text'); st('#st-tone', 'tone'); st('#st-size', 'size'); st('#st-chain', 'chain'); st('#st-review', 'review_keyframes');
  st('#st-cap', 'captions'); st('#st-bed', 'bed'); st('#st-steps', 'steps', v => v === '' ? null : +v); st('#st-seed', 'seed', v => +v || 0);
  const vm = q('#st-vmode'); if (vm) vm.onchange = () => patch('/settings', {voice_mode: vm.value});
  const vs = q('#st-voice'); if (vs) vs.onchange = () => { const [engine, voice] = vs.value.split('|'); patch('/settings', {voice: {engine, voice}}); };
  on('#st-anchor', () => pick('image/*', f => upload('/images/anchor', f))); on('#st-anchor2', () => pick('image/*', f => upload('/images/anchor', f)));
  on('#st-anchor-x', async () => { S = await call('/' + SID + '/images/anchor', {method: 'DELETE'}); render(); });
  on('#b-plan', b => post(b, '/plan', {}, 'Planning started'));
  on('#b-fit', b => post(b, '/fit', {}, 'Writing the shots again'));
  on('#b-keys', b => post(b, '/keyframes', {}, 'Keyframes started'));
  on('#b-keys-ok', b => post(b, '/keyframes/confirm', {confirmed: !S.keyframes_confirmed}));
  on('#b-final', b => post(b, '/final', {}, 'Putting the short together'));
  on('#b-voice-all', b => post(b, '/voice', {only_missing: false}, 'Making the voice'));
  all('[data-plan]').forEach(e => e.onchange = () => patch('/plan', {[e.dataset.plan]: e.value}));
  all('[data-beat]').forEach(e => e.onchange = () => patch('/narration', {beats: [{id: e.dataset.beat, sentences: e.value.split('\n')}]}));
  all('[data-tag]').forEach(e => e.onchange = () => { const ta = q(`[data-beat="${e.dataset.tag}"]`); patch('/narration', {beats: [{id: e.dataset.tag, sentences: ta.value.split('\n'), tag: e.value}]}); });
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
  all('[data-key]').forEach(e => e.onclick = () => post(e, '/keyframes', {shot_ids: [e.dataset.key], only_missing: false}, 'Making the keyframe'));
  all('[data-up]').forEach(e => e.onclick = () => pick('image/*', f => upload('/images/shot/' + e.dataset.up, f, e)));
  all('[data-approve]').forEach(e => e.onchange = async () => { await call('/item/' + e.dataset.approve + '/approve', {method: 'POST', json: {confirmed: e.checked}}); refresh(true); });
  // remix
  on('#rx-fetch', b => { const u = q('#rx-url').value.trim(); if (!u) return toast('Paste the YouTube link first', {bad: true}); post(b, '/remix/fetch', {url: u}, 'Fetching the video'); });
  on('#rx-upload', () => pick('video/*', f => upload('/remix/upload', f)));
  const win = start => act(null, async () => { S = await call('/' + SID + '/remix/window', {method: 'POST', json: {start, fit: q('#rx-fit').value, segments: +q('#rx-seg').value}}); render(); return true; }, 'Window ready');
  on('#rx-window', () => win(+q('#rx-start').value || 0));
  all('[data-sugg]').forEach(e => e.onclick = () => win(+e.dataset.sugg));
  const rx = (id, key, conv = v => v) => { const e = q(id); if (e) e.onchange = () => patch('/remix', {[key]: conv(e.type === 'checkbox' ? e.checked : e.value)}); };
  rx('#rx-char', 'character_id'); rx('#rx-look', 'look_id');
  rx('#rx-prompt', 'prompt'); rx('#rx-motion', 'motion_prompt'); rx('#rx-pose', 'pose_strength', v => +v); rx('#rx-audio', 'audio'); rx('#rx-script', 'script'); rx('#rx-r1', 'rights_video'); rx('#rx-r2', 'rights_character');
  on('#rx-make', b => post(b, '/remix/make', {}, 'Animating'));
}

/* option lists (voices, tags) */
(async () => {
  try { const o = await api('/shorts/options'); window._shVoices = o.voices; window._shTags = o.tags; window._shOpts = o; window._shChars = await api('/characters').catch(() => []); } catch { /* the screen works without; the voice list fills in on the next load */ }
})();
})();
