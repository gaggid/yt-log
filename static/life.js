'use strict';

const API = '/api/characters';
let CID = '';
let CAL_OFFSET = 0;
let SEL_DATE = '';
let MEM_CAT = 'all';
let _status_timer = null;
let _ctrl_ctx = '';   // accumulated context from inject box + force activity

// ── feeling colour map ────────────────────────────────────────────────────────

const FEELING_COLORS = {
  peaceful:'#38bdf8', content:'#4caf50', grateful:'#4caf50', settled:'#4caf50',
  cosy:'#f59e0b', satisfied:'#4caf50', serene:'#38bdf8', still:'#38bdf8',
  comfortable:'#4caf50', centred:'#38bdf8',
  excited:'#f59e0b', hopeful:'#9c6fe4', proud:'#9c6fe4', inspired:'#9c6fe4',
  playful:'#f59e0b', flirtatious:'#e4836f', amorous:'#e4836f', euphoric:'#f59e0b',
  radiant:'#f59e0b', giddy:'#f59e0b', elated:'#f59e0b',
  ambitious:'#9c6fe4', determined:'#9c6fe4', energised:'#4caf50', focused:'#38bdf8',
  driven:'#9c6fe4', motivated:'#9c6fe4', purposeful:'#9c6fe4', competitive:'#e4836f',
  warm:'#e4836f', affectionate:'#e4836f', tender:'#e4836f', connected:'#4caf50',
  lonely:'#5ba3f5', 'left-out':'#5ba3f5', jealous:'#f59e0b', seen:'#4caf50',
  invisible:'#666', needy:'#5ba3f5',
  anxious:'#ef4444', irritable:'#ef4444', bored:'#666', frustrated:'#f59e0b',
  disappointed:'#5ba3f5', guilty:'#666', embarrassed:'#e4836f', overwhelmed:'#ef4444',
  deflated:'#666', insecure:'#5ba3f5', resentful:'#ef4444', drained:'#666',
  nostalgic:'#5ba3f5', conflicted:'#f59e0b', restless:'#f59e0b', melancholy:'#5ba3f5',
  wistful:'#5ba3f5', curious:'#38bdf8', unsettled:'#f59e0b', numb:'#666',
  pensive:'#5ba3f5', bittersweet:'#5ba3f5', yearning:'#5ba3f5', detached:'#666',
  desirous:'#e4836f', longing:'#5ba3f5', aroused:'#e4836f', craving:'#e4836f',
  infatuated:'#e4836f', possessive:'#e4836f', hungry:'#e4836f', tempted:'#e4836f',
  'tired-but-happy':'#4caf50', 'drained-and-blank':'#666', 'wound-up':'#f59e0b',
  buzzing:'#f59e0b', 'restless-energy':'#f59e0b', heavy:'#666', light:'#4caf50',
};

function feelingColor(f) { return FEELING_COLORS[f] || '#9c6fe4'; }

// ── helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function api(path, opts = {}) {
  const url = API + path;
  const headers = {};
  let body;
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json); }
  const r = await fetch(url, { method: opts.method || 'GET', headers, body });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw e; }
  return r.json();
}

function relTime(ts) {
  const diff = Date.now()/1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.round(diff/60) + 'm ago';
  if (diff < 86400) return new Date(ts*1000).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true});
  const d = Math.round(diff/86400);
  return d < 7 ? d+'d ago' : Math.round(d/7)+'w ago';
}

function absTime(ts) {
  return new Date(ts*1000).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true});
}

function dateStr(dt) {
  return dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0');
}

function todayStr() { return dateStr(new Date()); }

function zoom(url) {
  document.getElementById('zoom-img').src = url;
  document.getElementById('zoom-overlay').classList.add('on');
}

// ── character selector ────────────────────────────────────────────────────────

async function loadChars() {
  const sel = document.getElementById('char-select');
  try {
    const chars = await api('?kind=person&limit=50');
    const people = (chars.items || chars || []).filter(c => c.kind === 'person');
    if (!people.length) { sel.innerHTML = '<option>No characters</option>'; return; }
    sel.innerHTML = people.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    CID = people[0].id;
    sel.value = CID;
  } catch { sel.innerHTML = '<option>Error loading</option>'; }
}

function onCharChange() {
  CID = document.getElementById('char-select').value;
  if (!CID) return;
  SEL_DATE = todayStr();
  renderCal();
  loadFeedDay(SEL_DATE);
  loadNow();
  loadMind();
  startStatusPoll();
  populateFeelingSelect();
  document.getElementById('goals-link').href = `/#${CID}`;
}

document.getElementById('char-select').onchange = onCharChange;

// ── feeling select ────────────────────────────────────────────────────────────

const ALL_FEELINGS_SORTED = [
  'peaceful','content','grateful','settled','cosy','satisfied','serene','still','comfortable','centred',
  'excited','hopeful','proud','inspired','playful','flirtatious','amorous','euphoric','radiant','giddy','elated',
  'ambitious','determined','energised','focused','driven','motivated','purposeful','competitive',
  'warm','affectionate','tender','connected','lonely','left-out','jealous','seen','invisible','needy',
  'anxious','irritable','bored','frustrated','disappointed','guilty','embarrassed','overwhelmed',
  'deflated','insecure','resentful','drained',
  'nostalgic','conflicted','restless','melancholy','wistful','curious','unsettled','numb',
  'pensive','bittersweet','yearning','detached',
  'desirous','longing','aroused','craving','infatuated','possessive','hungry','tempted','charged',
  'tired-but-happy','drained-and-blank','wound-up','buzzing','restless-energy','heavy','light',
];

function populateFeelingSelect() {
  const sel = document.getElementById('ctrl-feeling');
  if (sel.options.length > 1) return;
  sel.innerHTML = ALL_FEELINGS_SORTED.map(f => `<option value="${f}">${f}</option>`).join('');
}

// ── NOW panel ─────────────────────────────────────────────────────────────────

async function loadNow() {
  if (!CID) return;
  try {
    const [status, events, goals] = await Promise.all([
      api(`/${CID}/life/status`),
      api(`/${CID}/life?limit=3`),
      api(`/${CID}/goals`),
    ]);

    const energy = status.energy ?? 80;
    const sleepThr = status.sleep_threshold ?? 20;
    const col = energy > 60 ? '#4caf50' : energy > 30 ? '#f59e0b' : '#ef4444';
    const desc = energy > 70 ? 'Charged' : energy > 50 ? 'Moderate' : energy > 30 ? 'Tired' : energy <= sleepThr ? 'Sleeping' : 'Exhausted';
    const feel = status.feeling || {};
    const fPrimary = feel.primary || '';
    const fInt = feel.intensity || 0;
    const fSec = feel.secondary || '';
    const fColor = feelingColor(fPrimary);

    const lastThink = events.find(e => e.event_type === 'think');
    const out = (lastThink || {}).outputs || {};

    const activeGoals = (goals || []).filter(g => g.status === 'active').slice(0, 4);

    const dot = document.getElementById('live-dot');
    const loopDot = document.getElementById('loop-dot');
    const loopTxt = document.getElementById('loop-state-txt');
    if (status.life_enabled) {
      dot.classList.remove('off');
      loopDot.classList.remove('off');
      loopTxt.innerHTML = `Auto · <span style="color:var(--text2)">${status.interval_m || 60}m</span>`;
    } else {
      dot.classList.add('off');
      loopDot.classList.add('off');
      loopTxt.innerHTML = `<span style="color:var(--mute)">Paused</span>`;
    }

    // sync controls
    const ei = document.getElementById('ctrl-interval');
    if (ei && !ei.matches(':focus')) ei.value = status.interval_m || 60;
    const er = document.getElementById('ctrl-energy');
    if (er && !er.matches(':focus')) { er.value = energy; document.getElementById('ctrl-energy-val').textContent = energy; }

    const nextAt = status.next_run;
    const sinceStr = status.last_run ? relTime(status.last_run) : 'never';
    const nextStr  = nextAt ? relTime(nextAt) : '—';

    document.getElementById('think-status').textContent = status.last_run ? sinceStr : '';

    document.getElementById('now-body').innerHTML = `
      <div style="display:flex;align-items:baseline;gap:8px">
        <span class="energy-num" style="color:${col}">${energy}</span>
        <span style="font-size:11px;color:var(--text2)">/ 100 energy</span>
      </div>
      <div class="energy-track"><div class="energy-fill" style="width:${energy}%;background:${col}"></div></div>
      <div class="energy-desc">${desc}${energy <= sleepThr ? ' · sleeping 😴' : ''}</div>

      ${fPrimary ? `
      <div class="feeling-pill" style="border-color:${fColor}33;margin-top:10px">
        <span class="fdot" style="background:${fColor}"></span>
        <span>${esc(fPrimary)}${fInt ? ` <span style="color:var(--mute);font-size:10px">${fInt}/10</span>` : ''}</span>
      </div>
      ${fSec ? `<div style="font-size:11px;color:var(--text2);margin-top:3px;padding-left:2px">↗ ${esc(fSec)}</div>` : ''}
      ` : ''}

      ${out.space ? `
      <div style="margin-top:10px;border-top:1px solid var(--line);padding-top:9px">
        <div class="now-row"><span class="ico">📍</span><div><b>${esc(out.space)}</b></div></div>
        ${out.outfit ? `<div class="now-row"><span class="ico">👗</span><div>${esc(out.outfit)}</div></div>` : ''}
        ${out.activity ? `<div class="now-row"><span class="ico">↪</span><div>${esc(out.activity)}</div></div>` : ''}
        <div class="now-row"><span class="ico">⏱</span><div>${sinceStr}${nextStr !== '—' ? ` · next ${nextStr}` : ''}</div></div>
      </div>` : ''}

      ${activeGoals.length ? `
      <div style="margin-top:10px;border-top:1px solid var(--line);padding-top:9px">
        <div class="lp-label" style="margin-bottom:6px">Active Goals</div>
        ${activeGoals.map(g => `
          <div class="gmini">
            <div class="gmini-name" title="${esc(g.title)}">${esc(g.title)}</div>
            <div class="gmini-notes">${g.progress_notes?.length || 0} notes</div>
          </div>`).join('')}
      </div>` : ''}
    `;
  } catch(e) {
    document.getElementById('now-body').innerHTML = `<div style="color:var(--mute);font-size:11px">Could not load</div>`;
  }
}

function startStatusPoll() {
  if (_status_timer) clearInterval(_status_timer);
  _status_timer = setInterval(() => { loadNow(); }, 30000);
}

// ── calendar ──────────────────────────────────────────────────────────────────

async function getDaysWithEvents(year, month) {
  try {
    const r = await api(`/${CID}/life?limit=500`);
    const events = r || [];
    const days = new Set();
    events.forEach(e => {
      const d = new Date(e.created_at * 1000);
      if (d.getFullYear() === year && d.getMonth() + 1 === month)
        days.add(d.getDate());
    });
    return days;
  } catch { return new Set(); }
}

async function renderCal() {
  const container = document.getElementById('cal-days');
  const dow = ['Su','Mo','Tu','We','Th','Fr','Sa'];
  const today = new Date();
  today.setHours(0,0,0,0);
  const base = new Date(today);
  base.setDate(base.getDate() + CAL_OFFSET * 7 - 3);

  const year = today.getFullYear(), month = today.getMonth() + 1;
  const eventDays = await getDaysWithEvents(year, month);

  container.innerHTML = Array.from({length:7}, (_,i) => {
    const d = new Date(base); d.setDate(base.getDate() + i);
    const ds = dateStr(d);
    const isToday = ds === dateStr(today);
    const isActive = ds === SEL_DATE;
    const hasEv = eventDays.has(d.getDate()) && d.getMonth()+1 === month && d.getFullYear() === year;
    return `<button class="cal-day${isActive?' active':''}${hasEv?' has-events':''}" data-date="${ds}">
      <div class="dn">${isToday ? 'Today' : dow[d.getDay()]}</div>
      <div class="dd">${d.getDate()}</div>
    </button>`;
  }).join('');

  container.querySelectorAll('.cal-day').forEach(b => {
    b.onclick = () => { SEL_DATE = b.dataset.date; renderCal(); loadFeedDay(SEL_DATE); };
  });
}

document.getElementById('cal-prev').onclick = () => { CAL_OFFSET--; renderCal(); };
document.getElementById('cal-next').onclick = () => { CAL_OFFSET++; renderCal(); };

// ── feed ──────────────────────────────────────────────────────────────────────

async function loadFeedDay(dateStr_) {
  const scroll = document.getElementById('feed-scroll');
  scroll.innerHTML = '<div id="feed-loading">Loading…</div>';
  try {
    const start = new Date(dateStr_); start.setHours(0,0,0,0);
    const end   = new Date(dateStr_); end.setHours(23,59,59,999);
    const events = await api(`/${CID}/life/day?date=${dateStr_}`);
    renderFeed(events || []);
  } catch(e) {
    scroll.innerHTML = `<div id="feed-empty">Could not load — ${esc(e.detail || e.message || '')}</div>`;
  }
}

function renderFeed(events) {
  const scroll = document.getElementById('feed-scroll');
  if (!events.length) {
    scroll.innerHTML = '<div id="feed-empty">No events on this day.</div>';
    return;
  }

  // group by date section (mostly same day, but handle multi-day if needed)
  let html = '';
  let lastDate = '';
  for (const ev of events) {
    const d = new Date(ev.created_at*1000);
    const ds = dateStr(d);
    if (ds !== lastDate) {
      const label = ds === todayStr() ? 'Today' : d.toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long'});
      html += `<div class="feed-date-sep">${label}</div>`;
      lastDate = ds;
    }
    html += buildCard(ev, events);
  }
  scroll.innerHTML = html;

  // wire image zoom
  scroll.querySelectorAll('.fc-img').forEach(img => img.onclick = () => zoom(img.src));
  // wire action buttons
  scroll.querySelectorAll('.fca[data-toggle]').forEach(btn => {
    btn.onclick = () => {
      const target = btn.dataset.toggle;
      const panel = document.getElementById(target);
      if (!panel) return;
      const isOpen = panel.classList.toggle('on');
      btn.classList.toggle('on', isOpen);
    };
  });
  // wire redraw
  scroll.querySelectorAll('[data-redraw]').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = 'Drawing…';
      try {
        await api(`/${CID}/life/${btn.dataset.redraw}/draw`, {method:'POST',json:{}});
        for (let i=0;i<90;i++) {
          await new Promise(r=>setTimeout(r,3000));
          const s = await api(`/${CID}/life/status`).catch(()=>null);
          if (s && (!s.loop_running)) break;
        }
        await loadFeedDay(SEL_DATE);
      } catch(e) { btn.disabled=false; btn.textContent='↺ Redraw'; }
    };
  });
}

function buildCard(ev, allEvents) {
  const out = ev.outputs || {};
  const inp = ev.inputs  || {};

  // ── sleep card ──
  if (ev.event_type === 'sleep') {
    const ctx = inp.stage1_context || inp;
    return `<div class="feed-card feed-sleep">
      <div class="fc-head">
        <span class="fc-time">${absTime(ev.created_at)}</span>
        <span class="fc-tag fc-mood">😴 sleep</span>
      </div>
      <div class="fc-body" style="padding:9px 12px">
        <div style="font-size:11px;color:var(--text2)">Energy ${inp.energy_before ?? '?'} → ${out.energy_after ?? '?'} · +${out.restored ?? 0} restored</div>
      </div>
    </div>`;
  }

  // ── error card ──
  if (ev.event_type === 'error') {
    return `<div class="feed-card feed-error">
      <div class="fc-head">
        <span class="fc-time">${absTime(ev.created_at)}</span>
        <span class="fc-tag" style="background:rgba(239,68,68,.1);color:var(--bad)">error · ${esc((inp.stage || ''))}</span>
      </div>
      <div class="fc-body" style="padding:8px 12px"><div style="font-size:11px;color:var(--text2)">${esc((out.error||'').slice(0,160))}</div></div>
    </div>`;
  }

  if (ev.event_type !== 'think') return '';

  // find paired draw event
  const drawEv = allEvents.find(e => e.event_type === 'draw' && (e.inputs||{}).event_id === ev.id);
  const imgUrl = drawEv ? (drawEv.outputs||{}).url || '' : '';

  const space    = out.space    || '';
  const mood     = out.mood     || '';
  const activity = out.activity || '';
  const thought  = out.thought  || '';
  const gp       = out.goal_progress || '';
  const fuObj    = out.feeling_update || {};
  const fUpd     = fuObj.primary || '';
  const fInt     = fuObj.intensity || 0;
  const memCat   = out.memory_category || 'episodic';
  const eDelta   = out.energy_delta || 0;
  const aspire   = out.aspiration || '';

  const fColor = fUpd ? feelingColor(fUpd) : '';
  const eid = ev.id;
  const pipeId  = `pipe-${eid}`;
  const promptId = `prompt-${eid}`;

  // effects row
  const effects = [];
  if (eDelta) {
    const cls = eDelta > 0 ? 'e-energy-up' : 'e-energy-dn';
    effects.push(`<span class="eff ${cls}">${eDelta > 0 ? '+' : ''}${eDelta} energy</span>`);
  }
  if (fUpd) effects.push(`<span class="eff e-feeling" style="border-color:${fColor}33">${esc(fUpd)}${fInt ? ' '+fInt : ''}/10</span>`);
  if (memCat && memCat !== 'episodic') effects.push(`<span class="eff e-mem">${esc(memCat)}</span>`);
  if (gp) effects.push(`<span class="eff e-goal">🎯 ${esc(gp.slice(0,40))}</span>`);
  if (aspire) effects.push(`<span class="eff e-aspire">✦ ${esc(aspire.slice(0,40))}</span>`);

  // pipeline trace
  const ctx = inp.stage1_context || {};
  const s2out = inp.stage2_output || out;
  const s3out = inp.stage3_output || {};
  const pipeHtml = `
    <div class="pipe-stage">
      <div class="pipe-label">Context in</div>
      <div class="pipe-line">
        ${ctx.world_line ? `<div><b>World:</b> ${esc(ctx.world_line)}</div>` : ''}
        ${ctx.feeling_line ? `<div><b>Feeling:</b> ${esc(ctx.feeling_line)}</div>` : ''}
        ${ctx.day_arc_text ? `<div><b>Day arc:</b> ${esc(ctx.day_arc_text.split('\n')[0])}</div>` : ''}
        ${ctx.goals_text ? `<div><b>Goals:</b> ${esc(ctx.goals_text.slice(0,100))}</div>` : ''}
        ${ctx.memories_text ? `<div style="color:var(--mute)">Memories retrieved: ${(ctx.memories_text.match(/\[/g)||[]).length}</div>` : ''}
        ${ctx.neglect_nudge ? `<div style="color:var(--warn)">Nudge: ${esc(ctx.neglect_nudge)}</div>` : ''}
      </div>
    </div>
    <div class="pipe-stage">
      <div class="pipe-label">First pass</div>
      <div class="pipe-line">
        <div><b>Thought:</b> <i>${esc((s2out.thought||'').slice(0,120))}</i></div>
        <div><b>Activity:</b> ${esc(s2out.activity||'')} · <b>Space:</b> ${esc(s2out.space||'')} · <b>Mood:</b> ${esc(s2out.mood||'')}</div>
        <div><b>Shot:</b> ${esc(s2out.shot_type||'—')} · <b>log_photo:</b> ${s2out.log_photo !== undefined ? String(s2out.log_photo) : '—'}</div>
        ${s2out.wardrobe_want ? `<div style="color:var(--accent2)">Wardrobe want: ${esc(s2out.wardrobe_want)}</div>` : ''}
        ${s2out.new_interest?.name ? `<div style="color:var(--teal)">Interest proposal: ${esc(s2out.new_interest.name)}</div>` : ''}
      </div>
    </div>
    <div class="pipe-stage">
      <div class="pipe-label">Self-review</div>
      <div class="pipe-line">
        ${s3out.note === 'review skipped (error)' ? `<div style="color:var(--mute)">Skipped (error)</div>` :
          s3out.confirmed !== undefined
            ? `<div>${s3out.confirmed ? '✓ Confirmed as-is' : `<span class="pipe-change">Revised ↓</span>`}</div>
               ${!s3out.confirmed && s3out.revised_thought ? `<div><i>${esc(s3out.revised_thought.slice(0,120))}</i></div>` : ''}`
            : '<div style="color:var(--mute)">—</div>'}
      </div>
    </div>
    <div class="pipe-stage">
      <div class="pipe-label">Effects applied</div>
      <div class="pipe-line">
        <div><b>Memory:</b> ${esc(memCat)} · <b>Energy delta:</b> ${eDelta > 0 ? '+' : ''}${eDelta}</div>
        ${fUpd ? `<div><b>Feeling →</b> <span style="color:${fColor}">${esc(fUpd)} ${fInt}/10</span></div>` : ''}
        ${gp ? `<div><b>Goal progress:</b> ${esc(gp)}</div>` : ''}
        ${aspire ? `<div><b>Aspiration:</b> ${esc(aspire)}</div>` : ''}
        ${out.note ? `<div><b>Note saved:</b> ${esc(out.note)}</div>` : ''}
        ${out.wardrobe_want ? `<div><b>Wish saved:</b> ${esc(out.wardrobe_want)}</div>` : ''}
      </div>
    </div>`;

  // prompt inspector
  const promptHtml = `
    <div class="pipe-stage">
      <div class="pipe-label">System prompt</div>
      <div class="prompt-pre">${esc(inp.stage2_system || '(not stored)')}</div>
    </div>
    <div class="pipe-stage" style="margin-top:10px">
      <div class="pipe-label">User prompt</div>
      <div class="prompt-pre">${esc(inp.stage2_user || '(not stored)')}</div>
    </div>`;

  return `<div class="feed-card">
    <div class="fc-head">
      <span class="fc-time">${absTime(ev.created_at)}</span>
      ${space ? `<span class="fc-tag fc-space">${esc(space)}</span>` : ''}
      ${mood ? `<span class="fc-tag fc-mood">${esc(mood)}</span>` : ''}
      ${fUpd ? `<span class="fc-tag fc-feeling" style="background:${fColor}1a;color:${fColor}">${esc(fUpd)}</span>` : ''}
      ${memCat !== 'episodic' ? `<span class="fc-tag fc-memcat">${esc(memCat)}</span>` : ''}
    </div>
    <div class="fc-body">
      ${imgUrl
        ? `<img class="fc-img" src="${esc(imgUrl)}" alt="moment" loading="lazy">`
        : (out.log_photo === false ? '' : `<div class="fc-img-ph">no image</div>`)
      }
      <div class="fc-txt">
        ${thought ? `<div class="fc-thought">"${esc(thought)}"</div>` : ''}
        ${activity ? `<div class="fc-activity">${esc(activity)}</div>` : ''}
        ${gp ? `<div style="font-size:11px;color:var(--accent2);margin-top:2px">🎯 ${esc(gp)}</div>` : ''}
      </div>
    </div>
    ${effects.length ? `<div class="fc-effects">${effects.join('')}</div>` : ''}
    <div class="fc-actions">
      <button class="fca" data-toggle="${pipeId}" title="Pipeline trace">▶ Pipeline</button>
      <button class="fca" data-toggle="${promptId}" title="Raw prompt">▶ Prompt</button>
      <div class="fc-action-sp"></div>
      ${!imgUrl ? `<button class="fca" data-redraw="${eid}">↺ Draw</button>` : `<button class="fca" onclick="zoom('${imgUrl}')">⤢ Zoom</button>`}
    </div>
    <div class="fc-expand" id="${pipeId}">
      <div class="fc-expand-body">${pipeHtml}</div>
    </div>
    <div class="fc-expand" id="${promptId}">
      <div class="fc-expand-body">${promptHtml}</div>
    </div>
  </div>`;
}

// ── MIND panel ────────────────────────────────────────────────────────────────

async function loadMind() {
  if (!CID) return;
  const [mems, goals, aspirations, skills] = await Promise.all([
    api(`/${CID}/memories?limit=80`).catch(()=>[]),
    api(`/${CID}/goals`).catch(()=>[]),
    api(`/${CID}/aspirations`).catch(()=>[]),
    api(`/${CID}/skills`).catch(()=>[]),
  ]);
  renderMemories(mems);
  renderGoals(goals);
  renderAspirations(aspirations);
  renderSkills(skills);
}

function renderMemories(mems) {
  const list = document.getElementById('mem-list');
  const filtered = MEM_CAT === 'all' ? mems : mems.filter(m => m.category === MEM_CAT);
  if (!filtered.length) { list.innerHTML = '<div class="mind-empty">No memories here yet.</div>'; return; }
  list.innerHTML = filtered.map(m => {
    const s = Math.min(1, m.current_strength || (m.base_strength || 1));
    const col = s > 0.7 ? '#9c6fe4' : s > 0.4 ? '#5ba3f5' : '#666';
    const days = Math.round((Date.now()/1000 - m.formed_at) / 86400);
    const age = days < 1 ? 'today' : days < 7 ? days+'d' : Math.round(days/7)+'w';
    const cat = m.category || 'episodic';
    return `<div class="mem-row">
      <div class="mem-str" style="background:${col}"></div>
      <div class="mem-body">
        <div class="mem-content">${esc(m.content)}</div>
        <div class="mem-meta">
          <span class="mem-cat">${esc(cat)}</span>
          <span>${age} ago</span>
          <span>${Math.round(s*100)}%</span>
        </div>
      </div>
    </div>`;
  }).join('');
}

function renderGoals(goals) {
  const list = document.getElementById('goal-list');
  const active = (goals||[]).filter(g => g.status === 'active');
  if (!active.length) { list.innerHTML = '<div class="mind-empty">No active goals.</div>'; return; }
  list.innerHTML = active.map(g => {
    const last = g.progress_notes?.length ? g.progress_notes[g.progress_notes.length-1] : '';
    return `<div class="goal-row">
      <div class="goal-title">${esc(g.title)}</div>
      <div class="goal-sub">${esc(g.category)} · ${g.progress_notes?.length||0} notes</div>
      ${last ? `<div class="goal-last">${esc(last.slice(0,80))}</div>` : ''}
    </div>`;
  }).join('');
}

function renderSkills(skills) {
  const list = document.getElementById('skill-list');
  if (!skills||!skills.length) { list.innerHTML = '<div class="mind-empty">No skills added yet — add them in the character window.</div>'; return; }
  const THRESHOLDS = [0,5,20,60,150,300];
  list.innerHTML = skills.map(sk => {
    const lnum = parseInt((sk.level||'L1').replace('L',''))||1;
    const prev = THRESHOLDS[lnum-1]||0, next = THRESHOLDS[Math.min(lnum,5)];
    const h = sk.hours||0;
    const pct = next>prev ? Math.min(100,Math.round((h-prev)/(next-prev)*100)) : 100;
    return `<div class="skill-row">
      <span class="skill-name">${esc(sk.name)}</span>
      <div class="skill-track"><div class="skill-fill" style="width:${pct}%"></div></div>
      <span class="skill-meta">${esc(sk.level||'L1')} · ${h.toFixed(0)}h</span>
    </div>`;
  }).join('');
}

function renderAspirations(asps) {
  const list = document.getElementById('asp-list');
  if (!asps||!asps.length) { list.innerHTML = '<div class="mind-empty">None yet — surface from thinking.</div>'; return; }
  list.innerHTML = asps.map(a => `
    <div class="asp-row" data-aspid="${esc(a.id)}">
      <div class="asp-text">${esc(a.text)}</div>
      <div class="asp-meta">
        ${a.needs_goal_prompt ? `<span class="asp-badge">→ goal?</span>` : ''}
        <span class="asp-count">×${a.surfaced_count}</span>
        <button class="asp-del" data-asp="${esc(a.id)}" title="Dismiss">×</button>
      </div>
    </div>`).join('');
  list.querySelectorAll('[data-asp]').forEach(btn => {
    btn.onclick = async () => {
      await api(`/${CID}/aspirations/${btn.dataset.asp}`, {method:'DELETE'}).catch(()=>{});
      btn.closest('.asp-row').remove();
    };
  });
}

// ── mind tabs ─────────────────────────────────────────────────────────────────

document.querySelectorAll('.mind-tab').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.mind-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.mind-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('pane-' + tab.dataset.pane)?.classList.add('active');
  };
});

document.querySelectorAll('.mfbtn').forEach(btn => {
  btn.onclick = async () => {
    document.querySelectorAll('.mfbtn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    MEM_CAT = btn.dataset.mcat;
    const mems = await api(`/${CID}/memories?limit=80`).catch(()=>[]);
    renderMemories(mems);
  };
});

// ── think button ──────────────────────────────────────────────────────────────

function buildCtxOverride() {
  const inject = (document.getElementById('ctrl-context')?.value || '').trim();
  const force  = (document.getElementById('ctrl-force')?.value || '').trim();
  let ctx = inject;
  if (force) ctx = (ctx ? ctx + '. ' : '') + 'You are about to: ' + force;
  return ctx;
}

async function doThink() {
  const btn = document.getElementById('think-btn');
  const btn2 = document.getElementById('ctrl-think-now');
  [btn, btn2].forEach(b => { if(b){b.disabled=true;b.textContent='Thinking…';} });
  document.getElementById('think-status').textContent = 'thinking…';
  try {
    const ctxOverride = buildCtxOverride();
    const ev = await api(`/${CID}/think`, {method:'POST', json:{context_override: ctxOverride}});
    // clear inject fields after use
    if (document.getElementById('ctrl-context')) document.getElementById('ctrl-context').value = '';
    if (document.getElementById('ctrl-force'))   document.getElementById('ctrl-force').value = '';
    if (ev.ok) {
      await loadNow();
      await renderCal();
      await loadFeedDay(SEL_DATE);
      await loadMind();
    }
  } catch(e) {
    document.getElementById('think-status').textContent = e.detail || 'error';
    setTimeout(() => { document.getElementById('think-status').textContent = ''; }, 4000);
  } finally {
    [btn, btn2].forEach(b => { if(b){b.disabled=false;b.textContent=b===btn?'Think now':'Think now';} });
  }
}

document.getElementById('think-btn').onclick = doThink;

// ── controls wiring ───────────────────────────────────────────────────────────

// energy range display
document.getElementById('ctrl-energy').oninput = e => {
  document.getElementById('ctrl-energy-val').textContent = e.target.value;
};

// apply energy override
document.getElementById('ctrl-energy-apply').onclick = async () => {
  const val = parseInt(document.getElementById('ctrl-energy').value);
  await api(`/${CID}/override`, {method:'PATCH', json:{energy: val}}).catch(e => alert(e.detail||e.message));
  await loadNow();
};

// apply feeling override
document.getElementById('ctrl-feeling-apply').onclick = async () => {
  const primary = document.getElementById('ctrl-feeling').value;
  const intensity = parseInt(document.getElementById('ctrl-feeling-int').value)||6;
  if (!primary) return;
  await api(`/${CID}/override`, {method:'PATCH', json:{feeling:{primary,intensity}}}).catch(e => alert(e.detail||e.message));
  await loadNow();
};

// loop controls
document.getElementById('ctrl-pause').onclick = async () => {
  await api(`/${CID}/profile`, {method:'PATCH', json:{life_enabled:false}}).catch(()=>{});
  loadNow();
};
document.getElementById('ctrl-resume').onclick = async () => {
  await api(`/${CID}/profile`, {method:'PATCH', json:{life_enabled:true}}).catch(()=>{});
  loadNow();
};
document.getElementById('ctrl-think-now').onclick = doThink;
document.getElementById('ctrl-interval-set').onclick = async () => {
  const val = parseInt(document.getElementById('ctrl-interval').value)||60;
  await api(`/${CID}/profile`, {method:'PATCH', json:{life_interval_m:val}}).catch(()=>{});
  loadNow();
};

// ── boot ──────────────────────────────────────────────────────────────────────

(async () => {
  await loadChars();
  if (CID) {
    SEL_DATE = todayStr();
    document.getElementById('think-btn').disabled = false;
    renderCal();
    loadFeedDay(SEL_DATE);
    loadNow();
    loadMind();
    startStatusPoll();
    populateFeelingSelect();
    document.getElementById('goals-link').href = `/#${CID}`;
  }
})();
