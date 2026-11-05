/* Memory Analysis UI — mounted by characters.js when Memory tab is active.
   Entry point: window.chMemoryMount(charId) */

(function () {
  const CAT_COLOR = {
    episodic:    '#6C8EBF', observation: '#82B366', learning:    '#D6B656',
    achievement: '#9673A6', discovery:   '#E07B54', reflection:  '#67AB9F',
    desire:      '#D69B56', wish:        '#E088B4', note:        '#999',
    manual:      '#999',   trait:        '#E84393',
  };
  const SOURCE_LABEL = { think: 'Daily life', book: 'Reading', web: 'Web', consolidation: 'Consolidated', daydream: 'Daydream' };
  const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  // ── helpers ──────────────────────────────────────────────────────────────────
  function relTime(ts) {
    const d = Math.round((Date.now() / 1000 - ts) / 86400);
    return d < 1 ? 'today' : d < 7 ? d + 'd ago' : d < 30 ? Math.round(d/7) + 'w ago' : Math.round(d/30) + 'mo ago';
  }
  function strBar(s, len = 5) {
    const f = Math.round(Math.min(1, s) * len);
    return '<span style="letter-spacing:-1px;font-size:12px">' + '█'.repeat(f) + '░'.repeat(len - f) + '</span>';
  }
  function catDot(cat) {
    return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${CAT_COLOR[cat]||'#aaa'};margin-right:4px"></span>`;
  }
  function sourceTag(src) {
    const key = src ? src.split(':')[0] : 'think';
    const label = SOURCE_LABEL[key] || key;
    return `<span class="badge" style="font-size:10px;background:var(--panel);border:1px solid var(--line)">${esc(label)}</span>`;
  }
  async function api(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  // ── section wrappers ─────────────────────────────────────────────────────────
  function section(title, id, content) {
    return `<div class="card pad mt" id="${id}">
      <h3 style="margin-top:0;margin-bottom:10px">${title}</h3>${content}</div>`;
  }

  // ── 5a: Landscape ────────────────────────────────────────────────────────────
  function renderLandscape(data, sourceFilter) {
    const filterBar = `
      <div class="row" style="gap:6px;margin-bottom:10px;flex-wrap:wrap">
        <span class="mute small">Source:</span>
        ${['all','think','book','web'].map(s =>
          `<button class="small${sourceFilter===s?' primary':''}" data-src-filter="${s}">${s==='all'?'All':SOURCE_LABEL[s]||s}</button>`
        ).join('')}
      </div>`;

    const statusRow = `<div class="row" style="gap:16px;margin-bottom:12px">
      <span>${data.active} <span class="mute small">active</span></span>
      <span style="color:var(--mute)">${data.fading} <span class="mute small">fading</span></span>
      <span style="color:var(--mute);opacity:.5">${data.archived} <span class="mute small">archived</span></span>
      <span class="sp"></span><span class="mute small">${data.total} total</span>
    </div>`;

    const bars = data.by_category.map(c => {
      const pct = data.total ? Math.round(c.count / data.total * 100) : 0;
      return `<div style="margin-bottom:6px">
        <div class="row" style="gap:6px;margin-bottom:2px">
          ${catDot(c.category)}<span style="font-size:12px;min-width:120px">${esc(c.label)}</span>
          <span class="mute small" style="min-width:24px">${c.count}</span>
          <span class="mute small" style="font-size:11px">avg ${c.avg_strength}</span>
        </div>
        <div style="background:var(--line);border-radius:3px;height:6px;overflow:hidden">
          <div style="background:${CAT_COLOR[c.category]||'#aaa'};width:${pct}%;height:100%;transition:width .3s"></div>
        </div>
      </div>`;
    }).join('');

    const topMems = data.top_memories.length ? data.top_memories.map(m =>
      `<div class="row mt-s" style="gap:6px;align-items:flex-start;font-size:12px">
        ${catDot(m.category)}${strBar(m.current_strength)}${sourceTag(m.source)}
        <span style="flex:1">${esc(m.content.slice(0,100))}${m.content.length>100?'…':''}</span>
        <span class="mute" style="white-space:nowrap;font-size:11px">${relTime(m.formed_at)}</span>
      </div>`).join('')
    : '<div class="mute small">No strong memories yet.</div>';

    return filterBar + statusRow + bars +
      '<div class="mute small" style="margin:12px 0 6px;font-weight:600">Strongest right now</div>' + topMems;
  }

  // ── 5b: Bond Graph ───────────────────────────────────────────────────────────
  function renderBondGraph(data) {
    const W = 640, H = 420, cx = W/2, cy = H/2;
    const nodes = data.nodes, edges = data.edges;
    if (!nodes.length) return '<div class="mute small">No memories with bonds yet. They build as the character thinks.</div>';

    // Simple radial layout — nodes on concentric rings by strength
    const sorted = [...nodes].sort((a,b) => b.current_strength - a.current_strength);
    const pos = {};
    const rings = [1, 6, 12, 18, 24]; // capacity per ring
    let ri = 0, used = 0, total = 0;
    for (const n of sorted) {
      const capacity = rings[ri] || 24;
      if (used >= capacity) { ri = Math.min(ri + 1, rings.length - 1); used = 0; }
      const r = ri === 0 ? 0 : 60 + ri * 70;
      const countInRing = Math.min(nodes.length - total, rings[ri] || 24);
      const angle = used === 0 && ri === 0 ? 0 : (used / countInRing) * 2 * Math.PI - Math.PI/2;
      pos[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
      used++; total++;
    }

    const edgeSvg = edges.map(e => {
      const a = pos[e.a], b = pos[e.b];
      if (!a || !b) return '';
      const opacity = Math.min(0.8, e.strength);
      return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"
        stroke="#6C8EBF" stroke-width="${(e.strength * 3).toFixed(1)}" stroke-opacity="${opacity}"/>`;
    }).join('');

    const nodeSvg = nodes.map(n => {
      const p = pos[n.id]; if (!p) return '';
      const r = Math.max(4, Math.min(14, n.current_strength * 12));
      const col = CAT_COLOR[n.category] || '#aaa';
      const label = n.content.slice(0, 28) + (n.content.length > 28 ? '…' : '');
      const stable = n.stable ? ' ★' : '';
      return `<g class="mem-node" data-id="${esc(n.id)}" style="cursor:pointer">
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}" fill="${col}" fill-opacity="0.85" stroke="var(--panel)" stroke-width="1.5"/>
        <title>${esc(n.content)}${stable} [${n.category}] ${relTime(n.formed_at)}</title>
      </g>`;
    }).join('');

    const legend = Object.entries(CAT_COLOR).slice(0,8).map(([cat, col]) =>
      `<span style="margin-right:10px;font-size:11px">${catDot(cat)}${cat}</span>`
    ).join('');

    return `<div style="overflow-x:auto">
      <svg width="${W}" height="${H}" style="border:1px solid var(--line);border-radius:8px;background:var(--bg2,#fafafa)">
        <g class="edges">${edgeSvg}</g>
        <g class="nodes">${nodeSvg}</g>
      </svg>
    </div>
    <div style="margin-top:8px;flex-wrap:wrap;display:flex">${legend}</div>
    <div class="mute small mt-s">Node size = current strength · Edge thickness = bond strength · Hover for content</div>
    <div id="bond-detail" style="margin-top:8px;min-height:24px"></div>`;
  }

  // ── 5c: Traits ───────────────────────────────────────────────────────────────
  function renderTraits(traits) {
    if (!traits.length) return '<div class="mute small">No traits formed yet — traits emerge from repeated related memories during sleep consolidation.</div>';
    return traits.map(t => `
      <div class="card pad mt-s" style="border-left:3px solid ${t.stable ? '#E84393' : '#D6B656'}">
        <div class="row" style="gap:6px;align-items:center">
          ${t.stable ? '<span class="badge" style="background:#E84393;color:#fff;font-size:10px">★ stable trait</span>' : '<span class="badge" style="background:#D6B656;color:#fff;font-size:10px">emerging</span>'}
          ${strBar(Math.min(1, t.current_strength / 1.5))}
          <span class="mute small">${relTime(t.formed_at)}</span>
        </div>
        <div style="margin-top:6px;font-style:italic">${esc(t.content)}</div>
      </div>`).join('');
  }

  // ── 5d: Trajectory ───────────────────────────────────────────────────────────
  function renderTrajectory(snapshots) {
    if (snapshots.length < 2) return '<div class="mute small">Need at least 2 days of data for trajectory. Keep the character active.</div>';

    const dates = snapshots.map(s => s.snapshot_date.slice(5)); // MM-DD
    const energies = snapshots.map(s => s.energy);
    const maxE = Math.max(...energies, 1);

    // sparkline helper (SVG polyline)
    function sparkline(values, color, max) {
      const W2 = 180, H2 = 32, n = values.length;
      const pts = values.map((v, i) => `${(i/(n-1)*W2).toFixed(1)},${(H2 - v/max*H2).toFixed(1)}`).join(' ');
      return `<svg width="${W2}" height="${H2}" style="overflow:visible"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
    }

    // Interest trajectories
    const allInterestKeys = [...new Set(snapshots.flatMap(s => Object.keys(s.interests || {})))];
    const interestRows = allInterestKeys.slice(0, 6).map(k => {
      const vals = snapshots.map(s => ((s.interests[k] && typeof s.interests[k]==='object') ? s.interests[k].intensity : 5) || 5);
      return `<div class="row mt-s" style="gap:8px;align-items:center">
        <span style="min-width:60px;font-size:12px;color:var(--mute)">${esc(k)}</span>
        ${sparkline(vals, '#6C8EBF', 10)}
        <span class="mute small">${vals[vals.length-1]}/10</span>
      </div>`;
    }).join('');

    // Curiosity pool over time
    const allCuriosityNames = [...new Set(snapshots.flatMap(s => (s.curiosities||[]).map(c => c.name)))];
    const curiosityRows = allCuriosityNames.slice(0, 4).map(name => {
      const vals = snapshots.map(s => {
        const c = (s.curiosities||[]).find(c => c.name === name);
        return c ? c.spark : 0;
      });
      return `<div class="row mt-s" style="gap:8px;align-items:center">
        <span style="min-width:60px;font-size:12px;color:var(--mute)">${esc(name.slice(0,10))}</span>
        ${sparkline(vals, '#E07B54', 10)}
        <span class="mute small" style="font-size:11px">${vals[vals.length-1].toFixed(1)} spark</span>
      </div>`;
    }).join('');

    return `
      <div class="row" style="gap:24px;flex-wrap:wrap;align-items:flex-start">
        <div>
          <div class="mute small" style="font-weight:600;margin-bottom:4px">Energy (last ${snapshots.length}d)</div>
          ${sparkline(energies, '#82B366', 100)}
          <div class="mute small" style="margin-top:2px">now: ${energies[energies.length-1]}/100</div>
        </div>
        <div>
          <div class="mute small" style="font-weight:600;margin-bottom:4px">Interests</div>
          ${interestRows || '<span class="mute small">none yet</span>'}
        </div>
        <div>
          <div class="mute small" style="font-weight:600;margin-bottom:4px">Curiosity pool</div>
          ${curiosityRows || '<span class="mute small">none yet</span>'}
        </div>
      </div>`;
  }

  // ── 5e: Building / Fading ────────────────────────────────────────────────────
  function renderBuilding(landscape) {
    const all = landscape._all_mems || [];
    const now = Date.now() / 1000;
    const building = all.filter(m => m.last_accessed_at && (now - m.last_accessed_at) < 86400 && m.current_strength >= 0.4)
                        .sort((a,b) => b.current_strength - a.current_strength).slice(0,5);
    const fading   = all.filter(m => m.last_accessed_at && (now - m.last_accessed_at) > 5*86400 && m.current_strength >= 0.04)
                        .sort((a,b) => a.current_strength - b.current_strength).slice(0,5);
    const row = m => `<div class="row mt-s" style="font-size:12px;gap:6px">
      ${catDot(m.category)}${strBar(m.current_strength)}
      <span style="flex:1">${esc(m.content.slice(0,80))}${m.content.length>80?'…':''}</span>
      <span class="mute">${relTime(m.formed_at)}</span>
    </div>`;
    return `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          <div class="mute small" style="font-weight:600;margin-bottom:4px">On her mind (accessed today)</div>
          ${building.length ? building.map(row).join('') : '<div class="mute small">Nothing accessed today yet.</div>'}
        </div>
        <div>
          <div class="mute small" style="font-weight:600;margin-bottom:4px">Fading (5+ days unaccessed)</div>
          ${fading.length ? fading.map(row).join('') : '<div class="mute small">Nothing fading right now.</div>'}
        </div>
      </div>`;
  }

  // ── 5f: Nudges ───────────────────────────────────────────────────────────────
  function renderNudges(nudges, charId) {
    if (!nudges.length) return '<div class="mute small">No nudges right now — keep the character active.</div>';
    const icon = { aspiration_goal: '🎯', curiosity_promote: '✨', memory_theme: '🔍' };
    return nudges.map((n, i) => {
      const makeGoalBtn = n.type === 'aspiration_goal' && n.data && n.data.id
        ? `<button class="small primary" style="margin-top:6px" data-make-goal="${esc(n.data.id)}">Make this a goal</button>`
        : '';
      return `<div class="card pad mt-s" style="border-left:3px solid var(--warn);padding:8px 10px">
        <span>${icon[n.type]||'💡'} ${esc(n.message)}</span>${makeGoalBtn}
      </div>`;
    }).join('');
  }

  // ── mount ─────────────────────────────────────────────────────────────────────
  window.chMemoryMount = async function(charId) {
    const root = document.getElementById('ch-memory-root');
    if (!root) return;

    // also run seed_bonds on first mount (idempotent)
    fetch(`/api/characters/${charId}/memory/seed_bonds`, { method: 'POST' }).catch(() => {});

    root.innerHTML = `<div class="mute small" style="padding:24px">Loading memory data…</div>`;

    let sourceFilter = 'all';

    async function load() {
      root.innerHTML = `<div class="mute small" style="padding:24px">Loading…</div>`;
      try {
        const srcParam = sourceFilter !== 'all' ? `?source=${sourceFilter}` : '';
        const safe = url => api(url).catch(e => ({ _err: String(e) }));
        const [landscape, bonds, traits, trajectory, nudges] = await Promise.all([
          safe(`/api/characters/${charId}/memory/landscape${srcParam}`),
          safe(`/api/characters/${charId}/memory/bonds`),
          safe(`/api/characters/${charId}/memory/traits`),
          safe(`/api/characters/${charId}/memory/trajectory`),
          safe(`/api/characters/${charId}/memory/nudges`),
        ]);

        const errBox = (name, e) => `<div class="mute small" style="color:var(--warn)">${name} unavailable: ${esc(e)}</div>`;
        const landOk = !landscape._err, bondsOk = !bonds._err;

        root.innerHTML = [
          section('Memory Landscape', 'mem-landscape', landOk ? renderLandscape(landscape, sourceFilter) : errBox('Landscape', landscape._err)),
          section('Bond Graph', 'mem-bonds', bondsOk ? renderBondGraph(bonds) : errBox('Bond graph', bonds._err)),
          section('Traits &amp; Consolidations', 'mem-traits', traits._err ? errBox('Traits', traits._err) : renderTraits(traits)),
          section('Trajectory', 'mem-trajectory', trajectory._err ? errBox('Trajectory', trajectory._err) : renderTrajectory(trajectory)),
          section('Building / Fading', 'mem-building', renderBuilding({...(landOk ? landscape : {}), _all_mems: bondsOk ? bonds.nodes : []})),
          section('Nudges', 'mem-nudges', nudges._err ? errBox('Nudges', nudges._err) : renderNudges(nudges, charId)),
        ].join('');

        // source filter buttons
        root.querySelectorAll('[data-src-filter]').forEach(btn => {
          btn.onclick = () => { sourceFilter = btn.dataset.srcFilter; load(); };
        });

        // aspiration → goal buttons
        root.querySelectorAll('[data-make-goal]').forEach(btn => {
          btn.onclick = async () => {
            const aspId = btn.dataset.makeGoal;
            const cat = prompt('Goal category: ' + ['career','personal','creative','health','social','learning','financial'].join(' / '), 'personal') || 'personal';
            btn.disabled = true; btn.textContent = 'Creating…';
            try {
              await fetch(`/api/characters/${charId}/aspirations/${aspId}/goal`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({category: cat}),
              });
              btn.textContent = '✓ Goal created';
              setTimeout(() => load(), 800);
            } catch (e) {
              btn.disabled = false; btn.textContent = 'Make this a goal';
            }
          };
        });

        // bond graph node hover detail
        root.querySelectorAll('.mem-node').forEach(node => {
          node.addEventListener('mouseenter', () => {
            const detail = document.getElementById('bond-detail');
            if (!detail) return;
            const n = bonds.nodes.find(x => x.id === node.dataset.id);
            if (!n) return;
            const connectedEdges = bonds.edges.filter(e => e.a === n.id || e.b === n.id);
            detail.innerHTML = `<div class="card pad" style="padding:8px;font-size:12px">
              <b>${catDot(n.category)}${esc(n.category)}</b> ${sourceTag(n.source)} strength ${n.current_strength} · ${relTime(n.formed_at)}<br>
              <span style="color:var(--mute)">${esc(n.content)}</span><br>
              <span class="mute small">${connectedEdges.length} bond${connectedEdges.length!==1?'s':''}</span>
            </div>`;
          });
        });

      } catch (e) {
        root.innerHTML = `<div class="errbox" style="padding:12px">Failed to load memory data: ${esc(String(e))}</div>`;
      }
    }

    await load();
  };
})();
