/* YouTube analytics: connect the channel, see how each idea performed. Uses the helpers of index.html ($, api, esc, act, toast, dialog, badge). */
(() => {
const num = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0);
const when = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'}) : '';
const ago = ts => { const s = Date.now() / 1000 - ts; return s < 90 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : s < 86400 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' d ago'; };
let D = null, poll = null, tab = 'performance';

window.viewYoutube = async function () {
  clearTimeout(poll);
  const q = new URLSearchParams((location.hash.split('?')[1]) || '');
  $('#app').innerHTML = `<div class="mute small"><a href="#/shorts">Shorts</a> /</div><h2 style="margin-top:4px">YouTube analytics</h2>
    ${q.get('error') ? `<div class="errbox">YouTube sign-in failed: ${esc(q.get('error'))}</div>` : ''}
    <div id="yt-body"><div class="skel"></div></div>`;
  await load();
};

async function load() {
  const body = document.getElementById('yt-body');
  if (!body) return;
  try { D = await api('/youtube/performance'); } catch (e) { body.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; return; }
  draw(body);
  const run = D.status.sync.running;
  clearTimeout(poll);
  if (run && tab !== 'learn') poll = setTimeout(() => { if (location.hash.startsWith('#/youtube')) load(); }, 3000);
}

function connectCard(s) {
  if (!s.configured) return `<div class="card pad"><b>Not set up yet.</b><p class="small mute">Add <code>YT_CLIENT_ID</code>, <code>YT_CLIENT_SECRET</code> and <code>YT_REDIRECT_URI</code> to <code>.env</code> and restart the app.</p></div>`;
  const msg = s.broken ? `<div class="errbox">${esc(s.broken)}</div>` : '';
  return `<div class="card pad">${msg}<div class="row"><div><b>YouTube is not connected</b><div class="small mute">Read-only: views, watch time, likes and comments of your channel. Nothing is posted or changed.</div>
    <div class="small mute">Open this page at <b>${esc(location.origin)}</b> to match the redirect address <code>${esc(s.redirect_uri)}</code>.</div></div><span class="sp"></span>
    <a class="btn primary" href="/api/youtube/connect">Connect YouTube</a></div></div>`;
}

function tiles(d) {
  const t = (label, v) => `<div class="card pad" style="min-width:130px"><div class="mute small">${label}</div><div style="font-size:22px;font-weight:700">${v}</div></div>`;
  return `<div class="row" style="gap:10px;flex-wrap:wrap">${t('Videos on channel', d.videos)}${t('Linked to an idea', d.linked)}${t('Views of linked', num(d.views))}${t('Best 7-day views', num(Math.max(0, ...d.rows.filter(r => r.v7_done).map(r => r.v7))))}</div>`;
}

function groupTable(title, list) {
  if (!list.length) return '';
  const top = Math.max(...list.map(g => g.avg_v7), 1);
  return `<div class="card pad" style="flex:1;min-width:230px"><b class="small">${title}</b><table class="mt-s"><tbody>${list.map(g =>
    `<tr><td>${esc(g.key)}</td><td style="width:45%"><div style="height:8px;border-radius:4px;background:var(--accent);width:${Math.max(4, Math.round(100 * g.avg_v7 / top))}%"></div></td><td style="text-align:right"><b>${num(g.avg_v7)}</b></td><td class="mute small">${g.n}×</td></tr>`).join('')}</tbody></table></div>`;
}

function win(r, n) {
  const v = r['v' + n];
  return r['v' + n + '_done'] ? `<b>${num(v)}</b>` : (r.has_days ? `<span class="mute" title="Still counting: YouTube reports a day or two late">${num(v)}…</span>` : '<span class="mute">–</span>');
}

function rowsTable(d) {
  if (!d.rows.length) return `<div class="card pad mute">No video is linked to an idea yet. Videos are linked by title when a short's upload title matches; link the others below.</div>`;
  return `<div class="card" style="overflow:auto"><table><thead><tr><th>Idea / video</th><th>Score</th><th style="text-align:right">Views</th><th style="text-align:right">2 days</th><th style="text-align:right">7 days</th><th style="text-align:right">28 days</th>
    <th style="text-align:right">Watched</th><th style="text-align:right">Likes</th><th style="text-align:right">Comments</th><th style="text-align:right">Subs</th><th></th></tr></thead><tbody>
    ${d.rows.map(r => `<tr><td style="max-width:340px"><a href="https://youtube.com/shorts/${esc(r.video_id)}" target="_blank" rel="noopener"><b>${esc(r.title)}</b></a>
      <div class="mute small">${esc((r.hook || '').slice(0, 90))}</div><div class="mute small">${when(r.published_at)}${r.style ? ' · ' + esc(r.style) : ''}${r.tone ? ' · ' + esc(r.tone) : ''}${r.how === 'manual' ? ' · linked by hand' : ''}</div></td>
      <td>${r.score ? '★ ' + r.score.toFixed(1) : '–'}</td><td style="text-align:right"><b>${num(r.views)}</b></td>
      <td style="text-align:right">${win(r, 2)}</td><td style="text-align:right">${win(r, 7)}</td><td style="text-align:right">${win(r, 28)}</td>
      <td style="text-align:right" title="Average share of the video watched">${r.has_days ? r.avg_view_pct + '%' : '–'}</td><td style="text-align:right">${num(r.likes)}</td><td style="text-align:right">${num(r.comments)}</td><td style="text-align:right">${r.has_days ? num(r.subs) : '–'}</td>
      <td><a href="#/short/${esc(r.short_id)}" class="small">short</a> <button class="small link" data-unlink="${esc(r.video_id)}">unlink</button></td></tr>`).join('')}</tbody></table></div>`;
}

function unlinkedBox(d) {
  if (!d.unlinked.length) return '';
  const opts = d.targets.map(t => `<option value="${esc(t.short_id)}">${esc((t.title || t.short_id).slice(0, 70))}</option>`).join('');
  return `<h4 class="mt">Videos not linked to an idea</h4><div class="card pad"><div class="mute small">Pick the short each video came from. Shorts whose upload title matches are linked by themselves on the next sync.</div>
    <table class="mt-s"><tbody>${d.unlinked.map(v => `<tr><td><a href="https://youtube.com/shorts/${esc(v.video_id)}" target="_blank" rel="noopener">${esc(v.title)}</a><div class="mute small">${when(v.published_at)} · ${num(v.views)} views</div></td>
      <td style="width:260px"><select data-pick="${esc(v.video_id)}"><option value="">Link to short…</option>${opts}</select></td></tr>`).join('')}</tbody></table></div>`;
}

function draw(body) {
  const s = D.status, sy = s.sync;
  if (!s.connected) { body.innerHTML = connectCard(s); return; }
  const last = sy.last;
  const note = sy.running ? `<span class="mute small"><span class="spin"></span> ${esc(sy.note || 'Syncing…')}</span>`
    : sy.error ? `<span class="bad small">${esc(sy.error)}</span>` : last ? `<span class="mute small">Synced ${ago(last.at)}: ${last.videos} videos${last.analytics_failed ? `, daily numbers failed for ${last.analytics_failed} (${esc(last.analytics_error)})` : ''}</span>` : '';
  const g = D.groups;
  const header = `<div class="row" style="gap:10px;flex-wrap:wrap"><b>${esc(s.channel || 'Channel')}</b>${badge('good', 'connected')}${note}<span class="sp"></span>
      <button class="small primary" id="yt-sync" ${sy.running ? 'disabled' : ''}>Sync now</button><button class="small bad" id="yt-off">Disconnect</button></div>
    <div class="row mt-s" style="gap:6px"><button class="small ${tab === 'performance' ? 'primary' : ''}" id="yt-t-perf">Performance</button><button class="small ${tab === 'learn' ? 'primary' : ''}" id="yt-t-learn">Learn: what works</button></div>`;
  const perf = `<div class="mt">${tiles(D)}</div>
    <h4 class="mt">What works <span class="mute small">average views in the first 7 days, videos with 7 complete days (${g.n})</span></h4>
    ${g.n ? `<div class="row" style="gap:10px;flex-wrap:wrap;align-items:stretch">${groupTable('Idea score', g.score)}${groupTable('Picture style', g.style)}${groupTable('Tone', g.tone)}${groupTable('Attention mechanism', g.mechanism)}</div>` : '<div class="card pad mute">Shows up once a linked video is more than 9 days old.</div>'}
    <h4 class="mt">Ideas on the channel</h4>${rowsTable(D)}${unlinkedBox(D)}`;
  body.innerHTML = header + (tab === 'learn' ? '<div id="yt-learn" class="mt"></div>' : perf);
  document.getElementById('yt-t-perf').onclick = () => { tab = 'performance'; draw(body); };
  document.getElementById('yt-t-learn').onclick = () => { tab = 'learn'; draw(body); };
  if (tab === 'learn') window.mountLearn(document.getElementById('yt-learn'));
  document.getElementById('yt-sync').onclick = async b => { await act(b.currentTarget, () => api('/youtube/sync', {method: 'POST'})); load(); };
  document.getElementById('yt-off').onclick = async () => {
    const ok = await dialog({title: 'Disconnect YouTube?', html: '<p>The saved sign-in is removed and Google is told to revoke it. Numbers already pulled stay.</p>', buttons: [{label: 'Cancel', value: false}, {label: 'Disconnect', value: true, danger: true}]});
    if (ok === true) { await act(null, () => api('/youtube/disconnect', {method: 'POST'})); load(); }
  };
  body.querySelectorAll('[data-unlink]').forEach(b => b.onclick = async () => { await act(b, () => api('/youtube/link/' + b.dataset.unlink, {method: 'DELETE'})); load(); });
  body.querySelectorAll('[data-pick]').forEach(sel => sel.onchange = async () => {
    if (!sel.value) return;
    await act(null, () => api('/youtube/link', {method: 'POST', json: {short_id: sel.value, video: sel.dataset.pick}}));
    load();
  });
}
})();
