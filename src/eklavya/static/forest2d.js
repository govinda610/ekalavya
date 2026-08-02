/* ============================================================================
   Ekalavya · Forest of Mastery — 2D painterly MAP renderer (SVG)
   ----------------------------------------------------------------------------
   A legible enchanted-forest MAP (per docs/design/FOREST_RENDER_FIX_SPEC.md §0.5)
   built to reference forest_bg.jpg: a luminous winding path from a foreground
   ENTRANCE up to a golden TEMPLE, ~18 named grove medallions each permanently
   labelled, prerequisite edges drawn between them, proscenium framing, night
   ambience, and life (fireflies, birds, sway) — all procedural + deterministic,
   seeded from report.forest_map() so the map auto-regenerates when pillars change.

   Public API (called from the SPA):
     Forest2D.showOverview(svg, opts)      -> paints the full map from /api/forest
     Forest2D.showGrove(svg, pillar, opts) -> drills into one pillar's concepts
   opts: { onGrove(pillar), reduced:bool }
   ============================================================================ */
(function (global) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';

  // ---- app-palette-derived tokens (kept in sync with webapp.py :root) --------
  const C = {
    skyHigh: '#141026', skyMid: '#241a45', skyHorizon: '#3a2f5e',
    hillFar: '#20264a', hillMid: '#1c3040', hillNear: '#173035',
    ground: '#12241d', groundLit: '#274a35', groundDeep: '#0c1a16',
    frame: '#0a1018', frameLit: '#152820',
    path: '#eef0d8', pathGlow: '#9fe6d6', pathEdge: '#57d3ce',
    gold: '#e7b64b', goldBright: '#f7d98a', goldDeep: '#b8862f', goldEmber: '#8a5e1f',
    teal: '#57d3ce', tealDeep: '#124d4c', peacock: '#2ea3a0',
    parch: '#e8dcc0', parchDim: '#cfc0a0', parchMute: '#a89670',
    ember: '#d97a3c', magenta: '#c86ba8',
    locked: '#3a4652', lockedLeaf: '#2a3742'
  };

  // Signature canopy hue FAMILIES (spec §3b) — grouped so groves are distinguishable
  // before you read a label, yet stay inside the indigo/gold/teal world.
  const FAMILIES = {
    foundation: ['#4e8f6a', '#3e8c6a', '#5aa06b'],   // emerald / jade — the roots
    theory:     ['#6b6ca8', '#7d6bb0', '#8a6fb2'],   // violet — math/stats/theory
    language:   ['#3f9aa0', '#2ea3a0', '#57b8b0'],   // teal — NLP/representation
    systems:    ['#c98a3a', '#b8893a', '#d9a24a'],   // gold/amber — engineering/systems
    retrieval:  ['#3e8c8a', '#2a7d8c', '#4c9aa0'],   // deep teal — RAG/vector
    agents:     ['#c98a5a', '#a85c3c', '#d99a5a'],   // copper — agents/orchestration
    frontier:   ['#9a6fb0', '#7a3f83', '#b07ac0'],   // plum — interp/frontier
    craft:      ['#5a9a7a', '#4e8f6a', '#6bab86']    // green — python/eng craft
  };
  // map a pillar name to a family by keyword; deterministic + auto-adapts to new names
  function familyOf(name) {
    const n = (name || '').toLowerCase();
    if (/interpret|explain|mechanistic|frontier/.test(n)) return 'frontier';
    if (/rag|vector|retriev/.test(n)) return 'retrieval';
    if (/agent|orchestrat/.test(n)) return 'agents';
    if (/nlp|represent|language|graph/.test(n)) return 'language';
    if (/math|theory|statist|econometr|time-?series|forecast/.test(n)) return 'theory';
    if (/mlops|llmops|system\s*design|engineering|stack|genai|deep learning|llm/.test(n)) return 'systems';
    if (/python|object-?oriented|backend|production|data structure|algorithm|cs found/.test(n)) return 'craft';
    return 'foundation';
  }
  // a stable per-name hash so the exact hue within a family is deterministic
  function hash(str) { let h = 2166136261; for (let i = 0; i < (str || '').length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0); }
  function signatureHue(name) {
    const fam = FAMILIES[familyOf(name)];
    return fam[hash(name) % fam.length];
  }
  // small deterministic PRNG seeded from a string — for jittering foliage/stars
  function rng(seedStr) { let s = hash(seedStr) || 1; return function () { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }

  // ---- tiny svg helpers ------------------------------------------------------
  function el(t, a, parent) { const e = document.createElementNS(NS, t); if (a) for (const k in a) e.setAttribute(k, a[k]); if (parent) parent.appendChild(e); return e; }
  function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function short(s, n) { s = s || ''; return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function shade(hex, amt) { // lighten(+)/darken(-) a hex by amt in [-1,1]
    const m = /^#?([0-9a-f]{6})$/i.exec(hex); if (!m) return hex; const n = parseInt(m[1], 16);
    let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    const f = amt < 0 ? 0 : 255, k = Math.abs(amt);
    r = Math.round(lerp(r, f, k)); g = Math.round(lerp(g, f, k)); b = Math.round(lerp(b, f, k));
    return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  }

  const VB = { w: 1200, h: 760 };  // logical canvas (matches ref aspect ~1.58)

  // ============================================================================
  // LAYOUT — a SWITCHBACK trail climbing from a foreground ENTRANCE (bottom) up to
  // the TEMPLE (top center). Nodes are placed on serpentine rows (boustrophedon) so
  // spacing is guaranteed even at 18+ groves — never a bunched tangle. Foreground
  // rows are larger & wider; higher rows recede & narrow (perspective funnel).
  // ============================================================================
  function layout(n) {
    const temple = { x: VB.w * 0.5, y: 116 };
    if (n <= 0) return { pts: [], temple: temple };
    const marginTop = 214, marginBot = 132;
    const usableH = VB.h - marginTop - marginBot;
    // per-row count: keep ~3 groves/row so both horizontal AND vertical spacing stay
    // generous (medallions on adjacent rows must not stack). More rows just makes the
    // world taller/receding — legibility over density (spec §0.5).
    const perRow = n <= 3 ? Math.max(1, n) : (n <= 6 ? 3 : (n <= 12 ? 3 : 4));
    const rows = Math.ceil(n / perRow);
    const pts = [];
    for (let i = 0; i < n; i++) {
      const row = Math.floor(i / perRow);
      const col = i % perRow;
      const inRow = Math.min(perRow, n - row * perRow);
      const tRow = rows === 1 ? 0 : row / (rows - 1);   // 0 bottom … 1 top
      const y = VB.h - marginBot - Math.pow(tRow, 0.88) * usableH;
      // horizontal span narrows toward the temple (perspective funnel)
      const sideMargin = lerp(130, 340, tRow);
      const span = VB.w - 2 * sideMargin;
      const f = inRow > 1 ? col / (inRow - 1) : 0.5;
      // serpentine: even rows L→R, odd rows R→L → one continuous switchback trail
      let fx = row % 2 === 0 ? f : (1 - f);
      // half-column stagger between rows so medallions interleave, never stack vertically
      fx += (row % 2 === 0 ? 1 : -1) * (0.5 / Math.max(2, perRow)) * (inRow > 1 ? 1 : 0);
      fx = Math.max(0, Math.min(1, fx));
      const x = sideMargin + fx * span;
      // node scale shrinks with N so a crowded map stays uncluttered (foreground bigger)
      const base = n > 14 ? 0.92 : n > 9 ? 1.02 : 1.12;
      const scale = lerp(base, base * 0.62, tRow);
      pts.push({ x: Math.round(x), y: Math.round(y), t: i / Math.max(1, n - 1), scale: scale, row: row });
    }
    return { pts: pts, temple: temple };
  }

  // Catmull-Rom → cubic bezier through the points (smooth winding trail)
  function pathThrough(pts, upto) {
    const p = (upto == null ? pts : pts.slice(0, Math.max(1, upto)));
    if (p.length < 1) return '';
    if (p.length < 2) return 'M' + p[0].x + ',' + p[0].y;
    let d = 'M' + p[0].x + ',' + p[0].y;
    for (let i = 0; i < p.length - 1; i++) {
      const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
      const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
      d += ' C' + c1x.toFixed(1) + ',' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ',' + c2y.toFixed(1) + ' ' + p2.x + ',' + p2.y;
    }
    return d;
  }

  // ============================================================================
  // DEFS — gradients, glows, filters (soft, painterly)
  // ============================================================================
  function defs(svg, reduced) {
    const d = el('defs', {}, svg);
    d.innerHTML = [
      // sky: indigo night warming toward the temple horizon
      grad('skyG', 0, 0, 0, 1, [[0, C.skyHigh], [0.42, C.skyMid], [0.72, C.skyHorizon], [1, '#2a2340']]),
      // ground: saturated teal-green, never grey, warming toward the path
      grad('groundG', 0, 0, 0, 1, [[0, C.groundDeep], [0.5, C.ground], [1, '#0a1713']]),
      radial('templeGlow', 50, 46, 60, [[0, '#fff2c4'], [0.35, C.goldBright], [0.7, 'rgba(231,182,75,.35)'], [1, 'rgba(231,182,75,0)']]),
      radial('nodeGold', 50, 45, 60, [[0, '#fff3cf'], [0.4, C.gold], [1, 'rgba(231,182,75,0)']]),
      radial('nodeTeal', 50, 45, 60, [[0, '#d6fbf4'], [0.4, C.teal], [1, 'rgba(87,211,206,0)']]),
      radial('mistG', 50, 50, 60, [[0, 'rgba(180,200,220,.30)'], [1, 'rgba(180,200,220,0)']]),
      radial('moonG', 50, 50, 60, [[0, '#fbf3d8'], [0.5, 'rgba(247,231,197,.55)'], [1, 'rgba(247,231,197,0)']]),
      // luminous path: pale core, teal halo
      grad('pathG', 0, 0, 0, 1, [[0, '#f4f7e0'], [1, '#dfeecb']]),
      // vignette for edges
      radial('vig', 50, 46, 75, [[0, 'rgba(0,0,0,0)'], [0.72, 'rgba(0,0,0,0)'], [1, 'rgba(4,6,14,.72)']]),
      // soft blur filters
      '<filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="6"/></filter>',
      '<filter id="soft2" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="14"/></filter>',
      '<filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
      '<filter id="paper"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .04 0"/></filter>'
    ].join('');
    return d;
    function grad(id, x1, y1, x2, y2, stops) {
      return '<linearGradient id="' + id + '" x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '">' +
        stops.map(s => '<stop offset="' + s[0] + '" stop-color="' + s[1] + '"/>').join('') + '</linearGradient>';
    }
    function radial(id, cx, cy, r, stops) {
      return '<radialGradient id="' + id + '" cx="' + cx + '%" cy="' + cy + '%" r="' + r + '%">' +
        stops.map(s => '<stop offset="' + s[0] + '" stop-color="' + s[1] + '"/>').join('') + '</radialGradient>';
    }
  }

  // ============================================================================
  // BACKGROUND LAYERS — sky, moon/stars, hills, temple, mist
  // ============================================================================
  function paintSky(g, reduced) {
    el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#skyG)' }, g);
    // stars
    const r = rng('stars'); const stars = el('g', {}, g);
    for (let i = 0; i < 90; i++) {
      const x = r() * VB.w, y = r() * VB.h * 0.42, rad = 0.5 + r() * 1.3, o = 0.25 + r() * 0.55;
      const s = el('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: '#f4ecd6', opacity: o.toFixed(2) }, stars);
      if (!reduced) anim(s, 'opacity', o.toFixed(2), (o * 0.35).toFixed(2), (2.5 + r() * 4).toFixed(1) + 's');
    }
    // crescent moon (upper-right, per ref A compass side balance -> put opposite temple)
    const mg = el('g', { transform: 'translate(' + (VB.w * 0.8) + ',96)' }, g);
    el('circle', { r: 74, fill: 'url(#moonG)' }, mg);
    el('circle', { r: 26, fill: '#f7ecd0' }, mg);
    el('circle', { cx: 11, cy: -6, r: 24, fill: C.skyMid }, mg);  // crescent bite
  }

  function paintHills(g) {
    // three receding ridgelines, cool → warmer near the temple horizon
    band(g, C.hillFar, 176, 0.62, 'hf');
    band(g, C.hillMid, 210, 0.78, 'hm');
    band(g, C.hillNear, 250, 0.92, 'hn');
    function band(parent, col, baseY, op, seed) {
      const r = rng(seed); let d = 'M0,' + VB.h + ' L0,' + baseY;
      for (let x = 0; x <= VB.w; x += 60) { const y = baseY + Math.sin(x * 0.01 + r() * 6) * 26 - r() * 18; d += ' L' + x + ',' + y.toFixed(1); }
      d += ' L' + VB.w + ',' + VB.h + ' Z';
      el('path', { d: d, fill: col, opacity: op, filter: 'url(#soft)' }, parent);
    }
  }

  // Golden temple — a stepped shikhara/stupa complex, the journey's destination.
  function paintTemple(g, tp, reduced) {
    const glow = el('circle', { cx: tp.x, cy: tp.y + 6, r: 150, fill: 'url(#templeGlow)' }, g);
    if (!reduced) anim(glow, 'opacity', '1', '0.72', '6s');
    const t = el('g', { transform: 'translate(' + tp.x + ',' + tp.y + ')' }, g);
    // light shafts fanning down from the temple (god-rays)
    const rays = el('g', { opacity: 0.5, filter: 'url(#soft2)' }, t);
    for (let i = -2; i <= 2; i++) {
      el('path', { d: 'M0,-8 L' + (i * 60 - 40) + ',260 L' + (i * 60 + 40) + ',260 Z', fill: 'rgba(247,217,138,.10)' }, rays);
    }
    // three spires (center tallest) — stepped tiers as a stack of trapezoids
    spire(t, 0, 0, 1.0); spire(t, -78, 26, 0.62); spire(t, 78, 26, 0.62);
    spire(t, -140, 40, 0.4); spire(t, 140, 40, 0.4);
    // plinth
    el('rect', { x: -168, y: 74, width: 336, height: 20, rx: 4, fill: C.goldDeep, opacity: 0.9 }, t);
    el('rect', { x: -150, y: 70, width: 300, height: 8, fill: C.goldBright, opacity: 0.7 }, t);
    function spire(parent, dx, dy, s) {
      const gg = el('g', { transform: 'translate(' + dx + ',' + dy + ') scale(' + s + ')' }, parent);
      const tiers = 5; let w = 96, y = 74;
      for (let i = 0; i < tiers; i++) {
        const h = 15, top = w * 0.72;
        el('path', { d: 'M' + (-w / 2) + ',' + y + ' L' + (w / 2) + ',' + y + ' L' + (top / 2) + ',' + (y - h) + ' L' + (-top / 2) + ',' + (y - h) + ' Z',
          fill: i % 2 ? C.gold : C.goldBright, opacity: (0.82 - i * 0.04).toFixed(2) }, gg);
        w = top; y -= h;
      }
      // crowning spire
      el('path', { d: 'M0,' + (y - 26) + ' L' + (w * 0.28) + ',' + y + ' L' + (-w * 0.28) + ',' + y + ' Z', fill: C.goldBright }, gg);
      el('circle', { cx: 0, cy: y - 30, r: 3.4, fill: '#fff3cf' }, gg);
    }
  }

  function paintMist(g, reduced) {
    for (let i = 0; i < 4; i++) {
      const y = 250 + i * 42, w = 420 + i * 90, x = (i % 2 ? VB.w * 0.32 : VB.w * 0.66);
      const m = el('ellipse', { cx: x, cy: y, rx: w, ry: 44, fill: 'url(#mistG)', opacity: 0.5 }, g);
      if (!reduced) { const dur = (26 + i * 6) + 's'; const dx = (i % 2 ? 40 : -40);
        animT(m, x + ',' + y, (x + dx) + ',' + y, dur); }
    }
  }

  // ============================================================================
  // FOLIAGE STANDS (midground) + PROSCENIUM FRAME (foreground) — depth + framing
  // ============================================================================
  function paintStands(g) {
    // a lush understorey filling the ground plane between the path and the frame, so it
    // reads as a dense forest floor (never empty/dark), with density rising toward the
    // edges and a warm forest-floor wash so nothing is grey.
    el('rect', { x: 0, y: 300, width: VB.w, height: VB.h - 300, fill: 'url(#groundG)' }, g);
    // soft canopy-shadow pools scattered on the floor
    const rp = rng('pools');
    for (let i = 0; i < 26; i++) {
      const x = rp() * VB.w, y = 360 + rp() * (VB.h - 420), rad = 40 + rp() * 90;
      el('ellipse', { cx: x.toFixed(0), cy: y.toFixed(0), rx: rad.toFixed(0), ry: (rad * 0.4).toFixed(0), fill: rp() > 0.5 ? shade(C.groundLit, -0.1) : C.groundDeep, opacity: 0.25, filter: 'url(#soft2)' }, g);
    }
    // clustered tree stands — edges dense, centre (path) sparse
    const spots = [
      [90, 320, 1.1], [1110, 320, 1.1], [40, 460, 1.35], [1160, 460, 1.35],
      [200, 285, .8], [1000, 285, .8], [470, 250, .55], [740, 245, .55],
      [300, 380, .95], [900, 380, .95], [120, 600, 1.5], [1080, 600, 1.5],
      [350, 640, 1.1], [850, 640, 1.1], [560, 300, .5], [660, 300, .5],
      [230, 520, 1.1], [980, 520, 1.1]
    ];
    spots.forEach(([x, y, s], i) => stand(g, x, y, s, 'st' + i));
    function stand(parent, x, y, s, seed) {
      const rr = rng(seed);
      const gg = el('g', { transform: 'translate(' + x + ',' + y + ')' }, parent);
      const trees = 2 + Math.floor(rr() * 3);
      for (let i = 0; i < trees; i++) {
        const tx = (rr() - 0.5) * 80 * s, ty = (rr() - 0.5) * 30 * s, sc = (0.7 + rr() * 0.7) * s;
        // deep teal-green canopy (NOT olive-black), slight per-tree jitter, key-lit rim
        const base = shade('#1b3a34', -0.05 + rr() * 0.16);
        const t = el('g', { transform: 'translate(' + tx.toFixed(0) + ',' + ty.toFixed(0) + ') scale(' + sc.toFixed(2) + ')', opacity: (0.62 + rr() * 0.28).toFixed(2) }, gg);
        el('ellipse', { cx: 0, cy: 22, rx: 16, ry: 5, fill: '#0b1512', opacity: 0.5 }, t);
        el('path', { d: 'M0,22 V0', stroke: '#241d1a', 'stroke-width': 4 }, t);
        for (let k = 0; k < 6; k++) el('circle', { cx: (rr() - 0.5) * 30, cy: -8 - rr() * 22, r: 11 + rr() * 10, fill: base }, t);
        // rim light on top-left (key from temple side)
        for (let k = 0; k < 2; k++) el('circle', { cx: -6 - rr() * 8, cy: -22 - rr() * 8, r: 6 + rr() * 5, fill: shade(base, 0.28), opacity: 0.6 }, t);
      }
    }
  }

  // The proscenium: big dark arching banyans L/R, arch across the top, ferns/rocks
  // bottom corners — the single biggest "composed map" cue (spec §6.1).
  function paintFrame(g) {
    // top arching branches
    el('path', { d: 'M0,0 H1200 V54 C980,120 820,70 620,86 C420,70 250,124 0,58 Z', fill: C.frame, opacity: 0.96, filter: 'url(#soft)' }, g);
    hangingLeaves(g, 300, 70, 'tl'); hangingLeaves(g, 900, 70, 'tr');
    // left banyan mass
    banyan(g, -30, VB.h * 0.42, 1, 'L');
    // right banyan mass
    banyan(g, VB.w + 30, VB.h * 0.42, -1, 'R');
    // bottom ferns / rocks corners + a foreground lip so the path emerges from cover
    el('path', { d: 'M0,760 H1200 V690 C980,742 820,706 600,724 C400,706 220,748 0,700 Z', fill: C.frame, opacity: 0.9, filter: 'url(#soft)' }, g);
    ferns(g, 90, 700, 'fl', 1); ferns(g, 1110, 700, 'fr', -1);
    rocks(g, 150, 720, 'rl'); rocks(g, 1050, 720, 'rr');

    function banyan(parent, x, y, dir, seed) {
      const r = rng(seed);
      const gg = el('g', { transform: 'translate(' + x + ',' + y + ')', opacity: 0.98 }, parent);
      // thick trunk + arching limbs sweeping in from the corner (proscenium)
      el('path', { d: 'M' + (dir * 30) + ',330 C' + (dir * -10) + ',180 ' + (dir * 90) + ',60 ' + (dir * 10) + ',-300', stroke: '#0c1310', 'stroke-width': 82, fill: 'none', 'stroke-linecap': 'round' }, gg);
      el('path', { d: 'M' + (dir * 20) + ',40 C' + (dir * 170) + ',10 ' + (dir * 240) + ',110 ' + (dir * 360) + ',60', stroke: '#0b120d', 'stroke-width': 40, fill: 'none', 'stroke-linecap': 'round' }, gg);
      el('path', { d: 'M' + (dir * 10) + ',-40 C' + (dir * 120) + ',-70 ' + (dir * 220) + ',-30 ' + (dir * 300) + ',-90', stroke: '#0b120d', 'stroke-width': 26, fill: 'none', 'stroke-linecap': 'round' }, gg);
      // aerial-root strands (banyan signature)
      for (let i = 0; i < 6; i++) { const rx = dir * (60 + i * 46); el('line', { x1: rx, y1: -20 + r() * 40, x2: rx + dir * 6, y2: 120 + r() * 60, stroke: '#0c1310', 'stroke-width': 2.5, opacity: 0.7 }, gg); }
      // LUSH layered canopy — dense overlapping foliage, a couple lit rims so it reads
      // as a real tree massed in the corner (not scattered dots). Dark near-silhouette.
      const cl = el('g', {}, gg);
      const centers = [[dir * 70, -240, 90], [dir * 180, -180, 80], [dir * 40, -120, 96], [dir * 250, -120, 66], [dir * 150, -60, 84], [dir * 320, -40, 60], [dir * 90, 10, 74], [dir * 230, 40, 62]];
      centers.forEach(([cx, cy, rad]) => {
        for (let k = 0; k < 5; k++) el('circle', { cx: (cx + (r() - 0.5) * rad * 0.7).toFixed(0), cy: (cy + (r() - 0.5) * rad * 0.7).toFixed(0), r: (rad * (0.5 + r() * 0.5)).toFixed(0), fill: shade('#0d1712', r() * 0.06), opacity: (0.9 + r() * 0.1).toFixed(2) }, cl);
      });
      // a few dim teal-green lit leaves catching moonlight along the top edge
      for (let i = 0; i < 10; i++) el('circle', { cx: dir * (40 + r() * 280), cy: -260 + r() * 80, r: 5 + r() * 5, fill: shade('#1b3a34', 0.12), opacity: 0.4 }, cl);
      // warm lanterns hanging in the frame (ref A/alt5)
      lantern(gg, dir * 140, -30); lantern(gg, dir * 250, 60); lantern(gg, dir * 70, 90);
    }
    function lantern(parent, x, y) {
      const gg = el('g', { transform: 'translate(' + x + ',' + y + ')' }, parent);
      el('line', { x1: 0, y1: -40, x2: 0, y2: 0, stroke: '#2a2016', 'stroke-width': 1.5 }, gg);
      el('circle', { cx: 0, cy: 8, r: 16, fill: 'url(#nodeGold)', opacity: 0.9 }, gg);
      el('circle', { cx: 0, cy: 8, r: 5, fill: C.goldBright }, gg);
    }
    function hangingLeaves(parent, x, y, seed) {
      const r = rng(seed); const gg = el('g', {}, parent);
      for (let i = 0; i < 8; i++) { const lx = x + (r() - 0.5) * 260, ly = y + r() * 60;
        el('ellipse', { cx: lx.toFixed(0), cy: ly.toFixed(0), rx: 8, ry: 20, fill: '#0f1a13', opacity: 0.8, transform: 'rotate(' + ((r() - 0.5) * 40).toFixed(0) + ' ' + lx.toFixed(0) + ' ' + ly.toFixed(0) + ')' }, gg); }
    }
    function ferns(parent, x, y, seed, dir) {
      const r = rng(seed); const gg = el('g', { transform: 'translate(' + x + ',' + y + ')' }, parent);
      for (let i = 0; i < 7; i++) {
        const a = (-60 + i * 18 + (r() - 0.5) * 10) * dir, len = 90 + r() * 60;
        el('path', { d: 'M0,0 q' + (Math.cos(a * Math.PI / 180) * len * 0.5).toFixed(0) + ',' + (-len * 0.6).toFixed(0) + ' ' + (Math.cos(a * Math.PI / 180) * len).toFixed(0) + ',' + (-len).toFixed(0),
          stroke: shade(C.frameLit, r() * 0.1), 'stroke-width': 5, fill: 'none', 'stroke-linecap': 'round', opacity: 0.9 }, gg);
      }
    }
    function rocks(parent, x, y, seed) {
      const r = rng(seed); const gg = el('g', { transform: 'translate(' + x + ',' + y + ')' }, parent);
      for (let i = 0; i < 3; i++) el('ellipse', { cx: (r() - 0.5) * 90, cy: r() * 20, rx: 40 + r() * 30, ry: 22 + r() * 12, fill: shade('#182018', r() * 0.1), opacity: 0.9 }, gg);
    }
  }

  // ============================================================================
  // THE PATH (graph spine) + prerequisite EDGES between groves
  // ============================================================================
  function paintPath(g, pts, travelledUpto, reduced, temple) {
    // extend the trail from the last grove up to the temple so the spine clearly ends
    // at the destination (start at pts[0] entrance → temple).
    const ptsE = temple ? pts.concat([{ x: temple.x, y: temple.y + 78, scale: 0.5 }]) : pts;
    pts = ptsE;
    // The luminous winding RIVER-PATH — the spine of the map (ref A). Wide teal halo,
    // pale core, brightening along the travelled (gold) portion toward the temple.
    const full = pathThrough(pts, null);
    if (!full) return;
    el('path', { d: full, fill: 'none', stroke: C.pathGlow, 'stroke-width': 34, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.20, filter: 'url(#soft2)' }, g);
    el('path', { d: full, fill: 'none', stroke: C.pathEdge, 'stroke-width': 16, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.34, filter: 'url(#soft)' }, g);
    el('path', { d: full, fill: 'none', stroke: '#dfeecb', 'stroke-width': 6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.42 }, g);
    // dim dashed remainder (what's left to walk)
    el('path', { d: full, fill: 'none', stroke: 'rgba(235,240,215,.45)', 'stroke-width': 3.5, 'stroke-linecap': 'round', 'stroke-dasharray': '1 15' }, g);
    // travelled portion — bright luminous gold-white core with flowing dashes
    if (travelledUpto >= 1) {
      const gold = pathThrough(pts, travelledUpto + 1 > pts.length ? pts.length : travelledUpto + 1);
      el('path', { d: gold, fill: 'none', stroke: C.gold, 'stroke-width': 11, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.5, filter: 'url(#soft)' }, g);
      el('path', { d: gold, fill: 'none', stroke: 'url(#pathG)', 'stroke-width': 7, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', filter: 'url(#glow)' }, g);
      const flow = el('path', { d: gold, fill: 'none', stroke: '#ffffff', 'stroke-width': 2.6, 'stroke-linecap': 'round', 'stroke-dasharray': '2 22', opacity: 0.9 }, g);
      if (!reduced) anim(flow, 'stroke-dashoffset', '0', '-24', '1.6s', 'linear');
    }
    // a START marker at the foreground entrance + link up to the temple destination
    const s0 = pts[0];
    el('circle', { cx: s0.x, cy: s0.y, r: 7, fill: 'none', stroke: C.gold, 'stroke-width': 2, opacity: 0.8 }, g);
    // bead-markers along the trail (ref A) between nodes
    for (let i = 0; i < pts.length; i++) {
      const done = i < travelledUpto;
      el('circle', { cx: pts[i].x, cy: pts[i].y, r: 2.6, fill: done ? C.goldBright : 'rgba(235,240,215,.55)' }, g);
    }
  }

  function paintEdges(g, edges, posByPillar, statusByPillar) {
    // Prerequisite threads between grove medallions (spec §10). Kept SUBTLE so the
    // luminous main path stays the dominant spine — edges are faint connective vines,
    // brightest only where they tell the "what unlocks next" story (into active/available).
    const layer = el('g', { opacity: 0.9 }, g);
    edges.forEach(e => {
      const a = posByPillar[e.from], b = posByPillar[e.to];
      if (!a || !b) return;
      const st = statusByPillar[e.to];
      let stroke, w, dash, op;
      if (st === 'active') { stroke = C.teal; w = 1.8; dash = '4 6'; op = 0.6; }
      else if (st === 'unlocked') { stroke = C.teal; w = 1.2; dash = '3 7'; op = 0.32; }
      else if (st === 'blossoming') { stroke = C.gold; w = 1.2; dash = 'none'; op = 0.28; }
      else { stroke = '#3a4652'; w = 1; dash = '1 9'; op = 0.2; }   // locked → whisper only
      // curve the vine toward the path centre so it drapes rather than crosshatches
      const mx = (a.x + b.x) / 2 + (VB.w / 2 - (a.x + b.x) / 2) * 0.18;
      const my = (a.y + b.y) / 2 + 20;
      el('path', { d: 'M' + a.x + ',' + (a.y - 52) + ' Q' + mx + ',' + my + ' ' + b.x + ',' + (b.y - 52),
        fill: 'none', stroke: stroke, 'stroke-width': w, 'stroke-dasharray': dash, opacity: op, 'stroke-linecap': 'round' }, layer);
    });
  }

  // ============================================================================
  // GROVE NODE — a signature-hued tree + gold/teal medallion shrine + label band
  // ============================================================================
  function groveNode(g, grove, pt, opts) {
    opts = opts || {};
    const st = grove.status;
    const hue = opts.hue || signatureHue(grove.pillar);
    const s = pt.scale || 1;
    const grp = el('g', { transform: 'translate(' + pt.x + ',' + pt.y + ') scale(' + s.toFixed(2) + ')', class: 'grove ' + st }, g);
    if (opts.onClick && st !== 'locked') grp.style.cursor = 'pointer';

    // ground ring / rangoli decal
    const ringCol = st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? C.teal : C.locked;
    el('ellipse', { cx: 0, cy: 30, rx: 46, ry: 15, fill: 'none', stroke: ringCol, 'stroke-width': 1.5, opacity: st === 'locked' ? 0.3 : 0.55 }, grp);
    el('ellipse', { cx: 0, cy: 30, rx: 30, ry: 9, fill: 'none', stroke: ringCol, 'stroke-width': 1, opacity: st === 'locked' ? 0.2 : 0.35, 'stroke-dasharray': '3 5' }, grp);

    if (st === 'locked') {
      // bare frost-blue sapling at ~55% scale feel
      const t = el('g', { opacity: 0.55, transform: 'scale(.8)' }, grp);
      el('path', { d: 'M0,30 V-2', stroke: '#46525e', 'stroke-width': 4, 'stroke-linecap': 'round' }, t);
      el('path', { d: 'M0,6 l-14,-12 M0,6 l14,-12 M0,18 l-11,-9 M0,18 l11,-9', stroke: '#46525e', 'stroke-width': 3, 'stroke-linecap': 'round' }, t);
    } else {
      // signature-hued canopy: overlapping clustered volumes (a stand, not a blob)
      if (st === 'active') {
        const glow = el('circle', { cx: 0, cy: -18, r: 60, fill: 'url(#nodeTeal)', opacity: 0.5 }, grp);
        if (!opts.reduced) anim(glow, 'opacity', '0.55', '0.28', '3.4s');
        // rotating you-are-here ring
        const ring = el('circle', { cx: 0, cy: -18, r: 54, fill: 'none', stroke: C.teal, 'stroke-width': 2.2, 'stroke-dasharray': '6 8', opacity: 0.9 }, grp);
        if (!opts.reduced) { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0 0 -18', to: '360 0 -18', dur: '24s', repeatCount: 'indefinite' }); ring.appendChild(rot); }
      } else if (st === 'blossoming') {
        const glow = el('circle', { cx: 0, cy: -18, r: 52, fill: 'url(#nodeGold)', opacity: 0.5 }, grp);
        if (!opts.reduced) anim(glow, 'opacity', '0.55', '0.3', '5s');
      }
      canopy(grp, hue, st, opts.reduced, grove.pillar);
    }

    // MEDALLION — the consistent hit-target + state ring + glyph (spec §9)
    medallion(grp, st, ringCol, grove.pillar, opts.reduced);

    // LABEL band — permanently visible, dark plate, app serif (spec §9)
    const isCurrent = st === 'active';
    const labelTxt = opts.label != null ? opts.label : grove.pillar;
    const band = labelBand(grp, labelTxt, opts.meta != null ? opts.meta : metaFor(grove), st, isCurrent);
    // record for the declutter pass (current + hovered are never hidden)
    grp._label = band; grp._priority = isCurrent ? 3 : (st === 'unlocked' ? 2 : st === 'blossoming' ? 1 : 0);
    grp._nodePt = pt;
    grp.addEventListener('mouseenter', () => { if (band) band.style.display = ''; });

    // title tooltip
    const tt = el('title', {}, grp); tt.textContent = grove.pillar + ' — ' + grove.done + '/' + grove.total + ' · ' + st;
    if (opts.onClick && st !== 'locked') grp.addEventListener('click', () => opts.onClick(grove.pillar));
    return grp;

    function metaFor(gv) {
      return st === 'blossoming' ? '✦ MASTERED · ' + gv.done + '/' + gv.total
        : st === 'active' ? gv.done + '/' + gv.total + ' concepts'
        : st === 'unlocked' ? '◇ ' + gv.done + '/' + gv.total
        : '— locked';
    }
  }

  function canopy(grp, hue, st, reduced, seed) {
    const r = rng(seed + '|canopy');
    const t = el('g', {}, grp);
    // trunk (desaturated brown-violet, not orange)
    el('path', { d: 'M0,30 C-3,10 3,4 0,-6', stroke: '#4a3a44', 'stroke-width': 7, fill: 'none', 'stroke-linecap': 'round' }, t);
    el('path', { d: 'M0,30 C-3,10 3,4 0,-6', stroke: '#6a5560', 'stroke-width': 3, fill: 'none', 'stroke-linecap': 'round' }, t);
    // 6–8 overlapping foliage clusters in the signature hue ±value/hue jitter
    const clusters = 7;
    const sway = el('g', {}, t);
    for (let i = 0; i < clusters; i++) {
      const cx = (r() - 0.5) * 44, cy = -18 + (r() - 0.5) * 30, rad = 13 + r() * 12;
      const v = (r() - 0.5) * 0.28;
      const fill = shade(hue, v);
      el('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: rad.toFixed(1), fill: fill, opacity: 0.94 }, sway);
    }
    // lit rim highlights (key light from temple side, upper) + shaded undersides
    for (let i = 0; i < 3; i++) el('circle', { cx: (-8 + r() * 16).toFixed(1), cy: (-30 - r() * 8).toFixed(1), r: (8 + r() * 6).toFixed(1), fill: shade(hue, 0.35), opacity: 0.6 }, sway);
    for (let i = 0; i < 2; i++) el('circle', { cx: (-6 + r() * 12).toFixed(1), cy: (2 + r() * 6).toFixed(1), r: (9 + r() * 5).toFixed(1), fill: shade(hue, -0.4), opacity: 0.5 }, sway);
    // mastered: gold blossoms + a rising particle
    if (st === 'blossoming') {
      for (let i = 0; i < 6; i++) el('circle', { cx: ((r() - 0.5) * 50).toFixed(1), cy: (-24 + (r() - 0.5) * 34).toFixed(1), r: 2.4, fill: C.goldBright }, sway);
    }
    if (!reduced) { // gentle canopy sway
      const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', values: '-1.4 0 30;1.4 0 30;-1.4 0 30', dur: (5 + r() * 3).toFixed(1) + 's', repeatCount: 'indefinite' });
      sway.appendChild(rot);
    }
  }

  // Icon medallion above the tree: gold-rimmed circle + a per-pillar glyph.
  function medallion(grp, st, ringCol, name, reduced) {
    const y = -58;
    const rim = st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? C.teal : C.locked;
    const fill = st === 'blossoming' ? 'rgba(231,182,75,.9)' : st === 'active' ? 'rgba(18,77,76,.85)' : st === 'unlocked' ? 'rgba(10,20,26,.8)' : 'rgba(20,26,32,.7)';
    const m = el('g', { transform: 'translate(0,' + y + ')' }, grp);
    const rr = el('circle', { r: 15, fill: fill, stroke: rim, 'stroke-width': 2, opacity: st === 'locked' ? 0.5 : 1 }, m);
    if (st === 'active' && !reduced) anim(rr, 'stroke-width', '2', '3.4', '1.8s');
    const glyphCol = st === 'blossoming' ? '#3a2a08' : st === 'locked' ? '#5a6672' : C.goldBright;
    const gl = el('text', { x: 0, y: 5, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 14, fill: glyphCol }, m);
    gl.textContent = glyphFor(name);
  }

  // deterministic glyph per pillar keyword (ascii, so no font-dependency surprises)
  function glyphFor(name) {
    const n = (name || '').toLowerCase();
    if (/interpret|explain/.test(n)) return '◉';
    if (/rag|vector|retriev/.test(n)) return '⌘';
    if (/agent/.test(n)) return '⟁';
    if (/nlp|represent|language/.test(n)) return '¶';
    if (/graph/.test(n)) return '⊛';
    if (/math|theory|statist|econometr/.test(n)) return '∑';
    if (/time-?series|forecast/.test(n)) return '∿';
    if (/mlops|llmops/.test(n)) return '⚙';
    if (/system\s*design/.test(n)) return '▤';
    if (/genai|engineering|stack|deep learning|llm/.test(n)) return '❋';
    if (/python|object|backend|production/.test(n)) return '❭';
    if (/data structure|algorithm/.test(n)) return '≣';
    if (/cs found/.test(n)) return '⌂';
    return '✿';
  }

  function labelBand(grp, title, meta, st, isCurrent) {
    const y = 44;
    const w = Math.max(70, short(title, 22).length * 6.4 + 18);
    const band = el('g', { transform: 'translate(0,' + y + ')', class: 'lbl' }, grp);
    el('rect', { x: -w / 2, y: -1, width: w, height: isCurrent ? 34 : 30, rx: 6,
      fill: 'rgba(6,9,20,.72)', stroke: isCurrent ? C.teal : 'rgba(231,182,75,.28)', 'stroke-width': isCurrent ? 1.4 : 0.8 }, band);
    if (isCurrent) {
      const yah = el('text', { x: 0, y: -8, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.16em', fill: C.teal }, band);
      yah.textContent = 'YOU ARE HERE';
    }
    const t1 = el('text', { x: 0, y: 12, 'text-anchor': 'middle', 'font-family': 'Marcellus, serif', 'font-size': 12.5,
      fill: st === 'locked' ? C.parchMute : st === 'active' ? '#dcefe6' : C.parch }, band);
    t1.textContent = short(title, 24);
    const t2 = el('text', { x: 0, y: 24, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 8,
      'letter-spacing': '.04em', fill: st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? C.teal : C.parchMute }, band);
    t2.textContent = meta;
    band._w = w; band._y = y;
    return band;
  }

  // Declutter: hide the labels of lower-priority nodes when their bands would overlap,
  // but ALWAYS keep the current (active) node and its path-neighbours labelled (spec §9).
  // Runs on the placed nodes using their known band width + node position (no getBBox,
  // which is unreliable before layout / in headless).
  function declutterLabels(nodes, activeIdx) {
    const keep = new Set([activeIdx, activeIdx - 1, activeIdx + 1]);
    // priority: current > neighbours > unlocked > mastered > locked; ties by lower y (front)
    const idx = nodes.map((_, i) => i).sort((a, b) => {
      const ka = keep.has(a) ? 10 : nodes[a]._priority, kb = keep.has(b) ? 10 : nodes[b]._priority;
      if (ka !== kb) return kb - ka;
      return (nodes[b]._nodePt.y) - (nodes[a]._nodePt.y);
    });
    const placed = [];
    idx.forEach(i => {
      const g = nodes[i]; const band = g._label; if (!band) return;
      const pt = g._nodePt, s = pt.scale || 1;
      const w = (band._w || 90) * s + 8, h = 34 * s + 8;
      const cx = pt.x, cy = pt.y + (band._y || 44) * s + 15 * s;
      const box = { x: cx - w / 2, y: cy - h / 2, w: w, h: h };
      const collides = placed.some(b => !(box.x + box.w < b.x || b.x + b.w < box.x || box.y + box.h < b.y || b.y + b.h < box.y));
      if (collides && !keep.has(i)) { band.style.display = 'none'; }
      else { placed.push(box); }
    });
  }

  // ============================================================================
  // LIFE — fireflies, birds, player avatar (all reduced-motion aware)
  // ============================================================================
  function paintLife(g, pts, activeIdx, reduced) {
    // fireflies clustered near the path & light
    const r = rng('flies'); const ff = el('g', {}, g);
    for (let i = 0; i < 46; i++) {
      const anchor = pts[Math.floor(r() * pts.length)] || { x: VB.w / 2, y: VB.h / 2 };
      const x = anchor.x + (r() - 0.5) * 160, y = anchor.y + (r() - 0.5) * 120;
      const col = [C.gold, '#bfe9a0', C.teal][Math.floor(r() * 3)];
      const rad = 0.8 + r() * 1.6;
      const f = el('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: col, opacity: 0.9, filter: 'url(#glow)' }, ff);
      if (!reduced) {
        anim(f, 'opacity', '0.9', '0.15', (1.4 + r() * 2.2).toFixed(1) + 's');
        const dx = (r() - 0.5) * 40, dy = (r() - 0.5) * 34;
        animT(f, x.toFixed(0) + ',' + y.toFixed(0), (x + dx).toFixed(0) + ',' + (y + dy).toFixed(0), (5 + r() * 5).toFixed(1) + 's');
      }
    }
    // 3 gliding birds on looping arcs across the sky band
    if (!reduced) for (let i = 0; i < 3; i++) bird(g, 200 + i * 340, 150 + i * 26, 22 + i * 6, 'bird' + i);
    // player avatar at the active node (lantern-carrying silhouette) — scale + "where am I"
    const ap = pts[activeIdx] || pts[0];
    if (ap) {
      const s = ap.scale || 1;
      const av = el('g', { transform: 'translate(' + (ap.x + 26 * s) + ',' + (ap.y + 8 * s) + ') scale(' + (0.9 * s).toFixed(2) + ')' }, g);
      el('ellipse', { cx: 0, cy: 20, rx: 12, ry: 4, fill: 'rgba(0,0,0,.35)' }, av);
      el('path', { d: 'M0,-16 C-6,-16 -7,-6 -6,2 L-8,18 L8,18 L6,2 C7,-6 6,-16 0,-16 Z', fill: '#0e1518' }, av);
      el('circle', { cx: 0, cy: -20, r: 5, fill: '#13202024' }, av);
      el('circle', { cx: 0, cy: -20, r: 5, fill: '#14201f' }, av);
      const lan = el('circle', { cx: 11, cy: 2, r: 6, fill: 'url(#nodeGold)' }, av);
      el('circle', { cx: 11, cy: 2, r: 2, fill: C.goldBright }, av);
      if (!reduced) anim(lan, 'opacity', '1', '0.6', '2.4s');
    }
    function bird(parent, x, y, sz, seed) {
      const b = el('path', { d: 'M0,0 q-' + sz + ',-' + (sz * 0.5) + ' -' + (sz * 2) + ',0 q' + sz + ',-' + (sz * 0.5) + ' ' + (sz * 2) + ',0', fill: 'none', stroke: 'rgba(230,220,190,.5)', 'stroke-width': 2, 'stroke-linecap': 'round' }, parent);
      const mv = el('animateMotion', { dur: (22 + hash(seed) % 10) + 's', repeatCount: 'indefinite', rotate: 'auto',
        path: 'M' + x + ',' + y + ' q160,-40 320,10 q160,50 320,-10' });
      b.appendChild(mv);
      const wing = el('animate', { attributeName: 'd', dur: '0.5s', repeatCount: 'indefinite',
        values: 'M0,0 q-' + sz + ',-' + (sz * 0.5) + ' -' + (sz * 2) + ',0 q' + sz + ',-' + (sz * 0.5) + ' ' + (sz * 2) + ',0;' +
                'M0,0 q-' + sz + ',' + (sz * 0.3) + ' -' + (sz * 2) + ',0 q' + sz + ',' + (sz * 0.3) + ' ' + (sz * 2) + ',0;' +
                'M0,0 q-' + sz + ',-' + (sz * 0.5) + ' -' + (sz * 2) + ',0 q' + sz + ',-' + (sz * 0.5) + ' ' + (sz * 2) + ',0' });
      b.appendChild(wing);
    }
  }

  // ============================================================================
  // DIEGETIC HUD — compass rose, minimap, legend (drawn into the SVG, in-world)
  // ============================================================================
  function paintHUD(g, groves, pts, activeIdx, reduced, isDrill, title) {
    // ---- minimap (top-left) ----
    const mm = el('g', { transform: 'translate(20,20)', class: 'hud' }, g);
    el('rect', { x: 0, y: 0, width: 168, height: 116, rx: 8, fill: 'rgba(6,9,20,.78)', stroke: 'rgba(231,182,75,.35)', 'stroke-width': 1 }, mm);
    el('text', { x: 10, y: 16, 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.14em', fill: C.gold }, mm).textContent = isDrill ? 'GROVE MAP' : 'FOREST MAP';
    // scaled scatter of all nodes + the trail
    const mmx = 12, mmy = 26, mmw = 144, mmh = 78;
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    const y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const sx = v => mmx + (x1 === x0 ? 0.5 : (v - x0) / (x1 - x0)) * mmw;
    const sy = v => mmy + (y1 === y0 ? 0.5 : (v - y0) / (y1 - y0)) * mmh;
    let dd = ''; pts.forEach((p, i) => dd += (i ? 'L' : 'M') + sx(p.x).toFixed(1) + ',' + sy(p.y).toFixed(1) + ' ');
    el('path', { d: dd, fill: 'none', stroke: 'rgba(159,230,214,.5)', 'stroke-width': 1.2 }, mm);
    pts.forEach((p, i) => {
      const gv = groves[i]; const st = gv ? gv.status : 'locked';
      const col = st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? '#8fd0c8' : '#4a5662';
      const dot = el('circle', { cx: sx(p.x).toFixed(1), cy: sy(p.y).toFixed(1), r: i === activeIdx ? 3.4 : 2, fill: col }, mm);
      if (i === activeIdx && !reduced) anim(dot, 'r', '3.4', '2', '1.6s');
    });

    // ---- legend (below minimap) ----
    const lg = el('g', { transform: 'translate(20,148)', class: 'hud' }, g);
    el('rect', { x: 0, y: 0, width: 168, height: isDrill ? 58 : 74, rx: 8, fill: 'rgba(6,9,20,.72)', stroke: 'rgba(231,182,75,.28)', 'stroke-width': 1 }, lg);
    const items = isDrill
      ? [[C.gold, 'mastered'], [C.teal, 'available'], ['#4a5662', 'locked']]
      : [[C.gold, 'mastered'], [C.teal, 'you are here'], ['#8fd0c8', 'available'], ['#4a5662', 'locked']];
    items.forEach(([c, lab], i) => {
      const y = 16 + i * 15;
      el('circle', { cx: 14, cy: y - 3, r: 4.5, fill: c }, lg);
      el('text', { x: 26, y: y, 'font-family': 'JetBrains Mono, monospace', 'font-size': 9, fill: C.parchDim }, lg).textContent = lab;
    });

    // ---- compass rose (bottom-left, Indic ornamental) ----
    const cp = el('g', { transform: 'translate(64,' + (VB.h - 66) + ')', class: 'hud', opacity: 0.92 }, g);
    el('circle', { r: 34, fill: 'rgba(6,9,20,.7)', stroke: C.gold, 'stroke-width': 1.2 }, cp);
    el('circle', { r: 26, fill: 'none', stroke: 'rgba(231,182,75,.4)', 'stroke-width': 0.6, 'stroke-dasharray': '2 3' }, cp);
    // 8-point star
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4, long = i % 2 === 0;
      const r2 = long ? 30 : 16;
      el('line', { x1: 0, y1: 0, x2: (Math.sin(a) * r2).toFixed(1), y2: (-Math.cos(a) * r2).toFixed(1), stroke: long ? C.goldBright : 'rgba(231,182,75,.5)', 'stroke-width': long ? 2 : 1 }, cp);
    }
    el('circle', { r: 3, fill: C.goldBright }, cp);
    ['N', 'E', 'S', 'W'].forEach((d, i) => {
      const a = i * Math.PI / 2;
      el('text', { x: (Math.sin(a) * 40).toFixed(1), y: (-Math.cos(a) * 40 + 3.5).toFixed(1), 'text-anchor': 'middle', 'font-family': 'Cinzel, serif', 'font-size': 8, fill: C.gold }, cp).textContent = d;
    });

    // ---- title cartouche (bottom-center) ----
    const w = Math.max(220, (title || '').length * 9 + 60);
    const tc = el('g', { transform: 'translate(' + VB.w / 2 + ',' + (VB.h - 30) + ')', class: 'hud' }, g);
    el('rect', { x: -w / 2, y: -20, width: w, height: 34, rx: 17, fill: 'rgba(6,9,20,.7)', stroke: 'rgba(231,182,75,.35)', 'stroke-width': 1 }, tc);
    el('text', { x: 0, y: 3, 'text-anchor': 'middle', 'font-family': 'Cinzel, serif', 'font-weight': 700, 'font-size': 13, 'letter-spacing': '.14em', fill: C.goldBright }, tc).textContent = title || 'THE FOREST OF MASTERY';

    // ---- progress bar (bottom-right, ref A) ----
    const done = groves.filter(g => g.status === 'blossoming').length;
    const pct = groves.length ? done / groves.length : 0;
    const pb = el('g', { transform: 'translate(' + (VB.w - 200) + ',' + (VB.h - 34) + ')', class: 'hud' }, g);
    el('text', { x: 0, y: -6, 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.1em', fill: C.parchDim }, pb).textContent = 'GROVES MASTERED ' + done + '/' + groves.length;
    el('rect', { x: 0, y: 0, width: 180, height: 6, rx: 3, fill: 'rgba(6,9,20,.7)', stroke: 'rgba(231,182,75,.3)', 'stroke-width': 0.6 }, pb);
    el('rect', { x: 1, y: 1, width: Math.max(0, 178 * pct).toFixed(1), height: 4, rx: 2, fill: C.gold }, pb);
  }

  // ---- animation helpers (SMIL — no rAF loops, cheap + declarative) ----------
  function anim(node, attr, from, to, dur, calc) {
    const a = el('animate', { attributeName: attr, values: from + ';' + to + ';' + from, dur: dur, repeatCount: 'indefinite' });
    if (calc) a.setAttribute('calcMode', calc);
    node.appendChild(a);
  }
  function animT(node, from, to, dur) {
    node.appendChild(el('animateTransform', { attributeName: 'transform', type: 'translate', additive: 'sum', values: '0,0;' + (parseFloat(to.split(',')[0]) - parseFloat(from.split(',')[0])) + ',' + (parseFloat(to.split(',')[1]) - parseFloat(from.split(',')[1])) + ';0,0', dur: dur, repeatCount: 'indefinite' }));
  }

  // ============================================================================
  // PUBLIC — overview & drill-in
  // ============================================================================
  function prep(svg) {
    svg.setAttribute('viewBox', '0 0 ' + VB.w + ' ' + VB.h);
    // slice (cover) on wide screens for a full-bleed vista; on narrow/portrait screens
    // use meet so the corner HUD (minimap, compass) and frame stay on-screen and legible.
    const box = svg.getBoundingClientRect ? svg.getBoundingClientRect() : { width: 1200, height: 760 };
    const wide = box.width && box.height ? (box.width / box.height) >= (VB.w / VB.h) * 0.82 : true;
    svg.setAttribute('preserveAspectRatio', wide ? 'xMidYMid slice' : 'xMidYMid meet');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
  }

  function empty(svg, msg) {
    prep(svg);
    defs(svg, true);
    el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#skyG)' }, svg);
    paintSky(el('g', {}, svg), true);
    el('text', { x: VB.w / 2, y: VB.h / 2, 'text-anchor': 'middle', 'font-family': 'Marcellus, serif', 'font-size': 20, fill: C.parchDim }, svg)
      .textContent = msg || 'No forest yet — finish onboarding and Ekalavya will plant your groves.';
  }

  function showOverview(svg, opts) {
    opts = opts || {};
    const reduced = !!opts.reduced;
    prep(svg);
    return fetch('/api/forest').then(r => r.json()).then(c => {
      if (c.empty || !c.groves || !c.groves.length) { empty(svg); return null; }
      const groves = c.groves.slice();                 // already in journey order
      const lay = layout(groves.length);
      const pts = lay.pts;
      const activeIdx = Math.max(0, groves.findIndex(g => g.status === 'active'));
      const travelled = (() => {
        let i = groves.findIndex(g => g.status === 'active');
        if (i >= 0) return i + 1;
        return groves.filter(g => g.status === 'blossoming').length;
      })();

      defs(svg, reduced);
      const bg = el('g', {}, svg);
      paintSky(bg, reduced);
      paintHills(bg);
      paintTemple(bg, lay.temple, reduced);
      paintMist(bg, reduced);
      paintStands(bg);

      // edges (faint vines, drawn first/under) → then the luminous path (dominant spine)
      const world = el('g', {}, svg);
      const posByPillar = {}; groves.forEach((g, i) => posByPillar[g.pillar] = pts[i]);
      const statusByPillar = {}; groves.forEach(g => statusByPillar[g.pillar] = g.status);
      paintEdges(world, c.edges || [], posByPillar, statusByPillar);
      paintPath(world, pts, travelled, reduced, lay.temple);

      // draw nodes back-to-front (far/high first) so foreground groves overlap correctly
      const order = groves.map((g, i) => i).sort((a, b) => pts[a].y - pts[b].y);
      const nodeGroups = new Array(groves.length);
      order.forEach(i => { nodeGroups[i] = groveNode(world, groves[i], pts[i], {
        hue: signatureHue(groves[i].pillar), reduced: reduced,
        onClick: opts.onGrove ? (p) => opts.onGrove(p) : null
      }); });
      declutterLabels(nodeGroups, activeIdx);

      paintLife(world, pts, activeIdx, reduced);
      // foreground proscenium last (frames everything)
      paintFrame(svg);
      el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#vig)', 'pointer-events': 'none' }, svg);
      paintHUD(svg, groves, pts, activeIdx, reduced, false, 'THE FOREST OF MASTERY');
      return c;
    }).catch(() => { empty(svg, 'could not load the forest map.'); return null; });
  }

  function showGrove(svg, pillar, opts) {
    opts = opts || {};
    const reduced = !!opts.reduced;
    prep(svg);
    return fetch('/api/forest?pillar=' + encodeURIComponent(pillar)).then(r => r.json()).then(c => {
      if (c.empty || !c.concepts) { empty(svg); return null; }
      const hue = signatureHue(pillar);
      // map concept status → grove-status vocabulary so the same art applies
      const S = { done: 'blossoming', avail: 'active', lock: 'locked' };
      const groves = c.concepts.map(cc => ({ pillar: cc.name, status: S[cc.status] || 'locked', done: cc.status === 'done' ? 1 : 0, total: 1 }));
      const lay = layout(groves.length);
      const pts = lay.pts;
      const travelled = groves.filter(g => g.status === 'blossoming').length;
      const activeIdx = Math.max(0, groves.findIndex(g => g.status === 'active'));

      defs(svg, reduced);
      const bg = el('g', {}, svg);
      paintSky(bg, reduced);
      paintHills(bg);
      paintTemple(bg, lay.temple, reduced);
      paintMist(bg, reduced);
      paintStands(bg);

      const world = el('g', {}, svg);
      // intra-pillar edges (under) → luminous path (over)
      const posByName = {}; c.concepts.forEach((cc, i) => posByName[cc.name] = pts[i]);
      const statusByName = {}; groves.forEach(g => statusByName[g.pillar] = g.status);
      paintEdges(world, c.edges || [], posByName, statusByName);
      paintPath(world, pts, travelled, reduced, lay.temple);

      const order = groves.map((g, i) => i).sort((a, b) => pts[a].y - pts[b].y);
      const nodeGroups = new Array(groves.length);
      order.forEach(i => { nodeGroups[i] = groveNode(world, groves[i], pts[i], {
        hue: hue, reduced: reduced,
        label: c.concepts[i].name, meta: metaC(c.concepts[i].status),
        // an available/active concept is a "dive in and practise this" target
        onClick: (opts.onConcept && c.concepts[i].status !== 'lock') ? () => opts.onConcept(c.concepts[i].name, pillar) : null
      }); });
      declutterLabels(nodeGroups, activeIdx);

      paintLife(world, pts, activeIdx, reduced);
      paintFrame(svg);
      el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#vig)', 'pointer-events': 'none' }, svg);
      // back-to-overview affordance (top-right)
      const back = el('g', { transform: 'translate(' + (VB.w - 150) + ',30)', class: 'hud', style: 'cursor:pointer' }, svg);
      el('rect', { x: -8, y: -16, width: 138, height: 26, rx: 13, fill: 'rgba(6,9,20,.78)', stroke: 'rgba(231,182,75,.4)', 'stroke-width': 1 }, back);
      el('text', { x: 4, y: 2, 'font-family': 'JetBrains Mono, monospace', 'font-size': 10, fill: C.goldBright }, back).textContent = '← forest overview';
      if (opts.onBack) back.addEventListener('click', opts.onBack);
      paintHUD(svg, groves, pts, activeIdx, reduced, true, short(pillar, 30).toUpperCase());
      return c;
    }).catch(() => { empty(svg, 'could not load this grove.'); return null; });
    function metaC(s) { return s === 'done' ? '✦ mastered' : s === 'avail' ? '◇ available' : '— locked'; }
  }

  global.Forest2D = { showOverview: showOverview, showGrove: showGrove, VB: VB };
})(window);
