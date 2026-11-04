/* Character Studio (docs/PLAN_characters.md): a library of reusable characters and places, drawn and developed with the gateway image models. Uses the helpers of index.html ($, api, esc, act, toast, dialog, textDlg, confirmDlg, badge, bar, hd). */
(() => {
const css = document.createElement('style');
css.textContent = `
.ch-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px;margin-top:14px}
.ch-card{border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden;cursor:pointer}
.ch-card:hover{border-color:var(--accent)}
.ch-card .ph{aspect-ratio:3/4;background:var(--bg);display:grid;place-items:center;color:var(--mute);font-size:12px}
.ch-card img{width:100%;height:100%;object-fit:cover;display:block}
.ch-card .meta{padding:8px 10px;font-size:13px}
.ch-studio{display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px;align-items:start;margin-top:12px}
.ch-side{position:sticky;top:64px;max-height:calc(100vh - 80px);overflow:auto}
.ch-slot{display:grid;grid-template-columns:92px 1fr;gap:6px;align-items:center;margin:4px 0;font-size:12px}
.ch-slot input{font-size:13px}.ch-slot.gap input{border-color:var(--warn,#d9822b)}
.ch-views{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.ch-pic{border:1px solid var(--line);border-radius:10px;padding:6px;background:var(--panel);font-size:12px}
.ch-pic.canon{border:3px solid var(--ok,#2a9d5c)}
.ch-pic img{width:100%;border-radius:6px;display:block;background:var(--bg);cursor:zoom-in}
.ch-pic .ph{aspect-ratio:3/4;display:grid;place-items:center;color:var(--mute);background:var(--bg);border-radius:6px;text-align:center;padding:4px}
.ch-lora{display:flex;gap:6px;align-items:center;margin:4px 0;font-size:12px}.ch-lora input[type=number]{width:62px}
.vl-grid{display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px;align-items:start}
@media (max-width:980px){.ch-studio,.vl-grid{grid-template-columns:1fr}.ch-side{position:static;max-height:none}}
@media (max-width:640px){
.ch-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.ch-views{grid-template-columns:repeat(2,minmax(0,1fr))}
.ch-studio,.vl-grid{gap:12px}
.ch-slot{grid-template-columns:76px 1fr}
.ch-pic button.small,.ch-card button.small{padding:6px 10px}
#app button.small{padding:6px 11px;min-height:32px}
#app input:not([type=checkbox]):not([type=radio]),#app select,#app textarea{font-size:16px}
#app .row>label.f,#app .row>select,#app .row>input[type=text]{flex:1 1 100%;min-width:0!important}
#app .card.pad{padding:12px}
#vl-spaces .row input{flex:1 1 100%!important;width:auto!important}
.sp-studio-overlay{position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center}
.sp-studio{background:var(--bg);width:960px;max-width:96vw;max-height:92vh;border-radius:14px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.5)}
.sp-studio-head{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-shrink:0}
.sp-studio-body{display:flex;flex:1;overflow:hidden;min-height:0}
.sp-studio-ctrl{width:250px;min-width:220px;padding:16px;border-right:1px solid var(--line);overflow-y:auto;flex-shrink:0;display:flex;flex-direction:column;gap:10px}
.sp-studio-imgs{flex:1;padding:16px;overflow-y:auto}
.sp-img-card{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--panel);margin-bottom:10px}
.sp-img-card.approved{border:2px solid var(--ok,#2a9d5c)}
.sp-img-card img{width:100%;display:block;cursor:zoom-in;max-height:280px;object-fit:cover}
.sp-img-actions{display:flex;gap:6px;padding:8px;flex-wrap:wrap;align-items:center}
.sp-corner-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px}
.sp-corner-grid .sp-img-card img{max-height:160px}
.sp-section-label{font-size:11px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.5px;margin:12px 0 6px}
.sp-status{font-size:11px;color:var(--mute);min-height:16px}
#life-feed-box img{width:96px!important;height:128px!important}
.dlg .box{max-height:96vh}
}
`;
document.head.append(css);

const call = (path, opts = {}) => api('/characters' + path, opts);
let C = null, CID = null, OPT = null, pollT = null, CH_TAB = 'gallery', LIFE_EVENTS = null;
const SLOT_ORDER = {person: null, place: null};

/* ───────── library ───────── */
window.viewCharacters = async function () {
  const my = route_id;
  clearTimeout(pollT);
  $('#app').innerHTML = `<div class="row"><h2 style="margin:0">Characters</h2><span class="mute">a library of people and places you can reuse in every short</span><span class="sp"></span>
    <button class="small" id="ch-import">Import pack</button>
    <select id="ch-kind" style="width:auto"><option value="">All</option><option value="person">People</option></select>
    <button class="primary" id="ch-new">New character</button></div><div id="ch-list"><div class="skel"></div></div>`;
  $('#ch-new').onclick = newCharacter;
  $('#ch-import').onclick = () => { const i = document.createElement('input'); i.type = 'file'; i.accept = '.zip'; i.onchange = async () => { const fd = new FormData(); fd.append('file', i.files[0]);
    const c = await act(null, () => call('/import', {method: 'POST', form: fd}), 'Imported'); if (c) location.hash = '#/character/' + c.id; }; i.click(); };
  const load = async () => {
    const rows = await call('?kind=' + $('#ch-kind').value).catch(e => { toast(e.message, {bad: true}); return []; });
    if (my !== route_id) return;
    $('#ch-list').innerHTML = rows.length ? `<div class="ch-grid">${rows.map(r => `<div class="ch-card" onclick="location.hash='#/character/${r.id}'">
      <div class="ph">${r.thumb ? `<img src="${esc(r.thumb)}" loading="lazy">` : 'no picture yet'}</div>
      <div class="meta"><b>${esc(r.name)}</b><div class="mute small">${esc(r.kind)} · ${esc(r.style)} · v${r.version}</div>${badge(r.status === 'ready' ? 'done' : 'queued', r.status === 'ready' ? 'ready' : 'draft')}</div></div>`).join('')}</div>`
      : `<div class="big-empty"><h2>Make your first character</h2><p class="mute" style="max-width:560px;margin:0 auto 16px">Describe a person or a place in a sentence. The app fills in every detail, draws candidates, and you approve the one that becomes the character. Then use it in any short.</p><button class="primary" onclick="document.getElementById('ch-new').click()">New character</button></div>`;
  };
  $('#ch-kind').onchange = load;
  load();
};

const dl = (id, list) => `<datalist id="${id}">${list.map(x => `<option value="${esc(x)}">`).join('')}</datalist>`;
const choiceInput = (kind, key, value = '', extra = '') => `<input list="dl-${kind}-${key}" data-declared="${key}" value="${esc(value)}" placeholder="pick or type your own" ${extra}>${dl(`dl-${kind}-${key}`, (OPT.choices[kind] || {})[key] || [])}`;
const declaredFields = (kind, d = {}, dis = '') => OPT.declared[kind].map(x => x.key === 'gender'
  ? `<label class="f mt-s">${esc(x.label)}<select data-declared="gender" ${dis}><option value="">choose…</option><option value="male" ${d.gender === 'male' ? 'selected' : ''}>male</option><option value="female" ${d.gender === 'female' ? 'selected' : ''}>female</option></select></label>`
  : `<label class="f mt-s">${esc(kind === 'place' && x.key === 'ethnicity' ? 'region or culture of the place' : x.label)}${choiceInput(kind, x.key, d[x.key] || '', dis)}</label>`).join('');
const readDeclared = root => Object.fromEntries([...root.querySelectorAll('[data-declared]')].map(e => [e.dataset.declared, e.value.trim()]).filter(([, v]) => v));

async function newCharacter() {
  OPT = OPT || await call('/options');
  const html = `<label class="f">Name<input id="n-name" placeholder="Raju, the night-shift courier"></label>
    <label class="f mt-s">What is it<select id="n-kind"><option value="person">A person</option></select></label>
    <div id="n-declared"><div class="small mute mt-s">You decide these; the app never invents them. Pick from the list or type your own.</div>${declaredFields('person')}</div>
    <label class="f mt-s">The idea, in a sentence or two<textarea id="n-idea" placeholder="A confident delivery rider who films reels between orders, always in a yellow jacket"></textarea></label>
    <label class="f mt-s">Look<select id="n-style">${Object.entries(OPT.styles).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join('')}</select></label>
    <p class="mute small">The look (and its LoRAs) is locked once you approve a picture: the same description in another look draws a different person.</p>`;
  const layer = dialog({title: 'New character', html, buttons: [{label: 'Cancel', value: null}, {label: 'Create', primary: true,
    collect: l => ({name: l.querySelector('#n-name').value, kind: l.querySelector('#n-kind').value, idea: l.querySelector('#n-idea').value, style: l.querySelector('#n-style').value, declared: readDeclared(l.querySelector('#n-declared'))}),
    validate: x => x.idea.trim().length < 5 ? 'Write the idea in a sentence.' : OPT.declared[x.kind].find(d => !x.declared[d.key]) ? 'Say the ' + OPT.declared[x.kind].find(d => !x.declared[d.key]).label + '.' : ''}]});
  setTimeout(() => { const k = document.querySelector('#n-kind'); if (k) k.onchange = () => { document.querySelector('#n-declared').innerHTML = '<div class="small mute mt-s">You decide these; the app never invents them. Pick from the list or type your own.</div>' + declaredFields(k.value); }; }, 30);
  const v = await layer;
  if (!v) return;
  const st = OPT.styles[v.style];
  const c = await act(null, () => call('', {method: 'POST', json: {name: v.name, kind: v.kind, idea: v.idea, declared: v.declared, render: {style: v.style, model: OPT.default_render.model, loras: st.loras}}}));
  if (c) { sessionStorage.setItem('ch-suggest-' + c.id, '1'); location.hash = '#/character/' + c.id; }
}

/* ───────── studio ───────── */
window.viewCharacter = async function (id) {
  CID = id; clearTimeout(pollT); LIFE_EVENTS = null; LIFE_GOALS = null; LIFE_MEMORIES = null; CH_TAB = 'gallery';
  OPT = OPT || await call('/options').catch(() => null);
  const my = route_id;
  const load = async (force) => {
    if (my !== route_id) return;
    try { C = await call('/' + id); } catch (e) { $('#app').innerHTML = `<div class="errbox">${esc(e.message)}</div><a href="#/characters">Back</a>`; return; }
    if (my !== route_id) return;
    if (force || !document.querySelector('.ch-studio') || !editing()) render();
    else refreshCenter();
    if (C.job && C.job.state === 'running') pollT = setTimeout(() => load(false), 3000);
  };
  window._chLoad = load;
  await loadLists();
  try { window._chVoices = Object.entries((await api('/shorts/options')).voices || {}); } catch { window._chVoices = []; }
  await load(true);
  if (sessionStorage.getItem('ch-suggest-' + id)) { sessionStorage.removeItem('ch-suggest-' + id); await suggest(null); if (C && !C.gaps.length) await post(null, '/generate', {views: ['portrait'], n: 4}, 'Drawing four portraits: pick one as the canon'); }
};
const editing = () => ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement && document.activeElement.tagName);
const post = (btn, path, json, ok) => act(btn, async () => { await flushSlots(); await call('/' + CID + path, {method: 'POST', json: json || {}}); await window._chLoad(true); return true; }, ok);
let PENDING = Promise.resolve();
const flushSlots = async () => { document.querySelectorAll('[data-slot]').forEach(e => { clearTimeout(e._t); if ((C.slots[e.dataset.slot] || '') !== e.value) { const slots = {...C.slots}; slots[e.dataset.slot] = e.value; PENDING = patch({slots}); } }); await PENDING; };
const patchAvatar = async (json) => { await act(null, async () => { C = await call('/' + CID + '/avatar', {method: 'PATCH', json}); render(); return true; }); };
const patch = async (json) => { await act(null, async () => { C = await call('/' + CID, {method: 'PATCH', json}); render(); return true; }); };
const hdur = s => (window.hd ? hd(s) : Math.round(s) + 's');

function jobBox() {
  const j = C.job || {};
  if (j.state === 'running') return `<div class="jobbox"><div class="row"><span class="spin"></span><b>${esc(j.label || 'working')}</b><span class="sp"></span><span class="mute small">${hdur(j.elapsed_s || 0)}${j.eta_s ? ' · about ' + hdur(j.eta_s) + ' left' : ''}</span>
    <button class="small bad" onclick="chStop()">Stop</button></div>${bar(j.total ? Math.round(100 * j.done / j.total) : 0)}</div>`;
  if (j.state === 'error') return `<div class="errbox">The last step stopped: ${esc(j.error)}</div>`;
  return '';
}
window.chStop = async () => { await call('/' + CID + '/cancel', {method: 'POST'}); await window._chLoad(true); };

function render() {
  const busy = C.job && C.job.state === 'running';
  const studioHtml = CH_TAB === 'life'
    ? lifeView(busy)
    : `<div class="ch-studio"><div class="ch-side card pad">${sideView(busy)}</div><div id="ch-center">${galleryView(busy)}</div></div>`;
  $('#app').innerHTML = `
    <div class="row"><a href="#/characters">← Characters</a><h2 style="margin:0 0 0 8px">${esc(C.name)}</h2>${badge(C.status === 'ready' ? 'done' : 'queued', C.status)}<span class="mute small">v${C.version} · ${esc(C.kind)}</span><span class="sp"></span>
      <button class="small" onclick="chRename()">Rename</button><a class="small" href="/api/characters/${C.id}/pack" download><button class="small">Export pack</button></a><button class="small" onclick="chDup(this)">Duplicate</button><button class="small bad" onclick="chDelete()">Delete</button></div>
    <div id="ch-job">${jobBox()}</div>
    ${tabBar()}
    ${studioHtml}`;
  document.getElementById('tab-gallery').onclick = () => { CH_TAB = 'gallery'; render(); };
  document.getElementById('tab-life').onclick    = () => { CH_TAB = 'life'; LIFE_EVENTS = null; LIFE_GOALS = null; LIFE_MEMORIES = null; LIFE_ASPIRATIONS = null; render(); };
  wire();
}
function refreshCenter() {
  $('#ch-job').innerHTML = jobBox();
  if (CH_TAB === 'gallery') {
    const c = document.getElementById('ch-center');
    if (c) { c.innerHTML = galleryView(C.job && C.job.state === 'running'); wireCenter(); }
  }
}

function avatarBlock(dis) {
  const a = C.avatar || {voice: {}, ready: {}}, r = a.ready || {}, vs = window._chVoices || [];
  const cur = a.voice && a.voice.engine ? `${a.voice.engine}|${a.voice.voice}` : '';
  const badge2 = r.state === 'pass' ? badge('good', 'ready to talk') : r.state === 'weak' ? badge('warn', 'weak: see the notes') : badge('queued', 'not tested');
  return `<h3>Talking avatar</h3>
    <label class="f"><select id="av-voice" ${dis}><option value="">the app's default voice</option>${vs.flatMap(([eng, e]) => Object.entries(e.voices).map(([v, g]) => `<option value="${esc(eng)}|${esc(v)}" ${cur === eng + '|' + v ? 'selected' : ''}>${esc(e.label)}: ${esc(v)} (${esc(g)})</option>`)).join('')}</select></label>
    <div class="row small mt-s">${badge2}${r.stale ? ' ' + badge('warn', 'character changed since') : ''}<span class="sp"></span><button class="small" id="av-test" ${dis} ${C.canon && C.canon.portrait ? '' : 'disabled'} title="Makes a 3-second talking clip of the approved portrait with this voice and checks the mouth, hands and likeness. Takes several minutes.">Run the 3 s test</button></div>
    ${r.state ? `<div class="mute small">mouth ${r.mouth}/10 · hands ${r.hands}/10 · same person ${r.identity}/10${(r.notes || []).length ? ' · ' + esc(r.notes.join('; ')) : ''}</div>` : '<div class="mute small">The test needs an approved portrait and the talking model on the gateway.</div>'}
    ${a.clip ? `<video src="${esc(a.clip)}" controls muted style="width:100%;max-height:260px;margin-top:6px"></video>` : ''}`;
}

function stylingBlock(dis) {
  const st = (OPT && OPT.styling) || [], glam = C.styling === 'glamour', gender = ((C.declared || {}).gender || '').toLowerCase();
  const outfits = ((OPT && OPT.outfits) || []).filter(o => (!o.styling || (glam && !C.glamour_problem)) && (!o.gender || !gender || o.gender === gender));
  return `<h3>Styling</h3>
    <label class="f"><select id="ch-styling" ${dis} ${C.locked ? 'disabled' : ''}>${st.map(x => `<option value="${esc(x.id)}" ${(C.styling || '') === x.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select></label>
    ${C.styling === 'glamour' && C.glamour_problem ? `<div class="warnbox small">${esc(C.glamour_problem)}. The glamorous wording is not used until this is fixed.</div>` : ''}
    <div class="mute small">Glamorous is for adult, invented characters: fitted, softly revealing and tasteful, always clothed. It needs a declared age of 21 or more.</div>
    <label class="f mt-s">Quick outfit<select id="ch-outfit" ${dis}><option value="">choose to fill top, bottom, shoes and expression</option>${outfits.map(o => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join('')}</select></label>
    <div class="mute small">The first pictures show a clean person only. Ornaments (the accessories line) are added afterwards with an accessory edit, so the face comes out right.</div>`;
}

function sideView(busy) {
  const hints = Object.fromEntries((OPT ? OPT.slots[C.kind] : []).map(x => [x.key, x.hint]));
  const decl = new Set((C.declared_keys || []).map(x => x.key));
  const keys = Object.keys(hints).filter(k => !decl.has(k));
  const r = C.render, loras = (OPT && OPT.loras[r.model]) || [];
  const dis = busy ? 'disabled' : '';
  return `<h3 style="margin-top:0">Idea</h3>
    <textarea id="ch-idea" style="min-height:64px" ${dis}>${esc(C.idea)}</textarea>
    <h3>Decided by you</h3><div class="mute small">Never invented or changed by the model.</div>${declaredFields(C.kind, C.declared || {}, dis + (C.locked ? ' disabled' : ''))}
    <div class="row mt-s"><button class="small primary" id="ch-suggest" ${dis}>Fill the empty details</button><button class="small" id="ch-suggest-all" ${dis} title="Write every detail again; the five above stay">Write all again</button></div>
    ${C.kind === 'person' ? `<div class="row mt-s small">${C.photo ? `<img src="${esc(C.photo)}" style="width:44px;border-radius:6px"> started from a picture (${esc(C.rights.basis)})` : ''}<button class="small" id="ch-photo" ${dis}>${C.photo ? 'Change the picture' : 'Start from a picture'}</button></div>` : ''}
    ${C.kind === 'person' ? stylingBlock(dis) : ''}
    ${C.kind === 'person' ? avatarBlock(dis) : ''}
    ${C.kind === 'person' ? `<h3>Read a detail from a picture</h3><div class="row small" style="gap:6px"><select id="rd-aspect" ${dis}><option value="hair">hair (colour, streaks, style)</option><option value="outfit">outfit</option><option value="accessories">accessories</option><option value="face">face and skin</option><option value="expression">expression</option></select><button class="small" id="rd-pick" ${dis}>Choose a picture</button></div><div class="mute small">The model looks at the picture and writes the words into the matching detail; you can change them. The picture itself is not kept and is not given to the image model.</div>` : ''}
    <h3>Details</h3><div class="mute small">${C.gaps.length ? 'Fill these in: ' + C.gaps.map(esc).join(', ') + '. An image model invents what is not written.' : 'Every detail is written.'}</div>
    ${keys.map(k => `<label class="ch-slot ${C.gaps.includes(k) ? 'gap' : ''}" title="${esc(hints[k])}"><span>${esc(k)}</span><input data-slot="${k}" list="dl-slot-${k}" value="${esc(C.slots[k] || '')}" placeholder="pick or type" ${dis}>${dl('dl-slot-' + k, (OPT.choices[C.kind] || {})[k] || [])}</label>`).join('')}
    <label class="f mt-s">Personality (mood the face carries)<input id="ch-pers" value="${esc(C.personality)}" ${dis}></label>
    <label class="f mt-s">Tags (comma separated)<input id="ch-tags" value="${esc(C.tags.join(', '))}" ${dis}></label>
    <label class="f mt-s">Notes<textarea id="ch-notes" style="min-height:44px" ${dis}>${esc(C.notes)}</textarea></label>
    <h3>Look ${C.locked ? '<span class="mute small">locked</span>' : ''}</h3>
    ${C.locked ? '<div class="hint small">The look is locked because a canon picture is approved. To try another look, duplicate the character.</div>' : ''}
    <label class="f">Style<select id="ch-style" ${C.locked || busy ? 'disabled' : ''}>${OPT ? Object.entries(OPT.styles).map(([k, v]) => `<option value="${k}" ${r.style === k ? 'selected' : ''}>${esc(v.label)}</option>`).join('') : ''}</select></label>
    <label class="f mt-s">Image model<select id="ch-model" ${C.locked || busy ? 'disabled' : ''}>${OPT ? Object.entries(OPT.models).map(([k, v]) => `<option value="${k}" ${r.model === k ? 'selected' : ''}>${esc(v.label)}${v.licence === 'restricted' ? ' (licence restricted)' : ''}</option>`).join('') : ''}</select></label>
    <div class="mt-s small"><b>LoRAs</b> (up to four)</div>
    ${r.loras.map((l, i) => `<div class="ch-lora"><span style="flex:1">${esc(l.name)}</span><input type="number" step="0.05" min="-2" max="2" value="${l.strength}" data-lora-s="${i}" ${C.locked || busy ? 'disabled' : ''}>${C.locked ? '' : `<button class="small" data-lora-x="${i}">×</button>`}</div>`).join('') || '<div class="mute small">none</div>'}
    ${C.locked ? '' : `<select id="ch-lora-add"><option value="">Add a LoRA…</option>${loras.filter(l => !r.loras.some(x => x.name === l.name)).map(l => `<option value="${esc(l.name)}" title="${esc(l.description)}">${esc(l.name)}${l.trigger ? ' (trigger ' + esc(l.trigger) + ')' : ''}${l.default ? ' · on by default' : ''}</option>`).join('')}</select>`}
    ${loras.length ? '' : '<div class="mute small mt-s">The gateway lists no LoRAs for this model.</div>'}`;
}

function tabBar() {
  return `<div class="row" style="gap:6px;margin-bottom:14px;border-bottom:1px solid var(--line);padding-bottom:10px">
    <button id="tab-gallery" class="${CH_TAB==='gallery'?'primary':'small'}">Gallery &amp; Edits</button>
    <button id="tab-life" class="${CH_TAB==='life'?'primary':'small'}">Virtual Life</button>
  </div>`;
}

function galleryView(busy) {
  const dis = busy ? 'disabled' : '';
  const draw = C.views.filter(v => OPT && OPT.views[v].how === 'draw'), sheet = C.views.filter(v => OPT && OPT.views[v].how === 'edit');
  const pics = v => (C.gallery[v] || []).slice().reverse();
  const card = p => `<div class="ch-pic ${C.canon[p.view] === p.id ? 'canon' : ''}">${p.url ? `<img src="${esc(p.url)}" loading="lazy" onclick="chZoom('${esc(p.url)}')">` : `<div class="ph">${p.status === 'failed' ? 'failed<br>' + esc(p.error.slice(0, 80)) : 'drawing…'}</div>`}
    <div class="mute">#${p.attempt} · seed ${p.seed ?? '-'}${p.seconds_taken ? ' · ' + Math.round(p.seconds_taken) + 's' : ''}${p.current ? '' : ' · older'}</div>
    ${p.status === 'failed' ? `<div class="row" style="margin-top:4px;gap:4px"><button class="small" data-retry="${p.id}" ${dis}>Retry</button><button class="small bad" data-del="${p.id}" ${dis}>Delete</button></div>` : ''}
    ${p.url && (p.how === 'draw' || p.how === 'edit') ? `<div class="row" style="margin-top:4px;gap:4px">${C.canon[p.view] === p.id ? '<b>Canon ✓</b>' : `${p.view === 'portrait' || p.view === 'body' || p.view === 'place' ? `<button class="small primary" data-canon="${p.id}" ${dis}>Use as canon</button>` : (p.approved ? '<b>Kept ✓</b>' : `<button class="small" data-canon="${p.id}" ${dis}>Keep</button>`)} <button class="small bad" data-del="${p.id}" ${dis}>Delete</button>`}</div>` : ''}</div>`;
  const bodyRefPics = () => Object.values(C.gallery).flat().filter(p => p.url && p.status === 'done');
  const bodyRefSel = () => { const all = bodyRefPics(); if (!all.length) return ''; return `<label class="small" style="display:flex;align-items:center;gap:4px">Reference<select id="body-ref" style="width:auto"><option value="">Auto (canon portrait)</option>${all.map(p => `<option value="${p.id}">${esc(picLabel(p))}</option>`).join('')}</select></label>`; };
  const section = (v, n) => `<div class="card pad mt"><div class="row"><h3 style="margin:0">${esc(OPT.views[v].label)}</h3>${C.canon[v] ? badge('done', 'canon') : ''}<span class="sp"></span>
      ${v === 'body' && C.kind === 'person' ? bodyRefSel() : ''}
      <select data-n="${v}" style="width:auto">${[1, 2, 4].map(k => `<option value="${k}" ${k === n ? 'selected' : ''}>${k} new</option>`).join('')}</select>
      <button class="small" data-editprompt="${v}" ${dis}>Edit prompt</button><button class="small primary" data-draw="${v}" ${dis}>Draw</button></div>
      <div class="ch-views mt-s">${pics(v).map(card).join('') || '<div class="mute small">nothing drawn yet</div>'}</div></div>`;
  const haveCanon = C.kind === 'person' && C.canon.portrait && C.canon.body;
  return `<div class="mute small" title="The text the image model gets for the subject">${esc(C.identity || 'Write the details on the left.')}</div>
    ${draw.map(v => section(v, 2)).join('')}
    ${C.kind === 'person' ? `<div class="card pad mt"><div class="row"><h3 style="margin:0">Character sheet</h3><span class="mute small">three-quarter, side and back views and six expressions, each made from the canon</span><span class="sp"></span>
      <button class="small primary" id="ch-sheet" ${dis} ${haveCanon ? '' : 'disabled title="Approve a portrait and a full-body picture first"'}>Make the sheet</button></div>
      <div class="ch-views mt-s">${sheet.flatMap(v => pics(v).slice(0, 1).map(card)).join('') || '<div class="mute small">' + (haveCanon ? 'not made yet' : 'Approve a portrait and a full-body picture first.') + '</div>'}</div></div>` : ''}
    ${editCard(busy)}${refBlendCard(busy)}${inPlaceCard(busy)}${editsGallery(busy)}${matrixCard(busy)}`;
}

window.chZoom = url => dialog({title: 'Picture', html: `<img src="${esc(url)}" style="max-width:100%;max-height:72vh;display:block;margin:auto;border-radius:8px">`, buttons: [{label: 'Close', value: true, primary: true}]});
window.chRename = async () => { const t = await textDlg('Rename', 'Name', C.name); if (t) await patch({name: t}); };
window.chDup = btn => act(btn, async () => { const c = await call('/' + CID + '/duplicate', {method: 'POST'}); location.hash = '#/character/' + c.id; return true; }, 'Copied');
window.chDelete = async () => { if (await confirmDlg('Delete this character', 'Its pictures are deleted too. Shorts that used it keep their own pictures.', 'Delete', true)) { await act(null, () => call('/' + CID, {method: 'DELETE'})); location.hash = '#/characters'; } };

async function suggest(btn, keep = true) {
  const idea = ($('#ch-idea') || {}).value || C.idea;
  return act(btn, async () => { C = await call('/' + CID + '/suggest', {method: 'POST', json: {idea, keep}}); render(); return true; }, 'Details written: check them, then draw');
}

function wire() {
  const on = (sel, fn) => { const e = document.querySelector(sel); if (e) e.onclick = () => fn(e); };
  on('#ch-suggest', b => suggest(b, true)); on('#ch-suggest-all', b => suggest(b, false));
  document.querySelectorAll('#ch-side [data-declared], .ch-side [data-declared]').forEach(e => e.onchange = () => patch({declared: readDeclared(document.querySelector('.ch-side'))}));
  on('#ch-photo', startFromPicture);
  const val = (sel, key, conv = x => x) => { const e = document.querySelector(sel); if (e) e.onchange = () => patch({[key]: conv(e.value)}); };
  val('#ch-idea', 'idea'); val('#ch-pers', 'personality'); val('#ch-notes', 'notes'); val('#ch-tags', 'tags', v => v.split(','));
  const rdp = $('#rd-pick'); if (rdp) rdp.onclick = () => { const f = document.createElement('input'); f.type = 'file'; f.accept = 'image/jpeg,image/png,image/webp'; f.onchange = async () => { if (!f.files[0]) return; const fd = new FormData(); fd.append('file', f.files[0]); fd.append('aspect', $('#rd-aspect').value); await act(null, async () => { C = await call('/' + CID + '/read-detail', {method: 'POST', form: fd}); render(); return true; }, 'Read: check the words in the details'); }; f.click(); };
  const avv = $('#av-voice'); if (avv) avv.onchange = () => { const [engine, voice] = avv.value.split('|'); patchAvatar(avv.value ? {voice: {engine, voice}} : {voice: {}}); };
  const avt = $('#av-test'); if (avt) avt.onclick = () => post(avt, '/avatar/test', {}, 'The test clip is being made');
  const sty = $('#ch-styling'); if (sty) sty.onchange = () => patch({styling: sty.value});
  const out = $('#ch-outfit'); if (out) out.onchange = () => { const o = ((OPT && OPT.outfits) || []).find(x => x.id === out.value); if (!o) return; const slots = {...C.slots}; ['top', 'bottom', 'footwear', 'accessories', 'expression'].forEach(k => { slots[k] = o[k]; }); if (o.styling && C.styling !== 'glamour') patch({slots, styling: 'glamour'}); else patch({slots}); };
  document.querySelectorAll('[data-slot]').forEach(e => {
    const save = () => { clearTimeout(e._t); const v = e.value; if ((C.slots[e.dataset.slot] || '') === v) return Promise.resolve(); const slots = {...C.slots}; slots[e.dataset.slot] = v; PENDING = patch({slots}); return PENDING; };
    const quiet = () => { const v = e.value; if ((C.slots[e.dataset.slot] || '') === v) return; PENDING = call('/' + CID, {method: 'PATCH', json: {slots: {...C.slots, [e.dataset.slot]: v}}}).then(r => { C = r; }).catch(() => {}); };   // while typing: save without redrawing the panel
    e.onchange = save; e.oninput = () => { clearTimeout(e._t); e._t = setTimeout(quiet, 700); };
  });
  const renderPatch = async (change) => { await act(null, async () => { C = await call('/' + CID, {method: 'PATCH', json: {render: {...C.render, ...change}}}); render(); return true; }); render(); };
  const st = document.querySelector('#ch-style'); if (st) st.onchange = () => renderPatch({style: st.value, loras: OPT.styles[st.value].loras});
  const md = document.querySelector('#ch-model'); if (md) md.onchange = () => renderPatch({model: md.value, loras: []});
  document.querySelectorAll('[data-lora-s]').forEach(e => e.onchange = () => renderPatch({loras: C.render.loras.map((l, i) => i === +e.dataset.loraS ? {...l, strength: +e.value} : l)}));
  document.querySelectorAll('[data-lora-x]').forEach(e => e.onclick = () => renderPatch({loras: C.render.loras.filter((_, i) => i !== +e.dataset.loraX)}));
  const add = document.querySelector('#ch-lora-add');
  if (add) add.onchange = () => { if (!add.value) return; const l = OPT.loras[C.render.model].find(x => x.name === add.value); renderPatch({loras: [...C.render.loras, {name: l.name, strength: Math.min(l.strength, 0.8)}].slice(0, 4)}); };
  wireCenter();
}
function drawArgs(v) {
  const refEl = v === 'body' ? document.getElementById('body-ref') : null;
  const nEl = document.querySelector(`[data-n="${v}"]`);
  return {views: [v], n: nEl ? +nEl.value : 1, body_ref: refEl ? refEl.value : ''};
}
function wireCenter() {
  document.querySelectorAll('[data-draw]').forEach(b => b.onclick = () => { try { post(b, '/generate', drawArgs(b.dataset.draw), 'Drawing started'); } catch(e) { toast(e.message, {bad: true}); } });
  document.querySelectorAll('[data-editprompt]').forEach(b => b.onclick = async () => {
    const v = b.dataset.editprompt;
    b.disabled = true; b.textContent = '…';
    let pr; try { pr = await call('/' + CID + '/generate/preview', {method: 'POST', json: drawArgs(v)}); } catch(e) { toast(e.message, {bad: true}); } finally { b.disabled = false; b.textContent = 'Edit prompt'; }
    if (!pr) return;
    const result = await dialog({
      title: `Prompt for ${OPT.views[v].label}`,
      html: `<div class="mute small mb-s">${esc(pr.model)} · ${pr.how} mode. Edit below, then click Draw.</div>
             <textarea id="ep-txt" style="min-height:160px;width:100%;box-sizing:border-box;font-size:13px">${esc(pr.prompt)}</textarea>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Draw with this prompt', primary: true, collect: l => l.querySelector('#ep-txt').value.trim(), validate: v => v ? null : 'Prompt is empty'}]
    });
    if (!result) return;
    const drawBtn = document.querySelector(`[data-draw="${v}"]`);
    post(drawBtn, '/generate', {...drawArgs(v), custom_prompt: result}, 'Drawing started');
  });
  document.querySelectorAll('[data-retry]').forEach(b => b.onclick = async () => {
    let note = '';
    if (b.dataset.ask) {                      // a finished picture: say what to fix this time (can stay empty)
      note = await dialog({title: 'Retry with the same inputs', html: `<label class="f">What should be different this time?<textarea id="td" style="min-height:110px" placeholder="Leave empty to just draw again"></textarea></label>
        <div class="hint small mt-s">Added to the end of the same prompt; the same pictures and LoRAs are used. Say what you want to see, not what you do not want.<br>
        <b>Eyes look wrong?</b> <i>${esc(RETRY_EYES)}</i> <a href="#" onclick="event.preventDefault();document.getElementById('td').value=${esc(JSON.stringify(RETRY_EYES))}">Use this</a></div>`,
        buttons: [{label: 'Cancel', value: null}, {label: 'Retry', primary: true, collect: l => l.querySelector('#td').value}]});
      if (note === null) return;
    }
    act(b, async () => { await call('/item/' + b.dataset.retry + '/retry', {method: 'POST', json: {note}}); await window._chLoad(true); return true; }, 'Retrying…');
  });
  document.querySelectorAll('[data-canon]').forEach(b => b.onclick = () => act(b, async () => { await call('/item/' + b.dataset.canon + '/canon', {method: 'POST'}); await window._chLoad(true); return true; }, 'Saved'));
  const sh = document.querySelector('#ch-sheet'); if (sh) sh.onclick = () => post(sh, '/sheet', {}, 'Sheet started');
  wireEdit();
}

/* ───────── edits, try-on, places, looks, matrix (C2, C3) ───────── */
let EB = '', EX = [], CMP = [], WARD = null, ED_OPEN = false, RB_FILE = null;
const RETRY_EYES = 'Both eyes sharp, natural and the same size, looking in the same direction as image 1. Clear round irises, natural eyelids, no blur or smudging around the eyes.';
const RB = {part: 'face_into', lora: true, expr: false, sharp: false, pure: false};   // the reference-photo card's choices; the card is redrawn often and must not forget them
const allPics = () => Object.values(C.gallery).flat().filter(p => p.url);
const picLabel = p => `${p.view === 'edit' ? (p.op || 'edit') : p.view} #${p.attempt}${C.canon[p.view] === p.id ? ' (canon)' : ''}${p.depth ? ' · chain ' + p.depth : ''}`;
const canonBody = () => C.canon.body || C.canon.portrait || (allPics()[0] || {}).id || '';
const checkBadge = p => p.check ? `<span class="badge ${p.check.ok ? 'b-done' : 'b-failed'}" title="${esc((p.check.differences || []).join('; ') || 'matches the canon')}">same person ${p.check.score}/10</span>` : '';

function editCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait) return '';
  if (!EB || !allPics().some(p => p.id === EB)) EB = canonBody();
  const dis = busy ? 'disabled' : '';
  const pics = allPics();
  const base = pics.find(p => p.id === EB);
  const chain = base && base.depth >= 3 ? `<div class="warnbox small mt-s">This picture is ${base.depth} edits away from the canon; faces drift along a chain. <button class="small" id="e-rebase">Start from the canon body instead</button></div>` : '';
  return `<div class="card pad mt" id="ch-edit"><div class="row"><h3 style="margin:0">Edit with Qwen</h3><span class="mute small">change one thing, keep the person</span></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
      <label class="f" style="min-width:200px">Start from<select id="e-base">${pics.map(p => `<option value="${p.id}" ${p.id === EB ? 'selected' : ''}>${esc(picLabel(p))}</option>`).join('')}</select></label>
      ${base ? `<img src="${esc(base.url)}" style="height:90px;border-radius:6px">` : ''}</div>${chain}
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap">
      <label class="f">What<select id="e-preset">${OPT.presets.map(k => `<option value="${k}">${esc(k.replace('_', ' '))}</option>`).join('')}</select></label>
      <label class="f" style="flex:1;min-width:220px">Change it to<input id="e-value" placeholder="e.g. a dark green kurta with beige trousers"></label>
      <label class="f">Recipes<select id="e-recipe"><option value="">—</option>${C.recipes.map((r, i) => `<option value="${i}">${esc(r.name)}</option>`).join('')}</select></label></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
      <label class="f">Dress in clothes from a picture<select id="e-garment"><option value="">— none —</option>${(WARD || []).map(g => `<option value="${g.id}">${esc(g.name)}${g.worn ? (g.flat ? ' (flat lay ready)' : ' (worn by a model)') : ''}</option>`).join('')}</select></label>
      <label class="f">Which part<select id="e-scope">${Object.entries(OPT.scopes).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
      <button class="small" id="e-wardrobe">Wardrobe…</button></div>
    <details class="mt-s" ${ED_OPEN ? 'open' : ''}><summary class="small">Extra reference pictures and the full prompt (power)</summary>
      <div class="small mt-s" id="e-ex-list">Extra pictures (up to two): ${pics.filter(p => p.id !== EB).slice(-12).map(p => `<label style="margin-right:8px"><input type="checkbox" data-ex="${p.id}" ${EX.includes(p.id) ? 'checked' : ''}> ${esc(picLabel(p))}</label>`).join('') || 'none yet'}</div>
      <div class="small mt-s">Or upload a new reference: <input type="file" id="e-ref-file" accept="image/jpeg,image/png,image/webp" style="font-size:12px"></div>
      <label class="f mt-s">Your own full instruction (replaces the built one)<textarea id="e-prompt" style="min-height:60px"></textarea></label>
      <div id="e-preview" class="hint small mt-s" hidden></div></details>
    <div class="row mt-s"><select id="e-n" style="width:auto">${[1, 2, 4].map(k => `<option value="${k}">${k} picture${k > 1 ? 's' : ''}</option>`).join('')}</select>
      <button class="small" id="e-prev" ${dis}>Show the prompt</button><button class="small primary" id="e-run" ${dis}>Make the edit</button><button class="small" id="e-save-recipe">Save as recipe</button></div></div>`;
}


const PARTS = [
  {id: 'face_into',   label: 'My face into reference photo',   hint: 'character\'s face placed into the reference scene · clothes, body, background all from the reference'},
  {id: 'face',        label: 'Reference face into my photo',   hint: 'reference face placed into the source picture · clothes, hair, background stay from source'},
  {id: 'outfit',      label: 'Outfit from reference',          hint: 'outfit from reference · face, hair, skin tone, pose stay from source'},
  {id: 'background',  label: 'Background from reference',      hint: 'background from reference · person, clothes, pose stay from source'},
];

function refBlendCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait) return '';
  const dis = busy ? 'disabled' : '';
  const pics = allPics();
  return `<div class="card pad mt" id="ch-refblend">
    <div class="row"><h3 style="margin:0">Take from a reference photo</h3><span class="mute small">pick what to take FROM the uploaded photo; everything else stays FROM the source picture above</span></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
      <label class="f" style="min-width:200px">Source picture<select id="rb-base">${pics.map(p => `<option value="${p.id}" ${p.id === EB ? 'selected' : ''}>${esc(picLabel(p))}</option>`).join('')}</select></label>
      ${pics.find(p => p.id === EB) ? `<img src="${esc(pics.find(p => p.id === EB).url)}" style="height:70px;border-radius:6px">` : ''}
    </div>
    <div class="mt-s small"><b>What to take from the reference:</b>
      <div class="row mt-s" style="gap:8px;flex-wrap:wrap">
        ${PARTS.map(pt => `<label style="display:flex;align-items:center;gap:4px"><input type="radio" name="rb-part" value="${pt.id}" ${pt.id === RB.part ? 'checked' : ''}> <span><b>${pt.label}</b> <span class="mute">${pt.hint}</span></span></label>`).join('<br>')}
      </div>
    </div>
    <div class="row mt-s" style="gap:12px;align-items:center;flex-wrap:wrap">
      <label class="small" style="display:flex;align-items:center;gap:6px">Reference photo <input type="file" id="rb-file" accept="image/jpeg,image/png,image/webp" style="font-size:12px"></label>
      <label class="small" style="display:flex;align-items:center;gap:6px" title="Uses the bfs-head-swap LoRA for face swaps; uncheck to use prompt only"><input type="checkbox" id="rb-lora" ${RB.lora ? 'checked' : ''}> Head-swap LoRA</label>
      <label class="small" style="display:flex;align-items:center;gap:6px" title="Use when the reference has an open mouth or wide eyes (bfs-head-swap-expression)"><input type="checkbox" id="rb-expr" ${RB.expr ? 'checked' : ''}> Expression</label>
      <label class="small" style="display:flex;align-items:center;gap:6px" title="Adds the detail-fix LoRA for sharper output (qwen2.1-detail-fix-2.0)"><input type="checkbox" id="rb-sharp" ${RB.sharp ? 'checked' : ''}> Sharper</label>
      <label class="small" style="display:flex;align-items:center;gap:6px" title="PureLens Realism LoRA — more photographic, less illustrated look (purelens-realism)"><input type="checkbox" id="rb-pure" ${RB.pure ? 'checked' : ''}> PureLens</label>
    </div>
    <div class="hint small mt-s" id="rb-sum"></div>
    <div class="row mt-s"><button class="small primary" id="rb-run" ${dis}>Apply</button></div></div>`;
}

function inPlaceCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait || !C.canon.body) return '';
  const dis = busy ? 'disabled' : '';
  return `<div class="card pad mt"><div class="row"><h3 style="margin:0">Put the character in a place</h3><span class="mute small">describe the setting; optionally upload a reference image</span></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
      <label class="f" style="flex:2;min-width:220px">Describe the place<input id="pl-text" placeholder="a sun-lit café in Mumbai, wooden tables, warm morning light" ${dis}></label>
      <label class="f" style="flex:1;min-width:180px">What is the person doing<input id="pl-action" placeholder="sipping chai, looking out the window" ${dis}></label>
    </div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:center">
      <label class="small" style="display:flex;align-items:center;gap:6px">Reference image (optional)<input type="file" id="pl-img" accept="image/jpeg,image/png,image/webp" ${dis}></label>
      <span class="mute small">Leave empty to use text only</span>
      <span class="sp"></span>
      <button class="small primary" id="pl-run" ${dis}>Place them</button>
    </div></div>`;
}

let LIFE_GOALS = null, LIFE_MEMORIES = null, LIFE_ASPIRATIONS = null;

function lifeView(busy) {
  const dis = busy ? 'disabled' : '';
  const prof = C.profile || {};
  const interests = prof.interests || {};
  const spaces = (prof.spaces || []);

  // ── profile panel ──
  const spacesHtml = spaces.map((sp, i) => {
    const hasRef = sp.ref_image;
    const refUrl = hasRef ? `/api/characters/file/${CID}/${sp.ref_image}` : '';
    return `
    <div class="card pad mt-s" style="padding:8px;background:var(--bg2,#f8f8f8);display:flex;align-items:center;gap:10px" data-sp-card="${i}">
      ${hasRef ? `<img src="${esc(refUrl)}" style="width:56px;height:40px;object-fit:cover;border-radius:6px;border:2px solid var(--ok);flex-shrink:0">` : '<div style="width:56px;height:40px;border-radius:6px;border:2px dashed var(--line);display:flex;align-items:center;justify-content:center;color:var(--mute);font-size:10px;flex-shrink:0">no ref</div>'}
      <div style="flex:1;min-width:0">
        <input style="width:110px" data-sp-name="${i}" value="${esc(sp.name || '')}" placeholder="e.g. Bedroom" ${dis}>
        <input style="flex:1;width:calc(100% - 120px);margin-left:6px" data-sp-desc="${i}" value="${esc(sp.description || '')}" placeholder="cosy room with fairy lights and books" ${dis}>
      </div>
      <button class="small bad" data-sp-del="${i}" ${dis}>×</button>
    </div>`;
  }).join('');

  // ── goals panel ──
  const goals = LIFE_GOALS || [];
  const statusBadge = s => s === 'active' ? badge('done','active') : s === 'achieved' ? badge('info','achieved') : badge('queued','paused');
  const goalCards = goals.length ? goals.map(g => `
    <div class="card pad mt-s" style="padding:8px 10px">
      <div class="row"><b>${esc(g.title)}</b>${statusBadge(g.status)}<span class="badge b-info" style="font-size:10px">${esc(g.category)}</span><span class="sp"></span>
        <button class="small" data-goal-done="${esc(g.id)}" title="Mark achieved">✓</button>
        <button class="small bad" data-goal-del="${esc(g.id)}" title="Delete">×</button></div>
      ${g.description ? `<div class="mute small">${esc(g.description)}</div>` : ''}
      ${g.progress_notes && g.progress_notes.length ? `<details class="mt-s"><summary class="mute small">${g.progress_notes.length} progress note${g.progress_notes.length>1?'s':''}</summary>${g.progress_notes.map(n=>`<div class="small">· ${esc(n)}</div>`).join('')}</details>` : ''}
    </div>`).join('') : '<div class="mute small">No goals yet.</div>';

  // ── memory panel ──
  const mems = LIFE_MEMORIES || [];
  const strengthBar = s => { const f=Math.round(s*5); return '<span style="letter-spacing:-1px">'+'█'.repeat(f)+'░'.repeat(5-f)+'</span>'; };
  const relTime = ts => { const d = Math.round((Date.now()/1000 - ts)/86400); return d < 1 ? 'today' : d < 7 ? d+'d ago' : d < 30 ? Math.round(d/7)+'w ago' : Math.round(d/30)+'mo ago'; };
  const memRow = m => `
    <div class="row mt-s" style="gap:6px;align-items:flex-start;font-size:12px">
      <span title="strength ${m.current_strength}" style="color:var(--mute);white-space:nowrap">${strengthBar(m.current_strength||0)}</span>
      <span style="flex:1;color:${(m.current_strength||0)<0.2?'var(--mute)':'inherit'}">${esc(m.content)}</span>
      <span class="mute" style="white-space:nowrap">${relTime(m.formed_at)}</span>
      <button class="small bad" style="padding:0 4px;font-size:11px" data-mem-del="${esc(m.id)}">×</button>
    </div>`;
  const _memGroup = (label, items) => items.length ? `<div class="mute small" style="margin-top:10px;margin-bottom:2px;font-weight:600">${label}</div>${items.map(memRow).join('')}` : '';
  const _memBycat = cat => mems.filter(m => m.category === cat);
  const memCards = mems.length ? (
    _memGroup('Wardrobe & fashion wishes', _memBycat('wish')) +
    _memGroup('Notes & insights', _memBycat('note')) +
    _memGroup('Recent activity', mems.filter(m => m.category !== 'wish' && m.category !== 'note').slice(0, 10))
  ) || '<div class="mute small">No memories yet — they form automatically after each think.</div>'
    : '<div class="mute small">No memories yet — they form automatically after each think.</div>';

  // ── life feed ──
  const events = LIFE_EVENTS || [];
  const absTime = ts => {
    const diff = Date.now()/1000 - ts;
    if (diff < 86400) {
      const dt = new Date(ts * 1000);
      return dt.toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit', hour12: true});
    }
    const d = Math.round(diff/86400);
    return d < 7 ? d+'d ago' : d < 30 ? Math.round(d/7)+'w ago' : Math.round(d/30)+'mo ago';
  };
  const eventCard = ev => {
    const out = ev.outputs || {};
    if (ev.event_type === 'think') {
      const drawEv = events.find(e => e.event_type === 'draw' && (e.inputs||{}).event_id === ev.id);
      const drawnUrl = drawEv ? esc((drawEv.outputs||{}).url||'') : '';
      const drawn = drawnUrl ? `<img src="${drawnUrl}" style="width:120px;height:160px;object-fit:cover;border-radius:8px;margin-top:6px;cursor:zoom-in" onclick="chZoom('${drawnUrl}')" onerror="this.style.display='none'">` : '';
      const gp = out.goal_progress ? `<div class="mute small" style="margin-top:4px">↳ goal: ${esc(out.goal_progress)}</div>` : '';
      const noteHtml = out.note ? `<div style="margin-top:6px;font-size:12px;padding:4px 8px;background:var(--panel);border-radius:6px;border-left:2px solid var(--warn)">note: ${esc(out.note)}</div>` : '';
      const wishHtml = out.wardrobe_want ? `<div style="margin-top:6px;font-size:12px;padding:4px 8px;background:var(--panel);border-radius:6px;border-left:2px solid var(--ok)">wants: ${esc(out.wardrobe_want)}</div>` : '';
      const outfitTag = out.outfit_id ? `<span class="badge b-info" style="font-size:10px" title="wardrobe item">outfit from wardrobe</span>` : '';
      const exprTag = out.expression ? `<span class="mute small" style="font-size:11px" title="${esc(out.face_state||'')}">${esc(out.expression)}</span>` : '';
      return `<div class="card pad mt-s" style="border-left:3px solid var(--accent)">
        <div class="row"><span class="badge b-info">${esc(out.mood||'')}</span>${outfitTag}<span class="mute small">${esc(out.activity||'')} · ${esc(out.space||'')} · ${absTime(ev.created_at)}</span></div>
        ${exprTag ? `<div style="margin:2px 0 4px">${exprTag}</div>` : ''}
        <div style="font-style:italic;margin:6px 0">${esc(out.thought||'')}</div>${gp}${noteHtml}${wishHtml}${drawn}
        ${!drawEv ? `${out.log_photo === false ? '<div class="mute small mt-s">Not worth a picture, she decided. </div>' : ''}<button class="small ${out.log_photo === false ? '' : 'primary'} mt-s" data-draw-ev="${esc(ev.id)}">${out.log_photo === false ? 'Draw anyway' : 'Draw this look'}</button>` : '<span class="mute small mt-s">✓ drawn</span>'}
        <details class="mt-s"><summary class="mute small" style="cursor:pointer">Pipeline debug</summary>
          <pre style="font-size:10px;white-space:pre-wrap;max-height:200px;overflow:auto">${esc(JSON.stringify(out,null,2))}</pre>
        </details>
      </div>`;
    }
    if (ev.event_type === 'error') return `<div class="errbox small mt-s" style="display:flex;align-items:center;gap:8px"><span style="flex:1">${esc(ev.trigger)} error · ${absTime(ev.created_at)}: ${esc(out.error||'unknown')}</span><button class="small" data-dismiss-ev="${esc(ev.id)}" style="flex-shrink:0">Dismiss</button></div>`;
    return '';
  };

  return `<div class="vl-grid ch-studio">
  <div>
    <div class="card pad">
      <h3 style="margin-top:0">Profile</h3>
      <label class="f">Core character <span class="mute small">upbringing, formative experiences, values — never changes</span>
        <textarea id="vl-core" style="min-height:72px" placeholder="Grew up in Chandigarh, trained in classical dance for 10 years, moved to Pune at 22 for work. Values discipline and loyalty above all." ${dis}>${esc(prof.core_character || '')}</textarea></label>
      <label class="f mt-s">Personality <span class="mute small">current traits — can drift over time</span><input id="vl-pers" value="${esc(prof.personality || '')}" placeholder="warm, curious, slightly introverted" ${dis}></label>
      <label class="f mt-s">City (for weather context)<input id="vl-city" value="${esc(prof.city || '')}" placeholder="Mumbai" ${dis}></label>
      <label class="f mt-s">Phone model<input id="vl-phone" value="${esc(prof.phone || '')}" placeholder="iPhone 15, Samsung Galaxy S24, Nothing Phone 2…" ${dis}></label>
      <label class="f mt-s">Fashion &amp; style <span class="mute small">what she gravitates toward — updated as she discovers new things</span>
        <textarea id="vl-fashion" style="min-height:52px" placeholder="Prefers kurtas and co-ords over western wear, likes earthy tones and block prints, always watches Myntra sale." ${dis}>${esc(prof.fashion_taste || '')}</textarea></label>
      <label class="f mt-s">Chronotype
        <select id="vl-chrono" ${dis}>
          <option value="" ${!prof.chronotype?'selected':''}>balanced (adapts to a normal day)</option>
          <option value="early bird" ${prof.chronotype==='early bird'?'selected':''}>early bird — peaks in the morning, winds down by 9–10 pm</option>
          <option value="night owl" ${prof.chronotype==='night owl'?'selected':''}>night owl — slow mornings, peak energy in the evening</option>
        </select></label>
      <h4 style="margin:12px 0 4px">Interests</h4>
      <div class="mute small" style="margin-bottom:6px">Intensity bar fills automatically as the character engages with each interest over time.</div>
      ${['books','movies','music','food','hobbies'].map(k => {
        const raw = interests[k];
        const idata = (raw && typeof raw === 'object') ? raw : {text: raw || '', intensity: 5};
        const textVal = idata.text || '';
        const intensity = Math.max(1, Math.min(10, idata.intensity || 5));
        const filled = Math.round(intensity / 2);  // 0-5 blocks
        const bar = '█'.repeat(filled) + '░'.repeat(5 - filled);
        return `<div class="row mt-s" style="gap:6px;align-items:center">
          <span style="min-width:52px;font-size:12px;color:var(--mute)">${k}</span>
          <input style="flex:1" id="vl-int-${k}" data-int-key="${k}" value="${esc(textVal)}" placeholder="" ${dis}>
          <span title="Intensity ${intensity}/10" style="font-size:11px;letter-spacing:-1px;color:var(--accent);white-space:nowrap">${bar} ${intensity}</span>
        </div>`;
      }).join('')}
      <div id="vl-interest-proposals" style="margin-top:8px"></div>
      <div class="row" style="align-items:center;margin:12px 0 4px"><h4 style="margin:0">Spaces she lives in</h4><span class="sp"></span>${spaces.length ? `<button class="small primary" id="vl-sp-studio" ${dis}>Space Studio →</button>` : ''}</div>
      <div id="vl-spaces">${spacesHtml}</div>
      <div class="row mt-s" style="gap:6px"><button class="small" id="vl-sp-add" ${dis}>+ Add space</button>${spaces.length ? `<button class="small primary" id="vl-sp-studio2" ${dis}>Space Studio →</button>` : ''}</div>
      <h4 style="margin:16px 0 4px">Recurring accessories &amp; props</h4>
      <div class="mute small" style="margin-bottom:6px">Phone, laptop, bag, mug — upload a ref photo so they look the same in every picture.</div>
      <div id="vl-accessories">${(prof.accessories || []).map(a => {
        const hasRef = a.ref_image;
        const refUrl = hasRef ? `/api/characters/file/${CID}/accessories/${a.ref_image.split('/').pop()}` : '';
        return `<div class="card pad mt-s" style="padding:8px;background:var(--bg2,#f8f8f8)">
          <div class="row" style="gap:6px;align-items:center">
            <b style="min-width:80px">${esc(a.name)}</b>
            <span class="mute small" style="flex:1">${esc(a.description || '')}</span>
            <button class="small bad" data-acc-del="${esc(a.name)}" ${dis}>×</button>
          </div>
          <div class="row mt-s" style="gap:8px;align-items:center">
            ${hasRef ? `<img src="${esc(refUrl)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;border:1px solid var(--line)">` : '<div style="width:48px;height:48px;border-radius:6px;border:2px dashed var(--line);display:flex;align-items:center;justify-content:center;color:var(--mute);font-size:18px">+</div>'}
            <input type="file" data-acc-ref-upload="${esc(a.name)}" accept="image/*" style="font-size:11px;flex:1" ${dis}>
            ${hasRef ? `<button class="small bad" data-acc-ref-del="${esc(a.name)}" ${dis}>✕ ref</button>` : ''}
          </div>
        </div>`;
      }).join('')}</div>
      <div class="row mt-s" style="gap:6px">
        <input id="vl-acc-name" placeholder="e.g. iPhone 17" style="width:120px" ${dis}>
        <input id="vl-acc-desc" placeholder="description (optional)" style="flex:1" ${dis}>
        <button class="small" id="vl-acc-add" ${dis}>+ Add</button>
      </div>
      <label class="f mt-s">Current context<input id="vl-ctx" value="${esc(prof.current_context || '')}" placeholder="just moved to a new city for a job" ${dis}></label>
      <div class="row mt-s" style="gap:8px"><button class="primary" id="vl-save" ${dis}>Save profile</button></div>
      <h4 style="margin:16px 0 4px">Energy &amp; Feeling</h4>
      ${(() => {
        const e = prof.energy ?? 80;
        const col = e > 60 ? 'var(--ok)' : e > 30 ? 'var(--warn)' : 'var(--bad,#c0392b)';
        const feel = prof.current_feeling || {};
        const fPrimary = feel.primary || '';
        const fInt = feel.intensity || '';
        const feelHtml = fPrimary
          ? `<span class="badge" style="background:var(--panel);border:1px solid var(--line);font-size:11px">${esc(fPrimary)}${fInt ? ' · '+fInt+'/10' : ''}</span>`
          : `<span class="mute small">no feeling set yet</span>`;
        const feelingOpts = ['','peaceful','content','grateful','settled','cosy','satisfied','excited','hopeful','proud','inspired','playful','flirtatious','amorous','euphoric','radiant','giddy','elated','ambitious','determined','energised','focused','driven','motivated','purposeful','anxious','irritable','bored','frustrated','disappointed','guilty','embarrassed','overwhelmed','deflated','insecure','resentful','drained','nostalgic','conflicted','restless','melancholy','wistful','curious','unsettled','numb','pensive','bittersweet','yearning','detached','tired-but-happy','drained-and-blank','wound-up','buzzing','restless-energy','heavy','light','desirous','longing','aroused','craving','infatuated','possessive','hungry','tempted','warm','affectionate','tender','connected','lonely','left-out','jealous','seen','invisible','needy'].map(f => `<option value="${f}" ${f===fPrimary?'selected':''}>${f||'— pick feeling —'}</option>`).join('');
        return `<div class="row" style="align-items:center;gap:8px">
          <div style="flex:1;height:8px;background:var(--line);border-radius:4px">
            <div style="width:${e}%;height:100%;border-radius:4px;background:${col};transition:width .4s"></div>
          </div>
          <span class="mute small" style="white-space:nowrap">${e}/100</span>
        </div>
        <div class="row mt-s" style="gap:6px;align-items:center">
          <span class="mute small" style="min-width:50px">feeling</span>${feelHtml}
        </div>
        <details class="mt-s" style="font-size:12px">
          <summary class="mute small" style="cursor:pointer">Override energy &amp; feeling</summary>
          <div style="margin-top:8px;display:flex;flex-direction:column;gap:6px">
            <div class="row" style="gap:6px;align-items:center">
              <span class="mute small" style="min-width:50px">energy</span>
              <input type="range" id="vl-energy-ov" min="0" max="100" value="${e}" style="flex:1" ${dis}>
              <span id="vl-energy-ov-val" style="font-size:12px;min-width:28px">${e}</span>
            </div>
            <div class="row" style="gap:6px;align-items:center">
              <span class="mute small" style="min-width:50px">feeling</span>
              <select id="vl-feeling-ov" style="flex:1;font-size:12px" ${dis}>${feelingOpts}</select>
              <input type="number" id="vl-feeling-int" min="1" max="10" value="${fInt||7}" style="width:44px;font-size:12px" placeholder="1-10" ${dis}>
            </div>
            <button class="small primary" id="vl-override-apply" ${dis}>Apply override</button>
          </div>
        </details>
        <div class="mute small mt-s" style="display:flex;align-items:center;gap:8px">
          Sleep below <input type="number" id="vl-sleep-thr" min="5" max="40" value="${prof.sleep_threshold ?? 20}" style="width:48px" ${dis}> energy — restores ~12/hour while asleep.
        </div>`;
      })()}
      <h4 style="margin:16px 0 4px">Auto life</h4>
      <label style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <input type="checkbox" id="vl-enabled" ${prof.life_enabled ? 'checked' : ''} ${dis}> Auto-run when idle
        <span class="mute small" style="margin-left:4px">every</span>
        <input type="number" id="vl-interval" min="15" max="1440" value="${prof.life_interval_m || 60}" style="width:56px" ${dis}>
        <span class="mute small">min</span>
      </label>
      <label style="display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="vl-auto-draw" ${prof.auto_draw ? 'checked' : ''} ${dis}> Auto-draw when she finds it worth logging
      </label>
      <div class="mute small mt-s">She decides after each thought if the moment deserves a picture. Off: nothing is drawn by itself, use "Draw this look" on any moment. Applies to auto-run and the think button.</div>
      <h4 style="margin:16px 0 4px">Picture styles</h4>
      ${[['third_person','Third person','someone else or a timer takes it'],['selfie','Selfie / vlog','front camera or mirror selfie'],['pov','POV','what she sees, her view']].map(([k,l,d]) => `<label style="display:flex;align-items:center;gap:6px;margin:3px 0"><input type="checkbox" data-shot-style="${k}" ${(prof.shot_styles || ['third_person','selfie','pov']).includes(k) ? 'checked' : ''} ${dis}> ${l} <span class="mute small">${d}</span></label>`).join('')}
      <div class="mute small mt-s">Every picture follows these. With more than one ticked she picks what suits what she is doing.</div>
      <div id="vl-loop-status" class="mute small mt-s"></div>
    </div>

    <div class="card pad mt">
      <div class="row"><h3 style="margin:0">Wardrobe</h3><span class="sp"></span>
        <label class="small" style="display:flex;align-items:center;gap:4px">
          <input type="number" id="vl-ward-n" min="3" max="15" value="8" style="width:48px"> outfits
        </label>
        <button class="small primary" id="vl-ward-gen" ${dis}>Generate for current weather</button>
      </div>
      <div class="mute small mt-s">AI plans outfits suited to the city weather, season and fashion taste, then draws each as a flat-lay image and saves to the wardrobe. One job at a time — check <a href="#/characters/wardrobe">Wardrobe</a> when done.</div>
      <div id="vl-ward-job" class="mt-s"></div>
    </div>

    <div class="card pad mt">
      <div class="row"><h3 style="margin:0">Goals</h3><span class="sp"></span><button class="small primary" id="vl-goal-add" ${dis}>+ Add goal</button></div>
      <div class="mute small">Things she is working toward — the brain plans thoughts around active goals.</div>
      <div id="vl-goals-list">${goalCards}</div>
    </div>

    <div class="card pad mt" id="vl-aspirations-card">
      <div class="row"><h3 style="margin:0">Aspirations</h3></div>
      <div class="mute small mb-s">Things she wishes for or wants to become — emerge naturally from thoughts, can be dismissed once achieved.</div>
      <div id="vl-asp-list"><div class="mute small">Loading…</div></div>
    </div>

    <div class="card pad mt" id="vl-skills-card">
      <div class="row"><h3 style="margin:0">Skills</h3><span class="sp"></span></div>
      <div class="mute small mb-s">Practice hours accumulate automatically from activity. Levels: L1 Beginner → L5 Fluent.</div>
      <div id="vl-skill-list"></div>
      <div class="row mt-s" style="gap:6px">
        <input id="vl-sk-name" style="flex:1" placeholder="Skill name (e.g. Bhangra)" ${dis}>
        <input id="vl-sk-cat" style="width:100px" placeholder="Category" ${dis}>
        <input id="vl-sk-hours" type="number" min="0" max="500" value="0" style="width:60px" ${dis}>
        <span class="mute small" style="align-self:center">h</span>
        <button class="small" id="vl-sk-add" ${dis}>+ Add</button>
      </div>
    </div>

    <div class="card pad mt">
      <h3 style="margin-top:0">Memories <span class="mute small">${mems.length} total · fades after ~40 days</span></h3>
      <div id="vl-mem-list">${memCards}</div>
      <div class="row mt-s" style="gap:6px">
        <input id="vl-mem-add" style="flex:1" placeholder="Add a memory manually…" ${dis}>
        <button class="small" id="vl-mem-save" ${dis}>Add</button>
      </div>
    </div>
  </div>

  <div>
    <div class="card pad">
      <div class="row"><h3 style="margin:0">Life feed</h3><span class="mute small">${new Date().toLocaleString('en-IN', {weekday:'short', hour:'2-digit', minute:'2-digit', hour12:true})}</span><span class="sp"></span>
        <button class="primary" id="vl-think" ${dis}>What is she thinking?</button>
      </div>
      <div class="mute small mt-s">2-stage pipeline: first-pass thought → self-review → memory formed → image ready to draw.</div>
      <div id="life-feed-box" style="margin-top:10px">${events.length ? events.map(eventCard).join('') : '<div class="mute small" style="padding:12px 0">No moments yet.</div>'}</div>
    </div>
  </div>
</div>`;
}

function editsGallery(busy) {
  const list = (C.gallery.edit || []).slice().reverse();
  if (!list.length && !C.looks.length) return '';
  const dis = busy ? 'disabled' : '';
  const card = p => `<div class="ch-pic ${C.canon.body === p.id || C.canon.portrait === p.id ? 'canon' : ''}">${p.url ? `<img src="${esc(p.url)}" loading="lazy" onclick="chZoom('${esc(p.url)}')">` : `<div class="ph">${p.status === 'failed' ? 'failed<br>' + esc(p.error.slice(0, 80)) : 'drawing…'}</div>`}
    <div class="mute">${esc(p.op || 'edit')}${p.preset ? ': ' + esc(p.preset) : ''}${p.value ? ' · ' + esc(p.value.slice(0, 40)) : ''}</div>
    <div class="mute">chain ${p.depth}${p.depth >= 3 ? ' ⚠' : ''}${p.current ? '' : ' · older'}</div>${checkBadge(p)}
    ${p.status === 'failed' ? `<div class="row" style="margin-top:4px;gap:4px;flex-wrap:wrap"><button class="small" data-retry="${p.id}" ${dis}>Retry</button><button class="small bad" data-del="${p.id}" ${dis}>Delete</button></div>` : ''}
    ${p.url ? `<div class="row" style="margin-top:4px;gap:4px;flex-wrap:wrap"><button class="small" data-base="${p.id}">Edit this</button><button class="small ${p.kept ? 'primary' : ''}" data-keep="${p.id}" data-on="${p.kept ? 0 : 1}">${p.kept ? 'Kept ✓' : 'Keep'}</button>
      <button class="small" data-look="${p.id}">Save as look</button><button class="small" data-check="${p.id}" ${dis}>Check</button><button class="small" data-cmp="${p.id}">${CMP.includes(p.id) ? 'Compare ✓' : 'Compare'}</button>
      ${p.op === 'edit' || p.op === 'swap' ? `<button class="small" data-retry="${p.id}" data-ask="1" ${dis} title="Make this again from the same pictures, prompt and LoRAs (a new random draw)">Retry</button>` : ''}
      ${(p.op === 'edit' || p.op === 'tryon') ? `<button class="small" data-promote="${p.id}" data-view="body">Make canon body</button>` : ''}
      <button class="small bad" data-del="${p.id}" ${dis}>Delete</button></div>` : ''}</div>`;
  return `<div class="card pad mt"><div class="row"><h3 style="margin:0">Edits and looks</h3><span class="sp"></span>${CMP.length === 2 ? '<button class="small primary" id="cmp-go">Compare the two</button>' : '<span class="mute small">pick two pictures to compare</span>'}</div>
    ${C.looks.length ? `<div class="row mt-s small" style="gap:8px;flex-wrap:wrap"><b>Looks:</b>${C.looks.map(l => `<span class="badge b-info" title="made from canon version ${l.version}">${esc(l.name)}${l.stale ? ' · older canon' : ''} <a href="#" data-lookbase="${l.item}">use</a> <button class="small bad" style="padding:1px 6px;font-size:11px" data-lookdel="${l.id}" title="Delete this look">×</button></span>`).join('')}</div>` : ''}
    <div class="ch-views mt-s">${list.map(card).join('')}</div></div>`;
}

function matrixCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait) return '';
  return `<div class="card pad mt"><div class="row"><h3 style="margin:0">Expression grid</h3><span class="mute small">one picture per look and expression (at most 12)</span></div>
    <div class="small mt-s">${OPT.expressions.map(e => `<label style="margin-right:10px"><input type="checkbox" data-mx="${e}" ${['smile', 'angry', 'worried'].includes(e) ? 'checked' : ''}> ${esc(e)}</label>`).join('')}</div>
    ${C.looks.length ? `<div class="small mt-s">Looks: ${C.looks.map(l => `<label style="margin-right:10px"><input type="checkbox" data-ml="${l.id}"> ${esc(l.name)}</label>`).join('')} <span class="mute">(none ticked = the canon portrait)</span></div>` : ''}
    <div class="row mt-s"><button class="small primary" id="mx-run" ${busy ? 'disabled' : ''}>Make the grid</button></div></div>`;
}

async function loadLists() {
  WARD = await call('/wardrobe').catch(() => []);
}

function pollWardrobeJob() {
  const box = document.getElementById('vl-ward-job');
  if (!box) return;
  call('/wardrobe/job').then(j => {
    if (!j || j.state === 'idle') { box.innerHTML = ''; return; }
    if (j.state === 'running') {
      box.innerHTML = `<div class="small mute"><span class="spin"></span> ${esc(j.label||'working')} · ${Math.round(j.elapsed_s||0)}s</div>`;
      setTimeout(pollWardrobeJob, 4000);
    } else if (j.state === 'done') {
      box.innerHTML = `<div class="small" style="color:var(--ok)">Done — check <a href="#/characters/wardrobe">Wardrobe</a> for the new items.</div>`;
    } else if (j.state === 'error') {
      box.innerHTML = `<div class="errbox small">${esc(j.error||'failed')}</div>`;
    }
  }).catch(() => {});
}

async function loadLifeEvents() {
  const [evs, goals, mems, asps] = await Promise.allSettled([
    call('/' + CID + '/life'),
    call('/' + CID + '/goals'),
    call('/' + CID + '/memories'),
    call('/' + CID + '/aspirations'),
  ]);
  LIFE_EVENTS      = evs.status    === 'fulfilled' ? evs.value    : [];
  LIFE_GOALS       = goals.status  === 'fulfilled' ? goals.value  : [];
  LIFE_MEMORIES    = mems.status   === 'fulfilled' ? mems.value   : [];
  LIFE_ASPIRATIONS = asps.status   === 'fulfilled' ? asps.value   : [];
}

function wireLife() {
  const $e = id => document.getElementById(id);
  if (!$e('vl-save')) return; // not on life tab
  // load events/goals/memories async; re-render once they arrive so the UI shows real data
  if (LIFE_EVENTS === null) { loadLifeEvents().then(() => { if (CH_TAB === 'life') render(); }); }
  // load interest proposals and render into the placeholder div
  call('/' + CID + '/interests/proposals').then(proposals => {
    const el = document.getElementById('vl-interest-proposals');
    if (!el || !proposals || !proposals.length) return;
    el.innerHTML = `<div style="margin-top:10px"><div class="mute small" style="font-weight:600;margin-bottom:4px">New interests Fifi wants to explore</div>` +
      proposals.filter(p => !p.outputs.approved && !p.outputs.dismissed).map(p => `
        <div class="row mt-s" style="gap:6px;align-items:center;font-size:12px">
          <span style="flex:1"><b>${esc(p.outputs.name||'')}</b><span class="mute"> · ${esc(p.outputs.category||'')}</span></span>
          <button class="small primary" data-int-approve="${esc(p.id)}">Add</button>
          <button class="small bad" data-int-dismiss="${esc(p.id)}">×</button>
        </div>`).join('') + '</div>';
    el.querySelectorAll('[data-int-approve]').forEach(btn => {
      btn.onclick = async () => {
        await call('/' + CID + '/interests/proposals/' + btn.dataset.intApprove + '/approve', {method:'POST'});
        btn.closest('.row').remove();
        C = await call('/' + CID); render();
      };
    });
    el.querySelectorAll('[data-int-dismiss]').forEach(btn => {
      btn.onclick = async () => {
        await call('/' + CID + '/interests/proposals/' + btn.dataset.intDismiss + '/dismiss', {method:'POST'});
        btn.closest('.row').remove();
      };
    });
  }).catch(() => {});
  pollWardrobeJob();
  const readSpaces = () => {
    const names = [...document.querySelectorAll('[data-sp-name]')];
    const descs = [...document.querySelectorAll('[data-sp-desc]')];
    return names.map((n, i) => ({name: n.value.trim(), description: descs[i] ? descs[i].value.trim() : ''})).filter(s => s.name);
  };
  $e('vl-save').onclick = async () => {
    const body = {
      core_character: ($e('vl-core') || {}).value || '',
      personality: ($e('vl-pers') || {}).value || '',
      city: ($e('vl-city') || {}).value || '',
      phone: ($e('vl-phone') || {}).value || '',
      fashion_taste: ($e('vl-fashion') || {}).value || '',
      chronotype: ($e('vl-chrono') || {}).value || '',
      sleep_threshold: parseInt(($e('vl-sleep-thr') || {}).value || '20'),
      interests: Object.fromEntries(['books','movies','music','food','hobbies'].map(k => {
        const el = $e('vl-int-'+k);
        const text = el ? el.value : '';
        const existing = (C.profile && C.profile.interests && C.profile.interests[k]);
        const meta = (existing && typeof existing === 'object') ? existing : {intensity: 5, last_engaged_ts: Date.now()/1000, added_by: 'owner'};
        return [k, {...meta, text}];
      })),
      spaces: readSpaces(),
      current_context: ($e('vl-ctx') || {}).value || '',
    };
    await act($e('vl-save'), async () => { const prof = await call('/' + CID + '/profile', {method: 'PATCH', json: body}); C.profile = prof; render(); return true; }, 'Profile saved');
  };
  // goals
  $e('vl-goal-add') && ($e('vl-goal-add').onclick = async () => {
    const cats = ['career','personal','creative','health','social','learning','financial'];
    const html = `<label class="f">Goal title<input id="ga-title" placeholder="Learn Kathak"></label>
      <label class="f mt-s">Category<select id="ga-cat">${cats.map(c=>`<option value="${c}">${c}</option>`).join('')}</select></label>
      <label class="f mt-s">Description (optional)<input id="ga-desc" placeholder="Take one class a week, practice 20 min daily"></label>`;
    const v = await dialog({title:'Add a goal', html, buttons:[{label:'Cancel',value:null},{label:'Add',primary:true,
      collect:l=>({title:l.querySelector('#ga-title').value.trim(),category:l.querySelector('#ga-cat').value,description:l.querySelector('#ga-desc').value.trim()}),
      validate:x=>x.title?'':'Write the goal title.'}]});
    if (!v) return;
    await act(null, async () => { await call('/' + CID + '/goals', {method:'POST', json:v}); await loadLifeEvents(); render(); return true; }, 'Goal added');
  });
  document.querySelectorAll('[data-goal-done]').forEach(b => b.onclick = async () => {
    await act(null, async () => { await call('/' + CID + '/goals/' + b.dataset.goalDone, {method:'PATCH', json:{status:'achieved'}}); await loadLifeEvents(); render(); return true; }, 'Marked achieved');
  });
  document.querySelectorAll('[data-goal-del]').forEach(b => b.onclick = async () => {
    if (!await confirmDlg('Delete goal', 'This cannot be undone.', 'Delete', true)) return;
    await act(null, async () => { await call('/' + CID + '/goals/' + b.dataset.goalDel, {method:'DELETE'}); await loadLifeEvents(); render(); return true; });
  });
  // memories
  $e('vl-mem-save') && ($e('vl-mem-save').onclick = async () => {
    const content = ($e('vl-mem-add') || {}).value || '';
    if (!content.trim()) return;
    await act(null, async () => { await call('/' + CID + '/memories', {method:'POST', json:{content}}); $e('vl-mem-add').value = ''; await loadLifeEvents(); render(); return true; }, 'Memory added');
  });
  document.querySelectorAll('[data-mem-del]').forEach(b => b.onclick = async () => {
    await act(null, async () => { await call('/' + CID + '/memories/' + b.dataset.memDel, {method:'DELETE'}); await loadLifeEvents(); render(); return true; });
  });
  $e('vl-think') && ($e('vl-think').onclick = async () => {
    const btn = $e('vl-think');
    const autoDraw = ($e('vl-auto-draw') || {}).checked;
    btn.disabled = true; btn.textContent = 'Thinking…';
    try {
      const ev = await call('/' + CID + '/think', {method: 'POST', json: {}});
      if (ev.ok) {
        if (autoDraw && ev.log_photo !== false) {
          btn.textContent = 'Drawing…';
          await call('/' + CID + '/life/' + ev.event_id + '/draw', {method: 'POST', json: {}});
          for (let i = 0; i < 90; i++) {
            await new Promise(r => setTimeout(r, 3000));
            const s = await call('/' + CID).catch(() => null);
            if (s) { C = s; if (!s.job || s.job.state !== 'running') break; }
          }
        }
        LIFE_EVENTS = null; await loadLifeEvents(); render(); toast(autoDraw && ev.log_photo === false ? 'Thought recorded, not worth a picture' : 'Thought recorded');
      }
    } catch(e) { toast('Could not think: ' + e.message, {bad: true}); }
    finally { if (btn) { btn.disabled = false; btn.textContent = 'What is she thinking?'; } }
  });
  // skills
  (async () => {
    const skList = $e('vl-skill-list');
    if (!skList) return;
    const LEVELS = {L1:'Beginner',L2:'Dabbling',L3:'Consistent',L4:'Practiced',L5:'Fluent'};
    const THRESHOLDS = [0,5,20,60,150,300];
    const renderSkills = skills => {
      skList.innerHTML = !skills.length ? '<div class="mute small">No skills yet.</div>' :
        skills.map(sk => {
          const lnum = parseInt((sk.level||'L1').replace('L',''))||1;
          const prev = THRESHOLDS[lnum-1]||0, next = THRESHOLDS[Math.min(lnum,5)];
          const h = sk.hours||0;
          const pct = next>prev ? Math.min(100,Math.round((h-prev)/(next-prev)*100)) : 100;
          return `<div class="row mt-s" style="gap:6px;align-items:center;font-size:12px">
            <span style="min-width:90px;font-weight:600">${esc(sk.name)}</span>
            <span class="mute small" style="min-width:60px">${esc(sk.level||'L1')} ${esc(LEVELS[sk.level]||'')}</span>
            <div style="flex:1;height:5px;background:var(--line);border-radius:3px"><div style="width:${pct}%;height:100%;border-radius:3px;background:var(--accent2)"></div></div>
            <span class="mute small" style="min-width:30px;text-align:right">${h.toFixed(0)}h</span>
            <button class="small bad" data-sk-del="${esc(sk.name)}" style="padding:1px 5px">×</button>
          </div>`;
        }).join('');
      skList.querySelectorAll('[data-sk-del]').forEach(btn => {
        btn.onclick = async () => {
          await call('/' + CID + '/skills/' + encodeURIComponent(btn.dataset.skDel), {method:'DELETE'}).catch(()=>{});
          const updated = await call('/' + CID + '/skills').catch(()=>[]);
          renderSkills(updated);
        };
      });
    };
    const skills = await call('/' + CID + '/skills').catch(()=>[]);
    renderSkills(skills);
    $e('vl-sk-add') && ($e('vl-sk-add').onclick = async () => {
      const name = ($e('vl-sk-name')||{}).value?.trim();
      const cat  = ($e('vl-sk-cat')||{}).value?.trim() || '';
      const hrs  = parseFloat(($e('vl-sk-hours')||{}).value) || 0;
      if (!name) return;
      await call('/' + CID + '/skills', {method:'POST', json:{name, category:cat, seed_hours:hrs}}).catch(()=>{});
      if ($e('vl-sk-name')) $e('vl-sk-name').value = '';
      const updated = await call('/' + CID + '/skills').catch(()=>[]);
      renderSkills(updated);
    });
  })();
  // wardrobe generation
  $e('vl-ward-gen') && ($e('vl-ward-gen').onclick = async () => {
    const n = parseInt(($e('vl-ward-n')||{}).value||'8');
    await act($e('vl-ward-gen'), async () => {
      await call('/wardrobe/generate/' + CID + '?n=' + n, {method: 'POST', json: {}});
      pollWardrobeJob();
      return true;
    }, 'Generating outfits…');
  });

  document.querySelectorAll('[data-dismiss-ev]').forEach(b => b.onclick = async () => {
    await act(b, async () => { await call('/' + CID + '/life/' + b.dataset.dismissEv, {method: 'DELETE'}); LIFE_EVENTS = null; await loadLifeEvents(); render(); return true; });
  });
  document.querySelectorAll('[data-draw-ev]').forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = 'Drawing…';
    try {
      await call('/' + CID + '/life/' + b.dataset.drawEv + '/draw', {method: 'POST', json: {}});
      // draw runs as a background job — poll until done
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 3000));
        const s = await call('/' + CID).catch(() => null);
        if (s) { C = s; if (!s.job || s.job.state !== 'running') break; }
      }
      LIFE_EVENTS = null; await loadLifeEvents(); render();
    } catch(e) { toast(e.message, {bad: true}); b.disabled = false; b.textContent = 'Draw this look'; }
  });
  // show loop status
  call('/' + CID + '/life/status').then(st => {
    const el = document.getElementById('vl-loop-status'); if (!el) return;
    const relMin = ts => { if (!ts) return '—'; const m = Math.round((ts - Date.now()/1000)/60); return m < 1 ? 'soon' : m + ' min'; };
    const lastMin = ts => { if (!ts) return 'never'; const m = Math.round((Date.now()/1000 - ts)/60); return m < 1 ? 'just now' : m < 60 ? m+'m ago' : Math.round(m/60)+'h ago'; };
    el.textContent = `Loop ${st.loop_running ? '● running' : '○ stopped'} · last: ${lastMin(st.last_run_at)} · next: ${st.life_enabled ? relMin(st.next_run_at) : 'off'}`;
  }).catch(() => {});
  $e('vl-enabled') && ($e('vl-enabled').onchange = async () => {
    const body = {life_enabled: $e('vl-enabled').checked};
    await act(null, async () => { await call('/' + CID + '/profile', {method: 'PATCH', json: body}); return true; }, $e('vl-enabled').checked ? 'Auto life on' : 'Auto life off');
  });
  $e('vl-auto-draw') && ($e('vl-auto-draw').onchange = async () => {
    await act(null, async () => { await call('/' + CID + '/profile', {method: 'PATCH', json: {auto_draw: $e('vl-auto-draw').checked}}); return true; }, $e('vl-auto-draw').checked ? 'Auto-draw on' : 'Auto-draw off');
  });
  document.querySelectorAll('[data-shot-style]').forEach(cb => cb.onchange = async () => {
    const styles = [...document.querySelectorAll('[data-shot-style]')].filter(x => x.checked).map(x => x.dataset.shotStyle);
    if (!styles.length) { cb.checked = true; toast('Keep at least one picture style', {bad: true}); return; }
    await act(null, async () => { C.profile = await call('/' + CID + '/profile', {method: 'PATCH', json: {shot_styles: styles}}); return true; }, 'Picture styles saved');
  });
  $e('vl-interval') && ($e('vl-interval').onchange = async () => {
    const v = parseInt($e('vl-interval').value) || 60;
    await act(null, () => call('/' + CID + '/profile', {method: 'PATCH', json: {life_interval_m: v}}), '');
  });
  $e('vl-sp-add') && ($e('vl-sp-add').onclick = () => {
    const box = document.getElementById('vl-spaces');
    const i = box.querySelectorAll('[data-sp-name]').length;
    const card = document.createElement('div'); card.className = 'card pad mt-s'; card.style.cssText = 'padding:8px;background:var(--bg2,#f8f8f8);display:flex;align-items:center;gap:10px';
    card.innerHTML = `<div style="width:56px;height:40px;border-radius:6px;border:2px dashed var(--line);display:flex;align-items:center;justify-content:center;color:var(--mute);font-size:10px;flex-shrink:0">new</div><div style="flex:1;min-width:0"><input style="width:110px" data-sp-name="${i}" placeholder="e.g. Balcony"><input style="flex:1;width:calc(100% - 120px);margin-left:6px" data-sp-desc="${i}" placeholder="morning sun, cane chair, street below"></div><button class="small bad" data-sp-del="${i}">×</button>`;
    card.querySelector('[data-sp-del]').onclick = e => { e.target.closest('.card').remove(); };
    box.appendChild(card);
  });
  document.querySelectorAll('[data-sp-del]').forEach(b => b.onclick = e => e.target.closest('.card').remove());

  const _refresh = async () => { C = await call('/' + CID); render(); };

  // ── Space Studio modal ──────────────────────────────────────────────────
  // wire buttons (function defined at module level below)
  document.querySelectorAll('[data-sp-open]').forEach(btn => {
    btn.onclick = () => openSpaceStudio(btn.dataset.spOpen);
  });
  const spStudioBtns = ['vl-sp-studio','vl-sp-studio2'].map(id => document.getElementById(id)).filter(Boolean);
  spStudioBtns.forEach(btn => {
    btn.onclick = () => {
      const spaces = C.profile?.spaces || [];
      openSpaceStudio(spaces[0]?.name || '');
    };
  });
  // energy range display
  $e('vl-energy-ov') && ($e('vl-energy-ov').oninput = () => {
    $e('vl-energy-ov-val').textContent = $e('vl-energy-ov').value;
  });

  // override apply
  $e('vl-override-apply') && ($e('vl-override-apply').onclick = async () => {
    const energy = parseInt($e('vl-energy-ov').value);
    const fPrimary = ($e('vl-feeling-ov').value || '').trim();
    const fInt = parseInt($e('vl-feeling-int').value) || 7;
    const body = {};
    if (!isNaN(energy)) body.energy = energy;
    if (fPrimary) body.feeling = {primary: fPrimary, intensity: fInt};
    if (!Object.keys(body).length) return;
    try {
      await call('/' + CID + '/override', {method:'PATCH', json: body});
      C = await call('/' + CID);
      render();
      toast('Energy & feeling updated.');
    } catch(e) { showErr('Override failed: ' + (e.detail||e.message||e)); }
  });

  // aspirations
  (async () => {
    const asps = LIFE_ASPIRATIONS || await call('/' + CID + '/aspirations').catch(() => []);
    LIFE_ASPIRATIONS = asps;
    const box = document.getElementById('vl-asp-list');
    if (!box) return;
    if (!asps.length) { box.innerHTML = '<div class="mute small">None yet — they emerge naturally from her thoughts.</div>'; return; }
    box.innerHTML = asps.map(a => `
      <div class="row mt-s" style="gap:8px;align-items:flex-start;font-size:13px">
        <div style="flex:1">
          <b>${esc(a.title || a.text || '')}</b>
          ${a.category ? `<span class="badge b-info" style="font-size:10px;margin-left:4px">${esc(a.category)}</span>` : ''}
          ${a.reason ? `<div class="mute small" style="margin-top:2px">${esc(a.reason)}</div>` : ''}
        </div>
        <button class="small bad" data-asp-dismiss="${esc(a.id)}" title="Dismiss aspiration">× Dismiss</button>
      </div>`).join('');
    box.querySelectorAll('[data-asp-dismiss]').forEach(btn => {
      btn.onclick = async () => {
        await call('/' + CID + '/aspirations/' + btn.dataset.aspDismiss, {method:'DELETE'}).catch(()=>{});
        LIFE_ASPIRATIONS = (LIFE_ASPIRATIONS||[]).filter(a => a.id !== btn.dataset.aspDismiss);
        btn.closest('.row').remove();
        if (!box.querySelectorAll('[data-asp-dismiss]').length)
          box.innerHTML = '<div class="mute small">None yet — they emerge naturally from her thoughts.</div>';
      };
    });
  })();

  // accessories
  $e('vl-acc-add') && ($e('vl-acc-add').onclick = async () => {
    const name = ($e('vl-acc-name').value || '').trim();
    const desc = ($e('vl-acc-desc').value || '').trim();
    if (!name) return;
    const fd = new FormData(); fd.append('name', name); if (desc) fd.append('description', desc);
    try {
      await call('/' + CID + '/accessories', {method: 'POST', form: fd});
      await _refresh();
    } catch(e) { showErr('Add accessory failed: ' + (e.detail || e.message || e)); }
  });
  document.querySelectorAll('[data-acc-del]').forEach(b => b.onclick = async () => {
    const name = b.getAttribute('data-acc-del');
    await call('/' + CID + `/accessories/${encodeURIComponent(name)}`, {method: 'DELETE'});
    await _refresh();
  });
  document.querySelectorAll('[data-acc-ref-upload]').forEach(inp => inp.onchange = async () => {
    const accName = inp.getAttribute('data-acc-ref-upload');
    if (!accName || !inp.files[0]) return;
    const fd = new FormData(); fd.append('file', inp.files[0]);
    try {
      await call('/' + CID + `/accessories/${encodeURIComponent(accName)}/ref`, {method: 'POST', form: fd});
      await _refresh();
    } catch(e) { showErr('Accessory ref upload failed: ' + (e.detail || e.message || e)); }
  });
  document.querySelectorAll('[data-acc-ref-del]').forEach(b => b.onclick = async () => {
    const accName = b.getAttribute('data-acc-ref-del');
    await call('/' + CID + `/accessories/${encodeURIComponent(accName)}/ref`, {method: 'DELETE'});
    await _refresh();
  });
}

function openSpaceStudio(initialSpName) {
  const existing = document.getElementById('sp-studio-overlay');
  if (existing) existing.remove();

  const allSpaces = (C.profile && C.profile.spaces) || [];
  if (!allSpaces.length) { toast('Add at least one space and save the profile first.', {bad: true}); return; }

  let spName = initialSpName || allSpaces[0].name || '';

  const buildCtrl = () => {
    const spaceData = allSpaces.find(s => (s.name||'').toLowerCase() === spName.toLowerCase()) || {};
    const spacePicker = allSpaces.length > 1
      ? `<select id="ss-space-pick" style="width:100%;font-size:13px;margin-bottom:8px">${allSpaces.map(s => `<option value="${esc(s.name||'')}" ${s.name===spName?'selected':''}>${esc(s.name||'')}</option>`).join('')}</select>`
      : `<div style="font-weight:600;font-size:14px;margin-bottom:8px">${esc(spName)}</div>`;
    return `${spacePicker}
      <label class="f" style="font-size:12px">Name<input id="ss-name" value="${esc(spName)}"></label>
      <label class="f mt-s" style="font-size:12px">Description<textarea id="ss-desc" style="min-height:52px" placeholder="cosy room with fairy lights and books">${esc(spaceData.description||'')}</textarea></label>
      <button class="small mt-s" id="ss-save-details">Save details</button>
      <hr style="border:none;border-top:1px solid var(--line);margin:8px 0">
      <label class="f" style="font-size:12px">Instruction <span class="mute" style="font-size:10px">optional — what to change</span>
        <textarea id="ss-instr" style="min-height:48px" placeholder="add a bookshelf, warmer light, more plants…"></textarea>
      </label>
      <button class="small primary mt-s" id="ss-gen">⚡ Generate main view</button>
      <button class="small mt-s" id="ss-corners">▣ Generate 4 corners</button>
      <div class="sp-status" id="ss-status"></div>
      <hr style="border:none;border-top:1px solid var(--line);margin:8px 0">
      <div style="font-size:12px;margin-bottom:4px">Upload reference</div>
      <input type="file" id="ss-upload" accept="image/*" style="font-size:11px;width:100%">`;
  };

  const ov = document.createElement('div');
  ov.id = 'sp-studio-overlay';
  ov.className = 'sp-studio-overlay';
  ov.innerHTML = `
    <div class="sp-studio" id="sp-studio-box">
      <div class="sp-studio-head">
        <b style="font-size:16px">Space Studio</b>
        <span class="sp"></span>
        <button class="small" id="ss-close">× Close</button>
      </div>
      <div class="sp-studio-body">
        <div class="sp-studio-ctrl" id="ss-ctrl">${buildCtrl()}</div>
        <div class="sp-studio-imgs" id="ss-images"><div class="mute small">Loading…</div></div>
      </div>
    </div>`;
  document.body.appendChild(ov);

  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  document.getElementById('ss-close').onclick = () => ov.remove();

  const wireCtrl = () => {
    const $s = id => document.getElementById(id);

    const picker = $s('ss-space-pick');
    if (picker) picker.onchange = () => {
      spName = picker.value;
      document.getElementById('ss-ctrl').innerHTML = buildCtrl();
      wireCtrl();
      loadImages();
    };

    let jobRunning = false;
    const setStatus = (msg, running=false) => {
      const el = $s('ss-status'); if (el) el.textContent = msg;
      jobRunning = running;
      const g = $s('ss-gen'); if (g) { g.disabled = running; g.textContent = running ? '…generating…' : '⚡ Generate main view'; }
      const co = $s('ss-corners'); if (co) co.disabled = running;
    };
    const pollJob = async (maxS=180) => {
      for (let t = 0; t < maxS/3; t++) {
        await new Promise(r => setTimeout(r, 3000));
        const st = await call('/' + CID).catch(() => null);
        if (st && (!st.job || st.job.state !== 'running')) break;
      }
    };

    $s('ss-save-details') && ($s('ss-save-details').onclick = async () => {
      const newName = ($s('ss-name').value||'').trim();
      const newDesc = ($s('ss-desc').value||'').trim();
      if (!newName) return;
      const spaces = (C.profile?.spaces||[]).map(s => s.name?.toLowerCase()===spName.toLowerCase() ? {...s,name:newName,description:newDesc} : s);
      await call('/'+CID+'/profile', {method:'PATCH', json:{spaces}}).catch(e=>showErr(e.detail||e.message));
      spName = newName;
      C = await call('/'+CID);
      render(); toast('Space details saved.');
    });

    $s('ss-gen') && ($s('ss-gen').onclick = async () => {
      const instr = ($s('ss-instr').value||'').trim();
      setStatus('Generating main view…', true);
      try {
        await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/generate', {method:'POST', json:{instruction:instr}});
        setStatus('Waiting for job…', true);
        await pollJob(180);
        setStatus(''); C = await call('/'+CID); await loadImages(); render();
      } catch(e) { setStatus(''); showErr('Generate failed: '+(e.detail||e.message||e)); }
    });

    $s('ss-corners') && ($s('ss-corners').onclick = async () => {
      const instr = ($s('ss-instr').value||'').trim();
      setStatus('Generating 4 corners…', true);
      try {
        await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/corners', {method:'POST', json:{instruction:instr}});
        setStatus('Waiting for corners job…', true);
        await pollJob(300);
        setStatus(''); C = await call('/'+CID); await loadImages(); render();
      } catch(e) { setStatus(''); showErr('Corners failed: '+(e.detail||e.message||e)); }
    });

    $s('ss-upload') && ($s('ss-upload').onchange = async () => {
      const f = $s('ss-upload').files[0]; if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      try {
        await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/ref', {method:'POST', form:fd});
        C = await call('/'+CID); render(); toast('Reference image uploaded.');
      } catch(e) { showErr('Upload failed: '+(e.detail||e.message||e)); }
    });
  };

  const loadImages = async () => {
    const imgs = await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/images').catch(()=>({main:[],corners:[]}));
    const box = document.getElementById('ss-images');
    if (!box) return;
    const hasApprovedMain = (imgs.main||[]).some(r => r.approved && r.status==='done');
    const co = document.getElementById('ss-corners'); if (co) co.disabled = !hasApprovedMain;
    const mkCard = (it, corner=false) => {
      const url = it.file ? `/api/characters/file/${CID}/${it.file}` : '';
      const ap = it.approved, fail = it.status==='failed', run = it.status==='running';
      const pr = (it.meta||{}).prompt||'';
      return `<div class="sp-img-card ${ap?'approved':''}" data-img-id="${esc(it.id)}">
        ${url ? `<img src="${esc(url)}" onclick="chZoom('${esc(url)}')" onerror="this.style.display='none'">` :
          `<div style="height:${corner?'140px':'200px'};background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:12px;color:var(--mute)">${fail?'✕ failed':run?'⏳ generating…':'—'}</div>`}
        <div class="sp-img-actions">
          ${ap ? '<span class="badge b-ok" style="font-size:10px">✓ approved</span>' : ''}
          ${url && !ap ? `<button class="small primary" data-ss-approve="${esc(it.id)}">✓ Approve</button>` : ''}
          <button class="small bad" data-ss-delete="${esc(it.id)}">✕ Reject</button>
          ${pr ? `<details style="font-size:10px;width:100%"><summary class="mute" style="cursor:pointer">prompt</summary><div style="white-space:pre-wrap;padding:4px;color:var(--mute)">${esc(pr)}</div></details>` : ''}
        </div>
      </div>`;
    };
    let html = '';
    if (!imgs.main.length && !imgs.corners.length) {
      html = '<div class="mute small">No images yet — click Generate main view to start.</div>';
    } else {
      if (imgs.main.length) html += `<div class="sp-section-label">Main views (${imgs.main.length})</div>` + imgs.main.slice().reverse().map(it=>mkCard(it)).join('');
      if (imgs.corners.length) html += `<div class="sp-section-label">Corner views (${imgs.corners.length})</div><div class="sp-corner-grid">` + imgs.corners.slice().reverse().map(it=>mkCard(it,true)).join('') + '</div>';
    }
    box.innerHTML = html;
    box.querySelectorAll('[data-ss-approve]').forEach(btn => btn.onclick = async () => {
      await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/images/'+btn.dataset.ssApprove+'/approve', {method:'POST'}).catch(()=>{});
      C = await call('/'+CID); await loadImages(); render();
    });
    box.querySelectorAll('[data-ss-delete]').forEach(btn => btn.onclick = async () => {
      await call('/'+CID+'/spaces/'+encodeURIComponent(spName)+'/images/'+btn.dataset.ssDelete, {method:'DELETE'}).catch(()=>{});
      C = await call('/'+CID); await loadImages(); render();
    });
  };

  wireCtrl();
  loadImages();
}

function wireEdit() {
  const $e = id => document.getElementById(id);
  const args = () => ({base: EB, preset: $e('e-preset').value, value: $e('e-value').value, extra: EX.slice(0, 2), garment: $e('e-garment').value, scope: $e('e-scope').value, n: +$e('e-n').value, prompt: $e('e-prompt').value});
  const det = document.querySelector('#ch-edit details');
  if (det) det.ontoggle = () => { ED_OPEN = det.open; };
  if ($e('e-base')) $e('e-base').onchange = () => { EB = $e('e-base').value; render(); };
  if ($e('e-ref-file')) $e('e-ref-file').onchange = async () => {
    const f = $e('e-ref-file').files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await call('/' + CID + '/upload-ref', {method: 'POST', form: fd});
      EX = [...EX, r.id].slice(-2);
      const box = document.getElementById('e-ex-list');
      if (box) box.innerHTML += `<label style="margin-right:8px"><input type="checkbox" checked disabled> uploaded: ${esc(f.name)}</label>`;
      toast('Reference uploaded');
    } catch(e) { toast(e.message, {bad: true}); }
    $e('e-ref-file').value = '';
  };
  if ($e('e-rebase')) $e('e-rebase').onclick = () => { EB = canonBody(); render(); };
  document.querySelectorAll('[data-ex]').forEach(x => x.onchange = () => { EX = x.checked ? [...EX, x.dataset.ex].slice(-2) : EX.filter(i => i !== x.dataset.ex); });
  if ($e('e-recipe')) $e('e-recipe').onchange = () => { const r = C.recipes[+$e('e-recipe').value]; if (r) { $e('e-preset').value = r.preset; $e('e-value').value = r.value; } };
  if ($e('e-save-recipe')) $e('e-save-recipe').onclick = async () => {
    const name = await textDlg('Save as recipe', 'Name', ''); if (!name) return;
    const rec = [...C.recipes, {name, preset: $e('e-preset').value, value: $e('e-value').value}];
    await act(null, async () => { C = await call('/' + CID + '/recipes', {method: 'PUT', json: {recipes: rec}}); render(); return true; }, 'Saved');
  };
  if ($e('e-wardrobe')) $e('e-wardrobe').onclick = wardrobeDialog;
  if ($e('e-prev')) $e('e-prev').onclick = b => act($e('e-prev'), async () => { const r = await call('/' + CID + '/edit/preview', {method: 'POST', json: args()}); const box = $e('e-preview'); box.hidden = false;
    box.innerHTML = `<b>${esc(r.model)} · ${esc(r.size)} · ${r.refs.length} picture${r.refs.length > 1 ? 's' : ''} · chain ${r.depth}</b><div style="white-space:pre-wrap;margin-top:4px">${esc(r.prompt)}</div>`; document.querySelector('#ch-edit details').open = true; return true; });
  if ($e('e-run')) $e('e-run').onclick = () => post($e('e-run'), '/edit', args(), 'Edit started');
  if ($e('pl-run')) $e('pl-run').onclick = async () => {
    const text = ($e('pl-text') || {}).value || '';
    const action = ($e('pl-action') || {}).value || '';
    const img = $e('pl-img') && $e('pl-img').files[0];
    if (!text.trim() && !img) { toast('Describe the setting or upload a reference image', {bad: true}); return; }
    const btn = $e('pl-run');
    btn.disabled = true; btn.textContent = 'Uploading…';
    try {
      const fd = new FormData();
      fd.append('action', action); fd.append('place_text', text); fd.append('base', EB); fd.append('n', '1');
      if (img) fd.append('place_image', img);
      await act(null, async () => { await call('/' + CID + '/in-place', {method: 'POST', form: fd}); await window._chLoad(true); return true; }, 'Placing started');
    } finally { btn.disabled = false; btn.textContent = 'Place them'; }
  };
  // virtual life wiring
  wireLife();
  if ($e('mx-run')) $e('mx-run').onclick = () => post($e('mx-run'), '/matrix', {expressions: [...document.querySelectorAll('[data-mx]:checked')].map(x => x.dataset.mx), looks: [...document.querySelectorAll('[data-ml]:checked')].map(x => x.dataset.ml)}, 'Grid started');
  // ref-blend card
  const RB_INSTRUCTIONS = {
    face:       'Replace only the face of the person in the first picture with the face from the second picture. Keep the hair (style, colour and length), head shape, clothes, body, pose, lighting and background from the first picture exactly. Do not copy the hair from the second picture. The result must look photorealistic and seamless.',
    outfit:     'Replace only the clothes of the person in the first picture with the outfit shown in the second picture — same colours, fabric, pattern and cut. Keep the face, hair, skin tone, body shape, pose, lighting and background from the first picture exactly. Do not copy the person wearing the clothes in the second picture.',
    background: 'Replace only the background, setting and lighting in the first picture with the background from the second picture. Keep the person exactly as they appear in the first picture: face, hair, clothes, body and pose unchanged.',
    face_into:  'Replace only the face of the person in the first picture with the face from the second picture. Keep the hair (style, colour and length) from the first picture. Keep the clothes, body, pose, lighting and background from the first picture exactly. Do not copy the hair from the second picture. The result must look photorealistic and seamless.',
  };
  if ($e('rb-base')) $e('rb-base').onchange = () => { EB = $e('rb-base').value; render(); };
  if ($e('rb-file')) $e('rb-file').onchange = () => { RB_FILE = ($e('rb-file').files || [])[0] || null; rbSummary(); };
  const rbSummary = () => {
    const el = $e('rb-sum'); if (!el) return;
    const src = allPics().find(p => p.id === (($e('rb-base') || {}).value || EB));
    const srcName = src ? picLabel(src) : 'the source picture';
    const file = RB_FILE || (($e('rb-file') || {}).files || [])[0];
    const ref = file ? file.name : 'the reference photo (not chosen yet)';
    const lora = RB.lora && (RB.part === 'face' || RB.part === 'face_into')
      ? 'head-swap LoRA' + (RB.expr ? ' (expression)' : '') + (RB.sharp ? ' + sharper' : '') + (RB.pure ? ' + PureLens' : '') : 'prompt only';
    el.innerHTML = RB.part === 'face_into'
      ? `Will keep <b>${esc(ref)}</b> (body, clothes, background) and put the face of <b>${esc(srcName)}</b> into it · ${lora}`
      : RB.part === 'face'
        ? `Will keep <b>${esc(srcName)}</b> and put the face from <b>${esc(ref)}</b> into it · ${lora}`
        : `Will keep <b>${esc(srcName)}</b> and take the ${esc(PARTS.find(p => p.id === RB.part).label.toLowerCase())} from <b>${esc(ref)}</b>`;
  };
  document.querySelectorAll('[name="rb-part"]').forEach(r => r.onchange = () => { RB.part = r.value; rbSummary(); });
  [['rb-lora', 'lora'], ['rb-expr', 'expr'], ['rb-sharp', 'sharp'], ['rb-pure', 'pure']].forEach(([id, k]) => { if ($e(id)) $e(id).onchange = () => { RB[k] = $e(id).checked; rbSummary(); }; });
  rbSummary();
  if ($e('rb-run')) $e('rb-run').onclick = async () => {
    const btn = $e('rb-run');
    const file = RB_FILE || (($e('rb-file') || {}).files && $e('rb-file').files[0]);
    if (!file) { toast('Upload a reference photo first', {bad: true}); return; }
    const part = (document.querySelector('[name="rb-part"]:checked') || {}).value || 'face';
    btn.disabled = true; btn.textContent = 'Uploading…';
    let refId;
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await call('/' + CID + '/upload-ref', {method: 'POST', form: fd});
      refId = r.id;
    } catch(e) { toast('Upload failed: ' + e.message, {bad: true}); btn.disabled = false; btn.textContent = 'Apply'; return; }
    RB_FILE = null;
    btn.textContent = 'Apply';
    const charId = ($e('rb-base') || {}).value || EB;
    const partLabel = PARTS.find(p => p.id === part)?.label || part;
    const editArgs = part === 'face_into'
      ? {base: refId, preset: 'custom', value: partLabel, extra: [charId], n: 1, prompt: RB_INSTRUCTIONS[part]}
      : {base: charId, preset: 'custom', value: partLabel, extra: [refId], n: 1, prompt: RB_INSTRUCTIONS[part]};
    if (part === 'outfit') editArgs.flatten = true;   // a photo of a person wearing it is edited itself unless it is turned into a flat lay first
    if ((part === 'face' || part === 'face_into') && ($e('rb-lora') || {checked: true}).checked) {
      const base = ($e('rb-expr') || {}).checked ? 'bfs-head-swap-expression' : 'bfs-head-swap';
      const addons = [($e('rb-sharp') || {}).checked && 'qwen2.1-detail-fix-2.0', ($e('rb-pure') || {}).checked && 'purelens-realism'].filter(Boolean);
      editArgs.swap = addons.length ? base + ',' + addons.join(',') : base;
      editArgs.prompt = '';  // server uses SWAP_DEFAULT_PROMPT when empty
    }
    post(btn, '/edit', editArgs, 'Applying…');
  };
  document.querySelectorAll('[data-base]').forEach(b => b.onclick = () => { EB = b.dataset.base; render(); document.getElementById('ch-edit').scrollIntoView({behavior: 'smooth'}); });
  document.querySelectorAll('[data-keep]').forEach(b => b.onclick = () => act(b, async () => { C = await call('/item/' + b.dataset.keep + '/keep?on=' + (b.dataset.on === '1'), {method: 'POST'}); render(); return true; }));
  document.querySelectorAll('[data-look]').forEach(b => b.onclick = async () => { const name = await textDlg('Save as a look', 'Name of the look', ''); if (name) await act(null, async () => { C = await call('/item/' + b.dataset.look + '/look', {method: 'POST', json: {name}}); render(); return true; }, 'Look saved'); });
  document.querySelectorAll('[data-check]').forEach(b => b.onclick = () => act(b, async () => { C = await call('/item/' + b.dataset.check + '/check', {method: 'POST'}); render(); return true; }, 'Checked'));
  document.querySelectorAll('[data-promote]').forEach(b => b.onclick = async () => { if (await confirmDlg('Make this the canon body', 'Every later picture is made from it, and looks made from the old canon show as older.', 'Make canon')) await act(null, async () => { C = await call('/item/' + b.dataset.promote + '/canon/' + b.dataset.view, {method: 'POST'}); render(); return true; }, 'Canon changed'); });
  document.querySelectorAll('[data-cmp]').forEach(b => b.onclick = () => { CMP = CMP.includes(b.dataset.cmp) ? CMP.filter(i => i !== b.dataset.cmp) : [...CMP, b.dataset.cmp].slice(-2); refreshCenter(); });
  document.querySelectorAll('[data-lookbase]').forEach(a => a.onclick = ev => { ev.preventDefault(); EB = a.dataset.lookbase; render(); });
  document.querySelectorAll('[data-lookdel]').forEach(a => a.onclick = ev => { ev.preventDefault(); act(null, async () => { C = await call('/' + CID + '/looks/' + a.dataset.lookdel, {method: 'DELETE'}); render(); return true; }); });
  document.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => { if (await confirmDlg('Delete picture', 'The file is removed from disk. This cannot be undone.', 'Delete', true)) await act(null, async () => { C = await call('/item/' + b.dataset.del, {method: 'DELETE'}); render(); return true; }); });
  if ($e('cmp-go')) $e('cmp-go').onclick = () => { const [a, b] = CMP.map(id => allPics().find(p => p.id === id)); if (a && b) dialog({title: 'Compare', html: `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><div><div class="mute small">${esc(picLabel(a))}</div><img src="${esc(a.url)}" style="width:100%;border-radius:8px"></div><div><div class="mute small">${esc(picLabel(b))}</div><img src="${esc(b.url)}" style="width:100%;border-radius:8px"></div></div>`, buttons: [{label: 'Close', value: true, primary: true}]}); };
}

async function wardrobeDialog() {
  WARD = await call('/wardrobe').catch(() => []);
  const html = `<div class="small mute">Pictures of clothes you can put on any character. A photo of someone wearing the clothes is fine: only the clothing is copied, never the person. For a worn photo, press "Flat lay" to make a clean picture of just the clothes (recommended).</div>
    <div class="ch-views mt-s">${WARD.map(g => `<div class="ch-pic"><img src="${esc(g.url)}" onclick="chZoom('${esc(g.url)}')"><div><b>${esc(g.name)}</b> ${g.worn ? '<span class="mute">worn by a model</span>' : ''}${g.flat ? ' ✓ flat lay' : ''}</div>
      <div class="row" style="gap:4px;margin-top:4px">${g.worn && !g.flat ? `<button class="small" data-flat="${g.id}">Flat lay</button>` : ''}<button class="small bad" data-gdel="${g.id}">Delete</button></div></div>`).join('') || '<div class="mute small">No garments yet.</div>'}</div>
    <h4>Add clothes</h4><label class="f">Name<input id="g-name" placeholder="Maroon sherwani"></label>
    <label class="f mt-s">Picture<input type="file" id="g-file" accept="image/jpeg,image/png,image/webp"></label>
    <label class="row mt-s"><input type="checkbox" id="g-worn"> A person is wearing them in this picture</label>
    <label class="f mt-s">Whose picture is it<select id="g-basis"><option value="own">Mine</option><option value="licensed">Licensed or free to use</option><option value="invented">An invented or drawn outfit</option></select></label>
    <label class="row mt-s"><input type="checkbox" id="g-ok"> I confirm this is true</label>`;
  const layer = dialog({title: 'Wardrobe', html, buttons: [{label: 'Close', value: null}, {label: 'Add', primary: true,
    collect: l => ({name: l.querySelector('#g-name').value, file: l.querySelector('#g-file').files[0], worn: l.querySelector('#g-worn').checked, basis: l.querySelector('#g-basis').value, ok: l.querySelector('#g-ok').checked}),
    validate: x => !x.file ? 'Choose a picture.' : !x.ok ? 'Tick the box to confirm.' : ''}]});
  setTimeout(() => {
    document.querySelectorAll('[data-gdel]').forEach(b => b.onclick = async () => { await act(null, () => call('/wardrobe/' + b.dataset.gdel, {method: 'DELETE'})); document.querySelector('.dlg')?.remove(); wardrobeDialog(); });
    document.querySelectorAll('[data-flat]').forEach(b => b.onclick = async () => { await act(null, () => call('/wardrobe/' + b.dataset.flat + '/flatlay', {method: 'POST'}), () => 'Making the flat lay: about two minutes'); document.querySelector('.dlg')?.remove(); });
  }, 50);
  const v = await layer;
  if (!v) { await loadLists(); render(); return; }
  const fd = new FormData(); fd.append('file', v.file); fd.append('name', v.name); fd.append('basis', v.basis); fd.append('confirmed', 'true'); fd.append('worn', v.worn ? 'true' : 'false');
  await act(null, () => call('/wardrobe', {method: 'POST', form: fd}), 'Added');
  await loadLists(); render();
}

async function startFromPicture() {
  const html = `<p class="small">The picture is only a reference for drawing this character. It stays on this machine and is never uploaded anywhere.</p>
    <label class="f">Whose picture is it<select id="p-basis"><option value="own">It is me</option><option value="consent">The person agreed</option><option value="licensed">Licensed or free to use</option><option value="invented">An invented or drawn character</option></select></label>
    <label class="row mt-s"><input type="checkbox" id="p-ok"> I confirm this is true</label>
    <label class="f mt-s">Picture<input type="file" id="p-file" accept="image/jpeg,image/png,image/webp"></label>`;
  const v = await dialog({title: 'Start from a picture', html, buttons: [{label: 'Cancel', value: null}, {label: 'Use it', primary: true,
    collect: l => ({basis: l.querySelector('#p-basis').value, ok: l.querySelector('#p-ok').checked, file: l.querySelector('#p-file').files[0]}),
    validate: x => !x.ok ? 'Tick the box to confirm.' : !x.file ? 'Choose a picture.' : ''}]});
  if (!v) return;
  const fd = new FormData(); fd.append('file', v.file); fd.append('basis', v.basis); fd.append('confirmed', 'true'); fd.append('read', 'true');
  await act(null, async () => { C = await call('/' + CID + '/photo', {method: 'POST', form: fd}); render(); return true; }, 'Picture read: check the details');
}
})();
