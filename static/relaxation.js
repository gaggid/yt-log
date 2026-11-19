/* Relaxation Rain Channel — #/relaxation
   Called directly from index.html router as showRelaxation(). */
var showRelaxation = (function () {

  /* ── API helpers ─────────────────────────────────────────────────────────── */
  async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) {
      const j = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(j.detail || r.statusText);
    }
    return r.json();
  }

  const STEP_LABELS = {
    scene: '1. Room image',
    rain: '2. Rain drawn over the picture (4K)',
    thumbnail: 'New thumbnail',
    music: 'New music (4 takes, then the sound is swapped into the video: about 10 minutes)',
    upscale: '3. 2K upscale (old sessions)',
    audio: '4. Audio mix',
    video: '5. 3-hour video',
    publish: '6. Metadata',
  };

  const STATUS_CLASS = {
    new: '', running: 'b-running', ready: 'b-done', uploading: 'b-busy',
    uploaded: 'b-approved', failed: 'b-error',
  };

  /* ── polling ─────────────────────────────────────────────────────────────── */
  let _pollTimer = null;
  let _activeId = null;

  function startPoll(id, onUpdate) {
    _activeId = id;
    clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      try {
        const j = await api('GET', `/api/relaxation/${id}/run`);
        onUpdate(j);
        if (j.state === 'done' || j.state === 'error' || j.state === 'cancelled') {
          clearInterval(_pollTimer);
          _pollTimer = null;
        }
      } catch (e) { /* ignore transient errors */ }
    }, 2000);
  }

  /* ── render helpers ──────────────────────────────────────────────────────── */
  function badge(status) {
    return `<span class="badge ${STATUS_CLASS[status] || ''}">${status}</span>`;
  }

  // Posting to YouTube: a bar with the megabytes sent, the percent and the time left (from the upload job; before it is known, a plain note)
  function uploadBox(s) {
    const j = s._job && s._job.kind === 'yt_upload' ? s._job : null;
    if (!j || !j.total) return `<div class="small mt-s">Posting to YouTube: starting<span class="spin"></span></div>`;
    const pct = Math.min(100, Math.round(100 * j.done / j.total));
    const mb = x => Math.round(x / 1048576).toLocaleString();
    const eta = j.eta_s ? ` · about ${Math.max(1, Math.round(j.eta_s / 60))} min left` : '';
    return `<div class="mt-s"><div class="small">Posting to YouTube: <b>${pct}%</b> · ${mb(j.done)} of ${mb(j.total)} MB${eta} <span class="spin"></span></div>
      <div style="height:8px;background:var(--border,#30363d);border-radius:4px;margin-top:4px;max-width:420px"><div style="height:8px;width:${pct}%;background:var(--good,#3fb950);border-radius:4px"></div></div></div>`;
  }

  function stepDots(s) {
    const steps = ['scene', 'rain', 'audio', 'video', 'publish'];
    return steps.map(k => {
      const done = s[`${k === 'scene' ? 'scene' : k === 'final' ? 'final' : k}_ready`] ||
                   s[k + '_ready'] || false;
      const active = s.step === k;
      const cls = active ? 'running' : (done ? 'done' : '');
      return `<span class="dot ${cls}" title="${STEP_LABELS[k] || k}"></span>`;
    }).join('');
  }

  const watching = new Map();       // session id -> seconds played; kept across the page's redraws so a playing video is not lost

  /* ── session card ──────────────────────────────────────────────────────────*/
  function sessionCard(s, onAction) {
    const pub = s.publish || {};
    const ytId = s.youtube_video_id || '';
    const finalReady = s.final_ready;
    const hasMetadata = !!pub.title;

    return `
<div class="card pad mb" data-id="${s.id}">
  <div class="row">
    <div>
      <strong>${s.title || s.id}</strong>
      ${(s.settings && s.settings.music_plan) ? `<span class="mute small" style="margin-left:8px">${s.settings.music_plan.instrument}, ${s.settings.music_plan.mood}, ${s.settings.music_plan.bpm} BPM</span>` : ''}
      <span style="margin-left:8px">${badge(s.status)}</span>
      <span style="margin-left:8px">${stepDots(s)}</span>
    </div>
    <span class="sp"></span>
    <button class="small bad" data-action="delete" data-id="${s.id}">Delete</button>
  </div>

  ${s.error ? `<div class="errbox mt-s">${s.error}</div>` : ''}
  ${s.rain_weak ? `<div class="errbox mt-s">The rain does not fall properly in this video (${Math.round((s.rain_motion.streak_same || 0) * 100)}% of the streaks stay in the same place; a good clip is under 85%).</div>` : ''}
  ${s.music_error ? `<div class="errbox mt-s">The video has rain only: the music could not be made (${s.music_error}). Use "New music".</div>` : ''}
  ${s.step ? `<div class="small mute mt-s">Working: ${STEP_LABELS[s.step] || s.step}${s._job && s._job.label ? ' — ' + s._job.label + (s._job.elapsed_s ? ' (' + Math.round(s._job.elapsed_s / 60) + ' min so far)' : '') : ''} <span class="spin"></span></div>` : ''}
  ${s.status === 'uploading' ? uploadBox(s) : ''}
  ${s._done ? `<div class="small mt-s" style="color:var(--good,#3fb950)">${s._done}</div>` : ''}

  ${s.video_removed ? `<div class="small mute mt-s">Posted to YouTube; the local video file was removed to free disk.</div>` : ''}
  ${s.thumb_url || s.scene_url ? `<img src="${s.thumb_url || s.scene_url}" style="max-width:320px;border-radius:8px;margin-top:10px;display:block" alt="${s.thumb_url ? 'YouTube thumbnail' : 'scene preview'}">` : ''}

  <div class="row mt">
    ${s.status === 'new' || s.status === 'failed'
      ? `<button class="primary" data-action="run" data-id="${s.id}">Generate</button>`
      : s.status === 'running'
      ? `<button disabled>Running <span class="spin"></span></button>`
      : ''}
    ${finalReady && !hasMetadata
      ? `<button data-action="metadata" data-id="${s.id}">Write metadata</button>` : ''}
    ${finalReady && hasMetadata && !ytId
      ? (s.youtube_ready
          ? `<button class="good" data-action="upload" data-id="${s.id}">Post to ${s.youtube_channel_name || 'YouTube'}</button>`
          : `<span class="small mute">Not connected to ${s.youtube_channel_name || 'the rain channel'}: <a href="#/youtube">connect it on the YouTube page</a>.</span>`) : ''}
    ${ytId
      ? `<a href="https://youtu.be/${ytId}" target="_blank" class="btn">View on YouTube ↗</a>` : ''}
    ${finalReady
      ? `<button class="small" data-action="watch" data-id="${s.id}">${watching.has(s.id) ? 'Hide player' : 'Watch'}</button>
         <a href="/api/relaxation/${s.id}/download" class="btn small">Download</a>` : ''}
    ${finalReady && s.status !== 'running'
      ? `<button class="small" data-action="thumb" data-id="${s.id}" data-person="woman" title="Draw the thumbnail again with a happy woman by the rainy window">New thumbnail: woman</button>
         <button class="small" data-action="thumb" data-id="${s.id}" data-person="man" title="Draw the thumbnail again with a happy man by the rainy window">New thumbnail: man</button>` : ''}
    ${(s.audio_ready || finalReady) && s.status !== 'running'
      ? `<button class="small" data-action="music" data-id="${s.id}" data-instrument="" title="Same instrument, a new take">New music</button>
         <button class="small" data-action="music" data-id="${s.id}" data-instrument="other" title="Another instrument of this theme">New music, other instrument</button>` : ''}
  </div>
  ${finalReady && watching.has(s.id) && s.stream_url ? `<video class="rl-player" data-id="${s.id}" src="${s.stream_url}" controls preload="metadata" style="width:100%;max-width:960px;margin-top:10px;border-radius:8px;background:#000"></video><div class="small mute">Plays straight from the server; drag the bar to jump anywhere in the 3 hours.</div>` : ''}
  ${s.music_url ? `<div class="mt-s small mute">Music only: <audio controls preload="none" src="${s.music_url}" style="vertical-align:middle;height:30px"></audio></div>` : ''}

  ${hasMetadata ? `
  <details class="mt" style="font-size:13px">
    <summary style="cursor:pointer;color:var(--mute)">Metadata preview</summary>
    <div style="padding:8px 0">
      <strong>${pub.title}</strong><br>
      <span class="mute small">${(pub.description || '').substring(0, 200)}…</span><br>
      <span class="small">${(pub.tags || []).slice(0, 6).join(', ')}</span>
    </div>
  </details>` : ''}
</div>`;
  }

  /* ── main view ───────────────────────────────────────────────────────────── */
  async function showRelaxation() {
    const app = document.getElementById('app');
    app.innerHTML = '<h2>Rain Channel</h2><div class="small mute">Loading…</div>';

    let scenes = {};
    let sessions = [];
    let daily = {};

    try {
      const [sceneRes, sesRes, dailyRes] = await Promise.all([
        api('GET', '/api/relaxation/options/scenes'),
        api('GET', '/api/relaxation'),
        api('GET', '/api/relaxation/daily'),
      ]);
      daily = dailyRes || {};
      scenes = sceneRes.scenes || {};
      sessions = sesRes.sessions || [];
    } catch (e) {
      app.innerHTML = `<h2>Rain Channel</h2><div class="errbox">${e.message}</div>`;
      return;
    }

    function render() {
      document.querySelectorAll('video.rl-player').forEach(v => watching.set(v.dataset.id, v.currentTime || 0));     // keep the place when the page redraws
      const cards = sessions.length
        ? sessions.map(s => sessionCard(s)).join('')
        : '<div class="big-empty"><h2>No sessions yet</h2><p>Create one below to generate a 3-hour rain video.</p></div>';

      app.innerHTML = `
<h2>Rain Channel</h2>
<p class="mute small">Each session generates an ambient rain video (3 hours = 180 minutes by default) and posts it to YouTube.</p>

<div class="card pad mb" id="rl-daily">
  <h4>Daily run</h4>
  <div class="row">
    <label class="f"><input type="checkbox" id="rl-d-on" ${daily.enabled ? 'checked' : ''}> Make a new video every night</label>
    <label class="f">From (hour, 0-18)
      <input type="number" id="rl-d-hour" value="${daily.hour ?? 1}" min="0" max="18" style="width:70px">
    </label>
    <label class="f">Length (minutes)
      <input type="number" id="rl-d-min" value="${daily.minutes ?? 180}" min="1" max="480" style="width:90px">
    </label>
    <button id="rl-d-save">Save</button>
    <button id="rl-d-now">Make today's now</button>
  </div>
  <p class="mute small" style="margin:6px 0 0">Starts once a day, any time in the ${daily.window_h || 5} hours after the hour, when nothing else is running. A new theme, instrument and seed each time. Nothing is posted to YouTube by itself.${daily.done_today ? ' Today\'s run has started.' : ''}</p>
</div>

<div class="card pad mb">
  <h4>New session</h4>
  <div class="row">
    <label class="f">Scene
      <select id="rl-scene">
        <option value="">Next theme (automatic)</option>
        ${Object.entries(scenes).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}
      </select>
    </label>
    <label class="f">Length (minutes)
      <input type="number" id="rl-minutes" value="180" min="1" max="480" style="width:90px">
    </label>
    <button class="primary" id="rl-create">Create &amp; Generate</button>
  </div>
</div>

<div id="rl-sessions">${cards}</div>`;

      document.querySelectorAll('video.rl-player').forEach(v => {
        const t = watching.get(v.dataset.id) || 0;
        if (t > 0) v.addEventListener('loadedmetadata', () => { v.currentTime = t; }, { once: true });
      });

      document.getElementById('rl-d-save').onclick = async () => {
        try {
          daily = await api('PUT', '/api/relaxation/daily', {
            enabled: document.getElementById('rl-d-on').checked,
            hour: parseInt(document.getElementById('rl-d-hour').value) || 0,
            minutes: parseInt(document.getElementById('rl-d-min').value) || 180,
          });
          render();
        } catch (e) { alert(e.message); }
      };
      document.getElementById('rl-d-now').onclick = async () => {
        try {
          const s = await api('POST', '/api/relaxation/daily/run-now');
          sessions.unshift(s);
          render();
          runSession(s.id);
        } catch (e) { alert(e.message); }
      };

      document.getElementById('rl-create').onclick = async () => {
        const scene = document.getElementById('rl-scene').value;
        const minutes = parseInt(document.getElementById('rl-minutes').value) || 180;
        try {
          const s = await api('POST', '/api/relaxation', { scene, minutes });
          sessions.unshift(s);
          render();
          runSession(s.id);
        } catch (e) {
          alert(e.message);
        }
      };

      document.getElementById('rl-sessions').addEventListener('click', async ev => {
        const btn = ev.target.closest('[data-action]');
        if (!btn) return;
        const { action, id } = btn.dataset;

        if (action === 'delete') {
          if (!confirm('Delete this session and its files?')) return;
          try { await api('DELETE', `/api/relaxation/${id}`); } catch (e) { alert(e.message); return; }
          sessions = sessions.filter(s => s.id !== id);
          render();
          return;
        }
        if (action === 'run') { runSession(id); return; }
        if (action === 'watch') {
          if (watching.has(id)) {
            document.querySelectorAll(`video.rl-player[data-id="${id}"]`).forEach(v => { v.pause(); v.remove(); });     // before render() reads the place
            watching.delete(id);
          } else watching.set(id, 0);
          render();
          return;
        }
        if (action === 'thumb') {
          const i0 = sessions.findIndex(s => s.id === id);
          try { await api('POST', `/api/relaxation/${id}/thumbnail`, { person: btn.dataset.person || '' }); }
          catch (e) { if (!e.message.includes('running')) { alert(e.message); return; } }
          if (i0 >= 0) { sessions[i0] = { ...sessions[i0], status: 'running', step: 'thumbnail', error: '', _done: '', _job: { label: 'drawing the picture' } }; render(); }
          startPoll(id, async (job) => {
            const updated = await api('GET', `/api/relaxation/${id}`);
            const idx = sessions.findIndex(s => s.id === id);
            const finished = job.state === 'done' || job.state === 'error';
            if (idx >= 0) sessions[idx] = { ...updated, status: finished ? updated.status : 'running', step: finished ? '' : 'thumbnail', _job: finished ? null : job, _done: job.state === 'done' ? 'New thumbnail is ready (above).' : '', error: job.state === 'error' ? (job.error || updated.error) : updated.error };
            render();
          });
          return;
        }
        if (action === 'music') {
          const idx0 = sessions.findIndex(s => s.id === id);
          try { await api('POST', `/api/relaxation/${id}/music/regenerate`, { instrument: btn.dataset.instrument || '' }); }
          catch (e) { if (!e.message.includes('running')) { alert(e.message); return; } }
          if (idx0 >= 0) { sessions[idx0] = { ...sessions[idx0], status: 'running', step: 'music', error: '', _done: '', _job: { label: 'starting' } }; render(); }     // show it at once
          startPoll(id, async (job) => {
            const updated = await api('GET', `/api/relaxation/${id}`);
            const idx = sessions.findIndex(s => s.id === id);
            const finished = job.state === 'done' || job.state === 'error';
            if (idx >= 0) sessions[idx] = { ...updated, _job: finished ? null : job, _done: job.state === 'done' ? 'New music is in the video. Press Watch to listen.' : '', error: job.state === 'error' ? (job.error || updated.error) : updated.error };
            render();
          });
          return;
        }
        if (action === 'metadata') {
          btn.disabled = true;
          try {
            const pub = await api('POST', `/api/relaxation/${id}/publish`);
            const idx = sessions.findIndex(s => s.id === id);
            if (idx >= 0) { sessions[idx] = { ...sessions[idx], publish: pub }; }
            render();
          } catch (e) { alert(e.message); }
          return;
        }
        if (action === 'upload') {
          btn.disabled = true;
          try {
            await api('POST', '/api/youtube/upload-video', { session_id: id });
            followUpload(id);
          } catch (e) { alert(e.message); btn.disabled = false; }
          return;
        }
      });
    }

    async function runSession(id) {
      try {
        await api('POST', `/api/relaxation/${id}/run`);
      } catch (e) {
        if (!e.message.includes('running')) { alert(e.message); return; }
      }
      startPoll(id, async (job) => {
        try {
          const updated = await api('GET', `/api/relaxation/${id}`);
          const idx = sessions.findIndex(s => s.id === id);
          if (idx >= 0) sessions[idx] = updated;
          render();
          if (job.state === 'done') {
            const pub = await api('POST', `/api/relaxation/${id}/publish`).catch(() => null);
            if (pub) { sessions[idx] = { ...sessions[idx], publish: pub }; render(); }
          }
        } catch (_) {}
      });
      const idx = sessions.findIndex(s => s.id === id);
      if (idx >= 0) { sessions[idx] = { ...sessions[idx], status: 'running' }; render(); }
    }

    // follow a YouTube upload: the card shows the bar while it runs, then the link (or the error) when it ends
    function followUpload(id) {
      const i0 = sessions.findIndex(s => s.id === id);
      if (i0 >= 0) { sessions[i0] = { ...sessions[i0], status: 'uploading', error: '', _done: '', _job: null }; render(); }
      startPoll(id, async (job) => {
        const finished = job.state === 'done' || job.state === 'error';
        const updated = await api('GET', `/api/relaxation/${id}`);
        const idx = sessions.findIndex(s => s.id === id);
        if (idx >= 0) sessions[idx] = { ...updated, status: finished ? updated.status : 'uploading', _job: finished ? null : job,
          _done: job.state === 'done' ? (job.note || 'Posted to YouTube.') : '', error: job.state === 'error' ? (job.error || updated.error) : updated.error };
        render();
      });
    }

    render();
    // opening the page while something runs (a run, or new music started earlier): follow it, so the card shows where it is
    const going = sessions.find(s => s.status === 'running' || s.status === 'uploading');
    if (going) {
      startPoll(going.id, async (job) => {
        const updated = await api('GET', `/api/relaxation/${going.id}`);
        const idx = sessions.findIndex(s => s.id === going.id);
        const finished = job.state === 'done' || job.state === 'error';
        if (idx >= 0) sessions[idx] = { ...updated, _job: finished ? null : job, _done: job.state === 'done' && job.note ? job.note : '', error: job.state === 'error' ? (job.error || updated.error) : updated.error };
        render();
      });
    }
  }

  return showRelaxation;
})();
