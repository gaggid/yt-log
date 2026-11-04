/* Virtual Life — standalone page */
'use strict';

const API = '/api/characters';
let CID = '';           // active character id
let CAL_OFFSET = 0;     // weeks offset from today (0 = this week)
let SEL_DATE = '';      // YYYY-MM-DD currently selected
let MEM_CAT = 'all';    // active memory tab
let _status_timer = null;

// ── helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function api(path, opts = {}) {
  const url = API + path;
  const headers = {};
  let body;
  if (opts.json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json); }
  const r = await fetch(url, { method: opts.method || 'GET', headers, body });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw e; }
  return r.json();
}

function relTime(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.round(diff / 60) + 'm ago';
  if (diff < 86400) {
    const dt = new Date(ts * 1000);
    return dt.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
  }
  const d = Math.round(diff / 86400);
  return d < 7 ? d + 'd ago' : Math.round(d / 7) + 'w ago';
}

function absTime(ts) {
  const dt = new Date(ts * 1000);
  return dt.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

function dateStr(dt) {
  // dt is a Date object; returns YYYY-MM-DD in local time
  return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
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
    const chars = await api('');
    sel.innerHTML = chars.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    // prefer one with life_enabled
    const live = chars.find(c => (c.profile || {}).life_enabled);
    CID = (live || chars[0] || {}).id || '';
    sel.value = CID;
    if (CID) onCharChange();
  } catch (e) {
    sel.innerHTML = '<option>Error loading characters</option>';
  }
}

function onCharChange() {
  CID = document.getElementById('char-select').value;
  SEL_DATE = todayStr();
  CAL_OFFSET = 0;
  renderCal();
  loadFeedDay(SEL_DATE);
  loadNow();
  loadMind();
  startStatusPoll();
}

// ── calendar strip ────────────────────────────────────────────────────────────

function renderCal() {
  const container = document.getElementById('cal-days');
  const today = new Date();
  // show 7 days centred on today + offset
  const days = [];
  for (let i = -3 + CAL_OFFSET * 7; i <= 3 + CAL_OFFSET * 7; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    days.push(d);
  }
  const dow = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  container.innerHTML = days.map(d => {
    const ds = dateStr(d);
    const isToday = ds === todayStr();
    const isActive = ds === SEL_DATE;
    return `<button class="cal-day${isActive ? ' active' : ''}" data-date="${ds}">
      <div class="cal-dn">${isToday ? 'Today' : dow[d.getDay()]}</div>
      <div class="cal-dd">${d.getDate()}</div>
    </button>`;
  }).join('');
  container.querySelectorAll('.cal-day').forEach(b => {
    b.onclick = () => {
      SEL_DATE = b.getAttribute('data-date');
      renderCal();
      loadFeedDay(SEL_DATE);
    };
  });
}

document.getElementById('cal-prev').onclick = () => { CAL_OFFSET--; renderCal(); };
document.getElementById('cal-next').onclick = () => { CAL_OFFSET++; renderCal(); };

// ── feed ──────────────────────────────────────────────────────────────────────

function buildFeedCard(ev, allEvents) {
  const out = ev.outputs || {};
  const inp = ev.inputs || {};

  if (ev.event_type === 'sleep') {
    const e_before = inp.energy_before ?? '?';
    const e_after = out.energy_after ?? '?';
    const reason = inp.reason || 'sleep';
    return `<div class="feed-card feed-sleep">
      <div class="feed-card-header">
        <span class="feed-time">${absTime(ev.created_at)}</span>
        <span class="space-tag">&#128564; ${reason}</span>
      </div>
      <div class="feed-activity">Energy ${e_before} → ${e_after} (+${out.restored ?? 0})</div>
    </div>`;
  }

  if (ev.event_type === 'error') {
    return `<div class="feed-card feed-error">
      <div class="feed-card-header">
        <span class="feed-time">${absTime(ev.created_at)}</span>
        <span class="mood-tag" style="color:var(--bad)">error</span>
      </div>
      <div class="feed-activity">${esc((out.error || '').slice(0, 100))}</div>
    </div>`;
  }

  if (ev.event_type !== 'think') return '';

  const drawEv = allEvents.find(e => e.event_type === 'draw' && (e.inputs || {}).event_id === ev.id);
  const imgUrl = drawEv ? (drawEv.outputs || {}).url || '' : '';
  const mood = out.mood || '';
  // feeling_update holds the feeling the brain produced this cycle
  const fuObj = out.feeling_update || {};
  const feeling = fuObj.primary || '';
  const feelingInt = fuObj.intensity || 0;
  const space = out.space || '';
  const thought = out.thought || '';
  const activity = out.activity || '';
  const gp = out.goal_progress || '';
  const want = out.wardrobe_want || '';

  return `<div class="feed-card">
    <div class="feed-card-header">
      <span class="feed-time">${absTime(ev.created_at)}</span>
      ${space ? `<span class="space-tag">${esc(space)}</span>` : ''}
      ${mood ? `<span class="mood-tag">${esc(mood)}</span>` : ''}
      ${feeling ? `<span class="feeling-tag">feeling ${esc(feeling)}${feelingInt ? ' ' + feelingInt + '/10' : ''}</span>` : ''}
    </div>
    ${activity ? `<div class="feed-activity">${esc(activity)}</div>` : ''}
    ${thought ? `<div class="feed-thought">"${esc(thought)}"</div>` : ''}
    ${imgUrl ? `<img class="feed-image" src="${esc(imgUrl)}" loading="lazy" onclick="zoom('${esc(imgUrl)}')" onerror="this.style.display='none'">` : ''}
    ${gp ? `<div class="feed-gp">&#8599; ${esc(gp)}</div>` : ''}
    ${want ? `<div class="feed-want">&#9825; wants: ${esc(want)}</div>` : ''}
    <details class="feed-debug">
      <summary>debug</summary>
      <pre>${esc(JSON.stringify({thought: out.thought, shot_type: out.shot_type, log_photo: out.log_photo, energy_delta: out.energy_delta}, null, 2))}</pre>
    </details>
  </div>`;
}

async function loadFeedDay(dateStr) {
  if (!CID) return;
  const scroll = document.getElementById('feed-scroll');
  scroll.innerHTML = '<div id="feed-loading">Loading…</div>';
  try {
    const events = await api(`/${CID}/life/day?date=${dateStr}`);
    if (!events.length) {
      scroll.innerHTML = '<div id="feed-empty">No activity on this day.</div>';
      return;
    }
    const isToday = dateStr === todayStr();
    const label = isToday ? 'Today' : new Date(dateStr + 'T12:00:00').toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
    const cards = events.slice().reverse()  // show oldest first within the day
      .map(ev => buildFeedCard(ev, events)).filter(Boolean).join('');
    scroll.innerHTML = `<div class="feed-date-sep">${esc(label)}</div>${cards}`;
  } catch (e) {
    scroll.innerHTML = `<div id="feed-empty">Could not load feed: ${esc(String(e.detail || e))}</div>`;
  }
}

// ── NOW panel ─────────────────────────────────────────────────────────────────

async function loadNow() {
  if (!CID) return;
  const panel = document.getElementById('now-panel');
  try {
    const [status, events, goals] = await Promise.all([
      api(`/${CID}/life/status`),
      api(`/${CID}/life?limit=5`),
      api(`/${CID}/goals`),
    ]);
    const lastThink = events.find(e => e.event_type === 'think');
    const out = lastThink ? lastThink.outputs || {} : {};
    const energy = status.energy ?? 80;
    const sleepThr = status.sleep_threshold ?? 20;
    const energyColor = energy > 60 ? 'var(--ok)' : energy > 30 ? 'var(--warn)' : 'var(--bad)';
    const feelingObj = status.feeling || {};
    const feeling = feelingObj.primary || '';
    const feelingIntensity = feelingObj.intensity || 0;

    const goalsMini = (goals || []).filter(g => g.status === 'active').slice(0, 3).map(g =>
      `<div class="goal-mini"><b>${esc(g.title)}</b><span class="mute small" style="font-size:10px"> ${g.progress_notes?.length || 0} notes</span></div>`
    ).join('') || '<div style="font-size:11px;color:var(--mute)">No active goals</div>';

    panel.innerHTML = `
      <div>
        <h3>Energy</h3>
        <div class="energy-bar-wrap mt-s">
          <div class="energy-bar-fill" style="width:${energy}%;background:${energyColor}"></div>
        </div>
        <div style="font-size:11px;color:var(--mute);margin-top:3px">${energy}/100 ${energy <= sleepThr ? '&#128564; sleeping' : ''}</div>
      </div>
      ${feeling ? `<div>
        <h3>Feeling</h3>
        <div class="feeling-badge mt-s">
          <div class="feeling-dot"></div>
          ${esc(feeling)}${feelingIntensity ? ` <span style="color:var(--mute);font-size:10px">${feelingIntensity}/10</span>` : ''}
        </div>
      </div>` : ''}
      ${out.space ? `<div>
        <h3>Right now</h3>
        <div class="space-pill mt-s">${esc(out.space)}</div>
        ${out.outfit ? `<div class="outfit-line mt-s">${esc(out.outfit)}</div>` : ''}
        ${out.activity ? `<div style="font-size:11px;color:var(--mute);margin-top:4px">${esc(out.activity)}</div>` : ''}
      </div>` : ''}
      <div>
        <h3>Goals</h3>
        ${goalsMini}
      </div>
      ${status.last_run ? `<div style="font-size:10px;color:var(--mute)">${relTime(status.last_run)}</div>` : ''}
    `;
  } catch (e) {
    panel.innerHTML = `<div id="now-loading" style="color:var(--bad)">Could not load status</div>`;
  }
}

function startStatusPoll() {
  if (_status_timer) clearInterval(_status_timer);
  _status_timer = setInterval(() => {
    loadNow();
    // also refresh today's feed if we're viewing today and new events may have come in
    if (SEL_DATE === todayStr()) loadFeedDay(SEL_DATE);
  }, 60000);
}

// ── MIND panel ────────────────────────────────────────────────────────────────

async function loadMind() {
  if (!CID) return;
  const [mems, goals] = await Promise.all([
    api(`/${CID}/memories?limit=60`).catch(() => []),
    api(`/${CID}/goals`).catch(() => []),
  ]);
  renderMemories(mems);
  renderGoals(goals);
  updateGoalsLink();
}

function renderMemories(mems) {
  const list = document.getElementById('mem-list');
  const filtered = MEM_CAT === 'all' ? mems : mems.filter(m => m.category === MEM_CAT);
  if (!filtered.length) {
    list.innerHTML = '<div style="color:var(--mute);font-size:11px">No memories yet.</div>';
    return;
  }
  list.innerHTML = filtered.slice(0, 30).map(m => {
    const s = m.current_strength ?? m.strength ?? 0;
    const pct = Math.round(s * 100);
    const faded = s < 0.2;
    return `<div class="mem-row">
      <div class="mem-bar"><div class="mem-bar-fill" style="width:${pct}%"></div></div>
      <div class="mem-content" style="${faded ? 'opacity:.4' : ''}">${esc((m.content || '').slice(0, 90))}</div>
    </div>`;
  }).join('');
}

function renderGoals(goals) {
  const list = document.getElementById('goal-list');
  const active = (goals || []).filter(g => g.status === 'active');
  if (!active.length) {
    list.innerHTML = '<div style="color:var(--mute);font-size:11px">No active goals.</div>';
    return;
  }
  list.innerHTML = active.map(g => `
    <div class="goal-row">
      <div class="goal-title">${esc(g.title)}</div>
      <div class="goal-notes">${g.progress_notes?.length || 0} progress notes · ${esc(g.category)}</div>
      ${g.progress_notes?.length ? `<div style="font-size:10px;color:var(--mute);margin-top:2px">${esc((g.progress_notes[g.progress_notes.length - 1] || '').slice(0, 60))}</div>` : ''}
    </div>`).join('');
}

function updateGoalsLink() {
  const link = document.getElementById('goals-link');
  if (link && CID) link.href = `/#${CID}`;
}

// ── collapsible mind sections ─────────────────────────────────────────────────

document.querySelectorAll('.mind-h').forEach(h => {
  h.onclick = () => {
    const sec = h.getAttribute('data-sec');
    const body = document.getElementById('mind-' + sec);
    if (!body) return;
    const open = h.classList.toggle('open');
    body.style.display = open ? '' : 'none';
  };
});

// ── memory tabs ───────────────────────────────────────────────────────────────

document.querySelectorAll('.mem-tab').forEach(tab => {
  tab.onclick = async () => {
    document.querySelectorAll('.mem-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    MEM_CAT = tab.getAttribute('data-mcat');
    const mems = await api(`/${CID}/memories?limit=60`).catch(() => []);
    renderMemories(mems);
  };
});

// ── think button ──────────────────────────────────────────────────────────────

document.getElementById('think-btn').onclick = async () => {
  if (!CID) return;
  const btn = document.getElementById('think-btn');
  btn.disabled = true; btn.textContent = 'Thinking…';
  try {
    await api(`/${CID}/think`, { method: 'POST', json: {} });
    await loadNow();
    await loadFeedDay(SEL_DATE);
    await loadMind();
  } catch (e) {
    alert('Think failed: ' + (e.detail || JSON.stringify(e)));
  } finally {
    btn.disabled = false; btn.textContent = 'Think now';
  }
};

// ── char select ───────────────────────────────────────────────────────────────

document.getElementById('char-select').onchange = onCharChange;

// ── wire life.js version cache-bust ──────────────────────────────────────────

(function() {
  // stamp the life.js script tag so the browser doesn't serve stale on deploy
  const s = document.querySelector('script[src^="/life.js"]');
  if (s) s.src = '/life.js?v=' + Date.now();
})();

// ── init ──────────────────────────────────────────────────────────────────────

SEL_DATE = todayStr();
renderCal();
loadChars();
