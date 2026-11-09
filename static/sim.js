/* Stories page (#/sim, #/sim/<id>): the story simulator (docs/PLAN_simulation.md). Uses the helpers of index.html ($, api, esc, act, toast, dialog, confirmDlg, textDlg, badge, bar, fmtDate, hd). */
(() => {
const STYLE = `
.sm-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px;align-items:start}
@media(max-width:900px){.sm-grid{grid-template-columns:1fr}}
.sm-side{position:sticky;top:64px;display:grid;gap:12px;max-height:calc(100vh - 80px);overflow:auto}
.sm-ch h3{margin:0 0 2px;font-size:17px}
.sm-prose p{margin:0 0 10px;line-height:1.65;font-size:15px}
.sm-chip{display:inline-block;font-size:12px;padding:2px 9px;border-radius:99px;border:1px solid var(--line);margin:2px 4px 2px 0;background:var(--bg)}
.sm-chip.great,.sm-chip.success{border-color:var(--ok);color:var(--ok)}.sm-chip.partial{border-color:var(--warn);color:var(--warn)}.sm-chip.fail,.sm-chip.disaster{border-color:var(--bad);color:var(--bad)}
.sm-opt{display:block;width:100%;text-align:left;margin:6px 0;padding:10px 12px;line-height:1.4}
.sm-opt small{color:var(--mute);display:block}
.sm-risk-high{border-left:4px solid var(--bad)}.sm-risk-medium{border-left:4px solid var(--warn)}.sm-risk-low{border-left:4px solid var(--ok)}
.sm-dock{border:2px solid var(--accent)}
.sm-banner{padding:9px 14px;border-radius:10px;margin:10px 0;background:var(--infobg);color:var(--info)}
.sm-banner.bad{background:var(--badbg);color:var(--bad)}.sm-banner.warn{background:var(--warnbg);color:var(--warn)}
.sm-kv{display:grid;grid-template-columns:130px 1fr;gap:6px 10px;align-items:start;margin:6px 0}
.sm-kv label{color:var(--mute);font-size:12px;padding-top:7px}
.sm-kv input,.sm-kv textarea,.sm-kv select{width:100%}
.sm-state div{margin:5px 0;font-size:13px}.sm-state b{font-weight:600}
.sm-dead{text-decoration:line-through;color:var(--mute)}
.sm-panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:8px 0}
.sm-panels figure{margin:0}.sm-panels img{width:100%;border-radius:8px;display:block;background:var(--line);min-height:90px}
.sm-panels figcaption{font-size:12px;color:var(--mute);margin-top:2px}
.sm-read{max-width:720px;margin:0 auto}.sm-read h2{margin-top:34px}
.sm-tag{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
details.sm-d summary{cursor:pointer;color:var(--mute);font-size:12px}
.sm-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
.sm-card{padding:12px 14px}.sm-card h4{margin:0 0 4px;font-size:14px}
`;
let el = null, my = 0, D = null, SID = '', TAB = 'story', poll = null, opening = false;
const kindName = {items: 'Items', meter: 'Meter', clock: 'Clock', relation: 'Relationship', location: 'Locations', knowledge: 'Secrets', flag: 'Yes/no fact'};
const GROUPS = [['hard', 'Hard rules (never broken)'], ['world', 'World rules'], ['tone', 'Tone and pacing'], ['style', 'Style']];

function css() { if (!document.getElementById('sm-css')) { const s = document.createElement('style'); s.id = 'sm-css'; s.textContent = STYLE; document.head.append(s); } }
const live = () => el && document.body.contains(el) && my === route_id;
const paras = t => esc(t || '').split(/\n+/).filter(Boolean).map(p => `<p>${p}</p>`).join('');
const hash = (id, tab) => { location.hash = '#/sim' + (id ? '/' + id : '') + (tab ? '?t=' + tab : ''); };

/* ───────── library ───────── */
window.viewSim = async function () {
  css(); my = route_id; el = $('#app'); D = null; SID = '';
  el.innerHTML = '<div class="skel"></div>';
  let r; try { r = await api('/sim'); } catch (e) { el.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  if (!live()) return;
  el.innerHTML = `<div class="row mb"><h2 style="margin:0">Stories</h2><span class="sp"></span><label class="small mute">Import <input type="file" id="sm-imp" accept=".json" hidden></label><button class="small" id="sm-impb">Import a story file</button></div>
  <div class="card pad mb"><b>New story</b><p class="mute small" style="margin:4px 0 8px">Write the idea in a few sentences. The AI will propose the cast, the world, the things to keep track of and the rules; you edit them, then start.</p>
    <textarea id="sm-idea" placeholder="For example: A night-shift salesman is alone in a supermarket when a zombie outbreak begins. He must survive until dawn using only what the store holds."></textarea>
    <div class="row mt-s"><label class="small mute">Template <select id="sm-tpl">${r.templates.map(t => `<option value="${esc(t.id)}" title="${esc(t.blurb)}">${esc(t.name)}</option>`).join('')}</select></label><span class="sp"></span><button class="primary" id="sm-new">Create and set up with AI</button></div></div>
  <div class="sm-cards">${r.stories.length ? r.stories.map(s => `<div class="card sm-card click" onclick="location.hash='#/sim/${s.id}'" style="cursor:pointer"><h4>${esc(s.title)}</h4>
    <div class="small mute" style="margin-bottom:6px">${esc(s.idea.slice(0, 140))}${s.idea.length > 140 ? '…' : ''}</div>
    <div class="row small">${badge(s.status === 'running' ? 'good' : 'warn', s.status === 'setup' ? 'setting up' : 'in progress')}<span>${s.chapters} chapters</span>${s.bytes ? `<span class="mute">${(s.bytes / 1048576).toFixed(1)} MB of pictures</span>` : ''}${s.running ? '<span class="spin"></span>' : ''}<span class="sp"></span><span class="mute">${fmtDate(s.updated_at)}</span></div></div>`).join('') : '<p class="mute">No stories yet. Write an idea above.</p>'}</div>`;
  $('#sm-new').onclick = async e => {
    const idea = $('#sm-idea').value.trim(); if (!idea) { toast('Write the idea first', {bad: true}); return; }
    const made = await act(e.target, () => api('/sim', {method: 'POST', json: {idea, template_id: $('#sm-tpl').value === 'tp-free' ? '' : $('#sm-tpl').value}}));
    if (!made) return;
    try { await api(`/sim/${made.id}/seed/all`, {method: 'POST', json: {}}); } catch (er) { toast(er.message, {bad: true}); }
    hash(made.id, 'setup');
  };
  $('#sm-impb').onclick = () => $('#sm-imp').click();
  $('#sm-imp').onchange = async ev => {
    const f = ev.target.files[0]; if (!f) return;
    try { const m = await api('/sim/import', {method: 'POST', json: JSON.parse(await f.text())}); toast('Imported'); hash(m.id, 'setup'); } catch (er) { toast(er.message, {bad: true}); }
  };
};

/* ───────── one story ───────── */
window.viewSimStory = async function (id) {
  css(); my = route_id; el = $('#app'); SID = id;
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  TAB = q.get('t') || LS.get('sm-tab-' + id, 'story');
  el.innerHTML = '<div class="skel"></div><div class="skel"></div>';
  await load(true);
};

async function load(first) {
  if (!live()) return;
  try { D = await api('/sim/' + SID); } catch (e) { el.innerHTML = `<div class="errbox">${esc(e.message)} <a href="#/sim">Back to stories</a></div>`; return; }
  if (!live()) return;
  if (first && D.project.status === 'setup' && !D.chapters.length && TAB === 'story') TAB = 'setup';
  draw();
  if (D.run && D.run.state === 'running') watch();
}

function watch() {
  clearTimeout(poll);
  const my0 = my;
  const tick = async () => {
    if (!live() || my0 !== my) return;
    let r; try { r = await api(`/sim/${SID}/run`); } catch { poll = setTimeout(tick, 4000); return; }
    const b = document.getElementById('sm-run');
    if (r.state === 'running') {
      if (b) b.innerHTML = runBanner(r);
      poll = setTimeout(tick, 2500);
    } else {
      if (r.state === 'error') toast(r.error || 'The step failed', {bad: true});
      else if (r.note) toast(r.note);
      await load();
    }
  };
  poll = setTimeout(tick, 1500);
}

const STAGE = {gather: 'reading the situation', plan: 'planning', minds: 'what the others want', resolve: 'rolling the dice', delta: 'working out what changes', write: 'writing', referee: 'checking the rules', archive: 'remembering and offering options'};
function runBanner(r) {
  return `<span class="spin"></span> ${esc(r.label || 'working')}… <span class="mute small">${r.elapsed_s ? hd(r.elapsed_s) : ''}</span> <span class="sp"></span><button class="small bad" onclick="window.smStop()">Stop</button>`;
}
window.smStop = async () => { await act(null, () => api(`/sim/${SID}/stop`, {method: 'POST'}), 'Will stop after this step'); };

async function run(btn, path, body, label) {
  const r = await act(btn, () => api(`/sim/${SID}${path}`, {method: 'POST', json: body || {}}));
  if (r === undefined) return;
  toast(label || 'Started');
  await load();
}

function draw() {
  if (!live()) return;
  const p = D.project, running = D.run && D.run.state === 'running';
  const tabs = [['story', 'Story'], ['setup', 'Setup'], ['read', 'Read']];
  el.innerHTML = `<div class="row"><a href="#/sim">‹ Stories</a><h2 style="margin:0 0 0 8px;cursor:pointer" id="sm-title" title="Click to rename">${esc(p.title)}</h2><span class="sp"></span>
    ${badge(p.status === 'running' ? 'good' : 'warn', p.status === 'setup' ? 'setting up' : 'in progress')}<span class="small mute">${D.chapters.length} chapters · ${D.reading_minutes} min read</span></div>
  <div class="small mute" style="margin:2px 0 0">${esc(p.idea)}</div>
  <div id="sm-run" class="sm-banner" ${running ? '' : 'hidden'}>${running ? runBanner(D.run) : ''}</div>
  ${D.failed && !running ? `<div class="sm-banner bad row">A chapter stopped at "${esc(STAGE[D.failed.stage] || D.failed.stage || 'a step')}"${D.failed.error ? ': ' + esc(D.failed.error) : ' (stopped)'}. Finished steps are kept.<span class="sp"></span><button class="small primary" id="sm-retry">Retry from this step</button></div>` : ''}
  ${help()}
  <div class="tabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${k === TAB ? 'on' : ''}">${l}</button>`).join('')}</div><div id="sm-body"></div>`;
  $('#sm-title').onclick = async () => { const t = await textDlg('Rename the story', 'Title', p.title); if (t) { await act(null, () => api('/sim/' + SID, {method: 'PATCH', json: {title: t}})); load(); } };
  el.querySelectorAll('.tabs button').forEach(b => b.onclick = () => { TAB = b.dataset.t; LS.set('sm-tab-' + SID, TAB); draw(); });
  const rb = document.getElementById('sm-retry'); if (rb) rb.onclick = e => run(e.target, `/chapters/${D.failed.id}/retry`, {}, 'Retrying');
  ({story: drawStory, setup: drawSetup, read: drawRead})[TAB]();
}

function help() {
  return `<details class="card pad mt-s sm-d"><summary><b>How this page works</b></summary><div class="small" style="margin-top:8px;line-height:1.6">
    <p><b>The idea.</b> You write a few sentences. The AI proposes a world, a cast, <i>things to keep track of</i> (items, meters, clocks, relationships, secrets…) and rules. Everything is editable in <b>Setup</b>, before and during the story. This works for any kind of story, not only survival.</p>
    <p><b>A chapter</b> is about 350 words. For each one the AI plans the scene, <b>dice decide risky acts</b> (you see the roll; you can turn dice off in Setup), the AI works out what changes (items used, people hurt, clocks moving), a writer tells it, a checker compares it with your rules, and options for what happens next are offered. If a rule is broken twice, the chapter is kept with a red note; you can accept it or rewrite it.</p>
    <p><b>You steer</b> by clicking an option, writing your own action, pressing <b>Let it run</b> (the AI picks), or <b>Auto-run</b> several chapters (it stops on a death, a full clock, a broken rule or when you press Stop). <b>Add instruction</b> any time: an outside event, a limit, a twist or a steer, to happen next chapter, in some chapters, when something becomes true, or at a story time. Each instruction is used once on the line of the story it was added to.</p>
    <p><b>Rules and things tracked</b> keep the story honest: the AI may only use items that exist in the world card or that are made from items already used, the dead stay dead, and changes it proposes that do not fit are refused (shown under "What changed").</p>
    <p><b>Change your mind.</b> <i>Rewrite</i> a chapter with an instruction or roll <i>new dice</i>: the old version stays as another branch you can switch back to. <i>Edit text</i> lets you change the words; the AI can read your edit and propose how the state should change, and later chapters are marked as written before the edit. Only the last chapter of a line can be deleted.</p>
    <p><b>Pictures</b> are optional: press <i>Paint this chapter</i> (or tick "Paint every chapter automatically" in Setup). They are cinematic paintings drawn from text. Each person and place gets a reference painting first, so faces and places stay alike; you can repaint, edit, replace with your own picture or remove any of them. Changing a person's look marks their pictures "old".</p>
    <p><b>Reading and publishing.</b> The <b>Read</b> tab shows the story as a book; download it as Markdown, as a zip with pictures in order, or as chapter data for turning chapters into videos later. <i>Export setup</i> / <i>Save as template</i> / <i>Duplicate</i> in Setup let you reuse a story as a starting point for another.</p>
    <p class="mute">Steps run one at a time (the local model serves one request at a time), so a chapter takes a few minutes. You can leave this page; the work continues and the page picks it up when you come back.</p></div></details>`;
}

/* ───────── story tab ───────── */
function stateHtml(st) {
  const tr = D.trackers.filter(t => t.active);
  const rows = tr.map(t => {
    const v = st.trackers[t.id]; let body = '';
    if (t.kind === 'items') body = Object.entries(v || {}).map(([n, i]) => `${esc(n)} ×${i.qty}${i.at ? ` <span class="mute">(${esc(i.at)})</span>` : ''}`).join('<br>') || '<span class="mute">none</span>';
    else if (t.kind === 'meter') body = `${bar((v - t.min) / (t.max - t.min) * 100, v <= (t.danger_below ?? -1e9) || v >= (t.danger_above ?? 1e9) ? 'fail' : '')} <span class="small">${(+v).toFixed(1).replace(/\.0$/, '')}/${t.max} ${esc(t.unit || '')}</span>`;
    else if (t.kind === 'clock') body = Array.from({length: t.max}, (_, i) => `<span style="font-size:15px;color:${i < v ? 'var(--bad)' : 'var(--line)'}">●</span>`).join(' ') + ` <span class="small mute">${esc(t.rises || '')}</span>`;
    else if (t.kind === 'relation') body = `${esc(t.a)} ↔ ${esc(t.b)}: trust ${v.trust}, tension ${v.tension}`;
    else if (t.kind === 'location') body = Object.entries(v.at || {}).map(([w, p]) => `${esc(w)} → ${esc(p)}`).join('<br>') + (v.locked && v.locked.length ? `<br><span class="mute">locked: ${v.locked.map(esc).join(', ')}</span>` : '');
    else if (t.kind === 'knowledge') body = Object.entries(v || {}).map(([s, w]) => `${esc(s)}: ${w.length ? w.map(esc).join(', ') : '<span class="mute">nobody</span>'}`).join('<br>');
    else body = v ? 'yes' : 'no';
    return `<div><b>${esc(t.name)}</b> <span class="sm-tag">${kindName[t.kind]}</span><br>${body}</div>`;
  }).join('');
  const people = Object.entries(st.entities || {}).map(([n, e]) => `<span class="${e.alive ? '' : 'sm-dead'}">${esc(n)}</span>${e.status && e.alive ? ` <span class="mute small">(${esc(e.status)})</span>` : ''}`).join(' · ');
  return `<div class="card pad sm-state"><b>State</b> <span class="small mute">${esc(st.time || '')}</span>${D.pressure.length ? `<div class="err small">${D.pressure.map(p => esc(p.text)).join('<br>')}</div>` : ''}${rows}<div>${people}</div></div>`;
}

function sideHtml() {
  const pend = D.directives.filter(d => d.pending && d.status !== 'cancelled');
  const th = D.threads;
  const rules = D.guidelines.filter(g => g.enabled);
  return `<div class="sm-side">${stateHtml(D.state)}
    <div class="card pad"><div class="row"><b>Instructions waiting</b><span class="sp"></span><button class="small" id="sm-adddir">+ Add</button></div>
      ${pend.length ? pend.map(d => `<div class="small" style="margin:6px 0"><span class="sm-tag">${d.kind} · ${timingText(d.timing)}</span><br>${esc(d.text)} <button class="link" data-cdir="${d.id}" title="Cancel">✕</button></div>`).join('') : '<div class="small mute">None. Add an event, a limit or a twist at any time.</div>'}</div>
    ${th.length ? `<div class="card pad"><b>Open threads</b>${th.map(t => `<div class="small" style="margin:4px 0">• ${esc(t.text)}</div>`).join('')}</div>` : ''}
    <div class="card pad"><b>Rules in force</b> <span class="small mute">v${D.project.settings.rules_version}</span>${rules.slice(0, 12).map(g => `<div class="small" style="margin:3px 0"><span class="sm-tag">${g.grp}</span> ${esc(g.text)}</div>`).join('')}</div></div>`;
}

function timingText(t) {
  return t.mode === 'next' ? 'next chapter' : t.mode === 'in' ? `chapter ${t.from + t.chapters}` : t.mode === 'story_time' ? `at story time: ${t.at}` : t.tracker ? `when ${t.tracker} ${t.op || 'full'}` : `when: ${t.condition}`;
}

function chapterHtml(c, i) {
  const last = i === D.chapters.length - 1;
  const f = c.flags || {};
  const fired = c.fired.map(id => D.directives.find(d => d.id === id)).filter(Boolean);
  const flagsHtml = [f.rule_break ? `<div class="sm-banner bad">A rule may be broken here: ${f.rule_break.map(v => `"${esc(v.quote)}" → ${esc(v.fix)}`).join('; ')} <button class="small" data-accept="${c.id}">Accept anyway</button></div>` : '',
    f.stale ? '<div class="sm-banner warn">Written before an earlier chapter was edited.</div>' : '',
    last && f.rules_version && f.rules_version < D.project.settings.rules_version ? '<div class="sm-banner warn">The rules changed after this chapter; the next chapter follows the new rules.</div>' : '',
    f.reread ? `<div class="sm-banner">Your edit: ${esc(f.reread.note || 'no change to the state')} ${f.reread.preview.map(x => `<span class="sm-chip">${esc(x.text)}</span>`).join('')} <button class="small primary" data-apply="${c.id}">Apply to the state</button></div>` : ''].join('');
  const panels = c.panels.map(p => `<figure>${p.file ? `<img loading="lazy" src="/api/sim/file/${SID}/${esc(p.capfile || p.file)}?v=${esc(p.media_id)}" alt="">` : '<div style="height:120px;background:var(--line);border-radius:8px"></div>'}
    <figcaption>${p.old ? '<span class="badge b-warn">old</span> ' : ''}${p.uploaded ? '<span class="badge">your picture</span> ' : ''}${esc(p.caption || '')}</figcaption>
    <div class="row" style="gap:4px"><button class="small" data-pre="${c.id}:${p.n}">Redraw</button><button class="small" data-ped="${c.id}:${p.n}">Edit</button><button class="small" data-pup="${c.id}:${p.n}">Upload</button><button class="small bad" data-pdel="${c.id}:${p.n}">✕</button></div></figure>`).join('');
  const paintErr = f.paint_error ? `<div class="sm-banner warn">The pictures could not be painted: ${esc(f.paint_error)}</div>` : '';
  return `<div class="card pad sm-ch mt" id="ch-${c.id}"><div class="row"><h3>Chapter ${c.idx}: ${esc(c.title || '(untitled)')}</h3><span class="sp"></span>
      ${c.siblings.length ? `<select data-branch="${c.id}" title="Other versions of this chapter">${c.siblings.map(s => `<option value="${s.id}" ${s.id === c.id ? 'selected' : ''}>${esc(s.label)}${s.status === 'failed' ? ' (failed)' : ''}</option>`).join('')}</select>` : ''}
      <span class="small mute">${esc(c.story_time || '')}</span></div>
    <div class="small mute">${esc(c.plan.beat || '')}${c.focus.length ? ' · following ' + c.focus.map(esc).join(', ') : ''}${c.chosen && c.chosen.label ? '' : ''}</div>
    ${flagsHtml}${paintErr}${panels ? `<div class="sm-panels">${panels}</div>` : ''}
    <div class="sm-prose mt-s">${paras(c.prose)}</div>
    ${c.rolls.length ? `<div>${c.rolls.map(r => `<span class="sm-chip ${r.tier}" title="${esc((r.why || []).join(', '))}">${esc(r.act)}: ${r.dice_off ? 'success' : `${r.die}${r.mod >= 0 ? '+' : ''}${r.mod} vs ${r.target} → ${r.tier}`}</span>`).join('')}</div>` : ''}
    ${fired.length ? `<div>${fired.map(d => `<span class="sm-chip" style="border-color:var(--accent)">⚡ ${esc(d.kind)}: ${esc(d.text)}</span>`).join('')}</div>` : ''}
    <details class="sm-d mt-s"><summary>What changed${c.dropped.length ? ` · ${c.dropped.length} refused` : ''} · summary</summary>
      ${c.applied.length ? `<div class="small">${c.applied.map(a => `<span class="sm-chip">${esc(a.text)}</span>`).join('')}</div>` : '<div class="small mute">No change to the state.</div>'}
      ${c.dropped.length ? `<div class="small mute" style="margin-top:4px">Refused by the rules: ${c.dropped.map(d => `${esc(d.op)} ${esc(d.target || '')} (${esc(d.why)})`).join('; ')}</div>` : ''}
      <div class="small" style="margin-top:6px"><b>Summary:</b> ${esc(c.summary)}</div></details>
    <div class="row mt-s">${last && D.project.status !== 'setup' ? '' : ''}<button class="small" data-rewrite="${c.id}">Rewrite…</button><button class="small" data-reroll="${c.id}" title="Same plan, new dice">New dice</button>
      <button class="small" data-edit="${c.id}">Edit text</button><button class="small" data-paint="${c.id}">${c.panels.some(p => p.file) ? 'Repaint' : 'Paint this chapter'}</button>
      ${last ? `<button class="small bad" data-delch="${c.id}">Delete chapter</button>` : ''}</div></div>`;
}

function dockHtml() {
  const head = D.chapters[D.chapters.length - 1];
  const chars = Object.entries(D.state.entities || {}).filter(([, e]) => e.alive).map(([n]) => n);
  return `<div class="card pad sm-dock mt"><b>What happens next?</b>
    ${head.options.map(o => `<button class="sm-opt sm-risk-${o.risk}" data-opt="${o.id}"><b>${esc(o.who)}:</b> ${esc(o.label)}<small>${esc(o.hint || '')} · ${o.risk} risk</small></button>`).join('')}
    <div class="row mt-s"><select id="sm-who">${chars.map(c => `<option>${esc(c)}</option>`).join('')}</select><input id="sm-text" style="flex:1;min-width:200px" placeholder="…or write what they do (any action you like)"><button id="sm-go" class="primary">Do this</button></div>
    <div class="row mt-s"><button id="sm-let" title="The AI picks the most in-character option">Let it run</button><span class="small mute">Auto-run</span><input type="number" id="sm-n" value="3" min="1" max="10" style="width:60px"><button id="sm-auto">chapters</button><span class="sp"></span><button id="sm-dir2">+ Add instruction</button></div></div>`;
}

function drawStory() {
  const b = $('#sm-body');
  if (!D.chapters.length) {
    const miss = D.missing;
    b.innerHTML = `<div class="card pad mt"><h3 style="margin-top:0">${D.project.status === 'setup' ? 'Ready to start?' : 'No chapters yet'}</h3>${miss.length ? `<div class="sm-banner warn">Not ready: ${miss.map(esc).join('; ')}. Fix it in Setup. <button class="small" id="sm-gosetup">Open Setup</button></div>` : '<p class="mute">The setup looks complete. Chapter 1 is written from the starting scene.</p>'}
      <button class="primary" id="sm-start" ${miss.length ? 'disabled' : ''}>Start the story</button></div>`;
    $('#sm-start').onclick = e => run(e.target, '/start', {}, 'Writing chapter 1');
    const gsu = $('#sm-gosetup'); if (gsu) gsu.onclick = () => { TAB = 'setup'; LS.set('sm-tab-' + SID, 'setup'); draw(); };
    return;
  }
  b.innerHTML = `<div class="sm-grid"><div>${D.chapters.map(chapterHtml).join('')}${D.chapters[D.chapters.length - 1].status === 'done' ? dockHtml() : ''}</div>${sideHtml()}</div>`;
  wireStory();
}

function wireStory() {
  const busy = D.run && D.run.state === 'running';
  const on = (sel, fn) => el.querySelectorAll(sel).forEach(fn);
  on('[data-opt]', b => b.onclick = () => busy ? toast('A step is running', {bad: true}) : run(b, '/chapters', {kind: 'option', option_id: b.dataset.opt}, 'Writing the next chapter'));
  const go = $('#sm-go'); if (go) go.onclick = () => { const t = $('#sm-text').value.trim(); if (!t) { toast('Write what they do', {bad: true}); return; } run(go, '/chapters', {kind: 'text', text: t, who: $('#sm-who').value}, 'Writing the next chapter'); };
  const let_ = $('#sm-let'); if (let_) let_.onclick = () => run(let_, '/chapters', {kind: 'auto'}, 'Letting it run');
  const au = $('#sm-auto'); if (au) au.onclick = () => run(au, '/auto', {n: +$('#sm-n').value || 3}, 'Auto-run started');
  [$('#sm-dir2'), $('#sm-adddir')].forEach(b => { if (b) b.onclick = () => directiveDialog(); });
  on('[data-cdir]', b => b.onclick = async () => { if (await confirmDlg('Cancel this instruction?', 'It will not be used.', 'Cancel it')) { await act(null, () => api(`/sim/${SID}/directives/${b.dataset.cdir}`, {method: 'DELETE'})); load(); } });
  on('[data-rewrite]', b => b.onclick = async () => { const t = await textDlg('Rewrite this chapter', 'What should change? (the old version stays as another branch)', '', true); if (t && t.trim()) run(b, `/chapters/${b.dataset.rewrite}/rewrite`, {instruction: t}, 'Rewriting'); });
  on('[data-reroll]', b => b.onclick = () => run(b, `/chapters/${b.dataset.reroll}/reroll`, {}, 'Rolling again'));
  on('[data-edit]', b => b.onclick = () => editChapter(b.dataset.edit));
  on('[data-accept]', b => b.onclick = async () => { await act(b, () => api(`/sim/${SID}/chapters/${b.dataset.accept}/accept`, {method: 'POST'})); load(); });
  on('[data-apply]', b => b.onclick = async () => { await act(b, () => api(`/sim/${SID}/chapters/${b.dataset.apply}/reread/apply`, {method: 'POST'}), 'State updated'); load(); });
  on('[data-delch]', b => b.onclick = async () => { if (await confirmDlg('Delete this chapter?', 'Its pictures go too. This cannot be undone.', 'Delete', true)) { await act(null, () => api(`/sim/${SID}/chapters/${b.dataset.delch}`, {method: 'DELETE'})); load(); } });
  on('[data-branch]', s => s.onchange = async () => { if (s.value !== s.dataset.branch) { await act(null, () => api(`/sim/${SID}/head`, {method: 'POST', json: {chapter_id: s.value}}), 'Showing that version'); load(); } });
  on('[data-paint]', b => b.onclick = () => run(b, `/chapters/${b.dataset.paint}/paint`, {}, 'Painting'));
  const split = s => { const i = s.lastIndexOf(':'); return [s.slice(0, i), +s.slice(i + 1)]; };
  on('[data-pre]', b => b.onclick = async () => { const [cid, n] = split(b.dataset.pre); const t = await textDlg('Redraw this picture', 'Describe what should be seen (leave empty to draw the planned scene again)', '', true); if (t !== null) run(b, `/chapters/${cid}/panels/${n}/redraw`, {prompt: t}, 'Painting'); });
  on('[data-ped]', b => b.onclick = async () => {
    const [cid, n] = split(b.dataset.ped); const p = D.chapters.find(c => c.id === cid).panels.find(x => x.n === n);
    const v = await dialog({title: 'Edit this picture', html: `<label class="f">Caption (up to 12 words)<input id="pe-c" value="${esc(p.caption || '')}"></label><label class="f">What is seen<textarea id="pe-a">${esc(p.action || '')}</textarea></label><label class="f">Light and mood<input id="pe-m" value="${esc(p.mood || '')}"></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({caption: l.querySelector('#pe-c').value, action: l.querySelector('#pe-a').value, mood: l.querySelector('#pe-m').value})}]});
    if (!v) return;
    const changedScene = v.action !== (p.action || '') || v.mood !== (p.mood || '');
    await act(null, () => api(`/sim/${SID}/chapters/${cid}/panels/${n}`, {method: 'PATCH', json: v}), 'Saved');
    if (changedScene && await confirmDlg('Redraw it now?', 'You changed what is seen, so the picture is now out of date.', 'Redraw')) run(null, `/chapters/${cid}/panels/${n}/redraw`, {}, 'Painting'); else load();
  });
  on('[data-pup]', b => b.onclick = () => {
    const [cid, n] = split(b.dataset.pup); const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*';
    inp.onchange = async () => { const f = inp.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
      await act(null, () => api(`/sim/${SID}/chapters/${cid}/panels/${n}/upload`, {method: 'POST', form: fd}), 'Picture replaced'); load(); };
    inp.click();
  });
  on('[data-pdel]', b => b.onclick = async () => { const [cid, n] = split(b.dataset.pdel); if (await confirmDlg('Remove this picture?', 'It is deleted from the chapter.', 'Remove', true)) { await act(null, () => api(`/sim/${SID}/chapters/${cid}/panels/${n}`, {method: 'DELETE'})); load(); } });
}

async function editChapter(cid) {
  const c = D.chapters.find(x => x.id === cid);
  const v = await dialog({title: 'Edit this chapter', html: `<label class="f">Title<input id="ed-t" value="${esc(c.title)}"></label><label class="f">Text<textarea id="ed-p" style="min-height:300px">${esc(c.prose)}</textarea></label>
    <p class="small mute">If you change the story itself, the AI can read your edit and propose how the state should change (you approve it). Chapters after this one are marked as written before the edit.</p>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({title: l.querySelector('#ed-t').value, prose: l.querySelector('#ed-p').value})}]});
  if (!v) return;
  const r = await act(null, () => api(`/sim/${SID}/chapters/${cid}`, {method: 'PATCH', json: v}));
  if (!r) return;
  if (r.edited_prose) { if (await confirmDlg('Read your edit?', 'Let the AI check what your edit changes in the state (items, people, clocks). You approve before anything changes.', 'Read it')) await run(null, `/chapters/${cid}/reread`, {}, 'Reading your edit'); else load(); } else load();
}

async function directiveDialog() {
  const trackers = D.trackers.filter(t => ['clock', 'meter', 'flag'].includes(t.kind));
  const pr = dialog({title: 'Add an instruction to the story', html: `<p class="small mute">It can be an outside event (raiders arrive), a limit (no more food after day 2), a twist, or a steer toward somewhere. It is used once, on this line of the story.</p>
    <label class="f">What<textarea id="di-t" placeholder="Raiders arrive at the loading bay and demand supplies"></textarea></label>
    <label class="f">Kind<select id="di-k"><option value="event">Event</option><option value="constraint">Limit</option><option value="twist">Twist</option><option value="steer">Steer</option></select></label>
    <label class="f">When<select id="di-m"><option value="next">In the next chapter</option><option value="in">In a number of chapters</option><option value="when">When something happens</option><option value="story_time">At a story time</option></select></label>
    <div id="di-x"></div>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Add', primary: true, validate: v => !v.text.trim() ? 'Write the instruction' : (v.timing.mode === 'when' && !v.timing.condition && !v.timing.tracker ? 'Say when' : v.timing.mode === 'story_time' && !v.timing.at ? 'Say the story time' : ''),
      collect: l => { const m = l.querySelector('#di-m').value; const t = {mode: m};
        if (m === 'in') t.chapters = +l.querySelector('#di-n').value || 1;
        if (m === 'when') { const tr = l.querySelector('#di-tr').value; if (tr) { t.tracker = tr; t.op = l.querySelector('#di-op').value; t.value = +l.querySelector('#di-val').value; } else t.condition = l.querySelector('#di-c').value; }
        if (m === 'story_time') t.at = l.querySelector('#di-at').value;
        return {text: l.querySelector('#di-t').value, kind: l.querySelector('#di-k').value, timing: t}; }}]});
  const sel = document.getElementById('di-m');
  if (sel) sel.onchange = () => {
    const m = sel.value;
    document.getElementById('di-x').innerHTML = m === 'in' ? '<label class="f">In how many chapters (1 = the next one)<input id="di-n" type="number" value="2" min="1"></label>'
      : m === 'when' ? `<label class="f">When this tracker<select id="di-tr"><option value="">(describe it instead)</option>${trackers.map(t => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join('')}</select></label>
        <div class="row"><select id="di-op"><option value="full">is full / reaches</option><option value="below">goes below</option><option value="above">goes above</option><option value="on">is on</option><option value="off">is off</option></select><input id="di-val" type="number" value="0" style="width:90px"></div>
        <label class="f">…or describe it<input id="di-c" placeholder="when the power fails"></label>`
      : m === 'story_time' ? '<label class="f">Story time<input id="di-at" placeholder="Day 2, dawn"></label>' : '';
  };
  const v = await pr;
  if (!v) return;
  const r = await act(null, () => api(`/sim/${SID}/directives`, {method: 'POST', json: v}), 'Instruction added');
  if (r) load();
}

/* ───────── setup tab ───────── */
function field(label, id, val, tag = 'input', extra = '') {
  return `<div class="sm-kv"><label>${esc(label)}</label>${tag === 'textarea' ? `<textarea id="${id}" ${extra}>${esc(val ?? '')}</textarea>` : `<input id="${id}" value="${esc(val ?? '')}" ${extra}>`}</div>`;
}

function drawSetup() {
  const p = D.project, st = p.settings, w = D.world, started = p.status !== 'setup';
  const ents = D.entities.filter(e => e.active);
  const chars = ents.filter(e => e.kind === 'character'), others = ents.filter(e => e.kind !== 'character');
  $('#sm-body').innerHTML = `
  <div class="card pad mt"><div class="row"><b>The idea and how it plays</b><span class="sp"></span><button id="sm-dup" class="small">Duplicate</button><button id="sm-tpls" class="small">Save as template</button><button id="sm-exps" class="small">Export setup</button><button id="sm-expf" class="small">Export everything</button></div>
    <textarea id="s-idea" style="margin-top:8px">${esc(p.idea)}</textarea>
    <div class="row mt-s" style="gap:16px">
      <label>Difficulty <select id="s-diff">${['gentle', 'fair', 'brutal'].map(x => `<option ${st.difficulty === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      <label><input type="checkbox" id="s-dice" ${st.dice ? 'checked' : ''}> Dice decide risky acts</label>
      <label>Words per chapter <input type="number" id="s-words" value="${st.chapter_words}" min="150" max="900" step="10"></label>
      <label><input type="checkbox" id="s-deep" ${st.deep ? 'checked' : ''}> Let the other characters plan too (slower)</label></div>
    <div class="row mt-s" style="gap:16px"><label><input type="checkbox" id="s-auto" ${st.auto_images ? 'checked' : ''}> Paint every chapter automatically</label>
      <label>Picture shape <select id="s-shape"><option value="wide" ${st.panel_shape === 'wide' ? 'selected' : ''}>wide (16:9)</option><option value="tall" ${st.panel_shape === 'tall' ? 'selected' : ''}>tall (9:16)</option></select></label>
      <label><input type="checkbox" id="s-cap" ${st.captions ? 'checked' : ''}> Captions on pictures</label><label>Image model <input id="s-img" value="${esc(st.image_model)}" placeholder="default" style="width:150px"></label>
      <span class="sp"></span><button class="primary" id="s-save">Save</button></div></div>

  <div class="card pad mt"><div class="row"><b>The world</b><span class="sp"></span><button class="small" id="w-redo">Redo with AI…</button></div>
    ${[['place', 'Place'], ['period', 'When'], ['tone', 'Tone'], ['pacing', 'Pacing'], ['start_scene', 'First scene'], ['start_time', 'Story clock at start']].map(([k, l]) => field(l, 'w-' + k, w[k])).join('')}
    ${field('What exists here', 'w-exists', w.exists, 'textarea', 'style="min-height:110px"')}<div class="row"><span class="small mute">The story may only use what exists here (items appear only from places that hold them).</span><span class="sp"></span><button id="w-save">Save the world</button></div></div>

  <div class="card pad mt"><div class="row"><b>Cast and places</b><span class="sp"></span>${started ? '' : '<button class="small" id="c-redo">Redo with AI…</button>'}<button class="small" id="c-addc">+ Character</button><button class="small" id="c-addp">+ Place</button></div>
    <div class="sm-cards mt-s">${[...chars, ...others].map(e => `<div class="card sm-card"><h4>${esc(e.name)} <span class="sm-tag">${e.kind}</span></h4><div class="small">${e.kind === 'character' ? `${esc(e.role || '')}${e.goal ? `<br><span class="mute">wants:</span> ${esc(e.goal)}` : ''}${e.fear ? `<br><span class="mute">fears:</span> ${esc(e.fear)}` : ''}` : esc(e.description || '')}</div>
      ${e.ref_file ? `<img src="/api/sim/file/${SID}/${esc(e.ref_file)}" style="width:100%;border-radius:8px;margin-top:6px" alt="">` : ''}${e.ref_old ? '<span class="badge b-warn">picture is out of date</span>' : ''}
      <div class="small mute" style="margin-top:4px">${esc((e.look || '').slice(0, 120))}${(e.look || '').length > 120 ? '…' : ''}</div><div class="row mt-s"><button class="small" data-ee="${e.id}">Edit</button><button class="small" data-ep="${e.id}">${e.ref_file ? 'Repaint' : 'Paint'}</button><button class="small bad" data-ed="${e.id}">${started ? 'Retire' : 'Delete'}</button></div></div>`).join('') || '<p class="mute">No one yet.</p>'}</div></div>

  <div class="card pad mt"><div class="row"><b>What the story keeps track of</b><span class="sp"></span>${started ? '' : '<button class="small" id="t-redo">Redo with AI…</button>'}<button class="small" id="t-add">+ Add</button></div>
    <div class="small mute">Items, meters, clocks, relationships, who is where, secrets and yes/no facts. The AI changes these as the story moves; the rules refuse changes that do not make sense.</div>
    ${D.trackers.filter(t => t.active).map(t => `<div class="row mt-s"><span class="badge">${kindName[t.kind]}</span><b>${esc(t.name)}</b><span class="small mute" style="flex:1">${esc(trackerSummary(t))}</span><button class="small" data-te="${t.id}">Edit</button><button class="small bad" data-td="${t.id}">Remove</button></div>`).join('') || '<p class="mute">Nothing yet.</p>'}</div>

  <div class="card pad mt"><div class="row"><b>Rules</b> <span class="small mute">version ${st.rules_version}</span><span class="sp"></span><button class="small" id="r-redo">Redo the AI's rules…</button><button class="small" id="r-more">Suggest more…</button><button class="small" id="r-add">+ Add a rule</button></div>
    ${GROUPS.map(([g, l]) => { const rs = D.guidelines.filter(x => x.grp === g); return `<div class="mt-s"><div class="sm-tag">${l}</div>${rs.map(x => `<div class="row" style="margin:3px 0"><input type="checkbox" data-rt="${x.id}" ${x.enabled ? 'checked' : ''} title="Use this rule"><span style="flex:1;${x.enabled ? '' : 'color:var(--mute)'}">${esc(x.text)}</span><span class="small mute">${x.origin === 'ai' ? 'AI' : 'you'}</span><button class="small" data-re="${x.id}">Edit</button><button class="small bad" data-rd="${x.id}">✕</button></div>`).join('') || '<div class="small mute">none</div>'}</div>`; }).join('')}</div>

  ${started ? '<div class="sm-banner">The story has started: changes here apply from the next chapter.</div>' : `<div class="card pad mt row"><span class="sp"></span>${D.missing.length ? `<span class="small err">Not ready: ${D.missing.map(esc).join('; ')}</span>` : ''}<button class="small" id="all-redo">Redo everything with AI</button><button class="primary" id="go-story" ${D.missing.length ? 'disabled' : ''}>Go to the story</button></div>`}`;
  wireSetup();
}

function trackerSummary(t) {
  const v = t.start;
  if (t.kind === 'items') return Object.entries(v || {}).map(([n, i]) => `${n} ×${i.qty}`).join(', ');
  if (t.kind === 'meter') return `${t.min}–${t.max} ${t.unit || ''}, starts at ${v}${t.owner ? ', ' + t.owner : ''}`;
  if (t.kind === 'clock') return `${t.max} steps, starts at ${v}${t.rises ? ', rises with ' + t.rises : ''}${t.ends ? ', when full: ' + t.ends : ''}`;
  if (t.kind === 'relation') return `${t.a} and ${t.b}`;
  if (t.kind === 'location') return Object.entries((v || {}).at || {}).map(([w, p]) => `${w} at ${p}`).join(', ');
  if (t.kind === 'knowledge') return Object.keys(v || {}).join(', ');
  return v ? 'starts on' : 'starts off';
}

function wireSetup() {
  const on = (sel, fn) => el.querySelectorAll(sel).forEach(fn);
  const patch = async (json, ok) => { const r = await act(null, () => api('/sim/' + SID, {method: 'PATCH', json}), ok || 'Saved'); if (r) load(); };
  $('#s-save').onclick = () => patch({idea: $('#s-idea').value, settings: {difficulty: $('#s-diff').value, dice: $('#s-dice').checked, chapter_words: +$('#s-words').value || 350, deep: $('#s-deep').checked,
    auto_images: $('#s-auto').checked, panel_shape: $('#s-shape').value, captions: $('#s-cap').checked, image_model: $('#s-img').value.trim()}});
  $('#w-save').onclick = () => patch({world: Object.fromEntries(['place', 'period', 'tone', 'pacing', 'start_scene', 'start_time', 'exists'].map(k => [k, $('#w-' + k).value]))});
  $('#sm-dup').onclick = async () => { const r = await act(null, () => api(`/sim/${SID}/duplicate?full=false`, {method: 'POST'}), 'Copied'); if (r) hash(r.id, 'setup'); };
  $('#sm-tpls').onclick = async () => { const n = await textDlg('Save as template', 'Template name', D.project.title); if (n) act(null, () => api(`/sim/${SID}/save-template`, {method: 'POST', json: {name: n}}), 'Template saved'); };
  $('#sm-exps').onclick = () => { location = `/api/sim/${SID}/export?format=story`; };
  $('#sm-expf').onclick = () => { location = `/api/sim/${SID}/export?format=story&full=true`; };
  const redo = (btn, part, title) => btn && (btn.onclick = async () => { const t = await textDlg(title, 'Anything the AI should keep in mind? (optional)', '', true); if (t !== null) run(null, `/seed/${part}`, {instruction: t}, 'Working on it'); });
  redo($('#w-redo'), 'world', 'Redo the world'); redo($('#c-redo'), 'cast', 'Redo the cast and places'); redo($('#t-redo'), 'trackers', 'Redo the trackers'); redo($('#r-redo'), 'rules', 'Redo the AI-written rules');
  const sm = $('#r-more'); if (sm) sm.onclick = async () => { const t = await textDlg('Suggest more rules', 'Anything the AI should keep in mind? (optional)', '', true); if (t !== null) run(null, '/guidelines/suggest', {instruction: t}, 'Thinking of more rules'); };
  const ar = $('#all-redo'); if (ar) ar.onclick = async () => { if (await confirmDlg('Redo everything?', 'The world, cast, trackers and AI rules are written again from the idea.', 'Redo')) run(ar, '/seed/all', {}, 'Writing the setup'); };
  const gs = $('#go-story'); if (gs) gs.onclick = () => { TAB = 'story'; LS.set('sm-tab-' + SID, 'story'); draw(); };
  $('#c-addc').onclick = () => entityDialog(null, 'character'); $('#c-addp').onclick = () => entityDialog(null, 'place');
  on('[data-ee]', b => b.onclick = () => entityDialog(D.entities.find(e => e.id === b.dataset.ee)));
  on('[data-ep]', b => b.onclick = () => run(b, `/entities/${b.dataset.ep}/paint`, {}, 'Painting'));
  on('[data-ed]', b => b.onclick = async () => { if (await confirmDlg(D.project.head_id ? 'Retire?' : 'Delete?', D.project.head_id ? 'The story already started, so they are retired: earlier chapters keep them, later chapters leave them out.' : 'They are removed from the cast and from the trackers that mention them.', D.project.head_id ? 'Retire' : 'Delete', true)) { await act(null, () => api(`/sim/${SID}/entities/${b.dataset.ed}`, {method: 'DELETE'})); load(); } });
  $('#t-add').onclick = () => trackerDialog(null);
  on('[data-te]', b => b.onclick = () => trackerDialog(D.trackers.find(t => t.id === b.dataset.te)));
  on('[data-td]', b => b.onclick = async () => { if (await confirmDlg('Remove this tracker?', 'Earlier chapters keep their numbers; later chapters stop tracking it.', 'Remove', true)) { await act(null, () => api(`/sim/${SID}/trackers/${b.dataset.td}`, {method: 'DELETE'})); load(); } });
  $('#r-add').onclick = () => ruleDialog(null);
  on('[data-re]', b => b.onclick = () => ruleDialog(D.guidelines.find(g => g.id === b.dataset.re)));
  on('[data-rd]', b => b.onclick = async () => { await act(null, () => api(`/sim/${SID}/guidelines/${b.dataset.rd}`, {method: 'DELETE'})); load(); });
  on('[data-rt]', c => c.onchange = async () => { const g = D.guidelines.find(x => x.id === c.dataset.rt); await act(null, () => api(`/sim/${SID}/guidelines`, {method: 'POST', json: {id: g.id, grp: g.grp, text: g.text, enabled: c.checked}})); load(); });
}

async function ruleDialog(g) {
  const v = await dialog({title: g ? 'Edit the rule' : 'Add a rule', html: `<label class="f">Rule (one sentence a reader could check)<textarea id="ru-t">${esc(g ? g.text : '')}</textarea></label>
    <label class="f">Group<select id="ru-g">${GROUPS.map(([k, l]) => `<option value="${k}" ${g && g.grp === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.text.trim() ? '' : 'Write the rule', collect: l => ({id: g ? g.id : undefined, text: l.querySelector('#ru-t').value, grp: l.querySelector('#ru-g').value, enabled: g ? g.enabled : true})}]});
  if (!v) return;
  const r = await act(null, () => api(`/sim/${SID}/guidelines`, {method: 'POST', json: v}), 'Saved'); if (r) load();
}

const ENT_FIELDS = {character: [['role', 'Role', 'input'], ['goal', 'Wants', 'input'], ['fear', 'Fears', 'input'], ['secret', 'Secret', 'input'], ['voice', 'How they speak', 'input'], ['look', 'How they look (used for pictures)', 'textarea'], ['starting_condition', 'Condition at the start', 'input']],
  place: [['description', 'What it is like', 'textarea'], ['look', 'How it looks (used for pictures)', 'textarea']], group: [['description', 'Who they are', 'textarea']]};
async function entityDialog(e, kind) {
  kind = e ? e.kind : kind;
  const v = await dialog({title: e ? `Edit ${e.name}` : `Add a ${kind}`, html: `<label class="f">Name<input id="en-n" value="${esc(e ? e.name : '')}"></label>${ENT_FIELDS[kind].map(([k, l, t]) => `<label class="f">${l}${t === 'textarea' ? `<textarea id="en-${k}">${esc(e ? e[k] || '' : '')}</textarea>` : `<input id="en-${k}" value="${esc(e ? e[k] || '' : '')}">`}</label>`).join('')}`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.name.trim() ? '' : 'Give it a name', collect: l => ({name: l.querySelector('#en-n').value, data: {...(e || {}), ...Object.fromEntries(ENT_FIELDS[kind].map(([k]) => [k, l.querySelector('#en-' + k).value]))}})}]});
  if (!v) return;
  ['id', 'project_id', 'kind', 'name', 'position', 'active'].forEach(k => delete v.data[k]);
  const r = await act(null, () => api(`/sim/${SID}/entities`, {method: 'POST', json: {id: e ? e.id : undefined, kind, name: v.name, data: v.data}}), 'Saved'); if (r) load();
}

function lines(txt) { return txt.split('\n').map(s => s.trim()).filter(Boolean); }
async function trackerDialog(t) {
  const names = D.entities.filter(e => e.kind === 'character' && e.active).map(e => e.name), places = D.entities.filter(e => e.kind === 'place' && e.active).map(e => e.name);
  const kinds = Object.keys(kindName);
  const form = (k, t) => {
    const s = t ? t.start : null; const num = (id, l, v) => `<label class="f">${l}<input id="${id}" type="number" step="any" value="${v ?? ''}"></label>`;
    if (k === 'items') return `<label class="f">One item per line: name x quantity @ holder<textarea id="tk-items" style="min-height:120px">${Object.entries(s || {}).map(([n, i]) => `${n} x${i.qty}${i.at ? ' @ ' + i.at : ''}`).join('\n')}</textarea></label>`;
    if (k === 'meter') return num('tk-min', 'Lowest', t ? t.min : 0) + num('tk-max', 'Highest', t ? t.max : 10) + num('tk-start', 'Starts at', s ?? 5) + `<label class="f">Unit<input id="tk-unit" value="${esc(t ? t.unit || '' : '')}"></label>` + num('tk-lo', 'Danger at or below (optional)', t ? t.danger_below : '') + num('tk-hi', 'Danger at or above (optional)', t ? t.danger_above : '');
    if (k === 'clock') return num('tk-max', 'Steps until full', t ? t.max : 6) + num('tk-start', 'Starts at', s ?? 0) + `<label class="f">What makes it rise<input id="tk-rises" value="${esc(t ? t.rises || '' : '')}"></label><label class="f">What happens when full<input id="tk-ends" value="${esc(t ? t.ends || '' : '')}"></label>`;
    if (k === 'relation') return `<label class="f">Between<select id="tk-a">${names.map(n => `<option ${t && t.a === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select> and <select id="tk-b">${names.map(n => `<option ${t && t.b === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>` + num('tk-trust', 'Trust (-5 to 5)', s ? s.trust : 0) + num('tk-tension', 'Tension (-5 to 5)', s ? s.tension : 0);
    if (k === 'location') return `<label class="f">One per line: person @ place<textarea id="tk-loc" style="min-height:110px">${Object.entries((s || {}).at || {}).map(([w, p]) => `${w} @ ${p}`).join('\n')}</textarea></label><label class="f">Locked places (comma separated)<input id="tk-locked" value="${esc(((s || {}).locked || []).join(', '))}"></label><div class="small mute">Places: ${places.map(esc).join(', ')}</div>`;
    if (k === 'knowledge') return `<label class="f">One secret per line: secret: who knows (comma separated)<textarea id="tk-know" style="min-height:110px">${Object.entries(s || {}).map(([x, w]) => `${x}: ${w.join(', ')}`).join('\n')}</textarea></label>`;
    return `<label class="f"><input type="checkbox" id="tk-flag" ${s ? 'checked' : ''}> Starts on (true)</label>`;
  };
  const pr = dialog({title: t ? `Edit ${t.name}` : 'Add something to track', html: `<label class="f">Name<input id="tk-n" value="${esc(t ? t.name : '')}"></label>
    <label class="f">Kind<select id="tk-k" ${t ? 'disabled' : ''}>${kinds.map(k => `<option value="${k}" ${t && t.kind === k ? 'selected' : ''}>${kindName[k]}</option>`).join('')}</select></label>
    <label class="f">What it is for (optional)<input id="tk-d" value="${esc(t ? t.description || '' : '')}"></label><div id="tk-form">${form(t ? t.kind : kinds[0], t)}</div>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.name.trim() ? '' : 'Give it a name', collect: l => {
      const k = l.querySelector('#tk-k').value, g = id => { const e = l.querySelector('#' + id); return e ? e.value : ''; }; const d = {description: g('tk-d')};
      if (k === 'items') d.start = lines(g('tk-items')).map(x => { const m = x.match(/^(.*?)(?:\s+x\s*(\d+))?(?:\s*@\s*(.*))?$/i); return {name: m[1].trim(), qty: +(m[2] || 1), at: (m[3] || '').trim()}; });
      else if (k === 'meter') Object.assign(d, {min: +g('tk-min'), max: +g('tk-max'), start: +g('tk-start'), unit: g('tk-unit'), danger_below: g('tk-lo') === '' ? null : +g('tk-lo'), danger_above: g('tk-hi') === '' ? null : +g('tk-hi')});
      else if (k === 'clock') Object.assign(d, {max: +g('tk-max'), start: +g('tk-start'), rises: g('tk-rises'), ends: g('tk-ends')});
      else if (k === 'relation') Object.assign(d, {a: g('tk-a'), b: g('tk-b'), start: {trust: +g('tk-trust'), tension: +g('tk-tension')}});
      else if (k === 'location') d.start = {at: Object.fromEntries(lines(g('tk-loc')).map(x => x.split('@').map(s => s.trim())).filter(a => a.length === 2)), locked: g('tk-locked').split(',').map(s => s.trim()).filter(Boolean)};
      else if (k === 'knowledge') d.start = Object.fromEntries(lines(g('tk-know')).map(x => { const i = x.indexOf(':'); return [i < 0 ? x : x.slice(0, i).trim(), i < 0 ? [] : x.slice(i + 1).split(',').map(s => s.trim()).filter(Boolean)]; }));
      else d.start = l.querySelector('#tk-flag').checked;
      return {name: g('tk-n'), kind: k, data: d}; }}]});
  const ksel = document.getElementById('tk-k');
  if (ksel && !t) ksel.onchange = () => { document.getElementById('tk-form').innerHTML = form(ksel.value, null); };
  const v = await pr;
  if (!v) return;
  const r = await act(null, () => api(`/sim/${SID}/trackers`, {method: 'POST', json: {id: t ? t.id : undefined, ...v}}));
  if (r) { if (r.problems && r.problems.length) toast('Fixed: ' + r.problems.join('; ')); load(); }
}
/* ───────── read tab ───────── */
function drawRead() {
  const p = D.project;
  $('#sm-body').innerHTML = `<div class="row mt"><span class="sp"></span><a class="btn" href="/api/sim/${SID}/export?format=md">Download Markdown</a><a class="btn" href="/api/sim/${SID}/export?format=zip">Download with pictures (zip)</a><a class="btn" href="/api/sim/${SID}/export?format=json">Chapter data (JSON)</a></div>
  <div class="sm-read"><h1>${esc(p.title)}</h1><p class="mute"><i>${esc(p.idea)}</i></p>${D.chapters.filter(c => c.status === 'done').map(c => `<h2>Chapter ${c.idx}: ${esc(c.title)}</h2><div class="small mute">${esc(c.story_time)}</div>
    ${c.panels.filter(x => x.file).map(x => `<figure style="margin:12px 0"><img src="/api/sim/file/${SID}/${esc(x.capfile || x.file)}" style="width:100%;border-radius:8px"></figure>`).join('')}<div class="sm-prose">${paras(c.prose)}</div>`).join('') || '<p class="mute">Nothing written yet.</p>'}</div>`;
}
})();
