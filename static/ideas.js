/* Short Ideas — parking lot for video ideas before production.
   Flow: pending → approved → conditioned → queued (short created) | rejected
   Helpers from index.html: api, esc, toast, confirmDlg, fmtDate, badge, LS */
(() => {
const css = document.createElement('style');
css.textContent = `
.id-header{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.id-cfg{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:16px}
.id-cfg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px 16px;margin-bottom:12px}
.id-cfg-cell label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin-bottom:3px}
.id-cfg-cell select,.id-cfg-cell input[type=number]{width:100%;font:inherit;font-size:13px;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.id-cfg-foot{display:flex;align-items:center;gap:10px;padding-top:10px;border-top:1px solid var(--line)}
.id-cfg.id-cfg-locked .id-cfg-grid{opacity:.55;pointer-events:none}
.id-autorun-label{display:flex;align-items:center;gap:7px;cursor:pointer;user-select:none;font-weight:600}
.id-autorun-label input{width:16px;height:16px}
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
let _diverse  = LS.get('ideas:diverse', false);
let _autoRun  = LS.get('ideas:autorun', false);
let _options  = null;   // loaded from /api/shorts/options
let _cfg = {
  pipeline: 'keyframe',
  voice:    'taksh_hn',
  language: 'hi',
  target_s: 29,
  tone_id:  'bigbro',
  edge:     'clean',
  upscale:  '2k',
  ...LS.get('ideas:config', {}),
};

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

// ── config panel helpers ───────────────────────────────────────────────────────

function _saveCfg() { LS.set('ideas:config', _cfg); }

function _syncCfgLock() {
  const panel = document.getElementById('id-cfg');
  if (!panel) return;
  panel.classList.toggle('id-cfg-locked', _autoRun);
  document.querySelectorAll('.id-cfg-cell select, .id-cfg-cell input').forEach(el => {
    el.disabled = _autoRun;
  });
}

function _cfgHtml() {
  // Voices: from API if loaded, else minimal fallback
  let voiceOpts;
  if (_options && _options.voices && _options.voices['maya-tts']) {
    const vmap = _options.voices['maya-tts'].voices; // {id: gender}
    const male = [], female = [], other = [];
    Object.entries(vmap).forEach(([id, gender]) => {
      const opt = `<option value="${id}"${_cfg.voice===id?' selected':''}>${id}</option>`;
      if (gender === 'male') male.push(opt);
      else if (gender === 'female') female.push(opt);
      else other.push(opt);
    });
    voiceOpts = (male.length ? `<optgroup label="Male">${male.join('')}</optgroup>` : '')
              + (female.length ? `<optgroup label="Female">${female.join('')}</optgroup>` : '')
              + (other.length ? `<optgroup label="Other">${other.join('')}</optgroup>` : '');
  } else {
    voiceOpts = `<option value="${_cfg.voice}">${_cfg.voice}</option>`;
  }

  // Languages: from API if loaded
  let langOpts;
  if (_options && _options.languages) {
    langOpts = _options.languages.map(l =>
      `<option value="${l.id}"${_cfg.language===l.id?' selected':''}>${l.label}</option>`
    ).join('');
  } else {
    langOpts = `<option value="hi"${_cfg.language==='hi'?' selected':''}>Hindi (Devanagari)</option>`
             + `<option value="hinglish"${_cfg.language==='hinglish'?' selected':''}>Hinglish</option>`
             + `<option value="en"${_cfg.language==='en'?' selected':''}>English</option>`;
  }

  const tones = [
    ['bigbro','Friendly big brother (default)'], ['storyteller','Calm storyteller'],
    ['soothing','Soothing explainer'], ['documentary','Documentary narrator'],
    ['explorer','Curious explorer'], ['thriller','Dramatic thriller'],
    ['roaster','Sarcastic roaster'], ['motivator','Hype motivator'],
    ['viral','Fast viral hook'], ['intense','Intense / aggressive'],
    ['survivor','Survivor (first person)'], ['campfire','Campfire storyteller'],
    ['investigator','Cold investigator'], ['memoir','Memoir voice'],
    ['founder_first','First-principles founder'], ['ceo_empathy','Empathetic CEO'],
    ['orator_rally','Rally orator'], ['teacher_energy','High-energy teacher'],
  ];
  const toneOpts = tones.map(([v,l]) => `<option value="${v}"${_cfg.tone_id===v?' selected':''}>${l}</option>`).join('');

  const cell = (id, label, inner) => `<div class="id-cfg-cell"><label for="${id}">${label}</label>${inner}</div>`;

  return `
    <div class="id-cfg-grid">
      ${cell('cfg-pipeline','Pipeline',`<select id="cfg-pipeline">
        <option value="keyframe"${_cfg.pipeline==='keyframe'?' selected':''}>Keyframe (14B, full quality)</option>
        <option value="quick"${_cfg.pipeline==='quick'?' selected':''}>Quick (5B, faster)</option>
      </select>`)}
      ${cell('cfg-voice','Voice',`<select id="cfg-voice">${voiceOpts}</select>`)}
      ${cell('cfg-language','Language',`<select id="cfg-language">${langOpts}</select>`)}
      ${cell('cfg-target-s','Length (seconds)',`<input type="number" id="cfg-target-s" min="5" max="180" value="${_cfg.target_s}">`)}
      ${cell('cfg-tone','Tone',`<select id="cfg-tone">${toneOpts}</select>`)}
      ${cell('cfg-edge','Edge',`<select id="cfg-edge">
        <option value="clean"${_cfg.edge==='clean'?' selected':''}>Clean</option>
        <option value="spicy"${_cfg.edge==='spicy'?' selected':''}>Spicy</option>
        <option value="savage"${_cfg.edge==='savage'?' selected':''}>Savage</option>
      </select>`)}
      ${cell('cfg-upscale','Upscale',`<select id="cfg-upscale">
        <option value="2k"${_cfg.upscale==='2k'?' selected':''}>2K (1440×2560)</option>
        <option value=""${_cfg.upscale===''?' selected':''}>1080p (1080×1920)</option>
      </select>`)}
    </div>
    <div class="id-cfg-foot">
      <label class="id-autorun-label" title="When ON: queueing a conditioned idea will also auto-run the full pipeline (plan → voice → pictures → clips → 2K → final). Settings above are locked until you turn Auto-run OFF.">
        <input type="checkbox" id="id-autorun" ${_autoRun ? 'checked' : ''}>
        <span>Auto-run after queue</span>
      </label>
      <span class="small mute">${_autoRun ? 'Settings locked — turn off Auto-run to change them' : 'When ON, settings lock and pipeline runs automatically after queuing'}</span>
    </div>`;
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
    ? `<button class="primary small" onclick="idQueue('${idea.id}')">→ ${_autoRun ? 'Queue + Auto-run' : 'Send to Queue'}</button>` : '';
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
  if (idea.status === 'conditioned')
    actions.push(`<button class="primary small" ${busy?'disabled':''} onclick="idQueue('${idea.id}')">${busy?'<span class="spin"></span> Queuing…': (_autoRun ? '→ Queue + Auto-run' : '→ Queue')}</button>`);
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
  if (!document.getElementById('id-tabs')) return;
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
    const settings = {
      voice:      {engine: 'maya-tts', voice: _cfg.voice},
      language:   _cfg.language,
      target_s:   Number(_cfg.target_s) || 29,
      tone_id:    _cfg.tone_id,
      edge:       _cfg.edge,
      upscale:    _cfg.upscale,
      image_mode: 'qwen',
      review_keyframes: false,
    };
    const r = await call(`/${id}/queue`, {method:'POST', json:{
      pipeline: _cfg.pipeline,
      settings,
      auto_run: _autoRun,
    }});
    _ideas = _ideas.map(i => i.id === id ? r.idea : i);
    if (_autoRun) {
      toast(r.auto_started
        ? `Short queued + pipeline started — open it to track progress`
        : `Short queued (pipeline busy — open it to run manually)`
      );
      _exp[id] = null;
    } else {
      toast('Short created — opening…');
      setTimeout(() => { location.hash = `#/short/${r.short_id}`; }, 600);
    }
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

// ── config panel events ───────────────────────────────────────────────────────

function _wireCfg() {
  const bind = (id, field, transform) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.onchange = () => {
      _cfg[field] = transform ? transform(el.value) : el.value;
      _saveCfg();
    };
  };
  bind('cfg-pipeline', 'pipeline');
  bind('cfg-voice',    'voice');
  bind('cfg-language', 'language');
  bind('cfg-target-s', 'target_s', v => Math.max(5, Math.min(180, parseInt(v) || 29)));
  bind('cfg-tone',     'tone_id');
  bind('cfg-edge',     'edge');
  bind('cfg-upscale',  'upscale');

  const ar = document.getElementById('id-autorun');
  if (ar) ar.onchange = e => {
    _autoRun = e.target.checked;
    LS.set('ideas:autorun', _autoRun);
    // re-render config panel to update hint text and lock state
    const cfgEl = document.getElementById('id-cfg');
    if (cfgEl) cfgEl.innerHTML = _cfgHtml();
    _wireCfg();
    _syncCfgLock();
    _render(); // update queue button labels
  };
  _syncCfgLock();
}

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
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none" title="Diverse: splits ideas across 5 domain lenses (military, science, economics, Indian history, engineering) for variety, then auto-rates">
        <input type="checkbox" id="id-diverse" ${_diverse ? 'checked' : ''}>
        <span class="small">Diverse</span>
      </label>
      <button class="primary" id="id-gen">Generate</button>
      <button id="id-rate">Rate all</button>
      <button onclick="location.hash='#/shorts'">← Shorts</button>
    </div>
    <div class="id-cfg" id="id-cfg">${_cfgHtml()}</div>
    <div class="id-tabs" id="id-tabs"></div>
    <div id="id-list"><div class="pad"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div></div>`;

  _wireCfg();

  document.getElementById('id-diverse').onchange = e => {
    _diverse = e.target.checked;
    LS.set('ideas:diverse', _diverse);
  };

  document.getElementById('id-gen').onclick = async () => {
    const n = parseInt(document.getElementById('id-n').value) || 7;
    const diverse = document.getElementById('id-diverse').checked;
    const btn = document.getElementById('id-gen');
    const label = diverse ? `Generating ${n} ideas across 5 lenses…` : `Generating ${n} ideas…`;
    btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${label}`;
    try {
      const fresh = await call('/generate', {method:'POST', json:{n, diverse}});
      _ideas = [...fresh, ..._ideas];
      _tab = 'pending';
      _render();
      toast(`${fresh.length} ideas generated${diverse ? ' (diverse mode)' : ''}`);

      if (diverse && fresh.length) {
        const rateBtn = document.getElementById('id-rate');
        if (rateBtn) { rateBtn.disabled = true; rateBtn.innerHTML = '<span class="spin"></span> Rating…'; }
        try {
          const rated = await call('/rate', {method:'POST', json:{ids:[]}});
          const byId = Object.fromEntries(rated.map(r => [r.id, r]));
          _ideas = _ideas.map(i => byId[i.id] || i);
          _ideas.sort((a, b) => (b.engagement_score || 0) - (a.engagement_score || 0));
          _render();
          toast(`${rated.length} ideas scored and ranked`);
        } catch(e) { toast('Rating failed: ' + e.message, {bad:true}); }
        if (rateBtn) { rateBtn.disabled = false; rateBtn.innerHTML = 'Rate all'; }
      }
    } catch(e) { toast(e.message, {bad:true}); }
    btn.disabled = false; btn.innerHTML = 'Generate';
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

  [_ideas, _options] = await Promise.all([
    call('').catch(() => []),
    api('/shorts/options').catch(() => null),
  ]);
  // Re-render config panel now that we have live voices/languages
  const cfgEl = document.getElementById('id-cfg');
  if (cfgEl) { cfgEl.innerHTML = _cfgHtml(); _wireCfg(); }
  _render();
};
})();
