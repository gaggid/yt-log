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
    <select id="ch-kind" style="width:auto"><option value="">All</option><option value="person">People</option><option value="place">Places</option></select>
    <button class="primary" id="ch-new">New character</button></div><div id="ch-list"><div class="skel"></div></div>`;
  $('#ch-new').onclick = newCharacter;
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

async function newCharacter() {
  OPT = OPT || await call('/options');
  const html = `<label class="f">Name<input id="n-name" placeholder="Raju, the night-shift courier"></label>
    <label class="f mt-s">What is it<select id="n-kind"><option value="person">A person</option><option value="place">A place</option></select></label>
    <label class="f mt-s">The idea, in a sentence or two<textarea id="n-idea" placeholder="A tired thirty-year-old delivery rider, quiet humour, always in a yellow jacket"></textarea></label>
    <label class="f mt-s">Look<select id="n-style">${Object.entries(OPT.styles).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join('')}</select></label>
    <p class="mute small">The look (and its LoRAs) is locked once you approve a picture: the same description in another look draws a different person.</p>`;
  const v = await dialog({title: 'New character', html, buttons: [{label: 'Cancel', value: null}, {label: 'Create', primary: true,
    collect: l => ({name: l.querySelector('#n-name').value, kind: l.querySelector('#n-kind').value, idea: l.querySelector('#n-idea').value, style: l.querySelector('#n-style').value}),
    validate: x => x.idea.trim().length < 5 ? 'Write the idea in a sentence.' : ''}]});
  if (!v) return;
  const st = OPT.styles[v.style];
  const c = await act(null, () => call('', {method: 'POST', json: {name: v.name, kind: v.kind, idea: v.idea, render: {style: v.style, model: OPT.default_render.model, loras: st.loras}}}));
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
  await load(true);
  if (sessionStorage.getItem('ch-suggest-' + id)) { sessionStorage.removeItem('ch-suggest-' + id); suggest(null); }
};
const editing = () => ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement && document.activeElement.tagName);
const post = (btn, path, json, ok) => act(btn, async () => { await call('/' + CID + path, {method: 'POST', json: json || {}}); await window._chLoad(true); return true; }, ok);
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
      <button class="small" onclick="chRename()">Rename</button><button class="small" onclick="chDup(this)">Duplicate</button><button class="small bad" onclick="chDelete()">Delete</button></div>
    <div id="ch-job">${jobBox()}</div>
    <div class="ch-studio"><div class="ch-side card pad">${sideView(busy)}</div><div id="ch-center">${centerView(busy)}</div></div>`;
  wire();
}
function refreshCenter() { $('#ch-job').innerHTML = jobBox(); $('#ch-center').innerHTML = centerView(C.job && C.job.state === 'running'); wireCenter(); }

function sideView(busy) {
  const hints = Object.fromEntries((OPT ? OPT.slots[C.kind] : []).map(x => [x.key, x.hint]));
  const keys = Object.keys(hints);
  const r = C.render, loras = (OPT && OPT.loras[r.model]) || [];
  const dis = busy ? 'disabled' : '';
  return `<h3 style="margin-top:0">Idea</h3>
    <textarea id="ch-idea" style="min-height:64px" ${dis}>${esc(C.idea)}</textarea>
    <div class="row mt-s"><button class="small primary" id="ch-suggest" ${dis}>Fill in the details from the idea</button></div>
    ${C.kind === 'person' ? `<div class="row mt-s small">${C.photo ? `<img src="${esc(C.photo)}" style="width:44px;border-radius:6px"> started from a picture (${esc(C.rights.basis)})` : ''}<button class="small" id="ch-photo" ${dis}>${C.photo ? 'Change the picture' : 'Start from a picture'}</button></div>` : ''}
    <h3>Details</h3><div class="mute small">${C.gaps.length ? 'Fill these in: ' + C.gaps.map(esc).join(', ') + '. An image model invents what is not written.' : 'Every detail is written.'}</div>
    ${keys.map(k => `<label class="ch-slot ${C.gaps.includes(k) ? 'gap' : ''}" title="${esc(hints[k])}"><span>${esc(k)}</span><input data-slot="${k}" value="${esc(C.slots[k] || '')}" ${dis}></label>`).join('')}
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
    ${p.url && (p.how === 'draw' || p.how === 'edit') ? `<div class="row" style="margin-top:4px">${C.canon[p.view] === p.id ? '<b>Canon ✓</b>' : p.view === 'portrait' || p.view === 'body' || p.view === 'place' ? `<button class="small primary" data-canon="${p.id}" ${dis}>Use as canon</button>` : (p.approved ? '<b>Kept ✓</b>' : `<button class="small" data-canon="${p.id}" ${dis}>Keep</button>`)}</div>` : ''}</div>`;
  const section = (v, n) => `<div class="card pad mt"><div class="row"><h3 style="margin:0">${esc(OPT.views[v].label)}</h3>${C.canon[v] ? badge('done', 'canon') : ''}<span class="sp"></span>
      <select data-n="${v}" style="width:auto">${[1, 2, 4].map(k => `<option value="${k}" ${k === n ? 'selected' : ''}>${k} new</option>`).join('')}</select><button class="small primary" data-draw="${v}" ${dis}>Draw</button></div>
      <div class="ch-views mt-s">${pics(v).map(card).join('') || '<div class="mute small">nothing drawn yet</div>'}</div></div>`;
  const haveCanon = C.kind === 'person' && C.canon.portrait && C.canon.body;
  return `<div class="mute small" title="The text the image model gets for the subject">${esc(C.identity || 'Write the details on the left.')}</div>
    ${draw.map(v => section(v, 2)).join('')}
    ${C.kind === 'person' ? `<div class="card pad mt"><div class="row"><h3 style="margin:0">Character sheet</h3><span class="mute small">three-quarter, side and back views and six expressions, each made from the canon</span><span class="sp"></span>
      <button class="small primary" id="ch-sheet" ${dis} ${haveCanon ? '' : 'disabled title="Approve a portrait and a full-body picture first"'}>Make the sheet</button></div>
      <div class="ch-views mt-s">${sheet.flatMap(v => pics(v).slice(0, 1).map(card)).join('') || '<div class="mute small">' + (haveCanon ? 'not made yet' : 'Approve a portrait and a full-body picture first.') + '</div>'}</div></div>` : ''}`;
}

window.chZoom = url => dialog({title: 'Picture', html: `<img src="${esc(url)}" style="max-width:100%;max-height:72vh;display:block;margin:auto;border-radius:8px">`, buttons: [{label: 'Close', value: true, primary: true}]});
window.chRename = async () => { const t = await textDlg('Rename', 'Name', C.name); if (t) await patch({name: t}); };
window.chDup = btn => act(btn, async () => { const c = await call('/' + CID + '/duplicate', {method: 'POST'}); location.hash = '#/character/' + c.id; return true; }, 'Copied');
window.chDelete = async () => { if (await confirmDlg('Delete this character', 'Its pictures are deleted too. Shorts that used it keep their own pictures.', 'Delete', true)) { await act(null, () => call('/' + CID, {method: 'DELETE'})); location.hash = '#/characters'; } };

async function suggest(btn) {
  const idea = ($('#ch-idea') || {}).value || C.idea;
  await act(btn, async () => { C = await call('/' + CID + '/suggest', {method: 'POST', json: {idea}}); render(); return true; }, 'Details written: check them, then draw');
}

function wire() {
  const on = (sel, fn) => { const e = document.querySelector(sel); if (e) e.onclick = () => fn(e); };
  on('#ch-suggest', b => suggest(b));
  on('#ch-photo', startFromPicture);
  const val = (sel, key, conv = x => x) => { const e = document.querySelector(sel); if (e) e.onchange = () => patch({[key]: conv(e.value)}); };
  val('#ch-idea', 'idea'); val('#ch-pers', 'personality'); val('#ch-notes', 'notes'); val('#ch-tags', 'tags', v => v.split(','));
  document.querySelectorAll('[data-slot]').forEach(e => e.onchange = () => { const slots = {...C.slots}; slots[e.dataset.slot] = e.value; patch({slots}); });
  const renderPatch = async (change) => { await act(null, async () => { C = await call('/' + CID, {method: 'PATCH', json: {render: {...C.render, ...change}}}); render(); return true; }); render(); };
  const st = document.querySelector('#ch-style'); if (st) st.onchange = () => renderPatch({style: st.value, loras: OPT.styles[st.value].loras});
  const md = document.querySelector('#ch-model'); if (md) md.onchange = () => renderPatch({model: md.value, loras: []});
  document.querySelectorAll('[data-lora-s]').forEach(e => e.onchange = () => renderPatch({loras: C.render.loras.map((l, i) => i === +e.dataset.loraS ? {...l, strength: +e.value} : l)}));
  document.querySelectorAll('[data-lora-x]').forEach(e => e.onclick = () => renderPatch({loras: C.render.loras.filter((_, i) => i !== +e.dataset.loraX)}));
  const add = document.querySelector('#ch-lora-add');
  if (add) add.onchange = () => { if (!add.value) return; const l = OPT.loras[C.render.model].find(x => x.name === add.value); renderPatch({loras: [...C.render.loras, {name: l.name, strength: Math.min(l.strength, 0.8)}].slice(0, 4)}); };
  wireCenter();
}
function wireCenter() {
  document.querySelectorAll('[data-draw]').forEach(b => b.onclick = () => post(b, '/generate', {views: [b.dataset.draw], n: +document.querySelector(`[data-n="${b.dataset.draw}"]`).value}, 'Drawing started'));
  document.querySelectorAll('[data-canon]').forEach(b => b.onclick = () => act(b, async () => { await call('/item/' + b.dataset.canon + '/canon', {method: 'POST'}); await window._chLoad(true); return true; }, 'Saved'));
  const sh = document.querySelector('#ch-sheet'); if (sh) sh.onclick = () => post(sh, '/sheet', {}, 'Sheet started');
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
