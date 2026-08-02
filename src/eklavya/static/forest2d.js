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

  // ---- TIME OF DAY (real local clock) ---------------------------------------
  // The world's light + which fauna are active shift with the wall clock: dawn / day /
  // dusk / night. Returns a phase name, a 0..1 "darkness" weight, sky tint stops, and a
  // day/night flag the fauna casting uses (day → songbirds/peacock/deer; night →
  // tiger/owl/fireflies/spirits, brighter diyas). Kept subtle + always legible.
  function timeOfDay() {
    const h = new Date().getHours();
    if (h >= 5 && h < 8)  return { phase: 'dawn',  dark: 0.55, night: false, warm: 0.8 };
    if (h >= 8 && h < 17) return { phase: 'day',   dark: 0.0,  night: false, warm: 0.35 };
    if (h >= 17 && h < 20) return { phase: 'dusk', dark: 0.5,  night: false, warm: 0.9 };
    return { phase: 'night', dark: 1.0, night: true, warm: 0.15 };
  }

  // ---- DIFFICULTY (0 easy … 1 hard) per grove, deterministic-from-data -------
  // Combines the grove's journey ORDER (later = deeper toward the frontier temple), its
  // STATUS (mastered/available are conquered/near; locked is the unknown ahead), and its
  // CONCEPT COUNT (a bigger grove is a bigger challenge). Drives which fauna guard it:
  // gentle near easy/mastered, dangerous guardians near hard/locked. Scales to any curriculum.
  function difficultyOf(grove, idx, n) {
    const order = n > 1 ? idx / (n - 1) : 0;                 // 0 foundations … 1 frontier
    const size = Math.min(1, ((grove.total || 3) - 2) / 8);  // concept-count pressure
    let statusW;
    switch (grove.status) {
      case 'blossoming': statusW = 0.0; break;               // mastered → tamed
      case 'active':     statusW = 0.35; break;              // you're on it
      case 'unlocked':   statusW = 0.5; break;               // available frontier
      default:           statusW = 0.85; break;              // locked → perilous unknown
    }
    return Math.min(1, order * 0.5 + statusW * 0.35 + size * 0.15);
  }

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
      // ground: layered forest floor — deep teal shadow near the treeline warming to a
      // mossy sunlit sward in the mid-band and darkening again into the foreground cover.
      grad('groundG', 0, 0, 0, 1, [[0, '#16302a'], [0.28, C.ground], [0.55, '#20402f'], [0.8, '#132923'], [1, '#0a1713']]),
      // a warm pool of light spilling down the centre from the temple onto the floor
      radial('floorLight', 50, 0, 90, [[0, 'rgba(231,190,110,.22)'], [0.45, 'rgba(120,160,120,.10)'], [1, 'rgba(120,160,120,0)']]),
      radial('templeGlow', 50, 46, 60, [[0, '#fff2c4'], [0.35, C.goldBright], [0.7, 'rgba(231,182,75,.35)'], [1, 'rgba(231,182,75,0)']]),
      radial('nodeGold', 50, 45, 60, [[0, '#fff3cf'], [0.4, C.gold], [1, 'rgba(231,182,75,0)']]),
      radial('nodeTeal', 50, 45, 60, [[0, '#d6fbf4'], [0.4, C.teal], [1, 'rgba(87,211,206,0)']]),
      radial('mistG', 50, 50, 60, [[0, 'rgba(180,205,225,.32)'], [0.6, 'rgba(150,190,210,.14)'], [1, 'rgba(180,200,220,0)']]),
      radial('moonG', 50, 50, 60, [[0, '#fbf3d8'], [0.5, 'rgba(247,231,197,.55)'], [1, 'rgba(247,231,197,0)']]),
      // --- mythological layers (added) --------------------------------------
      // sacred lotus-pond (kund): teal water lit by a warm rim where the diyas float
      radial('pondG', 50, 42, 62, [[0, 'rgba(120,224,214,.5)'], [0.4, 'rgba(46,163,160,.34)'], [0.8, 'rgba(18,77,76,.5)'], [1, 'rgba(9,26,26,.7)']]),
      // diya / oil-lamp flame — a warm ember teardrop of light
      radial('diyaG', 50, 55, 60, [[0, '#fff2c4'], [0.35, C.goldBright], [0.7, 'rgba(231,182,75,.4)'], [1, 'rgba(217,122,60,0)']]),
      // --- CREATURE CONTRAST + ENCHANTMENT halos -----------------------------
      // soft DARK vignette placed UNDER a creature so its silhouette separates from busy
      // foliage (the pop-against-background cue). Deepest at centre, fading to nothing.
      radial('critShade', 50, 55, 60, [[0, 'rgba(4,8,10,.55)'], [0.55, 'rgba(6,12,12,.34)'], [1, 'rgba(6,12,12,0)']]),
      // warm-gold SPIRIT aura (luminous deer / peacock / lantern-bearer)
      radial('spiritGold', 50, 50, 60, [[0, 'rgba(255,244,204,.85)'], [0.35, 'rgba(247,217,138,.5)'], [0.7, 'rgba(231,182,75,.16)'], [1, 'rgba(231,182,75,0)']]),
      // cool-teal SPIRIT aura (luminous naga / apsara / ghost-elephant)
      radial('spiritTeal', 50, 50, 60, [[0, 'rgba(214,251,244,.85)'], [0.35, 'rgba(120,224,214,.5)'], [0.7, 'rgba(87,211,206,.16)'], [1, 'rgba(87,211,206,0)']]),
      // divine radiance behind the temple shikhara (sacred sunburst glow)
      radial('divineG', 50, 50, 60, [[0, 'rgba(255,244,210,.55)'], [0.35, 'rgba(247,217,138,.28)'], [0.7, 'rgba(231,182,75,.10)'], [1, 'rgba(231,182,75,0)']]),
      // lotus / rangoli petal sheen
      grad('lotusG', 0, 0, 0, 1, [[0, '#fbe6b0'], [1, '#e7b64b']]),
      // canopy foliage: a rounded painterly leaf-mass with a lit crown and shaded belly
      radial('leafLit', 42, 32, 68, [[0, '#7fb488'], [0.5, '#4e8a5c'], [1, '#264b3c']]),
      radial('leafDark', 44, 34, 70, [[0, '#2b5245'], [0.55, '#1c3a30'], [1, '#0f2019']]),
      // luminous path: warm gold near the temple flowing to cool teal down at the entrance
      grad('pathFlow', 0, 0, 0, 1, [[0, '#f7e6a8'], [0.4, '#eaf0d0'], [1, '#bfeee0']]),
      grad('pathG', 0, 0, 0, 1, [[0, '#f4f7e0'], [1, '#dfeecb']]),
      // god-ray cone: bright at the temple, fading down over the map
      grad('rayG', 0, 0, 0, 1, [[0, 'rgba(255,238,190,.30)'], [0.5, 'rgba(247,217,138,.10)'], [1, 'rgba(247,217,138,0)']]),
      // vignette for edges
      radial('vig', 50, 46, 75, [[0, 'rgba(0,0,0,0)'], [0.72, 'rgba(0,0,0,0)'], [1, 'rgba(4,6,14,.72)']]),
      // soft blur filters
      '<filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="6"/></filter>',
      '<filter id="soft2" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="14"/></filter>',
      '<filter id="soft1" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.2"/></filter>',
      '<filter id="glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
      // NOTE: the per-creature `critRim` rim-light and `critGlow` spirit-bloom FILTERS were the
      // map's single biggest render cost (a multi-primitive blur+flood+composite chain applied
      // to every one of ~90 creatures over large regions). They're removed: creatures now rely
      // on the dark `critShade` contrast-vignette + coloured aura gradients already drawn beneath
      // them, so they still separate from foliage and spirit-animals still glow — with no filters.
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
  // INTERACTIVITY STYLES — hover/tap affordances via CSS (GPU-cheap transforms/opacity),
  // driven by element CLASSES so we never attach thousands of JS listeners. ALL motion is
  // wrapped in @media (prefers-reduced-motion: no-preference); a reduced-motion visitor
  // still gets the non-moving HIGHLIGHT (brightness/opacity) so the map stays interactive.
  // ============================================================================
  function injectStyles(svg) {
    // one shared stylesheet per rendered map (scoped by the ids/classes we emit).
    const style = el('style', {}, svg);
    style.textContent = [
      // when the map is off-screen / tab hidden, freeze every CSS keyframe animation (the SMIL
      // clock is paused separately) so ambient motion costs nothing while unseen.
      'svg.anim-paused *{animation-play-state:paused !important}',
      // groves are the primary target: pointer + smooth transitions on the interactive parts
      '.grove:not(.locked){cursor:pointer}',
      '.grove .lbl{transition:opacity .18s ease}',
      // hovered/highlighted edge threads light up (JS toggles .edge-hot)
      '.pedge{transition:opacity .2s ease, stroke-width .2s ease}',
      '.pedge.edge-hot{opacity:.92 !important; stroke-width:2.6 !important}',
      // creatures + ponds + diyas get a subtle pointer so they invite interaction
      '.crit,.pond,.diya{cursor:pointer}',
      // --- highlight (always on, even reduced-motion) ---
      '.grove:not(.locked):hover .g-bloom{opacity:.85}',
      '.grove:not(.locked):hover .g-medallion circle:first-of-type,.grove:not(.locked):focus .g-medallion circle:first-of-type{stroke-width:3.4}',
      '.grove:not(.locked):hover .lbl-plate{stroke-opacity:1}',
      '.pond:hover .pond-water{filter:brightness(1.18)}',
      '.diya:hover .diya-glow{opacity:1}',
      '@media (prefers-reduced-motion: no-preference){',
      // grove: gentle lift + scale-up bloom + faster rangoli spin on hover. The inner group
      // scales from the medallion; fill-box keeps the origin on the group's own box.
      '  .g-inner{transition:transform .22s cubic-bezier(.2,.8,.2,1); transform-box:fill-box; transform-origin:center 70%}',
      '  .grove:not(.locked):hover .g-inner{transform:translateY(-4px) scale(1.06)}',
      '  .g-bloom{transition:opacity .3s ease}',
      '  .g-rangoli{transform-box:fill-box; transform-origin:center}',
      '  .grove:not(.locked):hover .g-rangoli{animation:spin 7s linear infinite}',
      // creature micro-animations (only the hovered one animates) — fill-box so each part
      // rotates about its own geometry regardless of the creature's placement transform.
      '  .peacock-tail,.deer-head,.eleph-trunk,.naga-hood,.lotus-bloom{transform-box:fill-box}',
      '  .peacock-tail{transition:transform .35s cubic-bezier(.2,.8,.2,1); transform-origin:right center}',
      '  .crit-peacock:hover .peacock-tail{transform:scale(1.18)}',
      '  .deer-head{transition:transform .3s ease; transform-origin:left bottom}',
      '  .crit-deer:hover .deer-head{transform:rotate(-16deg)}',
      '  .eleph-trunk{transition:transform .35s ease; transform-origin:left top}',
      '  .crit-elephant:hover .eleph-trunk{transform:rotate(-20deg)}',
      '  .naga-hood{transform-origin:center bottom}',
      '  .crit-naga:hover .naga-hood{animation:sway 1.4s ease-in-out infinite}',
      '  .sage-aura{transition:opacity .3s ease}',
      '  .crit-guru:hover .sage-aura{animation:pulse 1.6s ease-in-out infinite}',
      '  .flock-g{transition:transform .3s ease; transform-box:fill-box}',
      '  .flock-g:hover{transform:translateY(-3px)}',
      '  .crit-perched:hover .crit-perched-body{animation:hop .4s ease-in-out infinite}',
      '  .pond:hover .pond-ripple{animation-duration:2.4s !important}',
      '  .lotus-bloom{transition:transform .4s ease; transform-box:fill-box; transform-origin:center}',
      '  .lotus-breathe{animation:breathe 6s ease-in-out infinite; animation-delay:var(--ph,0s)}',
      '  .pond:hover .lotus-bloom{animation:none; transform:scale(1.5)}',   // hover overrides breathe
      '  @keyframes breathe{0%,100%{transform:scale(0.82)}50%{transform:scale(1.15)}}',
      '  .diya-flame{transition:transform .2s ease; transform-box:fill-box; transform-origin:center bottom}',
      '  .diya:hover .diya-flame{animation:flick .3s ease-in-out infinite}',
      // ================= AMBIENT (always-on) micro-life ===================
      // A deterministic SUBSET of creatures carry `.ambient` (capped, so we never animate the
      // whole cast at once) + an inline `--ph` phase so the loops are staggered/organic. All
      // use transform/opacity only (compositor-friendly) and live inside this reduced-motion
      // media block, so prefers-reduced-motion stops every bit of it. `fill-box` keeps each
      // part rotating about its own geometry regardless of the creature's placement transform.
      '  .amb,.amb-body{transform-box:fill-box}',
      '  .crit-deer.ambient .deer-head{animation:graze 5.5s ease-in-out infinite; animation-delay:var(--ph,0s); transform-origin:left bottom}',
      '  .crit-deer.ambient .deer-tail{animation:flick2 2.6s ease-in-out infinite; animation-delay:var(--ph,0s)}',
      '  .crit-peacock.ambient .peacock-tail{animation:shimmer 4.5s ease-in-out infinite; animation-delay:var(--ph,0s); transform-origin:right center}',
      '  .crit-monkey.ambient .amb-body{animation:bob 2.8s ease-in-out infinite; animation-delay:var(--ph,0s)}',
      '  .crit-monkey-swing.ambient .amb-body{animation:swingm 3.2s ease-in-out infinite; animation-delay:var(--ph,0s); transform-origin:center top}',
      '  .crit-naga.ambient .naga-hood{animation:slither 4s ease-in-out infinite; animation-delay:var(--ph,0s); transform-origin:center bottom}',
      '  .crit-elephant.ambient .amb-body{animation:esway 6s ease-in-out infinite; animation-delay:var(--ph,0s)}',
      '  .crit-elephant.ambient .eleph-trunk{animation:trunk 5s ease-in-out infinite; animation-delay:var(--ph,0s); transform-origin:left top}',
      '  .crit-perched.ambient .crit-perched-body{animation:tweet 3.4s ease-in-out infinite; animation-delay:var(--ph,0s)}',
      // FLORA breeze: a bounded subset of trees + understorey sway. Trees get `.breeze`,
      // grass/ferns get `.gbreeze` — both staggered by inline --ph.
      '  .breeze{animation:treesway 6.5s ease-in-out infinite; animation-delay:var(--ph,0s); transform-box:fill-box; transform-origin:center bottom}',
      '  .gbreeze{animation:grasswave 4.2s ease-in-out infinite; animation-delay:var(--ph,0s); transform-box:fill-box; transform-origin:center bottom}',
      // hovering a tree rustles it harder (faster, wider sway); hovering a flock scatters it.
      '  .tree-breeze:hover{animation:treerustle 0.6s ease-in-out infinite; cursor:default}',
      '  .flock:hover .flock-bird{animation:scatter 0.5s ease-out forwards}',
      '  @keyframes treerustle{0%,100%{transform:rotate(-3deg)}50%{transform:rotate(3deg)}}',
      '  @keyframes scatter{to{transform:translate(var(--sx,4px),var(--sy,-3px))}}',
      '  @keyframes spin{to{transform:rotate(360deg)}}',
      '  @keyframes sway{0%,100%{transform:rotate(-6deg)}50%{transform:rotate(6deg)}}',
      '  @keyframes pulse{0%,100%{opacity:.35}50%{opacity:.85}}',
      '  @keyframes flick{0%,100%{transform:scaleY(1)}50%{transform:scaleY(1.28) translateY(-1px)}}',
      '  @keyframes graze{0%,72%,100%{transform:rotate(0)}84%{transform:rotate(24deg)}}',   // head dips to graze
      '  @keyframes flick2{0%,88%,100%{transform:rotate(0)}94%{transform:rotate(-14deg)}}',  // tail flick
      '  @keyframes shimmer{0%,100%{transform:scaleX(1) scaleY(1)}50%{transform:scaleX(1.05) scaleY(1.03)}}',
      '  @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-2.2px)}}',
      '  @keyframes swingm{0%,100%{transform:rotate(-7deg)}50%{transform:rotate(7deg)}}',
      '  @keyframes slither{0%,100%{transform:rotate(-5deg)}50%{transform:rotate(5deg)}}',
      '  @keyframes esway{0%,100%{transform:translateX(-1px) rotate(-1deg)}50%{transform:translateX(1px) rotate(1deg)}}',
      '  @keyframes trunk{0%,100%{transform:rotate(0)}50%{transform:rotate(-10deg)}}',
      '  @keyframes tweet{0%,80%,100%{transform:translateY(0)}90%{transform:translateY(-1.6px)}}',
      '  @keyframes hop{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}',
      '  @keyframes treesway{0%,100%{transform:rotate(-1.1deg)}50%{transform:rotate(1.1deg)}}',
      '  @keyframes grasswave{0%,100%{transform:skewX(-4deg)}50%{transform:skewX(4deg)}}',
      // PROXIMITY reactivity: a predator the cursor nears BRISTLES — a taut alert quiver + its
      // eye-halo flares (the guardian turns to face). Prey get an inline flee-transform in JS.
      '  [data-react="pred"].react-on{animation:bristle .5s ease-in-out infinite}',
      '  [data-react="pred"].react-on .crit-spark,[data-react="pred"].react-on circle[fill^="rgba(255"]{opacity:1 !important}',
      '  @keyframes bristle{0%,100%{transform:translateY(0)}25%{transform:translateY(-0.6px) scale(1.02)}75%{transform:translateY(0.4px)}}',
      '}'
    ].join('');
  }

  // Delegated hover wiring: ONE set of listeners on the svg root (not per-element). When a
  // grove is hovered/focused/tapped, light up the prerequisite EDGES connected to it (its
  // route through the forest). Cheap: we only toggle a class on the few matching edges.
  function wireHover(svg) {
    const edgesFor = pillar => svg.querySelectorAll('.pedge[data-from="' + cssEsc(pillar) + '"], .pedge[data-to="' + cssEsc(pillar) + '"]');
    let hotEdges = [];
    const clearHot = () => { hotEdges.forEach(e => e.classList.remove('edge-hot')); hotEdges = []; };
    const lightRoute = grove => {
      clearHot();
      const pillar = grove && grove._pillar;
      if (!pillar) return;
      hotEdges = Array.prototype.slice.call(edgesFor(pillar));
      hotEdges.forEach(e => e.classList.add('edge-hot'));
    };
    const groveOf = t => { while (t && t !== svg) { if (t.classList && t.classList.contains('grove')) return t; t = t.parentNode; } return null; };
    svg.addEventListener('mouseover', e => { const g = groveOf(e.target); if (g) lightRoute(g); });
    svg.addEventListener('mouseout', e => { const g = groveOf(e.target); if (g && !g.contains(e.relatedTarget)) clearHot(); });
    svg.addEventListener('focusin', e => { const g = groveOf(e.target); if (g) lightRoute(g); });
    svg.addEventListener('focusout', clearHot);
    // touch: a tap on a grove lights its route briefly (selection/dive-in still handled by click)
    svg.addEventListener('touchstart', e => { const g = groveOf(e.target); if (g) lightRoute(g); }, { passive: true });
  }
  function cssEsc(s) { return (s || '').replace(/["\\]/g, '\\$&'); }

  // Subtle CURSOR PARALLAX — near layers shift a hair more than far ones as the pointer
  // moves, so the scene feels alive & 3-D. rAF-throttled, pointer-only, reduced-motion-off.
  function wireParallax(svg, layers, reduced) {
    if (reduced || !window.matchMedia || !window.matchMedia('(pointer:fine)').matches) return;
    let tx = 0, ty = 0, raf = 0;
    const apply = () => { raf = 0; layers.forEach(({ node, k }) => { node.setAttribute('transform', 'translate(' + (tx * k).toFixed(2) + ',' + (ty * k).toFixed(2) + ')'); }); };
    svg.addEventListener('pointermove', e => {
      const r = svg.getBoundingClientRect(); if (!r.width) return;
      tx = ((e.clientX - r.left) / r.width - 0.5) * 2;   // -1 … 1
      ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
      if (!raf) raf = requestAnimationFrame(apply);
    });
    svg.addEventListener('pointerleave', () => { tx = 0; ty = 0; if (!raf) raf = requestAnimationFrame(apply); });
  }

  // Pause ALL ambient motion (SMIL + CSS) whenever the Forest map is OFF-SCREEN or the tab is
  // hidden, so the animation cost is only paid while the learner is actually looking at it.
  // Uses the SVG's own SMIL clock (pause/unpauseAnimations) + a CSS class that freezes the CSS
  // keyframes. Reduced-motion maps have no motion, so we no-op there.
  function wireVisibilityPause(svg, reduced) {
    if (reduced) return;
    let paused = false;
    const pause = () => { if (paused) return; paused = true; try { svg.pauseAnimations(); } catch (e) {} svg.classList.add('anim-paused'); };
    const play = () => { if (!paused) return; paused = false; try { svg.unpauseAnimations(); } catch (e) {} svg.classList.remove('anim-paused'); };
    const onVis = () => { if (document.hidden) pause(); else if (onScreen) play(); };
    let onScreen = true;
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(entries => {
        onScreen = entries[0].isIntersecting;
        if (!onScreen || document.hidden) pause(); else play();
      }, { threshold: 0.01 });
      io.observe(svg);
    }
    document.addEventListener('visibilitychange', onVis);
  }

  // ============================================================================
  // BACKGROUND LAYERS — sky, moon/stars, hills, temple, mist
  // ============================================================================
  function paintSky(g, reduced, groves) {
    const tod = timeOfDay();
    el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#skyG)' }, g);
    // TIME-OF-DAY grade: a full-frame wash that warms the sky at dawn/dusk, brightens it by
    // day, and deepens it at night — blended with the progress-driven warmth (more mastered
    // groves → a touch more golden dawn behind the temple). One cheap rect, no filter.
    const mastered = groves && groves.length ? groves.filter(gv => gv.status === 'blossoming').length / groves.length : 0;
    const grade = (() => {
      if (tod.phase === 'day')  return 'rgba(150,190,210,.10)';   // bright, cool-clear
      if (tod.phase === 'dawn') return 'rgba(247,190,110,.16)';   // warm gold low sun
      if (tod.phase === 'dusk') return 'rgba(217,122,60,.18)';    // amber sunset
      return 'rgba(10,14,34,.34)';                                 // deep indigo night
    })();
    el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: grade, 'pointer-events': 'none' }, g);
    // progress-dawn: a warm horizon glow behind the temple that grows with mastery (the whole
    // world subtly warming as the learner advances) — strongest by day-agnostic, gated to not
    // wash a bright noon. cheap radial.
    if (mastered > 0.05) el('ellipse', { cx: VB.w * 0.5, cy: 150, rx: 520, ry: 180, fill: 'rgba(247,217,138,' + (0.06 + mastered * 0.16).toFixed(2) + ')', 'pointer-events': 'none' }, g);
    // stars — full & bright at night, faint by day (day sky isn't starless-black but the
    // stars recede). Density unchanged (perf), opacity scaled by darkness.
    const starOp = 0.15 + tod.dark * 0.85;
    const r = rng('stars'); const stars = el('g', { opacity: starOp.toFixed(2) }, g);
    for (let i = 0; i < 76; i++) {
      const x = r() * VB.w, y = r() * VB.h * 0.42, rad = 0.5 + r() * 1.3, o = 0.25 + r() * 0.55;
      const s = el('circle', { cx: x.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: '#f4ecd6', opacity: o.toFixed(2) }, stars);
      // only a TWINKLING SUBSET animates (every 3rd) — 90 simultaneous opacity-tweens up in the
      // sky forced scattered repaints for little visual gain; the rest are static points.
      if (!reduced && i % 3 === 0) anim(s, 'opacity', o.toFixed(2), (o * 0.35).toFixed(2), (2.5 + r() * 4).toFixed(1) + 's');
    }
    // soft constellation arc across the night — a few sacred asterisms joined by hairlines
    const cg = el('g', { opacity: 0.5 }, g);
    const cr = rng('constel');
    const asterism = [[0.14, 0.10], [0.20, 0.06], [0.27, 0.12], [0.33, 0.07], [0.40, 0.13],
                      [0.60, 0.09], [0.67, 0.05], [0.72, 0.12], [0.80, 0.07]];
    let cd = '';
    asterism.forEach(([fx, fy], i) => {
      const x = fx * VB.w, y = fy * VB.h;
      cd += (i && i !== 5 ? 'L' : 'M') + x.toFixed(0) + ',' + y.toFixed(0) + ' ';
      el('circle', { cx: x.toFixed(0), cy: y.toFixed(0), r: (1.4 + cr()).toFixed(1), fill: '#fbf3d8', opacity: 0.85 }, cg);
    });
    el('path', { d: cd, fill: 'none', stroke: 'rgba(247,231,197,.28)', 'stroke-width': 0.6 }, cg);

    // the celestial body (upper-right): by DAY a warm SUN disc; at dawn/dusk/night a crescent
    // MOON haloed by a lunar mandala. Same position + mandala, different disc — so the sky
    // instantly reads as the right time of day.
    const mg = el('g', { transform: 'translate(' + (VB.w * 0.8) + ',96)' }, g);
    el('circle', { r: 74, fill: 'url(#moonG)' }, mg);
    // mandala halo: two dotted rings + a radiating spoke wreath (sacred geometry)
    const mand = el('g', { opacity: 0.4 }, mg);
    el('circle', { r: 46, fill: 'none', stroke: 'rgba(247,231,197,.5)', 'stroke-width': 0.6, 'stroke-dasharray': '1 5' }, mand);
    el('circle', { r: 54, fill: 'none', stroke: 'rgba(231,182,75,.4)', 'stroke-width': 0.5 }, mand);
    for (let i = 0; i < 24; i++) {
      const a = i * Math.PI / 12, r1 = 46, r2 = i % 2 ? 51 : 58;
      el('line', { x1: (Math.cos(a) * r1).toFixed(1), y1: (Math.sin(a) * r1).toFixed(1), x2: (Math.cos(a) * r2).toFixed(1), y2: (Math.sin(a) * r2).toFixed(1), stroke: 'rgba(247,231,197,.45)', 'stroke-width': 0.5 }, mand);
    }
    if (!reduced) { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0', to: '360', dur: '140s', repeatCount: 'indefinite' }); mand.appendChild(rot); }
    if (tod.phase === 'day') {
      // bright warm sun — a full disc with a soft corona
      el('circle', { r: 34, fill: 'rgba(255,236,170,.5)' }, mg);
      el('circle', { r: 24, fill: '#fff2c4' }, mg);
    } else {
      el('circle', { r: 26, fill: '#f7ecd0' }, mg);
      el('circle', { cx: 11, cy: -6, r: 24, fill: C.skyMid }, mg);  // crescent bite
    }
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

  // Golden temple — a stepped shikhara/stupa complex, the journey's destination. The temple
  // RESPONDS TO PROGRESS (backlog): dim + a shut gate when far from completion; steadily
  // brighter, then blazing with an OPEN gate as the mastered-fraction rises — so the goal
  // visibly pulls the learner forward. `pct` is the mastered-grove fraction (0..1).
  function paintTemple(g, tp, reduced, groves) {
    const pct = (groves && groves.length) ? groves.filter(gv => gv.status === 'blossoming').length / groves.length : 0;
    const lum = 0.35 + pct * 0.65;               // overall temple luminance 0.35 (far) … 1 (done)
    const gateOpen = pct >= 0.999;               // the sanctum gate opens only at full mastery
    // divine radiance — grows from a faint ember to a broad sacred sunburst as pct rises
    const divine = el('circle', { cx: tp.x, cy: tp.y + 20, r: (150 + pct * 90).toFixed(0), fill: 'url(#divineG)', opacity: (0.4 + pct * 0.6).toFixed(2) }, g);
    if (!reduced) anim(divine, 'opacity', (0.4 + pct * 0.6).toFixed(2), (0.28 + pct * 0.42).toFixed(2), '8s');
    // a slow-turning aureole of fine rays (nimbus) — brighter with progress
    const aur = el('g', { transform: 'translate(' + tp.x + ',' + (tp.y + 10) + ')', opacity: (0.14 + pct * 0.3).toFixed(2) }, g);
    for (let i = 0; i < 40; i++) {
      const a = i * Math.PI / 20, r1 = 96, r2 = i % 2 ? 150 : 186;
      el('line', { x1: (Math.cos(a) * r1).toFixed(1), y1: (Math.sin(a) * r1).toFixed(1), x2: (Math.cos(a) * r2).toFixed(1), y2: (Math.sin(a) * r2).toFixed(1), stroke: 'rgba(247,217,138,.5)', 'stroke-width': i % 2 ? 1.4 : 0.7 }, aur);
    }
    if (!reduced) { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0 0 10', to: '360 0 10', dur: '120s', repeatCount: 'indefinite', additive: 'sum' }); aur.appendChild(rot); }
    const glow = el('circle', { cx: tp.x, cy: tp.y + 6, r: (110 + pct * 70).toFixed(0), fill: 'url(#templeGlow)', opacity: (0.5 + pct * 0.5).toFixed(2) }, g);
    if (!reduced) anim(glow, 'opacity', (0.5 + pct * 0.5).toFixed(2), (0.4 + pct * 0.32).toFixed(2), '6s');
    // the shikhara itself dims a touch when far from completion (a distant, quiet goal) and
    // brightens to full gold as pct rises — architecture stays fully readable throughout.
    const t = el('g', { transform: 'translate(' + tp.x + ',' + tp.y + ')', opacity: (0.7 + pct * 0.3).toFixed(2) }, g);
    // short light shafts fanning down from the temple onto the treeline (long overlay rays
    // are drawn in paintGodRays, above the ground, so they read over the forest).
    const rays = el('g', { opacity: 0.5, filter: 'url(#soft2)' }, t);
    for (let i = -2; i <= 2; i++) {
      el('path', { d: 'M0,-8 L' + (i * 60 - 40) + ',230 L' + (i * 60 + 40) + ',230 Z', fill: 'rgba(247,217,138,.10)' }, rays);
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
      // KALASH finial — a small pot-and-sphere crowning the shikhara (amalaka + kalasha)
      const ky = y - 26;
      el('ellipse', { cx: 0, cy: ky - 2, rx: 5, ry: 2, fill: C.goldDeep }, gg);            // amalaka disc
      el('path', { d: 'M-4,' + (ky - 2) + ' Q0,' + (ky - 14) + ' 4,' + (ky - 2) + ' Z', fill: C.goldBright }, gg);  // pot
      el('circle', { cx: 0, cy: ky - 15, r: 2.6, fill: '#fff3cf' }, gg);                     // sphere
      el('line', { x1: 0, y1: ky - 17, x2: 0, y2: ky - 24, stroke: C.goldBright, 'stroke-width': 1 }, gg);
      el('circle', { cx: 0, cy: ky - 25, r: 1.4, fill: '#fff8e4' }, gg);
    }
    // --- TORANA gateway: two ornate pillars + a scalloped arch framing the sanctum ---
    const tor = el('g', { opacity: 0.94 }, t);
    [-108, 108].forEach(px => {
      el('rect', { x: px - 8, y: 40, width: 16, height: 54, rx: 2, fill: C.goldDeep }, tor);
      el('rect', { x: px - 8, y: 40, width: 5, height: 54, fill: C.gold, opacity: 0.6 }, tor);   // lit edge
      el('rect', { x: px - 12, y: 36, width: 24, height: 7, rx: 2, fill: C.gold }, tor);         // capital
      el('rect', { x: px - 12, y: 88, width: 24, height: 6, rx: 2, fill: C.goldDeep }, tor);     // base
    });
    // torana arch (double scallop) spanning the pillars
    el('path', { d: 'M-108,40 Q0,-24 108,40', fill: 'none', stroke: C.gold, 'stroke-width': 5 }, tor);
    el('path', { d: 'M-108,44 Q0,-14 108,44', fill: 'none', stroke: C.goldBright, 'stroke-width': 2, opacity: 0.7 }, tor);
    // little scalloped pendants hanging under the arch
    for (let i = -3; i <= 3; i++) {
      const px = i * 30, py = 40 - (1 - Math.abs(i) / 3.4) * 44;
      el('path', { d: 'M' + (px - 4) + ',' + py + ' Q' + px + ',' + (py + 9) + ' ' + (px + 4) + ',' + py + ' Z', fill: C.goldBright, opacity: 0.8 }, tor);
    }
    // sanctum GATE — RESPONDS TO PROGRESS. Far from completion it's a SHUT dark gate (two
    // door-leaves, only a thin light seam); as pct rises the inner light strengthens; at full
    // mastery the gate stands OPEN with a blazing sanctum behind it. The archway frame is always
    // drawn; the door-leaves + inner glow reflect the state.
    const door = el('g', {}, t);
    const arch = 'M-16,94 L-16,58 Q0,44 16,58 L16,94 Z';
    // inner sanctum light — dim ember when locked, blazing gold when open
    const innerOp = 0.28 + pct * 0.72;
    const innerAttrs = { d: arch, fill: gateOpen ? 'rgba(255,244,196,.95)' : ('rgba(255,240,196,' + innerOp.toFixed(2) + ')') };
    if (gateOpen) innerAttrs.filter = 'url(#glow)';
    el('path', innerAttrs, door);
    if (!gateOpen) {
      // two shut door-leaves covering the sanctum (darker the further from completion)
      const leafShade = shade('#5a3a12', pct * 0.4);
      el('path', { d: 'M-15,93 L-15,58 Q-8,49 0,49 L0,93 Z', fill: leafShade, stroke: C.goldDeep, 'stroke-width': 0.8 }, door);
      el('path', { d: 'M15,93 L15,58 Q8,49 0,49 L0,93 Z', fill: shade(leafShade, -0.06), stroke: C.goldDeep, 'stroke-width': 0.8 }, door);
      // a thin warm light seam between the leaves (hope) + door-ring handles
      el('line', { x1: 0, y1: 50, x2: 0, y2: 93, stroke: '#ffe9ad', 'stroke-width': 1, opacity: (0.4 + pct * 0.5).toFixed(2) }, door);
      el('circle', { cx: -5, cy: 74, r: 1.6, fill: C.goldBright, opacity: 0.7 }, door); el('circle', { cx: 5, cy: 74, r: 1.6, fill: C.goldBright, opacity: 0.7 }, door);
    } else {
      // OPEN: the aum glyph shines in the blazing sanctum; the leaves are swung aside
      el('text', { x: 0, y: 80, 'text-anchor': 'middle', 'font-family': 'Tiro Devanagari Hindi, serif', 'font-size': 20, fill: '#7a4a12' }, door).textContent = 'ॐ';
      el('path', { d: 'M-15,93 L-15,58 Q-13,54 -11,53 L-11,93 Z', fill: '#5a3a12', opacity: 0.8 }, door);   // leaf swung to the jamb
      el('path', { d: 'M15,93 L15,58 Q13,54 11,53 L11,93 Z', fill: '#4a300f', opacity: 0.8 }, door);
    }
    el('path', { d: arch, fill: 'none', stroke: C.goldDeep, 'stroke-width': 2 }, door);
    // flanking diyas — brighter after dusk / with progress
    const tod = timeOfDay();
    const diyaBoost = (tod.night || tod.phase === 'dusk') ? 1 : 0.85;
    [-40, 40].forEach(dx => { el('circle', { cx: dx, cy: 90, r: (5 + pct * 2).toFixed(1), fill: 'url(#diyaG)', opacity: diyaBoost }, door); el('circle', { cx: dx, cy: 90, r: 1.6, fill: '#fff8e4' }, door); });
    // marigold TORAN garland swagging across the front of the plinth
    const gar = el('g', {}, t);
    for (let i = 0; i <= 26; i++) {
      const fx = -150 + (i / 26) * 300;
      const sag = Math.sin((i / 26) * Math.PI) * 10;
      el('circle', { cx: fx.toFixed(0), cy: (66 + sag).toFixed(0), r: 3, fill: i % 3 ? C.gold : C.ember, opacity: 0.9 }, gar);
    }
  }

  function paintMist(g, reduced) {
    for (let i = 0; i < 4; i++) {
      const y = 250 + i * 42, w = 420 + i * 90, x = (i % 2 ? VB.w * 0.32 : VB.w * 0.66);
      const m = el('ellipse', { cx: x, cy: y, rx: w, ry: 44, fill: 'url(#mistG)', opacity: 0.5 }, g);
      if (!reduced) { const dur = (26 + i * 6) + 's'; const dx = (i % 2 ? 40 : -40);
        animT(m, x + ',' + y, (x + dx) + ',' + y, dur); }
    }
    // low drifting mist ribbons over the forest floor (softens the treeline seam, depth)
    for (let i = 0; i < 3; i++) {
      const y = 470 + i * 80, x = (i % 2 ? VB.w * 0.6 : VB.w * 0.4);
      const m = el('ellipse', { cx: x, cy: y, rx: 560, ry: 30, fill: 'url(#mistG)', opacity: 0.28 }, g);
      if (!reduced) { animT(m, x + ',' + y, (x + (i % 2 ? -34 : 34)) + ',' + y, (34 + i * 8) + 's'); }
    }
  }

  // Long soft god-rays raking down from the temple across the whole forest (drawn ABOVE
  // the ground so the beams read over the trees — the reference art's signature light).
  function paintGodRays(g, tp, reduced) {
    // the big full-map god-ray cone: its fill already fades to transparent (rayG), so the
    // large-region soft2 blur was redundant cost — dropped.
    const rays = el('g', { opacity: 0.5, 'pointer-events': 'none',
      transform: 'translate(' + tp.x + ',' + (tp.y + 30) + ')' }, g);
    for (let i = -3; i <= 3; i++) {
      const spread = i * 92, top = i * 20;
      el('path', { d: 'M' + (top - 26) + ',0 L' + (spread - 120) + ',560 L' + (spread + 120) + ',560 L' + (top + 26) + ',0 Z', fill: 'url(#rayG)' }, rays);
    }
    if (!reduced) anim(rays, 'opacity', '0.5', '0.32', '9s');
  }

  // ============================================================================
  // FOLIAGE STANDS (midground) + PROSCENIUM FRAME (foreground) — depth + framing
  // ============================================================================
  // A single illustrated forest tree — layered painterly canopy with a lit crown, a
  // shaded belly, a tapering trunk and a soft cast shadow. `kind` varies the silhouette so
  // the wood reads as a mix of banyan / round / willow / spire, not one stamp repeated.
  // a spread of canopy tints — jewel greens/teals plus rarer plum/amber accents, so the
  // forest canopy reads rich and varied while staying inside the indigo/gold/teal world.
  // [belly, body, lit, rim] base hues; tone then lightens them for depth.
  const CANOPY_TINTS = [
    ['#132a22', '#1c3a30', '#3f7a58', '#6fae82'],   // classic jade (workhorse)
    ['#122a2a', '#1a4040', '#37877f', '#63c0b0'],   // teal-cedar
    ['#16301f', '#22482c', '#4d8f52', '#7cc077'],   // brighter emerald
    ['#0f2a26', '#183f3a', '#2f8478', '#57d3ce'],   // peacock-teal (rarer, luminous)
    ['#1c2836', '#2a3f52', '#4e7a8f', '#7fb0c8'],   // dusk blue-green (atmospheric, far)
    ['#241f36', '#33304e', '#6b6ca8', '#9a8fd0'],   // plum accent (rare)
    ['#2a2417', '#463a1f', '#9a7d3a', '#d9b45a']    // amber-olive accent (rare, warm)
  ];
  function forestTree(parent, sc, tone, kind, r, sway, tintIdx) {
    // tone in [0,1]: 0 = deep-shadow filler, 1 = lit near-tree. Blends toward teal-green.
    // tintIdx (optional) picks a canopy tint; default weights toward the greens.
    if (tintIdx == null) { const roll = r(); tintIdx = roll < 0.5 ? Math.floor(r() * 3) : roll < 0.78 ? 3 : roll < 0.9 ? 4 : roll < 0.96 ? 5 : 6; }
    const T = CANOPY_TINTS[tintIdx % CANOPY_TINTS.length];
    const belly = shade(T[0], tone * 0.10);
    const body = shade(T[1], 0.04 + tone * 0.24);
    const lit = shade(T[2], 0.06 + tone * 0.34);
    const rim = shade(T[3], 0.05 + tone * 0.28);
    const trunkCol = shade('#241c26', tone * 0.18);
    const t = el('g', { transform: 'scale(' + sc.toFixed(2) + ')' }, parent);
    // cast shadow pooled at the base (soft-edged via low opacity; no per-tree blur FILTER —
    // this fires once per tree across the whole forest, so a live blur here was very costly).
    el('ellipse', { cx: 2, cy: 26, rx: 22, ry: 6, fill: '#08120e', opacity: 0.34 }, t);
    const crown = el('g', {}, t);
    if (kind === 'willow') {
      // weeping willow — low twisted trunk + drooping fronds
      el('path', { d: 'M0,26 C-6,6 5,2 1,-14', stroke: trunkCol, 'stroke-width': 6, fill: 'none', 'stroke-linecap': 'round' }, t);
      for (let k = 0; k < 5; k++) {
        const dx = (r() - 0.5) * 46;
        el('path', { d: 'M' + dx.toFixed(0) + ',-18 q' + (dx * 0.3).toFixed(0) + ',26 ' + (dx * 0.5).toFixed(0) + ',42',
          stroke: body, 'stroke-width': 7, fill: 'none', 'stroke-linecap': 'round', opacity: 0.85 }, crown);
      }
      lobes(crown, -18, 30, 6, 0.9);
    } else if (kind === 'spire') {
      // conifer-ish spire for the ridgeline — tall narrow stacked triangles
      el('path', { d: 'M0,26 V-6', stroke: trunkCol, 'stroke-width': 5, 'stroke-linecap': 'round' }, t);
      for (let k = 0; k < 4; k++) {
        const y = 6 - k * 14, w = 34 - k * 7;
        el('path', { d: 'M0,' + (y - 22) + ' L' + w + ',' + y + ' L' + (-w) + ',' + y + ' Z', fill: k === 0 ? belly : body }, crown);
      }
      el('path', { d: 'M0,-40 L10,-28 L-10,-28 Z', fill: lit, opacity: 0.7 }, crown);
    } else if (kind === 'peepal') {
      // peepal / bodhi tree — slim pale trunk, a tall rounded heart-shaped crown with a
      // few drip-tip leaves; the sacred fig, distinct from the squat banyan.
      el('path', { d: 'M0,26 C-3,4 4,0 1,-16', stroke: trunkCol, 'stroke-width': 6, fill: 'none', 'stroke-linecap': 'round' }, t);
      el('path', { d: 'M0,-2 C-14,-8 -20,-20 -22,-30 M0,-2 C14,-8 20,-20 22,-30', stroke: trunkCol, 'stroke-width': 3, fill: 'none', 'stroke-linecap': 'round' }, t);
      lobes(crown, -26, 46, 8, 1.15);
      // a couple of dangling heart-leaves with drip tips catching light
      for (let k = 0; k < 4; k++) {
        const lx = (r() - 0.5) * 40, ly = -6 + r() * 14;
        el('path', { d: 'M' + lx.toFixed(0) + ',' + ly.toFixed(0) + ' q-4,4 0,9 q4,-5 0,-9 Z', fill: lit, opacity: 0.6 }, crown);
      }
    } else {
      // banyan / broadleaf — thick trunk, wide multi-lobed crown (the workhorse)
      const wide = kind === 'banyan';
      el('path', { d: 'M0,26 C-5,6 6,2 1,-12', stroke: trunkCol, 'stroke-width': wide ? 9 : 6, fill: 'none', 'stroke-linecap': 'round' }, t);
      if (wide) { // a couple of splayed limbs + aerial roots
        el('path', { d: 'M0,-2 C-22,-6 -30,-18 -40,-26 M0,-2 C22,-6 30,-18 40,-26', stroke: trunkCol, 'stroke-width': 5, fill: 'none', 'stroke-linecap': 'round' }, t);
        for (let k = 0; k < 4; k++) el('line', { x1: -30 + k * 20, y1: -6, x2: -28 + k * 20, y2: 20, stroke: trunkCol, 'stroke-width': 1.6, opacity: 0.55 }, t);
      }
      lobes(crown, -20, wide ? 54 : 40, wide ? 9 : 7, wide ? 1.05 : 0.85);
    }
    if (!sway) return t;
    const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', values: '-1 0 26;1.1 0 26;-1 0 26', dur: (5 + r() * 3.5).toFixed(1) + 's', repeatCount: 'indefinite' });
    crown.appendChild(rot);
    return t;

    // a painterly cloud of overlapping leaf-lobes: dark belly first, body, then a lit crown.
    // Lobe counts are trimmed (slightly larger radii compensate) — this loop runs once PER
    // tree across the whole forest, so shaving a few circles here removes thousands of DOM
    // nodes map-wide while the massed silhouette looks the same.
    function lobes(g2, cy, spread, n, vscale) {
      const nb = Math.max(2, Math.round(n * 0.7));      // belly/body lobes (was n)
      for (let k = 0; k < nb; k++) {
        const cx = (r() - 0.5) * spread, y = cy + (r() - 0.5) * spread * 0.5 * vscale, rad = 12 + r() * 14;
        el('circle', { cx: cx.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: belly, opacity: 0.9 }, g2);
      }
      for (let k = 0; k < nb; k++) {
        const cx = (r() - 0.5) * spread * 0.9, y = cy - 3 + (r() - 0.5) * spread * 0.45 * vscale, rad = 11 + r() * 13;
        el('circle', { cx: cx.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: body, opacity: 0.95 }, g2);
      }
      // lit crown catching the temple key light (upper-left biased)
      for (let k = 0; k < Math.max(2, n - 4); k++) {
        const cx = -spread * 0.2 + (r() - 0.5) * spread * 0.6, y = cy - 8 - r() * spread * 0.3, rad = 6 + r() * 8;
        el('circle', { cx: cx.toFixed(1), cy: y.toFixed(1), r: rad.toFixed(1), fill: lit, opacity: 0.7 }, g2);
      }
      el('circle', { cx: (-spread * 0.18).toFixed(1), cy: (cy - spread * 0.32).toFixed(1), r: (4 + r() * 4).toFixed(1), fill: rim, opacity: 0.5 }, g2);
    }
  }

  function paintStands(g, reduced) {
    // ---- the forest floor: layered painterly ground + a distant canopy WALL -----------
    el('rect', { x: 0, y: 290, width: VB.w, height: VB.h - 290, fill: 'url(#groundG)' }, g);
    // a dense dark canopy silhouette hugging the treeline horizon so the world reads as a
    // forest you're INSIDE (not scattered trees on a plane). Rolling lobed skyline.
    canopyWall(g, 330, '#0e2019', 0.96, 'cwA', 30);
    canopyWall(g, 360, '#12271f', 0.9, 'cwB', 26);
    // warm light pooling down the centre from the temple
    el('rect', { x: 0, y: 290, width: VB.w, height: VB.h - 290, fill: 'url(#floorLight)', opacity: 0.9 }, g);
    // ATMOSPHERIC DEPTH HAZE — soft cool bands of mist behind the far foliage so distant
    // bands recede (blue-green) and nearer ones read warmer/clearer, giving layered depth.
    // atmospheric depth haze — soft cool bands. These span the FULL width, so a big-region
    // feGaussianBlur (soft2) here was one of the priciest filters on the map; at this low
    // opacity a plain translucent band reads the same, so we drop the live blur.
    for (let i = 0; i < 5; i++) {
      const t = i / 4, y = 300 + t * 200;
      el('rect', { x: 0, y: y - 30, width: VB.w, height: 64, fill: 'rgba(120,170,190,' + (0.09 - t * 0.02).toFixed(3) + ')' }, g);
    }
    // soft canopy-shadow pools on the floor (depth) — low-opacity ellipses, no per-pool blur.
    const rp = rng('pools');
    for (let i = 0; i < 16; i++) {
      const x = rp() * VB.w, y = 380 + rp() * (VB.h - 440), rad = 44 + rp() * 96;
      el('ellipse', { cx: x.toFixed(0), cy: y.toFixed(0), rx: rad.toFixed(0), ry: (rad * 0.36).toFixed(0), fill: rp() > 0.5 ? shade(C.groundLit, -0.14) : C.groundDeep, opacity: 0.16 }, g);
    }
    // ---- understorey scatter: ferns, grass tufts, flowers, mushrooms, logs -------------
    understorey(g, reduced);

    // ---- clustered tree STANDS — edges dense, real clearings near the path/centre ------
    // [x, y, scale, kind]; larger & nearer at the bottom, receding & smaller up top.
    const spots = [
      [70, 330, 1.05, 'banyan'], [1130, 330, 1.05, 'banyan'], [30, 470, 1.5, 'banyan'], [1170, 470, 1.5, 'banyan'],
      [180, 300, .78, 'round'], [1020, 300, .78, 'round'], [440, 262, .5, 'spire'], [760, 258, .5, 'spire'],
      [270, 400, .95, 'willow'], [930, 400, .95, 'round'], [110, 610, 1.6, 'banyan'], [1090, 610, 1.6, 'banyan'],
      [330, 660, 1.15, 'round'], [870, 660, 1.15, 'willow'], [560, 300, .46, 'spire'], [640, 296, .46, 'spire'],
      [210, 540, 1.05, 'round'], [990, 540, 1.05, 'willow'], [400, 620, .9, 'round'], [800, 615, .9, 'banyan'],
      [520, 660, .8, 'round'], [680, 662, .8, 'round']
    ];
    spots.forEach(([x, y, s, kind], i) => stand(g, x, y, s, kind, 'st' + i));

    function canopyWall(parent, baseY, col, op, seed, step) {
      const r = rng(seed); let d = 'M0,' + VB.h + ' L0,' + baseY;
      for (let x = -20; x <= VB.w + 20; x += step) {
        const y = baseY - 26 - r() * 40 + Math.sin(x * 0.02) * 10;
        d += ' Q' + (x + step / 2) + ',' + (y - 18 - r() * 20).toFixed(0) + ' ' + (x + step) + ',' + y.toFixed(0);
      }
      d += ' L' + VB.w + ',' + VB.h + ' Z';
      el('path', { d: d, fill: col, opacity: op, filter: 'url(#soft1)' }, parent);
    }
    function stand(parent, x, y, s, kind, seed) {
      const rr = rng(seed);
      const gg = el('g', { transform: 'translate(' + x + ',' + y + ')' }, parent);
      const trees = 2 + Math.floor(rr() * 3);
      // depth tone: nearer (lower on screen, bigger scale) trees are more lit
      const depthTone = Math.min(1, Math.max(0, (y - 260) / 400)) * 0.7 + s * 0.2;
      for (let i = 0; i < trees; i++) {
        const tx = (rr() - 0.5) * 90 * s, ty = (rr() - 0.5) * 34 * s, sc = (0.72 + rr() * 0.7) * s;
        const tone = Math.min(1, depthTone + (rr() - 0.5) * 0.22);
        const k = kind === 'banyan' && rr() < 0.35 ? 'round' : kind;
        const tg = el('g', { transform: 'translate(' + tx.toFixed(0) + ',' + ty.toFixed(0) + ')', opacity: (0.72 + rr() * 0.24).toFixed(2) }, gg);
        forestTree(tg, sc, tone, k, rng(seed + '|' + i), !reduced && s > 0.9 && rr() > 0.4);
      }
    }
  }

  // ferns, grass tufts, wildflowers, mushrooms, fallen logs — a living forest floor.
  function understorey(g, reduced) {
    const r = rng('under'); const layer = el('g', {}, g);
    // grass/fern band hugging the treeline so trunks meet foliage, not a hard line
    for (let i = 0; i < 80; i++) {
      const x = r() * VB.w, y = 340 + r() * (VB.h - 400);
      const near = (y - 340) / (VB.h - 400);          // 0 far … 1 near
      const h = (6 + r() * 14) * (0.5 + near);
      const lean = (r() - 0.5) * 6;
      const col = shade('#1f4230', -0.1 + near * 0.35 + r() * 0.1);
      el('path', { d: 'M0,0 q' + lean.toFixed(0) + ',' + (-h * 0.6).toFixed(0) + ' ' + (lean * 1.4).toFixed(0) + ',' + (-h).toFixed(0),
        stroke: col, 'stroke-width': (1 + near * 1.6).toFixed(1), fill: 'none', 'stroke-linecap': 'round',
        opacity: (0.4 + near * 0.4).toFixed(2), transform: 'translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')' }, layer);
    }
    // ferns — small radiating fronds
    for (let i = 0; i < 22; i++) {
      const x = r() * VB.w, y = 420 + r() * (VB.h - 470), near = (y - 420) / (VB.h - 470);
      const fg = el('g', { transform: 'translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ') scale(' + (0.6 + near * 0.9).toFixed(2) + ')' }, layer);
      for (let k = -3; k <= 3; k++) {
        const a = k * 20, len = 16 + r() * 8;
        el('path', { d: 'M0,0 q' + (Math.sin(a * Math.PI / 180) * len * 0.5).toFixed(0) + ',' + (-len * 0.7).toFixed(0) + ' ' + (Math.sin(a * Math.PI / 180) * len).toFixed(0) + ',' + (-len).toFixed(0),
          stroke: shade('#2b5a3e', r() * 0.2), 'stroke-width': 1.4, fill: 'none', 'stroke-linecap': 'round', opacity: 0.55 }, fg);
      }
    }
    // wildflowers — sparse warm/violet dots of light (spec: rare, as sparkle)
    for (let i = 0; i < 34; i++) {
      const x = r() * VB.w, y = 460 + r() * (VB.h - 500);
      const col = [C.gold, '#e6c46a', C.magenta, '#d7f0c0'][Math.floor(r() * 4)];
      el('circle', { cx: x.toFixed(0), cy: y.toFixed(0), r: (0.8 + r() * 1.4).toFixed(1), fill: col, opacity: 0.55 }, layer);
    }
    // mushrooms + a couple of mossy logs, low near the foreground
    for (let i = 0; i < 8; i++) {
      const x = 80 + r() * (VB.w - 160), y = 600 + r() * 140;
      const mg = el('g', { transform: 'translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')' }, layer);
      el('rect', { x: -1.4, y: -2, width: 2.8, height: 6, fill: '#3a4038', opacity: 0.7 }, mg);
      el('ellipse', { cx: 0, cy: -2, rx: 5, ry: 3, fill: r() > 0.5 ? '#b8623c' : '#c9a35a', opacity: 0.65 }, mg);
    }
    for (let i = 0; i < 3; i++) {
      const x = 120 + r() * (VB.w - 240), y = 680 + r() * 60;
      el('ellipse', { cx: x.toFixed(0), cy: y.toFixed(0), rx: (36 + r() * 34).toFixed(0), ry: (7 + r() * 4).toFixed(0), fill: '#20342a', opacity: 0.6, transform: 'rotate(' + ((r() - 0.5) * 16).toFixed(0) + ' ' + x.toFixed(0) + ' ' + y.toFixed(0) + ')' }, layer);
    }
  }

  // ============================================================================
  // MYTHOLOGICAL SCENE LAYER — sacred lotus-pond (kund) + meditating guru, floating
  // diyas, peacock, small shrines. Echoes the reference art (alt5). Sits in a right-side
  // clearing so it never crowds the central path/labels; deterministic + reduced-safe.
  // ============================================================================

  // a single oil-lamp diya: a shallow clay bowl with a warm teardrop flame + halo.
  function diya(parent, x, y, s, reduced, seed) {
    s = s || 1;
    const gg = el('g', { class: 'diya', transform: 'translate(' + x + ',' + y + ') scale(' + s + ')' }, parent);
    el('ellipse', { cx: 0, cy: 8, rx: 12, ry: 4, fill: '#3a2417', opacity: 0.7 }, gg);          // reflection/shadow
    el('circle', { class: 'diya-glow', cx: 0, cy: -1, r: 10, fill: 'url(#diyaG)', opacity: 0.9 }, gg);   // glow
    el('path', { d: 'M-7,3 Q0,9 7,3 Z', fill: '#6a3a1c' }, gg);                                  // clay bowl
    el('path', { d: 'M-7,3 Q0,7 7,3', fill: 'none', stroke: C.goldDeep, 'stroke-width': 1 }, gg);
    const fl = el('path', { class: 'diya-flame', d: 'M0,-2 C-2,-6 0,-11 0,-13 C0,-11 2,-6 0,-2 Z', fill: C.goldBright }, gg);  // flame
    el('circle', { cx: 0, cy: -5, r: 1.6, fill: '#fff8e4' }, gg);
    if (!reduced) { const r = seed ? rng(seed) : Math.random; anim(fl, 'opacity', '1', '0.6', (1.6 + (r() || 0.4)).toFixed(1) + 's'); }
    return gg;
  }

  // a serene meditating GURU/sage silhouette in lotus posture, glowing aureole (echo of alt5).
  function guru(parent, x, y, s, reduced) {
    s = s || 1;
    const gg = el('g', { class: 'crit crit-guru', transform: 'translate(' + x + ',' + y + ') scale(' + s + ')' }, parent);
    el('rect', { x: -28, y: -42, width: 56, height: 56, fill: 'transparent', 'pointer-events': 'all' }, gg);   // hit-area
    // contrast pool so the sage separates from foliage
    el('ellipse', { cx: 0, cy: -12, rx: 30, ry: 26, fill: 'url(#critShade)', 'pointer-events': 'none' }, gg);
    // luminous golden aureole (spirit halo behind the head/shoulders)
    const spirit = el('circle', { cx: 0, cy: -18, r: 26, fill: 'url(#spiritGold)', opacity: 0.7, 'pointer-events': 'none' }, gg);
    if (!reduced) anim(spirit, 'opacity', '0.8', '0.4', '6s');
    const halo = el('circle', { class: 'sage-aura', cx: 0, cy: -20, r: 16, fill: 'none', stroke: C.goldBright, 'stroke-width': 1.2, opacity: 0.55, 'pointer-events': 'none' }, gg);
    if (!reduced) anim(halo, 'opacity', '0.6', '0.22', '5s');
    const body = el('g', {}, gg);
    el('ellipse', { cx: 0, cy: 8, rx: 26, ry: 6, fill: '#0a1712', opacity: 0.5 }, body);        // ground shadow
    // crossed-leg base
    el('path', { d: 'M-24,6 Q0,-2 24,6 Q0,13 -24,6 Z', fill: '#16281f' }, body);
    // torso + shoulders (robed)
    el('path', { d: 'M-15,4 C-16,-16 -8,-27 0,-27 C8,-27 16,-16 15,4 Z', fill: '#1c3226' }, body);
    // saffron shawl accent
    el('path', { d: 'M-12,-3 C-8,-16 8,-16 12,-3', fill: 'none', stroke: C.ember, 'stroke-width': 2.4, opacity: 0.8 }, body);
    el('circle', { cx: 0, cy: -32, r: 6.5, fill: '#243a2e' }, body);                             // head
    el('circle', { cx: 0, cy: -33, r: 1.5, fill: C.gold, opacity: 0.9 }, body);                  // tilak/bindu
    return gg;
  }

  // a PEACOCK (mor) — the iconic bird: a jewelled teal body with an S-curved neck & crest,
  // and a long SPREADING TRAIN of eye-feathers (ocelli) behind it. `fanned` shows the full
  // display fan; otherwise a graceful trailing train. Reads unmistakably as a peacock.
  function peacock(parent, x, y, s, dir, reduced, fanned, spirit) {
    s = s || 1; dir = dir || 1;
    const wrap = el('g', { class: 'crit crit-peacock' + (spirit ? ' crit-spirit' : ''), transform: 'translate(' + x + ',' + y + ') scale(' + (s * dir) + ',' + s + ')' }, parent);
    el('rect', { x: -56, y: -40, width: 84, height: 58, fill: 'transparent', 'pointer-events': 'all' }, wrap);   // hit-area
    // contrast pool under the bird so its jewelled body reads against foliage
    el('ellipse', { cx: -6, cy: -4, rx: fanned ? 42 : 34, ry: 26, fill: 'url(#critShade)', 'pointer-events': 'none' }, wrap);
    if (spirit) {
      const aura = el('ellipse', { class: 'crit-aura', cx: -4, cy: -6, rx: fanned ? 44 : 34, ry: 30, fill: 'url(#spiritTeal)', opacity: 0.75, 'pointer-events': 'none' }, wrap);
      if (!reduced) anim(aura, 'opacity', '0.85', '0.45', '3s');
    }
    const gg = el('g', {}, wrap);
    const eye = (fx, fy, rr) => {   // one ocellus "eye" feather tip
      el('ellipse', { cx: fx.toFixed(1), cy: fy.toFixed(1), rx: (rr * 1.15).toFixed(1), ry: rr.toFixed(1), fill: spirit ? '#57d3ce' : '#1f8f78', opacity: 0.9 }, tail);
      el('circle', { cx: fx.toFixed(1), cy: fy.toFixed(1), r: (rr * 0.62).toFixed(1), fill: spirit ? '#7fb0e0' : '#2f5fa0', opacity: 0.95 }, tail);
      el('circle', { cx: fx.toFixed(1), cy: fy.toFixed(1), r: (rr * 0.3).toFixed(1), fill: C.goldBright }, tail);
    };
    const tail = el('g', { class: 'peacock-tail' }, gg);
    const shaftCol = spirit ? '#57d3ce' : '#146a66';
    if (fanned) {
      // full display fan sweeping up & out behind the body (a wide arc of eye-feathers)
      const shafts = 13;
      for (let i = 0; i < shafts; i++) {
        const a = (-98 + (i / (shafts - 1)) * 196) * Math.PI / 180;   // -98°..+98°
        const len = 52 + Math.cos(a) * 10;
        const ex = -6 + Math.sin(a) * len, ey = -4 - Math.cos(a) * len;
        el('path', { d: 'M-4,2 Q' + (ex * 0.5 - 2).toFixed(1) + ',' + (ey * 0.5).toFixed(1) + ' ' + ex.toFixed(1) + ',' + ey.toFixed(1),
          fill: 'none', stroke: shaftCol, 'stroke-width': 1.2, opacity: 0.55 }, tail);
        eye(ex, ey, 4 - Math.abs(i - (shafts - 1) / 2) * 0.18);
      }
    } else {
      // graceful trailing TRAIN — long curved feathers streaming behind (to the left)
      const feathers = 8;
      for (let i = 0; i < feathers; i++) {
        const spread = (i - (feathers - 1) / 2) * 7;      // vertical spread of the train
        const len = 52 + (feathers - i) * 4;
        const ex = -len, ey = 10 + spread;
        el('path', { d: 'M-5,2 Q' + (-len * 0.5).toFixed(1) + ',' + (spread * 0.5 - 2).toFixed(1) + ' ' + ex.toFixed(1) + ',' + ey.toFixed(1),
          fill: 'none', stroke: shaftCol, 'stroke-width': 1.3, opacity: 0.6 }, tail);
        eye(ex, ey, 3.4);
      }
      // a few barb wisps for softness
      for (let i = 0; i < 4; i++) el('path', { d: 'M-6,4 Q-' + (30 + i * 9) + ',' + (12 + i * 3) + ' -' + (50 + i * 9) + ',' + (20 + i * 4), fill: 'none', stroke: spirit ? '#7fe6df' : '#1f8f78', 'stroke-width': 0.7, opacity: 0.45 }, tail);
    }
    // plump teal body
    const bodyCol = spirit ? '#2f8478' : '#124d4c', sheenCol = spirit ? '#7fe6df' : '#1a7d78';
    el('ellipse', { cx: 5, cy: 2, rx: 11, ry: 8.5, fill: bodyCol }, gg);
    el('ellipse', { cx: 6, cy: 0, rx: 7, ry: 5, fill: sheenCol, opacity: 0.75 }, gg);            // breast sheen
    // S-curved neck rising forward-right
    el('path', { d: 'M13,-1 C22,-5 23,-16 19,-22', fill: 'none', stroke: spirit ? '#57d3ce' : '#146a66', 'stroke-width': 5, 'stroke-linecap': 'round' }, gg);
    el('circle', { cx: 19, cy: -23, r: 4, fill: sheenCol }, gg);                                 // head
    el('path', { d: 'M22,-23 l4,-0.6', stroke: C.gold, 'stroke-width': 1.5, 'stroke-linecap': 'round' }, gg);   // beak
    el('circle', { cx: 18, cy: -23.5, r: 0.9, fill: '#08120e' }, gg);                            // eye
    // fan crest (3 dotted plumes)
    for (let k = -1; k <= 1; k++) {
      el('line', { x1: 19, y1: -27, x2: 19 + k * 3, y2: -34, stroke: sheenCol, 'stroke-width': 1 }, gg);
      el('circle', { cx: 19 + k * 3, cy: -34.5, r: 1.4, fill: spirit ? '#d6fbf4' : C.teal }, gg);
    }
    // legs
    el('path', { d: 'M3,10 l-1,6 M9,10 l1,6', stroke: '#2a2018', 'stroke-width': 1.2, 'stroke-linecap': 'round' }, gg);
    return wrap;
  }

  // ---- more Indic mythological LIFE (readable silhouettes at map scale, on-palette) ----
  // Every creature is wrapped in a POP layer: a soft dark ground-vignette + a rim-light
  // filter so it separates cleanly from the dense foliage. `spirit` ('gold'|'teal') adds a
  // luminous enchanted aura + swirling fireflies for the magical spirit-animals. The returned
  // group is the DRAW group (filtered); shade/halo sit beneath it in the wrapper.
  function critterBase(parent, x, y, s, dir, shadowRx, cls, spirit, reduced) {
    const rx = shadowRx || 16;
    // wrapper carries placement; holds (a) hit-area, (b) contrast pool, (c) optional aura,
    // (d) the filtered creature draw-group. The `crit` class + kind class live here for hover.
    const wrap = el('g', { class: 'crit' + (cls ? ' ' + cls : '') + (spirit ? ' crit-spirit' : ''),
      transform: 'translate(' + x + ',' + y + ') scale(' + (s * (dir || 1)) + ',' + s + ')' }, parent);
    // invisible hit-area so the WHOLE creature is hoverable/tappable.
    el('rect', { x: -rx - 8, y: -38, width: rx * 2 + 16, height: 50, fill: 'transparent', 'pointer-events': 'all' }, wrap);
    // CONTRAST: a broad soft dark vignette under the creature so its silhouette reads against
    // busy leaves (the single biggest "pop" cue) + a crisp cast shadow at the feet.
    el('ellipse', { cx: 0, cy: -6, rx: rx * 1.5, ry: rx * 1.1, fill: 'url(#critShade)', 'pointer-events': 'none' }, wrap);
    el('ellipse', { cx: 0, cy: 6, rx: rx, ry: 4, fill: '#06100c', opacity: 0.5 }, wrap);
    // ENCHANTED aura (spirit animals only): coloured luminous bloom + a few swirling fireflies.
    if (spirit) {
      const auraId = spirit === 'teal' ? 'spiritTeal' : 'spiritGold';
      const aura = el('ellipse', { class: 'crit-aura', cx: 0, cy: -12, rx: rx * 1.9, ry: rx * 1.7, fill: 'url(#' + auraId + ')', opacity: 0.9, 'pointer-events': 'none' }, wrap);
      if (!reduced) anim(aura, 'opacity', '0.95', '0.5', (2.6 + (rx % 5) * 0.4).toFixed(1) + 's');
      const ffCol = spirit === 'teal' ? '#bdf4ec' : '#ffe9ad';
      const haloId = spirit === 'teal' ? 'nodeTeal' : 'nodeGold';
      const fr = rng((cls || 'sp') + rx + x);
      for (let i = 0; i < 3; i++) {   // 3 (was 4); soft radial-gradient motes, no live-blur FILTER
        const a = fr() * Math.PI * 2, rr = rx * (0.9 + fr() * 0.9);
        const fx = Math.cos(a) * rr, fy = -12 + Math.sin(a) * rr * 0.7;
        // pre-baked halo (cheap radial gradient) + a tiny bright core — same sparkle look, no filter
        const f = el('g', { class: 'crit-spark', transform: 'translate(' + fx.toFixed(1) + ',' + fy.toFixed(1) + ')', 'pointer-events': 'none' }, wrap);
        el('circle', { r: (3 + fr() * 2).toFixed(1), fill: 'url(#' + haloId + ')', opacity: 0.7 }, f);
        el('circle', { r: (0.9 + fr() * 0.8).toFixed(1), fill: ffCol }, f);
        if (!reduced) { anim(f, 'opacity', '0.95', '0.2', (1.3 + fr() * 1.6).toFixed(1) + 's');
          animT(f, '0,0', ((fr() - 0.5) * 14).toFixed(0) + ',' + (-6 - fr() * 10).toFixed(0), (4 + fr() * 4).toFixed(1) + 's'); }
      }
    }
    // the actual creature art group. The dark `critShade` vignette drawn above already
    // separates the silhouette from foliage, so we skip the expensive per-creature rim-light
    // FILTER (feGaussian+feFlood+feComposite ×N was the map's #1 render cost). Spirit animals
    // keep no live blur either — their coloured aura gradient (drawn above) reads on its own.
    const gg = el('g', {}, wrap);
    gg._wrap = wrap;
    return gg;
  }

  // a DEER / chital — slender body, arched neck, antlers, dappled back. `spirit` makes it a
  // luminous golden ghost-deer (the enchanted-forest signature).
  function deer(parent, x, y, s, dir, spirit, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 19, 'crit-deer', spirit, reduced);
    const bodyCol = spirit ? '#f2dca0' : '#6a4e2c', litCol = spirit ? '#fff2c8' : '#8a6a3c', legCol = spirit ? '#caa860' : '#2a2018';
    el('path', { d: 'M-15,4 L-15,-8 M-7,4 L-7,-9 M7,3 L7,-9 M14,3 L14,-8', stroke: legCol, 'stroke-width': 2.1, 'stroke-linecap': 'round' }, gg);  // legs
    el('path', { d: 'M-16,-9 C-9,-17 9,-17 15,-10 L13,-4 C5,-7 -7,-7 -15,-4 Z', fill: bodyCol }, gg);   // body
    el('path', { d: 'M-14,-11 C-8,-16 6,-16 12,-11', fill: 'none', stroke: litCol, 'stroke-width': 1.4, opacity: 0.7 }, gg);  // lit back
    el('path', { class: 'deer-tail amb', d: 'M-15,-4 q-3,3 -2,7', stroke: legCol, 'stroke-width': 1.8, fill: 'none', 'stroke-linecap': 'round' }, gg);  // tail (flicks)
    for (let i = 0; i < 5; i++) el('circle', { cx: -9 + i * 5, cy: -11 + (i % 2) * 2.5, r: 1.1, fill: spirit ? '#fff8e0' : C.goldBright, opacity: 0.85 }, gg);  // dapples
    // head + neck + antlers as one group (lifts on hover) — origin at the neck base
    const head = el('g', { class: 'deer-head' }, gg);
    el('path', { d: 'M14,-10 C19,-15 20,-22 17,-27', fill: 'none', stroke: bodyCol, 'stroke-width': 3.6, 'stroke-linecap': 'round' }, head);  // neck
    el('circle', { cx: 17, cy: -28, r: 3.6, fill: litCol }, head);                                        // head
    el('path', { d: 'M17,-30 l-1,-6 M16,-32 l-3,-3 M19,-30 l1,-6 M20,-32 l3,-3', stroke: spirit ? '#fff2c8' : C.gold, 'stroke-width': 1.2, 'stroke-linecap': 'round' }, head);  // branched antlers
    el('circle', { cx: 15.6, cy: -28.5, r: 0.7, fill: '#08120e' }, head);   // eye
    el('path', { d: 'M20,-28 l2.5,-0.6', stroke: spirit ? '#fff2c8' : '#3a2c1a', 'stroke-width': 1.1, 'stroke-linecap': 'round' }, head);   // muzzle
    return gg._wrap;
  }

  // a NAGA / king cobra — redrawn readable: a clearly-coiled body on the ground, a tall
  // S-rising neck, and a broad symmetric flared HOOD with a distinct diamond head, forked
  // tongue + eyes. `spirit` gives a luminous teal spirit-serpent; `menace` reddens the eyes
  // (a guardian of the hard groves — see difficulty mapping).
  function naga(parent, x, y, s, dir, spirit, reduced, menace) {
    const gg = critterBase(parent, x, y, s, dir, 22, 'crit-naga', spirit, reduced);
    const coilCol = spirit ? '#57d3ce' : '#15706b', bodyCol = spirit ? '#7fe6df' : '#1f8a83',
          hoodCol = spirit ? '#2f8478' : '#0f4f4c', bellyCol = spirit ? '#bff0e9' : '#3fb0a4';
    // two stacked ground coils (read as a piled serpent, not a squiggle)
    el('ellipse', { cx: -3, cy: 1, rx: 17, ry: 7, fill: 'none', stroke: coilCol, 'stroke-width': 5.5 }, gg);
    el('ellipse', { cx: -1, cy: -3, rx: 12, ry: 5, fill: 'none', stroke: coilCol, 'stroke-width': 5 }, gg);
    el('path', { d: 'M-14,-2 q10,-4 20,0', fill: 'none', stroke: bellyCol, 'stroke-width': 1.2, opacity: 0.6 }, gg);  // belly scute sheen
    // rising neck + hood sway together on hover
    const hood = el('g', { class: 'naga-hood' }, gg);
    el('path', { d: 'M6,-6 C12,-14 10,-26 5,-34', fill: 'none', stroke: bodyCol, 'stroke-width': 5.4, 'stroke-linecap': 'round' }, hood);  // rising neck
    // broad symmetric hood (two lobes) framing the head
    el('path', { d: 'M5,-34 C-6,-40 -8,-52 -2,-56 C1,-49 3,-42 5,-38 C7,-42 9,-49 12,-56 C18,-52 16,-40 5,-34 Z', fill: hoodCol, stroke: spirit ? '#d6fbf4' : bodyCol, 'stroke-width': 1.2 }, hood);
    // hood eyespot markings (the cobra's ocelli)
    el('circle', { cx: 0, cy: -48, r: 1.6, fill: spirit ? '#d6fbf4' : C.gold, opacity: 0.8 }, hood);
    el('circle', { cx: 10, cy: -48, r: 1.6, fill: spirit ? '#d6fbf4' : C.gold, opacity: 0.8 }, hood);
    // diamond head
    el('path', { d: 'M5,-38 L1,-44 L5,-49 L9,-44 Z', fill: bodyCol, stroke: spirit ? '#d6fbf4' : hoodCol, 'stroke-width': 0.8 }, hood);
    const eyeCol = menace ? '#ff5a3c' : C.goldBright;
    el('circle', { cx: 3, cy: -44, r: 1.1, fill: eyeCol }, hood); el('circle', { cx: 7, cy: -44, r: 1.1, fill: eyeCol }, hood);   // eyes
    if (menace && !reduced) { const e = el('circle', { cx: 5, cy: -44, r: 3.2, fill: 'none', stroke: '#ff5a3c', 'stroke-width': 0.7, opacity: 0.5 }, hood); anim(e, 'opacity', '0.6', '0.2', '1.6s'); }
    // forked tongue flicking from the snout
    el('path', { d: 'M5,-49 l0,-4 M5,-53 l-1.6,-2.4 M5,-53 l1.6,-2.4', stroke: C.ember, 'stroke-width': 0.9, 'stroke-linecap': 'round', fill: 'none' }, hood);
    return gg._wrap;
  }

  // an ELEPHANT (gaja) — redrawn for a clean, unmistakable silhouette: a high domed back
  // sloping to the rump, four columnar legs with real gaps, a bulged forehead, a curling
  // trunk, a fanned ear, tusks. `spirit` gives a luminous teal spirit-elephant (Airavata).
  function elephant(parent, x, y, s, dir, spirit, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 30, 'crit-elephant', spirit, reduced);
    gg.setAttribute('class', 'amb-body');   // gentle body sway (+ trunk animates separately)
    const legCol = spirit ? '#357f78' : '#26252e', bodyCol = spirit ? '#57b8b0' : '#403f52',
          litCol = spirit ? '#7fe0d8' : '#565571', headCol = spirit ? '#63c1b8' : '#4a4960',
          earCol = spirit ? '#3f8f88' : '#33323f';
    // four columnar legs (front pair + back pair, with a gap between)
    el('path', { d: 'M-17,6 L-17,-9 M-6,7 L-6,-10', stroke: legCol, 'stroke-width': 5.2, 'stroke-linecap': 'round' }, gg);   // hind legs
    el('path', { d: 'M8,7 L8,-10 M18,6 L18,-9', stroke: legCol, 'stroke-width': 5.2, 'stroke-linecap': 'round' }, gg);       // fore legs
    // toenails
    el('path', { d: 'M-19,7 h4 M-8,8 h4 M6,8 h4 M16,7 h4', stroke: spirit ? '#bff0e9' : '#1a1922', 'stroke-width': 1, 'stroke-linecap': 'round', opacity: 0.7 }, gg);
    // body: a high domed back arcing down to a low rump + belly
    el('path', { d: 'M-20,-8 C-24,-24 -14,-32 2,-32 C16,-32 24,-24 24,-14 C24,-6 20,-4 14,-4 L-14,-4 C-19,-4 -19,-4 -20,-8 Z', fill: bodyCol }, gg);
    el('path', { d: 'M-16,-26 C-6,-32 8,-31 18,-22', fill: 'none', stroke: litCol, 'stroke-width': 3, 'stroke-linecap': 'round', opacity: 0.7 }, gg);  // lit back ridge
    // head: bulged forehead merging into the body front, cheek
    el('path', { d: 'M18,-24 C28,-24 30,-14 28,-6 C27,-2 22,-1 18,-3 C14,-6 14,-20 18,-24 Z', fill: headCol }, gg);
    // fanned ear over the shoulder
    el('path', { d: 'M13,-22 C4,-20 2,-8 10,-4 C16,-6 16,-16 16,-22 Z', fill: earCol, opacity: 0.94 }, gg);
    el('path', { d: 'M13,-20 C7,-17 6,-9 11,-6', fill: 'none', stroke: spirit ? '#bff0e9' : '#26252e', 'stroke-width': 0.8, opacity: 0.6 }, gg);  // ear fold
    // curling trunk down the front
    el('path', { class: 'eleph-trunk', d: 'M27,-14 C34,-9 34,2 29,9 C27,12 24,11 25,8', fill: 'none', stroke: headCol, 'stroke-width': 5.4, 'stroke-linecap': 'round' }, gg);
    // tusks flanking the trunk
    el('path', { d: 'M23,-4 C25,1 27,4 26,8 M27,-4 C29,0 31,3 31,7', fill: 'none', stroke: '#f2ecdb', 'stroke-width': 1.8, 'stroke-linecap': 'round' }, gg);
    el('circle', { cx: 24, cy: -16, r: 1.2, fill: '#08120e' }, gg);   // eye
    el('circle', { cx: 21, cy: -22, r: 1.5, fill: C.ember, opacity: 0.9 }, gg);   // bindi on brow
    // caparison drape hint across the back
    el('path', { d: 'M-10,-28 q10,-5 22,-1', fill: 'none', stroke: spirit ? '#d6fbf4' : C.gold, 'stroke-width': 1.2, opacity: 0.65 }, gg);
    return gg._wrap;
  }

  // a MONKEY (vanara) — redrawn readable: a rounded body with a paler belly, jointed limbs,
  // a long curling tail, and a clear pink face with a pale ruff (langur-like). `swing` hangs
  // it from a branch by one arm (canopy monkeys); otherwise it sits/perches on the ground.
  function monkey(parent, x, y, s, dir, swing) {
    const gg = critterBase(parent, x, y, s, dir, 13, 'crit-monkey' + (swing ? ' crit-monkey-swing' : ''));
    gg.setAttribute('class', 'amb-body');   // whole body bobs / swings ambiently
    const furDk = '#463526', furLt = '#6a5238', belly = '#8a7250', face = '#d8b888', ruff = '#c9b59a';
    if (swing) {
      // hangs from a branch above by one raised gripping arm; body dangles, tail curls up
      el('path', { d: 'M1,-20 C-2,-28 -6,-30 -7,-34', fill: 'none', stroke: furDk, 'stroke-width': 2.6, 'stroke-linecap': 'round' }, gg);  // raised gripping arm
      el('circle', { cx: -7, cy: -34, r: 1.6, fill: furLt }, gg);   // gripping hand
      el('path', { d: 'M3,-4 C11,-2 15,-8 13,-16 C12,-22 8,-24 6,-27', fill: 'none', stroke: furDk, 'stroke-width': 2.2, 'stroke-linecap': 'round' }, gg);  // long curling tail up
      el('ellipse', { cx: 0, cy: -11, rx: 6.5, ry: 9, fill: furDk }, gg);                                 // body
      el('ellipse', { cx: 0, cy: -9, rx: 3.8, ry: 6, fill: belly, opacity: 0.7 }, gg);                    // belly
      el('path', { d: 'M-4,-6 C-8,-2 -8,4 -6,9 M4,-6 C7,-1 6,5 3,10', fill: 'none', stroke: furDk, 'stroke-width': 2.2, 'stroke-linecap': 'round' }, gg);  // dangling legs
      el('circle', { cx: -6, cy: 9, r: 1.3, fill: furLt }, gg); el('circle', { cx: 3, cy: 10, r: 1.3, fill: furLt }, gg);   // feet
    } else {
      el('path', { d: 'M-4,2 C-13,4 -19,-2 -18,-9 C-17,-15 -12,-16 -9,-13', fill: 'none', stroke: furDk, 'stroke-width': 2.6, 'stroke-linecap': 'round' }, gg);  // long curling tail
      el('ellipse', { cx: 0, cy: -8, rx: 8, ry: 10, fill: furDk }, gg);                                   // body
      el('ellipse', { cx: 0, cy: -6, rx: 4.6, ry: 7, fill: belly, opacity: 0.75 }, gg);                   // belly
      el('path', { d: 'M-6,-3 C-9,1 -8,5 -6,8 M6,-3 C9,1 8,5 6,8', fill: 'none', stroke: furDk, 'stroke-width': 2.4, 'stroke-linecap': 'round' }, gg);  // arms resting
      el('circle', { cx: -6, cy: 8, r: 1.3, fill: furLt }, gg); el('circle', { cx: 6, cy: 8, r: 1.3, fill: furLt }, gg);   // hands
    }
    const head = el('g', { class: 'monkey-head' }, gg);
    el('circle', { cx: 2, cy: -20, r: 6, fill: furDk }, head);                                            // head fur
    el('circle', { cx: 2, cy: -19, r: 5, fill: ruff }, head);                                             // pale ruff
    el('ellipse', { cx: 2.4, cy: -18.5, rx: 3.4, ry: 4, fill: face }, head);                              // face
    el('circle', { cx: -3, cy: -22, r: 1.7, fill: furDk }, head); el('circle', { cx: 7, cy: -22, r: 1.7, fill: furDk }, head);  // ears
    el('circle', { cx: 0.8, cy: -19.5, r: 0.7, fill: '#20180f' }, head); el('circle', { cx: 3.8, cy: -19.5, r: 0.7, fill: '#20180f' }, head);  // eyes
    el('path', { d: 'M1.4,-16.5 q1,1 2,0', stroke: '#5a4028', 'stroke-width': 0.7, fill: 'none', 'stroke-linecap': 'round' }, head);   // muzzle
    return gg._wrap;
  }

  // ============================================================================
  // GUARDIAN FAUNA — the dangerous set that marks the HARD / advanced / locked groves.
  // Menacing silhouettes, watchful low posture, a subtle amber/red eye-glow. All read as
  // "this grove is a serious challenge." Deterministic difficulty→danger keeps a grove's
  // guardian stable across reloads (see difficultyOf + guardianFor).
  // ============================================================================

  // shared predator eye-glow: two small amber/red eyes that softly pulse (reduced-safe: a
  // static bright dot). `menace` intensifies to red. Sits in the creature's local frame.
  function predEyes(gg, x, y, gap, menace, reduced) {
    const col = menace ? '#ff5230' : '#ffb64a';
    [-gap / 2, gap / 2].forEach(dx => {
      const halo = el('circle', { cx: x + dx, cy: y, r: 2.4, fill: menace ? 'rgba(255,60,30,.5)' : 'rgba(255,180,60,.5)', 'pointer-events': 'none' }, gg);
      el('circle', { cx: x + dx, cy: y, r: 1, fill: col }, gg);
      if (!reduced) anim(halo, 'opacity', '0.85', '0.3', (1.4 + gap * 0.05).toFixed(1) + 's');
    });
  }

  // a TIGER (sher/vyaghra) — a low crouched stalking cat: heavy body, powerful shoulders,
  // striped flank, a long low tail, ears back, glowing eyes. The apex guardian of the
  // hardest groves. `menace` reddens the eyes (near locked/frontier).
  function tiger(parent, x, y, s, dir, menace, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 26, 'crit-tiger', null, reduced);
    const body = '#c67a2e', litB = '#e0a24e', belly = '#efe0c4', stripe = '#241812';
    // long low tail sweeping up behind the haunch
    el('path', { d: 'M-20,-10 C-30,-14 -35,-9 -34,-2', fill: 'none', stroke: body, 'stroke-width': 3.2, 'stroke-linecap': 'round' }, gg);
    el('path', { d: 'M-34,-3 l0,3', stroke: stripe, 'stroke-width': 3.2, 'stroke-linecap': 'round' }, gg);   // tail tip
    // four legs: crouched hind haunch + planted fore legs
    el('path', { d: 'M-16,6 L-16,-6 M-9,7 L-9,-6', stroke: body, 'stroke-width': 4.2, 'stroke-linecap': 'round' }, gg);  // hind
    el('path', { d: 'M10,7 L10,-6 M18,7 L18,-5', stroke: body, 'stroke-width': 4, 'stroke-linecap': 'round' }, gg);      // fore
    // body: a big rounded haunch at the rear, dipping through the back, rising to the shoulder
    el('path', { d: 'M-22,-8 C-24,-20 -14,-24 -8,-22 C-2,-20 -2,-14 4,-14 C12,-14 12,-20 18,-20 C25,-20 27,-12 25,-7 C24,-5 22,-4 19,-5 L-18,-5 C-21,-5 -22,-5 -22,-8 Z', fill: body }, gg);
    el('path', { d: 'M-18,-20 C-12,-23 -6,-20 -2,-16 C4,-19 12,-19 18,-18', fill: 'none', stroke: litB, 'stroke-width': 2.2, 'stroke-linecap': 'round', opacity: 0.7 }, gg);  // lit back
    el('path', { d: 'M-16,-6 C-4,-8 12,-8 20,-7', fill: 'none', stroke: belly, 'stroke-width': 2, opacity: 0.5 }, gg);   // belly
    // bold vertical flank stripes
    for (let i = 0; i < 6; i++) el('path', { d: 'M' + (-16 + i * 7) + ',-18 q-2,7 -1,12', fill: 'none', stroke: stripe, 'stroke-width': 1.5, 'stroke-linecap': 'round', opacity: 0.85 }, gg);
    // raised head on a thick neck, ears up, watchful (turns to face when the cursor is near)
    const head = el('g', { class: 'pred-head' }, gg);
    el('path', { d: 'M22,-16 C26,-20 30,-19 31,-15', fill: 'none', stroke: body, 'stroke-width': 4, 'stroke-linecap': 'round' }, head);  // neck
    el('circle', { cx: 30, cy: -18, r: 6.4, fill: litB }, head);                              // head
    el('path', { d: 'M25,-23 l-1,-4 l4,2 Z M35,-23 l1,-4 l-4,2 Z', fill: body }, head);       // ears up
    el('path', { d: 'M28,-14 q2,3 4,0 Z', fill: belly }, head);                               // muzzle/chin
    el('path', { d: 'M26,-20 q4,-1 8,0 M27,-16 q3,1 6,0', stroke: stripe, 'stroke-width': 0.8, fill: 'none', opacity: 0.7 }, head);   // face stripes
    predEyes(head, 30, -19, 4.5, menace, reduced);
    el('path', { d: 'M28,-13 l1,2', stroke: '#fff', 'stroke-width': 0.7, opacity: 0.6 }, head);   // fang glint
    return gg._wrap;
  }

  // a PANTHER (bagheera) — a sleek black big-cat, same crouched stalk as the tiger but a
  // near-silhouette body (no stripes) with a green-amber eye-shine. Guardian of hard groves.
  function panther(parent, x, y, s, dir, menace, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 24, 'crit-panther', null, reduced);
    const body = '#14161c', lit = '#2b2f3a';
    el('path', { d: 'M-20,-8 C-31,-11 -35,-4 -32,2', fill: 'none', stroke: body, 'stroke-width': 3.2, 'stroke-linecap': 'round' }, gg);  // tail
    el('path', { d: 'M-14,6 L-14,-4 M-6,7 L-6,-5 M9,7 L9,-5 M16,6 L16,-4', stroke: body, 'stroke-width': 3.8, 'stroke-linecap': 'round' }, gg);  // legs
    el('path', { d: 'M-19,-6 C-21,-15 -11,-19 0,-19 C11,-19 19,-17 23,-11 C24,-8 23,-6 20,-5 L-15,-5 C-18,-5 -18,-5 -19,-6 Z', fill: body }, gg);
    el('path', { d: 'M-14,-16 C-2,-19 12,-18 20,-12', fill: 'none', stroke: lit, 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.8 }, gg);  // sheen
    const head = el('g', { class: 'pred-head' }, gg);
    el('circle', { cx: 22, cy: -9, r: 6.4, fill: lit }, head);
    el('path', { d: 'M18,-14 l-1,-4 l4,2 M26,-14 l1,-4 l-4,2', fill: body }, head);   // ears
    el('path', { d: 'M22,-9 q6,1 7,4 q-4,2 -7,0 Z', fill: body }, head);              // muzzle
    predEyes(head, 22, -11, 5, menace, reduced);
    return gg._wrap;
  }

  // a CROCODILE (magar/makara) — a long low armoured reptile at the water's edge: a broad
  // snout, ridged scaly back, splayed legs, a thick tapering tail, a slit glowing eye. Draws
  // low and flat (it lurks). Guardian of water-adjacent hard groves.
  function crocodile(parent, x, y, s, dir, menace, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 30, 'crit-croc', null, reduced);
    const body = '#3a5a3e', lit = '#57794f', dark = '#22381f', belly = '#7a8c5c';
    // thick tapering tail
    el('path', { d: 'M-18,-2 C-30,-3 -38,-1 -44,2 C-38,4 -30,4 -18,2 Z', fill: body }, gg);
    for (let i = 0; i < 4; i++) el('path', { d: 'M' + (-22 - i * 5) + ',-3 l2,-3', stroke: dark, 'stroke-width': 1.4, 'stroke-linecap': 'round' }, gg);  // tail ridges
    // splayed legs
    el('path', { d: 'M-8,3 l-5,5 M0,3 l5,5 M14,3 l-5,5 M22,3 l5,5', stroke: body, 'stroke-width': 2.6, 'stroke-linecap': 'round' }, gg);
    // long low body
    el('path', { d: 'M-18,-5 C-18,1 34,2 34,-2 C34,-6 20,-8 0,-8 C-10,-8 -18,-8 -18,-5 Z', fill: body }, gg);
    el('path', { d: 'M-16,-6 C-4,-8 18,-8 30,-5', fill: 'none', stroke: lit, 'stroke-width': 1.6, opacity: 0.6 }, gg);  // back sheen
    // dorsal scute ridges (the croc signature)
    for (let i = 0; i < 7; i++) el('path', { d: 'M' + (-14 + i * 6) + ',-8 l2,-4 l2,4 Z', fill: dark, opacity: 0.9 }, gg);
    // broad snout + jaw line with teeth
    el('path', { d: 'M30,-6 C42,-6 46,-3 44,0 C40,2 34,2 30,1 Z', fill: body }, gg);
    el('path', { d: 'M31,-1 l3,2 l3,-2 l3,2 l3,-2', fill: 'none', stroke: '#e8e0cc', 'stroke-width': 0.7, opacity: 0.85 }, gg);   // teeth
    // raised eye ridge with a glowing slit eye
    el('path', { d: 'M22,-8 q3,-4 6,-1', fill: 'none', stroke: dark, 'stroke-width': 2.4, 'stroke-linecap': 'round' }, gg);
    predEyes(gg, 25, -10, 0.1, menace, reduced);
    return gg._wrap;
  }

  // a WILD BOAR (varaha/suar) — a bristly hump-shouldered pig: a wedge head with tusks, a
  // ridge of raised bristles, short legs, a curly tail. A charging guardian of hard groves.
  function boar(parent, x, y, s, dir, menace, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 20, 'crit-boar', null, reduced);
    const body = '#3f342a', lit = '#5a4a38', dark = '#241c14';
    el('path', { d: 'M-14,6 L-14,-3 M-6,7 L-6,-4 M8,7 L8,-4 M15,6 L15,-3', stroke: dark, 'stroke-width': 3, 'stroke-linecap': 'round' }, gg);  // short legs
    el('path', { d: 'M-16,-4 q-4,-2 -3,-6', fill: 'none', stroke: dark, 'stroke-width': 1.6, 'stroke-linecap': 'round' }, gg);   // curly tail
    // hump-shouldered body (higher at the shoulder toward the head)
    el('path', { d: 'M-16,-4 C-18,-12 -10,-16 2,-17 C14,-18 18,-14 20,-9 C21,-6 20,-4 17,-4 Z', fill: body }, gg);
    el('path', { d: 'M-6,-16 C4,-18 14,-16 18,-11', fill: 'none', stroke: lit, 'stroke-width': 2, opacity: 0.6 }, gg);   // lit hump
    // raised dorsal bristles
    for (let i = 0; i < 7; i++) el('line', { x1: -10 + i * 4, y1: -16, x2: -11 + i * 4, y2: -22, stroke: dark, 'stroke-width': 1.2, 'stroke-linecap': 'round' }, gg);
    // wedge head + snout
    el('path', { d: 'M17,-11 C25,-12 30,-8 31,-3 C31,-1 28,0 25,-1 C20,-3 16,-7 17,-11 Z', fill: lit }, gg);
    el('ellipse', { cx: 30, cy: -3, rx: 2.4, ry: 2, fill: dark }, gg);   // snout disc
    el('path', { d: 'M27,-2 q-2,3 -4,1 M31,-4 q2,-3 3,-1', fill: 'none', stroke: '#efe4d0', 'stroke-width': 1.4, 'stroke-linecap': 'round' }, gg);   // curved tusks
    el('path', { d: 'M18,-13 l-2,-5 l4,3 Z', fill: dark }, gg);   // ear
    predEyes(gg, 22, -8, 0.1, menace, reduced);
    return gg._wrap;
  }

  // an OWL (uluka) — a plump nocturnal perched bird: a round body, big forward eyes, ear
  // tufts, a hooked beak. Active at night; a wise watcher near mid-difficulty groves.
  function owl(parent, x, y, s, dir, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 12, 'crit-owl', null, reduced);
    const body = '#5a4a34', lit = '#7a6748', disc = '#c9b48c';
    el('line', { x1: -8, y1: 8, x2: 8, y2: 8, stroke: '#2a2018', 'stroke-width': 1.6, 'stroke-linecap': 'round' }, gg);   // branch
    el('path', { d: 'M-9,-2 C-11,-14 -6,-22 0,-22 C6,-22 11,-14 9,-2 C9,4 6,7 0,7 C-6,7 -9,4 -9,-2 Z', fill: body }, gg);  // plump body
    el('path', { d: 'M-6,-10 C-2,-6 2,-6 6,-10 M-6,-4 C-2,0 2,0 6,-4 M-6,2 C-2,5 2,5 6,2', fill: 'none', stroke: lit, 'stroke-width': 1, opacity: 0.6 }, gg);  // breast barring
    // ear tufts
    el('path', { d: 'M-6,-20 l-2,-6 l4,3 Z M6,-20 l2,-6 l-4,3 Z', fill: body }, gg);
    // facial discs + eyes
    el('circle', { cx: -3.4, cy: -13, r: 3.8, fill: disc }, gg); el('circle', { cx: 3.4, cy: -13, r: 3.8, fill: disc }, gg);
    const eyeCol = '#f7d98a';
    el('circle', { cx: -3.4, cy: -13, r: 2, fill: eyeCol }, gg); el('circle', { cx: 3.4, cy: -13, r: 2, fill: eyeCol }, gg);
    el('circle', { cx: -3.4, cy: -13, r: 0.9, fill: '#08120e' }, gg); el('circle', { cx: 3.4, cy: -13, r: 0.9, fill: '#08120e' }, gg);
    el('path', { d: 'M0,-11 l-1.4,3 l2.8,0 Z', fill: '#c88a3a' }, gg);   // beak
    if (!reduced) { const bl = el('rect', { x: -6, y: -15, width: 12, height: 0.1, fill: 'none' }, gg); }   // (blink handled via eye halo elsewhere)
    return gg._wrap;
  }

  // a HERON / crane (bagula) — a tall wading bird at the pond edge: long legs, an S-neck, a
  // dagger beak, poised to fish. Gentle water-margin fauna.
  function heron(parent, x, y, s, dir, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 14, 'crit-heron', null, reduced);
    const body = '#8fa7ac', lit = '#c2d2d4', legCol = '#5a4a30';
    el('path', { d: 'M-1,10 L-2,-6 M3,10 L4,-6', stroke: legCol, 'stroke-width': 1.6, 'stroke-linecap': 'round' }, gg);   // long legs
    el('path', { d: 'M-1,10 l-4,2 M3,10 l4,2', stroke: legCol, 'stroke-width': 1.4, 'stroke-linecap': 'round' }, gg);     // feet
    el('path', { d: 'M-9,-6 C-11,-14 -4,-16 4,-14 C10,-13 11,-8 8,-4 C4,-2 -6,-2 -9,-6 Z', fill: body }, gg);   // body
    el('path', { d: 'M-9,-6 C-16,-4 -20,0 -22,4', fill: 'none', stroke: body, 'stroke-width': 2, 'stroke-linecap': 'round' }, gg);   // folded wing/tail plume
    el('path', { d: 'M-7,-13 C-4,-15 2,-15 4,-13', fill: 'none', stroke: lit, 'stroke-width': 1.2, opacity: 0.7 }, gg);   // back sheen
    // S-curved neck + head + dagger beak
    el('path', { d: 'M6,-13 C12,-16 10,-24 6,-28', fill: 'none', stroke: body, 'stroke-width': 2.4, 'stroke-linecap': 'round' }, gg);
    el('circle', { cx: 6, cy: -29, r: 2.6, fill: lit }, gg);   // head
    el('path', { d: 'M4,-33 l3,-3 l-4,2 Z', fill: '#e0c04a' }, gg);   // crest plume
    el('path', { d: 'M8,-29 l7,-1', stroke: '#e8c24a', 'stroke-width': 1.4, 'stroke-linecap': 'round' }, gg);   // dagger beak
    el('circle', { cx: 6.6, cy: -29.5, r: 0.7, fill: '#08120e' }, gg);   // eye
    return gg._wrap;
  }

  // a RABBIT / hare (khargosh) — a small rounded body, long ears, a puff tail. Gentle fauna
  // near easy/mastered groves. Ears prick / it startles when the cursor is near (see wiring).
  function rabbit(parent, x, y, s, dir, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 10, 'crit-rabbit', null, reduced);
    const body = '#a89478', lit = '#cbbc9e', dark = '#6a5842';
    el('circle', { cx: -7, cy: -1, r: 2.4, fill: '#e8ddc8' }, gg);   // puff tail
    el('path', { d: 'M-6,-2 C-8,-9 -3,-13 3,-13 C9,-13 11,-8 9,-2 C8,2 4,4 1,4 C-3,4 -6,2 -6,-2 Z', fill: body }, gg);  // body
    el('path', { d: 'M-4,-11 C0,-13 5,-13 8,-10', fill: 'none', stroke: lit, 'stroke-width': 1.4, opacity: 0.7 }, gg);   // lit back
    el('path', { d: 'M0,4 l-2,3 M4,4 l2,3', stroke: dark, 'stroke-width': 1.6, 'stroke-linecap': 'round' }, gg);   // hind feet
    // head + long ears (the rabbit signature)
    const head = el('g', { class: 'rabbit-head amb', 'transform-origin': '8px -8px' }, gg);
    el('circle', { cx: 9, cy: -7, r: 3.4, fill: lit }, head);   // head
    el('path', { d: 'M7,-9 C5,-16 6,-21 8,-21 C10,-21 10,-16 9,-9 Z', fill: body }, head);   // ear 1
    el('path', { d: 'M11,-9 C11,-16 13,-20 14,-19 C15,-17 13,-13 12,-9 Z', fill: body }, head);  // ear 2
    el('path', { d: 'M8,-19 C7,-14 8,-11 8.5,-10', fill: 'none', stroke: '#e0a8a0', 'stroke-width': 0.8, opacity: 0.6 }, head);  // inner ear
    el('circle', { cx: 10.4, cy: -7.5, r: 0.7, fill: '#20180f' }, head);   // eye
    el('circle', { cx: 12, cy: -6, r: 0.6, fill: '#c88', opacity: 0.7 }, head);   // nose
    return gg._wrap;
  }

  // a walking PILGRIM (yatri) — robed figure with a staff, mid-stride along a path. `lantern`
  // makes them hold a glowing lamp aloft (a lantern-bearer walking the night path).
  function pilgrim(parent, x, y, s, dir, lantern, reduced) {
    const gg = critterBase(parent, x, y, s, dir, 11, 'crit-pilgrim', lantern ? 'gold' : null, reduced);
    const robe = '#33281c', robeLt = '#4a3a24';
    el('path', { d: 'M-4,6 L-6,-8 M4,6 L3,-8', stroke: '#1a1510', 'stroke-width': 3, 'stroke-linecap': 'round' }, gg);  // legs stride
    el('path', { d: 'M0,-8 C-8,-8 -8,3 -6,6 L6,6 C8,3 8,-8 0,-8 Z', fill: robe }, gg);                    // robe
    el('path', { d: 'M-6,-6 C-4,0 4,0 6,-6', fill: 'none', stroke: C.ember, 'stroke-width': 1.6, opacity: 0.7 }, gg);  // saffron sash
    el('path', { d: 'M0,-8 C-5,-18 5,-18 0,-8', fill: robeLt }, gg);                                      // torso/shoulders
    el('circle', { cx: 0, cy: -22, r: 4, fill: '#2e241a' }, gg);                                          // head
    el('circle', { cx: 0, cy: -23, r: 1.1, fill: C.gold, opacity: 0.8 }, gg);                             // tilak
    if (lantern) {
      // arm raised holding a bright hanging lantern
      el('path', { d: 'M4,-12 q8,-3 11,-9', fill: 'none', stroke: robeLt, 'stroke-width': 2.4, 'stroke-linecap': 'round' }, gg);  // arm
      el('line', { x1: 15, y1: -21, x2: 15, y2: -16, stroke: C.goldEmber, 'stroke-width': 1 }, gg);       // hanger
      el('circle', { cx: 15, cy: -13, r: 5.5, fill: 'url(#diyaG)' }, gg);                                 // lantern glow
      el('circle', { cx: 15, cy: -13, r: 2, fill: '#fff3cf' }, gg);
      el('rect', { x: 12.6, y: -15.4, width: 4.8, height: 5.2, rx: 1, fill: 'none', stroke: C.goldDeep, 'stroke-width': 0.7 }, gg);  // lantern frame
    } else {
      el('line', { x1: 8, y1: -26, x2: 9, y2: 6, stroke: C.goldEmber, 'stroke-width': 1.8 }, gg);         // staff
      el('circle', { cx: 8, cy: -26, r: 2.2, fill: 'url(#diyaG)' }, gg);                                  // knot-lamp on staff
    }
    return gg._wrap;
  }

  // a FLOCK of birds — bolder V-glyphs gliding on a looping flight path across the sky /
  // between canopies. Higher-contrast (light stroke + dark under-stroke) so it reads clearly
  // against sky AND foliage. The inner group flaps its wings continuously (reduced-safe).
  function flock(parent, x, y, s, seed, reduced) {
    const r = rng(seed); const gg = el('g', { class: 'flock', transform: 'translate(' + x + ',' + y + ') scale(' + s + ')' }, parent);
    // wide invisible hit-area so the flock is hoverable (scatter on hover)
    el('rect', { x: -34, y: -18, width: 68, height: 30, fill: 'transparent', 'pointer-events': 'all' }, gg);
    const inner = el('g', { class: 'flock-g' }, gg);   // hover + flap target (drift on gg)
    const n = 4 + Math.floor(r() * 3);
    const birds = [];
    for (let i = 0; i < n; i++) {
      const bx = (r() - 0.5) * 46, by = (r() - 0.5) * 20, sz = 5.5 + r() * 3.5;
      const b = el('g', { class: 'flock-bird', transform: 'translate(' + bx.toFixed(1) + ',' + by.toFixed(1) + ')' }, inner);
      const wingUp = 'M0,0 q-' + sz + ',-' + (sz * 0.6) + ' -' + (sz * 2) + ',0 q' + sz + ',-' + (sz * 0.6) + ' ' + (sz * 2) + ',0';
      const wingDn = 'M0,0 q-' + sz + ',' + (sz * 0.3) + ' -' + (sz * 2) + ',0 q' + sz + ',' + (sz * 0.3) + ' ' + (sz * 2) + ',0';
      // dark under-stroke first (contrast against sky), light stroke on top
      el('path', { class: 'flap', d: wingUp, fill: 'none', stroke: 'rgba(6,10,20,.55)', 'stroke-width': 2.6, 'stroke-linecap': 'round', transform: 'translate(0,0.7)' }, b);
      const w = el('path', { class: 'flap', d: wingUp, fill: 'none', stroke: 'rgba(240,232,206,.92)', 'stroke-width': 1.7, 'stroke-linecap': 'round' }, b);
      birds.push([w, wingUp, wingDn, r]);
      if (!reduced) w.parentNode.querySelectorAll('.flap').forEach(fp => {
        fp.appendChild(el('animate', { attributeName: 'd', values: wingUp + ';' + wingDn + ';' + wingUp, dur: (0.5 + r() * 0.4).toFixed(2) + 's', begin: (r() * 0.4).toFixed(2) + 's', repeatCount: 'indefinite' }));
      });
    }
    // looping glide across the map (SMIL animateMotion on the group)
    if (!reduced) {
      const dir = r() > 0.5 ? 1 : -1;
      const mv = el('animateMotion', { dur: (26 + r() * 14).toFixed(0) + 's', repeatCount: 'indefinite',
        path: 'M0,0 q' + (dir * 140) + ',-30 ' + (dir * 280) + ',10 q' + (dir * 140) + ',40 ' + (dir * 90) + ',-30 q' + (-dir * 260) + ',-20 ' + (-dir * 470) + ',10 Z' });
      gg.appendChild(mv);
    }
    return gg;
  }

  // a single PERCHED bird on a twig — a small rounded body, tail + beak, a warm eye.
  function perchedBird(parent, x, y, s, seed) {
    const r = rng(seed || ('pb' + x)); s = s || 1;
    const cols = [['#c86ba8', '#e6a0cc'], ['#57d3ce', '#a0eae4'], ['#e7b64b', '#f7d98a'], ['#d97a3c', '#f0a878']];
    const c = cols[Math.floor(r() * cols.length)];
    const gg = el('g', { class: 'crit crit-perched', transform: 'translate(' + x + ',' + y + ') scale(' + s + ')' }, parent);
    el('rect', { x: -10, y: -14, width: 22, height: 22, fill: 'transparent', 'pointer-events': 'all' }, gg);
    el('ellipse', { cx: 0, cy: 2, rx: 9, ry: 4, fill: 'url(#critShade)', 'pointer-events': 'none' }, gg);
    const b = el('g', { class: 'crit-perched-body amb' }, gg);
    el('line', { x1: -6, y1: 6, x2: 6, y2: 6, stroke: '#2a2018', 'stroke-width': 1.4, 'stroke-linecap': 'round' }, b);  // twig
    el('path', { d: 'M-2,4 q-8,-2 -9,-9', fill: 'none', stroke: c[0], 'stroke-width': 2.4, 'stroke-linecap': 'round' }, b);  // tail
    el('ellipse', { cx: 1, cy: -2, rx: 5, ry: 6, fill: c[0] }, b);   // body
    el('ellipse', { cx: 2, cy: -3, rx: 3, ry: 4, fill: c[1], opacity: 0.7 }, b);  // wing sheen
    el('circle', { cx: 4, cy: -8, r: 3, fill: c[1] }, b);   // head
    el('path', { d: 'M7,-8 l3,0.5', stroke: C.gold, 'stroke-width': 1.2, 'stroke-linecap': 'round' }, b);  // beak
    el('circle', { cx: 4.5, cy: -8.5, r: 0.7, fill: '#08120e' }, b);  // eye
    el('line', { x1: -1, y1: 4, x2: -1, y2: 6.5, stroke: '#2a2018', 'stroke-width': 0.9 }, b);  // leg
    return gg;
  }

  // The sacred lotus-pond (kund): glowing water, concentric ripples, lotus pads & flowers,
  // floating diyas, a meditating guru on the near bank, a peacock beside it.
  // Distribute SEVERAL sacred kunds across the whole map (one roughly per path band), each
  // in a clearing well clear of every grove medallion/label. Greedy: pick the clearest
  // candidate in each y-band, then keep pond→pond spacing so they read as distinct pools.
  // Deterministic-from-data (positions derive only from grove points), scales to any count.
  function pondSpots(pts, temple) {
    if (!pts.length) return [];
    // y-bands from just under the temple down to the near foreground
    const yTop = temple ? temple.y + 150 : 300;
    const bandYs = [];
    for (let y = yTop; y <= VB.h - 96; y += 118) bandYs.push(y);
    const chosen = [];
    bandYs.forEach(by => {
      let best = null, bestScore = -1e9;
      for (let fx = 0.12; fx <= 0.88; fx += 0.05) {
        const c = { x: VB.w * fx, y: by + ( (Math.round(fx * 20)) % 2 ? 14 : -14) };
        let nearNode = 1e9;
        pts.forEach(p => { const d = Math.hypot(p.x - c.x, p.y - c.y); if (d < nearNode) nearNode = d; });
        let nearPond = 1e9;
        chosen.forEach(p => { const d = Math.hypot(p.x - c.x, p.y - c.y); if (d < nearPond) nearPond = d; });
        // want clearance from nodes AND from other ponds; mild side-preference
        const score = nearNode + Math.min(nearPond, 200) * 0.6 + Math.abs(c.x - VB.w / 2) * 0.08;
        if (nearNode > 70 && score > bestScore) { bestScore = score; best = c; }
      }
      if (best) chosen.push(best);
    });
    return chosen;
  }

  function paintPond(g, reduced, spot, idx) {
    // default clearing: right-mid glade; caller may pass a computed gap so the pond never
    // sits under a grove medallion (positions vary with grove count). `idx` seeds variety
    // (size + who sits by the water) so distributed ponds don't look identical.
    idx = idx || 0;
    const near = spot ? Math.min(1, Math.max(0, (spot.y - 250) / 480)) : 0.8;   // 0 far … 1 near
    const scale = 0.62 + near * 0.5;                                            // pools recede up-map
    const cx = spot ? spot.x : VB.w * 0.79, cy = spot ? spot.y : 560;
    const rx = 120 * scale, ry = 40 * scale;
    const gg = el('g', { class: 'pond' }, g);
    // bank rim / wet stone
    el('ellipse', { cx: cx, cy: cy + 4, rx: rx + 14, ry: ry + 8, fill: '#0c1c18', opacity: 0.5 }, gg);
    // luminous water
    el('ellipse', { class: 'pond-water', cx: cx, cy: cy, rx: rx, ry: ry, fill: 'url(#pondG)' }, gg);
    el('ellipse', { cx: cx, cy: cy, rx: rx, ry: ry, fill: 'none', stroke: C.teal, 'stroke-width': 1, opacity: 0.4 }, gg);
    // concentric ripples (expanding, reduced-safe)
    for (let i = 0; i < 3; i++) {
      const rp = el('ellipse', { class: 'pond-ripple', cx: cx, cy: cy, rx: (rx * 0.3).toFixed(0), ry: (ry * 0.3).toFixed(0), fill: 'none', stroke: 'rgba(159,230,214,.45)', 'stroke-width': 1 }, gg);
      if (!reduced) {
        rp.appendChild(el('animate', { attributeName: 'rx', values: (rx * 0.2) + ';' + (rx * 0.95), dur: '6s', begin: (i * 2) + 's', repeatCount: 'indefinite' }));
        rp.appendChild(el('animate', { attributeName: 'ry', values: (ry * 0.2) + ';' + (ry * 0.95), dur: '6s', begin: (i * 2) + 's', repeatCount: 'indefinite' }));
        rp.appendChild(el('animate', { attributeName: 'opacity', values: '0.5;0', dur: '6s', begin: (i * 2) + 's', repeatCount: 'indefinite' }));
      }
    }
    // lotus pads + a couple of pink lotus blooms
    const r = rng('pond');
    for (let i = 0; i < 6; i++) {
      const px = cx + (r() - 0.5) * rx * 1.5, py = cy + (r() - 0.5) * ry * 1.3;
      el('ellipse', { cx: px.toFixed(0), cy: py.toFixed(0), rx: (7 + r() * 6).toFixed(0), ry: (3 + r() * 2).toFixed(0), fill: '#1e5a43', opacity: 0.7 }, gg);
    }
    // KOI fish gliding just under the surface — warm ember/gold darts that drift & wag (SMIL,
    // reduced-safe). Bounded to 2 per pond so the animator count stays small.
    for (let i = 0; i < 2; i++) {
      const kx = cx + (r() - 0.5) * rx * 0.9, ky = cy + (r() - 0.5) * ry * 0.7;
      const koi = el('g', { transform: 'translate(' + kx.toFixed(0) + ',' + ky.toFixed(0) + ')' }, gg);
      const kc = i % 2 ? C.ember : C.goldBright;
      el('ellipse', { cx: 0, cy: 0, rx: 4 * scale, ry: 2 * scale, fill: kc, opacity: 0.85 }, koi);   // body
      el('path', { d: 'M' + (-4 * scale) + ',0 l' + (-3 * scale) + ',' + (-2 * scale) + ' l0,' + (4 * scale) + ' Z', fill: kc, opacity: 0.7 }, koi);  // tail
      el('circle', { cx: 3 * scale, cy: -0.5, r: 0.7, fill: '#3a1e10' }, koi);   // eye
      if (!reduced) animT(koi, '0,0', ((r() - 0.5) * rx * 0.8).toFixed(0) + ',' + ((r() - 0.5) * ry * 0.6).toFixed(0), (8 + r() * 6).toFixed(1) + 's');
    }
    for (let i = 0; i < 3; i++) {
      const px = cx + (r() - 0.5) * rx * 1.2, py = cy + (r() - 0.5) * ry;
      // one lotus per pond BREATHES (opens/closes) ambiently; the others are static-but-hoverable.
      const breathe = !reduced && i === 0;
      const lg = el('g', { class: 'lotus-bloom' + (breathe ? ' lotus-breathe' : ''), transform: 'translate(' + px.toFixed(0) + ',' + py.toFixed(0) + ')', style: '--ph:' + (-(r() * 4).toFixed(2)) + 's' }, gg);
      for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; el('path', { d: 'M0,0 Q' + (Math.cos(a) * 3).toFixed(1) + ',-5 ' + (Math.cos(a) * 6).toFixed(1) + ',' + (Math.sin(a) * 6 - 2).toFixed(1), stroke: C.magenta, 'stroke-width': 1.4, fill: 'none', opacity: 0.75 }, lg); }
      el('circle', { cx: 0, cy: 0, r: 1.8, fill: C.goldBright }, lg);
    }
    // floating diyas drifting on the water
    [[-0.5, 0.1], [0.2, -0.2], [0.55, 0.25]].forEach(([fx, fy], i) => {
      const d = diya(gg, cx + fx * rx, cy + fy * ry, 0.7 * scale, reduced, 'ponddiya' + idx + i);
      if (!reduced) animT(d, '0,0', ((i % 2 ? 10 : -10)) + ',0', (10 + i * 3) + 's');
    });
    // a bank FIGURE (varies per pond) + a creature beside the water, both foreshortened
    const fsc = 1.05 * scale;
    if (idx % 3 === 0) guru(gg, cx - rx * 0.7, cy + 10 * scale, fsc, reduced);
    else if (idx % 3 === 1) pilgrim(gg, cx - rx * 0.7, cy + 8 * scale, fsc, 1);
    else guru(gg, cx - rx * 0.7, cy + 10 * scale, fsc, reduced);
    (idx % 2 ? deer(gg, cx + rx * 0.9, cy + 2 * scale, 0.9 * scale, -1)
             : peacock(gg, cx + rx * 0.85, cy - 6 * scale, 0.9 * scale, -1, reduced));
    // a small bank shrine (a lit diya at the water's edge)
    diya(gg, cx - rx * 0.2, cy - ry * 0.7, 0.8 * scale, reduced, 'shrined' + idx);
  }

  // Diyas lining the luminous path — small oil-lamps placed just off the trail at
  // deterministic intervals, so the way to the temple is candle-lit (echo of the ref).
  function paintPathDiyas(g, pts, reduced) {
    if (!pts || pts.length < 2) return;
    const r = rng('pathdiya'); const layer = el('g', {}, g);
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      // offset perpendicular to the segment, alternating sides, clear of medallions
      const side = i % 2 === 0 ? 1 : -1;
      const off = 34 + r() * 10;
      const px = mx + (-dy / len) * off * side, py = my + (dx / len) * off * side * 0.5 + 8;
      const sc = 0.6 + (a.scale || 1) * 0.3;
      diya(layer, px.toFixed(0), py.toFixed(0), sc, reduced, 'pd' + i);
    }
  }

  // ============================================================================
  // PER-BAND FOLIAGE — the key to UNIFORM density: for every path segment (all the
  // switchback rows up to the temple), scatter trees flanking BOTH sides + understorey
  // filling the gaps between bands, sized by perspective (bigger low, smaller high). This
  // is procedural per-segment (seeded from geometry), so new pillars auto-get the same
  // lush treatment and it scales to any count — no hand-placed spots for a fixed 18.
  // Drawn into the background (behind the path/nodes) so it never hides labels.
  function paintBandFoliage(g, pts, temple, reduced) {
    if (!pts || !pts.length) return;
    const layer = el('g', {}, g);
    const tempY = temple ? temple.y : 116;
    // perspective helper: how "near" a y is (0 far/top … 1 near/bottom)
    const nearOf = y => Math.min(1, Math.max(0, (y - tempY) / (VB.h - tempY)));
    // CSS-breeze budget: cap how many trees rock via CSS (on top of the SMIL-swaying subset)
    // so the breeze feels pervasive but the total animating element count stays bounded (60fps).
    let breezeBudget = reduced ? 0 : 24;
    const treeKinds = ['banyan', 'round', 'willow', 'peepal', 'round', 'banyan', 'peepal'];
    // a small planting helper so every source (grid / segments / temple) makes matched trees
    function plant(x, y, rr, opts) {
      opts = opts || {};
      if (x < 4 || x > VB.w - 4 || y < 300 || y > VB.h - 6) return;
      const near = nearOf(y);
      const scl = (opts.baseScale != null ? opts.baseScale : (0.62 + near * 0.82)) * (0.8 + rr() * 0.5);
      const kind = treeKinds[Math.floor(rr() * treeKinds.length)];
      // FAR trees drift toward the atmospheric dusk-blue tint; near trees stay green/jewel.
      let tintIdx; const roll = rr();
      if (near < 0.4) tintIdx = roll < 0.5 ? 4 : roll < 0.72 ? 1 : roll < 0.88 ? 2 : roll < 0.96 ? 3 : 5;
      else tintIdx = roll < 0.4 ? Math.floor(rr() * 3) : roll < 0.66 ? 3 : roll < 0.8 ? 1 : roll < 0.9 ? 2 : roll < 0.96 ? 6 : 5;
      const tone = Math.min(1, 0.4 + near * 0.45 + (rr() - 0.5) * 0.2);
      const tg = el('g', { transform: 'translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')', opacity: (0.82 + rr() * 0.16).toFixed(2) }, layer);
      const smilSway = !reduced && near > 0.6 && scl > 0.95 && rr() > 0.78;
      // CSS BREEZE on a bounded subset of the remaining (non-SMIL) trees — the whole crown
      // rocks gently; staggered by --ph. Inner group so the rotation composes with translate.
      // Also a hover target: `.tree-breeze` rustles harder on pointer-over (wired in CSS).
      const breeze = !reduced && !smilSway && breezeBudget > 0 && rr() < 0.5;
      let host = tg;
      if (breeze) { breezeBudget--; host = el('g', { class: 'breeze tree-breeze', style: '--ph:' + (-(rr() * 6).toFixed(2)) + 's' }, tg); }
      forestTree(host, scl, tone, kind, rng('t|' + x.toFixed(0) + '|' + y.toFixed(0)), smilSway, tintIdx);
    }

    // (0) FULL-FRAME tree GRID — guarantees UNIFORM coverage of every region (top, far
    // corners, the gaps between bands) so density never thins toward the temple. A jittered
    // lattice over the whole ground plane; because far trees are SMALL, we plant MORE of them
    // per area up top (finer rows + more columns + fewer gaps) so coverage stays even.
    const gr = rng('treegrid');
    for (let y = 316; y <= VB.h - 30; ) {
      const near = nearOf(y);
      // finer, denser lattice far away (small trees) → coarser near (big trees fill more).
      // Grid loosened a step (fewer rows/cols) — with the bigger-radius, lower-lobe trees the
      // canopy still reads fully even; this is the biggest single DOM-count reduction.
      const rowStep = lerp(44, 66, near);
      const cols = Math.round(lerp(10, 6, near));
      const skip = lerp(0.1, 0.24, near);               // fewer gaps up top
      const inset = lerp(2, 56, 1 - near);              // still plant out to the frame edges
      for (let c = 0; c <= cols; c++) {
        if (gr() < skip) continue;
        const fx = c / cols;
        const x = inset + fx * (VB.w - 2 * inset) + (gr() - 0.5) * (VB.w / cols) * 0.9;
        const yy = y + (gr() - 0.5) * rowStep * 0.5;
        plant(x, yy, gr);
      }
      y += rowStep;
    }

    // (1) extra trees flanking BOTH sides of every path segment — thickens the treed
    // CORRIDOR right along the trail (over the grid) so the path always feels embowered.
    const spine = temple ? pts.concat([{ x: temple.x, y: temple.y + 96, scale: 0.42 }]) : pts;
    const river = meander(spine);
    for (let i = 0; i < river.length - 1; i++) {
      const a = river[i], b = river[i + 1];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len, ny = dx / len;
      const near = nearOf(my);
      const rr = rng('band|' + i);
      [-1, 1].forEach(sideDir => {
        const nStands = 2;                              // UNIFORM count top→bottom (size recedes)
        for (let s = 0; s < nStands; s++) {
          const off = (46 + rr() * 40) + near * 24;     // clear of the path halo, both ends
          const along = (rr() - 0.5) * len * 0.7;
          const tx = mx + nx * off * sideDir + (dx / len) * along;
          const ty = my + ny * off * sideDir * 0.55 + (dy / len) * along;
          plant(tx, ty, rr);
        }
      });
    }

    // (2) TEMPLE-APPROACH grove — the top region around the shikhara gets its own dense
    // planting (the funnel makes the path a single narrow column up there, so the grid alone
    // can look thin). Trees hug both sides of the temple and fill the upper corners.
    if (temple) {
      const rt = rng('templegrove');
      for (let i = 0; i < 26; i++) {
        const side = i % 2 ? 1 : -1;
        const spread = 80 + rt() * 340;
        const x = temple.x + side * spread;
        const y = temple.y + 64 + rt() * 170;
        plant(x, y, rt, { baseScale: 0.44 + rt() * 0.34 });
      }
      // two staggered low bands of small trees straight across just under the temple horizon
      for (let x = 30; x < VB.w - 30; x += 64) plant(x + (rt() - 0.5) * 26, temple.y + 148 + (rt() - 0.5) * 24, rt, { baseScale: 0.42 + rt() * 0.24 });
      for (let x = 56; x < VB.w - 30; x += 72) plant(x + (rt() - 0.5) * 26, temple.y + 196 + (rt() - 0.5) * 24, rt, { baseScale: 0.44 + rt() * 0.26 });
    }

    // (3) understorey tufts + wildflowers filling the ground everywhere (uniform count). A
    // bounded subset of the near-foreground tufts get a CSS `.gbreeze` wave (staggered), so
    // the grass bobs in the breeze — capped so the total animator count stays 60fps-safe.
    const ru = rng('bandunder');
    const uStep = 70;                                    // coarser grass lattice (was 58)
    let grassBreeze = reduced ? 0 : 28;
    for (let y = 320; y <= VB.h - 14; y += 50) {         // coarser rows (was 40)
      const near = nearOf(y);
      for (let x = 20; x < VB.w - 20; x += uStep) {
        if (ru() < 0.4) continue;
        const px = x + (ru() - 0.5) * uStep, py = y + (ru() - 0.5) * 26;
        if (px < 8 || px > VB.w - 8) continue;
        const h = (4 + ru() * 11) * (0.55 + near * 0.8);
        const lean = (ru() - 0.5) * 6;
        const col = shade('#1f4230', -0.08 + near * 0.34 + ru() * 0.1);
        const dPath = 'M0,0 q' + lean.toFixed(0) + ',' + (-h * 0.6).toFixed(0) + ' ' + (lean * 1.4).toFixed(0) + ',' + (-h).toFixed(0);
        const wave = grassBreeze > 0 && near > 0.55 && ru() < 0.5;
        const host = wave
          ? (grassBreeze--, el('g', { class: 'gbreeze', style: '--ph:' + (-(ru() * 4).toFixed(2)) + 's', transform: 'translate(' + px.toFixed(0) + ',' + py.toFixed(0) + ')' }, layer))
          : layer;
        const gAttrs = { d: dPath, stroke: col, 'stroke-width': (1 + near * 1.4).toFixed(1), fill: 'none', 'stroke-linecap': 'round', opacity: (0.38 + near * 0.4).toFixed(2) };
        if (!wave) gAttrs.transform = 'translate(' + px.toFixed(0) + ',' + py.toFixed(0) + ')';
        el('path', gAttrs, host);
        if (ru() > 0.8) el('circle', { cx: px.toFixed(0), cy: (py - h).toFixed(0), r: (0.8 + ru() * 1.2).toFixed(1),
          fill: [C.gold, C.magenta, '#d7f0c0', C.goldBright][Math.floor(ru() * 4)], opacity: 0.55 }, layer);
      }
    }
  }

  // ============================================================================
  // MYTHOLOGICAL LIFE, DISTRIBUTED — peacocks, deer, nagas, elephants, monkeys, sages,
  // pilgrims, bird-flocks + apsara wisps scattered across ALL bands (near→far). Anchored
  // to path geometry & offset clear of every grove medallion/label; deterministic-from-data
  // so it's stable across reloads and auto-populates new pillars. Drawn over foliage,
  // under the grove nodes (nodes are painted after) so creatures never cover a label.
  // ============================================================================
  function paintCreatures(g, pts, temple, reduced, ponds, groves) {
    if (!pts || !pts.length) return;
    const layer = el('g', {}, g);
    const r = rng('critters');
    const tod = timeOfDay();
    const tempY = temple ? temple.y : 116;
    const nearOf = y => Math.min(1, Math.max(0, (y - tempY) / (VB.h - tempY)));
    ponds = ponds || [];
    const n = pts.length;
    // per-node DIFFICULTY (0 easy … 1 hard), deterministic-from-data, for the danger mapping.
    const diffAt = pts.map((p, i) => difficultyOf(groves && groves[i] ? groves[i] : { status: 'unlocked', total: 4 }, i, n));
    // nearest grove's difficulty at an arbitrary (x,y) — so a creature's menace matches the
    // grove it's guarding, wherever it stands.
    function localDifficulty(x, y) {
      let best = 0.4, bd = 1e9;
      pts.forEach((p, i) => { const d = Math.hypot(x - p.x, y - p.y); if (d < bd) { bd = d; best = diffAt[i]; } });
      return best;
    }
    // THICKET zones — dense-foliage pockets where big cats stalk. Derived from the darker
    // between-band gaps (away from the path spine + node clearings): we treat the flank thirds
    // of hard-grove rows as thickets. Returns how "thickety" a spot is (0..1).
    function thicketAt(x, y) {
      const centre = 1 - Math.abs(x - VB.w / 2) / (VB.w / 2);   // 1 centre … 0 edge
      return Math.max(0, 1 - centre) * 0.7 + 0.3;               // edges are denser cover
    }
    function nearPond(x, y, within) {
      let best = null, bd = within || 150;
      ponds.forEach(pd => { const d = Math.hypot(x - pd.x, y - pd.y); if (d < bd) { bd = d; best = pd; } });
      return best;
    }
    // is (x,y) clear of every grove medallion + its label band? (labels hang ~y+24..+86 below)
    const clearOfNodes = (x, y) => pts.every(p => {
      const s = p.scale || 1;
      const dx = Math.abs(x - p.x), dy = y - p.y;
      const nearBody = dx < 62 * s && dy > -80 * s && dy < 34 * s;
      const nearLabel = dx < 82 * s && dy > 22 * s && dy < 88 * s;
      return !(nearBody || nearLabel);
    });
    const clearOfPonds = (x, y) => ponds.every(pd => Math.hypot(x - pd.x, y - pd.y) > 118);

    // AMBIENT budget: mark only a bounded subset of creatures as self-animating (staggered
    // phases) so the scene feels alive without animating the whole cast — keeps it 60fps.
    let ambBudget = reduced ? 0 : 18;
    function markAmbient(node) {
      if (!node || ambBudget <= 0 || r() > 0.62) return;
      ambBudget--;
      node.setAttribute('class', node.getAttribute('class') + ' ambient');
      node.style.setProperty('--ph', (-(r() * 6).toFixed(2)) + 's');
    }
    // tag a creature for PROXIMITY-REACTIVITY: prey (deer/rabbit/bird/peacock) flee; predators
    // (tiger/panther/croc/naga/boar) turn-to-face + bristle. Stores its world centre + role so
    // one delegated pointer handler (wireCreatureProximity) can react without per-node listeners.
    function tagReactive(node, role) {
      if (!node) return;
      const b = node.getBBox ? null : null;   // (bbox unreliable headless; use placement centre)
      node.setAttribute('data-react', role);
    }

    // place ONE creature of `kind` at (x,y). Returns the node (already appended).
    function make(kind, x, y, sc) {
      const dir = r() < 0.5 ? 1 : -1;
      const spiritRoll = r();
      const menace = localDifficulty(x, y) > 0.62;   // guardians near hard groves bristle
      let node = null, role = null;
      if (kind === 'peacock') { node = peacock(layer, x, y, 0.92 * sc, dir, reduced, r() > 0.5, spiritRoll > 0.78 ? 'teal' : null); role = 'prey'; }
      else if (kind === 'deer') { node = deer(layer, x, y, sc, dir, spiritRoll > 0.7 ? 'gold' : null, reduced); role = 'prey'; }
      else if (kind === 'rabbit') { node = rabbit(layer, x, y, sc, dir, reduced); role = 'prey'; }
      else if (kind === 'monkey') { node = monkey(layer, x, y, sc, dir); }
      else if (kind === 'monkey-swing') { node = monkey(layer, x, y - 6 * sc, sc * 0.95, dir, true); }
      else if (kind === 'naga') { node = naga(layer, x, y, sc, dir, spiritRoll > 0.75 ? 'teal' : null, reduced, menace); role = 'pred'; }
      else if (kind === 'elephant') { node = elephant(layer, x, y, sc, dir, spiritRoll > 0.85 ? 'teal' : null, reduced); }
      else if (kind === 'tiger') { node = tiger(layer, x, y, sc, dir, menace, reduced); role = 'pred'; }
      else if (kind === 'panther') { node = panther(layer, x, y, sc, dir, menace, reduced); role = 'pred'; }
      else if (kind === 'crocodile') { node = crocodile(layer, x, y, sc, dir, menace, reduced); role = 'pred'; }
      else if (kind === 'boar') { node = boar(layer, x, y, sc, dir, menace, reduced); role = 'pred'; }
      else if (kind === 'owl') { node = owl(layer, x, y, sc, dir, reduced); }
      else if (kind === 'heron') { node = heron(layer, x, y, sc, dir, reduced); role = 'prey'; }
      else if (kind === 'guru') { node = guru(layer, x, y, sc, reduced); }
      else if (kind === 'pilgrim') { node = pilgrim(layer, x, y, sc, dir, spiritRoll > 0.55, reduced); }
      else if (kind === 'perched') { node = perchedBird(layer, x, y, 0.9 * sc, 'pb' + x.toFixed(0) + y.toFixed(0)); role = 'prey'; }
      if (node) { markAmbient(node); if (role) tagReactive(node, role); node._cx = x; node._cy = y; node._dir = dir; node._kind = kind; }
      return node;
    }

    // choose the fauna KIND for a spot from HABITAT + local DIFFICULTY + TIME OF DAY. Gentle
    // fauna near easy/mastered groves; dangerous guardians near hard/locked groves; the right
    // animal for the terrain (water / clearing / thicket / open); day vs night casts differ.
    function pickKind(x, y, zone) {
      const diff = localDifficulty(x, y);
      const roll = r();
      if (zone === 'water') {
        // pond margins: crocodile guards a hard grove's water; else a heron fishes.
        if (diff > 0.6 && roll < 0.6) return 'crocodile';
        return roll < 0.5 ? 'heron' : (tod.night ? 'crocodile' : 'peacock');
      }
      if (zone === 'canopy') {
        if (tod.night) return roll < 0.5 ? 'owl' : 'monkey-swing';
        return roll < 0.55 ? 'monkey-swing' : 'perched';
      }
      // ground / open forest — difficulty picks the guardian vs the gentle grazer
      if (diff > 0.66) {
        // HARD grove guardians (dangerous)
        if (tod.night) return roll < 0.42 ? 'tiger' : roll < 0.7 ? 'panther' : roll < 0.86 ? 'naga' : 'boar';
        return roll < 0.34 ? 'tiger' : roll < 0.56 ? 'panther' : roll < 0.74 ? 'boar' : roll < 0.9 ? 'naga' : 'elephant';
      }
      if (diff > 0.5) {
        // mid — a mix: a lurking naga/boar OR grazers
        if (roll < 0.3) return tod.night ? 'panther' : 'boar';
        if (roll < 0.5) return 'naga';
        return roll < 0.72 ? 'deer' : roll < 0.9 ? 'peacock' : 'elephant';
      }
      // EASY / mastered — gentle coexisting fauna only
      if (tod.night) return roll < 0.4 ? 'deer' : roll < 0.7 ? 'owl' : 'rabbit';
      return roll < 0.34 ? 'deer' : roll < 0.58 ? 'peacock' : roll < 0.78 ? 'rabbit' : 'elephant';
    }

    // try to place a habitat-appropriate creature near (cx,cy): search jittered spots for a
    // clear one, choose the zone by terrain, then pick the fitting kind.
    const placed = [];   // {node,x,y,kind,role} for the vignette scripting below
    function tryPlace(cx, cy, near, forcedZone, forcedKind) {
      for (let attempt = 0; attempt < 9; attempt++) {
        const x = cx + (r() - 0.5) * 96, y = cy + (r() - 0.5) * 44;
        if (x < 44 || x > VB.w - 44 || y < 300 || y > VB.h - 26) continue;
        if (!clearOfNodes(x, y)) continue;
        let zone = forcedZone;
        if (!zone) {
          const pd = nearPond(x, y, 150);
          if (pd && !clearOfPonds(x, y)) continue;               // never ON the water body
          if (pd) zone = 'water';
          else if (y < tempY + 260 && thicketAt(x, y) > 0.55 && r() < 0.4) zone = 'canopy';
          else zone = 'ground';
        } else if (zone !== 'water' && !clearOfPonds(x, y)) continue;
        const sc = 0.78 + near * 0.82;
        const kind = forcedKind || pickKind(x, y, zone);
        const node = make(kind, x, y, sc);
        if (node) { placed.push({ node: node, x: x, y: y, kind: kind }); return node; }
      }
      return null;
    }

    // EVEN DISTRIBUTION over y-BANDS across the full height (temple → foreground) — the whole
    // world stays alive — but every spot now gets a HABITAT + DIFFICULTY-appropriate creature.
    const rows = pts.reduce((m, p) => Math.max(m, p.row || 0), 0) + 1;
    const yTop = tempY + 140, yBot = VB.h - 50;
    const bands = Math.max(5, rows + 2);
    for (let bi = 0; bi < bands; bi++) {
      const by = yTop + (yBot - yTop) * (bi / (bands - 1));
      const near = nearOf(by);
      const perBand = 4 + Math.round(near * 2);        // 4 up top … 6 near the foreground
      for (let k = 0; k < perBand; k++) {
        const fx = 0.09 + (k / Math.max(1, perBand - 1)) * 0.82 + (r() - 0.5) * 0.07;
        const cx = VB.w * Math.min(0.93, Math.max(0.07, fx));
        tryPlace(cx, by, near);
      }
    }

    // WATER-MARGIN residents: a guardian/heron explicitly at each pond that isn't already busy,
    // so crocodiles reliably appear at hard-grove water (habitat rule) — a couple per map.
    ponds.slice(0, 3).forEach((pd, i) => {
      const ex = pd.x + (i % 2 ? 1 : -1) * 116, ey = pd.y + 6;
      if (ex > 50 && ex < VB.w - 50 && clearOfNodes(ex, ey)) tryPlace(ex, ey, nearOf(ey), 'water');
    });

    // CANOPY life — swinging monkeys, perched birds, owls up in the tree bands (mid/upper).
    for (let i = 0; i < 8; i++) {
      const fx = 0.1 + (i / 7) * 0.8 + (r() - 0.5) * 0.06;
      const cx = VB.w * Math.min(0.92, Math.max(0.08, fx));
      const cy = tempY + 120 + (i / 7) * (VB.h - tempY - 300) + (r() - 0.5) * 40;
      tryPlace(cx, cy, nearOf(cy), 'canopy');
    }

    // LANTERN-BEARERS walking the luminous trail — pilgrims with glowing lamps just off the path.
    for (let i = 0; i < 2 && pts.length > 1; i++) {
      const seg = pts[Math.min(pts.length - 2, Math.floor((0.3 + i * 0.4) * (pts.length - 1)))];
      const nxt = pts[Math.min(pts.length - 1, pts.indexOf(seg) + 1)] || seg;
      const mx = (seg.x + nxt.x) / 2, my = (seg.y + nxt.y) / 2;
      for (let a = 0; a < 6; a++) {
        const side = a % 2 ? 1 : -1;
        const px = mx + side * (70 + a * 10), py = my + 6;
        if (px > 50 && px < VB.w - 50 && clearOfNodes(px, py) && clearOfPonds(px, py)) {
          pilgrim(layer, px, py, 0.9 + nearOf(py) * 0.7, side < 0 ? 1 : -1, true, reduced);
          break;
        }
      }
    }

    // bird-FLOCKS across the sky (day: more/active) + a couple weaving between the canopies.
    const nFlocks = tod.night ? 2 : 4;
    for (let i = 0; i < nFlocks; i++) flock(layer, 120 + i * 300, 116 + (i % 3) * 40, 1.0 + (i % 2) * 0.4, 'flk' + i, reduced);
    for (let i = 0; i < 2; i++) flock(layer, 260 + i * 480, tempY + 200 + (i % 2) * 90, 0.8 + (i % 2) * 0.3, 'flklow' + i, reduced);

    // FIREFLIES + spirit motes — MORE at night (nocturnal ambience), fewer by day.
    const wispCount = tod.night ? 10 : 5;
    for (let i = 0; i < wispCount; i++) {
      const fx = 0.1 + (i / (wispCount - 1 || 1)) * 0.8;
      const wx = VB.w * fx + (r() - 0.5) * 60, wy = tempY + 120 + (i / (wispCount - 1 || 1)) * (VB.h - tempY - 220) + (r() - 0.5) * 40;
      const w = el('circle', { cx: wx.toFixed(0), cy: wy.toFixed(0), r: (3.5 + r() * 3).toFixed(1), fill: 'url(#spiritTeal)', opacity: (tod.night ? 0.6 : 0.4), 'pointer-events': 'none' }, layer);
      if (!reduced) { anim(w, 'opacity', (tod.night ? '0.7' : '0.45'), '0.16', (3 + r() * 3).toFixed(1) + 's');
        animT(w, wx.toFixed(0) + ',' + wy.toFixed(0), (wx + (r() - 0.5) * 70).toFixed(0) + ',' + (wy - 30 - r() * 30).toFixed(0), (12 + r() * 8).toFixed(1) + 's'); }
    }

    // ---- ECOLOGICAL VIGNETTES: a few staggered scripted loops so the scene reads as a living
    // ecosystem (predator/prey + habitat life). Perf-bounded: only a handful, all reduced-safe,
    // transform/opacity-only. Pairs are found among already-placed creatures (no extra draws).
    scriptVignettes(placed, reduced);

    // ---- PROXIMITY REACTIVITY: one delegated pointer handler makes prey flee + predators
    // turn-to-face when the cursor nears them (see wiring in showOverview/showGrove).
    layer.setAttribute('data-crit-layer', '1');
  }

  // A handful of staggered, looping "behaviours" between placed creatures so the forest reads
  // alive: a predator eases toward nearby prey (which stays alert), monkeys leap along branches,
  // a crocodile drifts at prey by the water. Purely cosmetic transforms; reduced-motion → none.
  function scriptVignettes(placed, reduced) {
    if (reduced || !placed.length) return;
    const preds = placed.filter(p => p.kind === 'tiger' || p.kind === 'panther' || p.kind === 'crocodile');
    const prey = placed.filter(p => p.kind === 'deer' || p.kind === 'rabbit' || p.kind === 'peacock' || p.kind === 'heron');
    let budget = 4;   // at most a few live vignettes (perf)
    // predator STALKS toward the nearest prey within reach — a slow additive drift + return.
    preds.forEach(pd => {
      if (budget <= 0) return;
      let target = null, bd = 240;
      prey.forEach(py => { const d = Math.hypot(pd.x - py.x, pd.y - py.y); if (d < bd) { bd = d; target = py; } });
      if (!target) return;
      budget--;
      const dx = Math.max(-26, Math.min(26, (target.x - pd.x) * 0.4));
      const dy = Math.max(-10, Math.min(10, (target.y - pd.y) * 0.4));
      // slow creep toward the prey and back (a long, menacing loop)
      pd.node.appendChild(el('animateTransform', { attributeName: 'transform', type: 'translate', additive: 'sum',
        values: '0,0;' + dx.toFixed(0) + ',' + dy.toFixed(0) + ';0,0', dur: (11 + (Math.abs(dx) % 4)).toFixed(0) + 's', repeatCount: 'indefinite' }));
      // the prey stays ALERT — a small wary shift away
      target.node.appendChild(el('animateTransform', { attributeName: 'transform', type: 'translate', additive: 'sum',
        values: '0,0;' + (-Math.sign(dx) * 6) + ',0;0,0', dur: '5s', repeatCount: 'indefinite' }));
    });
    // MONKEYS leap between branches — a swinging monkey arcs sideways on a loop.
    placed.filter(p => p.kind === 'monkey-swing').slice(0, 2).forEach((mk, i) => {
      mk.node.appendChild(el('animateTransform', { attributeName: 'transform', type: 'translate', additive: 'sum',
        values: '0,0;' + (i % 2 ? 24 : -24) + ',-6;0,0', dur: (4 + i).toFixed(0) + 's', repeatCount: 'indefinite' }));
    });
  }

  // PROXIMITY REACTIVITY: prey flee, predators turn-to-face + bristle as the cursor nears them.
  // ONE delegated pointermove on the svg (rAF-throttled) scans the tagged creatures and toggles
  // a transform/class by distance — no per-creature listeners. pointer-fine + reduced-safe only.
  function wireCreatureProximity(svg, reduced) {
    if (reduced || !window.matchMedia || !window.matchMedia('(pointer:fine)').matches) return;
    const layer = svg.querySelector('[data-crit-layer]');
    if (!layer) return;
    const crits = Array.prototype.slice.call(layer.querySelectorAll('[data-react]'));
    if (!crits.length) return;
    // cache each creature's screen-space centre lazily (viewBox → client via getScreenCTM).
    let raf = 0, mx = -1, my = -1;
    const react = () => {
      raf = 0;
      const ctm = svg.getScreenCTM(); if (!ctm) return;
      crits.forEach(node => {
        // the placement transform holds translate(x*dir…); read the group's own box centre via
        // a cached data attr set at draw time would be ideal, but getBoundingClientRect is fine
        // here (called only while the pointer moves, on a small tagged set).
        const b = node.getBoundingClientRect();
        const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
        const dist = Math.hypot(mx - cx, my - cy);
        const near = dist < 90;
        const role = node.getAttribute('data-react');
        if (near) {
          if (!node.classList.contains('react-on')) {
            node.classList.add('react-on');
            // prey flees AWAY from the cursor; predator holds ground + bristles (class-driven).
            if (role === 'prey') {
              const ax = (cx - mx) >= 0 ? 7 : -7, ay = (cy - my) >= 0 ? 4 : -4;
              node.style.transition = 'transform .3s ease';
              node.style.transform = 'translate(' + ax + 'px,' + ay + 'px)';
            }
          }
        } else if (node.classList.contains('react-on')) {
          node.classList.remove('react-on');
          node.style.transform = '';
        }
      });
    };
    svg.addEventListener('pointermove', e => { mx = e.clientX; my = e.clientY; if (!raf) raf = requestAnimationFrame(react); });
    svg.addEventListener('pointerleave', () => { mx = -1; my = -1; crits.forEach(nn => { nn.classList.remove('react-on'); nn.style.transform = ''; }); });
  }

  // The proscenium: big dark arching banyans L/R, arch across the top, ferns/rocks
  // bottom corners — the single biggest "composed map" cue (spec §6.1).
  function paintFrame(g, reduced) {
    // top arching branches — a heavier canopy roof so the map reads as seen from within
    // a bower, with a scalloped foliage underside and hanging vine tendrils.
    el('path', { d: 'M0,0 H1200 V60 C980,130 820,74 620,92 C420,74 250,134 0,64 Z', fill: C.frame, opacity: 0.97, filter: 'url(#soft)' }, g);
    topArch(g);
    hangingLeaves(g, 300, 74, 'tl'); hangingLeaves(g, 900, 74, 'tr');
    hangingVines(g, 'tv');
    toranGarland(g);   // marigold-leaf bandhanwar swagging under the canopy roof
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
      // teal-green lit leaves catching moonlight along the crown so the corner tree reads
      // as lush overhanging foliage, not a flat black mass.
      for (let i = 0; i < 22; i++) {
        const lx = dir * (30 + r() * 300), ly = -280 + r() * 120;
        el('circle', { cx: lx.toFixed(0), cy: ly.toFixed(0), r: (4 + r() * 8).toFixed(1), fill: shade('#1f4436', 0.08 + r() * 0.22), opacity: (0.35 + r() * 0.3).toFixed(2) }, cl);
      }
      // warm lanterns hanging in the frame (ref A/alt5)
      lantern(gg, dir * 140, -30); lantern(gg, dir * 250, 60); lantern(gg, dir * 70, 90);
      // PRAYER THREADS (mauli) tied around the trunk + a small base SHRINE diya — this is
      // a SACRED tree (vat/peepal): venerated, thread-wrapped, a lamp lit at its foot.
      for (let i = 0; i < 3; i++) {
        const ty = 150 + i * 40;
        el('path', { d: 'M' + (dir * 8) + ',' + ty + ' q' + (dir * 34) + ',6 ' + (dir * 60) + ',-2', stroke: i % 2 ? C.ember : C.gold, 'stroke-width': 1.4, fill: 'none', opacity: 0.6 }, gg);
      }
      diya(gg, dir * 46, 300, 1.05, reduced, seed + 'shrine');
    }
    // a marigold + mango-leaf TORAN (bandhanwar) swagging across under the canopy roof,
    // with a couple of small prayer-flag pennants — the threshold blessing motif.
    function toranGarland(parent) {
      const gg = el('g', { opacity: 0.85 }, parent);
      const segs = 5, x0 = 70, x1 = VB.w - 70, top = 66;
      let d = 'M' + x0 + ',' + top;
      const knots = [];
      for (let i = 1; i <= segs; i++) {
        const xa = x0 + ((x1 - x0) * (i - 0.5)) / segs, xb = x0 + ((x1 - x0) * i) / segs;
        d += ' Q' + xa.toFixed(0) + ',' + (top + 30) + ' ' + xb.toFixed(0) + ',' + top;
        knots.push([xa, top + 26]);
      }
      el('path', { d: d, fill: 'none', stroke: C.goldDeep, 'stroke-width': 1.4, opacity: 0.7 }, gg);
      // marigold + leaf beads along each swag
      for (let i = 0; i <= segs * 6; i++) {
        const t = i / (segs * 6), x = x0 + (x1 - x0) * t;
        const seg = t * segs, sag = Math.sin((seg % 1) * Math.PI) * 28;
        const y = top + sag;
        el('circle', { cx: x.toFixed(0), cy: y.toFixed(0), r: 2.4, fill: i % 4 === 0 ? '#2e6b3c' : (i % 2 ? C.gold : C.ember), opacity: 0.85 }, gg);
      }
      // small mango-leaf pendants + a pennant at each swag's low point
      knots.forEach(([kx, ky], i) => {
        el('path', { d: 'M' + kx.toFixed(0) + ',' + ky.toFixed(0) + ' q-4,10 0,16 q4,-6 0,-16 Z', fill: '#2e6b3c', opacity: 0.7 }, gg);
        if (i % 2 === 0) el('path', { d: 'M' + kx.toFixed(0) + ',' + (ky + 4) + ' l8,4 l-8,4 Z', fill: i % 4 ? C.ember : C.gold, opacity: 0.75 }, gg);
      });
    }
    // a leafy scalloped underside to the top canopy roof + dangling leaf clusters
    function topArch(parent) {
      const r = rng('topArch'); const gg = el('g', {}, parent);
      for (let x = 40; x < VB.w; x += 70) {
        const y = 44 + Math.sin(x * 0.02) * 8 + r() * 10;
        for (let k = 0; k < 4; k++) el('circle', { cx: (x + (r() - 0.5) * 40).toFixed(0), cy: (y + r() * 14).toFixed(0), r: (10 + r() * 12).toFixed(0), fill: shade('#0e1c15', r() * 0.08), opacity: 0.9 }, gg);
        // a few catch moonlight
        if (r() > 0.6) el('circle', { cx: x.toFixed(0), cy: (y - 4).toFixed(0), r: (5 + r() * 4).toFixed(1), fill: shade('#254a3a', 0.14), opacity: 0.4 }, gg);
      }
    }
    // slender hanging vine tendrils with tiny leaves, draping from the top canopy
    function hangingVines(parent, seed) {
      const r = rng(seed); const gg = el('g', {}, parent);
      for (let i = 0; i < 12; i++) {
        const x = 60 + r() * (VB.w - 120), len = 40 + r() * 130, swing = (r() - 0.5) * 30;
        el('path', { d: 'M' + x.toFixed(0) + ',48 q' + swing.toFixed(0) + ',' + (len * 0.6).toFixed(0) + ' ' + (swing * 0.7).toFixed(0) + ',' + len.toFixed(0),
          stroke: '#12241a', 'stroke-width': 1.6, fill: 'none', 'stroke-linecap': 'round', opacity: 0.65 }, gg);
        for (let k = 1; k <= 3; k++) {
          const ty = 48 + len * (k / 3.2);
          el('ellipse', { cx: (x + swing * (k / 4)).toFixed(0), cy: ty.toFixed(0), rx: 3, ry: 6, fill: shade('#1c3a2b', r() * 0.2), opacity: 0.6, transform: 'rotate(' + ((r() - 0.5) * 40).toFixed(0) + ' ' + (x + swing * (k / 4)).toFixed(0) + ' ' + ty.toFixed(0) + ')' }, gg);
        }
      }
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
  // Insert a gentle mid-waypoint between each pair of nodes, nudged sideways, so the trail
  // MEANDERS like a river instead of running dead-straight between medallions. Deterministic.
  function meander(pts) {
    if (pts.length < 2) return pts.slice();
    const r = rng('meander'); const out = [pts[0]];
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      // perpendicular offset, scaled by segment length, alternating side + a little jitter
      const side = (i % 2 === 0 ? 1 : -1) * (0.9 + r() * 0.5);
      const amp = Math.min(46, len * 0.18) * side;
      out.push({ x: mx + (-dy / len) * amp, y: my + (dx / len) * amp * 0.4, scale: (a.scale + b.scale) / 2 });
      out.push(b);
    }
    return out;
  }

  function paintPath(g, pts, travelledUpto, reduced, temple) {
    // extend the trail from the last grove up to the temple so the spine clearly ends
    // at the destination (start at pts[0] entrance → temple).
    const ptsE = temple ? pts.concat([{ x: temple.x, y: temple.y + 78, scale: 0.5 }]) : pts;
    // flowing river-path through meander waypoints; the node index i maps to river index 2i
    const river = meander(ptsE);
    const riverIdx = i => Math.min(river.length, i * 2 + 1);
    // The luminous winding RIVER-PATH — the spine of the map (ref A/ref art): a broad
    // teal halo, a warm gold→teal core gradient, energy flowing up toward the temple.
    const full = pathThrough(river, null);
    if (!full) return;
    el('path', { d: full, fill: 'none', stroke: C.pathGlow, 'stroke-width': 40, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.18, filter: 'url(#soft2)' }, g);
    el('path', { d: full, fill: 'none', stroke: C.pathEdge, 'stroke-width': 20, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.30, filter: 'url(#soft)' }, g);
    el('path', { d: full, fill: 'none', stroke: 'url(#pathFlow)', 'stroke-width': 9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.68 }, g);
    el('path', { d: full, fill: 'none', stroke: '#f4f7e0', 'stroke-width': 3.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.55 }, g);
    // dashed remainder (the route AHEAD, into the upcoming/locked groves) — lifted a touch so
    // the learner can read the way forward at a glance, without overpowering the travelled gold.
    el('path', { d: full, fill: 'none', stroke: 'rgba(210,244,236,.6)', 'stroke-width': 3.2, 'stroke-linecap': 'round', 'stroke-dasharray': '2 14' }, g);
    // travelled portion — bright luminous gold-white core with flowing dashes
    if (travelledUpto >= 1) {
      const upto = Math.min(river.length, riverIdx(travelledUpto - 1) + 1);
      const gold = pathThrough(river, upto);
      el('path', { d: gold, fill: 'none', stroke: C.gold, 'stroke-width': 12, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0.42, filter: 'url(#soft)' }, g);
      el('path', { d: gold, fill: 'none', stroke: 'url(#pathG)', 'stroke-width': 6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', filter: 'url(#glow)' }, g);
      const flow = el('path', { d: gold, fill: 'none', stroke: '#fff6da', 'stroke-width': 2.2, 'stroke-linecap': 'round', 'stroke-dasharray': '2 22', opacity: 0.85 }, g);
      if (!reduced) anim(flow, 'stroke-dashoffset', '0', '-24', '1.6s', 'linear');
    }
    // DIRECTIONAL CHEVRONS flowing UP the river toward the temple — the switchback reading
    // order is non-obvious, so small arrowheads mark the way forward (backlog P0). One chevron
    // near the middle of every segment, pointing along the trail (entrance → temple). Travelled
    // chevrons are warm gold; the way-ahead ones cool teal — reinforcing the gold→teal read.
    const chev = el('g', { class: 'path-chevrons', 'pointer-events': 'none' }, g);
    for (let i = 0; i < river.length - 1; i++) {
      // one chevron per whole segment between consecutive *nodes* (skip meander midpoints so
      // they don't crowd) — river alternates node,waypoint,node… so even indices are nodes.
      if (i % 2 !== 0) continue;
      const a = river[i], b = river[Math.min(river.length - 1, i + 2)] || river[i + 1];
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      const ux = dx / len, uy = dy / len;                 // unit direction of travel (up-trail)
      const ang = Math.atan2(uy, ux) * 180 / Math.PI;
      const nodeIdx = i / 2;                              // which node this segment leaves
      const travelled = nodeIdx < travelledUpto - 1;
      const col = travelled ? C.goldBright : '#bfeee0';
      const cg = el('g', { transform: 'translate(' + mx.toFixed(1) + ',' + my.toFixed(1) + ') rotate(' + ang.toFixed(1) + ')', opacity: travelled ? 0.9 : 0.7 }, chev);
      // a small ">"-shaped arrowhead pointing forward along the path
      el('path', { d: 'M-5,-5 L4,0 L-5,5', fill: 'none', stroke: col, 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, cg);
      // upward-flowing pulse on the way-ahead chevrons (bias toward the frontier), reduced-safe
      if (!reduced && !travelled) anim(cg, 'opacity', '0.35', '0.85', (1.6 + (nodeIdx % 3) * 0.4).toFixed(1) + 's');
    }
    // a START marker at the foreground entrance
    const s0 = river[0];
    el('circle', { cx: s0.x, cy: s0.y, r: 7, fill: 'none', stroke: C.gold, 'stroke-width': 2, opacity: 0.8 }, g);
    // bead-markers at each grove along the trail (ref A)
    for (let i = 0; i < ptsE.length; i++) {
      const done = i < travelledUpto;
      el('circle', { cx: ptsE[i].x, cy: ptsE[i].y, r: done ? 2.6 : 2.8, fill: done ? C.goldBright : 'rgba(200,240,232,.72)' }, g);
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
      const ep = el('path', { class: 'pedge', d: 'M' + a.x + ',' + (a.y - 52) + ' Q' + mx + ',' + my + ' ' + b.x + ',' + (b.y - 52),
        fill: 'none', stroke: stroke, 'stroke-width': w, 'stroke-dasharray': dash, opacity: op, 'stroke-linecap': 'round' }, layer);
      // tag endpoints so hovering a grove can light up its connected route (see wireHover)
      ep.setAttribute('data-from', e.from); ep.setAttribute('data-to', e.to);
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
    grp._pillar = grove.pillar;
    if (opts.onClick && st !== 'locked') { grp.style.cursor = 'pointer'; grp.setAttribute('tabindex', '0'); }
    // inner wrapper — the part that gently blooms/scales on hover (position stays on grp)
    const inner = el('g', { class: 'g-inner' }, grp);

    // ground ring — a lotus-MANDALA / RANGOLI decal at the grove's foot (spec: sacred
    // medallion). Locked groves keep only the faint austere ring (a bare sapling shrine).
    const ringCol = st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? C.teal : C.locked;
    el('ellipse', { cx: 0, cy: 30, rx: 46, ry: 15, fill: 'none', stroke: ringCol, 'stroke-width': 1.5, opacity: st === 'locked' ? 0.44 : 0.55 }, inner);
    el('ellipse', { cx: 0, cy: 30, rx: 30, ry: 9, fill: 'none', stroke: ringCol, 'stroke-width': 1, opacity: st === 'locked' ? 0.3 : 0.35, 'stroke-dasharray': '3 5' }, inner);
    if (st !== 'locked') rangoli(inner, ringCol, st, opts.reduced);

    if (st === 'locked') {
      // bare frost-blue sapling — lifted a touch (opacity + slightly brighter stroke) so the
      // LOCKED groves waiting ahead read as visible future waypoints, not near-invisible.
      const t = el('g', { opacity: 0.72, transform: 'scale(.8)' }, inner);
      el('path', { d: 'M0,30 V-2', stroke: '#5a6874', 'stroke-width': 4, 'stroke-linecap': 'round' }, t);
      el('path', { d: 'M0,6 l-14,-12 M0,6 l14,-12 M0,18 l-11,-9 M0,18 l11,-9', stroke: '#5a6874', 'stroke-width': 3, 'stroke-linecap': 'round' }, t);
    } else {
      // a hover "bloom" halo (revealed by CSS on hover; invisible otherwise)
      el('circle', { class: 'g-bloom', cx: 0, cy: -18, r: 66, fill: st === 'blossoming' ? 'url(#nodeGold)' : 'url(#nodeTeal)', opacity: 0 }, inner);
      // signature-hued canopy: overlapping clustered volumes (a stand, not a blob)
      if (st === 'active') {
        const glow = el('circle', { cx: 0, cy: -18, r: 60, fill: 'url(#nodeTeal)', opacity: 0.5 }, inner);
        if (!opts.reduced) anim(glow, 'opacity', '0.55', '0.28', '3.4s');
        // rotating you-are-here ring
        const ring = el('circle', { cx: 0, cy: -18, r: 54, fill: 'none', stroke: C.teal, 'stroke-width': 2.2, 'stroke-dasharray': '6 8', opacity: 0.9 }, inner);
        if (!opts.reduced) { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0 0 -18', to: '360 0 -18', dur: '24s', repeatCount: 'indefinite' }); ring.appendChild(rot); }
      } else if (st === 'blossoming') {
        const glow = el('circle', { cx: 0, cy: -18, r: 52, fill: 'url(#nodeGold)', opacity: 0.5 }, inner);
        if (!opts.reduced) anim(glow, 'opacity', '0.55', '0.3', '5s');
      }
      canopy(inner, hue, st, opts.reduced, grove.pillar);
    }

    // MEDALLION — the consistent hit-target + state ring + glyph (spec §9). The ordinal
    // (1,2,3…) rides on the medallion so the journey SEQUENCE is legible at 20+ nodes.
    medallion(inner, st, ringCol, grove.pillar, opts.reduced, opts.ordinal);

    // "→ NEXT" beacon on the single recommended grove — the one thing that answers
    // "what do I do next?" in <5s (backlog P0). A pulsing teal pennant above the medallion.
    if (opts.isNext) nextBeacon(inner, opts.reduced);

    // LABEL band — permanently visible, dark plate, app serif (spec §9)
    const isCurrent = st === 'active';
    const labelTxt = opts.label != null ? opts.label : grove.pillar;
    const band = labelBand(grp, labelTxt, opts.meta != null ? opts.meta : metaFor(grove), st, isCurrent, opts.isNext);
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

  // a lotus-mandala RANGOLI on the ground at the grove's foot — a ring of foreshortened
  // petals + kolam dots, in the grove's state colour. Drawn flat (ellipse projection).
  function rangoli(grp, col, st, reduced) {
    // outer group carries the ground offset; inner .g-rangoli spins about its own centre
    // (CSS hover / SMIL) without disturbing the translate.
    const outer = el('g', { transform: 'translate(0,30)', opacity: st === 'active' ? 0.7 : 0.5 }, grp);
    const rg = el('g', { class: 'g-rangoli' }, outer);
    const petals = 12, RX = 40, RY = 13;
    for (let i = 0; i < petals; i++) {
      const a = (i / petals) * Math.PI * 2;
      const px = Math.cos(a) * RX, py = Math.sin(a) * RY;
      const nx = Math.cos(a) * (RX - 9), ny = Math.sin(a) * (RY - 3);
      // a small petal (leaf) pointing outward from the ring centre
      el('path', { d: 'M' + nx.toFixed(1) + ',' + ny.toFixed(1) + ' Q' + (px * 1.02).toFixed(1) + ',' + ((py - 2)).toFixed(1) + ' ' + (px * 1.14).toFixed(1) + ',' + py.toFixed(1) + ' Q' + (px * 1.02).toFixed(1) + ',' + ((py + 2)).toFixed(1) + ' ' + nx.toFixed(1) + ',' + ny.toFixed(1) + ' Z',
        fill: col, opacity: 0.5 }, rg);
    }
    // kolam dot ring
    for (let i = 0; i < petals; i++) {
      const a = (i / petals) * Math.PI * 2 + Math.PI / petals;
      el('circle', { cx: (Math.cos(a) * (RX - 4)).toFixed(1), cy: (Math.sin(a) * (RY - 1)).toFixed(1), r: 1, fill: col, opacity: 0.55 }, rg);
    }
    if (!reduced && st === 'active') { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0', to: '360', dur: '48s', repeatCount: 'indefinite', additive: 'sum' }); rg.appendChild(rot); }
  }

  // Icon medallion above the tree: gold-rimmed circle + a per-pillar glyph + an ORDINAL
  // badge (the grove's 1-based journey number) tucked at its lower-right, so the switchback
  // reading ORDER is unambiguous even at 20+ nodes (backlog: "number the groves").
  function medallion(grp, st, ringCol, name, reduced, ordinal) {
    const y = -58;
    const rim = st === 'blossoming' ? C.gold : st === 'active' ? C.teal : st === 'unlocked' ? C.teal : C.locked;
    const fill = st === 'blossoming' ? 'rgba(231,182,75,.9)' : st === 'active' ? 'rgba(18,77,76,.85)' : st === 'unlocked' ? 'rgba(10,20,26,.8)' : 'rgba(20,26,32,.7)';
    const m = el('g', { class: 'g-medallion', transform: 'translate(0,' + y + ')' }, grp);
    const rr = el('circle', { r: 15, fill: fill, stroke: rim, 'stroke-width': 2, opacity: st === 'locked' ? 0.68 : 1 }, m);
    if (st === 'active' && !reduced) anim(rr, 'stroke-width', '2', '3.4', '1.8s');
    const glyphCol = st === 'blossoming' ? '#3a2a08' : st === 'locked' ? '#75828e' : C.goldBright;
    const gl = el('text', { x: 0, y: 5, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 14, fill: glyphCol }, m);
    gl.textContent = glyphFor(name);
    if (ordinal != null) {
      // small numbered coin at lower-right of the medallion — dark disc, gold/teal rim
      const bx = 13, by = 12;
      el('circle', { cx: bx, cy: by, r: 8, fill: 'rgba(6,9,20,.92)', stroke: rim, 'stroke-width': 1.3, opacity: st === 'locked' ? 0.8 : 1 }, m);
      el('text', { x: bx, y: by + 3.2, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 9.5, 'font-weight': 700, fill: st === 'locked' ? '#8b98a4' : (st === 'blossoming' ? C.goldBright : '#e8f4ef') }, m).textContent = ordinal;
    }
  }

  // "→ NEXT" beacon: a bright teal pennant rising above the recommended grove's medallion,
  // with a downward arrow pointing to it. The single strongest "do this next" cue.
  function nextBeacon(grp, reduced) {
    const b = el('g', { class: 'g-next', transform: 'translate(0,-92)' }, grp);
    // soft glow behind so it reads over any canopy
    const glow = el('circle', { cx: 0, cy: 8, r: 30, fill: 'url(#nodeTeal)', opacity: 0.55 }, b);
    if (!reduced) anim(glow, 'opacity', '0.6', '0.28', '2.2s');
    // pennant plate
    el('rect', { x: -30, y: -6, width: 60, height: 18, rx: 9, fill: 'rgba(6,20,22,.94)', stroke: C.teal, 'stroke-width': 1.6 }, b);
    el('text', { x: 0, y: 6.5, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 9.5, 'font-weight': 700, 'letter-spacing': '.12em', fill: '#d6fbf4' }, b).textContent = '→ NEXT';
    // downward chevron pointing at the medallion
    const arrow = el('path', { d: 'M-6,14 L0,24 L6,14 Z', fill: C.teal }, b);
    if (!reduced) { // gentle bob toward the node
      const bob = el('animateTransform', { attributeName: 'transform', type: 'translate', values: '0,0;0,4;0,0', dur: '1.8s', repeatCount: 'indefinite', additive: 'sum' });
      arrow.appendChild(bob);
    }
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

  function labelBand(grp, title, meta, st, isCurrent, isNext) {
    const y = 44;
    const w = Math.max(70, short(title, 22).length * 6.4 + 18);
    const band = el('g', { transform: 'translate(0,' + y + ')', class: 'lbl' }, grp);
    const framed = isCurrent || isNext;
    el('rect', { class: 'lbl-plate', x: -w / 2, y: -1, width: w, height: framed ? 34 : 30, rx: 6,
      fill: 'rgba(6,9,20,.72)', stroke: framed ? C.teal : 'rgba(231,182,75,.28)', 'stroke-width': framed ? 1.4 : 0.8 }, band);
    if (isCurrent) {
      const yah = el('text', { x: 0, y: -8, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.16em', fill: C.teal }, band);
      yah.textContent = 'YOU ARE HERE';
    } else if (isNext) {
      const nx = el('text', { x: 0, y: -8, 'text-anchor': 'middle', 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.16em', fill: C.teal }, band);
      nx.textContent = 'START HERE NEXT';
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
  function declutterLabels(nodes, activeIdx, nextIdx) {
    const keep = new Set([activeIdx, activeIdx - 1, activeIdx + 1, nextIdx]);
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
  // MILESTONE CELEBRATION — a one-time bloom-burst + gold glow flourish when a grove reaches
  // MASTERED. Additive (drawn over everything, removed when done), reduced-motion safe (a
  // brief static gold bloom instead of motion). Exposed as Forest2D.celebrate(pillar) so the
  // app can fire it after a grove completes; also auto-plays for a freshly-blossoming grove
  // on load. Uses SMIL so it needs no rAF loop and self-cleans on `end`.
  // ============================================================================
  let _lastSvg = null;   // the currently-mounted map svg, so the public hook can find nodes
  function celebrateAt(svg, cx, cy, reduced) {
    if (!svg) return;
    const g = el('g', { class: 'celebrate', 'pointer-events': 'none', transform: 'translate(' + cx + ',' + cy + ')' }, svg);
    // a swelling golden glow halo
    const halo = el('circle', { cx: 0, cy: -18, r: 20, fill: 'url(#nodeGold)', opacity: 0.9 }, g);
    // a burst ring
    const ring = el('circle', { cx: 0, cy: -18, r: 20, fill: 'none', stroke: C.goldBright, 'stroke-width': 3, opacity: 0.9 }, g);
    // petals flung outward (bloom-burst)
    const petals = 12, pr = rng('celeb' + cx + cy);
    const petalNodes = [];
    for (let i = 0; i < petals; i++) {
      const a = (i / petals) * Math.PI * 2, dist = 46 + pr() * 26;
      const p = el('g', { transform: 'translate(0,-18)' }, g);
      const petal = el('path', { d: 'M0,0 Q3,-6 0,-13 Q-3,-6 0,0 Z', fill: i % 2 ? C.goldBright : C.gold, opacity: 0.95, transform: 'rotate(' + (a * 180 / Math.PI) + ')' }, p);
      petalNodes.push({ g: p, a: a, dist: dist });
    }
    if (reduced) {
      // static bloom that lingers briefly then fades — no motion, still a clear "mastered!" flash
      petalNodes.forEach(pn => pn.g.setAttribute('transform', 'translate(' + (Math.cos(pn.a) * pn.dist * 0.7).toFixed(0) + ',' + (-18 + Math.sin(pn.a) * pn.dist * 0.7).toFixed(0) + ')'));
      const f = el('animate', { attributeName: 'opacity', values: '1;1;0', keyTimes: '0;0.6;1', dur: '2.6s', begin: '0s', fill: 'freeze', repeatCount: '1' });
      g.appendChild(f); f.addEventListener('endEvent', () => g.remove()); setTimeout(() => g.remove(), 3000);
      return;
    }
    // animated: halo swells + fades, ring expands, petals fly out + fade, then self-remove.
    halo.appendChild(el('animate', { attributeName: 'r', values: '20;96', dur: '1.4s', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    halo.appendChild(el('animate', { attributeName: 'opacity', values: '0.9;0', dur: '1.6s', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    ring.appendChild(el('animate', { attributeName: 'r', values: '10;90', dur: '1.2s', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    ring.appendChild(el('animate', { attributeName: 'stroke-width', values: '4;0.4', dur: '1.2s', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    ring.appendChild(el('animate', { attributeName: 'opacity', values: '0.95;0', dur: '1.3s', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    petalNodes.forEach((pn, i) => {
      const ex = (Math.cos(pn.a) * pn.dist).toFixed(0), ey = (-18 + Math.sin(pn.a) * pn.dist - 20).toFixed(0);
      pn.g.appendChild(el('animateTransform', { attributeName: 'transform', type: 'translate', values: '0,-18;' + ex + ',' + ey, dur: (1.1 + (i % 3) * 0.2).toFixed(1) + 's', begin: '0s', fill: 'freeze', repeatCount: '1', calcMode: 'spline', keySplines: '0.2 0.8 0.3 1' }));
      pn.g.appendChild(el('animate', { attributeName: 'opacity', values: '1;1;0', keyTimes: '0;0.5;1', dur: (1.3 + (i % 3) * 0.2).toFixed(1) + 's', begin: '0s', fill: 'freeze', repeatCount: '1' }));
    });
    // self-clean after the longest tween
    setTimeout(() => { if (g.parentNode) g.remove(); }, 2200);
  }

  // public hook: fire the celebration on a grove by pillar name (the app calls this after a
  // grove is freshly mastered). No-op if the map isn't mounted / the grove isn't found.
  function celebrate(pillar, opts) {
    opts = opts || {};
    const svg = opts.svg || _lastSvg;
    if (!svg || !pillar) return false;
    const grp = svg.querySelector('.grove'); // fallback
    const target = Array.prototype.slice.call(svg.querySelectorAll('.grove')).find(n => n._pillar === pillar);
    if (!target || !target._nodePt) return false;
    const reduced = svg.classList.contains('reduced') || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    celebrateAt(svg, target._nodePt.x, target._nodePt.y, !!reduced);
    return true;
  }

  // ============================================================================
  // LIFE — fireflies, birds, player avatar (all reduced-motion aware)
  // ============================================================================
  function paintLife(g, pts, activeIdx, reduced) {
    // fireflies clustered near the path & light — denser, varied size/colour/flicker
    const r = rng('flies'); const ff = el('g', {}, g);
    for (let i = 0; i < 40; i++) {   // 40 (was 54); each a pre-baked halo+core, no live-blur FILTER
      const anchor = pts[Math.floor(r() * pts.length)] || { x: VB.w / 2, y: VB.h / 2 };
      const x = anchor.x + (r() - 0.5) * 150, y = anchor.y + (r() - 0.5) * 110;
      const col = [C.gold, C.goldBright, '#bfe9a0', C.teal][Math.floor(r() * 4)];
      const teal = col === C.teal;
      const rad = 0.6 + r() * 1.8;
      // soft radial-gradient halo (cheap) around a tiny bright dot — same firefly glow, no #glow filter
      const f = el('g', { transform: 'translate(' + x.toFixed(1) + ',' + y.toFixed(1) + ')' }, ff);
      el('circle', { r: (rad * 3 + 2).toFixed(1), fill: 'url(#' + (teal ? 'nodeTeal' : 'nodeGold') + ')', opacity: 0.55 }, f);
      el('circle', { r: rad.toFixed(1), fill: col, opacity: 0.95 }, f);
      if (!reduced) {
        anim(f, 'opacity', '0.9', '0.15', (1.4 + r() * 2.2).toFixed(1) + 's');
        const dx = (r() - 0.5) * 40, dy = (r() - 0.5) * 34;
        animT(f, '0,0', dx.toFixed(0) + ',' + dy.toFixed(0), (5 + r() * 5).toFixed(1) + 's');
      }
    }
    // spirit-wisps — a few larger, soft, slow motes drifting along the trail
    for (let i = 0; i < 4; i++) {
      const a = pts[Math.min(pts.length - 1, Math.floor((i + 1) / 5 * pts.length))] || pts[0];
      if (!a) break;
      const wx = a.x + (r() - 0.5) * 40, wy = a.y - 30 - r() * 20;
      const w = el('circle', { cx: wx.toFixed(0), cy: wy.toFixed(0), r: (4 + r() * 3).toFixed(1), fill: 'url(#nodeTeal)', opacity: 0.55 }, ff);
      if (!reduced) { anim(w, 'opacity', '0.55', '0.15', (3 + r() * 3).toFixed(1) + 's');
        animT(w, wx.toFixed(0) + ',' + wy.toFixed(0), (wx + (r() - 0.5) * 60).toFixed(0) + ',' + (wy - 30 - r() * 30).toFixed(0), (12 + r() * 8).toFixed(1) + 's'); }
    }
    // 2 gliding birds on looping arcs across the sky band (each sweeps a wide region; the
    // flocks above already carry the sky's motion, so 2 is plenty).
    if (!reduced) for (let i = 0; i < 2; i++) bird(g, 240 + i * 460, 150 + i * 26, 22 + i * 6, 'bird' + i);
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
  function paintHUD(g, groves, pts, activeIdx, reduced, isDrill, title, nextIdx) {
    // ---- minimap (top-left) ----
    const mm = el('g', { transform: 'translate(20,20)', class: 'hud' }, g);
    el('rect', { x: 0, y: 0, width: 168, height: 116, rx: 8, fill: 'rgba(6,9,20,.78)', stroke: 'rgba(231,182,75,.35)', 'stroke-width': 1 }, mm);
    el('text', { x: 10, y: 16, 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.14em', fill: C.gold }, mm).textContent = isDrill ? 'GROVE MAP' : 'FOREST MAP';
    // scaled scatter of all nodes + the trail
    const mmx = 12, mmy = 30, mmw = 144, mmh = 74;
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
    // TEMPLE marker at the destination end (top of the trail): a small gold shikhara glyph.
    const topP = pts.reduce((m, p) => p.y < m.y ? p : m, pts[0]);
    const tmx = sx(topP.x), tmy = mmy - 3;
    el('path', { d: 'M' + (tmx - 4) + ',' + tmy + ' L' + tmx + ',' + (tmy - 6) + ' L' + (tmx + 4) + ',' + tmy + ' Z', fill: C.goldBright, stroke: C.goldDeep, 'stroke-width': 0.5 }, mm);
    // "YOU" marker — a teal caret pinned at the current grove so the minimap answers "where am I".
    const you = pts[activeIdx] || pts[0];
    if (you) {
      const yg = el('g', { transform: 'translate(' + sx(you.x).toFixed(1) + ',' + (sy(you.y) - 8).toFixed(1) + ')' }, mm);
      el('path', { d: 'M0,6 L-3.4,0 L3.4,0 Z', fill: C.teal, stroke: '#06141a', 'stroke-width': 0.5 }, yg);
      if (!reduced) anim(yg, 'opacity', '1', '0.5', '1.6s');
    }

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

    // ---- compass rose (bottom-left) — a CHAKRA / lotus-mandala compass (Indic ornament) ----
    const cp = el('g', { transform: 'translate(64,' + (VB.h - 66) + ')', class: 'hud', opacity: 0.92 }, g);
    // outer lotus-petal wreath (dharmachakra feel) — slow turning
    const wreath = el('g', { opacity: 0.5 }, cp);
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      el('path', { d: 'M' + (Math.cos(a) * 34).toFixed(1) + ',' + (Math.sin(a) * 34).toFixed(1) + ' L' + (Math.cos(a) * 40).toFixed(1) + ',' + (Math.sin(a) * 40).toFixed(1),
        stroke: i % 2 ? C.goldBright : 'rgba(231,182,75,.5)', 'stroke-width': i % 2 ? 1.4 : 0.7, 'stroke-linecap': 'round' }, wreath);
    }
    if (!reduced) { const rot = el('animateTransform', { attributeName: 'transform', type: 'rotate', from: '0', to: '360', dur: '90s', repeatCount: 'indefinite' }); wreath.appendChild(rot); }
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
    const tc = el('g', { transform: 'translate(' + VB.w / 2 + ',' + (VB.h - 34) + ')', class: 'hud' }, g);
    el('rect', { x: -w / 2, y: -20, width: w, height: 44, rx: 20, fill: 'rgba(6,9,20,.7)', stroke: 'rgba(231,182,75,.35)', 'stroke-width': 1 }, tc);
    el('text', { x: 0, y: -1, 'text-anchor': 'middle', 'font-family': 'Cinzel, serif', 'font-weight': 700, 'font-size': 13, 'letter-spacing': '.14em', fill: C.goldBright }, tc).textContent = title || 'THE FOREST OF MASTERY';
    // Devanagari creed (self-study · practice · attainment) — the app's motif, tastefully small
    el('text', { x: 0, y: 15, 'text-anchor': 'middle', 'font-family': 'Tiro Devanagari Hindi, serif', 'font-size': 10.5, 'letter-spacing': '.04em', fill: C.gold, opacity: 0.82 }, tc).textContent = 'स्वाध्याय · साधना · सिद्धि';
    // little lotus-bud finials flanking the cartouche
    [-1, 1].forEach(s => {
      const fx = s * (w / 2 + 10);
      el('path', { d: 'M' + fx + ',-2 q' + (s * 5) + ',-8 0,-14 q' + (-s * 5) + ',6 0,14 Z', fill: 'none', stroke: 'rgba(231,182,75,.5)', 'stroke-width': 1 }, tc);
      el('circle', { cx: fx, cy: 2, r: 1.6, fill: C.gold, opacity: 0.7 }, tc);
    });

    // ---- progress readout (bottom-right, ref A) — a clearer forward-momentum line: how many
    // groves mastered, and how many concepts remain in the NEXT recommended grove ("3 to go")
    // so the learner always sees the immediate objective, not just an overall count. ----
    const done = groves.filter(g => g.status === 'blossoming').length;
    const pct = groves.length ? done / groves.length : 0;
    const pb = el('g', { transform: 'translate(' + (VB.w - 200) + ',' + (VB.h - 40) + ')', class: 'hud' }, g);
    el('text', { x: 0, y: -12, 'font-family': 'JetBrains Mono, monospace', 'font-size': 8.5, 'letter-spacing': '.1em', fill: C.parchDim }, pb).textContent =
      (isDrill ? 'CONCEPTS MASTERED ' : 'GROVES MASTERED ') + done + ' of ' + groves.length;
    // "next up" sub-line: the recommended grove + concepts left in it
    const ng = (nextIdx != null && nextIdx >= 0) ? groves[nextIdx] : null;
    if (ng) {
      const left = Math.max(0, (ng.total || 0) - (ng.done || 0));
      const nm = short(ng.pillar, 22);
      el('text', { x: 0, y: -2, 'font-family': 'JetBrains Mono, monospace', 'font-size': 7.5, 'letter-spacing': '.06em', fill: C.teal }, pb).textContent =
        '→ NEXT: ' + nm + (left ? ' · ' + left + ' to go' : '');
    }
    el('rect', { x: 0, y: 4, width: 180, height: 6, rx: 3, fill: 'rgba(6,9,20,.7)', stroke: 'rgba(231,182,75,.3)', 'stroke-width': 0.6 }, pb);
    el('rect', { x: 1, y: 5, width: Math.max(0, 178 * pct).toFixed(1), height: 4, rx: 2, fill: C.gold }, pb);
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

  // The single RECOMMENDED next grove = first available/unlocked in journey order (backlog
  // P0). Prefer the active grove if it still has work; else the first unlocked; else the
  // first non-locked. Returns an index into the ordered groves, or -1 if all mastered.
  function recommendNext(groves) {
    const active = groves.findIndex(g => g.status === 'active');
    if (active >= 0 && (groves[active].done || 0) < (groves[active].total || 1)) return active;
    const unlocked = groves.findIndex(g => g.status === 'unlocked');
    if (unlocked >= 0) return unlocked;
    return groves.findIndex(g => g.status !== 'blossoming');
  }

  // ============================================================================
  // PUBLIC — overview & drill-in
  // ============================================================================
  function prep(svg) {
    svg.setAttribute('viewBox', '0 0 ' + VB.w + ' ' + VB.h);
    // ALWAYS `meet` (contain) so the ENTIRE map fits inside the panel with nothing clipped —
    // the whole vertical story reads top→bottom: mandir → every grove row → the bottom labels
    // and the diegetic HUD (minimap, compass, title cartouche, GROVES-MASTERED progress bar),
    // which all live near the viewBox edges. `slice` used to crop those bottom rows / the HUD
    // on wide-short panels (the reported clipping); `meet` guarantees the full composition on
    // desktop AND mobile. A little letterbox is acceptable; the frame/vignette blend into it.
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
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
      const nextIdx = recommendNext(groves);
      const travelled = (() => {
        let i = groves.findIndex(g => g.status === 'active');
        if (i >= 0) return i + 1;
        return groves.filter(g => g.status === 'blossoming').length;
      })();

      defs(svg, reduced);
      injectStyles(svg);
      const bg = el('g', {}, svg);
      paintSky(bg, reduced, groves);
      paintHills(bg);
      paintTemple(bg, lay.temple, reduced, groves);
      paintMist(bg, reduced);
      paintStands(bg, reduced);
      paintBandFoliage(bg, pts, lay.temple, reduced);          // lush trees + understorey along EVERY band
      const ponds = pondSpots(pts, lay.temple);
      ponds.forEach((sp, i) => paintPond(bg, reduced, sp, i));  // kunds across the map
      paintGodRays(bg, lay.temple, reduced);

      // edges (faint vines, drawn first/under) → then the luminous path (dominant spine)
      const world = el('g', {}, svg);
      const posByPillar = {}; groves.forEach((g, i) => posByPillar[g.pillar] = pts[i]);
      const statusByPillar = {}; groves.forEach(g => statusByPillar[g.pillar] = g.status);
      paintEdges(world, c.edges || [], posByPillar, statusByPillar);
      paintPath(world, pts, travelled, reduced, lay.temple);
      paintPathDiyas(world, pts, reduced);
      paintCreatures(world, pts, lay.temple, reduced, ponds, groves);  // habitat + difficulty-mapped fauna

      // draw nodes back-to-front (far/high first) so foreground groves overlap correctly
      const order = groves.map((g, i) => i).sort((a, b) => pts[a].y - pts[b].y);
      const nodeGroups = new Array(groves.length);
      order.forEach(i => { nodeGroups[i] = groveNode(world, groves[i], pts[i], {
        hue: signatureHue(groves[i].pillar), reduced: reduced, ordinal: i + 1, isNext: i === nextIdx,
        onClick: opts.onGrove ? (p) => opts.onGrove(p) : null
      }); });
      declutterLabels(nodeGroups, activeIdx, nextIdx);

      paintLife(world, pts, activeIdx, reduced);
      // foreground proscenium last (frames everything)
      paintFrame(svg, reduced);
      el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#vig)', 'pointer-events': 'none' }, svg);
      paintHUD(svg, groves, pts, activeIdx, reduced, false, 'THE FOREST OF MASTERY', nextIdx);
      // interactivity: delegated hover (edge routes + affordances) + subtle cursor parallax.
      // The far background drifts a touch more than the foreground world for a gentle vista;
      // both shifts are only a few viewBox units → imperceptible to click targets.
      wireHover(svg);
      wireCreatureProximity(svg, reduced);
      wireParallax(svg, [{ node: world, k: 3 }], reduced);
      wireVisibilityPause(svg, reduced);
      _lastSvg = svg;
      if (reduced) svg.classList.add('reduced');
      // one-time milestone flourish: if the caller names a freshly-mastered grove, celebrate it.
      if (opts.celebratePillar) setTimeout(() => celebrate(opts.celebratePillar, { svg: svg }), 260);
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
      const nextIdx = recommendNext(groves);

      defs(svg, reduced);
      injectStyles(svg);
      const bg = el('g', {}, svg);
      paintSky(bg, reduced);
      paintHills(bg);
      paintTemple(bg, lay.temple, reduced, groves);
      paintMist(bg, reduced);
      paintStands(bg, reduced);
      paintBandFoliage(bg, pts, lay.temple, reduced);
      const ponds = pondSpots(pts, lay.temple);
      ponds.forEach((sp, i) => paintPond(bg, reduced, sp, i));
      paintGodRays(bg, lay.temple, reduced);

      const world = el('g', {}, svg);
      // intra-pillar edges (under) → luminous path (over)
      const posByName = {}; c.concepts.forEach((cc, i) => posByName[cc.name] = pts[i]);
      const statusByName = {}; groves.forEach(g => statusByName[g.pillar] = g.status);
      paintEdges(world, c.edges || [], posByName, statusByName);
      paintPath(world, pts, travelled, reduced, lay.temple);
      paintPathDiyas(world, pts, reduced);
      paintCreatures(world, pts, lay.temple, reduced, ponds, groves);

      const order = groves.map((g, i) => i).sort((a, b) => pts[a].y - pts[b].y);
      const nodeGroups = new Array(groves.length);
      order.forEach(i => { nodeGroups[i] = groveNode(world, groves[i], pts[i], {
        hue: hue, reduced: reduced, ordinal: i + 1, isNext: i === nextIdx,
        label: c.concepts[i].name, meta: metaC(c.concepts[i].status),
        // an available/active concept is a "dive in and practise this" target
        onClick: (opts.onConcept && c.concepts[i].status !== 'lock') ? () => opts.onConcept(c.concepts[i].name, pillar) : null
      }); });
      declutterLabels(nodeGroups, activeIdx, nextIdx);

      paintLife(world, pts, activeIdx, reduced);
      paintFrame(svg, reduced);
      el('rect', { x: 0, y: 0, width: VB.w, height: VB.h, fill: 'url(#vig)', 'pointer-events': 'none' }, svg);
      // back-to-overview affordance (top-right)
      const back = el('g', { transform: 'translate(' + (VB.w - 150) + ',30)', class: 'hud', style: 'cursor:pointer' }, svg);
      el('rect', { x: -8, y: -16, width: 138, height: 26, rx: 13, fill: 'rgba(6,9,20,.78)', stroke: 'rgba(231,182,75,.4)', 'stroke-width': 1 }, back);
      el('text', { x: 4, y: 2, 'font-family': 'JetBrains Mono, monospace', 'font-size': 10, fill: C.goldBright }, back).textContent = '← forest overview';
      if (opts.onBack) back.addEventListener('click', opts.onBack);
      paintHUD(svg, groves, pts, activeIdx, reduced, true, short(pillar, 30).toUpperCase(), nextIdx);
      wireHover(svg);
      wireCreatureProximity(svg, reduced);
      wireParallax(svg, [{ node: world, k: 3 }], reduced);
      wireVisibilityPause(svg, reduced);
      _lastSvg = svg;
      if (reduced) svg.classList.add('reduced');
      if (opts.celebrateConcept) setTimeout(() => celebrate(opts.celebrateConcept, { svg: svg }), 260);
      return c;
    }).catch(() => { empty(svg, 'could not load this grove.'); return null; });
    function metaC(s) { return s === 'done' ? '✦ mastered' : s === 'avail' ? '◇ available' : '— locked'; }
  }

  global.Forest2D = { showOverview: showOverview, showGrove: showGrove, celebrate: celebrate, VB: VB };
  // dev-only: expose creature factories for the offline art-gallery screenshot harness. Gated
  // behind an explicit flag so it never ships behaviour to the app; tree-shakes to nothing.
  if (global.__FOREST_DEBUG__) {
    global.Forest2D._creatures = { peacock, deer, naga, elephant, monkey, tiger, panther,
      crocodile, boar, owl, heron, rabbit, guru, pilgrim, perchedBird, diya };
    global.Forest2D._defs = defs;
  }
})(window);
