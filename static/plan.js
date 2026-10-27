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
.plan-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px;align-items:start;margin-top:14px}
.plan-side{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}
.act{display:flex;gap:10px;align-items:flex-start;margin:7px 0}.act .an{width:24px;height:24px;border-radius:50%;border:1px solid var(--line);display:grid;place-items:center;font-size:12px;color:var(--mute);flex:none;margin-top:3px}
.act.done .an{background:var(--ok);color:#fff;border-color:var(--ok)}.act.next .an{border-color:var(--accent);color:var(--accent);font-weight:700}
.jobbox{border-left:4px solid var(--accent);padding:6px 10px;margin-bottom:12px;background:var(--accent-soft);border-radius:6px}
.banner{border-radius:10px;padding:10px 16px;margin:12px 0}.banner ul{margin:6px 0 0}
.banner.block{background:var(--badbg);color:var(--bad);border-left:4px solid var(--bad)}.banner.warn{background:var(--warnbg);color:var(--warn);border-left:4px solid var(--warn)}
.banner.good{background:var(--okbg);color:var(--ok);border-left:4px solid var(--ok)}
.dlg .box:has(.wide-dlg){max-width:min(980px,94vw);width:94vw;max-height:92vh;overflow:auto}
.nextbar{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:10px 0;padding:10px 14px;border:1px solid var(--accent);border-radius:10px;background:var(--accent-soft)}
.dimrow{padding:10px 0;border-top:1px solid var(--line)}.dsc{font-weight:700;padding:1px 9px;border-radius:999px;font-size:13px}
.dsc.good{background:var(--okbg);color:var(--ok)}.dsc.ok{background:var(--warnbg);color:var(--warn)}.dsc.weak{background:var(--badbg);color:var(--bad)}
.dbar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:6px}.dbar i{display:block;height:100%}.dbar i.good{background:var(--ok)}.dbar i.ok{background:var(--warn)}.dbar i.weak{background:var(--bad)}
.fix{margin-top:3px;padding-left:4px}
@media (max-width:980px){.plan-grid{grid-template-columns:1fr}.plan-side{position:static;max-height:none;order:-1}}
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
      ${stepChip(p.blueprint, 'blueprint')}${stepChip(p.beats && p.beats_written >= p.beats, `narration ${p.beats_written}/${p.beats || '?'} parts`)}${stepChip(p.scenes > 0, `${p.scenes} scenes`)}${stepChip(p.status === 'approved', 'approved')}${stepChip(p.exports > 0, p.exports ? `${p.exports} export${p.exports > 1 ? 's' : ''}` : 'exported')}
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
  let P = null, PV = {}, LK = null, MS = null, RS = null, SS = null, GS = null, VS = null, TH = null, AU = null, PF = 'open', VOPT = {captions: false, gaps: false}, sig = '', seenRun = false;
  const app = $('#app');
  const busyJob = () => P && P.job && P.job.state === 'running';
  const errHint = e => /failed to load|model_load_failed|llama-server exited|\b503\b/i.test(e || '') ? 'The model server could not load the chat model. Most often another model worker (a voice worker) is still holding the GPU memory: end it or restart the model server, then press Try again.'
    : /not reachable|connect/i.test(e || '') ? 'The model server is not reachable. Start it (check Settings, Test connection), then press Try again.'
    : /timed? ?out|timeout/i.test(e || '') ? 'The model took too long. Press Try again; if it repeats, restart the model server.'
    : /context|too long|budget/i.test(e || '') ? 'The request was too large for the model. Press Try again; if it repeats, make the plan shorter in Settings.'
    : 'Press Try again. If it fails the same way, the message above says what is wrong.';
  const editing = () => { const a = document.activeElement; return a && a.closest && a.closest('#plan') && ['TEXTAREA', 'INPUT', 'SELECT'].includes(a.tagName); };

  // a named person: how they appear, the photos found or uploaded, and the editor's approval of one (story3/likeness.py)
  const likenessBox = (x, dis) => {
    const L = ((LK && LK.people) || []).find(y => y.id === x.id); if (!L) return '';
    const mode = L.mode || 'generic', shown = L.photos.filter(ph => ph.status !== 'rejected');
    const opt = (v, t) => `<option value="${v}" ${mode === v ? 'selected' : ''}>${t}</option>`;
    return `<div style="grid-column:2/4" class="small"><label class="mute">Real person?
      <select ${dis} onchange="_plan.likeMode(this,'${x.id}',this.value)"><option value="" ${mode === 'generic' ? 'selected' : ''} disabled>No, an invented person</option>${opt('silhouette', 'Yes: silhouette only (no face)')}${opt('researched', 'Yes: painted likeness from an approved photo')}${opt('stylised', 'Yes: stylised near-likeness (no photo)')}</select></label>
      ${mode === 'researched' || mode === 'silhouette' || mode === 'stylised' ? `<span class="mute">public figure confirmed</span>` : ''}
      ${mode !== 'generic' && mode !== 'silhouette' ? `<button class="small" ${dis} onclick="_plan.likeSearch(this,'${x.id}')">Search the web for photos</button> <label class="small">or upload <input type="file" accept="image/jpeg,image/png" ${dis} onchange="_plan.likeUpload(this,'${x.id}')"></label>` : ''}
      ${shown.length ? `<div class="row mt-s" style="gap:8px;flex-wrap:wrap">${shown.map(ph => `<div style="width:150px;border:${ph.approved ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'};border-radius:6px;padding:4px">
        <img src="/api/media/file/${id}/${esc(ph.file)}" style="width:100%;border-radius:4px" loading="lazy"><div class="mute" style="font-size:11px">${esc(ph.licence || 'licence unknown')}${ph.author ? ' · ' + esc(ph.author) : ''}${ph.page ? ` · <a href="${esc(ph.page)}" target="_blank" rel="noopener">source</a>` : ''}</div>
        <div class="row"><button class="small ${ph.approved ? '' : 'primary'}" ${dis} onclick="_plan.likePhoto(this,'${x.id}','${ph.id}','approve')">${ph.approved ? 'Chosen ✓' : 'Use this'}</button><button class="small" ${dis} onclick="_plan.likePhoto(this,'${x.id}','${ph.id}','reject')">Reject</button></div></div>`).join('')}</div>
      <div class="mute" style="font-size:11px">The photo is only a reference for the painted character: it is never shown in the video. Check you are allowed to use it.</div>` : (mode === 'researched' ? '<div class="warnbox mt-s">No photo yet: search or upload one. Without an approved photo the character is drawn from the description.</div>' : '')}</div>`;
  };
  async function load(force) {
    const [p, m] = await Promise.all([api('/plans/' + id), api('/media/' + id).catch(() => null)]);
    LK = m && m.likeness; MS = m && m.voice; RS = m && m.refs; SS = m && m.scenes; GS = m && m.graphics; VS = m && m.video; TH = m && m.thumbnail; AU = m && m.auto;
    const s = JSON.stringify([LK, AU && [AU.next, AU.remaining], TH && [TH.done, TH.attempts], VS && [VS.done, VS.ready, VS.blockers.length, VS.warnings.length, VS.changes ? VS.changes.changed.length + ":" + VS.changes.stale.length : 0, VS.videos.map(v => v.id + v.current)], GS && [GS.approved, GS.needs_build, GS.thin, GS.scenes.map(r => r.items.map(a => a.id + a.approved + a.current))], SS && [SS.approved, SS.needs_choice, SS.needs_picture, SS.settings, SS.trial, SS.scenes.map(r => r.candidates.map(a => a.id + a.status + a.approved + a.current + (a.score ? a.score.total : '')))], RS && [RS.approved, RS.skipped, RS.without_pictures, RS.assets.map(r => r.candidates.map(a => a.id + a.status + a.approved + a.current + (a.score ? a.score.total : '')))], MS && [MS.have, MS.approved, MS.export.current, MS.segments.map(r => r.attempts.map(a => a.id + a.status + a.approved + a.current))], p.cast_gaps && p.cast_gaps.map(g => g.id + g.missing.join()), p.settings.visual_style, p.style && [p.style.registry_stale, p.style.storyboard_stale], p.rev, p.job.state, p.job.done, p.job.label, p.segments.map(x => x.rev), p.scenes.map(x => [x.rev, x.stale, x.start_s, x.status, x.locked]), p.assets.map(x => x.rev), p.validation ? 1 : 0, p.narrator.name, p.content_hash, p.approval && p.approval.state, p.exports.length, ((p.validation || {}).scores || {}).computed_at]);
    const changed = s !== sig; P = p;
    if (changed || force) { sig = s; if (!editing() || force) render(); }
    if (p.job.state === 'running') seenRun = true;
    if (seenRun && p.job.state !== 'running') { seenRun = false; if (p.job.state === 'error') toast('Stopped: ' + p.job.error, {bad: true}); else if (p.job.state === 'done') toast('Finished: ' + p.job.kind + (p.job.note ? ' — ' + p.job.note : '')); }
  }
  const tick = async () => { if (my !== route_id) return; try { await load(); } catch (e) { /* keep polling */ } timer = setTimeout(tick, busyJob() ? 1500 : 4000); };

  const STEP_WHAT = {1: 'blueprint', 2: 'narration', 3: 'registry', 4: 'storyboard', 5: 'references', 6: 'compile_prompts', 8: 'fix_repeats', 10: 'approved', 11: 'export', 12: 'voice', 13: 'scene_pictures', 14: 'graphics', 15: 'video'};
  const WHAT_LABEL = {blueprint: 'Plan the story', narration: 'Write the narration', registry: 'Create characters and places', references: 'Make reference pictures', storyboard: 'Design the storyboard', compile_prompts: 'Write image prompts', fix_repeats: 'Fix camera repeats', approved: 'Approve the plan', export: 'Export', voice: 'Make the voice', scene_pictures: 'Scene pictures', graphics: 'Graphics', video: 'Draft video', auto_run: 'Automatic run'};
  const agoText = ts => { const s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 10 ? 'just now' : s < 60 ? s + 's ago' : s < 3600 ? Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + 's ago' : s < 86400 ? Math.floor(s / 3600) + 'h ' + String(Math.floor(s % 3600 / 60)).padStart(2, '0') + 'm ago' : new Date(ts * 1000).toLocaleString(); };
  const clock = ts => new Date(ts * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  const agoSpan = ts => `<span data-ago="${ts}" title="${esc(new Date(ts * 1000).toLocaleString())}">${agoText(ts)}</span>`;
  const agoTimer = setInterval(() => { if (my !== route_id) return clearInterval(agoTimer); document.querySelectorAll('#app [data-ago]').forEach(e => { e.textContent = agoText(+e.dataset.ago); }); }, 5000);
  const run = (btn, path, json, label) => act(btn, async () => { const r = await api(path, {method: 'POST', json: json || {}}); await load(true); return r; });
  window._plan = {
    async blueprint(b) { if (P.blueprint && P.segments.length && !await confirmDlg('Plan the story again?', 'The new plan can change the beats. Narration you approved or locked is kept; the rest is replaced when you write it again.', 'Plan again')) return; await run(b, `/plans/${id}/blueprint`); },
    async narration(b, missing) { if (!missing && P.segments.length && !await confirmDlg('Rewrite all narration?', 'Parts you approved or locked are kept; everything else is written again, and its scenes are removed.', 'Rewrite')) return; await run(b, `/plans/${id}/narration`, {only_missing: !!missing}); },
    async beat(b, beat) { await run(b, `/plans/${id}/narration`, {beat_ids: [beat]}); },
    async registry(b) { if (P.assets.length && !await confirmDlg('Create the characters and places again?', 'The list is rewritten for the chosen style. Items you locked are kept. Reference pictures of the old items are no longer used.', 'Create again')) return; await run(b, `/plans/${id}/registry`); },
    async likeMode(b, assetId, mode, pub) {
      if (mode !== 'silhouette' && !pub && !(LK.people.find(x => x.id === assetId) || {}).public_figure && !await confirmDlg('Is this a public figure?', 'A painted likeness is only made for public figures, never for private individuals. It shows only what the facts say about them, and you can switch back to a silhouette at any time.', 'Yes, a public figure')) return;
      await act(b, () => api(`/media/${id}/likeness/${assetId}/mode`, {method: 'POST', json: {mode, public_figure: mode === 'silhouette' ? null : true}}), 'Saved'); await load(true);
    },
    async likeSearch(b, assetId) {
      await act(b, () => api(`/media/${id}/likeness/${assetId}/search`, {method: 'POST'}), 'Photos added below: pick the one that looks right'); await load(true);
    },
    async likeUpload(el, assetId) {
      const f = el.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
      await act(null, () => api(`/media/${id}/likeness/${assetId}/upload`, {method: 'POST', form: fd}), 'Photo added'); el.value = ''; await load(true);
    },
    async likePhoto(b, assetId, photoId, what) {
      await act(b, () => api(`/media/${id}/likeness/${assetId}/photos/${photoId}/${what}`, {method: 'POST', json: what === 'approve' ? {approved: true} : undefined}), what === 'approve' ? 'This photo will be the reference for the character' : 'Photo rejected'); await load(true);
    },
    async addAsset() {
      const name = (prompt('Name of the person, place or object to add (for example “the manager”):') || '').trim(); if (!name) return;
      const kind = (prompt('Is it a person, a place or a prop?', 'person') || '').trim().toLowerCase(); if (!kind) return;
      const description = prompt('Describe how it looks (age, build, face and hair, clothes; or the materials and light of the place):') || '';
      await act(null, () => api(`/plans/${id}/assets`, {method: 'POST', json: {name, kind, description}}), 'Added. Draw its reference sheet with “Make reference pictures”.'); await load(true);
    },
    async assetFill() {
      for (const g of P.cast_gaps || []) {
        const ap = {};
        for (const m of g.missing) { const v = prompt(`${g.name} (${g.kind}): ${m}
${g.hints[m] || ''}
Be concrete: colours, materials, numbers. Leave empty to skip.`); if (v === null) return; if (v.trim()) ap[m] = v.trim(); }
        if (Object.keys(ap).length) await act(null, () => api(`/plans/assets/${g.id}`, {method: 'PATCH', json: {appearance: ap}}), g.name + ' saved');
      }
      await load(true);
    },
    async setStyle(sid) { if (sid === (P.settings.visual_style || 'filmic')) return; await act(null, () => api(`/plans/${id}/visual-style`, {method: 'PATCH', json: {style: sid}}), 'Style changed'); await load(true); },
    async storyboard(b, redo) { const rep = !!(P.style && P.style.storyboard_stale); if (redo && !await confirmDlg(rep ? 'Redesign all scenes in the chosen style?' : 'Design all scenes again?', rep ? 'Every scene that is not locked is replaced, approved ones included, because they were made for another look. Narration and voice are not touched. Plan approval will ask you to approve again.' : 'Every scene that is not locked or approved is replaced. Parts with a locked or approved scene are skipped.', rep ? 'Redesign' : 'Design again')) return; await run(b, `/plans/${id}/storyboard`, {replace_approved: rep}); },
    async cancel(b) { await act(b, () => api(`/plans/${id}/cancel`, {method: 'POST'}), 'Stopping after this step…'); },
    async fixRepeats(b) { if (!await confirmDlg('Redraw scenes that repeat the camera?', 'Each flagged scene is redrawn with a different camera distance and angle, keeping the same idea. Locked and approved scenes are skipped. About 30 seconds per scene.', 'Redraw them')) return; await run(b, `/plans/${id}/fix-repeats`); },
    async compile(b) { const r = await act(b, () => api(`/plans/${id}/compile-prompts`, {method: 'POST'})); if (r) { await load(true); toast(r.issues.some(i => i.level === 'error') ? 'Prompts written; some need fixing' : 'Image prompts written for ' + r.compiled + ' scenes'); } },
    async imageModels(f) { await act(null, () => api(`/plans/${id}/image-models`, {method: 'PATCH', json: f}), 'Saved'); await load(true); },
    async byType(t, m) { const bt = {...(P.settings.image_models || {}).by_type}; if (m) bt[t] = m; else delete bt[t]; await window._plan.imageModels({by_type: bt}); },
    async licence(m, on) { await window._plan.imageModels({licence_checks: {...(P.settings.image_models || {}).licence_checks, [m]: on}}); },
    async sceneModel(sid, m) { await act(null, () => api(`/plans/scenes/${sid}`, {method: 'PATCH', json: {model: m}}), 'Image model set'); await load(true); },
    async prompts(sid) {
      const r = await api(`/plans/scenes/${sid}/prompts`);
      if (!r.prompts.qwen) return toast('Write the image prompts first (side panel, step 4).', {bad: true});
      const sc = P.scenes.find(x => x.id === sid);
      const ad = {qwen: 'Qwen Image 2.1', flux: 'FLUX.2 Klein'};
      const box = a => { const c = r.prompts[a];
        return `<div class="mt-s"><div class="row"><b>${ad[a]}</b><span class="mute small">adapter ${esc(c.adapter_version)} · ${esc(c.mode.replace(/_/g, ' '))} · ${c.size.width}x${c.size.height} · steps ${c.params.steps}, cfg ${c.params.cfg} (gateway defaults)</span><span class="sp"></span><button class="small" onclick="navigator.clipboard.writeText(document.getElementById('pp-${a}').value);toast('Copied')">Copy</button>${r.previews_enabled ? `<button class="small" onclick="_plan.preview('${sid}','${a}')">Make one preview image</button>` : ''}</div>
          <textarea id="pp-${a}" readonly style="width:100%;min-height:120px;font-size:12px;field-sizing:content">${esc(c.prompt)}</textarea>
          ${c.negative_prompt ? `<div class="small mt-s"><b>Negative prompt</b> (this model honours one): ${esc(c.negative_prompt)}</div>` : `<div class="small mute mt-s">No negative prompt: this endpoint ignores one, so exclusions are written into the prompt.</div>`}
          ${c.references.length ? `<div class="small mt-s"><b>Reference images (${c.references.length} of 3 allowed):</b> ${c.references.map((x, i) => `${i + 1}. ${esc(x.name)} (${esc(x.role)})`).join('; ')}</div>` : ''}
          ${c.missing_references.length ? `<div class="small mute mt-s">No approved reference image yet: ${c.missing_references.map(x => esc(x.name) + (x.action === 'create_reference' ? ' (this scene creates it)' : ' (needed before this scene)')).join(', ')}</div>` : ''}
          ${c.notes.map(n => `<div class="small mt-s">ℹ ${esc(n)}</div>`).join('')}</div>`; };
      const cov = r.comparison.coverage;
      const html = `<div class="wide-dlg"></div><div class="small mute">The prompt is built from the scene; edit the scene, not the prompt. Both models get the same facts, continuity and exclusions.</div>
        ${r.issues.length ? `<div class="mt-s">${r.issues.map(i => `<div class="iss ${i.level}">${i.level === 'error' ? '✗' : '⚠'} ${esc(i.adapter)} · ${esc(i.kind.replace(/_/g, ' '))}: ${esc(i.text)}</div>`).join('')}</div>` : '<div class="ok mt-s">✓ Both prompts pass the checks.</div>'}
        ${box('qwen')}${box('flux')}
        <details class="mt"><summary><b>Does each prompt carry the scene?</b> <span class="mute small">${cov.filter(x => x.qwen && x.flux).length} of ${cov.length} on both</span></summary>
          <table class="mt-s small"><tr><th align="left">Scene detail</th><th>Qwen</th><th>FLUX</th></tr>${cov.map(x => `<tr><td>${esc(x.element)}: ${esc(x.value)}</td><td align="center">${x.qwen ? '✓' : '✗'}</td><td align="center">${x.flux ? '✓' : '✗'}</td></tr>`).join('')}</table></details>
        <details class="mt"><summary><b>Licence and judging</b></summary><div class="small mt-s">${Object.entries(r.comparison.licence).map(([a, l]) => `<div><b>${esc(ad[a])}:</b> ${esc(l.status)}. ${esc(l.note)}</div>`).join('')}<div class="mt-s mute">After a preview, judge: ${r.comparison.evaluate_after_preview.join(', ')}.</div></div></details>
        ${r.previews.length ? `<div class="mt"><b>Previews</b><div class="row mt-s" style="align-items:flex-start;gap:10px">${r.previews.map(pv => `<div style="width:260px"><img src="/api/plans/previews/${esc(P.id)}/${esc(pv.file)}" style="width:100%;border-radius:6px"><div class="small">${esc(pv.model)} · ${pv.seconds}s · seed ${pv.seed}</div><div class="small mute">${pv.source_hash === (r.prompts[pv.adapter] || {}).source_hash ? 'matches the current prompt' : 'older prompt'}</div></div>`).join('')}</div></div>` : ''}`;
      await dialog({title: 'Image prompts · ' + (sc ? mmss(sc.start_s) : ''), html, wide: true, buttons: [{label: 'Close', value: null}]});
    },
    async preview(sid, adapter) { await run(null, `/plans/scenes/${sid}/preview`, {adapter}); toast('Making one preview image. It can take a minute or two; reopen Prompts to see it.'); },
    async review(b) { const r = await act(b, () => api(`/plans/${id}/review`, {method: 'POST'})); if (r) { await load(true); window._plan.go('sec-review'); toast(r.ok ? 'Reviewed: nothing blocks approval' : 'Reviewed: ' + r.blockers.length + ' thing(s) block approval'); } },
    async approve(b) {
      const so = (P.validation || {}).signoff;
      if (!so || (P.validation.scores || {}).content_hash !== P.content_hash) return window._plan.review(b);
      if (so.blockers.length) { window._plan.go('sec-review'); return toast('Fix what blocks approval first.', {bad: true}); }
      const note = await dialog({title: 'Approve this plan?', html: `<p>You are signing off the narration, ${P.scenes.length} scenes and their image prompts as they are now. If you change anything later, it will show as “changed since approval”.</p>
        ${so.warnings.length ? `<div class="small"><b>Recorded with the approval:</b><ul class="tight">${so.warnings.map(w => `<li>${esc(w.text)}</li>`).join('')}</ul></div>` : ''}<label class="f mt-s">Note (optional)<input id="apn" placeholder="e.g. listened to the narration, good to go"></label>`,
        buttons: [{label: 'Cancel', value: null}, {label: 'Approve', primary: true, collect: l => l.querySelector('#apn').value}]});
      if (note === null) return;
      await act(b, () => api(`/plans/${id}/approve`, {method: 'POST', json: {note}}), 'Plan approved'); await load(true);
    },
    async unapprove(b) { if (!await confirmDlg('Withdraw approval?', 'The plan goes back to draft. Nothing in it changes.', 'Withdraw')) return; await act(b, () => api(`/plans/${id}/unapprove`, {method: 'POST'}), 'Approval withdrawn'); await load(true); },
    async export(b) {
      const r = await act(b, () => api(`/plans/${id}/export`, {method: 'POST'}));
      if (r) { await load(true); window._plan.go('sec-review'); toast(`Exported v${r.rev}${r.ready_for_generation.ok ? '' : ' (not ready for generation: see the file)'}`); }
    },
    async loadHistory(el) {
      const box = el.querySelector('.hist'); const h = await api(`/plans/${id}/history`).catch(() => []);
      const label = {blueprint: 'Story planned', narration: 'Narration written', storyboard: 'Storyboard designed', scene: 'Scene edited', segment: 'Narration edited', approved: 'Plan approved', unapproved: 'Approval withdrawn',
        export: 'Exported', compile_prompts: 'Image prompts written', image_models: 'Image model settings changed', preview: 'Preview image made', fix_repeats: 'Camera repeats fixed', registry: 'Recurring assets listed'};
      box.innerHTML = h.length ? h.map(x => `<div>${fmtDate(x.ts)} · ${esc(label[x.what] || x.what.replace(/_/g, ' '))}${x.detail && x.detail.rev ? ' v' + x.detail.rev : ''}${x.detail && x.detail.note ? ' · “' + esc(x.detail.note) + '”' : ''}</div>`).join('') : 'No changes recorded yet.';
    },
    async voiceAll(b) {
      const eta = MS && MS.eta_missing_s ? ` It takes about ${hd(MS.eta_missing_s)}.` : '';
      if (!await confirmDlg('Make the voice?', `The voice model will read the ${MS ? MS.total - MS.have : ''} part(s) that have no voice yet.${eta} The model server handles one job at a time, so other steps wait. You can leave this page; finished parts are saved and you can stop at any time.`, 'Start')) return;
      await run(b, `/media/${id}/voice`, {only_missing: true});
    },
    async ttsSet(el, engine, voice) { await act(el, () => api(`/plans/${id}/tts`, {method: 'PATCH', json: voice ? {engine, voice} : {engine}}), 'Voice changed'); await load(true); },
    async voiceSample(b) { await run(b, `/media/${id}/voice/sample`, {}); toast('Making a short sample.'); },
    async cast(el, on) {
      const write = on && P.assets.some(a => (a.kind === 'person' || a.kind === 'narrator') && a.data.appearance) && await confirmDlg('Write it into the character list too?', 'The list keeps the old skin, hair and eye colours unless you rewrite it. Rewriting changes the descriptions you may have approved; the pictures use the Indian cast either way.', 'Rewrite the list');
      await act(el, () => api(`/plans/${id}/cast`, {method: 'PATCH', json: {indian: on, write_into_list: !!write}}), on ? 'People are drawn as Indian' : 'People follow the story'); await load(true);
    },
    async voiceOne(b, sid) { await run(b, `/media/${id}/voice`, {segment_ids: [sid], only_missing: false}); toast('Making this part again (about a minute or two).'); },
    async voiceApproveAll(b) {
      const todo = MS.segments.map(r => r.attempts.find(a => a.id === r.chosen)).filter(a => a && !a.approved && !(a.flags || []).length);
      if (!todo.length) return toast('Nothing to approve.');
      const flagged = MS.segments.filter(r => { const a = r.attempts.find(x => x.id === r.chosen); return a && (a.flags || []).length; }).length;
      if (!await confirmDlg('Approve all voice?', `${todo.length} finished take(s) will be approved as they are.${flagged ? ` ${flagged} take(s) with a warning are left for you to listen to.` : ''} You can unapprove any part later.`, 'Approve')) return;
      await act(b, async () => { for (const a of todo) await api(`/media/item/${a.id}`, {method: 'PATCH', json: {approved: true}}); return todo.length; }, n => `Approved ${n} voice take(s)`);
      await load(true);
    },
    async refsAll(b) {
      const n = RS ? RS.without_pictures : 0;
      if (!await confirmDlg('Make reference pictures?', `${RS.default_candidates} picture(s) for each of the ${n || RS.open} recurring thing(s) that have none yet, about ${hd((n || RS.open) * RS.default_candidates * RS.seconds_per_picture)} in total with ${RS.model}. The model server handles one job at a time, so other steps wait. Finished pictures are saved even if you stop.`, 'Start')) return;
      await run(b, `/media/${id}/references`, {only_missing: true});
    },
    async refsScore(b) { await run(b, `/media/${id}/references/score`, {}); toast('Checking the pictures.'); },
    async refsApproveBest(b) {
      if (!await confirmDlg('Approve the best pictures?', `For each of the ${RS.bulk_ready} open item(s) whose best picture scores ${RS.min_score}+ with no hard problem, that picture becomes its reference and the scene prompts update. Items without such a picture are left for you. You can unapprove any of them afterwards.`, 'Approve')) return;
      const r = await act(b, () => api(`/media/${id}/references/approve-best`, {method: 'POST', json: {min_score: RS.min_score}}));
      if (r) { await load(true); toast(`Approved ${r.approved}.` + (r.left.length ? ` ${r.left.length} left for you: ${r.left.map(x => x.asset + ' (' + x.why + ')').join('; ')}` : '')); }
    },
    async refsOne(b, aid) { await run(b, `/media/${id}/references`, {asset_ids: [aid], only_missing: false, candidates: RS.default_candidates}); toast('Drawing new pictures for this one.'); },
    async picsTrial(b) {
      if (!await confirmDlg('Run the three-scene trial?', `Three scenes are each drawn on Qwen and on FLUX, plain and (where the scene has approved reference sheets) from the sheets: up to 12 pictures, about ${hd(3 * 2 * (SS.seconds_per_picture['qwen-image-2.1'] + SS.seconds_per_picture['flux2-klein-9b']))}. The model server handles one job at a time, so other steps wait. Nothing from this trial is approved for you.`, 'Start')) return;
      await run(b, `/media/${id}/scenes/trial`, {});
    },
    async picsAll(b) {
      if (!await confirmDlg('Draw the scene pictures?', `${SS.needs_picture} scene(s) without a current picture, ${SS.settings.candidates} picture(s) each, about ${hd(SS.eta_missing_s)}, ${SS.settings.mode === 'generate' ? 'plain' : SS.settings.mode === 'edit' ? 'from the reference sheets' : 'from the sheets where a scene has them'}. Approved scenes are never redrawn. Finished pictures are saved even if you stop, and pressing the button again continues.`, 'Start')) return;
      await run(b, `/media/${id}/scenes`, {only_missing: true});
    },
    draft(k, v) { window._drafts[k] = v; },
    async refsDraw(b, aid) {
      const row = RS.assets.find(r => r.asset_id === aid), txt = document.getElementById('refp-' + aid).value.trim(), model = document.getElementById('refm-' + aid).value;
      if (!txt) { toast('The prompt is empty.', {bad: true}); return; }
      const json = {asset_ids: [aid], only_missing: false, candidates: RS.default_candidates, model};
      if (txt !== row.prompt.trim()) json.prompts = {[aid]: txt};
      delete window._drafts['ref:' + aid];
      await run(b, `/media/${id}/references`, json); toast(json.prompts ? 'Drawing from your prompt.' : 'Drawing new pictures for this one.');
    },
    refsReset(aid) { const row = RS.assets.find(r => r.asset_id === aid); delete window._drafts['ref:' + aid]; document.getElementById('refp-' + aid).value = row.prompt; },
    async redraw(b, sid) {
      let o;
      try { o = await api(`/media/${id}/scenes/${sid}/options`); } catch (e) { toast(e.message || 'Could not load the options.', {bad: true}); return; }
      const names = Object.keys(o.models), cur = o.models[o.model] ? o.model : names[0];
      window._rd = {o, fill(m, keepPrompt) {
        const x = o.models[m], q = document.getElementById('rd-prompt'), n = document.getElementById('rd-neg'), mode = document.getElementById('rd-mode');
        if (!keepPrompt) q.value = x.prompt;
        n.value = x.negative_prompt; n.disabled = !x.negative_used; document.getElementById('rd-neg-note').textContent = x.negative_used ? '' : 'This model ignores a negative prompt.';
        mode.querySelector('option[value=edit]').disabled = !x.can_edit;
        document.getElementById('rd-mode-note').textContent = x.can_edit ? `Uses: ${x.references.join(', ')}.` : (x.edits ? 'This scene has no approved reference sheet yet.' : 'This model cannot use reference pictures.');
        if (!x.can_edit) mode.value = 'generate';
      }};
      const html = `<div class="f"><label class="f">Model<select id="rd-model" onchange="_rd.fill(this.value)">${names.map(m => `<option value="${m}" ${m === cur ? 'selected' : ''}>${esc(o.models[m].label)}${m === o.default_model ? ' (default)' : ''}</option>`).join('')}</select></label>
        <label class="f">How<select id="rd-mode"><option value="generate" ${o.mode !== 'edit' ? 'selected' : ''}>Plain: the prompt only</option><option value="edit" ${o.mode === 'edit' ? 'selected' : ''}>From the reference sheets</option></select></label><div class="small mute" id="rd-mode-note"></div>
        <label class="f">Prompt (change anything; it is used for these pictures only)<textarea id="rd-prompt" style="min-height:220px"></textarea></label>
        <label class="f">Negative prompt<textarea id="rd-neg" style="min-height:50px"></textarea></label><div class="small mute" id="rd-neg-note"></div>
        <label class="f">Pictures<select id="rd-n">${[1, 2, 3, 4].map(n => `<option>${n}</option>`).join('')}</select></label>
        <label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="rd-keep" ${o.remembered ? 'checked' : ''}> Use this model and way for this scene from now on</label></div>`;
      const pr = dialog({title: 'Draw this scene again', html, buttons: [{label: 'Cancel', value: null}, {label: 'Draw', primary: true, collect: l => ({
        model: l.querySelector('#rd-model').value, mode: l.querySelector('#rd-mode').value, prompt: l.querySelector('#rd-prompt').value, negative_prompt: l.querySelector('#rd-neg').value,
        candidates: +l.querySelector('#rd-n').value, remember: l.querySelector('#rd-keep').checked})}]});
      window._rd.fill(cur); if (o.mode === 'edit') document.getElementById('rd-mode').value = 'edit';
      const v = await pr; if (!v) return;
      await run(b, `/media/${id}/scenes/${sid}/redraw`, v); toast('Drawing the scene again.');
    },
    async redrawStale(b) {
      const ids = VS.changes.stale.map(c => c.scene);
      if (!await confirmDlg('Redraw the scenes with old pictures?', `${ids.length} scene(s) are drawn again, one new picture each, in the way chosen for each scene. Your approved pictures stay until you approve the new ones; the video uses the new picture meanwhile.`, 'Redraw')) return;
      await run(b, `/media/${id}/scenes`, {scene_ids: ids, only_missing: false, candidates: 1});
    },
    async resolve(b, key, fix) {
      const r = await act(b, () => api(`/plans/${id}/resolve`, {method: 'POST', json: {key, fix}}));
      if (!r) return;
      window._fixNote = r.kind === 'instant' ? r.message : '';
      toast(r.kind === 'instant' ? r.message : 'Started: it runs in the background and the result is shown here when it ends.');
      await load(true);
    },
    async retry(b) {
      const k = ((P.job && P.job.kind) || '').toLowerCase(), by = {blueprint: () => this.blueprint(b), narration: () => this.narration(b, true), registry: () => this.registry(b), storyboard: () => this.storyboard(b),
        'fix repeats': () => this.fixRepeats(b), voice: () => this.voiceAll(b), 'scene pictures': () => this.picsAll(b), references: () => this.refsAll(b), 'auto-run': () => this.autoRun(b), video: () => this.vidBuild(b, 'draft')};
      const f = Object.entries(by).find(([name]) => k === name || k.startsWith(name));
      if (!f) { toast('Press the button of the step that stopped (' + (k || 'unknown') + ').', {bad: true}); return; }
      window._fixNote = ''; await f[1]();
    },
    async picsOne(b, sid) { await run(b, `/media/${id}/scenes`, {scene_ids: [sid], only_missing: false, candidates: 1}); toast('Drawing another picture of this scene.'); },
    async picsCorrect(b, sid, iid) {
      const change = prompt('What should change in this picture? (one clear change)'); if (!change || !change.trim()) return;
      const keep = prompt('What must stay exactly the same? (separate with semicolons)', 'the people, the setting, the composition and the style'); if (keep === null) return;
      await run(b, `/media/${id}/scenes/${sid}/correct`, {change, keep: keep.split(';').map(x => x.trim()).filter(Boolean), item_id: iid}); toast('Correcting the picture.');
    },
    async picsScore(b) { await run(b, `/media/${id}/scenes/score`, {}); toast('Checking the pictures.'); },
    async picsApproveBest(b) {
      if (!await confirmDlg('Approve the best scene pictures?', `For each of the ${SS.bulk_ready} open scene(s) whose best picture scores ${SS.min_score}+ with no hard problem, that picture is approved. The others are left for you. You can unapprove any of them afterwards.`, 'Approve')) return;
      const r = await act(b, () => api(`/media/${id}/scenes/approve-best`, {method: 'POST', json: {min_score: SS.min_score}}));
      if (r) { await load(true); toast(`Approved ${r.approved}.` + (r.left.length ? ` ${r.left.length} left for you.` : '')); }
    },
    async picsApprove(iid, on) { await act(null, () => api(`/media/item/${iid}`, {method: 'PATCH', json: {approved: on}}), on ? 'Picture approved' : 'Approval removed'); await load(true); },
    async picsSet(patch) { await act(null, () => api(`/media/${id}/scenes/settings`, {method: 'POST', json: patch}), 'Saved'); await load(true); },
    async picsChoose(model, mode) { await act(null, () => api(`/media/${id}/scenes/choose`, {method: 'POST', json: {model, mode}}), 'Chosen: used for the full run'); await load(true); },
    picsFilter(v) { PF = v; render(); },
    async autoRun(b) {
      const left = AU.stages.filter(s => !s.done).map(s => s.label);
      if (!await confirmDlg('Run everything automatically?', `It will do the ${left.length} unfinished step(s) one after another, starting at “${left[0]}”: ${left.join(' → ')}. At every choice it takes the default: the best (else first) finished picture or take is approved, scene pictures use Qwen drawn plain unless you already chose a way, charts built from thin facts are accepted, and the plan is signed off for you. It stops at the first problem it cannot settle and tells you what; everything finished is kept, and you can look at, unapprove or redo anything afterwards. Voice (about 26 minutes) and pictures take the longest, and other steps wait. You can stop it from the box at the top of the side panel.`, 'Start')) return;
      await run(b, `/media/${id}/auto`, {}); toast('Automatic run started.');
    },
    vidOpt(k, v) { VOPT[k] = v; render(); },
    async thumb(b) { await run(b, `/media/${id}/thumbnail`); toast('Drawing the thumbnail.'); },
    async vidBuild(b, profile) {
      const ps = VS.profiles[profile] || {};
      if (!await confirmDlg(profile === 'draft' ? 'Make the draft video?' : 'Make a preview?', `${ps.label || profile}, ${ps.size || ''}, about ${hd(ps.eta_s || 0)}${VOPT.captions ? ', with captions' : ''}. Pictures are held for exactly their scene's length with a slow zoom or pan, over the voice.${VS.blockers.length ? ` ${VS.blockers.length} missing item(s) get a labelled placeholder.` : ''} Other steps wait while it builds.`, 'Start')) return;
      await run(b, `/media/${id}/video`, {profile, captions: VOPT.captions, allow_gaps: VOPT.gaps});
    },
    async gfxBuild(b, force) { await run(b, `/media/${id}/graphics`, {force: !!force}); toast('Graphics built from the facts.'); },
    async gfxApproveAll(b) {
      if (!await confirmDlg('Approve the graphics?', `Every open graphic that is what its scene wanted is approved. ${GS.fallbacks ? GS.fallbacks + ' card(s) are a simpler card than the scene wanted (the facts are thin) and are left for you.' : ''}`, 'Approve')) return;
      const r = await act(b, () => api(`/media/${id}/graphics/approve-all`, {method: 'POST', json: {}})); if (r) { await load(true); toast(`Approved ${r.approved}.` + (r.left.length ? ` ${r.left.length} left for you.` : '')); }
    },
    async gfxApprove(iid, on) { await act(null, () => api(`/media/item/${iid}`, {method: 'PATCH', json: {approved: on}}), on ? 'Graphic approved' : 'Approval removed'); await load(true); },
    async refsApprove(iid, on) { await act(null, () => api(`/media/item/${iid}`, {method: 'PATCH', json: {approved: on}}), on ? 'Reference approved; scene prompts updated' : 'Approval removed; scene prompts updated'); await load(true); },
    async refsSkip(aid, on) { await act(null, () => api(`/media/${id}/references/skip`, {method: 'POST', json: {asset_id: aid, skip: on}}), on ? 'Skipped: no reference for this one' : 'Back on the list'); await load(true); },
    async voiceApprove(iid, on) { await act(null, () => api(`/media/item/${iid}`, {method: 'PATCH', json: {approved: on}}), on ? 'Recording approved' : 'Approval removed'); await load(true); },
    async validate(b) { const r = await act(b, () => api(`/plans/${id}/validate`, {method: 'POST'})); if (r) { await load(true); toast(r.ok ? 'No blocking problems found' : 'Some problems need attention'); } },
    async setTitle(el) { if (!el.value.trim()) return; await act(null, () => api(`/plans/${id}/title`, {method: 'POST', json: {title: el.value.trim()}}), 'Video title saved'); },
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
    go(id_) { const e = document.getElementById(id_); if (e) e.scrollIntoView({behavior: 'smooth', block: 'start'}); },
    firstProblem() {
      const bad = P.scenes.filter(x => (x.issues || []).some(i => i.level === 'error')).sort((x, y) => x.start_s - y.start_s)[0] || P.scenes.filter(x => x.stale).sort((x, y) => x.start_s - y.start_s)[0];
      const seg = P.segments.find(x => (x.issues || []).length);
      if (bad) return this.jump(bad.id);
      if (seg) return this.go('seg-' + seg.id);
      toast('Nothing to fix here.');
    },
    async approveAll(b, what) {
      const items = what === 'narration' ? P.segments.filter(x => x.status !== 'approved' && !x.locked) : P.scenes.filter(x => x.status !== 'approved' && !x.locked && !(x.issues || []).some(i => i.level === 'error'));
      if (!items.length) return toast('Everything is already approved.');
      if (!await confirmDlg('Approve ' + items.length + ' ' + what + '?', what === 'scenes' ? 'Scenes with an error are skipped. Approved parts are kept when you regenerate other parts.' : 'Approved narration is kept when you regenerate other parts.', 'Approve')) return;
      await act(b, async () => { for (const it of items) await api(what === 'narration' ? `/plans/segments/${it.id}` : `/plans/scenes/${it.id}`, {method: 'PATCH', json: what === 'narration' ? {status: 'approved'} : {status: 'approved'}}); return items.length; }, n => `Approved ${n} ${what}`);
      await load(true);
    },
    jump(sid) { const e = document.getElementById('sc-' + sid); if (e) e.scrollIntoView({behavior: 'smooth', block: 'center'}); },
  };

  const sentRow = (x, sid) => `<div class="sent"><textarea lang="hi" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'" onchange="_plan.segSave('${sid}')">${esc(x.text)}</textarea>
    <select onchange="_plan.segSave('${sid}')" title="How this sentence is spoken">${EMO.map(e => `<option ${e === x.emotion ? 'selected' : ''}>${e}</option>`).join('')}</select>
    <input type="number" min="0" max="10" step="0.2" value="${x.pause_after_s || 0}" onchange="_plan.segSave('${sid}')" title="Pause after the sentence, in seconds">
    <button class="small" title="Remove this sentence" onclick="_plan.segRemoveSentence(this,'${sid}')">×</button></div>`;

  function analyse() {
    const p = P, j = p.job, running = j.state === 'running';
    const v = p.validation || {}, vs = v.storyboard, vp = v.prompts;
    const issues = [...(v.issues || []).map(i => ({...i, part: 'Narration', level: i.level || 'error'})), ...((vs && vs.issues) || []).map(i => ({...i, part: 'Storyboard'})), ...((vp && vp.issues) || []).map(i => ({...i, part: 'Image prompts'}))];
    const compiled = p.scenes.length > 0 && p.scenes.every(s => s.data.prompts && s.data.prompts.qwen), promptStale = !!(vp && vp.issues.some(i => i.kind === 'stale'));
    const sc = v.scores || null, so = v.signoff || null, reviewed = !!(sc && sc.content_hash === p.content_hash);
    const voiceDone = !!(MS && MS.total && MS.have === MS.total), exportReady = !!(MS && MS.export.exists && MS.export.current);
    const refsDone = !!(RS && (RS.done || RS.total === 0)), refsOn = !!(RS && RS.total);
    const refsWait = !!(RS && RS.total && !RS.done && RS.open && !RS.without_pictures);
    const picsOn = !!(SS && SS.ready && SS.total), picsDone = !!(SS && SS.done);
    const gfxOn = !!(GS && GS.total), gfxDone = !!(GS && GS.done);
    const vidOn = !!(VS && VS.scenes), vidDone = !!(VS && VS.done);
    const sty = p.style || {}, charsDone = p.assets.length > 0 && !sty.registry_stale, sbStale = !!(p.scenes.length && sty.storyboard_stale);
    const voiceToApprove = MS ? MS.segments.map(r => r.attempts.find(a => a.id === r.chosen)).filter(a => a && !a.approved && !(a.flags || []).length) : [];
    const ap = p.approval || {state: 'draft'}, approved = ap.state === 'approved', lastExp = (p.exports || [])[0], exported = !!(lastExp && lastExp.content_hash === p.content_hash);
    const missingBeats = p.blueprint ? p.blueprint.beats.filter(b => !p.segments.some(s => s.beat === b.id)) : [];
    const segNoScene = p.segments.filter(s => !p.scenes.some(c => c.segment_id === s.id));
    const errors = issues.filter(i => i.level === 'error');
    const nRepeat = issues.filter(i => i.kind === 'repeat').length;
    const stale = p.scenes.filter(s => s.stale).length;
    const checked = !!(p.validation && p.validation.storyboard);
    const blocks = [], warns = [];
    if (!p.readiness.ready) blocks.push({t: p.readiness.checks.filter(c => c.level === 'blocked').map(c => c.text).join(' '), hint: 'Open the story list, approve the story there, and come back; or create the plan with “allow unapproved”.'});
    if (j.state === 'error') blocks.push({t: `The last step stopped: ${j.error} Finished parts are kept.`, hint: errHint(j.error), btn: ['Try again', '_plan.retry(this)']});
    if (!p.blueprint) blocks.push({t: 'The story is not planned yet.', btn: ['Plan the story', '_plan.blueprint(this)']});
    else if (missingBeats.length) blocks.push({t: `Narration is missing for ${missingBeats.length} of ${p.blueprint.beats.length} parts.`, btn: ['Write the missing narration', '_plan.narration(this,true)']});
    if (p.segments.length && segNoScene.length && !missingBeats.length) blocks.push({t: `${segNoScene.length} narration part(s) have no scenes yet.`, btn: ['Design the storyboard', '_plan.storyboard(this)']});
    if (errors.length) blocks.push({t: `${errors.length} error(s) must be fixed before you move on: ${[...new Set(errors.map(e => e.kind.replace(/_/g, ' ')))].join(', ')}. Each is explained below with what the app can do about it.`, btn: (p.blockers || []).length ? null : ['Check again', '_plan.validate(this)']});
    if (running) warns.push(`A step is running (${j.kind}: ${j.label}). Buttons wait until it ends.`);
    if (p.scenes.length && !checked) warns.push('Not checked since your last change. Press “Check everything”.');
    if (stale) warns.push(`${stale} scene(s) follow narration you changed: look at them, then approve.`);
    if (nRepeat) warns.push(`${nRepeat} scene(s) repeat the previous camera: use “Fix camera repeats”.`);
    if (p.scenes.length && !segNoScene.length && (!compiled || promptStale)) warns.push(promptStale ? 'Some scenes changed after their image prompts were written: press “Write image prompts”.' : 'Image prompts are not written yet: press “Write image prompts”.');
    return {refsWait, vidOn, vidDone, gfxOn, gfxDone, picsOn, picsDone, sty, charsDone, sbStale, refsDone, refsOn, voiceToApprove, voiceDone, exportReady, sc, so, reviewed, ap, approved, lastExp, exported, compiled, promptStale, j, running, v, vs, issues, missingBeats, segNoScene, errors, nRepeat, stale, checked, blocks, warns};
  }

  function render() {
    const p = P;
    const imSet = {default: 'qwen-image-2.1', by_type: {}, previews_enabled: false, ...(p.settings.image_models || {})};
    imSet.licence_checks = {'qwen-image-2.1': true, 'flux2-klein-9b': true, ...(imSet.licence_checks || {})};
    const modelFor = d => d.model || (imSet.by_type || {})[d.visual_type] || imSet.default;
    const a = analyse(), {refsWait, vidOn, vidDone, gfxOn, gfxDone, picsOn, picsDone, sty, charsDone, sbStale, refsDone, refsOn, voiceToApprove, voiceDone, exportReady, sc, so, reviewed, ap, approved, lastExp, exported, compiled, promptStale, j, running, v, vs, issues, missingBeats, segNoScene, errors, nRepeat, checked, blocks, warns} = a;
    const dis = running ? 'disabled' : '';
    const DRAFT = window._drafts = window._drafts || {}, MODELS = (SS && SS.model_info) || {};
    const steps = [['Story', true], ['Blueprint', !!p.blueprint], ['Narration', p.segments.length && p.blueprint && !missingBeats.length], ['Characters', charsDone], ['Storyboard', p.scenes.length && !segNoScene.length && !sbStale], ['References', refsDone], ['Image prompts', compiled && !promptStale],
      ['Checked', checked && !errors.length], ['Reviewed', reviewed], ['Approved', approved], ['Exported', exported], ['Voice', voiceDone], ...(picsOn ? [['Scene pictures', picsDone]] : []), ...(gfxOn ? [['Graphics', gfxDone]] : []), ...(vidOn ? [['Draft video', vidDone]] : [])];
    const firstOpen = steps.findIndex(s => !s[1]);
    const sceneAt = wid => p.scenes.find(x => x.id === wid) || null;
    const groups = []; for (const i of issues) { const k = i.part + '|' + i.kind + '|' + (i.kind === 'repeat' ? '' : i.text); let g = groups.find(x => x.k === k); if (!g) groups.push(g = {k, i, where: []}); g.where.push(i.where); }
    groups.sort((x, y) => (x.i.level === 'error' ? 0 : 1) - (y.i.level === 'error' ? 0 : 1));
    const segName = sid => { const s = p.segments.find(x => x.id === sid); const b = s && p.blueprint && p.blueprint.beats.find(x => x.id === s.beat); return b ? b.name : sid; };
    const ordered = [...p.scenes].sort((x, y) => x.start_s - y.start_s);
    const total = p.duration_s || 1;
    const segApproved = p.segments.filter(s => s.status === 'approved' || s.locked).length, scApproved = p.scenes.filter(s => s.status === 'approved' || s.locked).length;

    // side panel: one row per action, in the order you do them
    const act_ = (n, label, onclick, {done, ok = true, why = '', next = false, cls = ''}) => `<div class="act ${done ? 'done' : next ? 'next' : ''}">
        <div class="an">${done ? '✓' : n}</div><div style="flex:1;min-width:0"><button class="${next ? 'primary' : cls}" style="width:100%" ${ok && !running ? '' : 'disabled'} onclick="${onclick}">${label}</button>${!ok && why ? `<div class="small mute mt-s">${esc(why)}</div>` : ''}${STEP_WHAT[n] && (P.steps_done || {})[STEP_WHAT[n]] ? `<div class="small mute" style="margin-top:2px">finished ${agoSpan(P.steps_done[STEP_WHAT[n]])} · ${clock(P.steps_done[STEP_WHAT[n]])}</div>` : ''}</div></div>`;
    const nextKey = !p.blueprint ? 'blueprint' : missingBeats.length ? 'narration' : !charsDone ? 'characters' : (segNoScene.length || !p.scenes.length || sbStale) ? 'storyboard' : (refsOn && !refsDone) ? 'refs' : (!compiled || promptStale) ? 'prompts' : !checked ? 'check' : nRepeat ? 'repeats' : !reviewed ? 'review' : !approved ? (so && so.blockers.length ? 'blocked' : 'approve') : !exported ? 'export' : !voiceDone ? 'voice' : (picsOn && !picsDone) ? 'pictures' : (gfxOn && !gfxDone) ? 'graphics' : (vidOn && !vidDone) ? 'video' : 'done';
    const autoBox = AU && AU.remaining ? `<div class="mt-s" style="margin-bottom:10px"><button class="primary" style="width:100%" ${running ? 'disabled' : ''} title="Does every unfinished step in order and takes the default at each choice" onclick="_plan.autoRun(this)">▶ Run everything automatically (${AU.remaining} step${AU.remaining === 1 ? '' : 's'} left)</button><div class="small mute mt-s">Next: ${esc((AU.stages.find(s => s.key === AU.next) || {}).label || '')}. Approves the first good outcome of each step.</div></div>` : AU ? `<div class="small mute" style="margin-bottom:10px">Every step is finished.</div>` : '';
    const side = `<aside class="plan-side"><div class="card pad">
        ${running ? `<div class="jobbox"><b>${esc(j.kind)}</b> <span class="mute small">${esc(j.label)}</span>${bar(j.total ? 100 * j.done / j.total : 5)}<div class="small mute">${hd(j.elapsed_s)}${j.eta_s ? ' · about ' + hd(j.eta_s) + ' left' : ''}</div><button class="small mt-s" onclick="_plan.cancel(this)">Stop after this step</button><div class="small mute mt-s">You can leave the page; finished parts are saved.</div></div>` : ''}
        ${autoBox}
        <div class="small mute" style="text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">Do these in order</div>
        ${act_(1, p.blueprint ? 'Plan the story again' : 'Plan the story', '_plan.blueprint(this)', {done: !!p.blueprint && nextKey !== 'blueprint', ok: p.readiness.ready, why: 'This story cannot be planned yet.', next: nextKey === 'blueprint', cls: 'small'})}
        ${act_(2, missingBeats.length && p.segments.length ? `Write the ${missingBeats.length} missing part(s)` : p.segments.length ? 'Rewrite all narration' : 'Write the narration', `_plan.narration(this,${!!(missingBeats.length && p.segments.length)})`, {done: p.segments.length && !missingBeats.length, ok: !!p.blueprint, why: 'Plan the story first.', next: nextKey === 'narration'})}
        ${act_(3, charsDone ? 'Create characters and places again' : 'Create characters and places', '_plan.registry(this)', {done: charsDone, ok: p.segments.length > 0 && !missingBeats.length, why: 'Write all the narration first.', next: nextKey === 'characters'})}
        ${act_(4, sbStale ? 'Redesign all scenes in the chosen style' : p.scenes.length && segNoScene.length ? `Design the ${segNoScene.length} missing part(s)` : p.scenes.length ? 'Design all scenes again' : 'Design the storyboard', '_plan.storyboard(this' + (p.scenes.length && (!segNoScene.length || sbStale) ? ',true' : '') + ')', {done: p.scenes.length && !segNoScene.length && !sbStale, ok: p.segments.length && !missingBeats.length && charsDone, why: charsDone ? 'Write all the narration first.' : 'Create the characters and places first.', next: nextKey === 'storyboard'})}
        ${act_(5, refsDone ? 'Make reference pictures again' : refsWait ? (RS.bulk_ready ? `Approve the best reference pictures (${RS.bulk_ready})` : 'Choose the reference pictures') : RS && RS.open && RS.open < RS.total ? 'Make the missing reference pictures' : 'Make reference pictures', refsWait ? (RS.bulk_ready ? '_plan.refsApproveBest(this)' : "_plan.go('sec-refs')") : '_plan.refsAll(this)', {done: refsDone, ok: refsOn && charsDone, why: refsOn ? 'Create the characters and places first.' : 'No person, place or object to draw yet.', next: nextKey === 'refs'})}
        ${refsWait && !refsDone ? `<div class="small" style="margin:-4px 0 6px 34px;color:var(--warn)">✓ pictures are made; ${RS.open} item(s) wait for your approval</div>` : ''}
        ${act_(6, compiled && !promptStale ? 'Write image prompts again' : 'Write image prompts', '_plan.compile(this)', {done: compiled && !promptStale, ok: p.scenes.length > 0 && !segNoScene.length, why: 'Design the storyboard first.', next: nextKey === 'prompts'})}
        ${act_(7, 'Check everything', '_plan.validate(this)', {done: checked && !errors.length, ok: p.segments.length > 0, why: 'Nothing to check yet.', next: nextKey === 'check'})}
        ${act_(8, nRepeat ? `Fix ${nRepeat} camera repeat(s)` : 'Fix camera repeats', '_plan.fixRepeats(this)', {done: checked && !nRepeat, ok: nRepeat > 0, why: checked ? 'No repeats found.' : 'Run the check first.', next: nextKey === 'repeats'})}
        ${act_(9, reviewed ? 'Review and score again' : 'Review and score', '_plan.review(this)', {done: reviewed, ok: p.scenes.length > 0 && compiled, why: 'Write the image prompts first.', next: nextKey === 'review'})}
        ${act_(10, approved ? 'Approved' : ap.state === 'changed' ? 'Approve the changed plan' : 'Approve the plan', '_plan.approve(this)', {done: approved, ok: reviewed, why: 'Review and score first.', next: nextKey === 'approve'})}
        ${act_(11, exported ? 'Export again' : 'Export for the next modules', '_plan.export(this)', {done: exported, ok: p.scenes.length > 0 && compiled, why: 'Write the image prompts first.', next: nextKey === 'export'})}
        ${act_(12, voiceDone ? 'Make the voice again' : MS && MS.have ? 'Make the missing voice' : 'Make the voice', '_plan.voiceAll(this)', {done: voiceDone, ok: exportReady, why: exported ? 'Export again first.' : 'Export first.', next: nextKey === 'voice'})}
        ${act_(13, picsDone ? 'Scene pictures: all approved' : SS && SS.settings.chosen ? (SS.needs_choice && !SS.needs_picture ? 'Approve the best scene pictures' : 'Draw the scene pictures') : 'Run the three-scene picture trial', SS && SS.settings.chosen ? (SS.needs_choice && !SS.needs_picture ? '_plan.picsApproveBest(this)' : '_plan.picsAll(this)') : '_plan.picsTrial(this)', {done: picsDone, ok: picsOn, why: 'Write the image prompts first.', next: nextKey === 'pictures'})}
        ${act_(14, gfxDone ? 'Graphics: all approved' : GS && GS.needs_build ? `Build the ${GS.needs_build} graphic(s)` : 'Approve the graphics', GS && GS.needs_build ? '_plan.gfxBuild(this)' : '_plan.gfxApproveAll(this)', {done: gfxDone, ok: gfxOn, why: 'No scene needs a chart, document, screen, map or diagram.', next: nextKey === 'graphics'})}
        ${act_(15, vidDone ? 'Make the draft video again' : 'Make the draft video', "_plan.vidBuild(this,'draft')", {done: vidDone, ok: !!(VS && VS.tools.ffmpeg && vidOn), why: VS && !VS.tools.ffmpeg ? 'ffmpeg was not found on this machine.' : 'Write the image prompts first.', next: nextKey === 'video'})}
        ${act_(16, 'Go to the first problem', '_plan.firstProblem()', {done: false, ok: issues.some(i => i.level === 'error') || a.stale > 0, why: 'No errors to fix.', cls: 'small'})}
        <div class="small mute" style="text-transform:uppercase;letter-spacing:.04em;margin:12px 0 6px">When you are happy</div>
        <button class="small" style="width:100%" ${p.segments.length && !running ? '' : 'disabled'} onclick="_plan.approveAll(this,'narration')">Approve all narration (${segApproved}/${p.segments.length})</button>
        <button class="small mt-s" style="width:100%" ${p.scenes.length && !running ? '' : 'disabled'} onclick="_plan.approveAll(this,'scenes')">Approve all scenes (${scApproved}/${p.scenes.length})</button>
        <div class="small mute mt-s">Approved and locked parts are never overwritten when something else is regenerated.</div>
        <div class="small mute" style="text-transform:uppercase;letter-spacing:.04em;margin:12px 0 6px">Jump to</div>
        <div class="row small" style="gap:4px 12px">${[['sec-top', 'Top'], p.blueprint && ['sec-blueprint', 'Blueprint'], p.segments.length && ['sec-narration', 'Narration'], p.segments.length && ['sec-style', 'Visual style'], p.segments.length && ['sec-assets', 'Characters and places'], refsOn && ['sec-refs', 'Reference pictures'], p.scenes.length && ['sec-models', 'Image models'], p.scenes.length && ['sec-storyboard', 'Storyboard'], p.scenes.length && ['sec-review', 'Review and export'], MS && ['sec-voice', 'Voice'], picsOn && ['sec-pictures', 'Scene pictures'], gfxOn && ['sec-graphics', 'Graphics'], vidOn && ['sec-video', 'Draft video'], (groups.length || v.ok != null) && ['sec-results', 'Check results']].filter(Boolean).map(([id_, l]) => `<a href="#" onclick="_plan.go('${id_}');return false">${l}</a>`).join('')}</div>
      </div></aside>`;

    const sd = P.steps_done || {};
    const lastKey = Object.keys(sd).filter(k => k !== 'auto_run').sort((x, y) => sd[y] - sd[x])[0];
    const lastLine = lastKey ? `<div class="small mute" style="margin:6px 0">Last step finished: <b>${esc(WHAT_LABEL[lastKey] || lastKey)}</b> ${agoSpan(sd[lastKey])} (at ${clock(sd[lastKey])})${running ? ` · now running: <b>${esc(j.kind)}</b> for ${hd(j.elapsed_s)}` : ''}</div>` : '';
    const fixNote = window._fixNote || (j.state === 'done' && j.note ? j.note : '');
    const noteBox = fixNote ? `<div class="banner ${errors.length ? 'warn' : 'good'}" style="margin:6px 0"><b>What the last fix did</b><div class="small">${esc(fixNote)}</div></div>` : '';
    const banner = lastLine + noteBox + (blocks.length
      ? `<div class="banner block"><b>Stopping you from moving on</b><ul class="tight">${blocks.map(b => { b = typeof b === 'string' ? {t: b} : b; return `<li>${esc(b.t)}${b.btn ? ` <button class="small primary" ${dis} onclick="${b.btn[1]}">${esc(b.btn[0])}</button>` : ''}${b.hint ? `<div class="small mute">${esc(b.hint)}</div>` : ''}</li>`; }).join('')}</ul>
        ${(p.blockers || []).map(bk => `<div class="needbox mt-s"><div class="row"><b>${esc(bk.title)}</b>${badge('error', bk.count + (bk.count > 1 ? ' places' : ' place'))}</div>
          <div class="small">${esc(bk.why)}</div><div class="small mute mt-s">Example: ${esc(bk.sample)}${bk.when.length ? ` · scenes at ${bk.when.slice(0, 6).map(mmss).join(', ')}${bk.when.length > 6 ? ' …' : ''}` : ''}</div>
          ${bk.note ? `<div class="small mt-s">⚠ ${esc(bk.note)}</div>` : ''}
          <div class="row mt-s">${bk.fixes.map((f, i) => `<button class="small ${i ? '' : 'primary'}" ${dis} title="${esc(f.does)}" onclick="_plan.resolve(this,'${esc(bk.key)}','${f.id}')">${esc(f.label)}</button>`).join('')}<button class="small" onclick="_plan.go('${bk.jump}')">Go to it</button></div>
          <div class="small mute mt-s"><b>${esc(bk.fixes[0].label)}:</b> ${esc(bk.fixes[0].does)}${bk.manual ? ` <b>If that is not enough:</b> ${esc(bk.manual)}` : ''}</div></div>`).join('')}${warns.length ? `<div class="small mt-s">Also: ${warns.map(esc).join(' · ')}</div>` : ''}</div>`
      : warns.length ? `<div class="banner warn"><b>Nothing blocks you, but note:</b><ul class="tight">${warns.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>`
      : nextKey === 'done' ? `<div class="banner good"><b>Done so far.</b> Export v${lastExp.rev} is saved and the voice is made (${mmss(MS.real_s)} of real speech). Reference pictures are approved (${RS && RS.total ? RS.approved + ' approved, ' + RS.skipped + ' skipped' : 'none needed'}). ${picsOn ? 'Scene pictures are approved (' + SS.approved + ' of ' + SS.total + '). ' : ''}${gfxOn ? 'Graphics are approved (' + GS.approved + ' of ' + GS.total + '). ' : ''}${vidOn && vidDone ? 'The draft video is made (' + mmss(VS.videos.filter(v => v.profile === 'draft').slice(-1)[0].duration_s) + '). ' : ''}Music and upload are later projects; export again later to include the references in the file. <a href="/api/plans/exports/${esc(p.id)}/${esc(lastExp.file)}" download>Download the export</a>. Listen and look below and approve what you like.</div>`
      : `<div class="banner good"><b>Nothing is blocking you.</b> Narration, storyboard and image prompts are consistent and checked.</div>`);
    const NEXT = {blueprint: ['Plan the story', 'Decide how this story is told.', '_plan.blueprint(this)'], narration: ['Write the narration', 'Write the spoken narration for each part.', '_plan.narration(this,' + !!(missingBeats.length && p.segments.length) + ')'],
      characters: ['Create characters and places', `List the people, places and objects the story needs, drawn to fit the chosen style (${sty.label || 'style'}). Then draw each one once so they look the same in every scene.`, '_plan.registry(this)'],
      refs: refsWait ? [RS.bulk_ready ? 'Approve the best reference pictures' : 'Choose the reference pictures', `The pictures are made. ${RS.open} item(s) still wait for your approval${RS.bulk_ready ? `; ${RS.bulk_ready} have a picture that scores ${RS.min_score}+ with no problem, so “Approve the best” can take them` : ''}. Look at them first (Reference pictures section), approve one per item, or skip it.`, RS.bulk_ready ? '_plan.refsApproveBest(this)' : "_plan.go('sec-refs')"]
        : ['Make reference pictures', RS ? `${RS.open} recurring thing(s) still need a picture you approve (about ${hd(RS.eta_missing_s || RS.seconds_per_picture * 2)} of drawing). Approve one per item, or skip it.` : '', '_plan.refsAll(this)'],
      storyboard: [sbStale ? 'Redesign the scenes in the chosen style' : 'Design the storyboard', sbStale ? 'The scenes were designed for another look (or the older chart style). Redesign them as story pictures; approved scenes are replaced.' : 'Design the scenes that go with the narration.', '_plan.storyboard(this' + (sbStale ? ',true' : '') + ')'], prompts: ['Write image prompts', 'Turn each scene into prompts for the image models. Instant, no model needed.', '_plan.compile(this)'],
      check: ['Check everything', 'Look for mistakes before you review.', '_plan.validate(this)'], repeats: ['Fix camera repeats', 'Some scenes repeat the previous camera.', '_plan.fixRepeats(this)'],
      review: ['Review and score', 'See twelve scores with reasons, and what stands between this plan and approval.', '_plan.review(this)'], approve: ['Approve the plan', 'Sign off the exact version you reviewed.', '_plan.approve(this)'],
      export: ['Export', 'Save the file the image, voice and video modules will read.', '_plan.export(this)'],
      voice: ['Make the voice', 'The voice model reads each narration part; scenes are re-timed to the real audio. About ' + (MS ? hd(MS.eta_missing_s) : 'a while') + '.', '_plan.voiceAll(this)'],
      pictures: !SS ? ['Scene pictures', '', "_plan.go('sec-pictures')"] : !SS.settings.chosen && !SS.trial_done ? ['Run the three-scene picture trial', `Draw an opening, a character scene and a scene with quoted text on both models, plain and from the reference sheets (up to 12 pictures, about ${hd(3 * 2 * (SS.seconds_per_picture['qwen-image-2.1'] + SS.seconds_per_picture['flux2-klein-9b']))}). You pick the way that keeps the people the same.`, '_plan.picsTrial(this)']
        : !SS.settings.chosen ? ['Choose how to draw', 'Look at the trial pictures, then press the “Use ... for all scenes” button for the way that looks best.', "_plan.go('sec-pictures')"]
        : SS.needs_picture ? ['Draw the scene pictures', `${SS.needs_picture} scene(s) have no picture yet (about ${hd(SS.eta_missing_s)} with ${SS.models[SS.settings.model] || 'the plan model'}). Finished pictures are saved even if you stop.`, '_plan.picsAll(this)']
        : ['Approve the scene pictures', `${SS.needs_choice} scene(s) have pictures waiting for your choice. “Approve the best” takes the best one of each that scores ${SS.min_score}+ without a hard problem.`, '_plan.picsApproveBest(this)'],
      graphics: GS && GS.needs_build ? ['Build the graphics', `${GS.needs_build} scene(s) show a chart, document, screen, map or diagram. Cards are built from the numbers and dates in the story's facts (instant, no model needed).`, '_plan.gfxBuild(this)']
        : ['Approve the graphics', GS ? `${GS.needs_choice} graphic(s) wait for you${GS.fallbacks ? `; ${GS.fallbacks} are not what the scene wanted (the facts are thin), so look at those yourself` : ''}.` : '', '_plan.gfxApproveAll(this)'],
      video: ['Make the draft video', VS ? (VS.blockers.length ? `${VS.blockers.length} thing(s) are missing (listed in the Draft video section); you can build anyway with labelled placeholders.` : `A 1080p video with the approved pictures, graphics and voice${VS.warnings.length ? ` (${VS.warnings.length} item(s) not approved yet are used and listed)` : ''}. About ${hd((VS.profiles.draft || {}).eta_s || 0)}. A small preview takes much less.`) : '', "_plan.go('sec-video')"],
      blocked: ['See what blocks approval', `${so ? so.blockers.length : 0} thing(s) stand between this plan and approval: ${so ? so.blockers.map(b => b.text).join(' ') : ''}`, "_plan.go('sec-review')"]};
    const nx = NEXT[nextKey];
    const nextBar = nx ? `<div class="nextbar"><span><b>Next:</b> ${esc(nx[1])}</span><span class="row" style="gap:8px">${AU && AU.remaining > 1 ? `<button ${running ? 'disabled' : ''} title="Do this and every later step automatically" onclick="_plan.autoRun(this)">▶ Run all ${AU.remaining} steps automatically</button>` : ''}<button class="primary" ${running ? 'disabled' : ''} onclick="${nx[2]}">${esc(nx[0])}</button></span></div>` : '';
    const fixLinks = f => { const w = f.where || []; const secs = {narration: 'sec-narration', storyboard: 'sec-storyboard', prompts: 'sec-storyboard', continuity: 'sec-assets', models: 'sec-models', results: 'sec-results', plan: 'sec-top', review: 'sec-review'};
      const one = id_ => id_.startsWith('sc-') ? `<a href="#" onclick="_plan.jump('${id_}');return false">${mmss((sceneAt(id_) || {}).start_s || 0)}</a>` : id_.startsWith('seg-') ? `<a href="#" onclick="_plan.go('seg-${id_}');return false">${esc(segName(id_))}</a>` : '';
      const ls = w.map(one).filter(Boolean); return ls.length ? '<span class="mute">(' + ls.slice(0, 5).join(', ') + (ls.length > 5 ? ` +${ls.length - 5} more` : '') + ')</span>' : (secs[f.tab] ? `<a href="#" onclick="_plan.go('${secs[f.tab]}');return false">go there</a>` : ''); };

    app.innerHTML = `<div id="plan"><span id="sec-top"></span>
      <div class="row"><a href="#/p/${esc(p.project_id)}/plans">← Video plans</a><span class="mute">·</span><a href="#/p/${esc(p.project_id)}/stories?s=${esc(p.candidate_id)}">the story</a><span class="sp"></span><button class="small" onclick="_plan.delPlan()">Delete plan</button></div>
      <div class="row mt-s"><h2 style="margin:0">Video plan</h2>${badge('info', p.format + ' long-form')}${badge('info', p.story_type_label || 'Incident story')}${p.project_story_type && p.project_story_type !== p.story_type ? badge('warn', 'project is now ' + p.project_story_type + '; this plan was made as ' + p.story_type + '. Start a new plan to follow the new type') : ''}${badge('warn', 'facts not independently verified')}<span class="mute small">${esc(p.id)}</span></div>
      <div class="plan-steps">${steps.map(([l, ok], i) => `<span class="${ok ? 'done' : i === firstOpen ? 'on' : ''}">${ok ? '✓ ' : ''}${l}</span>`).join('')}</div>
      ${nextBar}${banner}
      <div class="plan-grid"><div class="plan-main">
      <div class="card pad"><div class="row" style="margin-bottom:8px"><label class="f" style="flex:1">Video title (your own — not the article headline)<input id="vtitle" value="${esc(p.settings.video_title || '')}" placeholder="${esc(p.working_title || 'e.g. How one click lost ₹64 crore')}" onchange="_plan.setTitle(this)"></label></div>
      <div class="row"><label class="f" style="min-width:230px">Narrator name (first person; set later)<input id="nname" value="${esc(p.narrator.name || '')}" placeholder="not set yet" onchange="_plan.narrator(this)"></label>
        <label class="f" style="width:150px">Target length (min)<input type="number" min="1" max="40" step="0.5" value="${p.settings.minutes}" onchange="_plan.minutes(this)"></label>
        <span class="mute small" style="flex:1;min-width:240px">The narrator is a guide: "I" shows and reacts, and never claims to have been there. Nothing refers to a book, an author or a source, and nothing is quoted.</span></div></div>

      <details class="card pad mt" ${p.blueprint ? '' : 'open'}><summary><b>Is the story ready?</b> ${badge(p.readiness.level === 'ok' ? 'good' : p.readiness.level === 'blocked' ? 'problem' : 'warn', p.readiness.level)}</summary>
        <ul class="tight mt-s">${p.readiness.checks.map(c => `<li><span class="${c.level === 'blocked' ? 'err' : ''}">${c.level === 'blocked' ? '✗' : '•'}</span> ${esc(c.text)}</li>`).join('')}</ul></details>

      ${p.blueprint ? `<div class="card pad mt" id="sec-blueprint"><div class="row"><h3 style="margin:0">Blueprint</h3>${badge('info', p.blueprint.structure.replace(/_/g, ' '))}</div>
        <div class="mt-s"><b>Viewer promise:</b> ${esc(p.blueprint.viewer_promise)}</div><div><b>Central question:</b> ${esc(p.blueprint.central_question)}</div><div class="mute small">${esc(p.blueprint.why_structure)}</div>${p.blueprint.cold_open ? `<div><b>Cold open:</b> ${esc(p.blueprint.cold_open)}</div>` : ''}${p.blueprint.stakes ? `<div><b>At stake:</b> ${esc(p.blueprint.stakes)}</div>` : ''}${p.blueprint.false_answer ? `<div><b>The wrong answer first:</b> ${esc(p.blueprint.false_answer)}</div>` : ''}
        <div class="mt-s">${p.blueprint.beats.map(b => `<div class="beatrow"><b>${esc(b.id)}</b><span>${esc(b.name)}</span><span>${esc(b.purpose)}</span><span class="mute">${esc(b.takeaway)}</span></div>`).join('')}</div></div>` : ''}

      ${p.segments.length ? `<div class="mt" id="sec-narration"><div class="row"><h3 style="margin:0">Narration (Hindi)</h3><span class="mute">${mmss(p.duration_s)} spoken · target ${mmss(p.settings.minutes * 60)}</span></div>
        ${p.segments.map((s, i) => `<div class="seg ${s.locked ? 'locked' : s.status === 'approved' ? 'approved' : ''}" data-seg="${s.id}" id="seg-${s.id}">
          <div class="row"><b>${esc(segName(s.id))}</b><span class="mute small">${mmss(s.duration_s)} · ${s.sentences.length} sentences</span>${badge(s.status === 'approved' ? 'approved' : s.status === 'edited' ? 'info' : 'queued', s.status)}${s.locked ? badge('info', 'locked') : ''}<span class="sp"></span>
            <button class="small" ${i ? '' : 'disabled'} title="Move earlier" onclick="_plan.segMove('${s.id}',-1)">↑</button><button class="small" ${i < p.segments.length - 1 ? '' : 'disabled'} title="Move later" onclick="_plan.segMove('${s.id}',1)">↓</button>
            <button class="small" ${dis} onclick="_plan.beat(this,'${s.beat}')" title="Write this beat again">Rewrite</button>
            <button class="small" onclick="_plan.segSet('${s.id}',{status:'${s.status === 'approved' ? 'draft' : 'approved'}'})">${s.status === 'approved' ? 'Unapprove' : 'Approve'}</button>
            <button class="small" onclick="_plan.segSet('${s.id}',{locked:${!s.locked}})">${s.locked ? 'Unlock' : 'Lock'}</button></div>
          <div class="sents mt-s">${s.sentences.map(x => sentRow(x, s.id)).join('')}</div>
          <div class="row mt-s"><button class="small" onclick="_plan.segAddSentence('${s.id}')">+ sentence</button><span class="mute small">emotion and pause are how it is spoken; change the words freely, the scenes follow.</span></div>
          <details class="mt-s"><summary class="small mute">Text with emotion tags (used by Svara; Veena speaks the plain sentences)</summary><div class="passage small" lang="hi">${esc(s.annotated)}</div></details>
          ${(s.issues || []).map(i => `<div class="iss ${i.kind === 'svara' || i.kind === 'script' ? 'error' : 'warn'}">⚠ ${esc(i.kind.replace(/_/g, ' '))}: ${esc(i.text)}</div>`).join('')}</div>`).join('')}</div>` : ''}

      ${p.segments.length ? `<div class="card pad mt" id="sec-style"><div class="row"><h3 style="margin:0">Visual style</h3>${sty.registry_stale || sbStale ? badge('warn', 'characters or scenes were made for another look') : badge('good', 'in use: ' + esc(sty.short || ''))}</div>
        <div class="mute small mt-s">The whole video is drawn as illustrated story scenes in one look: the style below is written into the characters, every scene prompt and every reference picture. Choose it before creating the characters. Changing it later updates the prompts at once; characters and scenes made for the old look are redone with the buttons in the side panel.</div>
        <div class="row mt-s" style="gap:12px;align-items:stretch;flex-wrap:wrap">${[['filmic', 'Cinematic film still (painted)', 'Painted realism like a feature-film still: natural colour grade, grounded light, real-looking people.'], ['gta', 'Game-art illustration (GTA-style)', 'Bold outlines, cel-shaded colour with painterly gradients, saturated cinematic colour and strong rim light.'], ['noir', 'Noir graphic novel', 'Heavy black ink, crosshatching and halftone dots, deep blue, red and amber, hard shadows.'], ['concept', 'Painterly game concept art', 'Soft painterly brushwork, moody filmic light and atmosphere.']].map(([sid, name, desc]) => `<div style="width:230px;border:${(p.settings.visual_style || 'filmic') === sid ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'};border-radius:8px;padding:6px;cursor:pointer" onclick="_plan.setStyle('${sid}')"><img src="/style-samples/${sid}.jpg" loading="lazy" style="width:100%;border-radius:5px"><div class="small mt-s"><b>${name}</b>${(p.settings.visual_style || 'filmic') === sid ? ' ✓' : ''}</div><div class="small mute">${desc}</div></div>`).join('')}</div>
        <div class="mute small mt-s">The pictures above were drawn from the same scene by the same model, only the style words differ. Characters are invented composite people with faces; a real, named person is only ever shown as a silhouette, from behind or in shadow.</div></div>` : ''}
      ${p.segments.length ? `<div class="card pad mt" id="sec-cast"><div class="row"><h3 style="margin:0">Who appears in the pictures</h3>${p.assets.length || p.settings.cast_indian !== undefined ? '' : badge('warn', 'choose one before creating the characters')}</div>
        <div class="row mt-s" style="gap:12px;flex-wrap:wrap">${[[true, 'Indian cast', 'Every person is drawn as an Indian person, whatever the country of the story. Good for an Indian audience and for stories with no fixed setting.'], [false, 'As the story says (AI suggested)', 'The model picks the look, name and clothes of each person from the country, period and community. Use it for foreign or historical stories.']].map(([v, name, desc]) => `<div style="width:300px;border:${p.settings.cast_indian !== undefined && (p.settings.cast_indian !== false) === v ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'};border-radius:8px;padding:8px;cursor:pointer" onclick="${dis ? '' : `_plan.cast(this,${v})`}"><b>${name}</b>${p.settings.cast_indian !== undefined && (p.settings.cast_indian !== false) === v ? ' ✓' : ''}<div class="small mute">${desc}</div></div>`).join('')}</div>
        <div class="mute small mt-s">${p.assets.length ? 'Characters already exist: changing this rewrites the image prompts and marks pictures made the other way as old. Use “Create again” in the list below to have the model write the characters for the new choice.' : 'Characters are written for this choice when you create them.'}</div></div>
      <div class="mt" id="sec-assets"><div class="row"><h3 style="margin:0">Characters, places and objects</h3><span class="small mute">${p.settings.cast_indian === false ? 'cast: as the story says' : 'cast: Indian'}</span><span class="sp"></span><button class="small" ${dis} onclick="_plan.addAsset()">Add one</button><button class="small" ${dis || (!p.assets.length && p.settings.cast_indian === undefined) ? 'disabled title="Choose who appears in the pictures first (the card above)"' : ''} onclick="_plan.registry(this)">${p.assets.length ? 'Create again' : 'Create them'}</button></div>
        ${(p.cast_gaps || []).length ? `<div class="needbox mt-s"><b>${p.cast_gaps.length} of ${p.assets.filter(x => ['person', 'place', 'prop'].includes(x.kind)).length} have gaps in their description.</b> The picture models draw exactly what is written and invent whatever is missing, so a missing detail changes from scene to scene: ${p.cast_gaps.map(g => `<b>${esc(g.name)}</b> (${g.missing.map(m => esc(m)).join(', ')})`).join('; ')}. <button class="small" ${dis} onclick="_plan.assetFill()">Fill in the gaps</button></div>` : ''}
        <div class="card pad mt-s">${p.assets.length ? p.assets.map(x => `<div class="assetrow"><span>${badge('info', x.kind)}</span><div><b>${esc(x.name)}</b> ${x.data.fictionalisation ? `<span class="mute small">${esc(x.data.fictionalisation.replace(/_/g, ' '))}</span>` : ''}<div>${esc(x.data.description || (x.kind === 'narrator' ? 'Avatar to be designed (outside this module).' : ''))}</div>${(x.data.fixed || []).length ? `<div class="mute small">always: ${esc(x.data.fixed.join('; '))}</div>` : ''}</div>
          ${x.kind === 'person' ? likenessBox(x, dis) : ''}<div class="row"><button class="small" onclick="_plan.assetEdit('${x.id}')">Edit</button><button class="small" onclick="_plan.assetLock('${x.id}',${!x.locked})">${x.locked ? 'Unlock' : 'Lock'}</button></div></div>`).join('') : '<span class="mute">Not listed yet. Press “Create characters and places”.</span>'}</div></div>` : ''}

      ${p.scenes.length ? `<div class="card pad mt" id="sec-models"><div class="row"><h3 style="margin:0">Image models</h3><span class="mute small">Qwen Image 2.1 is the default. Nothing is picked by ranking; judge by previews.</span></div>
        <div class="row mt-s"><label class="f" style="width:240px">Default model<select onchange="_plan.imageModels({default:this.value})">${(PV.providers || []).map(m => `<option value="${m.id}" ${m.id === imSet.default ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select></label>
          <label class="f" style="flex:1;min-width:260px;flex-direction:row;align-items:center;gap:8px"><input type="checkbox" ${imSet.previews_enabled ? 'checked' : ''} onchange="_plan.imageModels({previews_enabled:this.checked})"> Allow one-image previews (uses the image model; off by default)</label></div>
        <details class="mt-s"><summary class="small">Different model for some scene types</summary><div class="row mt-s" style="gap:6px 16px">${[...new Set(p.scenes.map(s => s.data.visual_type))].map(t => `<label class="f small" style="width:210px">${VT_LABEL[t]}<select onchange="_plan.byType('${t}',this.value)"><option value="">plan default</option>${(PV.providers || []).map(m => `<option value="${m.id}" ${(imSet.by_type || {})[t] === m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select></label>`).join('')}</div></details>
        <div class="mt-s">${(PV.providers || []).map(m => `<div class="small mt-s"><b>${esc(m.label)}</b> · ${m.negative_prompt ? 'honours a negative prompt' : 'ignores a negative prompt (exclusions go in the prompt)'} · edits with up to ${m.max_references} reference images, no masks · text in images unreliable · ${m.discovered ? 'listed by the gateway, not audited here' : `steps ${m.steps}, cfg ${m.cfg}`}
          <div class="mute">${esc(m.variant)}</div>
          <label style="display:flex;gap:8px;align-items:flex-start;margin-top:3px"><input type="checkbox" ${(imSet.licence_checks || {})[m.id] ? 'checked' : ''} onchange="_plan.licence('${m.id}',this.checked)"> <span><b>Licence is not treated as a blocker</b> (open-source model; your decision). Untick to bring the reminder back.</span></label></div>`).join('')}</div></div>` : ''}

      ${refsOn ? `<div class="card pad mt" id="sec-refs"><div class="row"><h3 style="margin:0">Reference pictures</h3>${refsDone ? badge('good', 'all settled') : badge('queued', RS.approved + ' of ' + RS.total + ' approved' + (RS.skipped ? ', ' + RS.skipped + ' skipped' : ''))}<span class="sp"></span>
          ${RS.unscored ? `<button class="small" ${dis} onclick="_plan.refsScore(this)">Score ${RS.unscored} picture(s)</button>` : ''}
          <button class="small" ${dis || !RS.bulk_ready ? 'disabled' : ''} title="Approves the best picture of every open item that scores ${RS.min_score} or more and has no hard problem" onclick="_plan.refsApproveBest(this)">Approve the best (${RS.bulk_ready})</button>
          <button class="small primary" ${dis} onclick="_plan.refsAll(this)">${RS.without_pictures ? 'Make pictures for the ones without' : 'Make more pictures for all'}</button></div>
        <div class="mute small mt-s">Each person in the list above is drawn as a <b>model sheet on a white background in four poses</b> (standing, walking, seated, a face close-up), each object as a sheet of three views, each place as one wide view. This happens before the scenes are designed, and the approved sheet is what the scene pictures are drawn from, so every character looks the same in every scene. Approve one picture per item and every later scene that shows it is drawn <b>from that picture</b>, so it looks the same each time (up to three references per scene). Pictures are made with ${esc(RS.model)}, about ${hd(RS.seconds_per_picture)} each. ${RS.scenes_using_references ? `<b>${RS.scenes_using_references}</b> scene prompt(s) now use a reference.` : 'No scene prompt uses a reference yet.'} Skip an item if a plain description is enough (for example an abstract chart). Each picture gets a <b>score out of 100</b>: half is measured from the pixels (blank, blurry, cut by the frame, cluttered backdrop), half is a strict look by the chat model against the brief, with the problems it found listed under the picture. ★ marks the best of its item. “Approve the best” approves the ★ picture of every open item that scores ${RS.min_score}+ and has no hard problem (text in the picture, cut off, blank); the rest stay for you. The score ranks pictures; it does not replace looking.</div>
        ${RS.assets.map(r => { const good = r.candidates.filter(c => c.status === 'done'); const old = good.filter(c => !c.current).length; return `<div class="seg ${r.approved ? 'approved' : ''}" style="padding:10px 14px"><div class="row"><b>${esc(r.name)}</b><span class="mute small">${esc(r.kind)} · in ${r.scenes} scenes · ${esc(r.size)}</span>${r.approved ? badge('approved', 'approved') : r.skipped ? badge('info', 'skipped') : good.length ? badge('info', 'choose one') : badge('queued', 'no picture yet')}<span class="sp"></span>
          <button class="small" ${dis} onclick="_plan.refsSkip('${r.asset_id}',${!r.skipped})">${r.skipped ? 'Use a reference' : 'Skip'}</button>
          ${r.skipped ? '' : `<button class="small" ${dis} onclick="_plan.refsOne(this,'${r.asset_id}')">${good.length ? 'Draw more' : 'Draw pictures'}</button>`}</div>
          <div class="small mt-s">${esc(r.description || 'No description yet; add one in Continuity so the picture has something to show.')}${r.fixed.length ? ` <span class="mute">Always the same: ${esc(r.fixed.join('; '))}.</span>` : ''}</div>
          ${r.candidates.filter(c => c.status === 'failed').slice(-1).map(c => `<div class="iss error">✗ Last try failed: ${esc(c.error)}</div>`).join('')}
          ${old ? `<div class="iss warn">⚠ ${old} picture(s) were made before this item's description or the style changed and are marked old.</div>` : ''}
          ${r.skipped ? '' : `<div class="row mt-s" style="align-items:flex-start;gap:12px;flex-wrap:wrap">${good.map(c => `<div style="width:340px"><a href="${esc(c.url)}" target="_blank"><img src="${esc(c.url)}" loading="lazy" style="width:340px;border-radius:6px;border:${c.approved ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'};${c.current ? '' : 'opacity:.5'}"></a>
            <div class="row small mt-s"><span class="mute">#${c.attempt}${c.current ? '' : ' · old'}${c.custom ? ' · your prompt' : ''}${c.model ? ' · ' + esc((MODELS[c.model] || {label: c.model}).label) : ''}</span>${c.score ? badge(c.score.hard ? 'error' : c.score.total >= RS.min_score ? 'good' : 'queued', (r.best === c.id ? '★ ' : '') + c.score.total) : ''}<span class="sp"></span><button class="small" ${dis} onclick="_plan.refsApprove('${c.id}',${!c.approved})">${c.approved ? 'Unapprove' : 'Approve'}</button></div>
            ${c.score ? `<div class="small mute mt-s" title="measured ${c.score.measured}${c.score.looked_at != null ? ', looked at ' + c.score.looked_at : ''}">${c.score.flags.length ? c.score.flags.slice(0, 3).map(f => '⚠ ' + esc(f)).join('<br>') : 'No problems found.'}${c.score.note ? `<br>${esc(c.score.note)}` : ''}</div>` : ''}</div>`).join('')}</div>`}
          <details class="mt-s" ${DRAFT['ref:' + r.asset_id] != null ? 'open' : ''}><summary class="small mute">The prompt sent to the model (you can change it)</summary>
            <textarea id="refp-${r.asset_id}" class="small" style="width:100%;min-height:150px;margin-top:6px" oninput="_plan.draft('ref:${r.asset_id}',this.value)">${esc(DRAFT['ref:' + r.asset_id] != null ? DRAFT['ref:' + r.asset_id] : r.prompt)}</textarea>
            ${r.negative_prompt ? `<div class="mute small mt-s">Negative (FLUX only): ${esc(r.negative_prompt)}</div>` : ''}
            <div class="row mt-s"><label class="small">Model <select id="refm-${r.asset_id}">${Object.entries(MODELS).map(([k, v]) => `<option value="${k}" ${k === RS.model ? 'selected' : ''}>${esc(v.label)}${v.default ? ' (default)' : ''}</option>`).join('')}</select></label>
              <button class="small primary" ${dis} onclick="_plan.refsDraw(this,'${r.asset_id}')">Draw with this prompt</button>
              <button class="small" ${dis} onclick="_plan.refsReset('${r.asset_id}')">Reset to the built prompt</button></div>
            <div class="mute small mt-s">Your text replaces the built prompt for the new pictures of this item only; the description above is not changed. Pictures drawn from your text are marked “your prompt”.</div></details></div>`; }).join('')}
        <div class="mute small mt-s">Look at each picture at full size (click it). Approve the one whose look you want to see throughout the video; if none is right, press “Draw more” (new seeds). Approving updates the scene prompts at once; your approved plan stays approved.</div></div>` : ''}

      ${picsOn ? (() => {
        const st = SS.settings, M = SS.models, modeName = m => m === 'edit' ? 'from the reference sheets' : m === 'correct' ? 'corrected' : 'plain';
        const rows = SS.scenes.filter(r => PF === 'all' || (PF === 'open' ? r.status !== 'approved' : PF === 'choice' ? r.status === 'needs_choice' : PF === 'none' ? r.status === 'needs_picture' : r.status === 'approved'));
        const thumb = (c, r, w) => `<div style="width:${w}px"><a href="${esc(c.url)}" target="_blank"><img src="${esc(c.url)}" loading="lazy" style="width:${w}px;border-radius:6px;border:${c.approved ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'};${c.current ? '' : 'opacity:.5'}"></a>
            <div class="row small mt-s"><span class="mute">#${c.attempt} · ${esc(M[c.model] || c.model)} · ${esc(modeName(c.mode))}${c.custom ? ' · your prompt' : ''}${c.current ? '' : ' · old'}</span>${c.score ? badge(c.score.hard ? 'error' : c.score.total >= SS.min_score ? 'good' : 'queued', (r.best === c.id ? '★ ' : '') + c.score.total) : ''}<span class="sp"></span><button class="small" ${dis} onclick="_plan.picsApprove('${c.id}',${!c.approved})">${c.approved ? 'Unapprove' : 'Approve'}</button><button class="small" ${dis} title="Change one thing and keep the rest" onclick="_plan.picsCorrect(this,'${r.id}','${c.id}')">Correct this</button></div>
            ${c.change ? `<div class="small mute mt-s">Correction: ${esc(c.change)}</div>` : ''}
            ${c.score ? `<div class="small mute mt-s" title="measured ${c.score.measured}${c.score.looked_at != null ? ', looked at ' + c.score.looked_at : ''}">${c.score.flags.length ? c.score.flags.slice(0, 3).map(f => '⚠ ' + esc(f)).join('<br>') : 'No problems found.'}${c.score.note ? `<br>${esc(c.score.note)}` : ''}</div>` : ''}</div>`;
        const trialRows = SS.scenes.filter(r => SS.trial.includes(r.id));
        const ways = [['qwen-image-2.1', 'generate'], ['qwen-image-2.1', 'edit'], ['flux2-klein-9b', 'generate'], ['flux2-klein-9b', 'edit']];
        return `<div class="card pad mt" id="sec-pictures"><div class="row"><h3 style="margin:0">Scene pictures</h3>${picsDone ? badge('good', 'all approved') : badge('queued', SS.approved + ' of ' + SS.total + ' approved')}<span class="sp"></span>
          ${SS.unscored ? `<button class="small" ${dis} onclick="_plan.picsScore(this)">Score ${SS.unscored} picture(s)</button>` : ''}
          <button class="small" ${dis || !SS.bulk_ready ? 'disabled' : ''} title="Approves the best picture of every open scene that scores ${SS.min_score} or more and has no hard problem" onclick="_plan.picsApproveBest(this)">Approve the best (${SS.bulk_ready})</button>
          <button class="small primary" ${dis || !st.chosen || !SS.needs_picture ? 'disabled' : ''} title="${st.chosen ? '' : 'Run the trial and choose how to draw first'}" onclick="_plan.picsAll(this)">${SS.needs_picture ? `Draw the ${SS.needs_picture} missing picture(s)` : 'Nothing missing'}</button></div>
        <div class="mute small mt-s">One picture per scene, 16:9, drawn from the scene's image prompt. First run the <b>three-scene trial</b>: an opening, a character scene and a scene with quoted text, drawn on both models, plain and (where the scene has approved reference sheets) <b>from the sheets</b>. Look at them side by side and choose the way that keeps the people the same and the look right; that choice is used for every scene. Each picture is measured and looked at by the chat model (extra people or objects, text that differs from the quoted text, wrong hands, a character that does not match). Nothing is approved without your say, except “Approve the best”, which skips anything with a hard problem. Your approved plan stays approved.</div>
        <div class="row mt-s" style="gap:10px;flex-wrap:wrap;align-items:flex-end">
          <label class="f">Model<select ${dis} onchange="_plan.picsSet({model: this.value || null})"><option value="" ${st.model ? '' : 'selected'}>Each scene's own (plan default)</option>${Object.entries(M).map(([k, v]) => `<option value="${k}" ${st.model === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
          <label class="f">How<select ${dis} onchange="_plan.picsSet({mode: this.value})">${[['generate', 'Plain: the full prompt only'], ['edit', 'From the reference sheets'], ['auto', 'Sheets where a scene has them']].map(([k, v]) => `<option value="${k}" ${st.mode === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
          <label class="f">Pictures per scene<select ${dis} onchange="_plan.picsSet({candidates: +this.value})">${[1, 2, 3, 4].map(n => `<option ${st.candidates === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
          <button class="small" ${dis} onclick="_plan.picsTrial(this)">${SS.trial.length ? 'Run the trial again' : 'Run the three-scene trial'}</button>
          <span class="small mute">${st.chosen ? `<b>Chosen:</b> ${esc(M[st.model] || 'plan model')}, ${esc(modeName(st.mode))}.` : 'No way chosen yet.'} About ${hd(SS.seconds_per_picture['qwen-image-2.1'])} per picture on Qwen, ${hd(SS.seconds_per_picture['flux2-klein-9b'])} on FLUX.</span></div>
        ${trialRows.length ? `<div class="mt"><b>Trial</b> <span class="mute small">${SS.trial_done ? 'finished' : 'waiting for pictures'}</span>
          <div class="row mt-s" style="gap:6px;flex-wrap:wrap">${ways.map(([m, mo]) => `<button class="small ${st.chosen && st.model === m && st.mode === mo ? 'primary' : ''}" ${dis || !SS.trial_done ? 'disabled' : ''} onclick="_plan.picsChoose('${m}','${mo}')">Use ${esc(M[m])}, ${esc(modeName(mo))}, for all scenes</button>`).join('')}</div>
          ${trialRows.map(r => `<div class="seg mt-s" style="padding:10px 14px"><div class="row"><b>${mmss(r.start_s)}</b><span class="small">${esc(r.subject)}</span>${r.references.length ? badge('info', r.references.length + ' reference sheet(s)') : ''}${r.quoted.length ? badge('info', 'text: ' + r.quoted.join(' / ')) : ''}</div>
            <div class="row mt-s" style="align-items:flex-start;gap:12px;flex-wrap:wrap">${r.candidates.filter(c => c.trial && c.status === 'done').map(c => thumb(c, r, 300)).join('') || '<span class="mute small">no trial pictures yet</span>'}</div></div>`).join('')}</div>` : ''}
        <div class="row mt" style="gap:10px"><b>Scenes</b><label class="small">Show <select onchange="_plan.picsFilter(this.value)">${[['open', 'not approved yet'], ['none', 'need a picture'], ['choice', 'need a choice'], ['done', 'approved'], ['all', 'all']].map(([k, v]) => `<option value="${k}" ${PF === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label><span class="small mute">${SS.needs_picture} need a picture · ${SS.needs_choice} need a choice · ${SS.approved} approved</span></div>
        ${rows.map(r => { const shown = r.candidates.filter(c => c.status === 'done'); return `<div class="seg ${r.approved_current ? 'approved' : ''}" style="padding:10px 14px"><div class="row"><b>${mmss(r.start_s)}</b><span class="mute small">${esc(r.visual_type || '')} · ${Math.round(r.duration_s)}s · ${esc(M[r.model] || r.model)} · ${esc(modeName(r.mode))}</span>${r.status === 'approved' ? badge('approved', 'approved') : r.status === 'needs_choice' ? badge('info', 'choose one') : badge('queued', 'no picture yet')}${r.references.length ? badge('info', r.references.length + ' sheet(s)') : ''}${r.chosen_here ? badge('info', 'own model/way') : ''}${r.quoted.length ? badge('info', 'text: ' + r.quoted.join(' / ')) : ''}<span class="sp"></span>
            <button class="small" ${dis} onclick="_plan.picsOne(this,'${r.id}')">${shown.length ? 'Draw again' : 'Draw'}</button><button class="small" ${dis} title="Choose the model, plain or from the reference sheets, and change the prompt" onclick="_plan.redraw(this,'${r.id}')">Redraw…</button></div>
          <div class="small mt-s">${esc(r.subject)}</div>
          ${r.candidates.filter(c => c.status === 'failed').slice(-1).map(c => `<div class="iss error">✗ Last try failed: ${esc(c.error)}</div>`).join('')}
          ${shown.some(c => !c.current) ? `<div class="iss warn">⚠ ${shown.filter(c => !c.current).length} picture(s) were made before this scene or a reference changed and are marked old.</div>` : ''}
          ${shown.length ? `<div class="row mt-s" style="align-items:flex-start;gap:12px;flex-wrap:wrap">${shown.map(c => thumb(c, r, 300)).join('')}</div>` : ''}
          <details class="mt-s"><summary class="small mute">The prompt sent to the model</summary><div class="small">${esc(r.prompt)}</div></details></div>`; }).join('') || '<div class="mute small mt-s">Nothing in this view.</div>'}
        <div class="mute small mt-s">Click a picture to see it at full size. “Draw again” makes one more picture with a new seed and keeps the others. “Correct this” edits the picture: say what to change and what must stay. An approved picture is never replaced by “Draw the missing pictures”.</div></div>`; })() : ''}

      ${gfxOn ? `<div class="card pad mt" id="sec-graphics"><div class="row"><h3 style="margin:0">Graphics</h3>${gfxDone ? badge('good', 'all approved') : badge('queued', GS.approved + ' of ' + GS.total + ' approved')}<span class="sp"></span>
          <button class="small" ${dis} onclick="_plan.gfxBuild(this,true)">Build again</button>
          <button class="small primary" ${dis || !(GS.needs_build || GS.needs_choice) ? 'disabled' : ''} onclick="${GS.needs_build ? '_plan.gfxBuild(this)' : '_plan.gfxApproveAll(this)'}">${GS.needs_build ? `Build the ${GS.needs_build} missing graphic(s)` : GS.needs_choice ? 'Approve all that match their scene' : 'Nothing to do'}</button></div>
        <div class="mute small mt-s">Scenes that show a chart, document, screen, map or diagram are not drawn by the picture model: a card is built by code from the numbers and dates in the story's facts. A number appears only if the facts state it. A line or bar chart needs every point from the facts; with fewer, the scene gets a stat card, a comparison, a timeline or a title card and the reason is shown. Cards use the colours of the chosen style and are 1920x1080. The video step animates them (count up, line draw, grow, reveal).</div>
        ${GS.scenes.map(r => { const c = r.current_item; return `<div class="seg ${r.status === 'approved' ? 'approved' : ''}" style="padding:10px 14px"><div class="row"><b>${mmss(r.start_s)}</b><span class="mute small">${esc(r.visual_type)} · ${Math.round(r.duration_s)}s · ${esc(r.template)} card</span>${r.status === 'approved' ? badge('approved', 'approved') : r.status === 'needs_choice' ? badge('info', 'look and approve') : badge('queued', 'not built')}<span class="sp"></span>
            ${c ? `<button class="small" ${dis} onclick="_plan.gfxApprove('${c.id}',${!c.approved})">${c.approved ? 'Unapprove' : 'Approve'}</button>` : ''}</div>
          <div class="small mt-s">${esc(r.subject)}</div>
          ${r.fallback ? `<div class="iss warn">⚠ ${esc(r.fallback)}.</div>` : ''}${r.dropped.map(x => `<div class="iss warn">⚠ ${esc(x)}.</div>`).join('')}
          ${c ? `<div class="mt-s"><a href="${esc(c.url)}" target="_blank"><img src="${esc(c.url)}" loading="lazy" style="width:420px;border-radius:6px;border:${c.approved ? '3px solid var(--good,#2a9d5c)' : '1px solid var(--line,#ccc)'}"></a><div class="small mute mt-s">Animation in the video: ${esc((c.animation || '').replace(/_/g, ' '))}${c.numbers.length ? ' · numbers shown: ' + esc(c.numbers.join(', ')) : ''}</div></div>` : ''}</div>`; }).join('')}</div>` : ''}

      ${p.blueprint ? `<div class="card pad mt" id="sec-thumbnail"><div class="row"><h3 style="margin:0">Video thumbnail</h3>${TH && TH.done ? badge('good', 'made') : badge('queued', 'not made yet')}<span class="sp"></span><button class="small" ${running ? 'disabled' : ''} onclick="_plan.thumb(this)">${TH && TH.done ? 'Make another' : 'Make the thumbnail'}</button></div>${TH && TH.item ? `<img src="${TH.item.url}" style="width:100%;max-width:640px;border-radius:8px;margin-top:8px"><div class="small mt-s"><b>Words on it:</b> ${esc(TH.item.text)}${TH.item.text_ok === false ? ' <span class="mute">(the words may not be drawn exactly: look at it)</span>' : ''}</div>` : '<div class="small mute mt-s">A movie-poster style picture with a short question on it, made when the other steps are done.</div>'}</div>` : ''}
      ${vidOn ? `<div class="card pad mt" id="sec-video"><div class="row"><h3 style="margin:0">Draft video</h3>${vidDone ? badge('good', 'made, up to date') : VS.ready ? badge('info', 'ready to build') : badge('queued', VS.blockers.length + ' missing')}<span class="sp"></span>
          <button class="small" ${dis || !VS.tools.ffmpeg || (VS.blockers.length && !VOPT.gaps) ? 'disabled' : ''} onclick="_plan.vidBuild(this,'preview')">Make a preview (${hd((VS.profiles.preview || {}).eta_s || 0)})</button>
          <button class="small primary" ${dis || !VS.tools.ffmpeg || (VS.blockers.length && !VOPT.gaps) ? 'disabled' : ''} onclick="_plan.vidBuild(this,'draft')">Make the draft video (${hd((VS.profiles.draft || {}).eta_s || 0)})</button></div>
        <div class="mute small mt-s">Each scene's approved picture (or graphic) is held for exactly the scene's length with a slow zoom or pan, never the same move twice in a row; cuts are at scene boundaries, and a dissolve only where the scene asks for one. The voice is the approved take of each part (else the latest valid). Plan length ${mmss(VS.plan_s)}, voice ${mmss(VS.audio_s)}. Nothing is skipped silently: anything missing is listed here.${VS.tools.ffmpeg ? '' : ' <b>ffmpeg was not found, so no video can be made.</b>'}</div>
        <div class="row mt-s" style="gap:16px;flex-wrap:wrap">
          <label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" ${VOPT.captions ? 'checked' : ''} ${VS.tools.captions ? '' : 'disabled'} onchange="_plan.vidOpt('captions',this.checked)"> Hinglish captions burned in (Nirmala UI)${VS.tools.captions ? '' : ' (this ffmpeg cannot)'}</label>
          <label class="small" style="display:flex;gap:6px;align-items:center"><input type="checkbox" ${VOPT.gaps ? 'checked' : ''} onchange="_plan.vidOpt('gaps',this.checked)"> Build anyway: put a labelled placeholder where a picture or voice is missing</label></div>
        ${VS.blockers.length ? `<div class="iss error mt-s"><b>Missing (${VS.blockers.length}):</b> ${VS.blockers.slice(0, 12).map(b => b.kind === 'picture' ? `${mmss(b.at)} ${esc(b.text)}` : `voice for a part: ${esc(b.text)}`).join(' · ')}${VS.blockers.length > 12 ? ` · +${VS.blockers.length - 12} more` : ''}</div>` : ''}
        ${VS.warnings.length ? `<div class="iss warn mt-s"><b>Used but not approved (${VS.warnings.length}):</b> ${VS.warnings.slice(0, 8).map(b => b.kind === 'picture' ? `${mmss(b.at)} ${esc(b.text)}` : esc(b.text)).join(' · ')}${VS.warnings.length > 8 ? ` · +${VS.warnings.length - 8} more` : ''}</div>` : ''}
        ${VS.changes && (VS.changes.changed.length || VS.changes.stale.length) ? `<div class="needbox mt-s" id="sec-changes"><b>Changes since the last video</b>
          ${VS.changes.stale.length ? `<div class="small mt-s">⚠ ${VS.changes.stale.length} scene(s) still show an approved picture made before a reference or the scene changed (${VS.changes.stale.slice(0, 6).map(c => mmss(c.at)).join(', ')}${VS.changes.stale.length > 6 ? ', …' : ''}). They stay in the video until you draw them again.
            <button class="small" ${dis} onclick="_plan.redrawStale(this)">Redraw these ${VS.changes.stale.length} scene(s)</button></div>` : ''}
          ${VS.changes.changed.length ? `<div class="small mt-s"><b>${VS.changes.changed.length}</b> scene(s) have a different picture from the one in the last video. Only these are drawn into the clips again when you rebuild; every other clip is reused.</div>
            <div class="row mt-s" style="gap:12px;align-items:flex-start;flex-wrap:wrap">${VS.changes.changed.slice(0, 12).map(c => `<div style="width:230px" class="small"><b>${mmss(c.at)}</b> ${c.approved ? '' : badge('queued', 'not approved')}<div class="row" style="gap:4px;flex-wrap:nowrap">${c.old_url ? `<img src="${esc(c.old_url)}" style="width:110px;border-radius:4px;opacity:.7" title="in the last video">` : ''}<img src="${esc(c.new_url)}" style="width:110px;border-radius:4px;border:2px solid var(--good,#2a9d5c)" title="now"></div></div>`).join('')}</div>
            ${VS.changes.changed.length > 12 ? `<div class="mute small mt-s">…and ${VS.changes.changed.length - 12} more.</div>` : ''}` : ''}
          <div class="row mt-s"><button class="small primary" ${dis || !VS.tools.ffmpeg || (VS.blockers.length && !VOPT.gaps) ? 'disabled' : ''} onclick="_plan.vidBuild(this,'draft')">Rebuild the draft video with the updated pictures</button><span class="small mute">The earlier video is kept as an earlier attempt.</span></div></div>` : ''}
        ${VS.length_gap_s > 1 ? `<div class="iss warn mt-s">⚠ The voice and the scenes differ by ${hd(VS.length_gap_s)}: make the voice again or retime.</div>` : ''}
        ${VS.videos.slice().reverse().slice(0, 4).map(v => `<div class="seg mt-s" style="padding:10px 14px"><div class="row"><b>${esc(v.profile)} #${v.attempt}</b><span class="mute small">${mmss(v.duration_s)} · ${esc(v.size)}${v.captions ? ' · captions' : ''} · ${Math.round((v.bytes || 0) / 1048576 * 10) / 10} MB · built in ${hd(v.seconds_taken || 0)}</span>${v.current ? badge('good', 'up to date') : badge('queued', 'older than the pictures or voice')}${v.placeholders.length ? badge('error', v.placeholders.length + ' placeholder(s)') : ''}${v.warnings ? badge('info', v.warnings + ' not approved') : ''}<span class="sp"></span><a class="small" href="${esc(v.url)}" download>Download</a></div>
          <video controls preload="metadata" style="width:100%;max-width:720px;margin-top:8px;border-radius:6px" src="${esc(v.url)}"></video></div>`).join('')}</div>` : ''}

      ${p.scenes.length ? `<div class="mt" id="sec-storyboard"><div class="row"><h3 style="margin:0">Storyboard</h3><span class="mute">${p.scenes.length} scenes · ${mmss(total)}</span></div>
        <div class="strip" title="Each block is a scene; width is how long it is on screen">${ordered.map(s => `<i style="width:${100 * s.duration_s / total}%;background:${vtColor(s.data.visual_type)}" onclick="_plan.jump('${s.id}')" title="${mmss(s.start_s)} ${VT_LABEL[s.data.visual_type]}: ${esc(s.data.subject)}"></i>`).join('')}</div>
        <div class="small mute">${[...new Set(ordered.map(s => s.data.visual_type))].map(t => `<span style="color:${vtColor(t)}">■</span> ${VT_LABEL[t]}`).join(' &nbsp; ')}</div>
        ${ordered.map(s => { const d = s.data, c = d.composition; return `<div class="scn ${s.stale ? 'stale' : s.locked ? 'locked' : s.status === 'approved' ? 'approved' : ''}" id="sc-${s.id}">
          <div class="tm"><b>${mmss(s.start_s)}–${mmss(s.end_s)}</b><div class="mute">${s.duration_s.toFixed(1)}s</div><div class="mute small">${esc(segName(s.segment_id))} · s${s.s_from}${s.s_to > s.s_from ? '–' + s.s_to : ''}</div></div>
          <div><div class="row"><span class="vt" style="background:${vtColor(d.visual_type)}">${VT_LABEL[d.visual_type]}</span>${s.stale ? badge('warn', 'narration changed: check') : ''}${s.status === 'approved' ? badge('approved', 'approved') : ''}${s.locked ? badge('info', 'locked') : ''}${d.feasibility.level === 'needs_asset' ? badge('info', 'needs a real asset') : ''}<span class="sp"></span>
              <button class="small" onclick="_plan.sceneSet('${s.id}',{status:'${s.status === 'approved' ? 'draft' : 'approved'}'})">${s.status === 'approved' ? 'Unapprove' : 'Approve'}</button><button class="small" onclick="_plan.sceneSet('${s.id}',{locked:${!s.locked}})">${s.locked ? 'Unlock' : 'Lock'}</button>
              <select class="small" title="Image model for this scene" onchange="_plan.sceneModel('${s.id}',this.value)"><option value="" ${d.model ? '' : 'selected'}>model: ${esc(modelFor(d).split('-')[0])} (plan)</option>${(PV.providers || []).map(m => `<option value="${m.id}" ${d.model === m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select><button class="small" onclick="_plan.prompts('${s.id}')">Prompts</button><button class="small" ${s.locked ? 'disabled' : ''} onclick="_plan.sceneEdit('${s.id}')">Edit</button><button class="small" ${s.locked || running ? 'disabled' : ''} onclick="_plan.sceneRedraw(this,'${s.id}')">Redraw</button></div>
            <div class="mt-s"><b>${esc(d.subject)}</b> — ${esc(d.action)}</div>
            <div class="mute small mt-s">Why: ${esc(d.narrative.purpose)} · New: ${esc(d.narrative.new_information)}</div>
            <div class="small mt-s">${[d.setting.location, c.position && 'subject ' + c.position, c.distance, c.camera_angle, d.lighting, d.palette].filter(Boolean).map(esc).join(' · ')}</div>
            ${d.feasibility.level === 'needs_asset' ? `<div class="needbox"><b>Needs:</b> ${esc(d.feasibility.needs_asset)}<br><b>Until then:</b> ${esc(d.feasibility.fallback)}</div>` : ''}
            ${d.text_on_screen.length ? `<div class="small mt-s">On-screen text: ${d.text_on_screen.map(t => '“' + esc(t.text) + '”').join(', ')}</div>` : ''}
            ${(s.issues || []).map(i => `<div class="iss ${i.level}">${i.level === 'error' ? '✗' : '⚠'} ${esc(i.kind.replace(/_/g, ' '))}: ${esc(i.text)}</div>`).join('')}</div></div>`; }).join('')}</div>` : ''}

      ${p.scenes.length ? `<div class="card pad mt" id="sec-review"><div class="row"><h3 style="margin:0">Review, approve and export</h3>${approved ? badge('approved', 'approved') : ap.state === 'changed' ? badge('warn', 'changed since approval') : badge('queued', 'not approved')}<span class="sp"></span>
          <button class="small" ${dis} onclick="_plan.review(this)">${sc ? 'Review again' : 'Review and score'}</button></div>
        <div class="mute small mt-s">${esc((sc && sc.disclaimer) || 'Twelve separate scores, each with its reason and what to fix. They are measured checks on this plan, not a forecast of views.')}</div>
        ${!sc ? `<div class="needbox mt-s"><b>Not reviewed yet.</b> Press “Review and score”. It runs every automatic check (no model needed) and tells you exactly what stands between this plan and approval.</div>`
          : `${!reviewed ? `<div class="iss warn mt-s">⚠ You changed the plan after this review. The scores below are from an earlier version: press “Review again”.</div>` : ''}
        ${sc.summary.weakest.length ? `<div class="mt-s"><b>Start here:</b> ${sc.summary.weakest.map(k => { const d = sc.dimensions.find(x => x.key === k); return `<a href="#" onclick="_plan.go('dim-${k}');return false">${esc(d.label)} (${d.score})</a>`; }).join(' · ')}</div>` : `<div class="ok mt-s">✓ No dimension is weak.</div>`}
        <div class="mt-s">${sc.dimensions.map(d => `<div class="dimrow" id="dim-${d.key}"><div class="row"><b style="flex:1">${esc(d.label)}</b><span class="dsc ${d.band}">${d.score}</span></div><div class="dbar"><i class="${d.band}" style="width:${d.score}%"></i></div>
          <div class="small mt-s">${esc(d.reason)}</div>${d.fixes.map(f => `<div class="fix small">→ ${esc(f.text)} ${fixLinks(f)}</div>`).join('')}</div>`).join('')}</div>`}
        <h4>Can this be approved?</h4>
        ${!so ? '<div class="mute small">Run “Review and score” to find out.</div>' : `${so.blockers.length ? `<ul class="tight">${so.blockers.map(b => { const act_ = {blueprint: ['Plan the story', '_plan.blueprint(this)'], narration: ['Write the missing narration', '_plan.narration(this,true)'], storyboard: ['Design the storyboard', '_plan.storyboard(this)'],
          errors: ['Show the errors and their fixes', "_plan.go('sec-top')"], prompts: ['Write the image prompts', '_plan.compile(this)'], prompts_stale: ['Write the image prompts again', '_plan.compile(this)']}[b.code];
          return `<li class="err">✗ ${esc(b.text)} ${act_ ? `<button class="small primary" ${dis} onclick="${act_[1]}">${esc(act_[0])}</button>` : ''} ${fixLinks({where: [], tab: b.tab})}${b.code === 'unapproved' ? '<div class="small mute">Look at them, then use “Approve all” on the narration and storyboard cards: approving is your decision, so it is never done for you.</div>' : ''}</li>`; }).join('')}</ul>` : '<div class="ok">✓ Nothing blocks approval.</div>'}
        ${so.warnings.length ? `<ul class="tight mt-s">${so.warnings.map(w => `<li>⚠ ${esc(w.text)} ${fixLinks({where: [], tab: w.tab})}</li>`).join('')}</ul><div class="mute small">Warnings do not stop approval; they are recorded with it.</div>` : ''}`}
        <div class="row mt-s"><button class="primary" ${dis} ${so && so.blockers.length || !reviewed ? 'disabled' : ''} onclick="_plan.approve(this)">${approved ? 'Approved (approve again)' : 'Approve this plan'}</button>
          ${ap.state !== 'draft' ? `<button class="small" ${dis} onclick="_plan.unapprove(this)">Withdraw approval</button>` : ''}
          <span class="mute small">${ap.state === 'draft' ? 'Approval is tied to this exact version: if you change anything afterwards it shows as “changed since approval”.' : `Approved ${fmtDate(ap.at)}${ap.note ? ' · “' + esc(ap.note) + '”' : ''}${(ap.warnings || []).length ? ' · ' + ap.warnings.length + ' warning(s) accepted' : ''}`}</span></div>
        <h4>Export</h4>
        <div class="mute small">One JSON file that the image, voice and video modules read. <b>public</b> holds everything that may be spoken, shown or sent to a model; <b>evidence</b> is the fact-checking trail and never goes into a prompt. The file is checked against a published schema (<a href="/api/plans/schema" target="_blank">view schema</a>) and is refused if anything in <b>public</b> points back to the source.</div>
        <div class="row mt-s"><button ${dis} ${p.scenes.length ? '' : 'disabled'} onclick="_plan.export(this)">${p.exports.length ? 'Export again (new version)' : 'Export now'}</button>${!approved && p.exports.length === 0 ? '<span class="mute small">You can export before approval; the file will say it is not ready for generation and why.</span>' : ''}</div>
        ${p.exports.length ? `<table class="mt-s small" style="width:100%"><tr><th align="left">Version</th><th align="left">Saved</th><th align="left">Size</th><th align="left">Ready for generation</th><th></th></tr>${p.exports.map((e, i) => `<tr><td>v${e.rev}${i === 0 ? (exported ? ' (current)' : ' (older than your last change)') : ''}</td><td>${fmtDate(e.created_at)}</td><td>${Math.round(e.bytes / 1024)} KB</td><td>${e.ready ? '<span class="ok">yes</span>' : '<span class="mute">no, see file</span>'}</td><td><a href="/api/plans/exports/${esc(p.id)}/${esc(e.file)}" download>Download</a></td></tr><tr><td colspan="5" class="mute small" style="word-break:break-all">${esc(e.path)}</td></tr>`).join('')}</table>` : ''}
        <details class="mt" ontoggle="if(this.open)_plan.loadHistory(this)"><summary><b>Change history</b> <span class="mute small">every approval, regeneration and export</span></summary><div class="hist mt-s small mute">Loading…</div></details></div>` : ''}

      ${MS && p.scenes.length ? `<div class="card pad mt" id="sec-voice"><div class="row"><h3 style="margin:0">Voice</h3>${MS.have === MS.total && MS.total ? badge('good', 'all parts voiced') : badge('queued', MS.have + ' of ' + MS.total + ' parts voiced')}<span class="sp"></span>
          <button class="small" ${dis || !voiceToApprove.length ? 'disabled' : ''} title="Approves every finished take that has no warning" onclick="_plan.voiceApproveAll(this)">Approve all voice (${voiceToApprove.length})</button>
          <button class="small primary" ${dis} ${exportReady ? '' : 'disabled'} onclick="_plan.voiceAll(this)">${MS.have ? 'Make the missing parts' : 'Make the voice for all parts'}</button></div>
        <div class="row mt-s"><label class="small">Voice engine <select ${dis} onchange="_plan.ttsSet(this,this.value,'')">${Object.entries(MS.engines).map(([k, e]) => `<option value="${k}" ${k === MS.engine ? 'selected' : ''}>${esc(e.label)}${e.default ? ' (default)' : ''}</option>`).join('')}</select></label>
          <label class="small">Voice <select ${dis} onchange="_plan.ttsSet(this,'${MS.engine}',this.value)">${Object.entries(MS.engines[MS.engine].voices).map(([v, g]) => `<option value="${v}" ${v === MS.voice ? 'selected' : ''}>${esc(v)} (${g})</option>`).join('')}</select></label>
          <button class="small" ${dis} onclick="_plan.voiceSample(this)">Hear a sample</button>${MS.sample ? `<audio controls preload="none" src="${esc(MS.sample)}" style="height:32px"></audio>` : ''}</div>
        <div class="mute small mt-s">${esc(MS.engines[MS.engine].label)} reads each narration part (${esc(MS.voice)}). Changing the voice keeps older takes but they stop counting until you make the parts again. ${MS.have ? `Measured speaking time so far: <b>${mmss(MS.real_s)}</b> for the parts voiced (the plan estimated ${mmss(MS.estimated_s)} for all). ` : ''}Scenes are re-timed to the real audio automatically.
          ${MS.eta_missing_s ? `Making the rest takes about <b>${hd(MS.eta_missing_s)}</b> (the model server speaks about ${MS.speed_ratio}x slower than real time, and other jobs wait meanwhile).` : ''}</div>
        ${!MS.export.exists ? `<div class="needbox mt-s"><b>Export first.</b> Media is made from the exported file, so the plan and the file cannot disagree. Use “Export” in the side panel.</div>`
          : !MS.export.current ? `<div class="needbox mt-s"><b>The plan changed after export v${MS.export.rev}.</b> Export again before making the voice, so the voice matches what you approved. <button class="small" ${dis} onclick="_plan.export(this)">Export again</button></div>` : ''}
        ${MS.segments.map(r => { const ch = r.attempts.find(a => a.id === r.chosen); const old = r.attempts.filter(a => a.status === 'done' && !a.current).length; return `<div class="seg ${ch && ch.approved ? 'approved' : ''}" style="padding:10px 14px"><div class="row"><b>${esc(r.name)}</b>
          <span class="mute small">${ch ? `${ch.duration_s.toFixed(1)}s real` : 'no voice yet'} · about ${r.expected_s.toFixed(0)}s expected</span>${ch && ch.approved ? badge('approved', 'approved') : ch ? badge('info', 'latest attempt') : badge('queued', 'not made')}<span class="sp"></span>
          ${ch ? `<button class="small" ${dis} onclick="_plan.voiceApprove('${ch.id}',${!ch.approved})">${ch.approved ? 'Unapprove' : 'Approve'}</button>` : ''}
          <button class="small" ${dis} ${exportReady ? '' : 'disabled'} onclick="_plan.voiceOne(this,'${r.segment_id}')">${ch ? 'Make again' : 'Make this part'}</button></div>
          ${ch ? `<audio controls preload="none" src="${esc(ch.url)}" style="width:100%;margin-top:6px"></audio>` : ''}
          ${r.attempts.filter(a => a.status === 'failed').slice(-1).map(a => `<div class="iss error">✗ Last try failed: ${esc(a.error)}</div>`).join('')}
          ${ch ? ch.flags.map(f => `<div class="iss warn">⚠ ${esc(f)}</div>`).join('') : ''}
          ${old ? `<div class="iss warn">⚠ ${old} earlier recording(s) were made from different wording and are ignored.</div>` : ''}
          ${r.attempts.filter(a => a.status === 'done' && a.current && a.id !== r.chosen).length ? `<div class="small mute mt-s">Other recordings: ${r.attempts.filter(a => a.status === 'done' && a.current && a.id !== r.chosen).map(a => `<a href="${esc(a.url)}" target="_blank">attempt ${a.attempt} (${a.duration_s.toFixed(1)}s)</a> <a href="#" onclick="_plan.voiceApprove('${a.id}',true);return false">use this one</a>`).join(' · ')}</div>` : ''}
          <details class="mt-s"><summary class="small mute">What is spoken</summary><div class="small" lang="hi">${esc(r.plain)}</div></details></div>`; }).join('')}
        <div class="mute small mt-s">Listen to each part. If a word is repeated or skipped, press “Make again” (it uses a new seed). Approving a recording locks it in for the video.</div></div>` : ''}

      ${issues.length || v.ok != null || vs ? `<div class="card pad mt" id="sec-results"><h3 style="margin:0 0 6px">Check results</h3>${groups.length ? `<ul class="tight">${groups.map(g => `<li class="${g.i.level === 'warn' ? '' : 'err'}"><b>${g.i.level === 'warn' ? 'Check' : 'Fix'}</b> · ${esc(g.i.part)} · ${esc((g.i.kind || '').replace(/_/g, ' '))}: ${esc(g.i.kind === 'repeat' ? `${g.where.length} scene(s) use the same camera distance and angle as the scene before` : g.i.text)}
          <div class="small mute">${g.where.map(w => { const sc = sceneAt(w); return sc ? `<a href="#" onclick="_plan.jump('${sc.id}');return false">${mmss(sc.start_s)}</a>` : (p.segments.some(x => x.id === w) ? `<a href="#" onclick="_plan.go('seg-${w}');return false">${esc(segName(w))}</a>` : esc(w === 'plan' ? 'whole plan' : w)); }).join(' · ')}</div></li>`).join('')}</ul>` : '<span class="ok">✓ No problems found.</span>'}
        <div class="mute small mt-s">Narration ${mmss(v.duration_s || 0)} · scenes add up to ${vs ? mmss(vs.scene_seconds) : '–'} · copied wording ${Math.round((v.copied_share || 0) * 100)}%</div></div>` : ''}
      </div>${side}</div>
    </div>`;
    document.querySelectorAll('.sent textarea').forEach(t => { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; });
  }

  app.innerHTML = '<div class="pad"><div class="skel"></div><div class="skel"></div></div>';
  try { PV = await api('/plans/providers'); } catch (e) { PV = {providers: []}; }
  try { await load(true); } catch (e) { app.innerHTML = `<div class="errbox">${esc(e.message)}</div><a href="#/">Back</a>`; return; }
  timer = setTimeout(tick, 2500);
};
})();
