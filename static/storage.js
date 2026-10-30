/* Settings → Storage: free disk space, only when asked. Lists every long-form project, short and character with the space its media uses and lets the admin remove folders, superseded attempts
   or everything for one project. Uses the helpers of index.html ($, api, esc, act, toast, dialog, badge). */
(() => {
const gb = b => b >= 1073741824 ? (b / 1073741824).toFixed(2) + ' GB' : b >= 1048576 ? (b / 1048576).toFixed(0) + ' MB' : b >= 1024 ? (b / 1024).toFixed(0) + ' KB' : b + ' B';
const KIND = {long: 'Long story', short: 'Short', character: 'Character', special: 'Library'};
let DATA = null;

window.mountStorage = async function () {
  const el = document.getElementById('storage-card');
  if (!el) return;
  el.innerHTML = `<div class="card pad mt"><h4 style="margin-top:0">Storage</h4><div class="mute small">Measuring what each project uses…</div></div>`;
  try { DATA = await api('/storage'); } catch (e) { el.innerHTML = `<div class="card pad mt"><h4 style="margin-top:0">Storage</h4><div class="errbox">${esc(e.message)}</div></div>`; return; }
  draw(el);
};

function draw(el) {
  const d = DATA;
  el.innerHTML = `<div class="card pad mt"><div class="row"><h4 style="margin:0">Storage</h4><span class="sp"></span><button class="small" id="st-refresh">Measure again</button></div>
    <p class="mute small">Media of each project, measured now. Nothing is removed unless you press a button and confirm. A project's text, plan, approvals and exports always stay; the pictures, voice, clips and videos removed here can be made again.</p>
    <div class="row small" style="gap:18px"><span><b>${gb(d.media_bytes)}</b> in media</span><span>Disk: <b>${gb(d.disk_free)}</b> free of ${gb(d.disk_total)}</span></div>
    <table class="mt"><thead><tr><th>Project</th><th>Type</th><th style="text-align:right">Space</th><th>What uses it</th><th></th></tr></thead><tbody>
    ${d.projects.map(p => `<tr><td><b>${esc(p.title)}</b>${p.orphan ? ' ' + badge('warn', 'project no longer exists') : ''}${p.running ? ' ' + badge('queued', 'running') : ''}<div class="mute small">${esc(p.id)}${p.status ? ' · ' + esc(p.status) : ''}</div></td>
      <td>${esc(KIND[p.kind] || p.kind)}</td><td style="text-align:right"><b>${gb(p.bytes)}</b></td>
      <td class="small mute">${p.folders.filter(f => f.bytes > 1048576).map(f => esc(f.name) + ' ' + gb(f.bytes)).join(' · ') || '—'}</td>
      <td><button class="small" data-free="${esc(p.id)}" ${p.running ? 'disabled' : ''}>Free space…</button></td></tr>`).join('') || '<tr><td colspan="5" class="mute">No media on disk.</td></tr>'}</tbody></table>
    ${d.other.length ? `<h4>Test output</h4><table><tbody>${d.other.map(o => `<tr><td>${esc(o.label)}<div class="mute small">data/${esc(o.key)}${o.keeps.length ? ' · keeps ' + esc(o.keeps.join(', ')) : ''}</div></td><td style="text-align:right"><b>${gb(o.bytes)}</b></td>
      <td><button class="small" data-other="${esc(o.key)}" ${o.bytes ? '' : 'disabled'}>Empty</button></td></tr>`).join('')}</tbody></table>` : ''}</div>`;
  document.getElementById('st-refresh').onclick = () => window.mountStorage();
  el.querySelectorAll('[data-free]').forEach(b => b.onclick = () => freeDialog(DATA.projects.find(p => p.id === b.dataset.free)));
  el.querySelectorAll('[data-other]').forEach(b => b.onclick = () => runOther(b.dataset.other));
}

async function confirmAndRun(title, body, what) {
  const dry = await api('/storage/clear', {method: 'POST', json: {...body, dry_run: true}}).catch(e => { toast(e.message, {bad: true}); return null; });
  if (!dry) return false;
  if (!dry.freed_bytes) { toast('Nothing to remove there.'); return false; }
  const ok = await dialog({title, html: `<p>${what}</p><p><b>${gb(dry.freed_bytes)}</b> in ${dry.files} file${dry.files === 1 ? '' : 's'} will be removed. This cannot be undone.</p>`,
    buttons: [{label: 'Cancel', value: false}, {label: 'Remove', value: true, danger: true}]});
  if (ok !== true) return false;
  const r = await act(null, () => api('/storage/clear', {method: 'POST', json: {...body, dry_run: false}}));
  if (r) toast(`Freed ${gb(r.freed_bytes)}`);
  return !!r;
}

async function freeDialog(p) {
  const html = `<div class="small mute">${esc(KIND[p.kind] || p.kind)} · ${esc(p.id)} · ${gb(p.bytes)} on disk</div>
    <div class="mt-s"><b class="small">Remove chosen folders</b>
    ${p.folders.map(f => `<label class="row small" style="gap:8px;margin:4px 0"><input type="checkbox" data-f="${esc(f.name)}"><span style="flex:1">${esc(f.label)} <span class="mute">(${esc(f.name)}, ${f.files} files)</span>${f.irreplaceable ? ` ${badge('warn', 'cannot be made again')}` : ''}</span><b>${gb(f.bytes)}</b></label>`).join('') || '<div class="mute small">no folders</div>'}</div>
    <div class="row mt-s" style="gap:8px;flex-wrap:wrap"><button id="fd-folders" class="small">Remove ticked folders</button>
      <button id="fd-older" class="small" ${p.older_count ? '' : 'disabled'} title="Keeps the approved (or newest) picture, take or clip of each; removes older and failed attempts">Remove older attempts only${p.older_count ? ` (${gb(p.older_bytes)}, ${p.older_count})` : ''}</button>
      <button id="fd-all" class="small bad">Remove all media of this project</button></div>
    <p class="mute small mt-s">${p.kind === 'character' ? 'Removing a character\'s pictures also removes its canon and looks if their pictures go; the character stays in the library and can be drawn again.' : 'The project stays; its steps show as not made yet.'}</p>`;
  const layer = dialog({title: p.title, html, buttons: [{label: 'Close', value: null, primary: true}]});
  setTimeout(() => {
    const done = async ok => { if (ok) { document.querySelector('.dlg')?.remove(); await window.mountStorage(); } };
    const q = id => document.getElementById(id);
    q('fd-folders').onclick = async () => {
      const folders = [...document.querySelectorAll('[data-f]:checked')].map(e => e.dataset.f);
      if (!folders.length) { toast('Tick at least one folder', {bad: true}); return; }
      const hard = p.folders.filter(f => folders.includes(f.name) && f.irreplaceable).map(f => f.label);
      await done(await confirmAndRun('Remove folders', {project: p.id, mode: 'folders', folders}, `Remove ${folders.join(', ')} of “${esc(p.title)}”.` + (hard.length ? ` <b>${esc(hard.join(', '))} cannot be made again by the app.</b>` : '')));
    };
    q('fd-older').onclick = async () => done(await confirmAndRun('Remove older attempts', {project: p.id, mode: 'older'}, `Keep the approved (or newest) picture, take and clip of “${esc(p.title)}” and remove every older or failed attempt.`));
    q('fd-all').onclick = async () => done(await confirmAndRun('Remove all media', {project: p.id, mode: 'all'}, `Remove every picture, voice take, clip and video of “${esc(p.title)}”, including files you uploaded for it.`));
  }, 50);
  await layer;
}

async function runOther(key) {
  const dry = await api('/storage/other', {method: 'POST', json: {key, dry_run: true}}).catch(e => { toast(e.message, {bad: true}); return null; });
  if (!dry || !dry.freed_bytes) { toast('Nothing to remove there.'); return; }
  const ok = await dialog({title: 'Empty test output', html: `<p>Remove ${dry.files} files (${gb(dry.freed_bytes)}) from data/${esc(key)}? The timing file the estimates use is kept.</p>`, buttons: [{label: 'Cancel', value: false}, {label: 'Empty', value: true, danger: true}]});
  if (ok !== true) return;
  const r = await act(null, () => api('/storage/other', {method: 'POST', json: {key, dry_run: false}}));
  if (r) { toast(`Freed ${gb(r.freed_bytes)}`); window.mountStorage(); }
}
})();
