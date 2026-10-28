'use strict';
// ── STATE ──────────────────────────────────────────────────────────────────
const S = {
  projectId: null,
  planId: null,
  plan: null,       // last GET /api/plans/{id} response
  media: null,      // last GET /api/media/{id} response
  phase: 'plan',    // 'plan' | 'media'
  selected: null,   // { kind: 'step'|'scene'|'segment', id } — drives right inspector
  tl: { zoom: 12 },
  projects: [],
  plans: [],
  _pollTimer: null,
  _palCmds: [],
  _palIdx: 0,
};

// ── CONSTANTS ──────────────────────────────────────────────────────────────
// Order and API mapping for all 15 pipeline stages.
// planApi: the POST endpoint to run this step.
// doneKey: key in plan.steps_done (may differ from stage key).
const STAGES = [
  { key:'blueprint',  label:'Plan the story',            api: id=>`/api/plans/${id}/blueprint`,       doneKey:'blueprint'      },
  { key:'narration',  label:'Write the narration',       api: id=>`/api/plans/${id}/narration`,        doneKey:'narration'      },
  { key:'characters', label:'Create characters',         api: id=>`/api/plans/${id}/registry`,         doneKey:'registry'       },
  { key:'storyboard', label:'Design the storyboard',     api: id=>`/api/plans/${id}/storyboard`,       doneKey:'storyboard'     },
  { key:'voicetags',  label:'Direct narrator voice',     api: id=>`/api/plans/${id}/voicetags`,        doneKey:'voicetags'      },
  { key:'references', label:'Make reference pictures',   api: id=>`/api/media/${id}/references`,       doneKey:'references'     },
  { key:'prompts',    label:'Write image prompts',       api: id=>`/api/plans/${id}/compile-prompts`,  doneKey:'compile_prompts'},
  { key:'repeats',    label:'Fix camera repeats',        api: id=>`/api/plans/${id}/fix-repeats`,      doneKey:'fix_repeats'    },
  { key:'approve',    label:'Approve the plan',          api: id=>`/api/plans/${id}/approve`,          doneKey:'approved'       },
  { key:'export',     label:'Export',                    api: id=>`/api/plans/${id}/export`,           doneKey:'export'         },
  { key:'voice',      label:'Make the voice',            api: id=>`/api/media/${id}/voice`,            doneKey:'voice'          },
  { key:'pictures',   label:'Draw scene pictures',       api: id=>`/api/media/${id}/scenes`,           doneKey:'scene_pictures' },
  { key:'graphics',   label:'Build graphics',            api: id=>`/api/media/${id}/graphics`,         doneKey:'graphics'       },
  { key:'video',      label:'Make the draft video',      api: id=>`/api/media/${id}/video`,            doneKey:'video'          },
  { key:'thumbnail',  label:'Make the thumbnail',        api: id=>`/api/media/${id}/thumbnail`,        doneKey:'thumbnail'      },
];

const VT = ['reconstruction','establishing','character','metaphor','object_process','montage','map_timeline',
            'data_chart','document_archival','screen_interface','diagram','comparison','text_led','minimalist','atmospheric','transition'];
const vtColor = t => `hsl(${(VT.indexOf(t) * 47 + 200) % 360} 55% 50%)`;
const EMO_COLORS = { neutral:'#7b87a0', happy:'#f5a623', sad:'#60b4f0', anger:'#f06060', fear:'#b060f0', clear:'#34c77b', excited:'#f5c842', calm:'#60f0c0' };
const emoColor = tag => EMO_COLORS[tag] || EMO_COLORS.neutral;

// ── DOM HELPERS ────────────────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDur = s => { s = Math.max(0, Math.round(s||0)); return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; };
const fmtDate = t => t ? new Date(t*1000).toLocaleString([],{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
const isEditing = () => ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);

function toast(msg, kind='ok') {
  const el = document.createElement('div');
  el.className = 'nxt-toast' + (kind === 'err' ? ' err' : '');
  el.textContent = msg;
  $('nxt-toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── API ────────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const r = await fetch(path, {
    method: opts.method || 'GET',
    headers: opts.json ? { 'Content-Type': 'application/json' } : {},
    body: opts.json ? JSON.stringify(opts.json) : undefined,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

// ── BOOT ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initShortcuts();
  initTimelineResize();
  initTimelineZoom();
  buildPaletteCommands();
  window.addEventListener('hashchange', route);
  await loadProjects();
  route();
});

// ── ROUTER ─────────────────────────────────────────────────────────────────
function route() {
  const h = location.hash;
  const m = h.match(/^#\/plan\/(.+)$/);
  if (m) { selectPlanById(m[1]); return; }
  const p = h.match(/^#\/project\/(.+)$/);
  if (p) { selectProjectById(p[1]); return; }
}

// ── PROJECTS ───────────────────────────────────────────────────────────────
async function loadProjects() {
  try {
    S.projects = await api('/api/projects');
  } catch(e) {
    $('rail-projects').innerHTML = `<div style="padding:10px;font-size:12px;color:var(--nbad)">${esc(e.message)}</div>`;
    return;
  }
  renderRailProjects();
}

function renderRailProjects() {
  const el = $('rail-projects');
  if (!S.projects.length) {
    el.innerHTML = '<div style="padding:10px;font-size:12px;color:var(--nmute)">No projects yet</div>';
    return;
  }
  el.innerHTML = S.projects.map(p => `
    <button class="rail-proj${S.projectId === p.id ? ' on':''}" onclick="selectProjectById('${esc(p.id)}')">
      <span class="rail-proj-title">${esc(p.title || p.id)}</span>
      <span class="rail-proj-sub">${esc(p.status || '')}</span>
    </button>`).join('');
}

async function selectProjectById(pid) {
  if (S.projectId === pid) return;
  S.projectId = pid;
  S.planId = null; S.plan = null; S.media = null; S.selected = null;
  stopPolling();
  renderRailProjects();
  // breadcrumb
  const proj = S.projects.find(p => p.id === pid);
  const bc = $('nxt-breadcrumb-proj');
  bc.textContent = proj?.title || pid;
  bc.style.display = '';
  $('nxt-breadcrumb-plan').style.display = 'none';
  $('rail-phases').hidden = false;
  if (location.hash !== '#/project/' + pid) history.replaceState(null,'','#/project/'+pid);
  await showPlanSelector(pid);
}

// ── PLAN SELECTOR ─────────────────────────────────────────────────────────
async function showPlanSelector(pid) {
  setCenter('<div class="nxt-skel"></div><div class="nxt-skel"></div>');
  setInspector('<div class="ins-empty">Select a plan to inspect</div>');
  let plans;
  try {
    plans = await api(`/api/plans?project_id=${pid}`);
  } catch(e) {
    setCenter(`<div class="nxt-empty"><div class="nxt-empty-icon">✕</div>${esc(e.message)}</div>`);
    return;
  }
  S.plans = plans;
  if (!plans.length) {
    setCenter(`<div class="nxt-empty"><div class="nxt-empty-icon">◈</div>No video plans yet.<br><span style="font-size:12px;color:var(--nmute)">Create one from the classic UI first.</span></div>`);
    return;
  }
  const cards = plans.map(p => `
    <div class="plan-card${S.planId===p.id?' on':''}" onclick="selectPlanById('${esc(p.id)}')">
      <div class="plan-card-title">${esc(p.settings?.video_title || p.id)}</div>
      <div class="plan-card-meta">
        ${esc(p.status || 'draft')} · ${p.beats_written||0}/${p.beats||'?'} parts · ${p.scenes||0} scenes · ${fmtDate(p.updated_at)}
      </div>
    </div>`).join('');
  setCenter(`<div class="nxt-h2">Video Plans</div>${cards}`);
}

async function selectPlanById(planId) {
  if (S.planId === planId && S.plan) return;
  S.planId = planId;
  S.plan = null; S.media = null; S.selected = null;
  stopPolling();
  if (location.hash !== '#/plan/' + planId) history.replaceState(null,'','#/plan/'+planId);
  // Try to infer project if not set
  if (!S.projectId) {
    const allPlans = await api('/api/plans').catch(()=>[]);
    const found = allPlans.find(p => p.id === planId);
    if (found?.project_id) {
      S.projectId = found.project_id;
      if (!S.projects.length) S.projects = await api('/api/projects').catch(()=>[]);
      renderRailProjects();
      $('rail-phases').hidden = false;
    }
  }
  await refreshPlanData();
  startPolling();
}

// ── DATA REFRESH ───────────────────────────────────────────────────────────
async function refreshPlanData() {
  if (!S.planId) return;
  try {
    const [plan, media] = await Promise.all([
      api(`/api/plans/${S.planId}`),
      api(`/api/media/${S.planId}`),
    ]);
    S.plan = plan;
    S.media = media;
    const planTitle = plan.settings?.video_title || plan.id;
    const bc = $('nxt-breadcrumb-plan');
    bc.textContent = planTitle;
    bc.style.display = '';
    // Update project breadcrumb
    if (plan.project_id && !S.projectId) {
      S.projectId = plan.project_id;
      if (!S.projects.length) S.projects = await api('/api/projects').catch(()=>[]);
      renderRailProjects();
    }
    renderPhaseButtons();
    renderCenter();
    buildTimeline();
    renderInspector();
    renderJobBadge(plan.job);
  } catch(e) {
    toast(e.message, 'err');
  }
}

// ── JOB POLLING ────────────────────────────────────────────────────────────
function startPolling() {
  stopPolling();
  S._pollTimer = setInterval(async () => {
    if (!S.planId) return;
    try {
      const job = await api(`/api/plans/${S.planId}/job`);
      const wasRunning = S.plan?.job?.state === 'running';
      if (S.plan) S.plan.job = job;
      renderJobBadge(job);
      if (job.state === 'running' || wasRunning) {
        await refreshPlanData();
      }
    } catch {}
  }, 4000);
}

function stopPolling() {
  if (S._pollTimer) { clearInterval(S._pollTimer); S._pollTimer = null; }
}

function renderJobBadge(job) {
  const badge = $('nxt-job-badge');
  const cancel = $('nxt-cancel-btn');
  if (!job || job.state === 'idle') {
    badge.hidden = true; cancel.hidden = true; return;
  }
  badge.hidden = false;
  if (job.state === 'running') {
    const pct = job.total ? Math.round(job.done/job.total*100) : 0;
    badge.textContent = `● ${job.kind || 'running'}${job.total ? ` ${job.done}/${job.total}` : ''}`;
    badge.style.background = 'var(--ninfo-bg)'; badge.style.color = 'var(--ninfo)';
    cancel.hidden = false;
  } else if (job.state === 'failed') {
    badge.textContent = `✕ ${job.error || 'failed'}`;
    badge.style.background = 'var(--nbad-bg)'; badge.style.color = 'var(--nbad)';
    cancel.hidden = true;
  } else {
    badge.textContent = `✓ ${job.kind || 'done'}`;
    badge.style.background = 'var(--nok-bg)'; badge.style.color = 'var(--nok)';
    cancel.hidden = true;
    setTimeout(() => { badge.hidden = true; }, 4000);
  }
}

// ── CENTER RENDERING ───────────────────────────────────────────────────────
function setCenter(html) { $('nxt-center-content').innerHTML = html; }
function setInspector(html) { $('nxt-inspector-content').innerHTML = html; }

function renderPhaseButtons() {
  $('phase-plan-btn').className = 'rail-btn' + (S.phase === 'plan' ? ' on' : '');
  $('phase-media-btn').className = 'rail-btn' + (S.phase === 'media' ? ' on' : '');
}

function renderCenter() {
  if (!S.plan) return;
  if (S.phase === 'plan') renderPlanOverview();
  else renderMediaDashboard();
}

function setPhase(phase) {
  S.phase = phase;
  S.selected = null;
  renderPhaseButtons();
  renderCenter();
  renderInspector();
}

// ── PLAN OVERVIEW ──────────────────────────────────────────────────────────
function renderPlanOverview() {
  if (!S.plan || !S.media) return;
  const p = S.plan;
  const autoStages = (S.media.auto?.stages || []);
  const doneMap = {};
  autoStages.forEach(s => { doneMap[s.key] = s.done; });
  const nextKey = S.media.auto?.next;
  const jobRunning = p.job?.state === 'running';
  const jobKind = (p.job?.kind || '').toLowerCase();

  const stepsHtml = STAGES.map(st => {
    const done = doneMap[st.key];
    let state = 'pending';
    if (done) state = 'done';
    else if (jobRunning && jobKind.includes(st.key.replace('_',''))) state = 'running';
    else if (st.key === nextKey) state = 'next';
    const dotChar = state === 'done' ? '✓' : state === 'running' ? '' : state === 'next' ? '▶' : '';
    const lastRun = p.steps_done?.[st.doneKey];
    return `<div class="step-row${S.selected?.id===st.key?' on':''}" onclick="selectStep('${esc(st.key)}')">
      <div class="step-dot ${state}">${state==='running'?'<span class="nxt-spin"></span>':dotChar}</div>
      <span class="step-label">${esc(st.label)}</span>
      <span class="step-time">${lastRun ? fmtDate(lastRun) : ''}</span>
    </div>`;
  }).join('');

  const blockerCount = (p.blockers||[]).length;
  const approvalState = p.approval?.state || 'pending';
  const remaining = S.media.auto?.remaining ?? '?';

  setCenter(`
    <div class="nxt-h2">${esc(p.settings?.video_title || p.id)}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center">
      <span class="ins-badge ${approvalState==='approved'?'done':blockerCount?'blocked':'pending'}">${approvalState}</span>
      ${p.style?.label ? `<span class="ins-badge pending">${esc(p.style.label)}</span>` : ''}
      ${p.story_type_label ? `<span class="ins-badge pending">${esc(p.story_type_label)}</span>` : ''}
      <span style="font-size:12px;color:var(--nmute)">${remaining} step${remaining===1?'':'s'} remaining</span>
    </div>
    <div class="plan-actions">
      <button class="nxt-btn primary" onclick="doAutoRun()" ${jobRunning?'disabled':''}>
        ${jobRunning?'<span class="nxt-spin"></span> Running…':'▶ Auto-run'}
      </button>
      ${jobRunning?`<button class="nxt-btn bad" onclick="doCancel()">✕ Cancel</button>`:''}
    </div>
    <div class="nxt-h3">Pipeline</div>
    <div class="step-pipeline">${stepsHtml}</div>
  `);
}

// ── MEDIA DASHBOARD ────────────────────────────────────────────────────────
function renderMediaDashboard() {
  if (!S.plan || !S.media) return;
  const m = S.media;
  const jobRunning = S.plan.job?.state === 'running';

  const cards = [
    { key:'voice',    label:'Voice',    icon:'♪', st: m.voice,    done:`${m.voice?.approved||0}/${m.voice?.total||0}`, action:'voice'    },
    { key:'refs',     label:'References',icon:'◈',st: m.refs,     done:`${m.refs?.done||0}/${m.refs?.total||0}`,       action:'references'},
    { key:'scenes',   label:'Scenes',   icon:'▶', st: m.scenes,   done:`${m.scenes?.done||0}/${m.scenes?.total||0}`,   action:'pictures' },
    { key:'graphics', label:'Graphics', icon:'◇', st: m.graphics, done:`${m.graphics?.done||0}/${m.graphics?.total||0}`, action:'graphics'},
    { key:'video',    label:'Video',    icon:'◼', st: m.video,    done: m.video?.done?'ready':'not ready',             action:'video'    },
    { key:'thumbnail',label:'Thumbnail',icon:'★', st: m.thumbnail,done: m.thumbnail?.done?'ready':'not ready',         action:'thumbnail'},
  ].map(c => {
    const stage = STAGES.find(s => s.key === c.action);
    return `<div class="media-card" onclick="selectStep('${esc(c.action)}')">
      <div class="media-card-label">${c.icon} ${esc(c.label)}</div>
      <div class="media-card-count">${esc(c.done)}</div>
      <div class="media-card-sub">${c.st?.done||c.st?.approved ? 'done ✓' : 'in progress'}</div>
      ${stage ? `<button class="media-card-btn" ${jobRunning?'disabled':''} onclick="event.stopPropagation();runStep('${esc(c.action)}')">Run ▶</button>` : ''}
    </div>`;
  }).join('');

  const sceneGridHtml = renderSceneGridHtml();

  setCenter(`
    <div class="nxt-h2">Media Production</div>
    <div class="plan-actions">
      <button class="nxt-btn primary" onclick="doAutoRun()" ${jobRunning?'disabled':''}>
        ${jobRunning?'<span class="nxt-spin"></span> Running…':'▶ Auto-run'}
      </button>
    </div>
    <div class="media-grid">${cards}</div>
    <div class="nxt-h3">Scenes (${(S.plan.scenes||[]).length})</div>
    <div class="scene-grid">${sceneGridHtml}</div>
  `);
}

function renderSceneGridHtml() {
  if (!S.plan?.scenes?.length) return '<div style="color:var(--nmute);font-size:13px">No scenes yet — run the storyboard step first.</div>';
  const sceneMediaMap = {};
  (S.media?.scenes?.scenes || []).forEach(sm => { sceneMediaMap[sm.id] = sm; });
  return S.plan.scenes.map(sc => {
    const sm = sceneMediaMap[sc.id];
    const approvedId = sm?.approved_current;
    const cand = sm?.candidates?.find(c => c.id === approvedId) || sm?.candidates?.find(c => c.status === 'done' && c.current);
    const imgSrc = cand?.file ? `/api/media/file/${S.planId}/${cand.file}` : null;
    const vt = sc.data?.visual_type || 'scene';
    const color = vtColor(sc.data?.visual_type);
    const thumb = imgSrc
      ? `<img src="${esc(imgSrc)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'">`
      : '';
    const ph = `<div class="scene-ph" style="background:${color}20;color:${color};${imgSrc?'display:none':''}">▶</div>`;
    return `<div class="scene-thumb${S.selected?.id===sc.id?' on':''}" onclick="selectScene('${esc(sc.id)}')" title="${esc(sc.data?.location||'')}">
      ${thumb}${ph}
      <div class="scene-thumb-overlay">${fmtDur(sc.start_s)} · ${esc(vt)}</div>
    </div>`;
  }).join('');
}

// ── SELECT ACTIONS ─────────────────────────────────────────────────────────
function selectStep(key) {
  S.selected = { kind: 'step', id: key };
  renderCenter(); // re-render to show active step highlight
  renderInspector();
}

function selectScene(sceneId) {
  S.selected = { kind: 'scene', id: sceneId };
  renderInspector();
  scrollTimelineTo('video', sceneId);
  // re-render scene grid to show selected state
  if (S.phase === 'media') renderMediaDashboard();
}

function selectSegment(segId) {
  S.selected = { kind: 'segment', id: segId };
  renderInspector();
  scrollTimelineTo('audio', segId);
}

// ── RIGHT INSPECTOR ────────────────────────────────────────────────────────
function renderInspector() {
  if (!S.selected) { setInspector('<div class="ins-empty">Select a step, scene<br>or segment to inspect</div>'); return; }
  const { kind, id } = S.selected;
  if (kind === 'step') renderStepPanel(id);
  else if (kind === 'scene') renderScenePanel(id);
  else if (kind === 'segment') renderSegmentPanel(id);
}

function renderStepPanel(key) {
  if (!S.plan || !S.media) return;
  const stage = STAGES.find(s => s.key === key);
  if (!stage) return;
  const autoStages = S.media.auto?.stages || [];
  const stageInfo = autoStages.find(s => s.key === key);
  const done = stageInfo?.done;
  const nextKey = S.media.auto?.next;
  const jobRunning = S.plan.job?.state === 'running';
  const lastRun = S.plan.steps_done?.[stage.doneKey];

  let state = 'pending';
  if (done) state = 'done';
  else if (key === nextKey) state = 'next';

  // Find any blockers (plan.blockers has blocker objects; we show all when approve step selected)
  const blockers = (S.plan.blockers || []);
  const blockerHtml = (key === 'approve' && blockers.length)
    ? blockers.map(b => `<div class="ins-blocker">⚠ ${esc(b.label || b.message || b.key)}</div>`).join('')
    : '';

  setInspector(`
    <div class="ins-section">
      <div class="ins-label">Step</div>
      <div class="ins-title">${esc(stage.label)}</div>
      <div class="ins-meta">
        <span class="ins-badge ${state}">${state}</span>
        ${lastRun ? `<span>Last: ${fmtDate(lastRun)}</span>` : ''}
      </div>
    </div>
    ${blockerHtml}
    <div class="ins-section">
      <div class="ins-actions">
        <button class="ins-btn primary" onclick="runStep('${esc(key)}')" ${jobRunning?'disabled':''}>
          ${jobRunning?'<span class="nxt-spin"></span>':'▶'} Run step
        </button>
        ${done ? `<button class="ins-btn" onclick="runStep('${esc(key)}')" ${jobRunning?'disabled':''}>↺ Re-run</button>` : ''}
      </div>
    </div>
    ${S.plan.job?.state==='running' ? renderJobProgress() : ''}
  `);
}

function renderJobProgress() {
  const job = S.plan?.job;
  if (!job || job.state !== 'running') return '';
  const pct = job.total ? Math.round(job.done / job.total * 100) : 0;
  const msgs = (job.messages || []).slice(-5);
  return `
    <div class="ins-section">
      <div class="ins-label">Running: ${esc(job.kind||'')}</div>
      <div class="ins-prog"><i style="width:${pct}%"></i></div>
      <div style="font-size:11px;color:var(--nmute);margin-top:2px">${job.done||0} / ${job.total||'?'}</div>
      ${msgs.length ? `<div class="ins-log">${msgs.map(m=>esc(m)).join('<br>')}</div>` : ''}
    </div>`;
}

function renderScenePanel(sceneId) {
  if (!S.plan) return;
  const sc = S.plan.scenes?.find(s => s.id === sceneId);
  if (!sc) { setInspector('<div class="ins-empty">Scene not found</div>'); return; }
  const sm = (S.media?.scenes?.scenes || []).find(s => s.id === sceneId);
  const approvedId = sm?.approved_current;
  const cand = sm?.candidates?.find(c => c.id === approvedId) || sm?.candidates?.find(c => c.status === 'done' && c.current);
  const imgSrc = cand?.file ? `/api/media/file/${S.planId}/${cand.file}` : null;
  const jobRunning = S.plan.job?.state === 'running';
  const vt = sc.data?.visual_type || '';
  const color = vtColor(vt);

  setInspector(`
    <div class="ins-section">
      ${imgSrc
        ? `<img class="ins-img" src="${esc(imgSrc)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'">`
        : ''}
      <div class="ins-img-ph" style="background:${color}20;color:${color};${imgSrc?'display:none':''}">▶</div>
      <div class="ins-title">${esc(sc.data?.location || 'Scene')}</div>
      <div class="ins-meta">
        <span class="ins-badge pending" style="background:${color}22;color:${color}">${esc(vt)}</span>
        <span>${fmtDur(sc.start_s)} – ${fmtDur((sc.start_s||0)+(sc.duration_s||0))}</span>
        ${sm?.approved_current ? '<span class="ins-badge done">approved ✓</span>' : ''}
      </div>
      <div class="ins-desc">${esc(sc.data?.description || '')}</div>
    </div>
    <div class="ins-section">
      <div class="ins-actions">
        ${approvedId
          ? `<button class="ins-btn bad" onclick="unapproveScene('${esc(sceneId)}')" ${jobRunning?'disabled':''}>Unapprove</button>`
          : sm?.candidates?.some(c=>c.status==='done')
            ? `<button class="ins-btn ok" onclick="approveSceneBest('${esc(sceneId)}')" ${jobRunning?'disabled':''}>✓ Approve best</button>`
            : ''}
        <button class="ins-btn" onclick="redrawScene('${esc(sceneId)}')" ${jobRunning?'disabled':''}>↺ Redraw</button>
      </div>
    </div>
    ${sc.data?.prompts?.qwen?.prompt ? `
    <div class="ins-section">
      <div class="ins-label">Prompt</div>
      <div class="ins-text" style="max-height:100px;overflow:auto;font-size:11px">${esc(sc.data.prompts.qwen.prompt)}</div>
    </div>` : ''}
    ${S.plan.job?.state==='running' ? renderJobProgress() : ''}
  `);
}

function renderSegmentPanel(segId) {
  if (!S.plan) return;
  const seg = S.plan.segments?.find(s => s.id === segId);
  if (!seg) { setInspector('<div class="ins-empty">Segment not found</div>'); return; }
  const voiceTakes = (S.media?.voice?.takes || []).filter(t => t.segment_id === segId);
  const jobRunning = S.plan.job?.state === 'running';
  const firstTag = seg.sentences?.[0]?.tag || 'neutral';

  const takesHtml = voiceTakes.length
    ? voiceTakes.map(t => `
      <div class="ins-take">
        <span style="font-size:10px;color:var(--nmute)">#${t.attempt||1}</span>
        <audio controls src="/api/media/file/${S.planId}/${esc(t.file)}" preload="none"></audio>
        ${t.approved ? '<span class="ins-badge done">✓</span>' : ''}
      </div>`).join('')
    : '<div style="font-size:12px;color:var(--nmute)">No voice takes yet</div>';

  setInspector(`
    <div class="ins-section">
      <div class="ins-label">Segment · ${fmtDur(seg.start_s)} – ${fmtDur((seg.start_s||0)+(seg.duration_s||0))}</div>
      <div class="ins-meta">
        <span class="ins-badge pending" style="background:${emoColor(firstTag)}22;color:${emoColor(firstTag)}">${esc(firstTag)}</span>
        <span>${(seg.sentences||[]).length} sentences</span>
        <span class="ins-badge ${seg.status==='approved'?'done':seg.status==='edited'?'next':'pending'}">${esc(seg.status||'draft')}</span>
      </div>
      <div class="ins-text" style="max-height:120px;overflow:auto">${esc(seg.sentences?.map(s=>s.text).join(' ') || seg.text || '')}</div>
    </div>
    <div class="ins-section">
      <div class="ins-label">Voice Takes</div>
      ${takesHtml}
      <div class="ins-actions" style="margin-top:10px">
        <button class="ins-btn primary" onclick="makeVoiceSegment('${esc(segId)}')" ${jobRunning?'disabled':''}>♪ Make voice</button>
      </div>
    </div>
    ${S.plan.job?.state==='running' ? renderJobProgress() : ''}
  `);
}

// ── STEP ACTIONS ───────────────────────────────────────────────────────────
async function runStep(key) {
  if (!S.planId) return;
  const stage = STAGES.find(s => s.key === key);
  if (!stage) return;
  try {
    await api(stage.api(S.planId), { method: 'POST' });
    toast(`Started: ${stage.label}`);
    await refreshPlanData();
    startPolling();
  } catch(e) {
    toast(e.message, 'err');
  }
}

async function doAutoRun() {
  if (!S.planId) return;
  try {
    await api(`/api/media/${S.planId}/auto`, { method: 'POST' });
    toast('Auto-run started');
    await refreshPlanData();
    startPolling();
  } catch(e) {
    toast(e.message, 'err');
  }
}

async function doCancel() {
  if (!S.planId) return;
  try {
    await api(`/api/plans/${S.planId}/cancel`, { method: 'POST' });
    toast('Job cancelled');
    await refreshPlanData();
  } catch(e) {
    toast(e.message, 'err');
  }
}

async function approveSceneBest(sceneId) {
  if (!S.planId) return;
  const sc = S.plan?.scenes?.find(s => s.id === sceneId);
  if (!sc) return;
  try {
    await api(`/api/media/${S.planId}/scenes/approve-best`, { method: 'POST', json: { min_score: 0 } });
    toast('Best scene approved');
    await refreshPlanData();
  } catch(e) {
    toast(e.message, 'err');
  }
}

async function unapproveScene(sceneId) {
  toast('Use the classic UI to unapprove individual scenes');
}

async function redrawScene(sceneId) {
  if (!S.planId) return;
  // Use the current model/mode settings of the plan
  const sceneMedia = (S.media?.scenes?.scenes || []).find(s => s.id === sceneId);
  const model = S.media?.scenes?.model || 'qwen-image-2.1';
  try {
    await api(`/api/media/${S.planId}/scenes/${sceneId}/redraw`, { method: 'POST', json: { model, mode: 'generate', candidates: 1 } });
    toast('Redraw started');
    await refreshPlanData();
    startPolling();
  } catch(e) {
    toast(e.message, 'err');
  }
}

async function makeVoiceSegment(segId) {
  if (!S.planId) return;
  try {
    await api(`/api/media/${S.planId}/voice`, { method: 'POST', json: { segment_ids: [segId], only_missing: false } });
    toast('Voice generation started');
    await refreshPlanData();
    startPolling();
  } catch(e) {
    toast(e.message, 'err');
  }
}

// ── TIMELINE ───────────────────────────────────────────────────────────────
function buildTimeline() {
  if (!S.plan) { clearTimeline(); return; }
  const scenes   = S.plan.scenes   || [];
  const segments = S.plan.segments || [];
  const gfxItems = (S.media?.graphics?.items || []).filter(g => g.approved);

  renderTimelineTrack('tl-video',    scenes,   s => ({
    id: s.id, start: s.start_s || 0, dur: s.duration_s || 2,
    label: s.data?.location || s.data?.visual_type || '',
    color: vtColor(s.data?.visual_type),
  }));
  renderTimelineTrack('tl-audio',    segments, s => ({
    id: s.id, start: s.start_s || 0, dur: s.duration_s || 2,
    label: s.sentences?.[0]?.text?.slice(0,40) || '',
    color: emoColor(s.sentences?.[0]?.tag),
  }));
  renderTimelineTrack('tl-graphics', gfxItems, g => ({
    id: g.id, start: g.start_s || 0, dur: g.duration_s || 3,
    label: g.kind || 'gfx',
    color: '#4f80ff',
  }));
  renderTimelineRuler(scenes, segments);
}

function renderTimelineTrack(trackId, items, mapper) {
  const container = $(trackId);
  if (!container) return;
  container.innerHTML = '';
  items.forEach(item => {
    const d = mapper(item);
    const el = document.createElement('div');
    el.className = 'tl-block' + (S.selected?.id === d.id ? ' on' : '');
    el.style.cssText = `left:${timeToPx(d.start)}px;width:${Math.max(timeToPx(d.dur)-2, 4)}px;background:${d.color}`;
    el.title = d.label;
    el.dataset.id = d.id;
    el.dataset.track = trackId;
    el.textContent = d.label.slice(0, 20);
    el.onclick = () => {
      if (trackId === 'tl-audio') selectSegment(d.id);
      else selectScene(d.id);
    };
    container.appendChild(el);
  });
}

function renderTimelineRuler(scenes, segments) {
  const ruler = $('tl-ruler');
  if (!ruler) return;
  ruler.innerHTML = '';
  const all = [...(scenes||[]).map(s=>s.start_s||0), ...(segments||[]).map(s=>s.start_s||0)];
  const totalS = all.length ? Math.max(...all) + 60 : 300;
  const step = S.tl.zoom > 20 ? 15 : S.tl.zoom > 8 ? 30 : 60;
  for (let t = 0; t <= totalS; t += step) {
    const tick = document.createElement('div');
    tick.className = 'tl-ruler-tick';
    tick.style.left = timeToPx(t) + 'px';
    tick.textContent = fmtDur(t);
    ruler.appendChild(tick);
  }
}

function clearTimeline() {
  ['tl-video','tl-audio','tl-graphics'].forEach(id => { const el=$(id); if(el) el.innerHTML=''; });
  const ruler = $('tl-ruler'); if(ruler) ruler.innerHTML='';
}

const timeToPx = s => s * S.tl.zoom;

function scrollTimelineTo(track, id) {
  const trackEl = $('tl-' + track);
  if (!trackEl) return;
  const block = trackEl.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!block) return;
  const left = parseInt(block.style.left);
  const row = trackEl.closest('.tl-row');
  if (row) {
    const tracks = $('tl-tracks');
    if (tracks) {
      // scroll the containing row's parent scroll container
      const scrollEl = trackEl.parentElement;
      if (scrollEl?.scrollTo) scrollEl.scrollTo({ left: Math.max(0, left - 80), behavior: 'smooth' });
    }
  }
  // highlight the block
  trackEl.querySelectorAll('.tl-block').forEach(b => b.classList.remove('on'));
  block.classList.add('on');
}

function initTimelineZoom() {
  $('tl-zoom-in').onclick = () => { S.tl.zoom = Math.min(S.tl.zoom * 1.5, 120); buildTimeline(); };
  $('tl-zoom-out').onclick = () => { S.tl.zoom = Math.max(S.tl.zoom / 1.5, 3); buildTimeline(); };
}

function initTimelineResize() {
  const handle = $('tl-resize');
  if (!handle) return;
  let startY = 0, startH = 0;
  handle.addEventListener('mousedown', e => {
    startY = e.clientY;
    startH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--tl-h')) || 180;
    const onMove = ev => {
      const delta = startY - ev.clientY;
      const newH = Math.max(80, Math.min(400, startH + delta));
      document.documentElement.style.setProperty('--tl-h', newH + 'px');
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

// ── COMMAND PALETTE ────────────────────────────────────────────────────────
function buildPaletteCommands() {
  S._palCmds = [
    { label:'Auto-run',        group:'Plan',    action:()=>doAutoRun() },
    { label:'Cancel job',      group:'Plan',    action:()=>doCancel()  },
    ...STAGES.map(st => ({
      label: `Run: ${st.label}`, group:'Steps', action:()=>runStep(st.key),
    })),
    { label:'Phase: Plan',     group:'View',    action:()=>setPhase('plan')  },
    { label:'Phase: Media',    group:'View',    action:()=>setPhase('media') },
    { label:'Zoom timeline in',group:'Timeline',action:()=>{ S.tl.zoom=Math.min(S.tl.zoom*1.5,120); buildTimeline(); } },
    { label:'Zoom timeline out',group:'Timeline',action:()=>{ S.tl.zoom=Math.max(S.tl.zoom/1.5,3); buildTimeline(); } },
    { label:'Open classic UI', group:'App',     action:()=>window.open('/','_blank') },
  ];
}

function openPalette() {
  $('nxt-palette').hidden = false;
  $('pal-input').value = '';
  $('pal-input').focus();
  S._palIdx = 0;
  filterPalette('');
}

function closePalette() {
  $('nxt-palette').hidden = true;
}

function filterPalette(q) {
  const lower = q.toLowerCase();
  const matched = lower
    ? S._palCmds.filter(c => c.label.toLowerCase().includes(lower))
    : S._palCmds;

  const grouped = {};
  matched.forEach(c => { (grouped[c.group] = grouped[c.group]||[]).push(c); });

  let html = '';
  let i = 0;
  Object.entries(grouped).forEach(([group, cmds]) => {
    html += `<li class="pal-group">${esc(group)}</li>`;
    cmds.forEach(c => {
      const idx = i++;
      html += `<li class="pal-item${idx===S._palIdx?' on':''}" data-idx="${idx}" onclick="runPaletteCmd(${idx})">
        <span class="pal-item-label">${esc(c.label)}</span>
      </li>`;
    });
  });
  $('pal-list').innerHTML = html || '<li style="padding:12px 16px;color:var(--nmute);font-size:13px">No commands match</li>';
  S._palAllFiltered = matched;
}

function runPaletteCmd(idx) {
  const cmd = S._palAllFiltered?.[idx] || S._palCmds[idx];
  closePalette();
  if (cmd) cmd.action();
}

$('pal-input').addEventListener('input', e => { S._palIdx = 0; filterPalette(e.target.value); });
$('pal-input').addEventListener('keydown', e => {
  const items = $('pal-list').querySelectorAll('.pal-item');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    S._palIdx = Math.min(S._palIdx + 1, items.length - 1);
    items.forEach((el,i) => el.classList.toggle('on', i === S._palIdx));
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    S._palIdx = Math.max(S._palIdx - 1, 0);
    items.forEach((el,i) => el.classList.toggle('on', i === S._palIdx));
  } else if (e.key === 'Enter') {
    const active = $('pal-list').querySelector('.pal-item.on');
    if (active) { runPaletteCmd(parseInt(active.dataset.idx)); }
  } else if (e.key === 'Escape') {
    closePalette();
  }
});

// ── KEYBOARD SHORTCUTS ─────────────────────────────────────────────────────
function initShortcuts() {
  document.addEventListener('keydown', e => {
    if (isEditing()) return;
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); openPalette(); return; }
    if ($('nxt-palette') && !$('nxt-palette').hidden) return; // palette handles its own keys
    switch(e.key) {
      case '[': {
        if (!S.plan?.scenes?.length) break;
        const scenes = S.plan.scenes;
        const cur = scenes.findIndex(s => s.id === S.selected?.id);
        const prev = scenes[Math.max(0, cur - 1)];
        if (prev) selectScene(prev.id);
        break;
      }
      case ']': {
        if (!S.plan?.scenes?.length) break;
        const scenes = S.plan.scenes;
        const cur = scenes.findIndex(s => s.id === S.selected?.id);
        const next = scenes[Math.min(scenes.length - 1, cur + 1)];
        if (next) selectScene(next.id);
        break;
      }
      case 'a': case 'A': {
        if (S.selected?.kind === 'scene') approveSceneBest(S.selected.id);
        break;
      }
      case 'r': case 'R': {
        if (S.selected?.kind === 'scene') redrawScene(S.selected.id);
        break;
      }
      case '+': case '=': {
        S.tl.zoom = Math.min(S.tl.zoom * 1.5, 120); buildTimeline();
        break;
      }
      case '-': {
        S.tl.zoom = Math.max(S.tl.zoom / 1.5, 3); buildTimeline();
        break;
      }
      case 'Escape': {
        S.selected = null; renderInspector(); renderCenter();
        break;
      }
    }
  });
}

// ── RESPONSIVE ─────────────────────────────────────────────────────────────
function initResponsive() {
  const mq1200 = window.matchMedia('(max-width:1200px)');
  const mq900  = window.matchMedia('(max-width:900px)');
  const handleResize = () => {
    // At < 1200px, inspector hidden via CSS.
    // At < 900px, rail collapses via CSS.
    // Re-render timeline ruler on resize so ticks don't overflow
    buildTimeline();
  };
  mq1200.addEventListener('change', handleResize);
  mq900.addEventListener('change', handleResize);
}
