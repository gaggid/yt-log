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
@media (max-width:980px){.ch-studio{grid-template-columns:1fr}.ch-side{position:static;max-height:none}}
`;
document.head.append(css);

const call = (path, opts = {}) => api('/characters' + path, opts);
let C = null, CID = null, OPT = null, pollT = null;
const SLOT_ORDER = {person: null, place: null};

/* ───────── library ───────── */
window.viewCharacters = async function () {
  const my = route_id;
  clearTimeout(pollT);
  $('#app').innerHTML = `<div class="row"><h2 style="margin:0">Characters</h2><span class="mute">a library of people and places you can reuse in every short</span><span class="sp"></span>
    <button class="small" id="ch-import">Import pack</button>
    <select id="ch-kind" style="width:auto"><option value="">All</option><option value="person">People</option><option value="place">Places</option></select>
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
    <label class="f mt-s">What is it<select id="n-kind"><option value="person">A person</option><option value="place">A place</option></select></label>
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
  CID = id; clearTimeout(pollT);
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
  $('#app').innerHTML = `
    <div class="row"><a href="#/characters">← Characters</a><h2 style="margin:0 0 0 8px">${esc(C.name)}</h2>${badge(C.status === 'ready' ? 'done' : 'queued', C.status)}<span class="mute small">v${C.version} · ${esc(C.kind)}</span><span class="sp"></span>
      <button class="small" onclick="chRename()">Rename</button><a class="small" href="/api/characters/${C.id}/pack" download><button class="small">Export pack</button></a><button class="small" onclick="chDup(this)">Duplicate</button><button class="small bad" onclick="chDelete()">Delete</button></div>
    <div id="ch-job">${jobBox()}</div>
    <div class="ch-studio"><div class="ch-side card pad">${sideView(busy)}</div><div id="ch-center">${centerView(busy)}</div></div>`;
  wire();
}
function refreshCenter() { $('#ch-job').innerHTML = jobBox(); $('#ch-center').innerHTML = centerView(C.job && C.job.state === 'running'); wireCenter(); }

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

function centerView(busy) {
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
    ${editCard(busy)}${refBlendCard(busy)}${placeCard(busy)}${editsGallery(busy)}${matrixCard(busy)}`;
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
  const refEl = v === 'body' ? $e('body-ref') : null;
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
  document.querySelectorAll('[data-retry]').forEach(b => b.onclick = () => act(b, async () => { await call('/item/' + b.dataset.retry + '/retry', {method: 'POST'}); await window._chLoad(true); return true; }, 'Retrying…'));
  document.querySelectorAll('[data-canon]').forEach(b => b.onclick = () => act(b, async () => { await call('/item/' + b.dataset.canon + '/canon', {method: 'POST'}); await window._chLoad(true); return true; }, 'Saved'));
  const sh = document.querySelector('#ch-sheet'); if (sh) sh.onclick = () => post(sh, '/sheet', {}, 'Sheet started');
  wireEdit();
}

/* ───────── edits, try-on, places, looks, matrix (C2, C3) ───────── */
let EB = '', EX = [], CMP = [], WARD = null, PLACES = null, ED_OPEN = false;
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

function refBlendCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait) return '';
  const dis = busy ? 'disabled' : '';
  const pics = allPics();
  const PARTS = [
    {id: 'face',       label: 'Face',       hint: 'copies face, skin tone and eyes; keeps hair, clothes, pose, background'},
    {id: 'outfit',     label: 'Outfit',     hint: 'copies the full outfit; keeps face, hair, skin tone, pose, background'},
    {id: 'background', label: 'Background', hint: 'copies the setting and lighting; keeps the person, clothes and pose'},
  ];
  return `<div class="card pad mt" id="ch-refblend">
    <div class="row"><h3 style="margin:0">Take from a reference photo</h3><span class="mute small">copy one part from an uploaded photo onto this character</span></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
      <label class="f" style="min-width:200px">Source picture<select id="rb-base">${pics.map(p => `<option value="${p.id}" ${p.id === EB ? 'selected' : ''}>${esc(picLabel(p))}</option>`).join('')}</select></label>
      ${pics.find(p => p.id === EB) ? `<img src="${esc(pics.find(p => p.id === EB).url)}" style="height:70px;border-radius:6px">` : ''}
    </div>
    <div class="mt-s small"><b>What to take from the reference:</b>
      <div class="row mt-s" style="gap:8px;flex-wrap:wrap">
        ${PARTS.map(pt => `<label style="display:flex;align-items:center;gap:4px"><input type="radio" name="rb-part" value="${pt.id}" ${pt.id === 'face' ? 'checked' : ''}> <span><b>${pt.label}</b> <span class="mute">${pt.hint}</span></span></label>`).join('<br>')}
      </div>
    </div>
    <div class="row mt-s" style="gap:8px;align-items:center">
      <label class="small" style="display:flex;align-items:center;gap:6px">Reference photo <input type="file" id="rb-file" accept="image/jpeg,image/png,image/webp" style="font-size:12px"></label>
      <span id="rb-status" class="mute small"></span>
    </div>
    <div class="row mt-s"><button class="small primary" id="rb-run" ${dis}>Apply</button></div></div>`;
}

function placeCard(busy) {
  if (C.kind !== 'person' || !C.canon.portrait || !C.canon.body) return '';
  return `<div class="card pad mt"><div class="row"><h3 style="margin:0">Put the character in a place</h3><span class="mute small">uses the face, the body and the place picture</span></div>
    <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end"><label class="f">Place<select id="pl-place"><option value="">— choose —</option>${(PLACES || []).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></label>
      <label class="f" style="flex:1;min-width:220px">What is the person doing<input id="pl-action" placeholder="leaning on a steel pillar, looking at the track"></label>
      <button class="small primary" id="pl-run" ${busy ? 'disabled' : ''}>Place them</button></div>
    ${PLACES && !PLACES.length ? '<div class="mute small mt-s">No place with an approved picture yet: make one in Characters → New character → A place.</div>' : ''}</div>`;
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
  const ps = await call('?kind=place').catch(() => []);
  PLACES = [];
  for (const p of ps) { if (p.status === 'ready') PLACES.push(p); }
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
  if ($e('pl-run')) $e('pl-run').onclick = () => { if (!$e('pl-place').value) { toast('Choose a place first', {bad: true}); return; } post($e('pl-run'), '/place', {place: $e('pl-place').value, action: $e('pl-action').value, base: EB, n: 1}, 'Placing started'); };
  if ($e('mx-run')) $e('mx-run').onclick = () => post($e('mx-run'), '/matrix', {expressions: [...document.querySelectorAll('[data-mx]:checked')].map(x => x.dataset.mx), looks: [...document.querySelectorAll('[data-ml]:checked')].map(x => x.dataset.ml)}, 'Grid started');
  // ref-blend card
  const RB_INSTRUCTIONS = {
    face:       'Replace only the face of the person in the first picture with the face from the second picture. Keep the hair (style, colour and length), head shape, clothes, body, pose, lighting and background from the first picture exactly. Do not copy the hair from the second picture. The result must look photorealistic and seamless.',
    outfit:     'Replace only the clothes of the person in the first picture with the outfit shown in the second picture — same colours, fabric, pattern and cut. Keep the face, hair, skin tone, body shape, pose, lighting and background from the first picture exactly. Do not copy the person wearing the clothes in the second picture.',
    background: 'Replace only the background, setting and lighting in the first picture with the background from the second picture. Keep the person exactly as they appear in the first picture: face, hair, clothes, body and pose unchanged.',
  };
  if ($e('rb-base')) $e('rb-base').onchange = () => { EB = $e('rb-base').value; render(); };
  if ($e('rb-run')) $e('rb-run').onclick = async () => {
    const btn = $e('rb-run');
    const file = ($e('rb-file') || {}).files && $e('rb-file').files[0];
    if (!file) { toast('Upload a reference photo first', {bad: true}); return; }
    const part = (document.querySelector('[name="rb-part"]:checked') || {}).value || 'face';
    btn.disabled = true; btn.textContent = 'Uploading…';
    let refId;
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await call('/' + CID + '/upload-ref', {method: 'POST', form: fd});
      refId = r.id;
    } catch(e) { toast('Upload failed: ' + e.message, {bad: true}); btn.disabled = false; btn.textContent = 'Apply'; return; }
    const baseId = ($e('rb-base') || {}).value || EB;
    post(btn, '/edit', {base: baseId, preset: 'custom', value: 'see prompt', extra: [refId], n: 1, prompt: RB_INSTRUCTIONS[part]}, 'Applying…');
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
