/* Relaxation Rain Channel — #/relaxation
   Called directly from index.html router as showRelaxation(). */

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
    rain: '2. Rain animation',
    upscale: '3. 2K upscale',
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

  function stepDots(s) {
    const steps = ['scene', 'rain', 'upscale', 'audio', 'video', 'publish'];
    return steps.map(k => {
      const done = s[`${k === 'scene' ? 'scene' : k === 'final' ? 'final' : k}_ready`] ||
                   s[k + '_ready'] || false;
      const active = s.step === k;
      const cls = active ? 'running' : (done ? 'done' : '');
      return `<span class="dot ${cls}" title="${STEP_LABELS[k] || k}"></span>`;
    }).join('');
  }

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
      <span style="margin-left:8px">${badge(s.status)}</span>
      <span style="margin-left:8px">${stepDots(s)}</span>
    </div>
    <span class="sp"></span>
    <button class="small bad" data-action="delete" data-id="${s.id}">Delete</button>
  </div>

  ${s.error ? `<div class="errbox mt-s">${s.error}</div>` : ''}
  ${s.step ? `<div class="small mute mt-s">Working: ${STEP_LABELS[s.step] || s.step} <span class="spin"></span></div>` : ''}

  ${s.scene_url ? `<img src="${s.scene_url}" style="max-width:320px;border-radius:8px;margin-top:10px;display:block" alt="scene preview">` : ''}

  <div class="row mt">
    ${s.status === 'new' || s.status === 'failed'
      ? `<button class="primary" data-action="run" data-id="${s.id}">Generate</button>`
      : s.status === 'running'
      ? `<button disabled>Running <span class="spin"></span></button>`
      : ''}
    ${finalReady && !hasMetadata
      ? `<button data-action="metadata" data-id="${s.id}">Write metadata</button>` : ''}
    ${finalReady && hasMetadata && !ytId
      ? `<button class="good" data-action="upload" data-id="${s.id}">Post to YouTube</button>` : ''}
    ${ytId
      ? `<a href="https://youtu.be/${ytId}" target="_blank" class="btn">View on YouTube ↗</a>` : ''}
    ${finalReady
      ? `<a href="/api/relaxation/${s.id}/download" class="btn small">Download</a>` : ''}
  </div>

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

    try {
      const [sceneRes, sesRes] = await Promise.all([
        api('GET', '/api/relaxation/options/scenes'),
        api('GET', '/api/relaxation'),
      ]);
      scenes = sceneRes.scenes || {};
      sessions = sesRes.sessions || [];
    } catch (e) {
      app.innerHTML = `<h2>Rain Channel</h2><div class="errbox">${e.message}</div>`;
      return;
    }

    function render() {
      const cards = sessions.length
        ? sessions.map(s => sessionCard(s)).join('')
        : '<div class="big-empty"><h2>No sessions yet</h2><p>Create one below to generate a 3-hour rain video.</p></div>';

      app.innerHTML = `
<h2>Rain Channel</h2>
<p class="mute small">Each session generates a 3-hour ambient rain video and posts it to YouTube.</p>

<div class="card pad mb">
  <h4>New session</h4>
  <div class="row">
    <label class="f">Scene
      <select id="rl-scene">
        ${Object.entries(scenes).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}
      </select>
    </label>
    <label class="f">Length (hours)
      <input type="number" id="rl-hours" value="3" min="1" max="8" style="width:80px">
    </label>
    <button class="primary" id="rl-create">Create &amp; Generate</button>
  </div>
</div>

<div id="rl-sessions">${cards}</div>`;

      document.getElementById('rl-create').onclick = async () => {
        const scene = document.getElementById('rl-scene').value;
        const hours = parseInt(document.getElementById('rl-hours').value) || 3;
        try {
          const s = await api('POST', '/api/relaxation', { scene, hours });
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
            pollUpload(id);
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

    async function pollUpload(id) {
      const t = setInterval(async () => {
        try {
          const job = await api('GET', `/api/relaxation/${id}/run`);
          if (job.state === 'done' || job.state === 'error') {
            clearInterval(t);
            const updated = await api('GET', `/api/relaxation/${id}`);
            const idx = sessions.findIndex(s => s.id === id);
            if (idx >= 0) sessions[idx] = updated;
            render();
          }
        } catch (_) {}
      }, 3000);
    }

    render();
  }
