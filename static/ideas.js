/* Short Ideas — parking lot for video ideas before production.
   Flow: pending → approved → conditioned → queued (short created) | rejected
   Helpers from index.html: api, esc, toast, confirmDlg, fmtDate, badge */
(() => {
const css = document.createElement('style');
css.textContent = `
.id-header{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
.id-day{font-size:11px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.06em;padding:14px 0 6px;border-bottom:1px solid var(--line);margin-bottom:10px}
.id-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px;transition:border-color .15s}
.id-card:hover{border-color:color-mix(in srgb,var(--accent) 50%,var(--line))}
.id-card.id-approved{border-left:4px solid var(--ok)}
.id-card.id-conditioned{border-left:4px solid var(--accent)}
.id-card.id-queued{border-left:4px solid var(--info)}
.id-card.id-rejected{opacity:.5}
.id-hook{font-size:16px;font-weight:650;line-height:1.35;margin:0 0 8px;cursor:pointer}
.id-hook:hover{color:var(--accent)}
.id-mech{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0}
.id-mech span{font-size:11px;padding:1px 8px;border-radius:99px;background:var(--accent-soft);color:var(--accent);font-weight:600}
.id-score{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:700;padding:2px 10px;border-radius:99px;background:var(--okbg);color:var(--ok)}
.id-score.low{background:var(--warnbg);color:var(--warn)}.id-score.bad{background:var(--badbg);color:var(--bad)}
.id-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:10px}
.id-expand{padding:10px 0 2px;border-top:1px solid var(--line);margin-top:10px}
.id-section{margin:10px 0}
.id-section h5{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:0 0 5px}
.id-arc{list-style:none;padding:0;margin:0}
.id-arc li{display:grid;grid-template-columns:60px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px}
.id-arc li:last-child{border-bottom:0}
.id-arc .ts{color:var(--accent);font-weight:600;font-size:11px;padding-top:1px}
.id-facts{margin:4px 0;padding-left:18px;font-size:13px}
.id-facts li{margin:3px 0}
.id-verdict{font-size:12px;font-style:italic;color:var(--mute);margin-top:4px}
.id-reasoning{font-size:13px;line-height:1.5;background:var(--bg);padding:8px 10px;border-radius:8px;margin-top:4px}
.id-journey{display:grid;grid-template-columns:60px 1fr;gap:5px;font-size:12px;line-height:1.6}
.id-journey .ts{color:var(--mute);font-weight:600}
.id-pnotes{font-size:13px;background:var(--warnbg);color:var(--warn);padding:8px 10px;border-radius:8px;margin-top:4px}
.id-tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:16px;overflow-x:auto}
.id-tabs button{border:0;border-bottom:2px solid transparent;border-radius:0;background:none;padding:7px 14px;color:var(--mute);font:inherit;cursor:pointer;white-space:nowrap}
.id-tabs button.on{color:var(--ink);border-color:var(--accent);font-weight:600}
.id-empty{text-align:center;padding:40px 20px;color:var(--mute)}
`;
document.head.append(css);

// ── state ─────────────────────────────────────────────────────────────────────
let _tab = 'all', _ideas = [], _busy = new Set(), _exp = {};

const call = (path, opts) => api('/shorts/ideas' + path, opts);
const STATUS_TABS = ['all','pending','approved','conditioned','queued','rejected'];
const MECH_LABELS = {
  curiosity_gap:'Curiosity gap', threat_detection:'Threat detect',
  novelty:'Novelty', prediction_error:'Prediction error',
  social_comparison:'Social compare', pattern_interruption:'Pattern interrupt',
  emotional_arousal:'Emotional arousal', incomplete_loops:'Incomplete loop',
};

function scoreClass(s) { return !s ? '' : s >= 7 ? '' : s >= 5 ? 'low' : 'bad'; }

function mechBadges(mechs) {
  return (mechs || []).map(m => `<span>${esc(MECH_LABELS[m] || m)}</span>`).join('');
}

function fmtDay(ts) {
  return new Date(ts * 1000).toLocaleDateString([], {weekday:'long',year:'numeric',month:'long',day:'numeric'});
}

function groupByDay(ideas) {
  const days = {};
  for (const i of ideas) {
    const key = new Date(i.created_at * 1000).toDateString();
    (days[key] = days[key] || {label: fmtDay(i.created_at), items: []}).items.push(i);
  }
  return Object.values(days);
}

// ── panel renderers ───────────────────────────────────────────────────────────

function scorePanel(idea) {
  const sc = idea.score_breakdown || {};
  if (!sc.reasoning) return '';
  const rows = [
    ['Hook', sc.hook_strength], ['Mechs', sc.mechanism_count],
    ['Emotion', sc.emotional_intensity], ['Completion', sc.completion_rate],
    ['Novelty', sc.novelty], ['Revelation', sc.progressive_revelation],
    ['Share', sc.shareability],
  ].filter(([,v]) => v != null).map(([l,v]) => `<span class="mute small">${l}</span> <b>${v}</b>`).join(' · ');
  return `<div class="id-expand">
    <div class="id-section"><h5>Score breakdown</h5>
      <div class="small" style="margin-bottom:6px">${rows}</div>
      <div class="id-reasoning">${esc(sc.reasoning)}</div>
    </div></div>`;
}

function condPanel(idea) {
  const c = idea.conditioning || {};
  if (!c.refined_hook) return '';
  const arc = (c.narrative_arc || []).map(s => {
    const sep = s.indexOf(': ');
    const ts = sep > -1 ? s.slice(0, sep) : '';
    const txt = sep > -1 ? s.slice(sep + 2) : s;
    return `<li><span class="ts">${esc(ts)}</span><span>${esc(txt)}</span></li>`;
  }).join('');
  const journey = (c.emotional_journey || []).map(s => {
    const sep = s.indexOf(': ');
    const ts = sep > -1 ? s.slice(0, sep) : '';
    const txt = sep > -1 ? s.slice(sep + 2) : s;
    return `<span class="ts">${esc(ts)}</span><span>${esc(txt)}</span>`;
  }).join('');
  const facts = (c.key_facts || []).map(f => `<li>${esc(f)}</li>`).join('');
  const queueBtn = idea.status === 'conditioned'
    ? `<button class="primary small" onclick="idQueue('${idea.id}')">→ Send to Queue</button>` : '';
  return `<div class="id-expand">
    <div class="id-section"><h5>Refined hook</h5>
      <div style="font-size:15px;font-weight:650;line-height:1.4">${esc(c.refined_hook)}</div>
    </div>
    ${c.opening_line ? `<div class="id-section"><h5>Opening line (Hinglish)</h5><div class="passage">${esc(c.opening_line)}</div></div>` : ''}
    ${arc ? `<div class="id-section"><h5>Narrative arc</h5><ul class="id-arc">${arc}</ul></div>` : ''}
    ${journey ? `<div class="id-section"><h5>Emotional journey</h5><div class="id-journey">${journey}</div></div>` : ''}
    ${facts ? `<div class="id-section"><h5>Key facts (verify before production)</h5><ul class="id-facts">${facts}</ul></div>` : ''}
    ${c.visual_direction ? `<div class="id-section"><h5>Visual direction</h5><div class="small">${esc(c.visual_direction)}</div></div>` : ''}
    ${c.suggested_tone ? `<div class="id-section"><h5>Suggested tone</h5><span class="badge">${esc(c.suggested_tone)}</span></div>` : ''}
    ${c.production_notes ? `<div class="id-section"><h5>Production notes</h5><div class="id-pnotes">${esc(c.production_notes)}</div></div>` : ''}
    ${queueBtn ? `<div class="id-actions">${queueBtn}</div>` : ''}
  </div>`;
}

// ── card ──────────────────────────────────────────────────────────────────────

function renderCard(idea) {
  const busy = _busy.has(idea.id);
  const exp  = _exp[idea.id];
  const hasSc = !!(idea.score_breakdown && idea.score_breakdown.reasoning);
  const hasCo = !!(idea.conditioning && idea.conditioning.refined_hook);
  const defaultExp = hasCo ? 'cond' : hasSc ? 'score' : '';

  const actions = [];
  if (idea.status === 'pending') {
    actions.push(`<button class="good small" onclick="idApprove('${idea.id}')">Approve</button>`);
    actions.push(`<button class="small bad" onclick="idReject('${idea.id}')">Reject</button>`);
  }
  if (idea.status === 'approved')
    actions.push(`<button class="primary small" ${busy?'disabled':''} onclick="idCondition('${idea.id}')">${busy?'<span class="spin"></span> Conditioning…':'Condition'}</button>`);
  if (idea.status === 'conditioned')
    actions.push(`<button class="small" ${busy?'disabled':''} onclick="idCondition('${idea.id}')">${busy?'<span class="spin"></span>':''}Re-condition</button>`);
  if (idea.status === 'queued' && idea.short_id)
    actions.push(`<a class="btn small" href="#/short/${idea.short_id}">Open short →</a>`);
  if (idea.status !== 'queued')
    actions.push(`<button class="small bad" onclick="idDelete('${idea.id}')">Delete</button>`);
  if (hasSc) actions.push(`<button class="small link" onclick="idToggle('${idea.id}','score')">${exp==='score'?'Hide score':'Score detail'}</button>`);
  if (hasCo) actions.push(`<button class="small link" onclick="idToggle('${idea.id}','cond')">${exp==='cond'?'Hide brief':'View brief'}</button>`);

  const statusKey = idea.status==='queued'?'queued':idea.status==='conditioned'?'info':idea.status==='approved'?'done':idea.status==='rejected'?'error':'';
  const expandPanel = exp === 'score' ? scorePanel(idea) : exp === 'cond' ? condPanel(idea) : '';

  return `<div class="id-card id-${idea.status}" id="card-${idea.id}">
    <div class="id-hook" onclick="idToggle('${idea.id}','${defaultExp}')">${esc(idea.hook)}</div>
    <div class="id-mech">${mechBadges(idea.mechanisms)}</div>
    <div class="row" style="gap:8px;flex-wrap:wrap">
      ${badge(statusKey, idea.status)}
      ${idea.engagement_score ? `<span class="id-score ${scoreClass(idea.engagement_score)}">★ ${idea.engagement_score.toFixed(1)}</span>` : ''}
      ${busy ? '<span class="mute small"><span class="spin"></span> working…</span>' : ''}
    </div>
    ${idea.premise ? `<p class="small mute" style="margin:6px 0 0">${esc(idea.premise)}</p>` : ''}
    <div class="id-actions">${actions.join('')}</div>
    ${expandPanel}
  </div>`;
}

// ── render ────────────────────────────────────────────────────────────────────

function _render() {
  if (!document.getElementById('id-tabs')) return; // navigated away
  const filtered = _tab === 'all' ? _ideas : _ideas.filter(i => i.status === _tab);
  const tabs = STATUS_TABS.map(t => {
    const n = t === 'all' ? _ideas.length : _ideas.filter(i => i.status === t).length;
    return `<button class="${_tab===t?'on':''}" onclick="idTab('${t}')">${t[0].toUpperCase()+t.slice(1)}${n?` <span class="badge">${n}</span>`:''}</button>`;
  }).join('');
  const groups = groupByDay(filtered);
  const content = groups.length
    ? groups.map(g => `<div class="id-day">${esc(g.label)}</div>` + g.items.map(renderCard).join('')).join('')
    : `<div class="id-empty">No ideas here. Generate some above.</div>`;
  document.getElementById('id-tabs').innerHTML = tabs;
  document.getElementById('id-list').innerHTML = content;
}

// ── window actions (called from onclick in generated HTML) ────────────────────

window.idTab = t => { _tab = t; _render(); };

window.idToggle = (id, mode) => {
  if (!mode) return;
  _exp[id] = _exp[id] === mode ? null : mode;
  _render();
};

window.idApprove = async id => {
  _busy.add(id); _render();
  try {
    const r = await call(`/${id}/approve`, {method:'POST'});
    _ideas = _ideas.map(i => i.id === id ? r : i);
    toast('Idea approved');
  } catch(e) { toast(e.message, {bad:true}); }
  _busy.delete(id); _render();
};

window.idReject = async id => {
  _busy.add(id); _render();
  try {
    const r = await call(`/${id}/reject`, {method:'POST'});
    _ideas = _ideas.map(i => i.id === id ? r : i);
    toast('Idea rejected');
  } catch(e) { toast(e.message, {bad:true}); }
  _busy.delete(id); _render();
};

window.idCondition = async id => {
  _busy.add(id); _render();
  try {
    const r = await call(`/${id}/condition`, {method:'POST'});
    _ideas = _ideas.map(i => i.id === id ? r : i);
    _exp[id] = 'cond';
    toast('Production brief ready — review before queuing');
  } catch(e) { toast(e.message, {bad:true}); }
  _busy.delete(id); _render();
};

window.idQueue = async id => {
  _busy.add(id); _render();
  try {
    const r = await call(`/${id}/queue`, {method:'POST', json:{pipeline:'quick'}});
    _ideas = _ideas.map(i => i.id === id ? r.idea : i);
    toast('Short created — opening…');
    setTimeout(() => { location.hash = `#/short/${r.short_id}`; }, 600);
  } catch(e) { toast(e.message, {bad:true}); }
  _busy.delete(id); _render();
};

window.idDelete = async id => {
  const idea = _ideas.find(i => i.id === id);
  if (!idea) return;
  if (!await confirmDlg('Delete idea', `Delete this idea?\n\n"${idea.hook}"`, 'Delete', true)) return;
  try {
    await call(`/${id}`, {method:'DELETE'});
    _ideas = _ideas.filter(i => i.id !== id);
    _render();
  } catch(e) { toast(e.message, {bad:true}); }
};

// ── main view ─────────────────────────────────────────────────────────────────

window.viewIdeas = async function() {
  document.getElementById('app').innerHTML = `
    <div class="id-header">
      <h2 style="margin:0">Short Ideas</h2>
      <span class="mute small">Park · Rate · Approve · Condition · Queue</span>
      <span class="sp"></span>
      <select id="id-n" style="width:90px">
        <option value="5">5 ideas</option>
        <option value="7" selected>7 ideas</option>
        <option value="10">10 ideas</option>
      </select>
      <button class="primary" id="id-gen">Generate</button>
      <button id="id-rate">Rate all</button>
      <button onclick="location.hash='#/shorts'">← Shorts</button>
    </div>
    <div class="id-tabs" id="id-tabs"></div>
    <div id="id-list"><div class="pad"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div></div>`;

  document.getElementById('id-gen').onclick = async () => {
    const n = parseInt(document.getElementById('id-n').value) || 7;
    const btn = document.getElementById('id-gen');
    await act(btn, async () => {
      const fresh = await call('/generate', {method:'POST', json:{n}});
      _ideas = [...fresh, ..._ideas];
      _tab = 'pending';
      _render();
      return fresh.length;
    }, n => `${n} ideas generated`);
  };

  document.getElementById('id-rate').onclick = async () => {
    const btn = document.getElementById('id-rate');
    await act(btn, async () => {
      const rated = await call('/rate', {method:'POST', json:{ids:[]}});
      const byId = Object.fromEntries(rated.map(r => [r.id, r]));
      _ideas = _ideas.map(i => byId[i.id] || i);
      _ideas.sort((a, b) => (b.engagement_score || 0) - (a.engagement_score || 0));
      _render();
      return rated.length;
    }, n => `${n} ideas scored and ranked`);
  };

  _ideas = await call('').catch(() => []);
  _render();
};
})();
