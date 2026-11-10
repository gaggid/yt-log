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
.sm-fig{margin:12px 0}.sm-fig img{width:100%;border-radius:8px;display:block;background:var(--line);min-height:90px}.sm-fig figcaption{font-size:12px;color:var(--mute);margin-top:2px}
.sm-panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:8px 0}
.sm-panels figure{margin:0}.sm-panels img{width:100%;border-radius:8px;display:block;background:var(--line);min-height:90px}
.sm-panels figcaption{font-size:12px;color:var(--mute);margin-top:2px}
.sm-read{max-width:720px;margin:0 auto}.sm-read h2{margin-top:34px}
.sm-tag{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
details.sm-d summary{cursor:pointer;color:var(--mute);font-size:12px}
.sm-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
.sm-card{padding:12px 14px}.sm-card h4{margin:0 0 4px;font-size:14px}
.sm-chip.thing{border-color:var(--accent)}.sm-chip.undone{opacity:.55;text-decoration:line-through}
.sm-chip .link{background:none;border:0;color:var(--accent);cursor:pointer;font-size:11px;padding:0 2px}
.sm-bars{display:flex;align-items:flex-end;gap:3px;height:48px;margin:6px 0}.sm-bar{display:inline-block;width:10px;background:var(--accent);border-radius:2px 2px 0 0}
.sm-th{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.sm-th .row{margin:4px 0}
@media(max-width:900px){.sm-side{position:static;max-height:none;overflow:visible}}
@media(max-width:640px){
#app[data-sm] button,#app[data-sm] select,#app[data-sm] input:not([type=checkbox]):not([type=file]),#app[data-sm] .tab,#app[data-sm] summary{min-height:40px}
#app[data-sm] input[type=checkbox]{width:20px;height:20px}
#app[data-sm] .row{gap:8px}
#app[data-sm] .card.pad{padding:12px 12px}
.sm-kv{grid-template-columns:1fr;gap:2px}.sm-kv label{padding-top:0}
.sm-sum{flex:1 1 100% !important;order:5}
.sm-cards,.sm-panels{grid-template-columns:1fr}
.sm-opt{padding:12px}
.sm-dock #sm-text{flex:1 1 100% !important}
#app[data-sm] .row>a:first-child{padding:10px 4px;margin:-10px 0}
.sm-read{padding:0 2px}
}
`;
let el = null, my = 0, D = null, SID = '', TAB = 'story', poll = null, opening = false;
const kindName = {items: 'Items', meter: 'Meter', clock: 'Clock', relation: 'Relationship', location: 'Locations', knowledge: 'Secrets', flag: 'Yes/no fact'};
const GROUPS = [['hard', 'Hard rules (never broken)'], ['world', 'World rules'], ['tone', 'Tone and pacing'], ['style', 'Style'], ['craft', 'Making and finding']];
const COND = ['', 'new', 'worn', 'damaged', 'crude', 'well made', 'broken'];
const THING_OPS = ['discover', 'craft', 'item_give', 'item_take', 'item_use', 'item_change', 'skill_learn', 'owner_edit', 'cost'];
const THING_ICON = {discover: '🔍 ', craft: '🔧 ', item_give: '🤝 ', item_take: '✋ ', item_use: '▸ ', item_change: '✎ ', skill_learn: '★ ', owner_edit: '✎ ', cost: '⚠ '};
const thingBits = i => { const p = i.props || {}, b = []; if (p.condition) b.push(esc(p.condition)); if (p.uses !== null && p.uses !== undefined) b.push(`${p.uses} use${p.uses === 1 ? '' : 's'} left`); if (i.bound_to) b.push('bound to ' + esc(i.bound_to)); if (i.note) b.push(esc(i.note)); return b.length ? ` <span class="mute">(${b.join(', ')})</span>` : ''; };
const itemTrackers = () => D.trackers.filter(t => t.active && t.kind === 'items');
const carryOf = n => { const p = (D.carry && D.carry.people) || {}; return n in p ? p[n] : (D.carry ? D.carry.default : 0); };
function holdings(st) {
  const out = {};
  itemTrackers().forEach(t => Object.entries(st.trackers[t.id] || {}).forEach(([n, i]) => { (out[i.at || 'nowhere'] = out[i.at || 'nowhere'] || []).push([n, i, t.id]); }));
  return out;
}
const sizeOf = i => ((i.props && i.props.size) || 1) * (i.qty || 1);

function mark(node) { node.dataset.sm = '1'; if (!window._smLeave) { window._smLeave = true; addEventListener('hashchange', () => { if (!location.hash.startsWith('#/sim')) { const a = document.getElementById('app'); if (a) delete a.dataset.sm; } }); } }
function css() { if (!document.getElementById('sm-css')) { const s = document.createElement('style'); s.id = 'sm-css'; s.textContent = STYLE; document.head.append(s); } }
const live = () => el && document.body.contains(el) && my === route_id;
const paras = t => esc(t || '').split(/\n+/).filter(Boolean).map(p => `<p>${p}</p>`).join('');
/* the paragraphs of a chapter with each picture right after the paragraph it illustrates (p.at, counted from 1; the server works it out) */
function withPictures(c, fig) {
  const ps = (c.prose || '').split(/\n+/).map(x => x.trim()).filter(Boolean);
  const pics = c.panels || [];
  if (!ps.length) return pics.map(fig).join('');
  return ps.map((x, i) => `<p>${esc(x)}</p>` + pics.filter(p => Math.min(Math.max(p.at || ps.length, 1), ps.length) === i + 1).map(fig).join('')).join('');
}
const hash = (id, tab) => { location.hash = '#/sim' + (id ? '/' + id : '') + (tab ? '?t=' + tab : ''); };

/* ───────── library ───────── */
window.viewSim = async function () {
  css(); my = route_id; el = $('#app'); mark(el); D = null; SID = '';
  el.innerHTML = '<div class="skel"></div>';
  let r; try { r = await api('/sim'); } catch (e) { el.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  if (!live()) return;
  el.innerHTML = `<div class="row mb"><h2 style="margin:0">Stories</h2><span class="sp"></span><label class="small mute">Import <input type="file" id="sm-imp" accept=".json" hidden></label><button class="small" id="sm-impb">Import a story file</button></div>
  <div class="card pad mb"><b>New story</b><p class="mute small" style="margin:4px 0 8px">Write the idea in a few sentences. The AI will propose the cast, the world, the things to keep track of and the rules; you edit them, then start.</p>
    <textarea id="sm-idea" placeholder="For example: A night-shift salesman is alone in a supermarket when a zombie outbreak begins. He must survive until dawn using only what the store holds."></textarea>
    <div class="row mt-s"><label class="small mute">Template <select id="sm-tpl">${r.templates.map(t => `<option value="${esc(t.id)}" title="${esc(t.blurb)}">${esc(t.name)}</option>`).join('')}</select></label><span class="sp"></span><button class="primary" id="sm-new">Create story</button></div></div>
  <div class="sm-cards">${r.stories.length ? r.stories.map(s => `<div class="card sm-card" style="cursor:pointer" onclick="if(!event.target.closest('[data-del]'))location.hash='#/sim/${s.id}'"><h4>${esc(s.title)}</h4>
    <div class="small mute" style="margin-bottom:6px">${esc(s.idea.slice(0, 140))}${s.idea.length > 140 ? '…' : ''}</div>
    <div class="row small">${badge(s.status === 'running' ? 'good' : 'warn', s.status === 'setup' ? 'setting up' : 'in progress')}<span>${s.chapters} chapters</span>${s.bytes ? `<span class="mute">${(s.bytes / 1048576).toFixed(1)} MB of pictures</span>` : ''}${s.running ? '<span class="spin"></span>' : ''}<span class="sp"></span><span class="mute">${fmtDate(s.updated_at)}</span><button class="small bad" data-del="${s.id}" style="margin-left:8px">Delete</button></div></div>`).join('') : '<p class="mute">No stories yet. Write an idea above.</p>'}</div>`;
  $('#sm-new').onclick = async e => {
    const idea = $('#sm-idea').value.trim(); if (!idea) { toast('Write the idea first', {bad: true}); return; }
    const made = await act(e.target, () => api('/sim', {method: 'POST', json: {idea, template_id: $('#sm-tpl').value === 'tp-free' ? '' : $('#sm-tpl').value}}));
    if (!made) return;
    hash(made.id, 'setup');
  };
  el.querySelectorAll('[data-del]').forEach(b => { b.onclick = async e => { e.stopPropagation(); if (await confirmDlg('Delete this story?', 'All chapters, pictures and assets are permanently removed. This cannot be undone.', 'Delete', true)) { await act(null, () => api(`/sim/${b.dataset.del}`, {method: 'DELETE'})); load(); } }; });
  $('#sm-impb').onclick = () => $('#sm-imp').click();
  $('#sm-imp').onchange = async ev => {
    const f = ev.target.files[0]; if (!f) return;
    try { const m = await api('/sim/import', {method: 'POST', json: JSON.parse(await f.text())}); toast('Imported'); hash(m.id, 'setup'); } catch (er) { toast(er.message, {bad: true}); }
  };
};

/* ───────── one story ───────── */
window.viewSimStory = async function (id) {
  css(); my = route_id; el = $('#app'); mark(el); SID = id;
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

const STAGE = {gather: 'reading the situation', plan: 'planning', resolve: 'rolling the dice', delta: 'working out what changes', write: 'writing', referee: 'checking the rules', archive: 'remembering and offering options'};
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
  const tabs = [['story', 'Story'], ['plan', 'Plan'], ...(D.chapters.length ? [['things', 'Things']] : []), ['setup', 'Setup'], ['read', 'Read']];
  if (!tabs.some(t => t[0] === TAB)) TAB = 'story';
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
  ({story: drawStory, plan: drawPlan, things: drawThings, setup: drawSetup, read: drawRead})[TAB]();
}

function help() {
  return `<details class="card pad mt-s sm-d"><summary><b>How this page works</b></summary><div class="small" style="margin-top:8px;line-height:1.6">
    <p><b>The idea.</b> You write a few sentences. The AI proposes a world, a cast, <i>things to keep track of</i> (items, meters, clocks, relationships, secrets…) and rules. Everything is editable in <b>Setup</b>, before and during the story. This works for any kind of story, not only survival.</p>
    <p><b>A chapter</b> is about 350 words. For each one the AI plans the scene, <b>dice decide risky acts</b> (you see the roll; you can turn dice off in Setup), the AI works out what changes (items used, people hurt, clocks moving), a writer tells it, a checker compares it with your rules, and options for what happens next are offered. If a rule is broken twice, the chapter is kept with a red note; you can accept it or rewrite it.</p>
    <p><b>You steer</b> by clicking an option, writing your own action, pressing <b>Let it run</b> (the AI picks), or <b>Auto-run</b> several chapters (it stops on a death, a full clock, a broken rule or when you press Stop). <b>Add instruction</b> any time: an outside event, a limit, a twist or a steer, to happen next chapter, in some chapters, when something becomes true, or at a story time. Each instruction is used once on the line of the story it was added to.</p>
    <p><b>Rules and things tracked</b> keep the story honest: the AI may only use items that exist in the world card or that are made from items already used, the dead stay dead, and changes it proposes that do not fit are refused (shown under "What changed").</p>
    <p><b>Change your mind.</b> <i>Rewrite</i> a chapter with an instruction or roll <i>new dice</i>: the old version stays as another branch you can switch back to. <i>Edit text</i> lets you change the words; the AI can read your edit and propose how the state should change, and later chapters are marked as written before the edit. Only the last chapter of a line can be deleted.</p>
    <p><b>Things.</b> People can <i>find</i> things (a search that succeeds, an instruction, or something the world already holds), <i>make</i> them from parts they hold or that lie where they are (the AI works out what is really possible; skills, tools and a known recipe help the dice), <i>use</i> them up, <i>drop</i>, <i>give</i> and <i>take</i> them. Someone may refuse to hand a thing over; a thing can be <i>bound</i> to a person; nobody can carry more than their limit. The <b>Things</b> tab shows who has what, recipes and skills, and lets you change any of it. Under "What changed", <i>undo</i> takes one change back. <i>+ Give a thing</i> in the box below the chapter hands someone a thing, takes one away or lifts a binding in the next chapter.</p>
    <p><b>Story health and the arc.</b> The <i>Story health</i> card is worked out by the system from the chapters (no AI call): the tension of each chapter, whether acts ever fail or cost anything, who is missing, which goals, fears and secrets have not come up, how chapters end and what words repeat. <i>Length</i> in Setup gives the story a shape (set-up, rising, twist, crisis, climax, resolution); the planner is told where the story is and how tense the chapter must be, the opposing force makes a move every chapter, a failed act always costs something, and acts get harder after a run of easy chapters.</p>
    <p><b>The story plan</b> (the <b>Plan</b> tab). Before the first chapter the AI writes the backbone of the story: how it is told, a hidden truth with clues planted along the way, rules the person discovers, recurring devices, real-world facts that solve problems, the ending and one beat for each chapter. Each chapter plays its beat; your choices decide how the person handles it, and if you write your own action the beats still to come are rewritten. The secret is hidden until you press <i>Show the secret</i>; every part and every beat can be edited. Stories without a plan are improvised chapter by chapter.</p>
    <p><b>Content</b> (Setup, "Content") says how free the story is. <i>unfiltered</i> (the default) lets characters swear, abuse, lie, steal, kill and break the law whenever the story goes there, with real consequences but no softening or lectures, and mild sexual content between adults is allowed (the scene closes before explicit detail); <i>mature</i> and <i>clean</i> turn it down. The rules you write still apply.</p>
    <p><b>Thinking</b> (Setup, "Thinking") is how long the AI reasons before it plans, changes the state or checks a chapter. <i>balanced</i> is the default; <i>deep</i> is slower and more consistent; <i>off</i> is the fastest and makes more mistakes.</p>
    <p><b>Pictures</b> are optional: press <i>Paint this chapter</i> (or tick "Paint every chapter automatically" in Setup). They are cinematic paintings drawn from text. Each person and place gets a reference painting first, so faces and places stay alike; you can repaint, edit, replace with your own picture or remove any of them. Changing a person's look marks their pictures "old".</p>
    <p><b>Reading and publishing.</b> The <b>Read</b> tab shows the story as a book; download it as Markdown, as a zip with pictures in order, or as chapter data for turning chapters into videos later. <i>Export setup</i> / <i>Save as template</i> / <i>Duplicate</i> in Setup let you reuse a story as a starting point for another.</p>
    <p class="mute">Steps run one at a time (the local model serves one request at a time), so a chapter takes a few minutes. You can leave this page; the work continues and the page picks it up when you come back.</p></div></details>`;
}

/* ───────── story tab ───────── */
function stateHtml(st) {
  const tr = D.trackers.filter(t => t.active);
  const rows = tr.map(t => {
    const v = st.trackers[t.id]; let body = '';
    if (t.kind === 'items') {
      const by = {}; Object.entries(v || {}).forEach(([n, i]) => { (by[i.at || 'nowhere'] = by[i.at || 'nowhere'] || []).push([n, i]); });
      body = Object.entries(by).map(([h, rows]) => { const person = h in (st.entities || {}); const lim = person ? carryOf(h) : 0; const used = rows.reduce((s, [, i]) => s + sizeOf(i), 0);
        return `<div style="margin:3px 0"><span class="small">${person ? '' : '<span class="mute">at </span>'}<b>${esc(h)}</b>${person && lim ? ` <span class="mute">${used}/${lim}</span>` : ''}</span>${person && lim ? bar(Math.min(100, used / lim * 100), used >= lim ? 'fail' : '') : ''}${rows.map(([n, i]) => `<div class="small">${esc(n)} ×${i.qty}${thingBits(i)}</div>`).join('')}</div>`; }).join('') || '<span class="mute">none</span>';
    }
    else if (t.kind === 'meter') body = `${bar((v - t.min) / (t.max - t.min) * 100, v <= (t.danger_below ?? -1e9) || v >= (t.danger_above ?? 1e9) ? 'fail' : '')} <span class="small">${(+v).toFixed(1).replace(/\.0$/, '')}/${t.max} ${esc(t.unit || '')}</span>`;
    else if (t.kind === 'clock') body = Array.from({length: t.max}, (_, i) => `<span style="font-size:15px;color:${i < v ? 'var(--bad)' : 'var(--line)'}">●</span>`).join(' ') + ` <span class="small mute">${esc(t.rises || '')}</span>`;
    else if (t.kind === 'relation') body = `${esc(t.a)} ↔ ${esc(t.b)}: trust ${v.trust}, tension ${v.tension}`;
    else if (t.kind === 'location') body = Object.entries(v.at || {}).map(([w, p]) => `${esc(w)} → ${esc(p)}`).join('<br>') + (v.locked && v.locked.length ? `<br><span class="mute">locked: ${v.locked.map(esc).join(', ')}</span>` : '');
    else if (t.kind === 'knowledge') body = Object.entries(v || {}).map(([s, w]) => `${esc(s)}: ${w.length ? w.map(esc).join(', ') : '<span class="mute">nobody</span>'}`).join('<br>');
    else body = v ? 'yes' : 'no';
    return `<div><b>${esc(t.name)}</b> <span class="sm-tag">${kindName[t.kind]}</span><br>${body}</div>`;
  }).join('');
  const people = Object.entries(st.entities || {}).map(([n, e]) => `<span class="${e.alive ? '' : 'sm-dead'}">${esc(n)}</span>${e.status && e.alive ? ` <span class="mute small">(${esc(e.status)})</span>` : ''}${(e.skills || []).length ? ` <span class="mute small">[${e.skills.map(esc).join(', ')}]</span>` : ''}`).join(' · ');
  const rec = Object.entries(st.recipes || {});
  const found = (st.world_add || []).slice(-5).reverse();
  return `<div class="card pad sm-state"><b>State</b> <span class="small mute">${esc(st.time || '')}</span>${D.pressure.length ? `<div class="err small">${D.pressure.map(p => esc(p.text)).join('<br>')}</div>` : ''}${rows}<div>${people}</div>
    ${rec.length ? `<div><b>Recipes</b><br>${rec.map(([n, r]) => `<div class="small">${esc(n)} <span class="mute">needs ${esc((r.needs || []).join(', ') || '—')}${(r.tools || []).length ? '; tools ' + esc(r.tools.join(', ')) : ''}</span></div>`).join('')}</div>` : ''}
    ${found.length ? `<div><b>Found lately</b><br>${found.map(w => `<div class="small">${esc(w.kind)} · ${esc(w.name)}${w.where ? ` <span class="mute">at ${esc(w.where)}</span>` : ''}</div>`).join('')}</div>` : ''}</div>`;
}

function healthHtml() {
  const h = D.health;
  if (!h || !h.chapters) return '';
  const dot = {bad: 'var(--bad)', warn: 'var(--warn)', ok: 'var(--ok)'};
  const t = h.dice ? Object.entries(h.dice.tiers).map(([k, v]) => `${v} ${k}`).join(' · ') : '';
  return `<div class="card pad sm-health"><b>Story health</b> <span class="small mute">worked out by the system from the chapters</span>
    <div class="sm-bars" title="Tension of each chapter, out of 10">${h.intensity.map((v, i) => `<span class="sm-bar" style="height:${4 + v * 4}px" title="Chapter ${i + 1}: ${v}/10"></span>`).join('')}</div>
    ${h.verdicts.map(v => `<div class="small" style="margin:4px 0"><span style="color:${dot[v.level]}">●</span> ${esc(v.text)}</div>`).join('')}
    <div class="small mute" style="margin-top:6px">Rolls: ${t || 'none'} · endings: ${h.endings.join(', ')}</div></div>`;
}

function sideHtml() {
  const pend = D.directives.filter(d => d.pending && d.status !== 'cancelled');
  const th = D.threads;
  const rules = D.guidelines.filter(g => g.enabled);
  return `<div class="sm-side">${healthHtml()}${stateHtml(D.state)}
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
  const fig = p => `<figure class="sm-fig">${p.file ? `<img loading="lazy" src="/api/sim/file/${SID}/${esc(p.capfile || p.file)}?v=${esc(p.media_id)}" alt="">` : '<div style="height:120px;background:var(--line);border-radius:8px"></div>'}
    <figcaption>${p.old ? '<span class="badge b-warn">old</span> ' : ''}${p.uploaded ? '<span class="badge">your picture</span> ' : ''}${esc(p.caption || '')}</figcaption>
    <div class="row" style="gap:4px"><button class="small" data-pre="${c.id}:${p.n}">Redraw</button><button class="small" data-ped="${c.id}:${p.n}">Edit</button><button class="small" data-pup="${c.id}:${p.n}">Upload</button><button class="small bad" data-pdel="${c.id}:${p.n}">✕</button></div></figure>`;
  const prose = withPictures(c, fig);
  const paintErr = f.paint_error ? `<div class="sm-banner warn">The pictures could not be painted: ${esc(f.paint_error)}</div>` : '';
  return `<div class="card pad sm-ch mt" id="ch-${c.id}"><div class="row"><h3>Chapter ${c.idx}: ${esc(c.title || '(untitled)')}</h3><span class="sp"></span>
      ${c.siblings.length ? `<select data-branch="${c.id}" title="Other versions of this chapter">${c.siblings.map(s => `<option value="${s.id}" ${s.id === c.id ? 'selected' : ''}>${esc(s.label)}${s.status === 'failed' ? ' (failed)' : ''}</option>`).join('')}</select>` : ''}
      <span class="small mute">${esc(c.story_time || '')}</span></div>
    <div class="small mute">${esc(c.plan.beat || '')}${c.focus.length ? ' · following ' + c.focus.map(esc).join(', ') : ''}${c.chosen && c.chosen.label ? '' : ''}</div>
    ${flagsHtml}${paintErr}
    <div class="sm-prose mt-s">${prose}</div>
    ${c.rolls.length ? `<div>${c.rolls.map(r => `<span class="sm-chip ${r.tier}" title="${esc((r.why || []).join(', '))}">${esc(r.act)}: ${r.dice_off ? 'success' : `${r.die}${r.mod >= 0 ? '+' : ''}${r.mod} vs ${r.target} → ${r.tier}`}</span>`).join('')}</div>` : ''}
    ${(c.flags && c.flags.arc) || (c.plan && c.plan.opposition) ? `<div class="small mute">${c.flags.arc ? `phase ${esc(c.flags.arc.phase)}, aimed at tension ${c.flags.arc.target}/10` : ''}${c.plan.opposition ? `${c.flags.arc ? ' · ' : ''}the opposition: ${esc(c.plan.opposition)}` : ''}${(c.plan.calibration || []).length ? ' · ' + c.plan.calibration.map(esc).join('; ') : ''}</div>` : ''}
    ${(() => { const pc = (D.health && D.health.per_chapter || []).find(x => x.idx === c.idx); return pc ? `<div class="small mute">tension ${pc.intensity}/10 · ends on a ${esc(pc.ending)}${pc.costs.length ? ' · cost: ' + pc.costs.map(esc).join('; ') : ' · no cost'}</div>` : ''; })()}
    ${fired.length ? `<div>${fired.map(d => `<span class="sm-chip" style="border-color:var(--accent)">⚡ ${esc(d.kind)}: ${esc(d.text)}</span>`).join('')}</div>` : ''}
    <details class="sm-d mt-s"><summary>What changed${c.dropped.length ? ` · ${c.dropped.length} refused` : ''} · summary</summary>
      ${c.applied.length ? `<div class="small">${c.applied.map((a, ai) => `<span class="sm-chip ${THING_OPS.includes(a.op) ? 'thing' : ''} ${a.undone ? 'undone' : ''}">${THING_ICON[a.op] || ''}${esc(a.text)}${a.undone ? ' (taken back)' : ''}${a.undo && !a.undone ? ` <button class="link" data-undo="${c.id}:${ai}" title="Take this back">undo</button>` : ''}</span>`).join('')}</div>` : '<div class="small mute">No change to the state.</div>'}
      ${(c.plan.risks || []).filter(r => r.craft && r.craft.reasoning).map(r => `<div class="small" style="margin-top:4px"><b>Why this works:</b> ${esc(r.who)} — ${esc(r.craft.reasoning)}</div>`).join('')}
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
    ${head.options.map(o => `<button class="sm-opt sm-risk-${o.risk}" data-opt="${o.id}"><b>${esc(o.who)}:</b> ${esc(o.label)}<small>${o.hint ? 'gain: ' + esc(o.hint) : ''}${o.cost ? ` · cost: ${esc(o.cost)}` : ''} · ${o.risk} risk</small></button>`).join('')}
    <div class="row mt-s"><select id="sm-who">${chars.map(c => `<option>${esc(c)}</option>`).join('')}</select><input id="sm-text" style="flex:1;min-width:200px" placeholder="…or write what they do (any action you like)"><button id="sm-go" class="primary">Do this</button></div>
    <div class="row mt-s"><button id="sm-let" title="The AI picks the most in-character option">Let it run</button><span class="small mute">Auto-run</span><input type="number" id="sm-n" value="3" min="1" max="10" style="width:60px"><button id="sm-auto">chapters</button><span class="sp"></span><button id="sm-give" title="Hand someone a thing, take one away or lift a binding">+ Give a thing</button><button id="sm-dir2">+ Add instruction</button></div></div>`;
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
  const gv = $('#sm-give'); if (gv) gv.onclick = () => directiveDialog('grant');
  on('[data-undo]', b => b.onclick = async () => { const [cid, i] = b.dataset.undo.split(':'); if (await confirmDlg('Take this back?', 'The thing goes back to how it was. Chapters after this one are marked as written before the change.', 'Take it back')) { await act(null, () => api(`/sim/${SID}/chapters/${cid}/undo`, {method: 'POST', json: {index: +i}}), 'Taken back'); load(); } });
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

async function directiveDialog(pre) {
  const trackers = D.trackers.filter(t => ['clock', 'meter', 'flag'].includes(t.kind));
  const known = Object.keys(holdings(D.state)).length ? [...new Set(Object.values(holdings(D.state)).flat().map(x => x[0]))] : [];
  const holders = [...Object.keys(D.state.entities || {}), ...D.entities.filter(e => e.kind === 'place' && e.active).map(e => e.name)];
  const kinds = [['event', 'Event'], ['constraint', 'Limit'], ['twist', 'Twist'], ['steer', 'Steer'], ['grant', 'Give a thing to someone'], ['take', 'Take a thing away'], ['unbind', 'Lift a binding on a thing']];
  const thingForm = k => k === 'grant' || k === 'take' || k === 'unbind' ? `<label class="f">Which thing<input id="di-item" list="di-items" placeholder="Flare gun"><datalist id="di-items">${known.map(n => `<option value="${esc(n)}">`).join('')}</datalist></label>
    ${k === 'unbind' ? '' : `<label class="f">${k === 'grant' ? 'Who gets it' : 'Where it goes (empty = it is gone)'}<select id="di-to">${k === 'take' ? '<option value="">(gone)</option>' : ''}${holders.map(h => `<option>${esc(h)}</option>`).join('')}</select></label><label class="f">How many<input id="di-q" type="number" min="1" value="1"></label>`}
    <p class="small mute">This is done by the system in that chapter, whatever the dice say; the story then shows it.</p>` : '';
  const pr = dialog({title: pre ? 'Give or take away a thing' : 'Add an instruction to the story', html: `<p class="small mute">It can be an outside event (raiders arrive), a limit (no more food after day 2), a twist, a steer toward somewhere, or a thing handed over or taken away. It is used once, on this line of the story.</p>
    <label class="f">What (the story is told this; optional for things)<textarea id="di-t" placeholder="Raiders arrive at the loading bay and demand supplies"></textarea></label>
    <label class="f">Kind<select id="di-k">${kinds.map(([v, l]) => `<option value="${v}" ${pre === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label><div id="di-th">${thingForm(pre)}</div>
    <label class="f">When<select id="di-m"><option value="next">In the next chapter</option><option value="in">In a number of chapters</option><option value="when">When something happens</option><option value="story_time">At a story time</option></select></label>
    <div id="di-x"></div>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Add', primary: true, validate: v => !v.text.trim() && !['grant', 'take', 'unbind'].includes(v.kind) ? 'Write the instruction' : (['grant', 'take', 'unbind'].includes(v.kind) && !v.thing.item.trim() ? 'Say which thing' : v.kind === 'grant' && !v.thing.to ? 'Say who gets it' : v.timing.mode === 'when' && !v.timing.condition && !v.timing.tracker ? 'Say when' : v.timing.mode === 'story_time' && !v.timing.at ? 'Say the story time' : ''),
      collect: l => { const m = l.querySelector('#di-m').value; const t = {mode: m};
        if (m === 'in') t.chapters = +l.querySelector('#di-n').value || 1;
        if (m === 'when') { const tr = l.querySelector('#di-tr').value; if (tr) { t.tracker = tr; t.op = l.querySelector('#di-op').value; t.value = +l.querySelector('#di-val').value; } else t.condition = l.querySelector('#di-c').value; }
        if (m === 'story_time') t.at = l.querySelector('#di-at').value;
        const kd = l.querySelector('#di-k').value, it = l.querySelector('#di-item'), to = l.querySelector('#di-to'), q = l.querySelector('#di-q');
        const tx = l.querySelector('#di-t').value.trim() || (kd === 'grant' ? `${to ? to.value : 'Someone'} gets ${it ? it.value : 'a thing'}` : kd === 'take' ? `${it ? it.value : 'A thing'} is taken away${to && to.value ? ' to ' + to.value : ''}` : `${it ? it.value : 'A thing'} is no longer bound`);
        return {text: tx, kind: kd, timing: t, thing: ['grant', 'take', 'unbind'].includes(kd) ? {item: it ? it.value : '', to: to ? to.value : '', qty: q ? +q.value || 1 : 1} : undefined}; }}]});
  const ksel = document.getElementById('di-k');
  if (ksel) ksel.onchange = () => { document.getElementById('di-th').innerHTML = thingForm(ksel.value); };
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

/* ───────── plan tab ───────── */
let PLAN_FULL = null;
const PURPOSES = ['setup', 'problem', 'solution', 'turn', 'clue', 'payoff', 'reveal', 'ending'];
const POVS = [['second', 'second person (you)'], ['first', 'first person (I)'], ['third', 'third person']];

async function planAct(method, path, json, ok) {
  const r = await act(null, () => api(`/sim/${SID}${path}`, {method, json}), ok || 'Saved');
  if (r) { PLAN_FULL = null; load(); }
  return r;
}

const SECRET_KINDS = [['authority_lie', 'Someone in charge lies'], ['trap', 'A trap'], ['hidden_resource', 'A hidden resource'], ['betrayal', 'A betrayal'], ['identity', 'A hidden identity'], ['other', 'Other']];
const RULE_KINDS = [['stated', 'said aloud'], ['discovered', 'learned from what happens'], ['policy', 'never said, shown']];
const kindLabel = k => (SECRET_KINDS.find(x => x[0] === k) || ['', k || ''])[1];

function pickerHtml(opts, busy) {
  if (!opts || !opts.length) return '';
  return `<h4 style="margin:14px 0 4px">Pick the twist</h4><p class="small mute">Four hidden truths grown out of your idea. Use one as it is, or edit it first; the plan is then written around it.</p>` + opts.map((o, i) => `<div class="card pad mt-s"><b>${esc(kindLabel(o.kind))}</b>
    <div class="small" style="margin:4px 0">${esc(o.truth)}</div><div class="small mute">The lie: ${esc(o.lie || 'none')} · Found out by: ${esc(o.found_by || '-')}</div>${(o.clues || []).length ? `<div class="small mute">Clues: ${o.clues.map(esc).join('; ')}</div>` : ''}
    <div class="row" style="margin-top:6px"><button class="small primary" data-pick="${i}" ${busy ? 'disabled' : ''}>Use this</button><button class="small" data-pick-edit="${i}" ${busy ? 'disabled' : ''}>Edit, then use</button></div></div>`).join('');
}

function bindPicker(root, opts, again) {
  const use = o => run(null, '/seed/bible', {instruction: '', secret: o}, 'Writing the story plan');
  root.querySelectorAll('[data-pick]').forEach(btn => btn.onclick = async () => { if (!again || await confirmDlg('Write the whole plan again?', 'The plan, its rules, objects and the beats still to come are written again around this twist. Chapters already written stay.', 'Write it again')) use(opts[+btn.dataset.pick]); });
  root.querySelectorAll('[data-pick-edit]').forEach(btn => btn.onclick = async () => {
    const o = opts[+btn.dataset.pickEdit];
    const v = await dialog({title: 'Edit the twist', html: `<label class="f">The hidden truth<textarea id="pk-t">${esc(o.truth)}</textarea></label><label class="f">Held by<input id="pk-w" value="${esc(o.who || '')}"></label><label class="f">The lie everyone believes<input id="pk-l" value="${esc(o.lie || '')}"></label><label class="f">The person finds out by<textarea id="pk-f">${esc(o.found_by || '')}</textarea></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Write the plan', primary: true, collect: l => ({...o, truth: l.querySelector('#pk-t').value, who: l.querySelector('#pk-w').value, lie: l.querySelector('#pk-l').value, found_by: l.querySelector('#pk-f').value})}]});
    if (v && (!again || await confirmDlg('Write the whole plan again?', 'The plan, its rules, objects and the beats still to come are written again around this twist. Chapters already written stay.', 'Write it again'))) use(v);
  });
  const ps = root.querySelector('#pl-secrets'); if (ps) ps.onclick = () => run(null, '/secrets', {instruction: ''}, 'Thinking of four twists');
}

async function drawPlan() {
  const b = $('#sm-body'), pl = D.plan, busy = D.run && D.run.state === 'running';
  if (!pl) {
    b.innerHTML = `<div class="card pad mt"><h3 style="margin-top:0">No story plan yet</h3>
      <p class="mute">A story plan is written before the chapters: the point of view and voice, a hidden truth with clues planted along the way, rules the person discovers, recurring devices, real-world facts that solve problems, the ending, and one beat for each chapter. Chapters then play their beats; your choices decide how the person handles each one. Without a plan the story is improvised chapter by chapter.</p>
      ${D.chapters.length ? '<p class="small mute">The story has started: the plan is written for the chapters still to come, from what has happened so far.</p>' : ''}
      <button class="primary" id="pl-make" ${busy ? 'disabled' : ''}>Write the story plan with AI</button> <button id="pl-secrets" ${busy ? 'disabled' : ''}>Propose four twists first</button>${pickerHtml(D.secret_options, busy)}</div>`;
    bindPicker(b, D.secret_options || [], false);
    $('#pl-make').onclick = async () => { const t = await textDlg('Write the story plan', 'Anything the AI should keep in mind? (optional)', '', true); if (t !== null) run(null, '/seed/bible', {instruction: t}, 'Writing the story plan'); };
    return;
  }
  let sec = pl.secret;
  if (PLAN_FULL) sec = PLAN_FULL.secret;
  const beats = PLAN_FULL ? PLAN_FULL.beats : pl.beats;
  const chip = s => `<span class="sm-chip ${s === 'done' ? 'success' : s === 'next' ? 'thing' : ''}">${s === 'done' ? 'played' : s === 'next' ? 'next' : 'later'}</span>`;
  b.innerHTML = `${busy ? '<div class="sm-banner warn">A step is running; changes wait until it is done.</div>' : ''}
  <div class="card pad mt"><div class="row"><b>The story plan</b><span class="sp"></span><button class="small" id="pl-basics">Edit</button></div>
    <p style="margin:6px 0"><i>${esc(pl.logline)}</i></p>
    <div class="small"><b>Told in</b> ${esc((POVS.find(p => p[0] === pl.pov) || ['', pl.pov])[1])}. <b>Voice:</b> ${esc(pl.voice)}</div>
    ${pl.opening && (pl.opening.line || pl.opening.action || pl.opening.belief) ? `<div class="small" style="margin-top:4px"><b>Opens on</b> ${esc(pl.opening.line || '')} <span class="mute">${esc(pl.opening.action || '')}${pl.opening.belief ? ' · believes: ' + esc(pl.opening.belief) : ''}</span></div>` : ''}</div>
  ${(pl.audit || []).length ? `<div class="card pad mt"><b>What the plan still lacks</b>${pl.audit.map(a => `<div class="small" style="margin:3px 0"><span class="sm-tag">${a.level === 'warn' ? 'missing' : 'note'}</span> ${esc(a.text)}</div>`).join('')}</div>` : '<div class="small mute mt">The plan has every part of the film framework.</div>'}
  <div class="card pad mt"><div class="row"><b>The hidden truth</b><span class="sp"></span>${sec.hidden ? '<button class="small" id="pl-show">Show the secret</button>' : '<button class="small" id="pl-edit-secret">Edit</button><button class="small" id="pl-hide">Hide</button>'}</div>
    ${sec.hidden ? `<div class="small mute">Hidden, so you can read the story as a reader would. ${sec.clues} clues are planted before it is revealed.</div>`
      : `<div class="small" style="margin-top:6px">${esc(sec.truth)} <span class="mute">(held by ${esc(sec.who || 'someone')}; revealed in beat ${sec.reveal_beat})</span></div>
      <div class="small mute">${esc(kindLabel(sec.kind))} · The lie: ${esc(sec.lie || 'none')} · Found out by: ${esc(sec.found_by || 'not said')}${sec.method_beat ? ' (beat ' + sec.method_beat + ')' : ''}</div>${(sec.clues || []).map(c => `<div class="small mute">beat ${c.beat}: ${esc(c.clue)}</div>`).join('')}`}</div>
  <div class="sm-th mt">
    <div class="card pad"><div class="row"><b>Rules the person discovers</b><span class="sp"></span><button class="small" id="pl-rules">Edit</button></div>${(pl.rules || []).map(r => `<div class="small" style="margin:3px 0"><b>${esc(r.name)}</b> · ${esc((RULE_KINDS.find(k => k[0] === r.kind) || ['', r.kind || 'said aloud'])[1])} · beat ${r.beat}${(r.uses || []).length ? ', again in ' + r.uses.join(', ') : ''}${r.broken_beat ? ', broken in ' + r.broken_beat : ''}<br>${esc(r.text)}${r.shown ? `<br><span class="mute">Shown by: ${esc(r.shown)}</span>` : ''}</div>`).join('') || '<div class="small mute">none</div>'}</div>
    <div class="card pad"><div class="row"><b>Recurring devices</b><span class="sp"></span><button class="small" id="pl-motifs">Edit</button></div>${(pl.motifs || []).map(x => `<div class="small" style="margin:3px 0"><b>${esc(x.name)}</b> · from beat ${x.first_beat}${(x.payoffs || []).length ? ', pays off in ' + x.payoffs.join(', ') : ''}<br>${esc(x.what)}</div>`).join('') || '<div class="small mute">none</div>'}</div>
    <div class="card pad"><div class="row"><b>Real-world facts</b><span class="sp"></span><button class="small" id="pl-facts">Edit</button></div><div class="small mute">The AI's general knowledge: please check them.</div>${(pl.facts || []).map(f => `<div class="small" style="margin:3px 0">beat ${f.beat}: ${esc(f.fact)}<br><span class="mute">${esc(f.use)}</span></div>`).join('') || '<div class="small mute">none</div>'}</div>
    <div class="card pad"><div class="row"><b>The ending</b><span class="sp"></span><button class="small" id="pl-end">Edit</button></div><div class="small">${esc((pl.ending || {}).outcome || '')}<br><span class="mute">Last image:</span> ${esc((pl.ending || {}).final_image || '')}<br><span class="mute">Closing line:</span> ${esc((pl.ending || {}).closing_line || '')}${(pl.ending || {}).inversion ? `<br><span class="mute">Turns the opening around:</span> ${esc(pl.ending.inversion)}` : ''}</div></div>
    <div class="card pad"><div class="row"><b>Number on screen</b><span class="sp"></span><button class="small" id="pl-count">Edit</button></div>${(pl.countdown || {}).name ? `<div class="small"><b>${esc(pl.countdown.name)}</b> <span class="mute">(${esc(pl.countdown.unit || '')})</span></div>${(pl.countdown.steps || []).map(s => `<div class="small mute">beat ${s.beat}: ${s.value}${s.note ? ' · ' + esc(s.note) : ''}</div>`).join('')}` : '<div class="small mute">none</div>'}</div>
    <div class="card pad"><div class="row"><b>Planted objects</b><span class="sp"></span><button class="small" id="pl-objects">Edit</button></div>${(pl.objects || []).map(o => `<div class="small" style="margin:3px 0"><b>${esc(o.name)}</b> · planted in beat ${o.plant_beat}, pays off in ${o.payoff_beat}<br><span class="mute">${esc(o.what)} → ${esc(o.payoff)}</span></div>`).join('') || '<div class="small mute">none</div>'}</div>
    <div class="card pad"><div class="row"><b>Acts</b><span class="sp"></span><button class="small" id="pl-acts">Edit</button></div><div class="small">Midpoint: ${(pl.midpoint || {}).beat ? `beat ${pl.midpoint.beat}: ${esc(pl.midpoint.change || '')}` : '<span class="mute">none</span>'}</div><div class="small">Low point: ${(pl.low_point || {}).beat ? `beat ${pl.low_point.beat}: ${esc(pl.low_point.loss || '')}` : '<span class="mute">none</span>'}</div></div></div>
  <div class="card pad mt"><div class="row"><b>The beats</b> <span class="small mute">${pl.done} of ${beats.length} played</span><span class="sp"></span><button class="small" id="pl-replan" ${busy ? 'disabled' : ''}>Re-plan the rest…</button><button class="small" id="pl-redo" ${busy ? 'disabled' : ''}>Write the whole plan again…</button></div>
    ${beats.map(x => `<div class="mt-s" style="border-top:1px solid var(--line);padding-top:8px"><div class="row"><b>${esc(x.label)}</b>${chip(x.status)}<span class="sm-tag">${esc(x.purpose)}</span><span class="sp"></span><button class="small" data-be="${x.n}">Edit</button></div>
      <div class="small">${esc(x.event)}</div><div class="small mute">Problem: ${esc(x.problem)}${x.turn ? ` · Turn: ${esc(x.turn)}` : ''}${x.hook ? ` · Ends on: ${esc(x.hook)}` : ''}${x.rule ? ` · Rule: ${esc(x.rule)}` : ''}${x.motif ? ` · Device: ${esc(x.motif)}` : ''}${x.fact ? ` · Fact: ${esc(x.fact)}` : ''}${(x.clues || []).length ? ` · Plants: ${x.clues.map(esc).join('; ')}` : ''}</div>
      <div class="small mute">${esc(x.act || '')}${x.role ? ' · ' + x.role.replace('_', ' ') : ''}${x.problem_no ? ' · ' + esc(x.signpost) : ''}${x.solved_by ? ' · Solved by: ' + esc(x.solved_by) : ''}${x.count != null && pl.countdown && pl.countdown.name ? ' · ' + esc(pl.countdown.name) + ': ' + x.count : ''}${(x.plant || []).length ? ' · Sets up: ' + x.plant.map(esc).join(', ') : ''}${(x.pay || []).length ? ' · Pays off: ' + x.pay.map(esc).join(', ') : ''}${(x.rule_uses || []).length ? ' · Uses: ' + x.rule_uses.map(esc).join(', ') : ''}${x.method ? ' · Method: ' + esc(x.method) : ''}</div></div>`).join('')}</div>${pickerHtml(D.secret_options, busy) ? `<div class="card pad mt">${pickerHtml(D.secret_options, busy)}</div>` : ''}
  <div class="row mt"><button class="small" id="pl-secrets" ${busy ? 'disabled' : ''}>Propose four new twists…</button></div>`;
  bindPicker(b, D.secret_options || [], true);
  const on = (sel, fn) => el.querySelectorAll(sel).forEach(fn);
  const full = async () => { const r = await act(null, () => api(`/sim/${SID}/bible?spoilers=true`)); if (r) { PLAN_FULL = r.plan; drawPlan(); } };
  const bt = $('#pl-show'); if (bt) bt.onclick = full;
  const hd2 = $('#pl-hide'); if (hd2) hd2.onclick = () => { PLAN_FULL = null; drawPlan(); };
  $('#pl-basics').onclick = async () => {
    const v = await dialog({title: 'Edit the story basics', html: `<label class="f">Logline<textarea id="pb-l">${esc(pl.logline)}</textarea></label><label class="f">Told in<select id="pb-p">${POVS.map(([k, l]) => `<option value="${k}" ${pl.pov === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label class="f">Voice<textarea id="pb-v">${esc(pl.voice)}</textarea></label>
      <label class="f">The first line<input id="pb-ol" value="${esc((pl.opening || {}).line || '')}"></label><label class="f">What the person does in the first scene<input id="pb-oa" value="${esc((pl.opening || {}).action || '')}"></label><label class="f">What the person believes at the start<input id="pb-ob" value="${esc((pl.opening || {}).belief || '')}"></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({logline: l.querySelector('#pb-l').value, pov: l.querySelector('#pb-p').value, voice: l.querySelector('#pb-v').value, opening: {line: l.querySelector('#pb-ol').value, action: l.querySelector('#pb-oa').value, belief: l.querySelector('#pb-ob').value}})}]});
    if (v) planAct('PUT', '/bible', v);
  };
  const es = $('#pl-edit-secret'); if (es) es.onclick = async () => {
    const v = await dialog({title: 'Edit the hidden truth', html: `<label class="f">The truth<textarea id="ps-t">${esc(sec.truth)}</textarea></label><label class="f">Who or what holds it<input id="ps-w" value="${esc(sec.who || '')}"></label><label class="f">Revealed in beat<input id="ps-r" type="number" value="${sec.reveal_beat}"></label>
      <label class="f">What kind of secret<select id="ps-k">${SECRET_KINDS.map(([k, l]) => `<option value="${k}" ${sec.kind === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label class="f">The lie everyone believes (what the authority says)<input id="ps-l" value="${esc(sec.lie || '')}"></label>
      <label class="f">The person finds out by (something they do)<textarea id="ps-f">${esc(sec.found_by || '')}</textarea></label><label class="f">Method beat<input id="ps-m" type="number" value="${sec.method_beat || ''}"></label>
      <label class="f">Clues, one per line: beat | clue<textarea id="ps-c" style="min-height:110px">${(sec.clues || []).map(c => `${c.beat} | ${c.clue}`).join('\n')}</textarea></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({secret: {truth: l.querySelector('#ps-t').value, who: l.querySelector('#ps-w').value, reveal_beat: +l.querySelector('#ps-r').value, kind: l.querySelector('#ps-k').value, lie: l.querySelector('#ps-l').value, found_by: l.querySelector('#ps-f').value, method_beat: +l.querySelector('#ps-m').value || 0, clues: lines(l.querySelector('#ps-c').value).map(x => { const i = x.indexOf('|'); return {beat: +x.slice(0, i) || 1, clue: x.slice(i + 1).trim()}; })}})}]});
    if (v) planAct('PUT', '/bible', v);
  };
  const listEdit = (id, title, hint, rows, key, fmt, parse) => { const btn = $(id); if (btn) btn.onclick = async () => {
    const v = await dialog({title, html: `<label class="f">${hint}<textarea id="pe-x" style="min-height:160px">${rows.map(fmt).join('\n')}</textarea></label>`, buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({[key]: lines(l.querySelector('#pe-x').value).map(parse)})}]});
    if (v) planAct('PUT', '/bible', v); }; };
  listEdit('#pl-rules', 'Edit the rules', 'One per line: name | the rule | beat where it is learned | stated, discovered or policy | beats where it is used again (comma separated) | for a policy, how it shows without being said | beat where it is broken on purpose (0 = never)', pl.rules || [], 'rules',
    r => `${r.name} | ${r.text} | ${r.beat} | ${r.kind || 'stated'} | ${(r.uses || []).join(', ')} | ${r.shown || ''} | ${r.broken_beat || 0}`,
    x => { const p = x.split('|').map(s => s.trim()); return {name: p[0], text: p[1] || '', beat: +p[2] || 1, kind: ['stated', 'discovered', 'policy'].includes(p[3]) ? p[3] : 'stated', uses: (p[4] || '').split(',').map(s => +s.trim()).filter(Boolean), shown: p[5] || '', broken_beat: +p[6] || 0}; });
  listEdit('#pl-motifs', 'Edit the recurring devices', 'One per line: name | what it is | first beat | beats where it pays off (comma separated)', pl.motifs || [], 'motifs', r => `${r.name} | ${r.what} | ${r.first_beat} | ${(r.payoffs || []).join(', ')}`, x => { const p = x.split('|').map(s => s.trim()); return {name: p[0], what: p[1] || '', first_beat: +p[2] || 1, payoffs: (p[3] || '').split(',').map(s => +s.trim()).filter(Boolean)}; });
  listEdit('#pl-facts', 'Edit the real-world facts', 'One per line: the fact | how the story uses it | beat', pl.facts || [], 'facts', r => `${r.fact} | ${r.use} | ${r.beat}`, x => { const p = x.split('|').map(s => s.trim()); return {fact: p[0], use: p[1] || '', beat: +p[2] || 1}; });
  $('#pl-end').onclick = async () => {
    const e = pl.ending || {};
    const v = await dialog({title: 'Edit the ending', html: `<label class="f">How it ends<textarea id="pn-o">${esc(e.outcome || '')}</textarea></label><label class="f">The last image<input id="pn-i" value="${esc(e.final_image || '')}"></label><label class="f">The closing line<input id="pn-c" value="${esc(e.closing_line || '')}"></label><label class="f">How the ending turns the opening around<textarea id="pn-v">${esc(e.inversion || '')}</textarea></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({ending: {outcome: l.querySelector('#pn-o').value, final_image: l.querySelector('#pn-i').value, closing_line: l.querySelector('#pn-c').value, inversion: l.querySelector('#pn-v').value}})}]});
    if (v) planAct('PUT', '/bible', v);
  };
  const cb = $('#pl-count'); if (cb) cb.onclick = async () => {
    const c = pl.countdown || {};
    const v = await dialog({title: 'Edit the number on screen', html: `<label class="f">What is counted (days of food, people left...)<input id="pc-n" value="${esc(c.name || '')}"></label><label class="f">Unit<input id="pc-u" value="${esc(c.unit || '')}"></label>
      <label class="f">Steps, one per line: beat | value | why it changes<textarea id="pc-s" style="min-height:140px">${(c.steps || []).map(s => `${s.beat} | ${s.value} | ${s.note || ''}`).join('\n')}</textarea></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({countdown: {name: l.querySelector('#pc-n').value, unit: l.querySelector('#pc-u').value, steps: lines(l.querySelector('#pc-s').value).map(x => { const p = x.split('|').map(s => s.trim()); return {beat: +p[0] || 1, value: +p[1] || 0, note: p[2] || ''}; })}})}]});
    if (v) planAct('PUT', '/bible', v);
  };
  listEdit('#pl-objects', 'Edit the planted objects', 'One per line: name | how it first appears | beat where it is planted | beat where it pays off | how it pays off', pl.objects || [], 'objects', o => `${o.name} | ${o.what} | ${o.plant_beat} | ${o.payoff_beat} | ${o.payoff}`,
    x => { const p = x.split('|').map(s => s.trim()); return {name: p[0], what: p[1] || '', plant_beat: +p[2] || 1, payoff_beat: +p[3] || 0, payoff: p[4] || ''}; });
  const ab = $('#pl-acts'); if (ab) ab.onclick = async () => {
    const m1 = pl.midpoint || {}, l1 = pl.low_point || {};
    const v = await dialog({title: 'Edit the acts', html: `<label class="f">Midpoint beat<input id="pa-mb" type="number" value="${m1.beat || ''}"></label><label class="f">What changes for good at the midpoint<input id="pa-mc" value="${esc(m1.change || '')}"></label>
      <label class="f">Low point beat<input id="pa-lb" type="number" value="${l1.beat || ''}"></label><label class="f">What the person loses<input id="pa-ll" value="${esc(l1.loss || '')}"></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({midpoint: {beat: +l.querySelector('#pa-mb').value || 0, change: l.querySelector('#pa-mc').value}, low_point: {beat: +l.querySelector('#pa-lb').value || 0, loss: l.querySelector('#pa-ll').value}})}]});
    if (v) planAct('PUT', '/bible', v);
  };
  on('[data-be]', btn => btn.onclick = async () => {
    const x = beats.find(y => y.n === +btn.dataset.be);
    const v = await dialog({title: `Edit beat ${x.n}`, html: `<label class="f">Label (time: title)<input id="bb-l" value="${esc(x.label)}"></label><label class="f">What happens<textarea id="bb-e">${esc(x.event)}</textarea></label><label class="f">The problem to solve<textarea id="bb-p">${esc(x.problem)}</textarea></label><label class="f">What solves it (a fact, a rule, an object, an idea)<input id="bb-s" value="${esc(x.solved_by || '')}"></label>
      <label class="f">The turn<input id="bb-t" value="${esc(x.turn || '')}"></label><label class="f">It ends on<input id="bb-h" value="${esc(x.hook || '')}"></label><label class="f">A risky act for the dice (optional)<input id="bb-c" value="${esc(x.challenge || '')}"></label>
      <label class="f">Purpose<select id="bb-u">${PURPOSES.map(p => `<option ${x.purpose === p ? 'selected' : ''}>${p}</option>`).join('')}</select></label>`,
      buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => ({label: l.querySelector('#bb-l').value, event: l.querySelector('#bb-e').value, problem: l.querySelector('#bb-p').value, solved_by: l.querySelector('#bb-s').value, turn: l.querySelector('#bb-t').value, hook: l.querySelector('#bb-h').value, challenge: l.querySelector('#bb-c').value, purpose: l.querySelector('#bb-u').value})}]});
    if (v) planAct('PUT', `/bible/beats/${x.n}`, v);
  });
  $('#pl-replan').onclick = async () => { const t = await textDlg('Re-plan the rest', 'What should change in the beats still to come? (optional)', '', true); if (t !== null) run(null, '/replan', {instruction: t}, 'Rewriting the rest of the plan'); };
  $('#pl-redo').onclick = async () => { if (await confirmDlg('Write the whole plan again?', 'The hidden truth, rules, devices, facts, ending and the beats still to come are written again. Chapters already written stay.', 'Write it again')) { const t = await textDlg('Write the story plan', 'Anything the AI should keep in mind? (optional)', '', true); if (t !== null) run(null, '/seed/bible', {instruction: t}, 'Writing the story plan'); } };
}

/* ───────── things tab ───────── */
async function thingAct(action, ok) {
  const r = await act(null, () => api(`/sim/${SID}/things`, {method: 'POST', json: {action}}), ok || 'Saved');
  if (r) load();
  return r;
}

function drawThings() {
  const st = D.state, busy = D.run && D.run.state === 'running';
  const hold = holdings(st);
  const people = Object.entries(st.entities || {});
  const places = D.entities.filter(e => e.kind === 'place' && e.active).map(e => e.name).concat((st.world_add || []).filter(w => w.kind === 'place').map(w => w.name));
  const thingRow = ([n, i]) => `<div class="row"><span style="flex:1"><b>${esc(n)}</b> ×${i.qty}${thingBits(i)}${i.origin && i.origin.how && i.origin.how !== 'start' && i.origin.how !== 'stock' ? ` <span class="small mute">· ${esc(i.origin.how)}${i.origin.chapter ? ' in chapter ' + i.origin.chapter : ''}${i.origin.by ? ' by ' + esc(i.origin.by) : ''}</span>` : ''}</span>
    <button class="small" data-th-edit="${esc(n)}">Edit</button><button class="small bad" data-th-del="${esc(n)}">✕</button></div>`;
  const personCard = ([n, e]) => { const rows = hold[n] || []; const lim = carryOf(n); const used = rows.reduce((s, [, i]) => s + sizeOf(i), 0);
    return `<div class="card pad ${e.alive ? '' : 'sm-dead'}"><div class="row"><b>${esc(n)}</b>${lim ? `<span class="small mute">carries ${used}/${lim}</span>` : ''}<span class="sp"></span><button class="small" data-th-addto="${esc(n)}">+ Thing</button></div>
      ${lim ? bar(Math.min(100, used / lim * 100), used >= lim ? 'fail' : '') : ''}
      <div class="small mute" style="margin:4px 0">Skills: ${(e.skills || []).map(s => `<span class="sm-chip">${esc(s)} <button class="link" data-sk-del="${esc(n)}|${esc(s)}">✕</button></span>`).join('') || 'none'} <button class="link" data-sk-add="${esc(n)}">+ skill</button></div>
      ${rows.map(([nm, i]) => thingRow([nm, i])).join('') || '<div class="small mute">Carries nothing.</div>'}</div>`; };
  const placeCard = p => { const rows = hold[p] || []; return `<div class="card pad"><div class="row"><b>${esc(p)}</b><span class="sp"></span><button class="small" data-th-addto="${esc(p)}">+ Thing</button></div>${rows.map(([nm, i]) => thingRow([nm, i])).join('') || '<div class="small mute">Nothing lies here.</div>'}</div>`; };
  const rec = Object.entries(st.recipes || {});
  const found = st.world_add || [];
  $('#sm-body').innerHTML = `${busy ? '<div class="sm-banner warn">A step is running; changes here wait until it is done.</div>' : ''}
  <div class="small mute mt-s">Everything the people carry and know, as the story stands after the last chapter. Changes here apply to the next chapter. A thing can be bound to a person so nobody else can take or be given it; an instruction can still lift that.</div>
  <h3 class="mt">People</h3><div class="sm-th">${people.map(personCard).join('')}</div>
  <h3 class="mt">Places</h3><div class="sm-th">${places.map(placeCard).join('') || '<div class="mute">No places.</div>'}${hold.nowhere ? `<div class="card pad"><b>Nowhere in particular</b>${hold.nowhere.map(([nm, i]) => thingRow([nm, i])).join('')}</div>` : ''}</div>
  <div class="card pad mt"><div class="row"><b>Recipes known</b><span class="sp"></span><button class="small" data-rc-add="1">+ Recipe</button></div>
    ${rec.map(([n, r]) => `<div class="row"><span style="flex:1"><b>${esc(n)}</b> <span class="small mute">needs ${esc((r.needs || []).join(', ') || '—')}${(r.tools || []).length ? '; tools ' + esc(r.tools.join(', ')) : ''}${r.skill ? '; skill ' + esc(r.skill) : ''}${(r.learned_by || []).length ? '; known by ' + esc(r.learned_by.join(', ')) : ''}</span></span><button class="small" data-rc-edit="${esc(n)}">Edit</button><button class="small bad" data-rc-del="${esc(n)}">✕</button></div>`).join('') || '<div class="small mute">None yet. A recipe is remembered the first time something is made, or when someone is taught it.</div>'}</div>
  <div class="card pad mt"><b>Found so far</b>${found.length ? found.slice().reverse().map(w => `<div class="small" style="margin:3px 0"><span class="sm-tag">${esc(w.kind)}</span> <b>${esc(w.name)}</b>${w.where ? ` at ${esc(w.where)}` : ''}${w.by ? ` · found by ${esc(w.by)}` : ''} · chapter ${w.chapter}${w.text ? `<br><span class="mute">${esc(w.text)}</span>` : ''}</div>`).join('') : '<div class="small mute">Nothing found yet. Things, places and clues found in the story are listed here.</div>'}</div>`;
  const on = (sel, fn) => el.querySelectorAll(sel).forEach(fn);
  const find = n => Object.values(hold).flat().find(x => x[0] === n);
  on('[data-th-edit]', b => b.onclick = () => thingDialog(b.dataset.thEdit, find(b.dataset.thEdit)[1]));
  on('[data-th-del]', b => b.onclick = async () => { if (await confirmDlg(`Remove ${b.dataset.thDel}?`, 'It disappears from the story from the next chapter.', 'Remove', true)) thingAct({do: 'remove_thing', name: b.dataset.thDel}, 'Removed'); });
  on('[data-th-addto]', b => b.onclick = () => thingDialog('', {qty: 1, at: b.dataset.thAddto, props: {}}, true));
  on('[data-sk-add]', b => b.onclick = async () => { const s = await textDlg(`A skill for ${b.dataset.skAdd}`, 'For example: first aid', ''); if (s && s.trim()) thingAct({do: 'add_skill', who: b.dataset.skAdd, skill: s.trim()}, 'Skill added'); });
  on('[data-sk-del]', b => b.onclick = () => { const [w, s] = b.dataset.skDel.split('|'); thingAct({do: 'remove_skill', who: w, skill: s}, 'Skill removed'); });
  on('[data-rc-add]', b => b.onclick = () => recipeDialog('', {}));
  on('[data-rc-edit]', b => b.onclick = () => recipeDialog(b.dataset.rcEdit, st.recipes[b.dataset.rcEdit]));
  on('[data-rc-del]', b => b.onclick = async () => { if (await confirmDlg(`Forget the recipe for ${b.dataset.rcDel}?`, 'People stop knowing how to make it.', 'Forget', true)) thingAct({do: 'remove_recipe', name: b.dataset.rcDel}, 'Removed'); });
}

async function thingDialog(name, i, isNew) {
  const holders = [...Object.keys(D.state.entities || {}), ...D.entities.filter(e => e.kind === 'place' && e.active).map(e => e.name)];
  const p = i.props || {};
  const v = await dialog({title: isNew ? 'Add a thing' : `Edit ${name}`, html: `<label class="f">Name<input id="th-n" value="${esc(name)}" ${isNew ? '' : 'disabled'}></label>
    <label class="f">Who has it, or where it lies<select id="th-at">${holders.map(h => `<option ${i.at === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}</select></label>
    <label class="f">How many<input id="th-q" type="number" min="1" value="${i.qty || 1}"></label>
    <label class="f">Condition<select id="th-c">${COND.map(c => `<option value="${c}" ${(p.condition || '') === c ? 'selected' : ''}>${c || '(not said)'}</option>`).join('')}</select></label>
    <label class="f">Uses left (empty = it does not wear out)<input id="th-u" type="number" min="0" value="${p.uses ?? ''}"></label>
    <label class="f">Size (counts against what a person can carry)<input id="th-s" type="number" min="1" max="9" value="${p.size || 1}"></label>
    <label class="f">Bound to (nobody else can take it or be given it)<select id="th-b"><option value="">(nobody)</option>${Object.keys(D.state.entities || {}).map(h => `<option ${i.bound_to === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}</select></label>
    <label class="f">Note<input id="th-note" value="${esc(i.note || '')}" placeholder="opens the pharmacy safe"></label>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.name.trim() ? '' : 'Give it a name', collect: l => ({name: isNew ? l.querySelector('#th-n').value.trim() : name,
      fields: {at: l.querySelector('#th-at').value, qty: +l.querySelector('#th-q').value || 1, condition: l.querySelector('#th-c').value, uses: l.querySelector('#th-u').value === '' ? null : +l.querySelector('#th-u').value, size: +l.querySelector('#th-s').value || 1, bound_to: l.querySelector('#th-b').value, note: l.querySelector('#th-note').value}})}]});
  if (v) thingAct({do: 'set_thing', name: v.name, fields: v.fields}, 'Saved');
}

async function recipeDialog(name, r) {
  const v = await dialog({title: name ? `Edit the recipe for ${name}` : 'Add a recipe', html: `<label class="f">What it makes<input id="rc-n" value="${esc(name)}" ${name ? 'disabled' : ''}></label>
    <label class="f">Parts used up (comma separated)<input id="rc-p" value="${esc((r.needs || []).join(', '))}"></label><label class="f">Tools needed, not used up (comma separated)<input id="rc-t" value="${esc((r.tools || []).join(', '))}"></label>
    <label class="f">Skill needed<input id="rc-s" value="${esc(r.skill || '')}"></label><label class="f">Known by (comma separated)<input id="rc-k" value="${esc((r.learned_by || []).join(', '))}"></label>`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.name.trim() ? '' : 'Say what it makes', collect: l => { const cs = id => l.querySelector('#' + id).value.split(',').map(s => s.trim()).filter(Boolean);
      return {name: name || l.querySelector('#rc-n').value.trim(), needs: cs('rc-p'), tools: cs('rc-t'), skill: l.querySelector('#rc-s').value, learned_by: cs('rc-k')}; }}]});
  if (v) thingAct({do: 'set_recipe', ...v}, 'Saved');
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
      <label title="How many chapters the story should have. The system builds the story toward a climax and an ending of that size; open-ended repeats a cycle of build-up, twist, crisis and release.">Length <select id="s-length">${[[0, 'open-ended'], [6, '6 chapters'], [8, '8 chapters'], [12, '12 chapters'], [16, '16 chapters'], [24, '24 chapters'], [36, '36 chapters'], [48, '48 chapters']].map(([v, l]) => `<option value="${v}" ${(st.length || 0) === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label title="Write a story plan with the AI when the story is set up: point of view, a hidden truth with clues, rules to discover, recurring devices, real facts, the ending and a beat for every chapter."><input type="checkbox" id="s-plan" ${st.plan !== false ? 'checked' : ''}> Write a story plan at setup</label>
      <label title="An editor's pass over every chapter: the same events in more specific, varied prose, without the model's stock words. Costs about a minute a chapter."><input type="checkbox" id="s-polish" ${st.polish ? 'checked' : ''}> Polish every chapter</label>
      <label title="The narration announces each problem aloud: First problem, water. Second problem, sleep. Works with a story plan."><input type="checkbox" id="s-signposts" ${st.signposts ? 'checked' : ''}> Announce each problem aloud</label>
      <label title="How much one person can carry, in size units (a plain thing is 1). 0 means no limit. A person can have their own limit in their card.">Carry limit <input type="number" id="s-carry" value="${st.carry_limit ?? 8}" min="0" max="40" style="width:70px"></label>
      <label title="How freely the story may go. Unfiltered: strong language, cruelty, crime and mild adult romance are written as the scene needs them, without softening or moral comment.">Content <select id="s-content">${[['clean', 'clean'], ['mature', 'mature'], ['unfiltered', 'unfiltered (no limits)']].map(([v, l]) => `<option value="${v}" ${(st.content || 'unfiltered') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label title="How long the AI thinks before it plans, changes the state or checks a chapter. More thinking is slower and keeps the story more consistent.">Thinking <select id="s-think">${[['off', 'off (fastest)'], ['balanced', 'balanced'], ['deep', 'deep (slowest)']].map(([v, l]) => `<option value="${v}" ${(st.thinking || 'balanced') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>
    <div class="row mt-s" style="gap:16px"><label><input type="checkbox" id="s-auto" ${st.auto_images ? 'checked' : ''}> Paint every chapter automatically</label>
      <label title="How the pictures look. Changing it marks the pictures already drawn as old, so you can repaint them.">Picture style <select id="s-style">${[['painted', 'Cinematic painting'], ['comic', 'Comic book'], ['flat', 'Simple flat 2D']].map(([v, l]) => `<option value="${v}" ${(st.image_style || 'painted') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label>Picture shape <select id="s-shape"><option value="wide" ${st.panel_shape === 'wide' ? 'selected' : ''}>wide (16:9)</option><option value="tall" ${st.panel_shape === 'tall' ? 'selected' : ''}>tall (9:16)</option></select></label>
      <label><input type="checkbox" id="s-cap" ${st.captions ? 'checked' : ''}> Captions on pictures</label><label>Image model <input id="s-img" value="${esc(st.image_model)}" placeholder="default" style="width:150px"></label>
      <span class="sp"></span><button class="primary" id="s-save">Save</button></div></div>

  <div class="card pad mt"><div class="row"><b>The world</b><span class="sp"></span><button class="small" id="w-redo">Redo with AI…</button></div>
    ${[['place', 'Place'], ['period', 'When'], ['tone', 'Tone'], ['pacing', 'Pacing'], ['start_scene', 'First scene'], ['start_time', 'Story clock at start']].map(([k, l]) => field(l, 'w-' + k, w[k])).join('')}
    ${field('What the story is about', 'w-goal', w.goal, 'textarea', 'style="min-height:60px" placeholder="What the people must achieve or avoid, and what is lost if they fail. Every chapter is steered by this."')}${field('What exists here', 'w-exists', w.exists, 'textarea', 'style="min-height:110px"')}${field('What can be made or found', 'w-craft', w.craft, 'textarea', 'style="min-height:60px" placeholder="For example: makeshift tools only; nothing electronic works"')}<div class="row"><span class="small mute">The story may only use what exists here (items appear only from places that hold them).</span><span class="sp"></span><button id="w-save">Save the world</button></div></div>

  <div class="card pad mt"><div class="row"><b>Cast and places</b><span class="sp"></span>${started ? '' : '<button class="small" id="c-redo">Redo with AI…</button>'}<button class="small" id="c-addc">+ Character</button><button class="small" id="c-addp">+ Place</button></div>
    <div class="sm-cards mt-s">${[...chars, ...others].map(e => `<div class="card sm-card"><h4>${esc(e.name)} <span class="sm-tag">${e.kind}</span></h4><div class="small">${e.kind === 'character' ? `${esc(e.role || '')}${e.goal ? `<br><span class="mute">wants:</span> ${esc(e.goal)}` : ''}${e.fear ? `<br><span class="mute">fears:</span> ${esc(e.fear)}` : ''}${(e.skills || []).length ? `<br><span class="mute">skills:</span> ${e.skills.map(esc).join(', ')}` : ''}` : esc(e.description || '')}</div>
      ${e.ref_file ? `<img src="/api/sim/file/${SID}/${esc(e.ref_file)}" style="width:100%;border-radius:8px;margin-top:6px" alt="">` : ''}${e.ref_old ? '<span class="badge b-warn">picture is out of date</span>' : ''}
      <div class="small mute" style="margin-top:4px">${esc((e.look || '').slice(0, 120))}${(e.look || '').length > 120 ? '…' : ''}</div><div class="row mt-s"><button class="small" data-ee="${e.id}">Edit</button><button class="small" data-ep="${e.id}">${e.ref_file ? 'Repaint' : 'Paint'}</button><button class="small bad" data-ed="${e.id}">${started ? 'Retire' : 'Delete'}</button></div></div>`).join('') || '<p class="mute">No one yet.</p>'}</div></div>

  <div class="card pad mt"><div class="row"><b>What the story keeps track of</b><span class="sp"></span>${started ? '' : '<button class="small" id="t-redo">Redo with AI…</button>'}<button class="small" id="t-add">+ Add</button></div>
    <div class="small mute">Items, meters, clocks, relationships, who is where, secrets and yes/no facts. The AI changes these as the story moves; the rules refuse changes that do not make sense.</div>
    ${D.trackers.filter(t => t.active).map(t => `<div class="row mt-s"><span class="badge">${kindName[t.kind]}</span><b>${esc(t.name)}</b><span class="small mute sm-sum" style="flex:1">${esc(trackerSummary(t))}</span><button class="small" data-te="${t.id}">Edit</button><button class="small bad" data-td="${t.id}">Remove</button></div>`).join('') || '<p class="mute">Nothing yet.</p>'}</div>

  <div class="card pad mt"><div class="row"><b>Rules</b> <span class="small mute">version ${st.rules_version}</span><span class="sp"></span><button class="small" id="r-redo">Redo the AI's rules…</button><button class="small" id="r-more">Suggest more…</button><button class="small" id="r-add">+ Add a rule</button></div>
    ${GROUPS.map(([g, l]) => { const rs = D.guidelines.filter(x => x.grp === g); return `<div class="mt-s"><div class="sm-tag">${l}</div>${rs.map(x => `<div class="row" style="margin:3px 0"><input type="checkbox" data-rt="${x.id}" ${x.enabled ? 'checked' : ''} title="Use this rule"><span style="flex:1;${x.enabled ? '' : 'color:var(--mute)'}">${esc(x.text)}</span><span class="small mute">${x.origin === 'ai' ? 'AI' : 'you'}</span><button class="small" data-re="${x.id}">Edit</button><button class="small bad" data-rd="${x.id}">✕</button></div>`).join('') || '<div class="small mute">none</div>'}</div>`; }).join('')}</div>

  ${started ? '<div class="sm-banner">The story has started: changes here apply from the next chapter.</div>' : (() => { const noWorld = !D.world.place; return `<div class="card pad mt row"><span class="sp"></span>${D.missing.length ? `<span class="small err">Not ready: ${D.missing.map(esc).join('; ')}</span>` : ''}<button class="${noWorld ? 'primary' : 'small'}" id="all-redo">${noWorld ? 'Generate setup with AI' : 'Redo everything with AI'}</button><button class="primary" id="go-story" ${D.missing.length ? 'disabled' : ''}>Go to the story</button></div>`; })()}`;
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
  $('#s-save').onclick = () => patch({idea: $('#s-idea').value, settings: {difficulty: $('#s-diff').value, dice: $('#s-dice').checked, chapter_words: +$('#s-words').value || 350, thinking: $('#s-think').value, content: $('#s-content').value, carry_limit: +$('#s-carry').value || 0, plan: $('#s-plan').checked, polish: $('#s-polish').checked, signposts: $('#s-signposts').checked, length: +$('#s-length').value || 0,
    auto_images: $('#s-auto').checked, panel_shape: $('#s-shape').value, image_style: $('#s-style').value, captions: $('#s-cap').checked, image_model: $('#s-img').value.trim()}});
  $('#w-save').onclick = () => patch({world: Object.fromEntries(['place', 'period', 'tone', 'pacing', 'start_scene', 'start_time', 'exists', 'craft', 'goal'].map(k => [k, $('#w-' + k).value]))});
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

const ENT_FIELDS = {character: [['role', 'Role', 'input'], ['goal', 'Wants', 'input'], ['fear', 'Fears', 'input'], ['secret', 'Secret', 'input'], ['voice', 'How they speak', 'input'], ['skills', 'Skills (comma separated: what they are good at)', 'input'], ['carry', 'Carry limit (empty = the story default, 0 = none)', 'input'], ['look', 'How they look (used for pictures)', 'textarea'], ['starting_condition', 'Condition at the start', 'input']],
  place: [['description', 'What it is like', 'textarea'], ['look', 'How it looks (used for pictures)', 'textarea']], group: [['description', 'Who they are', 'textarea']]};
async function entityDialog(e, kind) {
  kind = e ? e.kind : kind;
  const v = await dialog({title: e ? `Edit ${e.name}` : `Add a ${kind}`, html: `<label class="f">Name<input id="en-n" value="${esc(e ? e.name : '')}"></label>${ENT_FIELDS[kind].map(([k, l, t]) => `<label class="f">${l}${t === 'textarea' ? `<textarea id="en-${k}">${esc(e ? e[k] || '' : '')}</textarea>` : `<input id="en-${k}" value="${esc(e ? (Array.isArray(e[k]) ? e[k].join(', ') : e[k] ?? '') : '')}">`}</label>`).join('')}`,
    buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, validate: v => v.name.trim() ? '' : 'Give it a name', collect: l => ({name: l.querySelector('#en-n').value, data: {...(e || {}), ...Object.fromEntries(ENT_FIELDS[kind].map(([k]) => [k, k === 'skills' ? l.querySelector('#en-' + k).value.split(',').map(s => s.trim()).filter(Boolean) : l.querySelector('#en-' + k).value]))}})}]});
  if (!v) return;
  ['id', 'project_id', 'kind', 'name', 'position', 'active'].forEach(k => delete v.data[k]);
  const r = await act(null, () => api(`/sim/${SID}/entities`, {method: 'POST', json: {id: e ? e.id : undefined, kind, name: v.name, data: v.data}}), 'Saved'); if (r) load();
}

function itemLine(n, i) {
  const p = i.props || {}, b = [];
  if (p.uses !== null && p.uses !== undefined) b.push('uses ' + p.uses);
  if (p.size && p.size > 1) b.push('size ' + p.size);
  if (p.condition) b.push('condition ' + p.condition);
  if (i.bound_to) b.push('bound ' + i.bound_to);
  return `${n} x${i.qty}${i.at ? ' @ ' + i.at : ''}${b.length ? ' [' + b.join(', ') + ']' : ''}`;
}
function parseItemLine(x) {
  let extra = ''; const br = x.match(/\[(.*)\]\s*$/); if (br) { extra = br[1]; x = x.slice(0, br.index); }
  const m = x.match(/^(.*?)(?:\s+x\s*(\d+))?(?:\s*@\s*(.*))?$/i); const o = {name: m[1].trim(), qty: +(m[2] || 1), at: (m[3] || '').trim()};
  extra.split(',').map(s => s.trim()).filter(Boolean).forEach(s => { const mm = s.match(/^(uses|size|condition|bound)\s+(.+)$/i); if (!mm) return; const key = mm[1].toLowerCase(), val = mm[2].trim(); if (key === 'uses') o.uses = +val; else if (key === 'size') o.size = +val; else if (key === 'condition') o.condition = val; else o.bound_to = val; });
  return o;
}
function lines(txt) { return txt.split('\n').map(s => s.trim()).filter(Boolean); }
async function trackerDialog(t) {
  const names = D.entities.filter(e => e.kind === 'character' && e.active).map(e => e.name), places = D.entities.filter(e => e.kind === 'place' && e.active).map(e => e.name);
  const kinds = Object.keys(kindName);
  const form = (k, t) => {
    const s = t ? t.start : null; const num = (id, l, v) => `<label class="f">${l}<input id="${id}" type="number" step="any" value="${v ?? ''}"></label>`;
    if (k === 'items') return `<label class="f">One thing per line: name x quantity @ holder [uses 3, size 2, condition worn, bound Dev]<textarea id="tk-items" style="min-height:140px">${Object.entries(s || {}).map(([n, i]) => itemLine(n, i)).join('\n')}</textarea></label><div class="small mute">The part in square brackets is optional. Holders are people or places of the story.</div>`;
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
      if (k === 'items') d.start = lines(g('tk-items')).map(parseItemLine);
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
    <div class="sm-prose">${withPictures({...c, panels: c.panels.filter(x => x.file)}, x => `<figure class="sm-fig"><img src="/api/sim/file/${SID}/${esc(x.capfile || x.file)}" alt="">${x.caption ? `<figcaption>${esc(x.caption)}</figcaption>` : ''}</figure>`)}</div>`).join('') || '<p class="mute">Nothing written yet.</p>'}</div>`;
}
})();
