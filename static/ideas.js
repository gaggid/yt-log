/* Short Ideas — parking lot for video ideas before production.
   Flow: pending → approved → conditioned → queued (short being made) → done (short finished, by itself) | rejected
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
.id-prog{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:14px}
.id-prog-top{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600}
.id-prog-bar{height:6px;border-radius:99px;background:var(--line);margin-top:8px;overflow:hidden}
.id-prog-bar i{display:block;height:100%;background:var(--accent);transition:width .4s}
.id-prog.bad{border-color:var(--bad)}
.id-auto{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:12px}
.id-auto.on{border-color:var(--ok)}
.id-auto-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.id-auto-top .big{font-size:15px;font-weight:700}
.id-auto-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px 18px;margin-top:10px}
.id-auto-grid .it{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:13px}
.id-auto-grid input[type=number]{width:62px;font:inherit;font-size:13px;padding:2px 6px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.id-auto-grid .nx{width:100%;font-size:11px;color:var(--mute);padding-left:22px}
.id-q{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}
.id-q span{font-size:12px;padding:3px 10px;border-radius:99px;background:var(--bg);border:1px solid var(--line)}
.id-q span b{font-weight:700}
.id-q span.run{border-color:var(--accent);color:var(--accent)}
.id-board{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-bottom:14px}
.id-col{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}
.id-col h4{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);display:flex;gap:6px;align-items:center}
.id-col h4 .badge{margin-left:auto}
.id-col .none{font-size:12px;color:var(--mute);padding:6px 0}
.id-qi{border-top:1px solid var(--line);padding:7px 0;font-size:13px}
.id-qi:first-of-type{border-top:0}
.id-qi .t{line-height:1.3;word-break:break-word}
.id-rank{display:inline-block;min-width:26px;text-align:center;margin-right:6px;font-size:11px;font-weight:700;padding:0 6px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
.id-rank.next{background:var(--accent);border-color:var(--accent);color:#fff}
.id-rank.held{opacity:.6}
.id-col .id-sub{font-size:11px;color:var(--mute);margin:-4px 0 6px}
.id-card.id-done{border-left:4px solid var(--good, #2e9d5b)}
.id-qi .m{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px;font-size:11px;color:var(--mute)}
.id-pub textarea,.id-pub input{width:100%;font:inherit;font-size:13px;padding:6px 8px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
.id-chips{display:flex;gap:6px;flex-wrap:wrap}
.id-chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:3px 10px;border-radius:99px;border:1px solid var(--line);cursor:pointer;user-select:none}
.id-chip input{margin:0}
.id-chip.on{background:var(--accent-soft);border-color:var(--accent)}
.id-src{margin:6px 0 0;font-size:12px}
.id-src a{margin-right:10px}
.id-why{font-size:12px;color:var(--warn);margin-top:4px}
.id-card.id-new{animation:idnew 1.6s ease-out}
@keyframes idnew{from{background:var(--accent-soft)}to{background:var(--panel)}}
`;
document.head.append(css);

// ── state ─────────────────────────────────────────────────────────────────────
let _tab = 'all', _ideas = [], _busy = new Set(), _exp = {};
let _diverse  = false;
let _autoRun  = false;
let _options  = null;
let _cfg      = {};
let _n        = 7;
let _minScore = 7;
let _job      = null, _seen = new Set(), _pollGen = 0;
let _auto     = {autopilot:false, auto_generate:false, auto_approve:false, auto_condition:false, gen_every_h:1, gen_n:5, approve_min:7.8, make_every_h:2, pending_cap:30, review_cap:3, styles:[]};
const BRIGHT_STYLES = ['realism', 'pixar3d', 'anime', 'ghibli', 'tinyworld'];
let _ap       = null, _apAt = 0, _apTimer = null;      // /ideas/autopilot (queues and schedule) and when it was read
const _CFG_DEFAULTS = {pipeline:'keyframe', voice:'taksh_hn', language:'hi', target_s:29, tone_id:'bigbro', edge:'clean', upscale:'2k'};

function _loadState() {                     // the browser's copy: shown at once; the server's copy (saved config) replaces it when it arrives
  _diverse  = LS.get('ideas:diverse', false);
  _autoRun  = LS.get('ideas:autorun', false);
  _cfg      = {..._CFG_DEFAULTS, ...LS.get('ideas:config', {})};
  _auto     = {..._auto, ...LS.get('ideas:auto', {})};
  _n        = LS.get('ideas:n', 7);
  _minScore = LS.get('ideas:minscore', 7);
}

function _applyServerCfg(c) {
  if (!c) return;
  _diverse = !!c.diverse; _autoRun = !!c.autorun; _n = c.n || 7; _minScore = c.min_score ?? 7;
  _cfg = {..._CFG_DEFAULTS, ...(c.run || {})};
  for (const k of Object.keys(_auto)) if (c[k] !== undefined) _auto[k] = c[k];
  LS.set('ideas:auto', _auto);
  LS.set('ideas:diverse', _diverse); LS.set('ideas:autorun', _autoRun); LS.set('ideas:config', _cfg); LS.set('ideas:n', _n); LS.set('ideas:minscore', _minScore);
}

let _saveT = null;
function _persist() {                       // every change is saved on the server (debounced), so any browser and the unattended auto-queue see it
  LS.set('ideas:diverse', _diverse); LS.set('ideas:autorun', _autoRun); LS.set('ideas:config', _cfg); LS.set('ideas:n', _n); LS.set('ideas:minscore', _minScore); LS.set('ideas:auto', _auto);
  clearTimeout(_saveT);
  _saveT = setTimeout(() => call('/config', {method:'PUT', json:{autorun:_autoRun, diverse:_diverse, n:_n, min_score:_minScore, run:_cfg, ..._auto}})
    .catch(e => toast('Settings not saved: ' + e.message, {bad:true})), 300);
}

const call = (path, opts) => api('/shorts/ideas' + path, opts);
const STATUS_TABS = ['all','pending','approved','conditioned','queued','done','rejected'];
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

function _saveCfg() { _persist(); }

function _syncCfgLock() {
  const panel = document.getElementById('id-cfg');
  if (!panel) return;
  panel.classList.toggle('id-cfg-locked', _auto.autopilot);
  document.querySelectorAll('.id-cfg-cell select, .id-cfg-cell input').forEach(el => {
    el.disabled = _auto.autopilot;
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
    <div class="id-cfg-foot" style="display:block">
      <div class="small mute" style="margin-bottom:6px;font-weight:600;text-transform:uppercase;letter-spacing:.05em">Picture styles <span style="text-transform:none;font-weight:400">— ideas and shorts use only the ticked styles, rotating; none ticked = any</span>
        <button class="small link" id="st-bright" type="button">Bright set</button><button class="small link" id="st-any" type="button">Any style</button></div>
      <div class="id-chips" id="id-styles">${_stylesHtml()}</div>
    </div>`;
}

function _stylesHtml() {
  const list = ((_options && _options.visual_styles) || []).filter(m => m.id);
  if (!list.length) return '<span class="mute small">Loading styles…</span>';
  return list.map(m => {
    const on = _auto.styles.includes(m.id);
    return `<label class="id-chip ${on ? 'on' : ''}" title="${esc(m.description || '')}"><input type="checkbox" data-style="${esc(m.id)}" ${on ? 'checked' : ''} ${_auto.autopilot ? 'disabled' : ''}>${esc(m.label)}</label>`;
  }).join('');
}

// ── autopilot panel: master switch, schedule, queues ──────────────────────────

function _until(ts) {                       // "in 12m" from a server timestamp (corrected by the clock difference read with it)
  const left = ts - (_ap ? _ap.now : Date.now() / 1000) - (Date.now() / 1000 - _apAt);
  return left <= 0 ? 'due now' : 'in ' + hd(left);
}

function _autoHtml() {
  const a = _auto, on = a.autopilot, c = (_ap && _ap.counts) || {}, run = _ap && _ap.running || {};
  const num = (id, v, min, max, step) => `<input type="number" id="${id}" value="${v}" min="${min}" max="${max}" step="${step || 1}">`;
  const sw = (id, label, checked, extra, next) => `<div class="it"><label style="display:flex;align-items:center;gap:6px;cursor:pointer"><input type="checkbox" id="${id}" ${checked ? 'checked' : ''}> ${label}</label>${extra || ''}${next ? `<div class="nx">${next}</div>` : ''}</div>`;
  const nextGen = on && a.auto_generate && _ap ? 'next batch ' + _until(_ap.next_gen_at) : '';
  const nextMake = on && _autoRun && _ap ? 'next short ' + _until(_ap.next_make_at) : '';
  const q = (label, n, cls) => `<span class="${cls || ''}">${label} <b>${n || 0}</b></span>`;
  return `<div class="id-auto-top">
      <label class="id-autorun-label" title="OFF: nothing runs by itself. ON: the switches below run in sequence, one job at a time (the gateway key serves one request at a time).">
        <input type="checkbox" id="ap-master" ${on ? 'checked' : ''}><span class="big">Autopilot — full automated pipeline</span></label>
      <span class="badge ${on ? 'good' : ''}">${on ? 'ON' : 'OFF'}</span>
      <span class="sp"></span>
      <span class="mute small">${on ? (run.busy ? (run.kind === 'short' ? 'A short is being made now' : 'An ideas job is running') : 'Idle: waiting for the next step') : 'Nothing runs by itself'}</span>
    </div>
    <div class="id-auto-grid">
      ${sw('ap-gen', 'Generate ideas every', a.auto_generate, `${num('ap-gen-h', a.gen_every_h, 0.25, 48, 0.25)} h × ${num('ap-gen-n', a.gen_n, 1, 15)} ideas (web search, duplicates removed, rated)`, nextGen)}
      ${sw('ap-appr', 'Auto-approve scoring at least', a.auto_approve, num('ap-appr-min', a.approve_min, 0, 10, 0.1))}
      ${sw('ap-cond', 'Write the brief (condition) for approved ideas, best first', a.auto_condition)}
      ${sw('id-autorun', 'Make a short every', _autoRun, `${num('ap-make-h', a.make_every_h, 0.25, 48, 0.25)} h, scoring at least ${num('id-minscore', _minScore, 0, 10, 0.5)}`, nextMake)}
      <div class="it"><span>Pause making when</span>${num('ap-review', a.review_cap, 0, 100)}<span>finished shorts wait for your review (0 = no limit)</span></div>
      <div class="it"><span>Keep at most</span>${num('ap-pending', a.pending_cap, 1, 500)}<span>ideas waiting for approval</span></div>
    </div>
    <div class="id-q">
      ${q('To approve', c.pending)}${q('To condition', c.approved)}${q('To make', c.conditioned)}
      ${run.busy && run.kind === 'short' ? `<span class="run">Making now: <a href="#/short/${esc(run.short_id)}">${esc(run.short_id)}</a></span>` : q('Making', 0)}
      ${q('Done', c.done)}${q('Waiting for review', c.waiting_review + (a.review_cap ? ' / ' + a.review_cap : ''))}${q('Rejected', c.rejected)}
      <span class="sp"></span>
      <button class="small" id="ap-run-gen" title="Run one batch now">Generate now</button>
      <button class="small" id="ap-run-cond" title="Write the brief of the best approved idea now">Condition next</button>
      <button class="small" id="ap-run-make" title="Make a short of the best conditioned idea now">Make next</button>
    </div>`;
}

function _serverNow() { return (_ap ? _ap.now : Date.now() / 1000) + (Date.now() / 1000 - _apAt); }

function _age(sec) {                        // "2d 4h", "3h 10m", "12 min"
  sec = Math.max(0, Math.round(sec));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${String(m).padStart(2, '0')}m` : `${Math.max(1, m)} min`;
}

function _since(i, field) {                 // how long the idea has waited at this stage (rows from before the stamps use the last change)
  return _age(_serverNow() - (i[field] || i.updated_at));
}

function _queueItem(i, stage) {
  const sc = i.engagement_score ? `<span class="id-score ${scoreClass(i.engagement_score)}" style="font-size:11px;padding:0 7px">★ ${i.engagement_score.toFixed(1)}</span>` : '';
  const a = _ap || {};
  const rank = i.rank ? `<span class="id-rank${i.rank === 1 ? ' next' : ''}" title="${i.rank === 1 ? 'Taken next' : 'Place in line'}">${i.rank === 1 ? 'NEXT' : '#' + i.rank}</span>` : (i.hold ? '<span class="id-rank held">–</span>' : '');
  const hold = i.hold ? `<span class="bad">${esc(i.hold)}</span>` : '';
  const act = stage === 'approved' ? `<button class="small" data-now="condition" data-id="${i.id}">Condition now</button>`
    : stage === 'conditioned' ? `<button class="small primary" data-now="make" data-id="${i.id}">Make now</button>`
    : stage === 'queued' ? `${i.short_id ? `<a class="btn small" href="#/short/${i.short_id}">Open</a>` : ''}`
    : `${i.short_id ? `<a class="btn small" href="#/short/${i.short_id}">Open</a>` : ''}<button class="small" onclick="idReviewed('${i.id}', ${i.reviewed ? 'false' : 'true'})">${i.reviewed ? 'Reviewed ✓' : 'Mark reviewed'}</button>`;
  let stat = '';
  if (stage === 'approved') stat = i.hold ? '' : `<span title="Time since this idea was approved">approved ${_since(i, 'approved_at')} ago</span>`;
  else if (stage === 'conditioned') {
    stat = `<span title="Time since the brief was written, so this idea could be made">ready ${_since(i, 'conditioned_at')} ago</span>`;
    if (i.rank) {                           // when the schedule reaches it: the next slot, then one more every "make every" hours
      const on = _auto.autopilot && _autoRun;
      const at = Math.max(a.next_make_at || 0, _serverNow()) + (i.rank - 1) * (a.make_every_h || 2) * 3600;
      stat += on ? `<span title="Estimated: the next slot, then one short every ${a.make_every_h || 2} h (waits if reviews pile up)">starts ${_until(at)}</span>` : '<span>autopilot is not making shorts</span>';
    }
  }
  else if (stage === 'queued') stat = `<span>${esc(i.short_status === 'deleted' ? 'short deleted' : 'being made')}</span>`;
  else stat = `<span>finished ${_since(i, 'done_at')} ago</span>${i.reviewed ? '' : '<span>not reviewed</span>'}`;
  return `<div class="id-qi"><div class="t">${rank}${esc((i.hook || '').slice(0, 110))}</div><div class="m">${sc}${stat}${hold}<span class="sp"></span>${act}</div></div>`;
}

function _boardHtml() {
  const q = (_ap && _ap.queues) || {approved: [], conditioned: [], queued: [], done: []};
  const col = (title, list, stage, note, sub) => `<div class="id-col"><h4>${title}<span class="badge">${list.length}</span></h4>${sub ? `<div class="id-sub">${sub}</div>` : ''}${list.length ? list.map(i => _queueItem(i, stage)).join('') : `<div class="none">${note}</div>`}</div>`;
  return col('1 · To condition (approved)', q.approved, 'approved', 'No approved idea waits for a brief.', 'Best score first. #1 gets its brief next.')
       + col('2 · To make (conditioned)', q.conditioned, 'conditioned', 'No conditioned idea is waiting to be made into a short.', `Best score first, only scoring ${(_ap && _ap.min_score) || _minScore}+. #1 is made next.`)
       + col('3 · Being made', q.queued || [], 'queued', 'No short is being made.', '')
       + col('4 · Done (video ready)', q.done || [], 'done', 'No finished short yet.', 'An idea moves here by itself when its video is ready.');
}

function _wireBoard() {
  document.querySelectorAll('#id-board [data-now]').forEach(b => b.onclick = async () => {
    await act(b, async () => { _ap = await call('/autopilot/run', {method:'POST', json:{stage: b.dataset.now, idea_id: b.dataset.id}}); _apAt = Date.now() / 1000; _poll(); },
      b.dataset.now === 'make' ? 'Short queued and started' : 'Started');
    _drawAuto();
  });
}

function _wireAuto() {
  const el = document.getElementById('id-auto');
  if (!el) return;
  const flag = (id, key) => { const e = document.getElementById(id); if (e) e.onchange = () => { _auto[key] = e.checked; _persist(); _drawAuto(); }; };
  const numf = (id, key, lo, hi, set) => { const e = document.getElementById(id); if (e) e.onchange = () => { const v = Math.max(lo, Math.min(hi, parseFloat(e.value) || lo)); e.value = v; set ? set(v) : (_auto[key] = v); _persist(); }; };
  flag('ap-master', 'autopilot'); flag('ap-gen', 'auto_generate'); flag('ap-appr', 'auto_approve'); flag('ap-cond', 'auto_condition');
  const ar = document.getElementById('id-autorun');
  if (ar) ar.onchange = () => { _autoRun = ar.checked; _persist(); _drawAuto(); _render(); };
  numf('ap-gen-h', 'gen_every_h', 0.25, 48); numf('ap-gen-n', 'gen_n', 1, 15); numf('ap-appr-min', 'approve_min', 0, 10);
  numf('ap-make-h', 'make_every_h', 0.25, 48); numf('id-minscore', '', 0, 10, v => { _minScore = v; });
  numf('ap-review', 'review_cap', 0, 100); numf('ap-pending', 'pending_cap', 1, 500);
  const run = async (btn, stage) => {
    await act(btn, async () => { _ap = await call('/autopilot/run', {method:'POST', json:{stage}}); _apAt = Date.now() / 1000; _poll(); }, stage === 'make' ? 'Short queued and started' : 'Started');
    _drawAuto();
  };
  const g = document.getElementById('ap-run-gen'), c = document.getElementById('ap-run-cond'), m = document.getElementById('ap-run-make');
  if (g) g.onclick = () => run(g, 'generate');
  if (c) c.onclick = () => run(c, 'condition');
  if (m) m.onclick = () => run(m, 'make');
}

function _drawAuto() {
  const el = document.getElementById('id-auto');
  if (!el) return;
  el.className = 'id-auto' + (_auto.autopilot ? ' on' : '');
  el.innerHTML = _autoHtml();
  _wireAuto();
  const bd = document.getElementById('id-board');
  if (bd) { bd.innerHTML = _boardHtml(); _wireBoard(); }
  _syncCfgLock();
  const st = document.getElementById('id-styles');
  if (st) st.innerHTML = _stylesHtml(), _wireStyles();
}

function _wireStyles() {
  const setStyles = list => { _auto.styles = list; _persist(); const st = document.getElementById('id-styles'); if (st) { st.innerHTML = _stylesHtml(); _wireStyles(); } };
  const b = document.getElementById('st-bright'), a = document.getElementById('st-any');
  if (b) b.onclick = () => { if (!_auto.autopilot) setStyles([...BRIGHT_STYLES]); };
  if (a) a.onclick = () => { if (!_auto.autopilot) setStyles([]); };
  document.querySelectorAll('#id-styles input[data-style]').forEach(e => e.onchange = () => {
    _auto.styles = [...document.querySelectorAll('#id-styles input[data-style]:checked')].map(x => x.dataset.style);
    e.closest('.id-chip').classList.toggle('on', e.checked);
    _persist();
  });
}

async function _refreshAuto() {             // queues, schedule and new ideas written while this screen is open
  try {
    _ap = await call('/autopilot'); _apAt = Date.now() / 1000;
    if (!document.getElementById('id-auto')) return;
    const keep = document.activeElement && document.activeElement.closest && document.activeElement.closest('#id-auto');
    if (!keep) _drawAuto();
    const list = await call('');
    if (list.length !== _ideas.length || list.some((i, k) => _ideas[k] && (i.status !== _ideas[k].status || i.updated_at !== _ideas[k].updated_at))) {
      _ideas = list; _render();
    }
    const j = await call('/run');
    if (j.state === 'running' && !(_job && _job.state === 'running' && _pollGen)) { _job = j; _poll(); }
    else if (j.state !== 'running' && _job && _job.state === 'running') { _job = j; _renderProg(); }
  } catch(e) { /* a hiccup: next tick */ }
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

function pubPanel(idea) {
  const p = idea.publish;
  if (!p) return '';
  const field = (label, key, text, rows) => `<div class="id-section"><div class="row"><h5 style="margin:0">${label}</h5><span class="sp"></span><button class="small" onclick="idCopy('${idea.id}','${key}')">Copy</button></div>
    ${rows ? `<textarea rows="${rows}" readonly>${esc(text)}</textarea>` : `<input value="${esc(text)}" readonly>`}</div>`;
  return `<div class="id-expand id-pub">
    ${p.stale ? '<div class="id-why">The narration changed after this was written. Open the short and write it again.</div>' : ''}
    ${field('Title (' + p.title.length + ' characters)', 'title', p.title, 0)}
    ${field('Description', 'description', p.description, 10)}
    ${field('Tags', 'tags_text', p.tags_text, 3)}
    <div class="id-actions"><button class="small primary" onclick="idCopy('${idea.id}','all')">Copy title + description</button></div>
  </div>`;
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
  if ((idea.status === 'queued' || idea.status === 'done') && idea.short_id)
    actions.push(`<a class="btn small" href="#/short/${idea.short_id}">Open short →</a>`);
  if (idea.status === 'done')
    actions.push(`<button class="small ${idea.reviewed ? '' : 'primary'}" onclick="idReviewed('${idea.id}', ${idea.reviewed ? 'false' : 'true'})">${idea.reviewed ? 'Reviewed ✓ (undo)' : 'Mark reviewed'}</button>`);
  if (idea.status !== 'queued')
    actions.push(`<button class="small bad" onclick="idDelete('${idea.id}')">Delete</button>`);
  if (idea.status === 'done')
    actions.push(idea.publish
      ? `<button class="small link" onclick="idToggle('${idea.id}','pub')">${exp==='pub'?'Hide upload text':'Upload text'}${idea.publish.stale ? ' (outdated)' : ''}</button>`
      : `<button class="small" ${busy?'disabled':''} onclick="idWritePub('${idea.id}')">${busy?'<span class="spin"></span> Writing…':'Write upload text'}</button>`);
  if (hasSc) actions.push(`<button class="small link" onclick="idToggle('${idea.id}','score')">${exp==='score'?'Hide score':'Score detail'}</button>`);
  if (hasCo) actions.push(`<button class="small link" onclick="idToggle('${idea.id}','cond')">${exp==='cond'?'Hide brief':'View brief'}</button>`);

  const statusKey = idea.status==='queued'?'queued':idea.status==='done'?'done':idea.status==='conditioned'?'info':idea.status==='approved'?'done':idea.status==='rejected'?'error':'';
  const expandPanel = exp === 'score' ? scorePanel(idea) : exp === 'cond' ? condPanel(idea) : exp === 'pub' ? pubPanel(idea) : '';

  const fresh = _job && _job.new_ids && _job.new_ids.includes(idea.id) && _job.state === 'running';
  return `<div class="id-card id-${idea.status}${fresh ? ' id-new' : ''}" id="card-${idea.id}">
    <div class="id-hook" onclick="idToggle('${idea.id}','${defaultExp}')">${esc(idea.hook)}</div>
    <div class="id-mech">${mechBadges(idea.mechanisms)}</div>
    <div class="row" style="gap:8px;flex-wrap:wrap">
      ${badge(statusKey, idea.status)}
      ${idea.auto && idea.status !== 'rejected' ? '<span class="badge">auto-approved</span>' : ''}${idea.style ? `<span class="badge">${esc(idea.style)}</span>` : ''}
      ${idea.engagement_score ? `<span class="id-score ${scoreClass(idea.engagement_score)}">★ ${idea.engagement_score.toFixed(1)}</span>` : ''}
      ${busy ? '<span class="mute small"><span class="spin"></span> working…</span>' : ''}
    </div>
    ${idea.premise ? `<p class="small mute" style="margin:6px 0 0">${esc(idea.premise)}</p>` : ''}
    ${(idea.sources || []).length ? `<div class="id-src"><span class="mute">Sources:</span> ${idea.sources.map(x => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc((x.title || x.url).slice(0, 60))}</a>`).join('')}</div>` : ''}
    ${idea.reject_reason ? `<div class="id-why">${esc(idea.reject_reason)}${idea.dup_of ? ` (<a href="javascript:void(0)" onclick="idJump('${esc(idea.dup_of)}')">see the earlier idea</a>)` : ''}</div>` : ''}
    ${(idea.cond_fails || 0) >= 2 && idea.status === 'approved' ? `<div class="id-why">The brief failed ${idea.cond_fails} times, so the autopilot skips this idea. Press Condition to try again.</div>` : ''}
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

window.idCopy = (id, key) => {
  const p = (_ideas.find(i => i.id === id) || {}).publish;
  if (!p) return;
  const text = key === 'all' ? p.title + '\n\n' + p.description : p[key];
  navigator.clipboard.writeText(text).then(() => toast('Copied'), () => toast('Copy failed: select the text and copy it', {bad:true}));
};

window.idWritePub = async id => {
  const idea = _ideas.find(i => i.id === id);
  if (!idea || !idea.short_id) return;
  _busy.add(id); _render();
  try {
    await api('/shorts/' + idea.short_id + '/publish', {method:'POST', json:{}});
    _ideas = await call('');
    _exp[id] = 'pub';
    toast('Upload text written');
  } catch(e) { toast(e.message, {bad:true}); }
  _busy.delete(id); _render();
};

window.idReviewed = async (id, reviewed) => {
  try {
    const r = await call(`/${id}/reviewed`, {method:'POST', json:{reviewed}});
    _ideas = _ideas.map(i => i.id === id ? r : i);
    _render(); _refreshAuto();
  } catch(e) { toast(e.message, {bad:true}); }
};

window.idJump = id => {
  _tab = 'all'; _render();
  const el = document.getElementById('card-' + id);
  if (el) { el.scrollIntoView({behavior:'smooth', block:'center'}); el.classList.add('id-new'); }
};

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
  _syncCfgLock();
}

// ── main view ─────────────────────────────────────────────────────────────────

window.viewIdeas = async function() {
  _loadState();
  document.getElementById('app').innerHTML = `
    <div class="id-header">
      <h2 style="margin:0">Short Ideas</h2>
      <span class="mute small">Park · Rate · Approve · Condition · Queue</span>
      <span class="sp"></span>
      <select id="id-n" style="width:90px">
        <option value="5"${_n===5?' selected':''}>5 ideas</option>
        <option value="7"${_n===7?' selected':''}>7 ideas</option>
        <option value="10"${_n===10?' selected':''}>10 ideas</option>
      </select>
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none" title="Diverse: splits ideas across 5 domain lenses (military, science, economics, Indian history, engineering) for variety, then auto-rates">
        <input type="checkbox" id="id-diverse" ${_diverse ? 'checked' : ''}>
        <span class="small">Diverse</span>
      </label>
      <button class="primary" id="id-gen">Generate</button>
      <button id="id-rate">Rate all</button>
      <button onclick="location.hash='#/shorts'">← Shorts</button>
    </div>
    <div id="id-prog"></div>
    <div class="id-auto" id="id-auto"></div>
    <div class="id-board" id="id-board"></div>
    <div class="id-cfg" id="id-cfg">${_cfgHtml()}</div>
    <div class="id-tabs" id="id-tabs"></div>
    <div id="id-list"><div class="pad"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div></div>`;

  _wireCfg();
  _drawAuto();
  clearInterval(_apTimer);
  const mine = route_id;
  _apTimer = setInterval(() => { if (mine !== route_id || !document.getElementById('id-auto')) { clearInterval(_apTimer); return; } _refreshAuto(); }, 15000);

  document.getElementById('id-diverse').onchange = e => { _diverse = e.target.checked; _persist(); };
  document.getElementById('id-n').onchange = e => { _n = parseInt(e.target.value) || 7; _persist(); };

  document.getElementById('id-gen').onclick = async () => {
    const n = parseInt(document.getElementById('id-n').value) || 7;
    const diverse = document.getElementById('id-diverse').checked;
    try {
      _job = await call('/generate', {method:'POST', json:{n, diverse}});
      _tab = 'pending';
      _poll();
    } catch(e) { toast(e.message, {bad:true}); }
  };

  document.getElementById('id-rate').onclick = async () => {
    try { _job = await call('/rate', {method:'POST', json:{ids:[]}}); _poll(); }
    catch(e) { toast(e.message, {bad:true}); }
  };

  let cfg;
  [_ideas, _options, cfg, _job] = await Promise.all([
    call('').catch(() => []),
    api('/shorts/options').catch(() => null),
    call('/config').catch(() => null),
    call('/run').catch(() => null),
  ]);
  _applyServerCfg(cfg);
  document.getElementById('id-n').value = String(_n);
  document.getElementById('id-diverse').checked = _diverse;
  // Re-render config panel now that we have live voices/languages
  const cfgEl = document.getElementById('id-cfg');
  if (cfgEl) { cfgEl.innerHTML = _cfgHtml(); _wireCfg(); _wireStyles(); }
  _drawAuto();
  _refreshAuto();
  _seen = new Set(_ideas.map(i => i.id));
  _render();
  _renderProg();
  if (_job && _job.state === 'running') _poll();      // a run that was started before you left is still going: pick it up
};

// ── background run: progress and ideas as they are written ───────────────────

function _renderProg() {
  const el = document.getElementById('id-prog');
  const gen = document.getElementById('id-gen'), rate = document.getElementById('id-rate');
  if (!el) return;
  const j = _job, running = !!(j && j.state === 'running');
  if (gen) { gen.disabled = running; gen.innerHTML = running && j.kind === 'generate' ? '<span class="spin"></span> Generating…' : 'Generate'; }
  if (rate) { rate.disabled = running; rate.innerHTML = running && j.kind === 'rate' ? '<span class="spin"></span> Rating…' : 'Rate all'; }
  if (!j || j.state === 'idle' || (j.state === 'done' && !_showDone)) { el.innerHTML = ''; return; }
  const pct = j.total ? Math.min(100, Math.round(100 * j.done / j.total)) : 0;
  const made = (j.new_ids || []).length;
  const eta = running && j.eta_s ? ` · about ${hd(j.eta_s)} left` : '';
  if (running) {
    el.innerHTML = `<div class="id-prog"><div class="id-prog-top"><span class="spin"></span><span>${esc(j.label || 'working')}</span><span class="sp"></span><span class="mute small">${made ? made + ' ideas so far' : ''}${eta} · ${hd(j.elapsed_s || 0)}</span></div><div class="id-prog-bar"><i style="width:${Math.max(4, pct)}%"></i></div><div class="mute small" style="margin-top:6px">You can leave this screen: the run keeps going on the server.</div></div>`;
  } else if (j.state === 'error') {
    el.innerHTML = `<div class="id-prog bad"><div class="id-prog-top"><span>Run failed: ${esc(j.error)}</span></div></div>`;
  } else {
    el.innerHTML = `<div class="id-prog"><div class="id-prog-top"><span>${esc(j.note || 'Finished')}</span>${j.error ? `<span class="bad small">${esc(j.error)}</span>` : ''}</div></div>`;
  }
}
let _showDone = false;

async function _poll() {
  const gen = ++_pollGen, my = route_id;
  _showDone = true;
  while (gen === _pollGen && my === route_id && document.getElementById('id-prog')) {
    try {
      const [j, list] = await Promise.all([call('/run'), call('')]);
      if (gen !== _pollGen || my !== route_id) return;
      const was = _job && _job.state;
      _job = j;
      const byId = new Map(list.map(i => [i.id, i]));
      _ideas = list.sort((a, b) => (b.engagement_score || 0) - (a.engagement_score || 0) || b.created_at - a.created_at);
      const fresh = list.filter(i => !_seen.has(i.id));
      fresh.forEach(i => _seen.add(i.id));
      _render(); _renderProg();
      if (j.state !== 'running') {
        if (j.state === 'done') toast(j.note || 'Finished');
        else if (j.state === 'error') toast(j.error, {bad:true});
        return;
      }
    } catch(e) { /* a hiccup: try again */ }
    await new Promise(r => setTimeout(r, 2000));
  }
}

})();
