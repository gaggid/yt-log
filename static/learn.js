/* YouTube page, "Learn" tab: how the channel's results steer the idea factory (docs/PLAN_feedback_loop.md). Uses the helpers of index.html ($, api, esc, act, toast, dialog, badge). */
(() => {
const num = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n || 0));
const when = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, {day: 'numeric', month: 'short'}) : '';
const DIMS = [['hook_type', 'Hook shape'], ['territory', 'Subject territory'], ['mechanism', 'Attention mechanism'], ['mech_pair', 'Mechanism pair'], ['style', 'Picture style'], ['tone', 'Tone'],
  ['score_band', 'Idea score'], ['length', 'Length'], ['has_number', 'Number in the hook'], ['hook_len', 'Hook length'], ['origin', 'Where the idea came from']];
let D = null, host = null, poll = null;

window.mountLearn = async function (el) {
  host = el;
  host.innerHTML = '<div class="skel"></div>';
  await load();
};

async function load() {
  if (!host || !document.body.contains(host)) return;
  try { D = await api('/feedback/overview'); } catch (e) { host.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  draw();
}

async function runJob(btn, path, label) {
  const ok = await act(btn, () => api(path, {method: 'POST'}), label + ' started');
  if (ok === undefined || ok === null) return;
  watch();
}

function watch() {
  clearTimeout(poll);
  const tick = async () => {
    let r;
    try { r = await api('/shorts/ideas/run'); } catch (e) { return; }
    const note = document.getElementById('lr-run');
    if (r.state === 'running') {
      if (note) note.innerHTML = `<span class="spin"></span> ${esc(r.label || r.kind || 'working')}…`;
      poll = setTimeout(tick, 3000);
    } else {
      if (note) note.textContent = '';
      if (r.state === 'error' || r.error) toast(r.error || r.note || 'The step failed', {bad: true});
      else if (r.note && r.kind) toast(r.note);
      load();
    }
  };
  tick();
}

function controls() {
  const s = D.state;
  return `<div class="card pad"><div class="row" style="gap:14px;flex-wrap:wrap">
    <label class="row small" style="gap:6px"><input type="checkbox" id="lr-use" ${s.use_playbook ? 'checked' : ''}> Use the Playbook in idea generation</label>
    <label class="row small" style="gap:6px">Explore <select id="lr-explore">${[0.3, 0.35, 0.4].map(v => `<option value="${v}" ${Math.abs(s.explore - v) < 0.001 ? 'selected' : ''}>${Math.round(v * 100)}%</option>`).join('')}</select> of choices try something new</label>
    <label class="row small" style="gap:6px"><input type="checkbox" id="lr-auto" ${s.auto_feedback ? 'checked' : ''}> Daily feedback cycle in the autopilot <span class="mute">(drafts only)</span></label>
    <span class="sp"></span><span id="lr-run" class="mute small"></span></div>
    <div class="row mt-s" style="gap:8px;flex-wrap:wrap">
      <button class="small" id="lr-refresh" title="Recompute every grade from the numbers already pulled">Regrade</button>
      <button class="small" id="lr-tag" title="Territory of ideas and channel videos that have none">Tag subjects</button>
      <button class="small primary" id="lr-draft">Draft a Playbook</button>
      <button class="small" id="lr-seq" title="New ideas from videos at 3x your median or better">Sequels of winners</button>
      <button class="small" id="lr-com" title="New ideas from what viewers ask in the comments">Ideas from comments</button>
      <button class="small" id="lr-cycle" title="All of the above, then check the new ideas">Run the whole cycle</button></div>
    ${s.last_cycle ? `<div class="mute small mt-s">Last cycle ${when(s.last_cycle.at)}: ${esc(s.last_cycle.notes.join('; '))}</div>` : ''}</div>`;
}

function tiles() {
  const b = D.baseline, c = D.calibration;
  const t = (label, v, sub) => `<div class="card pad" style="min-width:140px"><div class="mute small">${label}</div><div style="font-size:22px;font-weight:700">${v}</div>${sub ? `<div class="mute small">${sub}</div>` : ''}</div>`;
  const lf = new Date(D.learn_from * 1000).toLocaleDateString('en-IN', {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata'});
  return `<div class="mute small mb-s">Learning only from shorts published on or after <b>${lf}</b> <a href="#" id="lf-change">change</a></div><div class="row" style="gap:10px;flex-wrap:wrap">${t('Graded shorts', D.rows.length, `${D.n_app} by the app, ${D.n_history} older`)}${t('Winners / flops', D.winners + ' / ' + D.flops, 'top and bottom quarter')}
    ${t('Typical 7-day views', num(b.reach || 0), `median of ${b.n} shorts`)}${t('Score predicts results?', c.total === null || c.total === undefined ? 'not yet' : c.total.toFixed(2), c.total === null || c.total === undefined ? `needs 5 ideas, has ${c.n}` : '1 = perfectly, 0 = not at all')}</div>`;
}

function itemRow(pb, it, kind) {
  const off = (pb.data.disabled || []).includes(it.key);
  return `<li style="margin:6px 0;${off ? 'opacity:.45;text-decoration:line-through' : ''}"><label class="row" style="gap:8px;align-items:flex-start"><input type="checkbox" data-toggle="${pb.id}" data-key="${esc(it.key)}" ${off ? '' : 'checked'} title="Untick to stop using this item">
    <span style="flex:1">${esc(it.text)} <span class="badge">${esc(it.scope)}</span> <span class="mute small">${it.evidence.map(e => `<a href="https://youtube.com/shorts/${esc(e)}" target="_blank" rel="noopener">${esc(e.slice(0, 5))}…</a>`).join(' ')}</span></span></label></li>`;
}

function playbookCard(pb) {
  const d = pb.data, ch = d.changes || {};
  const status = {draft: badge('warn', 'draft: waiting for your review'), approved: badge('good', 'in use'), archived: badge('', 'replaced'), rejected: badge('error', 'rejected')}[pb.status] || '';
  const diff = (ch.added || []).length || (ch.removed || []).length ? `<div class="small mt-s"><b>What changed${ch.against ? ' since v' + ch.against : ''}</b>
    ${(ch.added || []).map(t => `<div style="color:var(--good,#2e9d5b)">+ ${esc(t)}</div>`).join('')}${(ch.removed || []).map(t => `<div style="color:var(--bad,#c0392b)">− ${esc(t)}</div>`).join('')}</div>` : '';
  const btns = pb.status === 'draft' ? `<button class="small primary" data-approve="${pb.id}">Approve: use it</button> <button class="small bad" data-reject="${pb.id}">Reject</button>` : '';
  return `<div class="card pad mt-s"><div class="row" style="gap:8px"><b>Playbook v${pb.version}</b>${status}<span class="mute small">${when(pb.created_at)} · from ${d.based_on ? d.based_on.graded : '?'} graded shorts</span><span class="sp"></span>${btns}</div>
    <p class="small">${esc(d.summary || '')}</p>
    <div class="row" style="gap:18px;align-items:flex-start;flex-wrap:wrap"><div style="flex:1;min-width:260px"><b class="small">Do more</b><ul style="padding-left:0;list-style:none">${(d.do_more || []).map(i => itemRow(pb, i)).join('') || '<li class="mute small">nothing yet</li>'}</ul></div>
      <div style="flex:1;min-width:260px"><b class="small">Do less</b><ul style="padding-left:0;list-style:none">${(d.do_less || []).map(i => itemRow(pb, i)).join('') || '<li class="mute small">nothing yet</li>'}</ul></div></div>
    ${d.title_note ? `<div class="small"><b>Titles:</b> ${esc(d.title_note)}</div>` : ''}${d.script_note ? `<div class="small"><b>Narration:</b> ${esc(d.script_note)}</div>` : ''}
    ${(d.open_questions || []).length ? `<div class="small mute mt-s">Still unknown: ${d.open_questions.map(esc).join(' · ')}</div>` : ''}${diff}</div>`;
}

function playbooks() {
  const pbs = D.playbooks;
  const live = pbs.filter(p => p.status === 'draft' || p.status === 'approved');
  const old = pbs.filter(p => p.status !== 'draft' && p.status !== 'approved');
  return `<h4 class="mt">Playbook <span class="mute small">only an approved version steers the factory</span></h4>
    ${live.map(playbookCard).join('') || `<div class="card pad mute">No Playbook yet. It can be drafted once ${D.state.min_graded} shorts have a 7-day grade (${D.rows.length} so far).</div>`}
    ${old.length ? `<details class="mt-s"><summary class="small mute">Older versions (${old.length})</summary>${old.map(playbookCard).join('')}</details>` : ''}
    <div class="card pad mt-s"><b class="small">Principles the Playbook may never override</b>
      <ul style="padding-left:18px">${D.pins.map(p => `<li class="small">${esc(p.text)} <button class="small link" data-pin-del="${p.id}">remove</button></li>`).join('') || '<li class="small mute">none</li>'}</ul>
      <div class="row" style="gap:8px"><input id="lr-pin" placeholder="For example: never make fun of real tragedies" style="flex:1"><button class="small" id="lr-pin-add">Pin</button></div></div>`;
}

function lifts() {
  if (!Object.keys(D.lifts).length) return `<h4 class="mt">What separates winners from flops</h4><div class="card pad mute">Nothing to show until a feature has at least 3 graded shorts.</div>`;
  const card = ([dim, title]) => {
    const items = D.lifts[dim];
    if (!items) return '';
    const top = Math.max(...items.map(i => i.lift), 1.5);
    return `<div class="card pad" style="flex:1;min-width:250px"><b class="small">${title}</b><table class="mt-s"><tbody>${items.map(i =>
      `<tr><td>${esc(i.key)}</td><td style="width:34%"><div style="height:8px;border-radius:4px;background:${i.lift >= 1 ? 'var(--accent)' : 'var(--mute)'};width:${Math.max(4, Math.round(100 * i.lift / top))}%"></div></td>
      <td style="text-align:right"><b>${i.lift.toFixed(2)}×</b></td><td class="mute small" title="videos behind it; winners / flops">n=${i.n} · ${Math.round(i.win_rate * 100)}%/${Math.round(i.flop_rate * 100)}%</td></tr>`).join('')}</tbody></table></div>`;
  };
  return `<h4 class="mt">What separates winners from flops <span class="mute small">lift on typical 7-day views; small groups are pulled towards 1×</span></h4><div class="row" style="gap:10px;flex-wrap:wrap;align-items:stretch">${DIMS.map(card).join('')}</div>`;
}

function calibration() {
  const c = D.calibration;
  const rho = v => v === null || v === undefined ? '<span class="mute">–</span>' : `<b>${v.toFixed(2)}</b>`;
  const adv = c.advice ? `<div class="mt-s small">${esc(c.advice.text)} <button class="small" id="lr-apply" data-t="${c.advice.threshold}">Set approve and make thresholds to ${c.advice.threshold}</button></div>` : '<div class="mt-s small mute">No clear score line yet.</div>';
  return `<h4 class="mt">Does our idea score predict results?</h4><div class="card pad"><div class="small">Total score against grade: ${rho(c.total)} <span class="mute">(${c.n} ideas; needs 5 or more)</span></div>
    <table class="mt-s small"><tbody>${Object.entries(c.parts).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, ' '))}</td><td style="text-align:right">${rho(v)}</td></tr>`).join('')}</tbody></table>${adv}
    <div class="mute small mt-s">Current thresholds: approve at ${D.state.approve_min}, make at ${D.state.min_score}.</div></div>`;
}

function hours() {
  const h = D.best_hours;
  if (!h.hour.length && !h.weekday.length) return '';
  const t = (title, list) => list.length ? `<div class="card pad" style="flex:1;min-width:230px"><b class="small">${title}</b><table class="mt-s small"><tbody>${list.map(i => `<tr><td>${esc(i.key)}</td><td style="text-align:right"><b>${i.lift.toFixed(2)}×</b></td><td class="mute">n=${i.n}</td></tr>`).join('')}</tbody></table></div>` : '';
  return `<h4 class="mt">Best time to upload <span class="mute small">India time; advice only, uploads stay manual</span></h4><div class="row" style="gap:10px;flex-wrap:wrap">${t('Time of day', h.hour)}${t('Weekday', h.weekday)}</div>`;
}

function experiments() {
  const ex = D.experiments;
  const names = {style: 'Picture style', tone: 'Tone', territory: 'Subject territory'};
  const how = {explore: 'tried something new', exploit: 'chosen from what worked', idea: "the idea's own pick", model: "the writer's own pick", rotation: 'plain rotation'};
  if (!Object.keys(ex).length) return `<h4 class="mt">Experiments</h4><div class="card pad mute small">Fills in once shorts are made while a Playbook is in use. Each choice is labelled exploring or exploiting, so we can see whether trying new things pays.</div>`;
  return `<h4 class="mt">Experiments <span class="mute small">median grade by how the choice was made</span></h4><div class="row" style="gap:10px;flex-wrap:wrap">${Object.entries(ex).map(([f, g]) =>
    `<div class="card pad" style="flex:1;min-width:230px"><b class="small">${names[f] || f}</b><table class="mt-s small"><tbody>${Object.entries(g).map(([src, v]) =>
      `<tr><td>${esc(how[src] || src)}</td><td style="text-align:right"><b>${v.median_grade}</b></td><td class="mute">n=${v.n}</td></tr>`).join('')}</tbody></table></div>`).join('')}</div>`;
}

function videosTable() {
  const rows = [...D.rows].sort((a, b) => b.grade - a.grade);
  const lab = {winner: badge('good', 'winner'), flop: badge('error', 'flop'), average: ''};
  return `<h4 class="mt">Graded shorts <span class="mute small">0 to 100 against the channel's own median: reach 40%, retention 30%, engagement 15%, growth 15%</span></h4>
    <div class="card" style="overflow:auto;max-height:420px"><table class="small"><thead><tr><th>Short</th><th>Grade</th><th></th><th style="text-align:right">7-day views</th><th style="text-align:right">Watched</th><th></th></tr></thead><tbody>${rows.map(r =>
      `<tr><td style="max-width:360px"><a href="https://youtube.com/shorts/${esc(r.video_id)}" target="_blank" rel="noopener">${esc(r.title)}</a><div class="mute">${when(r.published_at)} · ${r.source === 'app' ? 'made by the app' : 'older video'}${r.partial ? ' · no retention data' : ''}</div></td>
      <td style="width:130px"><div style="height:8px;border-radius:4px;background:var(--line)"><div style="height:8px;border-radius:4px;background:var(--accent);width:${Math.round(r.grade)}%"></div></div></td><td><b>${Math.round(r.grade)}</b> ${lab[r.label] || ''}</td>
      <td style="text-align:right">${num(r.v7)}</td><td style="text-align:right">${r.pct === null || r.pct === undefined ? '–' : r.pct.toFixed(0) + '%'}</td><td>${r.features && r.features.origin && r.features.origin !== 'generated' ? `<span class="badge">${esc(r.features.origin.split(':')[0])}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
}

function help() {
  let open = false;
  try { open = localStorage.getItem('learn-help') === '1'; } catch (e) { /* storage may be blocked */ }
  return `<details class="card pad mb-s" id="lr-help" ${open ? 'open' : ''}><summary><b>How this page works</b> <span class="mute small">what it learns, how to use it</span></summary>
    <div class="small mt-s" style="line-height:1.55">
    <p><b>What it is.</b> The loop that lets your channel's real results steer the idea factory. It grades every short, finds what separates winners from flops, writes that down as a <b>Playbook</b> for you to review, and only an approved Playbook changes how ideas, titles and scripts are made.</p>
    <p><b>What it learns from.</b> Only shorts published on or after the date at the top (1 Nov 2026 unless you change it). Anything older is ignored everywhere. A short is graded after its first 7 days are complete plus 2 days of buffer, so new shorts show up here about 9 days after upload.</p>
    <p><b>The grade (0 to 100).</b> Each short is compared with your channel's own typical short (the median, because Shorts views are very uneven): <b>reach</b> 40% (views in 7 days), <b>retention</b> 30% (share of the video watched), <b>engagement</b> 15% (likes, comments, shares per 1,000 views) and <b>growth</b> 15% (subscribers per 1,000 views). 50 means typical. The top quarter are <b>winners</b>, the bottom quarter <b>flops</b> (once 8 are graded). It needs 5 graded shorts before it trusts the baseline.</p>
    <p><b>Buttons.</b><br>
    <b>Regrade</b>: recompute every grade from the numbers already pulled (no model).<br>
    <b>Tag subjects</b>: puts each idea and short into a subject territory (history, science, crime and so on) so subjects can be compared.<br>
    <b>Draft a Playbook</b>: the model writes what to do more and less, each point citing real videos. Needs 6 graded shorts. A draft changes nothing.<br>
    <b>Sequels of winners</b>: new ideas from shorts at 3 times your typical reach or more.<br>
    <b>Ideas from comments</b>: new ideas from what viewers ask in the top comments.<br>
    <b>Run the whole cycle</b>: all of the above, then checks the new ideas. New ideas still go through the normal duplicate check and rating.</p>
    <p><b>Your part, step by step.</b><br>
    1. Wait until shorts have grades (the tiles show the count).<br>
    2. Press <b>Tag subjects</b>, then <b>Draft a Playbook</b>.<br>
    3. Read the draft. Untick any point you disagree with, then <b>Approve</b>. <b>Reject</b> throws it away. A new approved version replaces the old one.<br>
    4. Keep <b>Use the Playbook in idea generation</b> ticked. Now ideas, ratings, upload titles and scripts get the approved points. Untick it to go back to the old behaviour at once.<br>
    5. Add <b>pinned principles</b> for rules that must never be overridden (for example "every fact must be real"). They apply whenever the switch is on.</p>
    <p><b>Explore 30 to 40%.</b> That share of choices (subject, picture style, tone) deliberately takes the least-tried option, so new things get a chance. The rest favour what worked. A choice with 4 or more flops and no winner rests for 14 days. Each idea remembers whether it was an explore or exploit choice, so the <b>Experiments</b> block can show whether trying new things pays.</p>
    <p><b>Daily feedback cycle.</b> When ticked, the autopilot grades, tags, drafts a Playbook (when 3 or more new shorts are graded, or at least weekly when something new is graded) and proposes ideas. It never approves anything.</p>
    <p><b>The blocks below.</b><br>
    <b>Playbook</b>: drafts to review, the approved one in use, and what changed against the last version.<br>
    <b>What separates winners from flops</b>: for each feature, a lift (1.0 = typical, 2.0 = twice as good) shrunk for small samples. Groups under 3 shorts are hidden. Treat anything under 6 shorts as a hint.<br>
    <b>Does our idea score predict results?</b>: compares your idea score with the real grade. If it does not, the page suggests a better approval threshold with an Apply button.<br>
    <b>Best time to upload</b>, <b>Experiments</b> (explore against exploit) and <b>Graded shorts</b> (every graded short with its grade).</p>
    <p class="mute">Small numbers lie: with few shorts everything here is an early signal. It gets better every week as more shorts are graded.</p></div></details>`;
}

function draw() {
  host.innerHTML = `${help()}${controls()}<div class="mt">${tiles()}</div>${playbooks()}${lifts()}${calibration()}${hours()}${experiments()}${videosTable()}`;
  const q = id => document.getElementById(id);
  q('lr-help').ontoggle = e => { try { localStorage.setItem('learn-help', e.target.open ? '1' : '0'); } catch (err) { /* ignore */ } };
  const cfg = patch => act(null, () => api('/shorts/ideas/config', {method: 'PUT', json: patch})).then(load);
  q('lr-use').onchange = e => cfg({use_playbook: e.target.checked});
  q('lr-explore').onchange = e => cfg({explore: parseFloat(e.target.value)});
  q('lr-auto').onchange = e => cfg({auto_feedback: e.target.checked});
  q('lr-refresh').onclick = async e => { await act(e.currentTarget, () => api('/feedback/refresh', {method: 'POST'}), 'Regraded'); load(); };
  q('lf-change').onclick = async e => { e.preventDefault(); const d = (prompt('Learn only from shorts published on or after (YYYY-MM-DD, India time):', new Date(D.learn_from * 1000 + 19800000).toISOString().slice(0, 10)) || '').trim(); if (!d) return; await act(null, () => api('/feedback/learn-from', {method: 'POST', json: {date: d}}), 'Saved'); load(); };
  q('lr-tag').onclick = e => runJob(e.currentTarget, '/feedback/tag', 'Tagging');
  q('lr-draft').onclick = e => runJob(e.currentTarget, '/feedback/playbook/draft', 'Playbook');
  q('lr-seq').onclick = e => runJob(e.currentTarget, '/feedback/sequels', 'Sequels');
  q('lr-com').onclick = e => runJob(e.currentTarget, '/feedback/comments/ideas', 'Comment ideas');
  q('lr-cycle').onclick = e => runJob(e.currentTarget, '/feedback/cycle', 'Cycle');
  host.querySelectorAll('[data-approve]').forEach(b => b.onclick = async () => {
    const ok = await dialog({title: 'Use this Playbook?', html: '<p>From now on its items steer idea generation, rating, titles and scripts. You can switch it off or untick single items at any time.</p>', buttons: [{label: 'Cancel', value: false}, {label: 'Approve', value: true, primary: true}]});
    if (ok === true) { await act(b, () => api(`/feedback/playbooks/${b.dataset.approve}/approve`, {method: 'POST'}), 'Playbook approved'); load(); }
  });
  host.querySelectorAll('[data-reject]').forEach(b => b.onclick = async () => { await act(b, () => api(`/feedback/playbooks/${b.dataset.reject}/reject`, {method: 'POST'})); load(); });
  host.querySelectorAll('[data-toggle]').forEach(c => c.onchange = async () => { await act(null, () => api(`/feedback/playbooks/${c.dataset.toggle}/toggle`, {method: 'POST', json: {key: c.dataset.key}})); load(); });
  host.querySelectorAll('[data-pin-del]').forEach(b => b.onclick = async () => { await act(b, () => api(`/feedback/pins/${b.dataset.pinDel}`, {method: 'DELETE'})); load(); });
  q('lr-pin-add').onclick = async () => { const t = q('lr-pin').value.trim(); if (!t) return; await act(null, () => api('/feedback/pins', {method: 'POST', json: {text: t}})); load(); };
  const ap = q('lr-apply');
  if (ap) ap.onclick = async () => {
    const ok = await dialog({title: 'Change the thresholds?', html: `<p>Ideas are auto-approved and made from a score of <b>${ap.dataset.t}</b> upward.</p>`, buttons: [{label: 'Cancel', value: false}, {label: 'Change', value: true, primary: true}]});
    if (ok === true) { await act(ap, () => api('/feedback/calibration/apply', {method: 'POST', json: {threshold: parseFloat(ap.dataset.t)}}), 'Thresholds changed'); load(); }
  };
}
})();
