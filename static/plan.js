/* Video plan screen (Phase 2): story -> blueprint -> Hindi narration -> storyboard. Uses the helpers of index.html. */
(() => {
const css = document.createElement('style');
css.textContent = `
.plan-steps{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.plan-steps span{padding:3px 12px;border-radius:99px;border:1px solid var(--line);font-size:13px;color:var(--mute)}
.plan-steps span.on{border-color:var(--accent);color:var(--ink);font-weight:600}.plan-steps span.done{color:var(--ok);border-color:var(--ok)}
.seg{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0;background:var(--panel)}
.seg.locked{border-left:4px solid var(--accent)}.seg.approved{border-left:4px solid var(--ok)}
.sent{display:grid;grid-template-columns:1fr 112px 64px 28px;gap:6px;align-items:start;margin:4px 0}
.sent textarea{min-height:42px;font-size:15px;line-height:1.5}
.strip{display:flex;height:34px;border-radius:8px;overflow:hidden;border:1px solid var(--line);margin:8px 0}
.strip i{display:block;border-right:1px solid var(--panel);min-width:2px;cursor:pointer}
.scn{display:grid;grid-template-columns:96px 1fr;gap:14px;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0;background:var(--panel)}
.scn.stale{border-left:4px solid var(--warn)}.scn.approved{border-left:4px solid var(--ok)}.scn.locked{border-left:4px solid var(--accent)}
.scn .tm{font-variant-numeric:tabular-nums;font-size:13px}.vt{font-size:12px;border-radius:6px;padding:1px 8px;color:#fff;font-weight:600;white-space:nowrap}
.needbox{background:var(--infobg);color:var(--info);padding:6px 10px;border-radius:8px;margin-top:6px;font-size:13px}
.iss{font-size:12px;margin-top:4px}.iss.error{color:var(--bad)}.iss.warn{color:var(--warn)}
.assetrow{display:grid;grid-template-columns:90px 1fr auto;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.beatrow{display:grid;grid-template-columns:40px 150px 1fr 1fr;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:14px}
@media (max-width:760px){.scn{grid-template-columns:1fr}.sent{grid-template-columns:1fr 100px}.beatrow{grid-template-columns:36px 1fr}}
`;
document.head.append(css);

const VT = ['reconstruction', 'establishing', 'character', 'metaphor', 'object_process', 'montage', 'map_timeline', 'data_chart',
  'document_archival', 'screen_interface', 'diagram', 'comparison', 'text_led', 'minimalist', 'atmospheric', 'transition'];
const VT_LABEL = {reconstruction: 'Reconstruction', establishing: 'Establishing', character: 'Character', metaphor: 'Metaphor', object_process: 'Object / process',
  montage: 'Montage', map_timeline: 'Map / timeline', data_chart: 'Chart', document_archival: 'Document', screen_interface: 'Screen', diagram: 'Diagram',
  comparison: 'Comparison', text_led: 'Text-led', minimalist: 'Minimalist', atmospheric: 'Atmospheric', transition: 'Transition'};
const vtColor = t => `hsl(${(VT.indexOf(t) * 47 + 200) % 360} 45% 38%)`;
const EMO = ['neutral', 'happy', 'sad', 'anger', 'fear', 'clear'];
const mmss = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const A = {done: 'done', running: 'running'};

window.planLinks = async function (cid, status) {            // used by the story drawer
  const ps = await api('/plans?candidate_id=' + cid).catch(() => []);
  return `<h4>Video plans</h4>${ps.length ? `<ul class="tight">${ps.map(p => `<li><a href="#/plan/${p.id}">Open plan ${esc(p.id)}</a> <span class="mute small">${esc(p.status)} · ${fmtDate(p.updated_at)}</span></li>`).join('')}</ul>` : '<div class="mute small">No video plan yet.</div>'}
    <div class="row mt-s"><button class="small" onclick="newPlan('${cid}', '${status}')">+ Make a video plan from this story</button></div>`;
};
window.tabPlans = async function (id) {
  const el = $('#tab');
  el.innerHTML = '<div class="pad"><div class="skel"></div><div class="skel"></div></div>';
  const [stories, plans] = await Promise.all([api(`/projects/${id}/stories?status=approved&sort=priority`), api('/plans?project_id=' + id)]);
  const pend = PR && PR.next ? PR.next.counts.pending : 0;
  const stepChip = (ok, label) => `<span class="${ok ? 'ok' : 'mute'}">${ok ? '✓' : '○'} ${label}</span>`;
  const planCard = p => `<div class="row small" style="gap:14px;padding:6px 0;border-top:1px solid var(--line)"><a href="#/plan/${esc(p.id)}"><b>Open plan</b></a>
      ${stepChip(p.blueprint, 'blueprint')}${stepChip(p.beats && p.beats_written >= p.beats, `narration ${p.beats_written}/${p.beats || '?'} parts`)}${stepChip(p.scenes > 0, `${p.scenes} scenes`)}
      <span class="mute">${p.spoken_s ? Math.round(p.spoken_s / 60 * 10) / 10 + ' min spoken · ' : ''}${esc(p.format)} · ${fmtDate(p.updated_at)}</span></div>`;
  el.innerHTML = `<div class="card pad"><b>From story to video</b>
      <div class="mute">For each approved story you can make a video plan: how to tell it, Hindi narration for a first-person narrator, and a storyboard with timing. Nothing in it refers to the source or quotes it. Image prompts come next.</div></div>
    ${stories.length ? stories.map(s => { const ps = plans.filter(p => p.candidate_id === s.id); return `<div class="card pad mt"><div class="row"><div style="flex:1;min-width:240px"><b>${esc(s.title)}</b> ${natBadge(s.nature)}<div class="mute">${esc(s.premise)}</div>
        <div class="mute small">${esc(s.id)} · priority ${Math.round(s.eff_priority)} · completeness ${Math.round(s.completeness)}</div></div>
        <button class="${ps.length ? '' : 'primary'}" onclick="newPlan('${s.id}','approved')">${ps.length ? '+ Another plan' : 'Make a video plan'}</button></div>${ps.map(planCard).join('')}</div>`; }).join('')
      : `<div class="big-empty mute">No approved stories yet. Open the Stories tab, approve the ones you want to turn into videos, then come back here.</div>`}
    ${pend && stories.length ? `<div class="mute small mt">${pend} more stor${pend === 1 ? 'y is' : 'ies are'} still waiting for review in the Stories tab.</div>` : ''}
    ${plans.filter(p => !stories.some(s => s.id === p.candidate_id)).length ? `<h4>Plans for stories that are no longer approved</h4>${plans.filter(p => !stories.some(s => s.id === p.candidate_id)).map(planCard).join('')}` : ''}`;
};
window.newPlan = async function (cid, status) {
  let allow = false;
  if (status !== 'approved') {
    if (!await confirmDlg('This story is not approved yet', 'A video plan is normally made from an approved story. You can continue, and approve the story later.', 'Make the plan anyway')) return;
    allow = true;
  }
  const r = await act(null, () => api('/plans', {method: 'POST', json: {candidate_id: cid, allow_unapproved: allow}}));
  if (r) location.hash = '#/plan/' + r.id;
};

window.viewPlan = async function (id) {
  const my = route_id;
  let P = null, sig = '', seenRun = false;
  const app = $('#app');
  const busyJob = () => P && P.job && P.job.state === 'running';
  const editing = () => { const a = document.activeElement; return a && a.closest && a.closest('#plan') && ['TEXTAREA', 'INPUT', 'SELECT'].includes(a.tagName); };

  async function load(force) {
    const p = await api('/plans/' + id);
    const s = JSON.stringify([p.rev, p.job.state, p.job.done, p.job.label, p.segments.map(x => x.rev), p.scenes.map(x => [x.rev, x.stale, x.start_s, x.status, x.locked]), p.assets.map(x => x.rev), p.validation ? 1 : 0, p.narrator.name]);
    const changed = s !== sig; P = p;
    if (changed || force) { sig = s; if (!editing() || force) render(); }
    if (p.job.state === 'running') seenRun = true;
    if (seenRun && p.job.state !== 'running') { seenRun = false; if (p.job.state === 'error') toast('Stopped: ' + p.job.error, {bad: true}); else if (p.job.state === 'done') toast('Finished: ' + p.job.kind); }
  }
  const tick = async () => { if (my !== route_id) return; try { await load(); } catch (e) { /* keep polling */ } timer = setTimeout(tick, busyJob() ? 1500 : 4000); };

  const run = (btn, path, json, label) => act(btn, async () => { const r = await api(path, {method: 'POST', json: json || {}}); await load(true); return r; });
  window._plan = {
    async blueprint(b) { if (P.blueprint && P.segments.length && !await confirmDlg('Plan the story again?', 'The new plan can change the beats. Narration you approved or locked is kept; the rest is replaced when you write it again.', 'Plan again')) return; await run(b, `/plans/${id}/blueprint`); },
    async narration(b, missing) { await run(b, `/plans/${id}/narration`, {only_missing: !!missing}); },
    async beat(b, beat) { await run(b, `/plans/${id}/narration`, {beat_ids: [beat]}); },
    async registry(b) { await run(b, `/plans/${id}/registry`); },
    async storyboard(b) { await run(b, `/plans/${id}/storyboard`); },
    async cancel(b) { await act(b, () => api(`/plans/${id}/cancel`, {method: 'POST'}), 'Stopping after this step…'); },
    async fixRepeats(b) { if (!await confirmDlg('Redraw scenes that repeat the camera?', 'Each flagged scene is redrawn with a different camera distance and angle, keeping the same idea. Locked and approved scenes are skipped. About 30 seconds per scene.', 'Redraw them')) return; await run(b, `/plans/${id}/fix-repeats`); },
    async validate(b) { const r = await act(b, () => api(`/plans/${id}/validate`, {method: 'POST'})); if (r) { await load(true); toast(r.ok ? 'No blocking problems found' : 'Some problems need attention'); } },
    async narrator(el) { await act(null, () => api(`/plans/${id}/narrator`, {method: 'PATCH', json: {name: el.value}}), 'Narrator name saved'); await load(true); },
    async minutes(el) { await act(null, () => api(`/plans/${id}/settings`, {method: 'PATCH', json: {minutes: +el.value}}), 'Target length saved'); await load(true); },
    async delPlan() { if (!await confirmDlg('Delete this plan?', 'The story itself is not touched. Narration and storyboard of this plan are removed.', 'Delete', true)) return; await act(null, () => api(`/plans/${id}`, {method: 'DELETE'}), 'Plan deleted'); location.hash = '#/p/' + P.project_id + '/stories'; },
    async segSave(sid) {
      const box = document.querySelector(`[data-seg="${sid}"]`);
      const sentences = [...box.querySelectorAll('.sent')].map(r => ({text: r.querySelector('textarea').value.trim(), emotion: r.querySelector('select').value, pause_after_s: +r.querySelector('input').value || 0})).filter(x => x.text);
      if (!sentences.length) return toast('A segment needs at least one sentence', {bad: true});
      await act(null, () => api(`/plans/segments/${sid}`, {method: 'PATCH', json: {sentences}}), 'Saved. Scenes for this part were kept and spread over the new sentences; check them.'); await load(true);
    },
    async segAddSentence(sid) { const box = document.querySelector(`[data-seg="${sid}"] .sents`); box.insertAdjacentHTML('beforeend', sentRow({text: '', emotion: 'neutral', pause_after_s: 0}, sid)); box.lastElementChild.querySelector('textarea').focus(); },
    async segRemoveSentence(btn, sid) { btn.closest('.sent').remove(); await window._plan.segSave(sid); },
    async segSet(sid, f) { await act(null, () => api(`/plans/segments/${sid}`, {method: 'PATCH', json: f})); await load(true); },
    async segMove(sid, d) { await act(null, () => api(`/plans/segments/${sid}/move`, {method: 'POST', json: {direction: d}})); await load(true); },
    async sceneSet(sid, f) { await act(null, () => api(`/plans/scenes/${sid}`, {method: 'PATCH', json: f})); await load(true); },
    async sceneRedraw(b, sid) {
      const note = await textDlg('Redraw this scene', 'What should change? (optional) For example: a wider shot, show the desk from behind.', '', true); if (note === null) return;
      await run(b, `/plans/scenes/${sid}/regenerate`, {note});
    },
    async sceneEdit(sid) {
      const s = P.scenes.find(x => x.id === sid), d = s.data, c = d.composition;
      const f = (k, l, v, rows = 1) => `<label class="f mt-s">${l}${rows > 1 ? `<textarea data-k="${k}" style="min-height:${rows * 24}px">${esc(v || '')}</textarea>` : `<input data-k="${k}" value="${esc(v || '')}">`}</label>`;
      const patch = await dialog({title: 'Edit scene', html: `<label class="f">Visual type<select data-k="visual_type">${VT.map(t => `<option value="${t}" ${t === d.visual_type ? 'selected' : ''}>${VT_LABEL[t]}</option>`).join('')}</select></label>
        ${f('narrative.purpose', 'Why this scene exists', d.narrative.purpose, 2)}${f('narrative.new_information', 'What is new for the viewer', d.narrative.new_information, 2)}
        ${f('subject', 'Main subject', d.subject, 2)}${f('action', 'What visibly happens', d.action, 2)}${f('setting.location', 'Where', d.setting.location)}
        ${f('composition.position', 'Where the subject sits in the frame', c.position)}${f('composition.distance', 'Camera distance', c.distance)}${f('composition.camera_angle', 'Camera angle', c.camera_angle)}
        ${f('lighting', 'Lighting', d.lighting, 2)}${f('palette', 'Colours', d.palette)}`,
        buttons: [{label: 'Cancel', value: null}, {label: 'Save', primary: true, collect: l => { const o = {}; l.querySelectorAll('[data-k]').forEach(e => { const k = e.dataset.k; const old = k.split('.').reduce((a, x) => a && a[x], d); if (e.value !== (old || '')) o[k] = e.value; }); return o; }}]});
      if (patch && Object.keys(patch).length) { await act(null, () => api(`/plans/scenes/${sid}`, {method: 'PATCH', json: patch}), 'Scene saved'); await load(true); }
    },
    async assetLock(aid, on) { await act(null, () => api(`/plans/assets/${aid}`, {method: 'PATCH', json: {locked: on}})); await load(true); },
    async assetEdit(aid) {
      const a = P.assets.find(x => x.id === aid); const v = await textDlg('Edit ' + a.name, 'Approved look (what must stay consistent in every scene)', a.data.description || '', true); if (v === null) return;
      await act(null, () => api(`/plans/assets/${aid}`, {method: 'PATCH', json: {description: v}}), 'Saved'); await load(true);
    },
    jump(sid) { const e = document.getElementById('sc-' + sid); if (e) e.scrollIntoView({behavior: 'smooth', block: 'center'}); },
  };

  const sentRow = (x, sid) => `<div class="sent"><textarea lang="hi" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'" onchange="_plan.segSave('${sid}')">${esc(x.text)}</textarea>
    <select onchange="_plan.segSave('${sid}')" title="How this sentence is spoken">${EMO.map(e => `<option ${e === x.emotion ? 'selected' : ''}>${e}</option>`).join('')}</select>
    <input type="number" min="0" max="10" step="0.2" value="${x.pause_after_s || 0}" onchange="_plan.segSave('${sid}')" title="Pause after the sentence, in seconds">
    <button class="small" title="Remove this sentence" onclick="_plan.segRemoveSentence(this,'${sid}')">×</button></div>`;

  function nextStep() {
    const missingBeats = P.blueprint ? P.blueprint.beats.filter(b => !P.segments.some(s => s.beat === b.id)) : [];
    const segNoScene = P.segments.filter(s => !P.scenes.some(c => c.segment_id === s.id));
    if (!P.readiness.ready) return ['problem', 'This story cannot be planned yet', P.readiness.checks.filter(c => c.level === 'blocked').map(c => c.text).join(' '), null];
    if (!P.blueprint) return ['action', 'Step 1: plan how to tell the story', 'The model reads the story facts and proposes a structure and 5 to 9 beats. It takes about a minute. You review it before any narration is written.', ['Plan the story', 'blueprint']];
    if (missingBeats.length) return ['action', P.segments.length ? `Narration is missing for ${missingBeats.length} beat(s)` : 'Step 2: write the narration', 'Hindi, first person, one beat at a time (about 40 seconds each). Each beat appears as soon as it is written, and you can edit it while the rest is being written.', [P.segments.length ? 'Write the missing beats' : 'Write the narration', 'narration', !!P.segments.length]];
    if (segNoScene.length) return ['action', P.scenes.length ? `${segNoScene.length} narration part(s) have no scenes` : 'Step 3: design the storyboard', 'First the recurring people, places and style are listed, then every sentence gets a scene with timing. Edit the narration first if you want changes; the scenes follow it.', [P.scenes.length ? 'Design the missing scenes' : 'Design the storyboard', 'storyboard']];
    const v = P.validation && P.validation.storyboard;
    return ['good', 'Step 4: review and check', 'Edit anything, approve or lock what is final, then run the check. Locked and approved parts are never overwritten when you regenerate something else.', ['Check everything', 'validate']];
  }

  function render() {
    const p = P, cur = nextStep(), j = p.job, running = j.state === 'running';
    const steps = [['Story', true], ['Blueprint', !!p.blueprint], ['Narration', p.segments.length && p.blueprint && !p.blueprint.beats.some(b => !p.segments.some(s => s.beat === b.id))], ['Storyboard', p.scenes.length && !p.segments.some(s => !p.scenes.some(c => c.segment_id === s.id))]];
    const firstOpen = steps.findIndex(s => !s[1]);
    const dis = running ? 'disabled' : '';
    const btnFn = {blueprint: 'blueprint', narration: 'narration', storyboard: 'storyboard', validate: 'validate'};
    const v = p.validation || {}, vs = v.storyboard;
    const issues = [...(v.issues || []).map(i => ({...i, part: 'Narration'})), ...((vs && vs.issues) || []).map(i => ({...i, part: 'Storyboard'}))];
    const sceneAt = wid => { const sc = p.scenes.find(x => x.id === wid); return sc ? sc : null; };
    const groups = []; for (const i of issues) { const k = i.part + '|' + i.kind + '|' + (i.kind === 'repeat' ? '' : i.text); let g = groups.find(x => x.k === k); if (!g) groups.push(g = {k, i, where: []}); g.where.push(i.where); }
    groups.sort((a, b) => (a.i.level === 'error' ? 0 : 1) - (b.i.level === 'error' ? 0 : 1));
    const nRepeat = issues.filter(i => i.kind === 'repeat').length;
    const segName = sid => { const s = p.segments.find(x => x.id === sid); const b = s && p.blueprint && p.blueprint.beats.find(x => x.id === s.beat); return b ? b.name : sid; };
    const ordered = [...p.scenes].sort((a, b) => a.start_s - b.start_s);
    const total = p.duration_s || 1;
    app.innerHTML = `<div id="plan">
      <div class="row"><a href="#/p/${esc(p.project_id)}/stories?s=${esc(p.candidate_id)}">← Back to the story</a><span class="sp"></span><button class="small" onclick="_plan.delPlan()">Delete plan</button></div>
      <div class="row mt-s"><h2 style="margin:0">Video plan</h2>${badge('info', p.format + ' long-form')}${badge('warn', 'facts not independently verified')}<span class="mute small">${esc(p.id)}</span></div>
      <div class="plan-steps">${steps.map(([l, ok], i) => `<span class="${ok ? 'done' : i === firstOpen ? 'on' : ''}">${ok ? '✓ ' : ''}${l}</span>`).join('')}</div>
      <div class="card pad"><div class="row"><label class="f" style="min-width:230px">Narrator name (first person; set later)<input id="nname" value="${esc(p.narrator.name || '')}" placeholder="not set yet" onchange="_plan.narrator(this)"></label>
        <label class="f" style="width:150px">Target length (min)<input type="number" min="1" max="40" step="0.5" value="${p.settings.minutes}" onchange="_plan.minutes(this)"></label>
        <span class="mute small" style="flex:1;min-width:240px">The narrator is a guide: "I" shows and reacts, and never claims to have been there. Nothing refers to a book, an author or a source, and nothing is quoted.</span></div></div>
      ${running ? `<div class="card pad mt" style="border-left:4px solid var(--accent)"><div class="row"><b>Working: ${esc(j.kind)}</b><span class="mute">${esc(j.label)}</span><span class="sp"></span><span class="mute small">${hd(j.elapsed_s)} elapsed${j.eta_s ? ' · about ' + hd(j.eta_s) + ' left' : ''}</span><button class="small" onclick="_plan.cancel(this)">Stop after this step</button></div>${bar(j.total ? 100 * j.done / j.total : 5)}<div class="small mute mt-s">You can leave this page. Finished parts are saved as they complete.</div></div>`
        : j.state === 'error' ? `<div class="errbox mt">The last step stopped: ${esc(j.error)} Finished parts are kept; press the button again to continue.</div>` : ''}
      <div class="card pad mt" style="border-left:4px solid var(--${cur[0] === 'problem' ? 'bad' : cur[0] === 'good' ? 'ok' : 'accent'})"><div class="row"><div style="flex:1;min-width:260px"><b>${esc(cur[1])}</b><div class="mute">${esc(cur[2])}</div></div>
        ${cur[3] ? `<button class="primary" ${dis} onclick="_plan.${btnFn[cur[3][1]]}(this${cur[3][2] ? ',true' : ''})">${esc(cur[3][0])}</button>` : ''}</div></div>

      <details class="card pad mt" ${p.blueprint ? '' : 'open'}><summary><b>Is the story ready?</b> ${badge(p.readiness.level === 'ok' ? 'good' : p.readiness.level === 'blocked' ? 'problem' : 'warn', p.readiness.level)}</summary>
        <ul class="tight mt-s">${p.readiness.checks.map(c => `<li><span class="${c.level === 'blocked' ? 'err' : ''}">${c.level === 'blocked' ? '✗' : '•'}</span> ${esc(c.text)}</li>`).join('')}</ul></details>

      ${p.blueprint ? `<div class="card pad mt"><div class="row"><h3 style="margin:0">Blueprint</h3>${badge('info', p.blueprint.structure.replace(/_/g, ' '))}<span class="sp"></span><button class="small" ${dis} onclick="_plan.blueprint(this)">Plan again</button></div>
        <div class="mt-s"><b>Viewer promise:</b> ${esc(p.blueprint.viewer_promise)}</div><div><b>Central question:</b> ${esc(p.blueprint.central_question)}</div><div class="mute small">${esc(p.blueprint.why_structure)}</div>
        <div class="mt-s">${p.blueprint.beats.map(b => `<div class="beatrow"><b>${esc(b.id)}</b><span>${esc(b.name)}</span><span>${esc(b.purpose)}</span><span class="mute">${esc(b.takeaway)}</span></div>`).join('')}</div></div>` : ''}

      ${p.segments.length ? `<div class="mt"><div class="row"><h3 style="margin:0">Narration (Hindi)</h3><span class="mute">${mmss(p.duration_s)} spoken · target ${mmss(p.settings.minutes * 60)}</span></div>
        ${p.segments.map((s, i) => `<div class="seg ${s.locked ? 'locked' : s.status === 'approved' ? 'approved' : ''}" data-seg="${s.id}">
          <div class="row"><b>${esc(segName(s.id))}</b><span class="mute small">${mmss(s.duration_s)} · ${s.sentences.length} sentences</span>${badge(s.status === 'approved' ? 'approved' : s.status === 'edited' ? 'info' : 'queued', s.status)}${s.locked ? badge('info', 'locked') : ''}<span class="sp"></span>
            <button class="small" ${i ? '' : 'disabled'} title="Move earlier" onclick="_plan.segMove('${s.id}',-1)">↑</button><button class="small" ${i < p.segments.length - 1 ? '' : 'disabled'} title="Move later" onclick="_plan.segMove('${s.id}',1)">↓</button>
            <button class="small" ${dis} onclick="_plan.beat(this,'${s.beat}')" title="Write this beat again">Rewrite</button>
            <button class="small" onclick="_plan.segSet('${s.id}',{status:'${s.status === 'approved' ? 'draft' : 'approved'}'})">${s.status === 'approved' ? 'Unapprove' : 'Approve'}</button>
            <button class="small" onclick="_plan.segSet('${s.id}',{locked:${!s.locked}})">${s.locked ? 'Unlock' : 'Lock'}</button></div>
          <div class="sents mt-s">${s.sentences.map(x => sentRow(x, s.id)).join('')}</div>
          <div class="row mt-s"><button class="small" onclick="_plan.segAddSentence('${s.id}')">+ sentence</button><span class="mute small">emotion and pause are how it is spoken; change the words freely, the scenes follow.</span></div>
          <details class="mt-s"><summary class="small mute">Text sent to the voice (Svara)</summary><div class="passage small" lang="hi">${esc(s.annotated)}</div></details>
          ${(s.issues || []).map(i => `<div class="iss ${i.kind === 'svara' || i.kind === 'script' ? 'error' : 'warn'}">⚠ ${esc(i.kind.replace(/_/g, ' '))}: ${esc(i.text)}</div>`).join('')}</div>`).join('')}</div>` : ''}

      ${p.segments.length ? `<div class="mt"><div class="row"><h3 style="margin:0">Continuity: recurring people, places and style</h3><span class="sp"></span><button class="small" ${dis} onclick="_plan.registry(this)">${p.assets.length ? 'List again' : 'List them'}</button></div>
        <div class="card pad mt-s">${p.assets.length ? p.assets.map(a => `<div class="assetrow"><span>${badge('info', a.kind)}</span><div><b>${esc(a.name)}</b> ${a.data.fictionalisation ? `<span class="mute small">${esc(a.data.fictionalisation.replace(/_/g, ' '))}</span>` : ''}<div>${esc(a.data.description || (a.kind === 'narrator' ? 'Avatar to be designed (outside this module).' : ''))}</div>${(a.data.fixed || []).length ? `<div class="mute small">always: ${esc(a.data.fixed.join('; '))}</div>` : ''}</div>
          <div class="row"><button class="small" onclick="_plan.assetEdit('${a.id}')">Edit</button><button class="small" onclick="_plan.assetLock('${a.id}',${!a.locked})">${a.locked ? 'Unlock' : 'Lock'}</button></div></div>`).join('') : '<span class="mute">Not listed yet. It happens automatically when you design the storyboard.</span>'}</div></div>` : ''}

      ${p.scenes.length ? `<div class="mt"><div class="row"><h3 style="margin:0">Storyboard</h3><span class="mute">${p.scenes.length} scenes · ${mmss(total)}</span><span class="sp"></span><button class="small" ${dis} onclick="_plan.validate(this)">Check everything</button></div>
        <div class="strip" title="Each block is a scene; width is how long it is on screen">${ordered.map(s => `<i style="width:${100 * s.duration_s / total}%;background:${vtColor(s.data.visual_type)}" onclick="_plan.jump('${s.id}')" title="${mmss(s.start_s)} ${VT_LABEL[s.data.visual_type]}: ${esc(s.data.subject)}"></i>`).join('')}</div>
        <div class="small mute">${[...new Set(ordered.map(s => s.data.visual_type))].map(t => `<span style="color:${vtColor(t)}">■</span> ${VT_LABEL[t]}`).join(' &nbsp; ')}</div>
        ${ordered.map(s => { const d = s.data, c = d.composition; return `<div class="scn ${s.stale ? 'stale' : s.locked ? 'locked' : s.status === 'approved' ? 'approved' : ''}" id="sc-${s.id}">
          <div class="tm"><b>${mmss(s.start_s)}–${mmss(s.end_s)}</b><div class="mute">${s.duration_s.toFixed(1)}s</div><div class="mute small">${esc(segName(s.segment_id))} · s${s.s_from}${s.s_to > s.s_from ? '–' + s.s_to : ''}</div></div>
          <div><div class="row"><span class="vt" style="background:${vtColor(d.visual_type)}">${VT_LABEL[d.visual_type]}</span>${s.stale ? badge('warn', 'narration changed: check') : ''}${s.status === 'approved' ? badge('approved', 'approved') : ''}${s.locked ? badge('info', 'locked') : ''}${d.feasibility.level === 'needs_asset' ? badge('info', 'needs a real asset') : ''}<span class="sp"></span>
              <button class="small" onclick="_plan.sceneSet('${s.id}',{status:'${s.status === 'approved' ? 'draft' : 'approved'}'})">${s.status === 'approved' ? 'Unapprove' : 'Approve'}</button><button class="small" onclick="_plan.sceneSet('${s.id}',{locked:${!s.locked}})">${s.locked ? 'Unlock' : 'Lock'}</button>
              <button class="small" ${s.locked ? 'disabled' : ''} onclick="_plan.sceneEdit('${s.id}')">Edit</button><button class="small" ${s.locked || running ? 'disabled' : ''} onclick="_plan.sceneRedraw(this,'${s.id}')">Redraw</button></div>
            <div class="mt-s"><b>${esc(d.subject)}</b> — ${esc(d.action)}</div>
            <div class="mute small mt-s">Why: ${esc(d.narrative.purpose)} · New: ${esc(d.narrative.new_information)}</div>
            <div class="small mt-s">${[d.setting.location, c.position && 'subject ' + c.position, c.distance, c.camera_angle, d.lighting, d.palette].filter(Boolean).map(esc).join(' · ')}</div>
            ${d.feasibility.level === 'needs_asset' ? `<div class="needbox"><b>Needs:</b> ${esc(d.feasibility.needs_asset)}<br><b>Until then:</b> ${esc(d.feasibility.fallback)}</div>` : ''}
            ${d.text_on_screen.length ? `<div class="small mt-s">On-screen text: ${d.text_on_screen.map(t => '“' + esc(t.text) + '”').join(', ')}</div>` : ''}
            ${(s.issues || []).map(i => `<div class="iss ${i.level}">${i.level === 'error' ? '✗' : '⚠'} ${esc(i.kind.replace(/_/g, ' '))}: ${esc(i.text)}</div>`).join('')}</div></div>`; }).join('')}</div>` : ''}

      ${issues.length || v.ok != null || vs ? `<div class="card pad mt"><h3 style="margin:0 0 6px">Check results</h3>${groups.length ? `<ul class="tight">${groups.map(g => `<li class="${g.i.level === 'warn' ? '' : 'err'}"><b>${g.i.level === 'warn' ? 'Check' : 'Fix'}</b> · ${esc(g.i.part)} · ${esc((g.i.kind || '').replace(/_/g, ' '))}: ${esc(g.i.kind === 'repeat' ? `${g.where.length} scene(s) use the same camera distance and angle as the scene before` : g.i.text)}
          <div class="small mute">${g.where.map(w => { const sc = sceneAt(w); return sc ? `<a href="#" onclick="_plan.jump('${sc.id}');return false">${mmss(sc.start_s)}</a>` : esc(w === 'plan' ? 'whole plan' : (segName(w) || w)); }).join(' · ')}</div></li>`).join('')}</ul>
        ${nRepeat ? `<div class="row mt-s"><button ${dis} onclick="_plan.fixRepeats(this)">Fix the ${nRepeat} camera repeats automatically</button><span class="mute small">Redraws only those scenes, one by one.</span></div>` : ''}` : '<span class="ok">✓ No problems found.</span>'}
        <div class="mute small mt-s">Narration ${mmss(v.duration_s || 0)} · scenes add up to ${vs ? mmss(vs.scene_seconds) : '–'} · copied wording ${Math.round((v.copied_share || 0) * 100)}%</div></div>` : ''}
    </div>`;
    document.querySelectorAll('.sent textarea').forEach(t => { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; });
  }

  app.innerHTML = '<div class="pad"><div class="skel"></div><div class="skel"></div></div>';
  try { await load(true); } catch (e) { app.innerHTML = `<div class="errbox">${esc(e.message)}</div><a href="#/">Back</a>`; return; }
  timer = setTimeout(tick, 2500);
};
})();
