/* =============================================================================
   Ekalavya · Forest of Mastery — a REAL-TIME 3D scene (Three.js r128)
   -----------------------------------------------------------------------------
   Our own stylised interpretation of an enchanted, mythological ancient-India
   forest journey: a night woodland under a warm moon, a glowing winding path
   past ornate milestone-trees (one per curriculum PILLAR, in learning order)
   climbing toward a golden temple on a distant hill. Status drives each grove's
   look; the active grove wears a teal "YOU ARE HERE" ring and the camera rests
   near it. Clicking a grove reuses the SPA's detail popover; flying into a grove
   reveals its concepts as a short sub-forest.

   Everything is generated from report.forest_map() — nothing is hardcoded, so
   the scene grows with the curriculum. Motion is gated by reduced-motion; GL
   resources are disposed and the rAF loop paused when the forest view is hidden;
   a graceful message shows if WebGL is unavailable.

   Exposes window.Forest3D — the SPA drives it (mount / renderForest / drillIn /
   back / setVisible / dispose). Uses window hooks the SPA provides:
     _reduced()      → true when calm/static mode is on
     _openGrovePop / _openConceptPop / hideNodePop → the shared popover
   Palette (Option E): indigo night #0a0c18–#141024, gold #e7b64b/#f7d98a,
   teal #57d3ce, ember-amber firelight.
   ============================================================================= */
(function () {
  "use strict";
  var T = window.THREE;

  // ---- palette -------------------------------------------------------------
  // DERIVED FROM THE APP'S OPTION-E DESIGN TOKENS (webapp.py :root) so the 3D scene
  // sits harmoniously inside the app frame — same indigo night, gold (#e7b64b/#f7d98a),
  // teal/peacock (#57d3ce), ember/amber. The fix-spec §5 palette is reconciled toward
  // these tokens: the GROUND is a saturated teal-green earth (never grey), shadows are
  // blue-violet (via the hemisphere fill), highlights clamp to warm gold — never pure white.
  var COL = {
    // sky / night — app --indigo-night #101528 base, lifting to a warm lilac-gold horizon
    nightTop: 0x0d1224, nightMid: 0x1a1a34, nightLow: 0x3a3358,   // indigo zenith → warm lilac horizon
    skyWarm: 0xe8b866,                                            // temple-glow horizon band
    fog: 0x20233f,
    // GROUND — saturated teal-green earth (spec §5 --forest-ground #1E3B3A), warm sage in light.
    ground: 0x1e3b3a, groundLit: 0x5e7350, groundPath: 0x2a4a40,
    // gold family (app tokens) — mastered state, temple, lanterns
    gold: 0xe7b64b, goldBright: 0xf7d98a, goldDeep: 0xb8862f, goldEmber: 0x8a5e1f,
    // teal / peacock (app tokens) — available + you-are-here + spirit wisps + path network
    teal: 0x57d3ce, tealBright: 0x9ff2ea, tealDeep: 0x2ea3a0,
    // foliage greens (app --forest / --forest-lit), warmer than the old olive-black
    green: 0x52a061, greenLit: 0x84c778, canopyDark: 0x1b3a34,   // filler canopy in shadow (teal-green)
    ember: 0xffab52, moon: 0xfff2d8, vermilion: 0xff5a3c,
    trunk: 0x6a5142, trunkLit: 0x8a7060, trunkDark: 0x4a3a44,     // desaturated brown-violet (spec §3)
    locked: 0x5a6a86, lockedLeaf: 0x3a4a64,                       // frost-blue locked (spec §9)
  };

  // Grove SIGNATURE canopy hues (spec §3b) — reconciled toward the app's jewel-tone family
  // (indigo/gold/teal base) so groves are distinguishable BEFORE reading a label, without
  // fighting the chrome. Assigned deterministically by grove ORDER (stable, data-driven for
  // any N pillars — never keyed to today's 7). Gold stays reserved for mastered, teal for
  // active/available (those live on the emissive/glow channel, not the hue channel).
  var SIGNATURE_HUES = [
    0x3e8c6a,  // jade-emerald
    0x2e8ca0,  // teal-cyan
    0x6b5aa0,  // violet-indigo
    0xb8893a,  // muted gold-amber
    0xa85c4c,  // copper-terracotta
    0x4e9a78,  // sea-green
    0x8a4f73,  // plum
    0x5a7ab0,  // steel-blue
    0x9a7a3a,  // brass
    0x4a6a9a,  // slate-indigo
  ];
  function signatureHue(order) {
    return SIGNATURE_HUES[((order % SIGNATURE_HUES.length) + SIGNATURE_HUES.length) % SIGNATURE_HUES.length];
  }

  // HUE FAMILIES (spec update): at ~18 pillars, 18 unrelated hues read as noise. Instead the
  // canopy hue is a function of the grove's POSITION ALONG THE JOURNEY (its order fraction u),
  // sweeping smoothly through a curated ramp of jewel tones — so the map reads as REGIONS of a
  // world (a warm gold foothills band → cool teal midlands → deep violet highlands near the
  // temple) rather than a random palette. A small per-grove hue jitter keeps neighbours
  // distinct. Fully data-driven: any N pillars just sample the same ramp at N points.
  // All tones sit within the app's indigo / gold / teal family (harmonious with the chrome).
  var HUE_RAMP = [
    0xb8893a,  // 0.00 — warm brass/gold (foundations, foothills)
    0xa8794a,  // copper-amber
    0x8a8a4a,  // olive-gold
    0x5a9a6a,  // warm sea-green (transition)
    0x3e9c7a,  // jade
    0x2e9aa0,  // teal (midlands)
    0x3a86b0,  // cyan-steel
    0x4a6aae,  // indigo-blue
    0x6a5aa8,  // violet
    0x7a4f8c,  // plum (highlands, near temple)
  ];
  function rampHue(u) {
    u = Math.max(0, Math.min(1, u));
    var f = u * (HUE_RAMP.length - 1);
    var i = Math.floor(f), t = f - i;
    var a = new T.Color(HUE_RAMP[i]), b = new T.Color(HUE_RAMP[Math.min(HUE_RAMP.length - 1, i + 1)]);
    return a.lerp(b, t);
  }
  // The signature hue for a grove given its journey fraction u + a stable seed for jitter.
  function familyHue(u, seed) {
    var c = rampHue(u);
    var r = rng(seed >>> 0 || 1);
    c.offsetHSL((r() - 0.5) * 0.04, (r() - 0.5) * 0.06, (r() - 0.5) * 0.05);
    return c.getHex();
  }

  // A grove NODE MEDALLION (spec §9): a small gold/teal-rimmed disc floating above the tree —
  // the consistent click target + the state indicator, legible at any zoom. State rides the
  // rim colour + fill; grove identity rides the canopy hue below it. A tiny glyph disc marks
  // mastered/active. Returns a Group; billboards toward the camera in the loop.
  function buildMedallion(style) {
    var g = new T.Group();
    var state = style.state;
    var rim = state === "blossoming" ? COL.gold
      : state === "active" ? COL.teal
      : state === "unlocked" ? COL.tealDeep : COL.locked;
    var fillC = state === "blossoming" ? COL.goldDeep
      : state === "active" ? COL.tealDeep
      : state === "unlocked" ? 0x1c3340 : 0x2a3348;
    // backing disc (dark, so the rim reads on any canopy)
    var back = new T.Mesh(new T.CircleGeometry(2.5, 28),
      new T.MeshBasicMaterial({ color: fillC, transparent: true, opacity: 0.9, fog: false }));
    g.add(back);
    // rim ring
    var ring = new T.Mesh(new T.RingGeometry(2.5, 3.1, 32),
      new T.MeshBasicMaterial({ color: rim, transparent: true, opacity: state === "locked" ? 0.5 : 0.95,
        blending: T.AdditiveBlending, depthWrite: false, fog: false }));
    g.add(ring);
    // inner glyph pip for mastered/active (a filled centre); locked has none
    if (state === "blossoming" || state === "active") {
      var pip = new T.Mesh(new T.CircleGeometry(1.1, 20),
        new T.MeshBasicMaterial({ color: state === "blossoming" ? COL.goldBright : COL.tealBright, fog: false }));
      pip.position.z = 0.02; g.add(pip);
    }
    // a soft glow behind lit medallions so they pop as beacons (bloom lifts them)
    if (state !== "locked") {
      var halo = glowSprite(rim, 12, state === "active" ? 0.5 : 0.32, true);
      halo.position.z = -0.1; g.add(halo);
      g.userData.halo = halo;
    }
    g.userData.ring = ring; g.userData.state = state;
    g.userData.disposables = [back.geometry, back.material, ring.geometry, ring.material];
    return g;
  }

  // Recursively flag a subtree to cast (and its ground-touching parts to receive) shadows.
  function setShadow(obj, cast) {
    obj.traverse(function (o) { if (o.isMesh) { o.castShadow = cast; o.receiveShadow = false; } });
  }

  // A carved stone PLINTH the milestone tree grows from + a glowing rangoli RING decal set
  // into the earth (spec §9 node-as-shrine). The ring colour tracks state. Small + cheap.
  function buildPlinth(scale, st) {
    var g = new T.Group();
    var s = scale || 1;
    var stone = new T.MeshStandardMaterial({ color: 0x2b3550, roughness: 0.95, flatShading: true });
    var base = new T.Mesh(new T.CylinderGeometry(3.4 * s, 4.0 * s, 1.4 * s, 12), stone);
    base.position.y = 0.7 * s; base.receiveShadow = true; base.castShadow = true; g.add(base);
    // rangoli ring decal — a thin glowing torus laid flat in the earth around the plinth
    var rc = st.state === "blossoming" ? COL.gold : st.state === "active" ? COL.teal
      : st.state === "unlocked" ? COL.tealDeep : COL.locked;
    var ring = new T.Mesh(new T.TorusGeometry(5.2 * s, 0.16 * s, 8, 40),
      new T.MeshBasicMaterial({ color: rc, transparent: true, opacity: st.bare ? 0.3 : 0.7,
        blending: T.AdditiveBlending, depthWrite: false }));
    ring.rotation.x = Math.PI / 2; ring.position.y = 0.15; g.add(ring);
    return g;
  }

  // PATH-AS-GRAPH edges (spec §10): a glowing thread from each prereq grove to its dependent,
  // drawn as a thin bloomable tube hugging the ground, state-styled. src/dst are pillar names.
  function buildEdges(edges, laid, nodeIndex) {
    var g = new T.Group();
    var disposables = [];
    for (var i = 0; i < edges.length; i++) {
      var a = nodeIndex[edges[i].src], b = nodeIndex[edges[i].dst];
      if (a == null || b == null) continue;
      var A = laid[a], B = laid[b];
      var sa = A.grove.status, sb = B.grove.status;
      // traversed: both mastered → gold. available-next: dst is active/unlocked & src done → teal.
      // else dim/locked.
      var traversed = (sa === "blossoming" && sb === "blossoming");
      var avail = (sa === "blossoming") && (sb === "active" || sb === "unlocked");
      var col = traversed ? COL.gold : avail ? COL.teal : COL.locked;
      var op = traversed ? 0.55 : avail ? 0.6 : 0.22;
      var p0 = new T.Vector3(A.x, groundY(A.x, A.z) + 0.4, A.z);
      var p2 = new T.Vector3(B.x, groundY(B.x, B.z) + 0.4, B.z);
      var mid = p0.clone().lerp(p2, 0.5);
      mid.x += (B.z - A.z) * 0.05; mid.z -= (B.x - A.x) * 0.05;   // gentle bow
      mid.y = groundY(mid.x, mid.z) + 1.2;
      var curve = new T.QuadraticBezierCurve3(p0, mid, p2);
      var geo = new T.TubeGeometry(curve, 20, 0.35, 6, false);
      var mat = new T.MeshBasicMaterial({ color: col, transparent: true, opacity: op,
        blending: T.AdditiveBlending, depthWrite: false, fog: false });
      var m = new T.Mesh(geo, mat); g.add(m);
      disposables.push(geo, mat);
    }
    g.userData.disposables = disposables;
    return g;
  }

  // status → a small style descriptor the tree/particle builders read. `sig` is the grove's
  // signature canopy hue (§3b): grove IDENTITY rides the canopy hue, node STATE rides the
  // glow/emissive channel + a state tint blended over the signature. This keeps the two
  // information channels separate (spec §3b).
  function styleFor(status, sig) {
    sig = sig != null ? sig : COL.green;
    var sigC = new T.Color(sig);
    var mixToward = function (hex, k) { return sigC.clone().lerp(new T.Color(hex), k).getHex(); };
    switch (status) {
      // MASTERED: signature hue lifted toward gold + gold blossoms; gold glow. Never pure white.
      case "blossoming": return { leaf: mixToward(COL.gold, 0.45), leaf2: COL.goldBright, glow: COL.gold,
        bare: false, lush: 1.18, emissive: 0.12, state: "blossoming", sig: sig };
      // ACTIVE (current focus): brightest signature hue, teal glow (you-are-here channel).
      case "active":     return { leaf: sigC.clone().offsetHSL(0, 0.05, 0.12).getHex(), leaf2: COL.tealBright, glow: COL.teal,
        bare: false, lush: 1.08, emissive: 0.14, state: "active", sig: sig };
      // AVAILABLE: signature hue at moderate value, soft teal glow.
      case "unlocked":   return { leaf: sig, leaf2: sigC.clone().offsetHSL(0, 0, 0.16).getHex(), glow: COL.teal,
        bare: false, lush: 0.96, emissive: 0.07, state: "unlocked", sig: sig };
      // LOCKED: bare frost-blue branches, no foliage, small.
      default:           return { leaf: COL.lockedLeaf, leaf2: COL.locked, glow: COL.locked,
        bare: true, lush: 0.62, emissive: 0.0, state: "locked", sig: sig };
    }
  }

  // ---- module state --------------------------------------------------------
  var S = null;   // the live scene bundle (null when disposed)

  function reduced() {
    try { return !!(window._reduced && window._reduced()); } catch (e) { return false; }
  }

  function _escHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Detect WebGL up-front so we can fall back gracefully instead of crashing.
  function webglOK() {
    try {
      var c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (e) { return false; }
  }

  // A tiny seeded PRNG so a given curriculum always paints the same wood.
  function rng(seed) {
    var s = seed >>> 0 || 1;
    return function () { s = (s * 1664525 + 1013904223) & 0xffffffff; return (s >>> 0) / 0xffffffff; };
  }
  function hashStr(str) {
    var h = 2166136261; str = String(str || "");
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = (h * 16777619) >>> 0; }
    return h >>> 0;
  }

  // A 4-step gradient RAMP for cel/toon shading (Ghibli-ish banded light). Built once,
  // shared by every toon material so the whole wood reads as one painterly illustration
  // rather than smooth PBR. NearestFilter keeps the steps hard.
  var _ramp = null;
  function toonRamp() {
    if (_ramp) return _ramp;
    // 4 GRAYSCALE steps as full RGBA so the gradientMap tints neutrally (a Red-only
    // texture would warm every material). NearestFilter keeps the bands hard (cel look).
    var steps = [70, 118, 175, 255], data = new Uint8Array(steps.length * 4);
    for (var i = 0; i < steps.length; i++) {
      data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = steps[i]; data[i * 4 + 3] = 255;
    }
    _ramp = new T.DataTexture(data, steps.length, 1, T.RGBAFormat);
    _ramp.minFilter = _ramp.magFilter = T.NearestFilter;
    _ramp.generateMipmaps = false; _ramp.needsUpdate = true;
    return _ramp;
  }
  // A MeshToonMaterial with our ramp (falls back to Standard if Toon is unavailable),
  // plus optional height-masked WIND sway injected via onBeforeCompile so canopies wave
  // while trunks stay planted. `windScene` collects the shared uTime uniform for the loop.
  var _windUniforms = [];
  function toonMat(opts) {
    opts = opts || {};
    var m;
    if (T.MeshToonMaterial) {
      m = new T.MeshToonMaterial({ color: opts.color, emissive: opts.emissive || 0x000000,
        gradientMap: toonRamp() });
      if (opts.emissive != null) m.emissiveIntensity = opts.emissiveIntensity != null ? opts.emissiveIntensity : 1;
    } else {
      m = new T.MeshStandardMaterial({ color: opts.color, emissive: opts.emissive || 0x000000,
        emissiveIntensity: opts.emissiveIntensity != null ? opts.emissiveIntensity : 1,
        roughness: 0.85, flatShading: !!opts.flat });
    }
    if (opts.wind) {
      m.onBeforeCompile = function (shader) {
        shader.uniforms.uTime = { value: 0 };
        shader.uniforms.uSway = { value: opts.wind };
        _windUniforms.push(shader.uniforms.uTime);
        shader.vertexShader = shader.vertexShader
          .replace("#include <common>",
            "#include <common>\nuniform float uTime;\nuniform float uSway;")
          .replace("#include <begin_vertex>",
            "#include <begin_vertex>\n" +
            // mask by height above the local origin so trunks stay put; sum of sines sways
            "float wMask = clamp((position.y)/6.0, 0.0, 1.0);\n" +
            "float w = sin(uTime*0.9 + position.x*0.3) + sin(uTime*1.3 + position.z*0.4)*0.6;\n" +
            "transformed.x += w * uSway * wMask;\n" +
            "transformed.z += w * uSway * 0.5 * wMask;");
      };
    }
    return m;
  }

  // =========================================================================
  // GEOMETRY BUILDERS
  // =========================================================================

  // Undulating terrain: a large plane displaced by layered sines → soft rolling
  // ground that rises toward the temple hill at the far (−Z) end.
  function buildTerrain() {
    var W = 620, D = 680, segW = 140, segD = 150;
    var geo = new T.PlaneGeometry(W, D, segW, segD);
    geo.rotateX(-Math.PI / 2);
    geo.translate(0, 0, -70);   // centre the terrain under the map (which extends toward −Z)
    var pos = geo.attributes.position, v = new T.Vector3(), col = new T.Color();
    var earth = new T.Color(COL.ground), earthLit = new T.Color(COL.groundLit), pathC = new T.Color(COL.groundPath);
    var colors = new Float32Array(pos.count * 3);
    for (var i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      var y = groundY(v.x, v.z);
      pos.setY(i, y);
      // SATURATED TEAL-GREEN EARTH (never grey): a base earth tone, lifted toward warm sage
      // on the sunlit crests (higher y) and toward a mossy path-green along the centre spine.
      col.copy(earth);
      var crest = Math.max(0, Math.min(1, (y + 2) / 14));          // higher ground catches light
      col.lerp(earthLit, crest * 0.5);
      var nearSpine = Math.exp(-(v.x * v.x) / 5200);
      col.lerp(pathC, nearSpine * 0.5);
      // gentle mottling so the earth isn't a flat fill
      var n2 = Math.sin(v.x * 0.14 + v.z * 0.11) * 0.5 + 0.5;
      col.offsetHSL(0, 0.02, (n2 - 0.5) * 0.05);
      colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b;
    }
    geo.setAttribute("color", new T.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    var mat = new T.MeshStandardMaterial({
      vertexColors: true, roughness: 1.0, metalness: 0.0, flatShading: true,
      emissive: 0x0e2420, emissiveIntensity: 0.22,          // faint teal-green self-lift (not grey)
    });
    var mesh = new T.Mesh(geo, mat);
    mesh.receiveShadow = true;
    return mesh;
  }

  // Sample the terrain height analytically (single source of truth for terrain + props).
  // A gently rolling floor (SHALLOW — this is a map diorama, not a landscape) + a temple
  // hill rising at the far (−Z) end so the temple sits elevated and readable.
  function groundY(x, z) {
    var h = Math.sin(x * 0.045) * 1.1 + Math.cos(z * 0.04 + x * 0.02) * 1.3
          + Math.sin(x * 0.10 + z * 0.03) * 0.6;
    // hill ramps up smoothly toward the back, cresting under the temple
    var hill = Math.max(0, (-z - 90)) * 0.5;
    return h + hill;
  }

  // A curved branch/trunk limb built from a short quadratic curve → thin TubeGeometry,
  // so trunks bend and branches fork organically (the icosphere-on-a-stick look is the
  // biggest "tech-demo" tell; real ancient-forest trees have crooked, tapering limbs).
  function _limb(from, to, ctrl, r0, r1, mat) {
    var curve = new T.QuadraticBezierCurve3(from, ctrl, to);
    // TubeGeometry has a constant radius; taper by scaling radius per-segment isn't
    // supported, so we approximate a taper with a mid radius and rely on the crown to hide it.
    var geo = new T.TubeGeometry(curve, 6, (r0 + r1) / 2, 6, false);
    return new T.Mesh(geo, mat);
  }

  // A soft painterly LEAF CLUSTER: several overlapping low-poly spheres forming one
  // organic blob (not a single sphere), with a lighter inner highlight tuft.
  function _leafCluster(cx, cy, cz, rad, matA, matB, r) {
    var g = new T.Group();
    var puffs = [[0, 0, 0, 1.0], [0.6, 0.1, 0.2, 0.7], [-0.55, 0.15, -0.1, 0.72],
                 [0.1, 0.5, -0.3, 0.66], [-0.2, -0.35, 0.4, 0.6]];
    for (var i = 0; i < puffs.length; i++) {
      var p = puffs[i];
      var m = new T.Mesh(new T.IcosahedronGeometry(rad * p[3] * (0.9 + r() * 0.25), 0),
        i === 0 ? matB : matA);
      m.position.set(cx + p[0] * rad, cy + p[1] * rad, cz + p[2] * rad);
      m.rotation.set(r() * 6.28, r() * 6.28, r() * 6.28);
      g.add(m);
    }
    g.position.set(0, 0, 0);
    return g;
  }

  // A stylised MILESTONE / hero tree. `variant` (seeded per grove) shapes the silhouette:
  //   oak      — broad rounded crown on a stout curved trunk (default hero)
  //   banyan   — wide low crown + several aerial-root pillars (ancient India banyan)
  //   willow   — tall trunk with drooping trailing leaf strands
  //   blossom  — slimmer trunk, airy scattered blossom puffs
  // Status tints the leaves (gold mastered / teal active / green available); locked =
  // bare crooked limbs. Returns a Group with y=0 at the ground; canopy sways in the loop.
  function buildTree(style, scale, seed, variant) {
    var g = new T.Group();
    var r = rng(seed);
    var s = (scale || 1) * (style.lush || 1);
    variant = variant || ["oak", "banyan", "willow", "blossom", "oak"][seed % 5];

    var barkMat = toonMat({ color: style.bare ? COL.trunkDark : COL.trunk });
    var lean = (r() - 0.5) * 0.16;

    // --- trunk: a curved, tapering tube (bends as it rises) ------------------
    var trunkH = (variant === "willow" ? 8 : variant === "banyan" ? 5.2 : 6.4) * s;
    var base = new T.Vector3(0, 0, 0);
    var top = new T.Vector3(Math.sin(lean) * trunkH * 0.35, trunkH, Math.cos(lean) * 0.4);
    var ctrl = new T.Vector3(Math.sin(lean) * trunkH * 0.28, trunkH * 0.5, 0);
    var trunk = _limb(base, top, ctrl, 0.85 * s, 0.42 * s, barkMat);
    g.add(trunk);

    if (style.bare) {
      // LOCKED: a DORMANT tree — crooked limbs with a sparse frost-blue canopy (not naked
      // sticks), so the map reads as a wood of resting groves waiting to bloom, not a
      // graveyard. Dim + cool + low so it clearly still reads as "locked" vs the lit groves.
      var frostA = toonMat({ color: COL.lockedLeaf });
      var frostB = toonMat({ color: COL.locked });
      var canopyL = new T.Group();
      for (var l = 0; l < 5; l++) {
        var ang = l / 5 * 6.28 + r();
        var f = new T.Vector3(top.x, top.y * (0.6 + 0.1 * l), top.z);
        var t2 = new T.Vector3(Math.cos(ang) * 3 * s, top.y + (0.4 + r()) * 2 * s, Math.sin(ang) * 3 * s);
        g.add(_limb(f, t2, f.clone().lerp(t2, 0.5).add(new T.Vector3(0, s, 0)), 0.18 * s, 0.05 * s, barkMat));
        // a small sparse frost tuft at each limb tip
        var tuft = new T.Mesh(new T.IcosahedronGeometry((0.9 + r() * 0.5) * s, 0), r() < 0.5 ? frostA : frostB);
        tuft.position.copy(t2); canopyL.add(tuft);
      }
      // a thin dormant crown
      var crownL = new T.Mesh(new T.IcosahedronGeometry(2.0 * s, 0), frostA);
      crownL.position.set(top.x, top.y + 0.8 * s, top.z); crownL.scale.y = 0.8; canopyL.add(crownL);
      g.add(canopyL);
      g.userData.canopy = canopyL;
      g.userData.mats = [frostA, frostB, barkMat];
      return g;
    }

    // --- crown: a canopy group of soft leaf clusters (sways as one) ----------
    var canopy = new T.Group();
    var leafMat = toonMat({ color: style.leaf, emissive: style.leaf,
      emissiveIntensity: style.emissive * 0.3, wind: 0.4 });
    var leafMat2 = toonMat({ color: style.leaf2, emissive: style.leaf2,
      emissiveIntensity: style.emissive * 0.4, wind: 0.4 });

    if (variant === "banyan") {
      // wide low umbrella crown + aerial-root pillars dropping from it
      var cH = trunkH + 1.4 * s;
      var spread = [[0, 0, 0, 3.4], [3.2, -0.4, 0.5, 2.2], [-3.0, -0.3, -0.6, 2.3],
                    [1.4, 0.6, 2.6, 2.0], [-1.8, 0.5, -2.4, 2.1], [0.4, 1.2, 0.2, 2.2]];
      for (var b0 = 0; b0 < spread.length; b0++) {
        var sp = spread[b0];
        canopy.add(_leafCluster(sp[0] * s, cH + sp[1] * s, sp[2] * s, sp[3] * s, leafMat, leafMat2, r));
      }
      // aerial roots — thin pillars from crown edge to ground
      for (var ar = 0; ar < 4; ar++) {
        var aa = ar / 4 * 6.28 + 0.5;
        var rx = Math.cos(aa) * 3.0 * s, rz = Math.sin(aa) * 3.0 * s;
        g.add(_limb(new T.Vector3(rx, cH - 1 * s, rz), new T.Vector3(rx * 1.1, 0, rz * 1.1),
          new T.Vector3(rx * 1.05, cH * 0.4, rz * 1.05), 0.12 * s, 0.18 * s, barkMat));
      }
      canopy.position.y = 0;
    } else if (variant === "willow") {
      // high crown + drooping trailing strands
      var wH = trunkH + 0.5 * s;
      for (var w0 = 0; w0 < 5; w0++) {
        var wa = w0 / 5 * 6.28;
        canopy.add(_leafCluster(Math.cos(wa) * 1.6 * s, wH + (r() - 0.5) * s, Math.sin(wa) * 1.6 * s,
          1.8 * s, leafMat, leafMat2, r));
      }
      // drooping strands: thin vertical leaf columns
      for (var st0 = 0; st0 < 7; st0++) {
        var sa = st0 / 7 * 6.28 + r();
        var sx = Math.cos(sa) * 3.0 * s, sz = Math.sin(sa) * 3.0 * s;
        for (var d0 = 0; d0 < 3; d0++) {
          var dm = new T.Mesh(new T.IcosahedronGeometry(0.7 * s, 0), leafMat);
          dm.position.set(sx, wH - 1.5 * s - d0 * 1.6 * s, sz);
          canopy.add(dm);
        }
      }
      canopy.position.y = 0;
    } else if (variant === "blossom") {
      var pH = trunkH + 1.2 * s;
      var pp = [[0, 0.4, 0, 2.4], [1.8, 0, 0.6, 1.5], [-1.7, 0.1, -0.5, 1.5],
                [0.6, 1.1, -1.4, 1.3], [-0.8, 0.9, 1.4, 1.3]];
      for (var p0 = 0; p0 < pp.length; p0++) {
        var q = pp[p0];
        canopy.add(_leafCluster(q[0] * s, pH + q[1] * s, q[2] * s, q[3] * s, leafMat, leafMat2, r));
      }
      // scattered blossom flecks (tiny bright puffs)
      var fleck = toonMat({ color: style.leaf2, emissive: style.leaf2, emissiveIntensity: style.emissive * 0.6 });
      for (var fl = 0; fl < 10; fl++) {
        var fm = new T.Mesh(new T.IcosahedronGeometry(0.32 * s, 0), fleck);
        fm.position.set((r() - 0.5) * 6 * s, pH + (r() - 0.2) * 3 * s, (r() - 0.5) * 6 * s);
        canopy.add(fm);
      }
      canopy.position.y = 0;
    } else {
      // oak: a broad rounded multi-cluster crown + a couple of forking branches
      var oH = trunkH + 1.2 * s;
      var oc = [[0, 0.5, 0, 3.0], [2.0, -0.1, 0.4, 2.0], [-2.0, 0.0, -0.5, 2.0],
                [0.6, 1.3, -1.6, 1.7], [-0.9, 1.1, 1.5, 1.7], [0.2, -0.2, 1.9, 1.6]];
      for (var o0 = 0; o0 < oc.length; o0++) {
        var c = oc[o0];
        canopy.add(_leafCluster(c[0] * s, oH + c[1] * s, c[2] * s, c[3] * s, leafMat, leafMat2, r));
      }
      // two forking branches into the crown
      for (var br = 0; br < 2; br++) {
        var bd = br ? 1 : -1;
        g.add(_limb(new T.Vector3(top.x, top.y * 0.7, top.z),
          new T.Vector3(bd * 2.2 * s, oH - 0.5 * s, 0.5 * s),
          new T.Vector3(bd * 1.2 * s, top.y * 0.9, 0), 0.3 * s, 0.12 * s, barkMat));
      }
    }

    g.add(canopy);
    g.userData.canopy = canopy;
    g.userData.mats = [leafMat, leafMat2, barkMat];
    return g;
  }

  // The golden TEMPLE — the composition's ANCHOR. A large ornate temple complex: a tall
  // central shikhara + tapering tiers, flanked by two mid towers + two small corner spires,
  // on a wide tiered platform, with a glowing DOORWAY. Emissive gold, fog-free, so it blazes
  // on the horizon like the reference Sunset-Peak temple.
  function buildTemple() {
    var g = new T.Group();
    var mat = new T.MeshStandardMaterial({
      // A DEEPER base gold (not the near-white goldBright) + lower emissive + lower metalness
      // so the lit shikhara tiers stay a structured GOLD under the moon/warm keys + ACES + bloom
      // instead of the reflective faces washing to pure white. Flat shading bands the tiers.
      color: COL.gold, emissive: COL.goldDeep, emissiveIntensity: 0.45,
      roughness: 0.42, metalness: 0.25, flatShading: true, fog: false,
    });
    // warm amber (not near-white) so the doorway/finials glow keeps colour instead of clipping.
    var brightMat = new T.MeshBasicMaterial({ color: 0xffdf9a, fog: false });   // doorway/finials glow
    // tiered base platform (two steps)
    var p1 = new T.Mesh(new T.BoxGeometry(46, 3, 30), mat); p1.position.y = 1.5; g.add(p1);
    var p2 = new T.Mesh(new T.BoxGeometry(38, 3, 24), mat); p2.position.y = 4.5; g.add(p2);
    // a stepped tower (shikhara) with a finial
    function tower(cx, cz, tiers, top) {
      var y = 6;
      for (var i = 0; i < tiers.length; i++) {
        var w = tiers[i][0], h = tiers[i][1];
        var box = new T.Mesh(new T.BoxGeometry(w, h, w * 0.74), mat);
        box.position.set(cx, y + h / 2, cz); g.add(box);
        y += h * 0.84;
      }
      var spire = new T.Mesh(new T.ConeGeometry(top || 2.4, 11, 6), mat);
      spire.position.set(cx, y + 5, cz); g.add(spire);
      var finial = new T.Mesh(new T.SphereGeometry(top ? top * 0.5 : 1.2, 8, 8), brightMat);
      finial.position.set(cx, y + 11, cz); g.add(finial);
      return y + 11;
    }
    var topY = tower(0, 0, [[19, 8], [15, 7], [11, 7], [8, 7], [5, 6]], 3.0);
    tower(-15, -1, [[10, 6], [7, 5.5], [5, 5]], 2.0);
    tower(15, -1, [[10, 6], [7, 5.5], [5, 5]], 2.0);
    tower(-24, -2, [[6, 5], [4, 4]], 1.4);
    tower(24, -2, [[6, 5], [4, 4]], 1.4);
    // a glowing arched DOORWAY at the base of the central tower (the destination beckons)
    var door = new T.Mesh(new T.PlaneGeometry(6, 9), brightMat);
    door.position.set(0, 10, 11.2); g.add(door);
    // doorway glow kept smaller + fainter so it reads as a lit arch, not a white flare that
    // merges with the shikhara into one clipped core.
    var doorGlow = glowSprite(0xffe6b4, 15, 0.3, true); doorGlow.position.set(0, 10, 12); g.add(doorGlow);
    // a warm beacon light + a layered halo so the temple glows on the horizon (dialed back
    // again so the structured gold tiers survive bloom instead of washing to white).
    var glow = new T.PointLight(0xffd98a, 0.9, 200, 2.0); glow.position.y = topY * 0.5; g.add(glow);
    g.userData.mats = [mat, brightMat]; g.userData.topY = topY;
    return g;
  }

  // Warm GOD-RAYS + halo radiating behind the temple (its glow on the horizon) — fanning
  // additive planes plus a big soft halo, like the luminous glow behind both refs' temples.
  function buildTempleRays(topY) {
    var g = new T.Group();
    var mat = new T.MeshBasicMaterial({ color: 0xffe6a8, transparent: true, opacity: 0.07,
      blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide, fog: false });
    for (var i = -4; i <= 4; i++) {
      var pl = new T.Mesh(new T.PlaneGeometry(7, 150), mat);
      pl.position.set(i * 10, topY + 30, -6); pl.rotation.z = i * 0.06; g.add(pl);
    }
    // a big soft warm halo that spills up into the sky/forest behind the temple. The broad
    // outer halo stays (the horizon glow the refs have); the tight inner core is dimmed so it
    // no longer sums with the shikhara/doorway into a blown-out white centre.
    var halo = glowSprite(0xffdc9a, 210, 0.3, true); halo.position.set(0, topY * 0.6, -4); g.add(halo);
    var halo2 = glowSprite(0xffefc4, 90, 0.24, true); halo2.position.set(0, topY * 0.55, -2); g.add(halo2);
    g.userData = { mat: mat };
    return g;
  }

  // Soft radial glow sprite (moon halo, grove auras, temple bloom) — a canvas
  // gradient on an additive sprite so it reads as luminous haze, not a flat disc.
  function glowSprite(color, size, opacity, noFog) {
    var cv = document.createElement("canvas"); cv.width = cv.height = 128;
    var ctx = cv.getContext("2d");
    var c = new T.Color(color);
    var r = Math.round(c.r * 255), gg = Math.round(c.g * 255), bb = Math.round(c.b * 255);
    var grd = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(" + r + "," + gg + "," + bb + ",1)");
    grd.addColorStop(0.35, "rgba(" + r + "," + gg + "," + bb + ",0.5)");
    grd.addColorStop(1, "rgba(" + r + "," + gg + "," + bb + ",0)");
    ctx.fillStyle = grd; ctx.fillRect(0, 0, 128, 128);
    var tex = new T.CanvasTexture(cv);
    var mat = new T.SpriteMaterial({ map: tex, blending: T.AdditiveBlending, transparent: true,
      depthWrite: false, opacity: opacity == null ? 1 : opacity, fog: !noFog });
    var sp = new T.Sprite(mat);
    sp.scale.set(size, size, 1);
    sp.userData.tex = tex; sp.userData.mat = mat;
    return sp;
  }

  // The glowing PATH as a tube along a smooth curve through the grove positions,
  // from the foreground toward the temple. The TRAVELED portion (up to & incl. the
  // active grove) glows brighter/warmer than the path ahead. Returns a Group.
  function buildPath(points, activeIndex, templeZ, toTemple) {
    var g = new T.Group();
    if (points.length < 2) return g;
    var curvePts = points.map(function (p) { return new T.Vector3(p.x, groundY(p.x, p.z) + 0.35, p.z); });
    // FIXED START: extend in front of the first grove so the trail enters the foreground.
    var first = curvePts[0], second = curvePts[1] || curvePts[0];
    var dir = first.clone().sub(second).setY(0).normalize();
    curvePts.unshift(first.clone().add(dir.multiplyScalar(26)).setY(groundY(first.x + dir.x * 26, first.z + dir.z * 26) + 0.35));
    // FIXED END: run the trail on up the hill to the temple so the destination reads.
    if (toTemple && templeZ != null) {
      var tz = templeZ + 14;
      curvePts.push(new T.Vector3(0, groundY(0, tz) + 0.5, tz));
    }
    var curve = new T.CatmullRomCurve3(curvePts, false, "catmullrom", 0.5);
    // The split point on the curve (in [0,1]) up to which the trail is "traveled":
    // from the (prepended) start through the active grove. The rest glows cool/dim.
    var travT = (activeIndex + 2) / curvePts.length;   // +1 for prepended start, +1 to include active
    travT = Math.max(0.12, Math.min(1, travT));

    // The HERO PATH — a BOLD, wide, bright glowing RIBBON that is the spine of the whole
    // composition (like forest_bg's teal-white trail). A bright core ribbon + a bright inner
    // stripe + a broad soft under-glow, raised just above the ground so it never hides under
    // foliage. Fog-free so it glows all the way to the temple.
    // A broad, FLAT luminous ribbon laid on the earth — reads as the map's spine from the
    // top-down diorama view (like forest_bg's teal-white trail). Flattened tubes (thin in Y,
    // wide in XZ) so it's a glowing PATH on the ground, not a pipe.
    function ribbon(t0, t1, core, coreE, edge, width, op, stripe) {
      var n = Math.max(12, Math.round((t1 - t0) * 200));
      var sub = [];
      for (var i = 0; i <= n; i++) sub.push(curve.getPoint(t0 + (t1 - t0) * i / n));
      var c2 = new T.CatmullRomCurve3(sub);
      // broad soft under-glow bleeding onto the ground either side of the trail
      var gmat = new T.MeshBasicMaterial({ color: edge, transparent: true, opacity: op * 0.14,
        blending: T.AdditiveBlending, depthWrite: false, fog: false });
      var geo0 = new T.TubeGeometry(c2, n, width * 2.4, 12, false); geo0.scale(1, 0.04, 1);
      var m0 = new T.Mesh(geo0, gmat); m0.position.y += 0.12; g.add(m0);
      // main ribbon body — wide + flat so it reads as a trail from above
      var geo = new T.TubeGeometry(c2, n, width, 12, false); geo.scale(1, 0.1, 1);
      var mat = new T.MeshStandardMaterial({ color: core, emissive: core, emissiveIntensity: coreE,
        roughness: 0.4, transparent: true, opacity: op, fog: false });
      var m = new T.Mesh(geo, mat); m.position.y += 0.3; g.add(m);
      // a bright inner stripe (the flowing-energy core) — a slim luminous centre-line.
      var smat = new T.MeshBasicMaterial({ color: stripe || 0xffe6b0, transparent: true, opacity: op * 0.34,
        blending: T.AdditiveBlending, depthWrite: false, fog: false });
      var geoS = new T.TubeGeometry(c2, n, width * 0.3, 8, false); geoS.scale(1, 0.1, 1);
      var mS = new T.Mesh(geoS, smat); mS.position.y += 0.4; g.add(mS);
      g.userData.disposables = (g.userData.disposables || []).concat([geo0, gmat, geo, mat, geoS, smat]);
      return m;
    }
    // traveled (warm gold) → ahead (cool teal toward the temple). Wider than before so the
    // path is the clear spine of the composition. Emissive below full-white so it blooms
    // without clipping to a white river.
    ribbon(0, travT, COL.gold, 0.6, 0xffd98a, 4.6, 0.9, 0xffe0a4);
    if (travT < 1) ribbon(travT, 1, COL.teal, 0.78, COL.tealBright, 4.2, 0.85, 0x9ff2ea);
    g.userData.curve = curve;
    return g;
  }

  // A soft round sprite texture for fireflies so each point is a glowing orb (not a hard
  // square). Built once, shared.
  var _dotTex = null;
  function dotTexture() {
    if (_dotTex) return _dotTex;
    var cv = document.createElement("canvas"); cv.width = cv.height = 64;
    var ctx = cv.getContext("2d");
    var grd = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,1)");
    grd.addColorStop(0.3, "rgba(255,240,200,0.8)");
    grd.addColorStop(1, "rgba(255,240,200,0)");
    ctx.fillStyle = grd; ctx.fillRect(0, 0, 64, 64);
    _dotTex = new T.CanvasTexture(cv);
    return _dotTex;
  }

  // FIREFLY / mote points — a warm glowing cloud drifting over the wood, biased low near
  // the ground and path so they read as fireflies in the undergrowth (bloom lifts them).
  function buildFireflies(count, spread) {
    var geo = new T.BufferGeometry();
    var pos = new Float32Array(count * 3);
    var phase = new Float32Array(count);
    var base = [];
    for (var i = 0; i < count; i++) {
      var x = (Math.random() - 0.5) * spread;
      var z = (Math.random() - 0.5) * spread * 1.1 - 30;
      // most fireflies hover low (0–14 above ground); a few drift higher
      var y = groundY(x, z) + 1.5 + Math.pow(Math.random(), 1.6) * 20;
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
      phase[i] = Math.random() * 6.28;
      base.push({ x: x, y: y, z: z });
    }
    geo.setAttribute("position", new T.BufferAttribute(pos, 3));
    var mat = new T.PointsMaterial({ color: 0xffe9a8, size: 2.2, map: dotTexture(),
      sizeAttenuation: true, transparent: true, opacity: 0.95,
      blending: T.AdditiveBlending, depthWrite: false });
    var pts = new T.Points(geo, mat);
    pts.userData = { base: base, phase: phase, geo: geo, mat: mat };
    return pts;
  }

  // Warm EMBER/gold motes that hug the PATH — sampled along the curve so they rise from the
  // trail like drifting sparks (the warm particle life the refs have right along the path).
  function buildEmbers(curve, count) {
    if (!curve) return null;
    var geo = new T.BufferGeometry();
    var pos = new Float32Array(count * 3), phase = new Float32Array(count), base = [];
    for (var i = 0; i < count; i++) {
      var p = curve.getPoint(Math.random());
      var x = p.x + (Math.random() - 0.5) * 10;
      var z = p.z + (Math.random() - 0.5) * 8;
      var y = groundY(x, z) + 1 + Math.pow(Math.random(), 2) * 14;
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
      phase[i] = Math.random() * 6.28; base.push({ x: x, y: y, z: z });
    }
    geo.setAttribute("position", new T.BufferAttribute(pos, 3));
    var mat = new T.PointsMaterial({ color: 0xffb05a, size: 2.6, map: dotTexture(),
      sizeAttenuation: true, transparent: true, opacity: 0.9,
      blending: T.AdditiveBlending, depthWrite: false });
    var pts = new T.Points(geo, mat);
    pts.userData = { base: base, phase: phase, geo: geo, mat: mat, rise: true };
    return pts;
  }

  // Drifting low MIST layers between depth planes — a few big soft billboards near the
  // ground that slowly slide, separating the foreground / mid / far tree walls.
  function buildMist() {
    var g = new T.Group();
    var layers = [];
    for (var i = 0; i < 5; i++) {
      var z = 40 - i * 34;
      var sp = glowSprite(0x9fb8c8, 120 + i * 16, 0.10);
      sp.position.set((i % 2 ? 1 : -1) * 20, groundY(0, z) + 6, z);
      g.add(sp); layers.push({ sp: sp, baseX: sp.position.x, speed: 0.3 + i * 0.15 });
    }
    g.userData = { layers: layers };
    return g;
  }

  // A simple gliding BIRD (a soft V of two thin boxes) that flies between groves.
  function buildBird() {
    var g = new T.Group();
    var mat = new T.MeshBasicMaterial({ color: 0xcbb98a, transparent: true, opacity: 0.7 });
    var w1 = new T.Mesh(new T.BoxGeometry(2.4, 0.12, 0.5), mat); w1.position.x = -1.1; w1.rotation.z = 0.35;
    var w2 = new T.Mesh(new T.BoxGeometry(2.4, 0.12, 0.5), mat); w2.position.x = 1.1; w2.rotation.z = -0.35;
    g.add(w1); g.add(w2);
    g.userData = { w1: w1, w2: w2, mat: mat };
    return g;
  }

  // A glowing teal POND (alt5) — a luminous pool with a bright rim, a soft haze, and
  // animated concentric RIPPLE rings expanding across the surface. Sunk slightly into the
  // ground so it reads as water, not a floating disc.
  function buildPond(x, z) {
    var g = new T.Group();
    var gy = groundY(x, z) - 0.6;
    var disc = new T.Mesh(new T.CircleGeometry(13, 48),
      new T.MeshStandardMaterial({ color: 0x0c3a44, emissive: COL.teal, emissiveIntensity: 0.5,
        roughness: 0.15, metalness: 0.5, transparent: true, opacity: 0.94 }));
    disc.rotation.x = -Math.PI / 2; disc.position.set(x, gy + 0.2, z); g.add(disc);
    var rim = new T.Mesh(new T.TorusGeometry(13, 0.45, 8, 52),
      new T.MeshBasicMaterial({ color: COL.tealBright, transparent: true, opacity: 0.8,
        blending: T.AdditiveBlending, depthWrite: false }));
    rim.rotation.x = Math.PI / 2; rim.position.set(x, gy + 0.3, z); g.add(rim);
    var haze = glowSprite(COL.teal, 30, 0.35); haze.position.set(x, gy + 4, z); g.add(haze);
    // ripple rings — thin tori that grow + fade, restarting (driven in the loop)
    var ripples = [];
    for (var i = 0; i < 3; i++) {
      var rg = new T.TorusGeometry(1, 0.12, 6, 40);
      var rm = new T.MeshBasicMaterial({ color: COL.tealBright, transparent: true, opacity: 0.5,
        blending: T.AdditiveBlending, depthWrite: false });
      var rip = new T.Mesh(rg, rm); rip.rotation.x = Math.PI / 2; rip.position.set(x, gy + 0.35, z);
      g.add(rip); ripples.push({ mesh: rip, phase: i / 3 });
    }
    g.userData = { ripples: ripples, maxR: 12 };
    return g;
  }

  // A hanging LANTERN — a warm ember orb on a thin thread. `light:true` adds a real warm
  // point-light for local warm/cool contrast (used sparingly — lights are capped).
  function buildLantern(x, y, z, seed, light) {
    var g = new T.Group();
    var body = new T.Mesh(new T.SphereGeometry(0.8, 8, 8),
      new T.MeshBasicMaterial({ color: 0xffd98a }));
    body.position.set(x, y, z); g.add(body);
    // a larger, warmer glow pool so lanterns read as pools of firelight (priority 1)
    var glow = glowSprite(0xffb867, 13, 0.95); glow.position.set(x, y, z); g.add(glow);
    var thread = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 4, 4),
      new T.MeshBasicMaterial({ color: 0x3a2c14 }));
    thread.position.set(x, y + 2.2, z); g.add(thread);
    var pl = null;
    if (light) { pl = new T.PointLight(0xffb15a, 1.4, 52, 2.0); pl.position.set(x, y, z); g.add(pl); }
    g.userData = { glow: glow, light: pl, phase: (seed % 100) / 16 };
    return g;
  }

  // Soft GOD-RAYS fanning down from the moon — a few thin additive cones. Skipped under
  // reduced motion (they only read when they breathe).
  function buildGodrays() {
    var g = new T.Group();
    var mat = new T.MeshBasicMaterial({ color: 0xfff0c0, transparent: true, opacity: 0.05,
      blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide });
    for (var i = 0; i < 4; i++) {
      var cone = new T.Mesh(new T.ConeGeometry(26 + i * 6, 200, 12, 1, true), mat);
      cone.position.set(80 - i * 30, 120, -180);
      cone.rotation.z = 0.15 + i * 0.06; cone.rotation.x = 0.1;
      g.add(cone);
    }
    g.userData = { mat: mat };
    return g;
  }

  // PROSCENIUM — the dark ornate foliage that FRAMES the vista (both refs are shot from
  // under overhanging trees). Massive near trunks arching in from both sides + a canopy of
  // dark leaf-masses overhanging the TOP edge, with hanging lanterns dangling into frame.
  // Near-black silhouette so it reads as a vignette, letting the lit vista glow through.
  // Returns { group, lanterns } so the loop can flicker the framing lanterns too.
  // PROSCENIUM (spec §6): dark near-silhouette foliage clumps + rocks tucked into the FOUR
  // outer corners of the map bounds, framing the composition like the refs' overhanging trees.
  // Bounds-relative so it always sits just outside the grove spread at the corners, for any N.
  // Rendered near-black (unlit-ish, deep indigo) so it reads as a vignette and lets the lit
  // map glow through. `bounds` = {minX,maxX,minZ,maxZ}.
  function buildFraming(bounds) {
    var g = new T.Group();
    var lanterns = [];
    var bark = new T.MeshStandardMaterial({ color: 0x120e1c, roughness: 1, flatShading: true });
    var leaf = new T.MeshStandardMaterial({ color: 0x101a18, roughness: 1, flatShading: true,
      emissive: 0x0e1620, emissiveIntensity: 0.12 });
    var r = rng(777);
    var minX = bounds.minX, maxX = bounds.maxX, minZ = bounds.minZ, maxZ = bounds.maxZ;
    // the NEAR corners (high +Z, toward the camera) get big overhanging clumps; the far
    // corners get lower dark stands so the whole frame is proscenium'd.
    var corners = [
      { x: minX - 8, z: maxZ + 8, big: true, dir: 1 },   // near-left
      { x: maxX + 8, z: maxZ + 8, big: true, dir: -1 },  // near-right
      { x: minX - 6, z: minZ - 6, big: false, dir: 1 },  // far-left
      { x: maxX + 6, z: minZ - 6, big: false, dir: -1 }, // far-right
    ];
    corners.forEach(function (a) {
      var x = a.x, z = a.z, dir = a.dir, gy = groundY(x, z);
      var H = a.big ? 46 : 26;
      // a gnarled trunk sweeping up + INWARD (arching into frame)
      var trunk = _limb(new T.Vector3(x, gy - 6, z),
        new T.Vector3(x + dir * 10, gy + H, z - 6),
        new T.Vector3(x + dir * 3, gy + H * 0.5, z - 3), a.big ? 4.5 : 2.6, 1.6, bark);
      g.add(trunk);
      // a clump of dark crowns climbing the corner + arching inward
      var n = a.big ? 9 : 5;
      for (var b = 0; b < n; b++) {
        var cy = gy + 6 + b * (H / n);
        var cx = x + dir * b * 1.6;
        var cr = (a.big ? 9 : 6) + r() * 5;
        var m = new T.Mesh(new T.IcosahedronGeometry(cr, 0), leaf);
        m.position.set(cx, cy, z - 3 + (r() - 0.5) * 8); g.add(m);
      }
      // a mossy boulder anchoring the corner base
      var rock = new T.Mesh(new T.IcosahedronGeometry(4 + r() * 3, 0), bark);
      rock.position.set(x + dir * 3, gy + 1.5, z + 2); rock.castShadow = true; g.add(rock);
      // a hanging lantern dangling into frame from the near corners
      if (a.big) {
        var lan = buildLantern(x + dir * 12, gy + H * 0.7, z - 6, (r() * 1e5) | 0, false);
        g.add(lan); lanterns.push(lan);
      }
    });
    // NEAR-EDGE foreground band (spec §6): a row of dark ferns + shrubs + rocks along the
    // front (high +Z) edge so the empty bright foreground reads as an overhung near bank,
    // not bare ground. Near-silhouette; bleeds off the bottom of frame.
    var frontZ = maxZ + 6, spanX = maxX - minX;
    var nFront = Math.max(8, Math.round(spanX / 16));
    for (var fi = 0; fi <= nFront; fi++) {
      var fx = minX - 6 + (spanX + 12) * (fi / nFront) + (r() - 0.5) * 8;
      var fz = frontZ + (r() - 0.5) * 10;
      var fgy = groundY(fx, fz);
      // a low dark shrub clump
      for (var cc = 0; cc < 2 + ((r() * 2) | 0); cc++) {
        var sh = new T.Mesh(new T.IcosahedronGeometry(3 + r() * 3, 0), leaf);
        sh.position.set(fx + (r() - 0.5) * 8, fgy + 1.5 + r() * 2, fz + (r() - 0.5) * 6);
        sh.scale.y = 0.75; sh.castShadow = true; g.add(sh);
      }
      // a fern fan
      for (var bl = 0; bl < 4; bl++) {
        var blade = new T.Mesh(new T.ConeGeometry(0.4, 4 + r() * 2, 4), bark);
        blade.position.set(fx + (r() - 0.5) * 6, fgy + 2, fz + (r() - 0.5) * 4);
        blade.rotation.z = (r() - 0.5) * 1.0; g.add(blade);
      }
    }
    g.userData = { bark: bark, leaf: leaf };
    return { group: g, lanterns: lanterns };
  }

  // Low ground FOLIAGE scattered near the path corridor — ferns, shrubs and glowing
  // mushrooms so the earth isn't bare navy (both refs are carpeted). Instanced-ish via a
  // single group of cheap meshes; density scales with reduced-motion.
  function buildGroundFoliage(curve) {
    var g = new T.Group();
    var r = rng(4242);
    // warmer, lighter shrubs so the understory reads as living green, not dark navy
    var shrubMat = toonMat({ color: 0x3a6a44 });
    var shrubMat2 = toonMat({ color: 0x4a7a4e });
    var count = reduced() ? 110 : 220;
    // magical accent colours for glowing flowers/mushrooms (teal, violet, magenta, gold)
    var accents = [0x57d3ce, 0xb07bd6, 0xe86ab0, 0xffcf6a, 0x8fd66a];
    for (var i = 0; i < count; i++) {
      // hug the path curve so the trail is richly planted-in (refs are lush along the trail),
      // with a wider spread into the wood so the whole map floor carpets, not just the corridor.
      var t = r();
      var cp = curve ? curve.getPoint(t) : new T.Vector3((r() - 0.5) * 120, 0, -40 + r() * 120);
      var off = 4 + r() * r() * 70, side = r() < 0.5 ? -1 : 1;
      var x = cp.x + side * off + (r() - 0.5) * 14;
      var z = cp.z + (r() - 0.5) * 34;
      if (Math.abs(x) > 200 || z > 90 || z < -220) continue;
      var gy = groundY(x, z);
      var kind = r();
      if (kind < 0.42) {
        // a shrub: a squashed leaf blob (a little cluster of 1–2)
        for (var sc0 = 0; sc0 < (r() < 0.5 ? 1 : 2); sc0++) {
          var sh = new T.Mesh(new T.IcosahedronGeometry(1.1 + r() * 1.5, 0), r() < 0.5 ? shrubMat : shrubMat2);
          sh.position.set(x + (r() - 0.5) * 2, gy + 0.8, z + (r() - 0.5) * 2); sh.scale.y = 0.7; g.add(sh);
        }
      } else if (kind < 0.66) {
        // a fern: thin cones fanning up
        for (var f = 0; f < 4; f++) {
          var blade = new T.Mesh(new T.ConeGeometry(0.22, 2.6 + r(), 4), shrubMat2);
          blade.position.set(x + (r() - 0.5) * 1.2, gy + 1.3, z + (r() - 0.5) * 1.2);
          blade.rotation.z = (r() - 0.5) * 0.9; g.add(blade);
        }
      } else if (kind < 0.86) {
        // a glowing FLOWER cluster — a few bright emissive petball blooms on short stems
        var fcol = accents[(r() * accents.length) | 0];
        var fmat = new T.MeshBasicMaterial({ color: fcol });
        for (var fl = 0; fl < 3; fl++) {
          var stem2 = new T.Mesh(new T.CylinderGeometry(0.06, 0.08, 1.4, 4), shrubMat2);
          var fx = x + (r() - 0.5) * 2.4, fz = z + (r() - 0.5) * 2.4;
          stem2.position.set(fx, gy + 0.7, fz); g.add(stem2);
          var bloom = new T.Mesh(new T.IcosahedronGeometry(0.3 + r() * 0.2, 0), fmat);
          bloom.position.set(fx, gy + 1.5, fz); g.add(bloom);
        }
        var fg = glowSprite(fcol, 4, 0.5); fg.position.set(x, gy + 1.4, z); g.add(fg);
      } else {
        // a glowing mushroom (accent-lit) — the magical understory
        var mcol = accents[(r() * accents.length) | 0];
        var cap = new T.Mesh(new T.SphereGeometry(0.5 + r() * 0.3, 8, 6, 0, 6.28, 0, 1.7),
          new T.MeshBasicMaterial({ color: mcol }));
        cap.position.set(x, gy + 1.1, z); g.add(cap);
        var stem = new T.Mesh(new T.CylinderGeometry(0.1, 0.14, 1, 5),
          new T.MeshStandardMaterial({ color: 0xe6ddd0 }));
        stem.position.set(x, gy + 0.5, z); g.add(stem);
        var mg = glowSprite(mcol, 4, 0.6); mg.position.set(x, gy + 1.2, z); g.add(mg);
      }
    }
    return g;
  }

  // =========================================================================
  // GROVE ARCHETYPE POOL (Dead Cells / Hades "prefab pool")
  // -------------------------------------------------------------------------
  // Each pillar's grove is a milestone tree PLUS one of these modular decor
  // pieces, chosen deterministically by a seed from the pillar key. Every piece
  // is authored to look good and reads status through the passed-in style, so
  // adding a pillar just stitches another varied-but-tuned grove into the middle.
  // Small, cheap meshes only (a few per grove) — perf stays flat as N grows.
  // =========================================================================
  function _rock(rand, x, z, s, col) {
    var m = new T.Mesh(new T.IcosahedronGeometry(s, 0),
      new T.MeshStandardMaterial({ color: col || 0x2a3350, roughness: 1, flatShading: true }));
    m.position.set(x, s * 0.4, z); m.rotation.set(rand() * 6, rand() * 6, rand() * 6);
    return m;
  }
  function _shroom(rand, x, z, col) {
    var g = new T.Group();
    var cap = new T.Mesh(new T.SphereGeometry(0.7, 8, 6, 0, 6.28, 0, 1.6),
      new T.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.6, flatShading: true }));
    cap.position.y = 1; g.add(cap);
    var stem = new T.Mesh(new T.CylinderGeometry(0.15, 0.2, 1, 5),
      new T.MeshStandardMaterial({ color: 0xdfe6ea })); stem.position.y = 0.5; g.add(stem);
    g.position.set(x, 0, z); return g;
  }
  function _fern(rand, x, z, col) {
    var g = new T.Group();
    for (var i = 0; i < 5; i++) {
      var blade = new T.Mesh(new T.ConeGeometry(0.3, 3, 4),
        new T.MeshStandardMaterial({ color: col, roughness: 0.8, flatShading: true }));
      blade.position.set((rand() - 0.5) * 1.5, 1.5, (rand() - 0.5) * 1.5);
      blade.rotation.z = (rand() - 0.5) * 0.8; g.add(blade);
    }
    g.position.set(x, 0, z); return g;
  }
  // A tiny shrine (a small glowing arch) for the "shrine grove" archetype.
  function _shrine(x, z, col) {
    var g = new T.Group();
    var mat = new T.MeshStandardMaterial({ color: 0x2a2036, emissive: col, emissiveIntensity: 0.4, flatShading: true });
    var l = new T.Mesh(new T.BoxGeometry(0.6, 5, 0.6), mat); l.position.set(-2, 2.5, 0); g.add(l);
    var r = new T.Mesh(new T.BoxGeometry(0.6, 5, 0.6), mat); r.position.set(2, 2.5, 0); g.add(r);
    var top = new T.Mesh(new T.BoxGeometry(5, 0.8, 0.8), mat); top.position.set(0, 5.2, 0); g.add(top);
    var flame = glowSprite(COL.ember, 5, 0.9); flame.position.set(0, 2.5, 0); g.add(flame);
    g.position.set(x, 0, z); g.scale.set(0.7, 0.7, 0.7); return g;
  }
  var GROVE_ARCHES = [
    { name: "clearing", decor: function (p, st, sc, rand, C) {   // open, a ring of glowing shrooms
        var shroomCol = st.bare ? 0x3a4258 : st.glow;
        for (var i = 0; i < 6; i++) { var a = i / 6 * 6.28 + rand();
          p.add(_shroom(rand, Math.cos(a) * 7 * sc, Math.sin(a) * 7 * sc, shroomCol)); }
      } },
    { name: "thicket", decor: function (p, st, sc, rand, C) {    // dense — extra small saplings + ferns
        for (var i = 0; i < 3; i++) {
          var sap = buildTree(st, sc * 0.5, (rand() * 1e6) | 0);
          sap.position.set((rand() - 0.5) * 16, 0, (rand() - 0.5) * 10 + 4); p.add(sap);
        }
        for (var f = 0; f < 4; f++) p.add(_fern(rand, (rand() - 0.5) * 18, (rand() - 0.5) * 12, st.bare ? 0x2b3450 : C.green));
      } },
    { name: "riverside", decor: function (p, st, sc, rand, C) {  // reeds + a couple of wet rocks + shrooms
        for (var i = 0; i < 4; i++) p.add(_rock(rand, (rand() - 0.5) * 16, (rand() - 0.5) * 12, 1 + rand() * 1.6, 0x24304a));
        for (var s = 0; s < 3; s++) p.add(_shroom(rand, (rand() - 0.5) * 14, (rand() - 0.5) * 10, st.bare ? 0x3a4258 : C.teal));
      } },
    { name: "ridge", decor: function (p, st, sc, rand, C) {      // rocky outcrop — a cluster of boulders
        for (var i = 0; i < 5; i++) p.add(_rock(rand, (rand() - 0.5) * 18, (rand() - 0.5) * 12, 1.4 + rand() * 2.4, 0x2a3350));
      } },
    { name: "shrine", decor: function (p, st, sc, rand, C) {     // a small glowing shrine + a few ferns
        p.add(_shrine((rand() - 0.5) * 8, 6, st.bare ? 0x3a4258 : st.glow));
        for (var f = 0; f < 3; f++) p.add(_fern(rand, (rand() - 0.5) * 14, (rand() - 0.5) * 10, st.bare ? 0x2b3450 : C.green));
      } },
    { name: "hollow", decor: function (p, st, sc, rand, C) {     // lantern-lit — glowing shrooms + rocks
        for (var i = 0; i < 4; i++) p.add(_shroom(rand, (rand() - 0.5) * 12, (rand() - 0.5) * 10, st.bare ? 0x3a4258 : C.ember));
        for (var r = 0; r < 2; r++) p.add(_rock(rand, (rand() - 0.5) * 14, (rand() - 0.5) * 10, 1.2 + rand() * 1.4, 0x262f47));
      } },
  ];

  // =========================================================================
  // SCENE ASSEMBLY
  // =========================================================================

  // Lay grove positions out as a MAP (spec §0.5 / §1): a wide, shallow, multi-bend
  // SERPENTINE that spreads groves LATERALLY (not in depth), so ALL N groves read at
  // similar scale with room for a medallion + label, no occlusion — the fit-to-bounds
  // camera then frames the whole spread. Fully data-driven: 3 or 18 pillars both lay out
  // as a walkable journey from the foreground ENTRANCE (fixed start bookend) to the TEMPLE
  // (fixed end bookend) on the far hill. Order comes from data (`order`). Nothing keyed to
  // a pillar — add/remove/reorder pillars → the path re-stitches + re-frames automatically.
  //
  // Geometry: nodes advance MOSTLY along −Z (toward the temple) but with a strong lateral
  // serpentine sway so the trail winds left↔right; the sway amplitude tapers near the temple
  // so the last grove + path funnel onto the temple's centre axis (both refs do this).
  function layoutGroves(groves) {
    var n = groves.length;
    var out = [];
    if (n === 0) return out;
    if (n === 1) { out.push({ x: 0, z: 20, grove: groves[0] }); return out; }
    // Distribute nodes EVENLY across the whole field (spec §1: the map reads across the width).
    // A wide multi-bend serpentine advancing steadily toward the temple, with the lateral sway
    // holding near full amplitude the whole way (only easing slightly at the very end so the
    // final node funnels onto the temple axis). This spreads groves across width AND depth so
    // no medallion/label bunches. Fully data-driven — any N samples the same serpentine.
    var zStart = 58;
    var zSpan = 70 + Math.min(170, n * 10);           // total −Z travel (grows with N)
    var amp = 66;                                     // wide lateral amplitude
    // ~1 full bend per 3.5 groves → ~18 pillars wind through ~5 lobes, spreading laterally.
    var bends = Math.max(1.5, n / 3.5);
    for (var i = 0; i < n; i++) {
      var u = i / (n - 1);                            // 0 (entrance) … 1 (temple)
      var z = zStart - u * zSpan;
      // hold amplitude nearly full until the last ~15%, then ease onto the temple centre axis.
      var taper = u < 0.85 ? 1 : (1 - (u - 0.85) / 0.15);
      var x = Math.sin(u * Math.PI * bends + 0.4) * amp * taper;
      out.push({ x: x, z: z, grove: groves[i], u: u });
    }
    return out;
  }

  // Build the entire static scene from a forest_map payload. `mode` is
  // 'overview' (groves) or 'grove' (concepts sub-forest).
  function buildScene(data, mode) {
    _windUniforms = [];   // fresh wind-uniform collector for this scene's toon materials
    var scene = new T.Scene();
    // fog recedes the far ridge INTO the sky (spec §6). Tinted indigo-violet to match the
    // app night base; lighter/thinner for the map so the whole spread stays legible.
    scene.fog = new T.FogExp2(0x241f3e, reduced() ? 0.0026 : 0.0034);
    scene.background = new T.Color(COL.nightMid);

    // --- sky dome: indigo zenith → warm lilac-gold horizon, with a bright WARM GLOW low
    //     over the temple direction (−Z) so the sky itself blooms behind the temple. ------
    var skyGeo = new T.SphereGeometry(400, 24, 16);
    var skyMat = new T.ShaderMaterial({
      side: T.BackSide, depthWrite: false,
      uniforms: {
        top: { value: new T.Color(COL.nightTop) },
        mid: { value: new T.Color(COL.nightMid) },
        low: { value: new T.Color(COL.nightLow) },
        warm: { value: new T.Color(0xf3c878) },      // temple-glow horizon
      },
      vertexShader: "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader:
        "varying vec3 vP; uniform vec3 top; uniform vec3 mid; uniform vec3 low; uniform vec3 warm;" +
        "void main(){ vec3 n = normalize(vP); float h = n.y*0.5+0.5;" +
        " vec3 c = mix(low, mid, smoothstep(0.0,0.5,h)); c = mix(c, top, smoothstep(0.5,1.0,h));" +
        // warm bloom low on the horizon toward the temple (−Z), fading up and to the sides
        " float toward = smoothstep(0.2, 1.0, -n.z);" +
        " float lowBand = smoothstep(0.55, 0.0, h);" +
        " c = mix(c, warm, toward * lowBand * 0.7);" +
        " gl_FragColor = vec4(c,1.0);}",
    });
    scene.add(new T.Mesh(skyGeo, skyMat));

    // --- STARS: a sprinkle of soft points on a high dome, biased to the upper sky band so
    //     the night world reads (spec §6). Cheap; a few hundred points, one draw call. ------
    var starGeo = new T.BufferGeometry();
    var nStars = reduced() ? 180 : 320;
    var starPos = new Float32Array(nStars * 3);
    for (var si = 0; si < nStars; si++) {
      // random direction on the upper hemisphere, placed on a far dome
      var th = Math.random() * Math.PI * 2, ph = Math.acos(0.15 + Math.random() * 0.8);
      var R = 360;
      starPos[si * 3] = Math.sin(ph) * Math.cos(th) * R;
      starPos[si * 3 + 1] = Math.cos(ph) * R * 0.7 + 40;
      starPos[si * 3 + 2] = Math.sin(ph) * Math.sin(th) * R;
    }
    starGeo.setAttribute("position", new T.BufferAttribute(starPos, 3));
    var starMat = new T.PointsMaterial({ color: 0xdfe6ff, size: 1.6, map: dotTexture(),
      sizeAttenuation: false, transparent: true, opacity: 0.85, depthWrite: false,
      blending: T.AdditiveBlending, fog: false });
    var stars = new T.Points(starGeo, starMat); scene.add(stars);

    // --- lights: warm ambient + a moon key ABOVE-FRONT (lights tree fronts) + a warm rim
    //     from the temple side. The front key is the fix for trees reading as dark cutouts. -
    // SKY FILL (spec §2): a HemisphereLight puts COLOUR in the shadows instead of grey —
    // violet sky term → teal-green ground term, so shaded undersides read blue-violet, never
    // grey/black (the biggest palette difference from the refs).
    scene.add(new T.HemisphereLight(0x6a5a9a, 0x16403a, 0.85));
    // KEY LIGHT (spec §2): warm directional from BEHIND + above the temple → golden rims +
    // dark undersides, the change that makes trees stop looking like blobs. Casts shadows.
    var key = new T.DirectionalLight(0xffd9a0, 2.0);
    key.position.set(40, 130, -120);                            // behind/above the temple (−Z)
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0006;
    var sc = key.shadow.camera;                                 // tight ortho frustum over the map
    sc.near = 20; sc.far = 520; sc.left = -240; sc.right = 240; sc.top = 240; sc.bottom = -240;
    sc.updateProjectionMatrix();
    scene.add(key); scene.add(key.target);
    key.target.position.set(0, 0, -30);
    // FRONT MOON FILL — a gentle cool light from camera side so the backlit camera-facing
    // faces keep readable form (not crushed), but dimmer than the key so backlighting reads.
    var moon = new T.DirectionalLight(0xdfe4ff, 0.55);
    moon.position.set(30, 90, 150); scene.add(moon);
    // SEPARATION RIM (spec §2): dim cool from camera-left so overlapping canopies don't merge.
    var coolRim = new T.DirectionalLight(0x7fd8d0, 0.35);
    coolRim.position.set(-110, 50, 40); scene.add(coolRim);
    // a low WARM wrap fill so shaded undersides keep a touch of warm colour (refs have no
    // pure-black tree faces).
    var wrapFill = new T.DirectionalLight(0xffcaa0, 0.35);
    wrapFill.position.set(0, 14, 90); scene.add(wrapFill);

    // --- moon disc + haze, high in the upper sky band, offset from the temple so both read.
    //     Faces the camera-side so it presents as a full disc in the map framing. ------------
    var moonGroup = new T.Group();
    var moonDisc = new T.Mesh(new T.CircleGeometry(11, 32),
      new T.MeshBasicMaterial({ color: COL.moon, fog: false }));
    // a subtle crescent shadow (a dark disc offset over the bright one)
    var moonShadow = new T.Mesh(new T.CircleGeometry(9.5, 32),
      new T.MeshBasicMaterial({ color: COL.nightMid, fog: false }));
    moonShadow.position.set(4.5, 1.5, 0.1);
    var moonHaze = glowSprite(0xdfe8ff, 74, 0.55, true);
    moonGroup.add(moonHaze); moonGroup.add(moonDisc); moonGroup.add(moonShadow);
    // up-left in the sky band, in front of the far dome so it's clearly in-frame above the wood.
    moonGroup.position.set(-150, 175, -150);
    moonGroup.lookAt(-40, 30, 120);
    scene.add(moonGroup);

    // --- terrain -------------------------------------------------------------
    scene.add(buildTerrain());

    // (standalone moon god-rays were a VISTA device — in the top-down map they streak as odd
    // bright shafts across the ground, so they're omitted here; the temple keeps its own rays.)
    var godrays = null;

    // --- the milestone groves (or concept sub-forest) along the path ---------
    // ARCHITECTURE (Dead Cells / Hades-style procedural stitching):
    //   • FIXED BOOKENDS — the path always begins at a hand-tuned entrance in the
    //     foreground and ends at the golden TEMPLE on the far hill (authored, stable).
    //   • PROCEDURAL MIDDLE — one grove per curriculum PILLAR, each assembled from a
    //     POOL of modular grove archetypes chosen deterministically by a seed derived
    //     from the pillar KEY. Nothing is keyed to a pillar name, so adding/removing/
    //     reordering pillars re-stitches the middle + re-frames the camera, no code change.
    // The drill-in sub-forest reuses the SAME assembly so a grove's concepts look just as
    // lush and framed as the overview (priority 9).
    var laid = layoutGroves(mode === "overview" ? data.groves
      : conceptGroves(data));
    var activeIndex = 0;
    for (var i = 0; i < laid.length; i++) if (laid[i].grove._active) activeIndex = i;

    // FIXED END bookend: the TEMPLE — the composition anchor + final node on the map — on the
    // path's centre axis just beyond the last grove, on the far hill. MAP treatment (spec §7):
    // a legible golden shrine at map scale (not a giant cinematic vista slab). templeZ tracks
    // the last grove so it re-seats automatically as the curriculum grows.
    var lastNode = laid.length ? laid[laid.length - 1] : { x: 0, z: 0 };
    var templeZ = lastNode.z - 40;                    // just past the final grove, on the hill
    var templeTopY = 0;
    if (mode === "overview") {
      var temple = buildTemple();
      var tgy = groundY(0, templeZ);
      var tScale = 0.6;                               // map scale — a jewel shrine, not a vista
      temple.position.set(0, tgy, templeZ);
      temple.scale.set(tScale, tScale, tScale);
      setShadow(temple, true);
      scene.add(temple);
      templeTopY = tgy + temple.userData.topY * tScale;
      var rays = buildTempleRays(temple.userData.topY);   // rays/halo positioned in temple-local Y
      rays.position.set(0, tgy, templeZ); rays.scale.set(tScale, tScale, tScale); scene.add(rays);
    }

    // --- the glowing winding PATH (traveled glow runs start→active) ----------
    var path = buildPath(laid, activeIndex, templeZ, mode === "overview");
    scene.add(path);

    // --- filler wood carpeting the map around the nodes + path (both modes) --
    var bgGroup = buildInstancedForest(laid, path.userData.curve, mode === "overview" ? templeZ : null);
    scene.add(bgGroup.mesh); scene.add(bgGroup.mesh2); scene.add(bgGroup.mesh3);

    // --- low ground FOLIAGE + drifting MIST layers (both modes) --------------
    scene.add(buildGroundFoliage(path.userData.curve));
    var mist = null;
    if (!reduced()) { mist = buildMist(); scene.add(mist); }

    // --- PROSCENIUM framing (dark corner foliage + rocks, bounds-relative) ---
    var fbMinX = -30, fbMaxX = 30, fbMinZ = -20, fbMaxZ = 30;
    for (var fb = 0; fb < laid.length; fb++) {
      fbMinX = Math.min(fbMinX, laid[fb].x); fbMaxX = Math.max(fbMaxX, laid[fb].x);
      fbMinZ = Math.min(fbMinZ, laid[fb].z); fbMaxZ = Math.max(fbMaxZ, laid[fb].z);
    }
    if (mode === "overview" && templeZ != null) fbMinZ = Math.min(fbMinZ, templeZ);
    var framing = buildFraming({ minX: fbMinX, maxX: fbMaxX, minZ: fbMinZ, maxZ: fbMaxZ });
    scene.add(framing.group);

    // --- FIXED START bookend: gate-lanterns flanking the entrance (with light) -
    var lanterns = framing.lanterns.slice();   // framing lanterns flicker too
    var lightBudget = reduced() ? 0 : 6;       // cap real point-lights for perf
    if (laid.length) {
      var e0 = laid[0], egy = groundY(e0.x, e0.z);
      var gl1 = buildLantern(e0.x - 7, egy + 8, e0.z + 9, 11, lightBudget-- > 0);
      var gl2 = buildLantern(e0.x + 7, egy + 8, e0.z + 9, 37, lightBudget-- > 0);
      scene.add(gl1); scene.add(gl2); lanterns.push(gl1, gl2);
    }

    // --- a glowing POND beside the path (procedurally seeded position) --------
    var pond = null;
    if (laid.length >= 2) {
      var seedBase = (data.groves && data.groves[0]) ? data.groves[0].pillar
        : (data.pillar || "pond");
      var pIdx = 1 + (hashStr(seedBase) % Math.max(1, laid.length - 1));
      pIdx = Math.min(pIdx, laid.length - 1);
      var pl = laid[pIdx];
      var side = (hashStr("side" + pIdx) % 2) ? 1 : -1;
      pond = buildPond(pl.x + side * 42, pl.z + 8);
      scene.add(pond);
    }

    var pickables = [];   // { obj, grove, x/y/z, labelY } for raycasting + DOM labels
    var auras = [];       // grove aura sprites to pulse
    var medallions = [];  // { grp, state } billboarded node medallions to face the camera
    var youHere = null;
    var nodeIndex = {};   // pillar → laid-index, for path-graph edge lookup

    // HERO milestone trees are markedly bigger than the neutral filler (spec §3: 2.5–4×) so a
    // grove node reads as a landmark, not another shrub. Scales gently down with N so ~18 still
    // fit, but never so small that heroes blend into filler.
    var baseScale = mode === "overview" ? (laid.length > 12 ? 1.5 : laid.length > 6 ? 1.7 : 2.0) : 1.6;

    for (var j = 0; j < laid.length; j++) {
      var L = laid[j], gd = L.grove;
      nodeIndex[gd.pillar || gd.name] = j;
      // grove SIGNATURE hue from its journey fraction (family band) — see familyHue().
      var seed = hashStr(gd.pillar || gd.name);
      var sig = familyHue(L.u != null ? L.u : j / Math.max(1, laid.length - 1), seed);
      var st = styleFor(gd.status, sig);
      var gy = groundY(L.x, L.z);
      var scale = baseScale * (gd._active ? 1.15 : 1.0);
      var arche = GROVE_ARCHES[seed % GROVE_ARCHES.length];
      // the ACTIVE grove always gets a hero banyan/willow; others vary by seed.
      var variant = gd._active ? (seed % 2 ? "banyan" : "willow")
        : ["oak", "banyan", "blossom", "oak", "willow"][seed % 5];

      var piece = new T.Group();
      piece.position.set(L.x, gy, L.z);
      var tree = buildTree(st, scale, seed, variant);
      setShadow(tree, true);
      piece.add(tree);
      arche.decor(piece, st, scale, rng(seed), COL);
      // carved stone PLINTH the tree grows from (spec §9) + a rangoli ring decal in the earth
      piece.add(buildPlinth(scale, st));
      piece.userData.grove = gd; piece.userData.arche = arche.name;
      scene.add(piece);

      var treeH = 9 * scale + 4;       // approx canopy top for the medallion + label
      pickables.push({ obj: tree, grove: gd, x: L.x, y: gy, z: L.z,
        labelY: gy + treeH + 6, piece: piece, active: !!gd._active });

      // MEDALLION above the canopy — the consistent click target + state indicator (spec §9).
      var med = buildMedallion(st);
      med.position.set(L.x, gy + treeH + 6, L.z);
      med.userData.grove = gd;                 // so a click on the medallion also picks the grove
      scene.add(med);
      medallions.push({ grp: med, state: st.state });
      pickables.push({ obj: med, grove: gd, x: L.x, y: gy, z: L.z, medallion: true });

      // soft aura HALO behind lit trees (subtle — bloom lifts it without washing the tree).
      if (!st.bare) {
        var aura = glowSprite(st.glow, 16 * scale, 0.12);
        aura.position.set(L.x, gy + 9 * scale, L.z - 2);
        scene.add(aura); auras.push({ sp: aura, status: gd.status });
      }
      // hanging LANTERN on each lit grove; a real warm light on the nearest few (budget-capped).
      if (!st.bare) {
        var lan = buildLantern(L.x + 4.5 * scale, gy + 9 * scale, L.z + 3, seed, lightBudget-- > 0);
        scene.add(lan); lanterns.push(lan);
      }
      // "YOU ARE HERE" teal ring encircling the active grove
      if (gd._active) {
        youHere = buildYouHere(st);
        youHere.position.set(L.x, gy + 0.1, L.z);
        scene.add(youHere);
      }
    }

    // --- PATH-AS-GRAPH: draw the prerequisite topology as glowing edges (spec §10 + §11).
    // State-styled: gold=traversed (both mastered), teal=available-next, dim=locked. Data-driven
    // from data.edges (grove→grove DAG in overview; concept→concept DAG in the drill-in) —
    // auto-updates with the curriculum. In the drill-in these are the dependency edges between
    // concept trees (§11: the single highest-value change to the grove view).
    if (data.edges && data.edges.length) {
      var edgeGrp = buildEdges(data.edges, laid, nodeIndex);
      if (edgeGrp) scene.add(edgeGrp);
    }

    // --- fireflies + warm path embers + birds --------------------------------
    var fireflies = null, embers = null, birds = [];
    if (!reduced()) {
      fireflies = buildFireflies(Math.min(240, 120 + laid.length * 12), 230);
      scene.add(fireflies);
      embers = buildEmbers(path.userData.curve, 70);
      if (embers) scene.add(embers);
      var nBirds = Math.min(5, Math.max(3, Math.floor(laid.length / 2)));
      for (var bk = 0; bk < nBirds; bk++) {
        var bird = buildBird();
        bird.userData.t = Math.random(); bird.userData.speed = 0.02 + Math.random() * 0.02;
        bird.userData.curve = path.userData.curve;
        bird.userData.height = 20 + Math.random() * 18;
        scene.add(bird); birds.push(bird);
      }
    }

    return {
      scene: scene, pickables: pickables, auras: auras, youHere: youHere,
      medallions: medallions,
      fireflies: fireflies, embers: embers, birds: birds, path: path, moonHaze: moonHaze,
      lanterns: lanterns, pond: pond, godrays: godrays, mist: mist,
      laid: laid, activeIndex: activeIndex, templeZ: templeZ, templeTopY: templeTopY,
      mode: mode,
      _extraDispose: [skyGeo, skyMat, bgGroup],
    };
  }

  // Concept sub-forest: adapt drill-in `concepts` to the grove shape the layout/
  // tree builders expect (status mapped, first available = the "you are here").
  function conceptGroves(data) {
    var map = { done: "blossoming", avail: "available_active", lock: "locked" };
    var firstAvail = -1;
    var out = (data.concepts || []).map(function (c, i) {
      if (firstAvail < 0 && c.status === "avail") firstAvail = i;
      return {
        pillar: c.name, name: c.name,
        status: c.status === "done" ? "blossoming" : c.status === "avail" ? "unlocked" : "locked",
        done: c.status === "done" ? 1 : 0, total: 1, artifacts: 0,
        _concept: c,
      };
    });
    if (firstAvail >= 0) out[firstAvail]._active = true;
    else if (out.length) out[0]._active = true;   // fall back so a ring always anchors the view
    return out;
  }

  // The teal "YOU ARE HERE" ring (alt5) — an elegant glowing TORUS encircling the active
  // grove, a soft ground-glow disc, and a faint upward light. NO hard cylinder edges: the
  // upward light is a fading additive halo, not a walled beam. Pulsed in the loop.
  function buildYouHere(style) {
    var g = new T.Group();
    // a bright thin ring, hovering just above the ground, tilted flat (reads as a halo on
    // the earth in perspective — like the alt5 teal ring around the central tree)
    var ringGeo = new T.TorusGeometry(9, 0.28, 10, 64);
    var ringMat = new T.MeshBasicMaterial({ color: COL.tealBright, transparent: true, opacity: 0.95,
      blending: T.AdditiveBlending, depthWrite: false });
    var ring = new T.Mesh(ringGeo, ringMat); ring.rotation.x = Math.PI / 2; ring.position.y = 0.6;
    g.add(ring);
    // a second, softer outer ring for depth
    var ring2Geo = new T.TorusGeometry(9.6, 0.6, 10, 64);
    var ring2Mat = new T.MeshBasicMaterial({ color: COL.teal, transparent: true, opacity: 0.35,
      blending: T.AdditiveBlending, depthWrite: false });
    var ring2 = new T.Mesh(ring2Geo, ring2Mat); ring2.rotation.x = Math.PI / 2; ring2.position.y = 0.5;
    g.add(ring2);
    // ground glow disc filling the ring (soft, additive — no edges). Kept small + faint so
    // it reads as a halo on the earth, not a central sunburst in the drill-in view.
    var disc = glowSprite(COL.teal, 20, 0.18); disc.position.y = 1.2;
    disc.material.rotation = 0; g.add(disc);
    // a faint upward glow column made of stacked fading sprites (soft, edgeless)
    var col = new T.Group();
    for (var i = 0; i < 4; i++) {
      var sp = glowSprite(COL.tealBright, 13 - i * 2, 0.10 - i * 0.02);
      sp.position.y = 6 + i * 7; col.add(sp);
    }
    g.add(col);
    g.userData = { ring: ring, ring2: ring2, glow: disc, col: col,
      disposables: [ringGeo, ringMat, ring2Geo, ring2Mat] };
    return g;
  }

  // Instanced BACKGROUND wood — a dense, LUSH woodland that reads as lit foliage, not flat
  // black cutouts. Three instanced layers (trunk + a main crown lobe + a top lobe) give each
  // tree a fuller, rounder, two-tier silhouette; higher-facet icosahedra + toon-ish shading
  // catch the moonlight so they read as volumes. Warmer, lighter, more varied greens/teals
  // so the wood glows instead of going navy-black. A handful of draw calls for the whole wood.
  // Filler wood that CARPETS the map (spec §4) — neutral-dark stands that fill the ground
  // AROUND the grove nodes + path, rising toward the frame edges to frame the composition,
  // thinning near the path/nodes so heroes read. Scatters within the actual map bounds
  // (derived from grove positions), avoiding grove/path/temple footprints. Two instanced
  // lobes per tree (crown + top) + a trunk → volume; casts + receives soft shadows.
  function buildInstancedForest(laid, curve, templeZ) {
    var COUNT = reduced() ? 260 : 460;
    var trunkGeo = new T.CylinderGeometry(0.22, 0.42, 5, 5);
    var trunkMat = new T.MeshStandardMaterial({ color: 0x3a3040, roughness: 1, flatShading: true });
    var crownGeo = new T.IcosahedronGeometry(2.2, 1);
    var crownMat = new T.MeshStandardMaterial({ roughness: 0.8, flatShading: true,
      emissive: 0x11241f, emissiveIntensity: 0.22, vertexColors: true });
    var topGeo = new T.IcosahedronGeometry(1.4, 1);
    var topMat = crownMat.clone();
    var trunks = new T.InstancedMesh(trunkGeo, trunkMat, COUNT);
    var crowns = new T.InstancedMesh(crownGeo, crownMat, COUNT);
    var tops = new T.InstancedMesh(topGeo, topMat, COUNT);
    trunks.castShadow = crowns.castShadow = tops.castShadow = true;
    trunks.receiveShadow = crowns.receiveShadow = tops.receiveShadow = true;
    var m = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), pos = new T.Vector3();
    var r = rng(20240802);
    // FILLER stays NEUTRAL-DARK teal-green (spec §3b) so the coloured hero canopies pop.
    var palette = [0x1b3a34, 0x214238, 0x1e3d3c, 0x263f34, 0x233a3e, 0x2a4038, 0x1d3630];
    var col = new T.Color(), fogC = new T.Color(0x2a2444);

    // map bounds from the groves (+ temple), padded, so filler carpets the whole visible field.
    var minX = -60, maxX = 60, minZ = -60, maxZ = 60;
    for (var g = 0; g < laid.length; g++) {
      minX = Math.min(minX, laid[g].x); maxX = Math.max(maxX, laid[g].x);
      minZ = Math.min(minZ, laid[g].z); maxZ = Math.max(maxZ, laid[g].z);
    }
    if (templeZ != null) minZ = Math.min(minZ, templeZ);
    minX -= 90; maxX += 90; maxZ += 60; minZ -= 60;
    var cx = (minX + maxX) / 2;

    // avoidance test: too close to a grove node, the temple footprint, or the path curve.
    function blocked(x, z) {
      for (var i = 0; i < laid.length; i++) {
        var dx = x - laid[i].x, dz = z - laid[i].z;
        if (dx * dx + dz * dz < 220) return true;          // grove clearing
      }
      if (templeZ != null && Math.abs(x) < 34 && Math.abs(z - templeZ) < 34) return true;
      // path proximity (sample a few points near this z)
      if (curve) {
        var pt = curve.getPoint(Math.max(0, Math.min(1, (maxZ - z) / (maxZ - minZ))));
        if ((x - pt.x) * (x - pt.x) < 120 && Math.abs(z - pt.z) < 16) return true;
      }
      return false;
    }

    var placed = 0, lastX = 0, lastZ = 0;
    for (var i = 0; i < COUNT * 3 && placed < COUNT; i++) {
      var x, z;
      if (r() < 0.5 && placed > 0) {                        // cluster into loose stands
        x = lastX + (r() - 0.5) * 22; z = lastZ + (r() - 0.5) * 22;
      } else {
        x = minX + r() * (maxX - minX); z = minZ + r() * (maxZ - minZ);
      }
      if (x < minX || x > maxX || z < minZ || z > maxZ) continue;
      // rising density toward the LATERAL frame edges (framing), thinning in the middle band
      var edge = Math.min(1, Math.abs(x - cx) / ((maxX - minX) / 2));
      if (r() > 0.25 + edge * 0.75) continue;               // more likely to keep near edges
      if (blocked(x, z)) continue;
      lastX = x; lastZ = z;
      var s = 0.7 + r() * r() * 1.8;
      var gy = groundY(x, z) - 0.15;                        // sink slightly (ground contact)
      q.setFromAxisAngle(new T.Vector3(0, 1, 0), r() * 6.28);
      pos.set(x, gy + 2.8 * s, z); sc.set(s, s * (0.9 + r() * 0.4), s);
      m.compose(pos, q, sc); crowns.setMatrixAt(placed, m);
      pos.set(x + (r() - 0.5) * s, gy + 4.6 * s, z + (r() - 0.5) * s); sc.set(s * 0.85, s, s * 0.85);
      m.compose(pos, q, sc); tops.setMatrixAt(placed, m);
      pos.set(x, gy + 2.2 * s, z); sc.set(s, s, s);
      m.compose(pos, q, sc); trunks.setMatrixAt(placed, m);
      col.setHex(palette[(r() * palette.length) | 0]);
      col.offsetHSL((r() - 0.5) * 0.03, 0, (r() - 0.5) * 0.06);
      // fade the outermost / far trees into fog so edges melt into the sky
      var farK = Math.max(0, Math.min(1, (maxZ - z) / (maxZ - minZ)));   // 0 near … 1 toward temple
      col.lerp(fogC, Math.min(0.5, edge * 0.4 + farK * 0.3));
      crowns.setColorAt(placed, col); tops.setColorAt(placed, col);
      placed++;
    }
    trunks.count = placed; crowns.count = placed; tops.count = placed;
    trunks.instanceMatrix.needsUpdate = true; crowns.instanceMatrix.needsUpdate = true;
    tops.instanceMatrix.needsUpdate = true;
    if (crowns.instanceColor) crowns.instanceColor.needsUpdate = true;
    if (tops.instanceColor) tops.instanceColor.needsUpdate = true;
    return { mesh: trunks, mesh2: crowns, mesh3: tops,
      dispose: function () { trunkGeo.dispose(); trunkMat.dispose(); crownGeo.dispose();
        crownMat.dispose(); topGeo.dispose(); topMat.dispose(); } };
  }

  // =========================================================================
  // RENDERER / CONTROLS / LOOP
  // =========================================================================

  function makeRenderer(canvas) {
    var r = new T.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.setClearColor(COL.nightMid, 1);
    // SHADOWS (spec §2) — soft PCF shadows give trees form + ground contact. Without this
    // nothing else in the spec saves the render.
    r.shadowMap.enabled = true;
    r.shadowMap.type = T.PCFSoftShadowMap;
    // ACES filmic tone mapping. Exposure a touch under 1 (spec §2: 0.85–1.0) keeps the night
    // moody and stops emitters clipping to white.
    r.toneMapping = T.ACESFilmicToneMapping;
    r.toneMappingExposure = 0.92;
    if (T.sRGBEncoding != null) r.outputEncoding = T.sRGBEncoding;
    return r;
  }

  // Warm/cool color GRADE + VIGNETTE in one cheap fullscreen pass: lift indigo into the
  // shadows, push gold/teal into the highlights, and darken the corners so the eye
  // stays on the glowing path/temple. Applied after bloom, before the screen.
  var GradeShader = {
    uniforms: {
      tDiffuse: { value: null },
      uVignette: { value: 1.15 },
      uShadow: { value: new T.Color(0x14183a) },   // only the DEEPEST darks stay indigo
      uMid: { value: new T.Color(0xffd9a0) },       // warm amber wash through the midtones
      uHi: { value: new T.Color(0xfff0d0) },        // warm gold in the brights
    },
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader:
      "varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uVignette;" +
      "uniform vec3 uShadow; uniform vec3 uMid; uniform vec3 uHi;" +
      "void main(){ vec4 c = texture2D(tDiffuse, vUv);" +
      " float l = dot(c.rgb, vec3(0.299,0.587,0.114));" +
      // WARM the whole image: indigo only in the darkest darks, amber through the mids, gold
      // in the highs — so the forest GLOWS warm instead of reading cold navy.
      " float shadowW = smoothstep(0.35, 0.0, l);" +   // only very dark pixels
      " float midW = smoothstep(0.0, 0.5, l) * smoothstep(1.0, 0.5, l);" +
      " vec3 tinted = c.rgb + uShadow*shadowW*0.16 + (uMid-vec3(1.0))*midW*0.26 + (uHi-vec3(1.0))*l*0.18;" +
      // saturation + a touch of warm exposure lift so emerald/teal/gold sing
      " float g = dot(tinted, vec3(0.299,0.587,0.114));" +
      " tinted = mix(vec3(g), tinted, 1.22) * 1.04;" +
      // vignette: darken corners to hold the eye on the glowing path/temple
      " float d = distance(vUv, vec2(0.5)); float vig = smoothstep(0.92, 0.34*uVignette, d);" +
      " tinted *= mix(0.62, 1.0, vig);" +
      " gl_FragColor = vec4(tinted, c.a); }",
  };

  // Build the composer pipeline: scene render → bloom → grade/vignette. Bloom picks out
  // the high-emissive path, lanterns, temple and fireflies as glowing light.
  function makeComposer(renderer, scene, cam, w, h) {
    var composer = new T.EffectComposer(renderer);
    composer.addPass(new T.RenderPass(scene, cam));
    // strength gentle, radius soft, threshold HIGH so bloom HALOS the true emitters
    // (path, lanterns, temple, fireflies, rings) instead of flooding the midtones to white.
    // Lowered strength + raised threshold from the previous pass, which stacked into a
    // central white blob near the camera.
    var bloom = new T.UnrealBloomPass(new T.Vector2(w, h), 0.26, 0.6, 0.85);
    composer.addPass(bloom);
    var grade = new T.ShaderPass(GradeShader);
    grade.renderToScreen = true;
    composer.addPass(grade);
    composer.setSize(w, h);
    composer._bloom = bloom;
    return composer;
  }

  // A near-ORTHOGRAPHIC map diorama camera (spec §1). Orthographic removes perspective
  // distortion at the frame edges and keeps distant groves at readable scale — what makes
  // the scene read as a MAP, not a landscape photo. The frustum height is set by
  // fitOrtho() from the grove bounds so all N nodes fit. A slight perspective is faked by
  // the shallow pitch of the eye, but the projection itself is parallel.
  function makeCamera(w, h) {
    var aspect = w / Math.max(1, h);
    var halfH = 60;                                    // replaced immediately by fitOrtho()
    var cam = new T.OrthographicCamera(-halfH * aspect, halfH * aspect, halfH, -halfH, -400, 900);
    cam.userData.halfH = halfH;
    return cam;
  }

  // Resize an orthographic camera's frustum to a given half-height, honouring aspect.
  function setOrthoHalfH(cam, halfH, aspect) {
    cam.userData.halfH = halfH;
    cam.left = -halfH * aspect; cam.right = halfH * aspect;
    cam.top = halfH; cam.bottom = -halfH;
    cam.updateProjectionMatrix();
  }

  function makeControls(cam, dom) {
    var c = new T.OrbitControls(cam, dom);
    c.enableDamping = true; c.dampingFactor = 0.09;
    // orthographic zoom is via .zoom (dolly is meaningless); constrain it.
    c.minZoom = 0.55; c.maxZoom = 3.2;
    // CONSTRAIN orbit (spec §1): keep the shallow map pitch; allow only a little yaw + pitch
    // so the user can nudge the diorama but never frame it badly. "Wander mode" is separate.
    var basePolar = MAP_PITCH;                          // shallow map pitch
    c.maxPolarAngle = basePolar + 0.14;
    c.minPolarAngle = basePolar - 0.10;
    c.minAzimuthAngle = -0.35; c.maxAzimuthAngle = 0.35;   // ±~20° yaw
    c.enablePan = false;
    c.rotateSpeed = 0.45; c.zoomSpeed = 0.9;
    c.autoRotate = false;
    return c;
  }
  // The shallow map pitch (polar angle from +Y). ~24° down-look → horizon ~22–28% from top.
  var MAP_PITCH = Math.PI * 0.5 - (25 * Math.PI / 180);

  // FIT-TO-BOUNDS the orthographic map camera (spec §1) so the DEFAULT framing shows ALL
  // groves + the temple, none occluded, with ~12% padding. Fully a function of the live
  // grove bounds → adapts automatically to any N (3 or 18 pillars) and re-frames when the
  // curriculum grows. The eye sits at the shallow MAP_PITCH aimed at the centre of the
  // spread; the frustum half-height is sized to contain the lateral + depth extent + temple.
  function fitOrtho(state, aspect, instant) {
    var cam = state.cam, ctl = state.controls;
    var laid = state.laid || [];
    // bounds over grove nodes (+ their canopy/label headroom) + the entrance + the temple.
    var minX = -22, maxX = 22, minZ = -18, maxZ = 34;
    for (var i = 0; i < laid.length; i++) {
      minX = Math.min(minX, laid[i].x - 14); maxX = Math.max(maxX, laid[i].x + 14);
      minZ = Math.min(minZ, laid[i].z - 10); maxZ = Math.max(maxZ, laid[i].z + 16);
    }
    if (state.templeZ != null) minZ = Math.min(minZ, state.templeZ - 22);
    var cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
    // look at the centre of the spread, lifted so the temple crowns the upper band.
    var look = new T.Vector3(cx, groundY(cx, cz) + 6, cz);
    // eye direction at the shallow map pitch (parallel projection — distance is irrelevant to
    // framing, so just place it well back along the view dir).
    var dir = new T.Vector3(0, Math.cos(MAP_PITCH), Math.sin(MAP_PITCH));
    var eye = look.clone().add(dir.clone().multiplyScalar(300));
    // Fit: project the 8 corners of the bounds box (ground + a canopy-height top) through a
    // trial view matrix at this eye/look, and size halfH so all corners fit with padding.
    // Robust for any pitch/aspect and any N — the map fills the frame, nothing crops.
    var trial = new T.Matrix4();
    var up = new T.Vector3(0, 1, 0);
    trial.lookAt(eye, look, up);
    var inv = new T.Matrix4().copy(trial).invert();     // world→view basis
    // view matrix = inverse of the camera's world transform; build it directly.
    var camM = new T.Matrix4().makeTranslation(eye.x, eye.y, eye.z).multiply(trial);
    var viewM = new T.Matrix4().copy(camM).invert();
    var topY = 22;                                       // grove canopy/medallion headroom
    var vMaxX = 0, vMaxY = 0, p = new T.Vector3();
    var corners = [[minX,0,minZ],[maxX,0,minZ],[minX,0,maxZ],[maxX,0,maxZ],
                   [minX,topY,minZ],[maxX,topY,minZ],[minX,topY,maxZ],[maxX,topY,maxZ]];
    for (var c = 0; c < corners.length; c++) {
      p.set(corners[c][0], corners[c][1] + groundY(corners[c][0], corners[c][2]), corners[c][2]);
      p.applyMatrix4(viewM);
      vMaxX = Math.max(vMaxX, Math.abs(p.x)); vMaxY = Math.max(vMaxY, Math.abs(p.y));
    }
    // add sky HEADROOM above the map (spec §6: a thin sky band with moon/stars) — grow halfH a
    // touch and nudge the look-target UP-world (down-screen) so a slice of night sky shows.
    var halfH = Math.max(vMaxY, vMaxX / Math.max(0.4, aspect)) * 1.12;
    halfH = Math.max(38, halfH);
    // shift the framing so the map centre sits a little below frame-centre, revealing sky above.
    look.z += halfH * 0.18 * Math.sin(MAP_PITCH);   // push look toward the camera → map drops
    eye = look.clone().add(dir.clone().multiplyScalar(300));
    state._fitHalfH = halfH; state._fitAspect = aspect;
    if (instant || reduced() || !cam.position.lengthSq()) {
      cam.position.copy(eye); ctl.target.copy(look);
      setOrthoHalfH(cam, halfH, aspect); cam.zoom = 1; cam.updateProjectionMatrix(); ctl.update();
    } else {
      setOrthoHalfH(cam, halfH, aspect);
      state._tween = { fromE: cam.position.clone(), toE: eye,
        fromT: ctl.target.clone(), toT: look, t: 0, dur: 1.1 };
    }
  }

  // =========================================================================
  // PUBLIC API
  // =========================================================================
  var API = {
    mounted: false, visible: false, canvas: null, frame: null,
    raf: 0, clock: null, state: null, data: null, mode: "overview",
    curPillar: null, lastT: 0,

    // Attach to the canvas + frame; detect WebGL; no scene yet.
    mount: function (canvas, frame) {
      this.canvas = canvas; this.frame = frame; this.mounted = true;
      if (!webglOK()) { this._fallback("This device can't show the 3D forest (WebGL unavailable)."); return false; }
      try {
        this.renderer = makeRenderer(canvas);
      } catch (e) { this._fallback("The 3D forest couldn't start on this device."); return false; }
      this.clock = new T.Clock();
      var self = this;
      this._onResize = function () { self._resize(); };
      window.addEventListener("resize", this._onResize);
      return true;
    },

    ok: function () { return !!this.renderer; },

    _fallback: function (msg) {
      if (this.frame) {
        var d = document.createElement("div");
        d.className = "forest3d-fallback";
        d.textContent = msg + " Your groves and progress are still tracked — use the list on the Ashram.";
        this.frame.appendChild(d);
      }
      if (this.canvas) this.canvas.style.display = "none";
      this.failed = true;
    },

    // Build (or rebuild) the OVERVIEW scene from a forest_map payload.
    renderOverview: function (data) {
      if (!this.ok()) return;
      this.data = data; this.mode = "overview"; this.curPillar = null;
      this._install(buildScene(data, "overview"));
      // FIT the whole map (all groves + temple) into the default framing (spec §1).
      var w = this.canvas.clientWidth || 800, h = this.canvas.clientHeight || 600;
      fitOrtho(this.state, w / Math.max(1, h), true);
    },

    // Build the drill-in CONCEPT sub-forest for a pillar (same lush assembly as overview).
    // No temple here — frame from a bit further back + higher so the concept trees fill the
    // frame (not a washed-out close-up of the active concept's glow), aiming into the wood
    // so the upper frame holds trees rather than empty sky.
    renderGrove: function (data, pillar) {
      if (!this.ok()) return;
      this.data = data; this.mode = "grove"; this.curPillar = pillar;
      this._install(buildScene(data, "grove"));
      // fit the concept sub-forest into frame (no temple in the drill-in).
      this.state.templeZ = null;
      var w = this.canvas.clientWidth || 800, h = this.canvas.clientHeight || 600;
      fitOrtho(this.state, w / Math.max(1, h), true);
    },

    _install: function (state) {
      this._disposeScene();
      var w = this.canvas.clientWidth || 800, h = this.canvas.clientHeight || 600;
      state.cam = makeCamera(w, h);
      state.controls = makeControls(state.cam, this.canvas);
      // post-processing composer (bloom + grade) — fall back to plain render if it fails.
      try { state.composer = makeComposer(this.renderer, state.scene, state.cam, w, h); }
      catch (e) { state.composer = null; }
      this.state = state;
      this._buildLabels();
      this._buildHud();
      this._resize();
      this._wirePick();
      this._syncLabels();
      if (this.visible) this._start();
    },

    // Create a DOM overlay layer + one permanent LABEL per grove (spec §9). Labels are
    // billboarded via camera projection each frame (_syncLabels), so they always face the
    // viewer and sit above their node — DOM text, not scene textures (crisper, restyleable).
    _buildLabels: function () {
      var frame = this.frame; if (!frame) return;
      if (!this._labelLayer) {
        var layer = document.createElement("div");
        layer.className = "forest-labels";
        layer.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:4;overflow:hidden";
        frame.appendChild(layer); this._labelLayer = layer;
      }
      // rebuild label elements for the current scene's groves
      this._labelLayer.innerHTML = "";
      this._labels = [];
      var laid = this.state.laid || [];
      for (var i = 0; i < laid.length; i++) {
        var gd = laid[i].grove;
        var el = document.createElement("div");
        el.className = "forest-label" + (gd._active ? " here" : "") + " st-" + (gd.status || "");
        var name = gd.pillar || gd.name || "";
        el.innerHTML = (gd._active ? '<span class="fl-here">YOU ARE HERE</span>' : '')
          + '<span class="fl-name">' + _escHtml(name) + '</span>';
        this._labelLayer.appendChild(el);
        this._labels.push({ el: el, idx: i, active: !!gd._active, w: 0, h: 0 });
      }
    },

    // Project each grove's label anchor to screen and place/fade the DOM labels. Collision/
    // fade strategy for MANY nodes (spec §9 + scale update): always show the active grove +
    // its path neighbours + any hovered/selected node at full opacity; for the rest, hide on
    // heavy overlap (labels live in the dark bands between canopies). The minimap carries the
    // full set, so hiding some overview labels never loses information.
    _syncLabels: function () {
      var st = this.state; if (!st || !this._labels) return;
      var cam = st.cam, cv = this.canvas;
      var W = cv.clientWidth || 1, H = cv.clientHeight || 1;
      var pick = st.pickables, laid = st.laid;
      // map laid-index → its label anchor (grove tree pickable carries labelY)
      var anchors = {};
      for (var p = 0; p < pick.length; p++) if (pick[p].labelY != null) {
        // find its laid index by matching grove
        for (var q = 0; q < laid.length; q++) if (laid[q].grove === pick[p].grove) { anchors[q] = pick[p]; break; }
      }
      var v = new T.Vector3();
      var ai = st.activeIndex;
      var hov = this._hoverIdx != null ? this._hoverIdx : -1;
      // Priority (spec §9 + scale update): active is always shown, then hovered/selected, then
      // path neighbours of the active grove, then mastered landmarks, then the rest. Compute
      // all projected rects, then greedily accept HIGH→LOW priority, hiding overlaps — so the
      // shown labels never collide and the important ones always win. The minimap carries the
      // full set, so hiding some is lossless.
      var cand = [];
      for (var i = 0; i < this._labels.length; i++) {
        var L = this._labels[i], a = anchors[L.idx];
        if (!a) { L.el.style.opacity = "0"; continue; }
        v.set(a.x, a.labelY, a.z).project(cam);
        if (v.z > 1) { L.el.style.opacity = "0"; continue; }
        var sx = (v.x * 0.5 + 0.5) * W, sy = (-v.y * 0.5 + 0.5) * H;
        if (sx < -60 || sx > W + 60 || sy < -30 || sy > H + 40) { L.el.style.opacity = "0"; continue; }
        if (!L.w) { L.w = L.el.offsetWidth || 80; L.h = L.el.offsetHeight || 18; }
        var st2 = laid[L.idx].grove.status;
        var prio = L.active ? 100
          : (L.idx === hov || L.idx === this._selIdx) ? 92
          : (Math.abs(L.idx - ai) === 1) ? 84
          : (st2 === "blossoming") ? 66
          : (st2 === "unlocked") ? 52 : 40;
        cand.push({ L: L, x: sx, y: sy - L.h * 0.5, w: L.w, h: L.h, prio: prio });
      }
      cand.sort(function (p, q) { return q.prio - p.prio; });
      var placed = [];
      for (var c2 = 0; c2 < cand.length; c2++) {
        var C = cand[c2], show = true;
        if (C.prio < 100) {
          for (var k = 0; k < placed.length; k++) {
            var o = placed[k];
            if (Math.abs(C.x - o.x) < (C.w + o.w) * 0.5 + 4 && Math.abs(C.y - o.y) < (C.h + o.h) * 0.5 + 3) {
              show = false; break;
            }
          }
        }
        if (show) {
          C.L.el.style.transform = "translate(-50%,-100%) translate(" + C.x.toFixed(1) + "px," + C.y.toFixed(1) + "px)";
          C.L.el.style.opacity = C.prio >= 84 ? "1" : "0.88";
          placed.push(C);
        } else {
          C.L.el.style.opacity = "0";
        }
      }
      this._syncHud();
    },

    // Build the diegetic HUD (spec §13): compass rose + minimap + legend, styled in the app's
    // gold-on-dark ornament language (the DOM/CSS lives in the mapframe; here we just draw the
    // minimap dots each frame). We create a <canvas> minimap once.
    _buildHud: function () {
      if (this._miniCanvas) return;
      var mini = document.getElementById("forest-mini");
      if (mini) { this._miniCanvas = mini; }
    },
    _syncHud: function () {
      var mini = this._miniCanvas, st = this.state; if (!mini || !st) return;
      var laid = st.laid || [];
      var ctx = mini.getContext("2d");
      var W = mini.width, H = mini.height;
      ctx.clearRect(0, 0, W, H);
      if (!laid.length) return;
      // bounds
      var minX = 1e9, maxX = -1e9, minZ = 1e9, maxZ = -1e9;
      for (var i = 0; i < laid.length; i++) {
        minX = Math.min(minX, laid[i].x); maxX = Math.max(maxX, laid[i].x);
        minZ = Math.min(minZ, laid[i].z); maxZ = Math.max(maxZ, laid[i].z);
      }
      if (st.templeZ != null) minZ = Math.min(minZ, st.templeZ);
      var pad = 12;
      var sx = (maxX > minX) ? (W - pad * 2) / (maxX - minX) : 1;
      var sz = (maxZ > minZ) ? (H - pad * 2) / (maxZ - minZ) : 1;
      var s = Math.min(sx, sz);
      function px(x, z) { return [pad + (x - minX) * s + (W - pad * 2 - (maxX - minX) * s) / 2,
                                   pad + (maxZ - z) * s]; }
      // path polyline
      ctx.strokeStyle = "rgba(231,182,75,0.5)"; ctx.lineWidth = 1.4; ctx.beginPath();
      for (var j = 0; j < laid.length; j++) { var pt = px(laid[j].x, laid[j].z); j ? ctx.lineTo(pt[0], pt[1]) : ctx.moveTo(pt[0], pt[1]); }
      ctx.stroke();
      // temple marker
      if (st.templeZ != null) { var tp = px(0, st.templeZ);
        ctx.fillStyle = "#f7d98a"; ctx.beginPath(); ctx.moveTo(tp[0], tp[1] - 4); ctx.lineTo(tp[0] + 3, tp[1] + 2); ctx.lineTo(tp[0] - 3, tp[1] + 2); ctx.closePath(); ctx.fill(); }
      // grove dots, coloured by state
      for (var k = 0; k < laid.length; k++) {
        var g = laid[k].grove, pp = px(laid[k].x, laid[k].z);
        var col = g._active ? "#57d3ce" : g.status === "blossoming" ? "#e7b64b"
          : g.status === "locked" ? "#6a7590" : "#84c778";
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(pp[0], pp[1], g._active ? 3.4 : 2.4, 0, 6.283); ctx.fill();
        if (g._active) { ctx.strokeStyle = "rgba(87,211,206,0.7)"; ctx.lineWidth = 1.4;
          ctx.beginPath(); ctx.arc(pp[0], pp[1], 5.5, 0, 6.283); ctx.stroke(); }
      }
    },

    // Orthographic zoom is via cam.zoom; these expose the HUD zoom buttons.
    zoom: function (mult) {
      if (!this.state) return;
      var c = this.state.controls, cam = this.state.cam;
      cam.zoom = Math.max(c.minZoom, Math.min(c.maxZoom, cam.zoom * mult));
      cam.updateProjectionMatrix(); c.update();
    },
    zoomReset: function () {
      if (!this.state) return;
      var w = this.canvas.clientWidth || 800, h = this.canvas.clientHeight || 600;
      fitOrtho(this.state, w / Math.max(1, h), false);
    },

    setVisible: function (on) {
      this.visible = !!on;
      if (on) { if (this.state && this.ok()) { this._resize(); this._start(); } }
      else this._stop();
    },

    _start: function () {
      if (this.raf || !this.state) return;
      var self = this;
      if (this.clock) this.clock.start();
      var loop = function () { self.raf = requestAnimationFrame(loop); self._tick(); };
      this.raf = requestAnimationFrame(loop);
    },
    _stop: function () { if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; } },

    _resize: function () {
      if (!this.renderer || !this.state) return;
      var w = this.canvas.clientWidth || (this.frame ? this.frame.clientWidth : 800);
      var h = this.canvas.clientHeight || (this.frame ? this.frame.clientHeight : 600);
      this.renderer.setSize(w, h, false);
      var aspect = w / Math.max(1, h), cam = this.state.cam;
      // orthographic: re-fit the frustum to the new aspect so nothing crops on resize.
      if (cam.isOrthographicCamera) {
        setOrthoHalfH(cam, this.state._fitHalfH || cam.userData.halfH || 60, aspect);
      } else { cam.aspect = aspect; cam.updateProjectionMatrix(); }
      if (this.state.composer) this.state.composer.setSize(w, h);
      if (this._syncLabels) this._syncLabels();
    },

    _tick: function () {
      var st = this.state; if (!st || !this.renderer) return;
      var dt = this.clock ? this.clock.getDelta() : 0.016;
      var t = (this.lastT += dt);
      var calm = reduced();

      // camera tween (fly-to)
      if (st._tween) {
        var tw = st._tween; tw.t += dt / tw.dur;
        var k = Math.min(1, tw.t); var e = 1 - Math.pow(1 - k, 3);
        st.cam.position.lerpVectors(tw.fromE, tw.toE, e);
        st.controls.target.lerpVectors(tw.fromT, tw.toT, e);
        if (k >= 1) st._tween = null;
      }

      // medallions + you-are-here always billboard to face the camera (readable at any yaw).
      var camQ = st.cam.quaternion;
      if (st.medallions) for (var md = 0; md < st.medallions.length; md++) st.medallions[md].grp.quaternion.copy(camQ);

      if (!calm) {
        // the map camera stays put (no idle orbit — it would fight fit-to-bounds + labels);
        // life comes from wind, particles, lantern flicker and medallion pulse instead.
        st.controls.autoRotate = false;
        // drive the shared WIND uniform on every toon material (height-masked sway in-shader)
        for (var wu = 0; wu < _windUniforms.length; wu++) _windUniforms[wu].value = t;
        // medallion beacon pulse — active pulses brightest so the eye finds "you are here".
        for (var mp = 0; mp < (st.medallions ? st.medallions.length : 0); mp++) {
          var M = st.medallions[mp]; if (!M.grp.userData.halo) continue;
          var pb = M.state === "active" ? 0.5 : M.state === "blossoming" ? 0.34 : 0.28;
          M.grp.userData.halo.material.opacity = pb + Math.sin(t * (M.state === "active" ? 2.4 : 1.4) + mp) * 0.12;
        }
        // extra whole-canopy sway on the hero milestone trees for readable life up close
        for (var i = 0; i < st.pickables.length; i++) {
          var tr = st.pickables[i].obj, cp = tr.userData.canopy;
          if (cp) cp.rotation.z = Math.sin(t * 0.8 + i) * 0.03;
        }
        // aura pulse (soft halo behind lit groves) — scaled by nearK so foreground auras stay
        // faint and never pulse back up into the central white blob.
        for (var a = 0; a < st.auras.length; a++) {
          var au = st.auras[a];
          var base = au.status === "active" ? 0.17 : au.status === "blossoming" ? 0.15 : 0.11;
          au.sp.material.opacity = (base + Math.sin(t * 1.6 + a) * 0.05) * (au.nearK != null ? au.nearK : 1);
        }
        // you-are-here ring pulse (breathes) + soft glow shimmer
        if (st.youHere) {
          var yh = st.youHere.userData;
          var s = 1 + Math.sin(t * 1.6) * 0.05;
          yh.ring.scale.set(s, s, s);
          if (yh.ring2) yh.ring2.material.opacity = 0.28 + Math.sin(t * 1.6) * 0.1;
          if (yh.glow) yh.glow.material.opacity = 0.15 + Math.sin(t * 1.6) * 0.05;
        }
        // hanging lanterns bob-flicker (glow + real light intensity)
        for (var ln = 0; ln < st.lanterns.length; ln++) {
          var lu = st.lanterns[ln].userData;
          if (lu && lu.glow) {
            var fk = 0.8 + Math.sin(t * 3 + lu.phase) * 0.18 + Math.sin(t * 7.3 + lu.phase) * 0.06;
            lu.glow.material.opacity = 0.7 * fk + 0.15;
            if (lu.light) lu.light.intensity = 1.0 * fk;
          }
        }
        // god-ray + temple-ray breath
        if (st.godrays) st.godrays.userData.mat.opacity = 0.04 + Math.sin(t * 0.6) * 0.03;
        // pond ripples expand + fade
        if (st.pond && st.pond.userData.ripples) {
          var rr = st.pond.userData.ripples, mx = st.pond.userData.maxR;
          for (var pr = 0; pr < rr.length; pr++) {
            var ph2 = (t * 0.25 + rr[pr].phase) % 1;
            var rad = 0.5 + ph2 * mx;
            rr[pr].mesh.scale.set(rad, rad, 1);
            rr[pr].mesh.material.opacity = 0.5 * (1 - ph2);
          }
        }
        // mist layers drift sideways
        if (st.mist) {
          var ml = st.mist.userData.layers;
          for (var mi = 0; mi < ml.length; mi++)
            ml[mi].sp.position.x = ml[mi].baseX + Math.sin(t * 0.1 * ml[mi].speed) * 30;
        }
        // fireflies drift
        if (st.fireflies) {
          var ff = st.fireflies.userData, arr = ff.geo.attributes.position.array;
          for (var f = 0; f < ff.base.length; f++) {
            var b = ff.base[f], ph = ff.phase[f];
            arr[f * 3] = b.x + Math.sin(t * 0.5 + ph) * 3;
            arr[f * 3 + 1] = b.y + Math.sin(t * 0.7 + ph * 1.3) * 2;
            arr[f * 3 + 2] = b.z + Math.cos(t * 0.4 + ph) * 3;
          }
          ff.geo.attributes.position.needsUpdate = true;
          ff.mat.opacity = 0.7 + Math.sin(t * 2) * 0.25;
        }
        // warm path embers rise slowly + drift, looping back down (sparks off the trail)
        if (st.embers) {
          var em = st.embers.userData, ea = em.geo.attributes.position.array;
          for (var e2 = 0; e2 < em.base.length; e2++) {
            var eb = em.base[e2], eph = em.phase[e2];
            var rise = ((t * 2 + eph * 3) % 16);
            ea[e2 * 3] = eb.x + Math.sin(t * 0.6 + eph) * 2;
            ea[e2 * 3 + 1] = eb.y + rise;
            ea[e2 * 3 + 2] = eb.z + Math.cos(t * 0.5 + eph) * 2;
          }
          em.geo.attributes.position.needsUpdate = true;
          em.mat.opacity = 0.75 + Math.sin(t * 3) * 0.2;
        }
        // birds glide along the path curve, wings flapping
        for (var bd = 0; bd < st.birds.length; bd++) {
          var bird = st.birds[bd], u = bird.userData;
          u.t = (u.t + u.speed * dt * 6) % 1;
          if (u.curve) {
            var p = u.curve.getPoint(u.t);
            bird.position.set(p.x, groundY(p.x, p.z) + u.height, p.z);
            var p2 = u.curve.getPoint((u.t + 0.01) % 1);
            bird.lookAt(p2.x, groundY(p2.x, p2.z) + u.height, p2.z);
          }
          var flap = Math.sin(t * 8 + bd) * 0.4;
          u.w1.rotation.z = 0.35 + flap; u.w2.rotation.z = -0.35 - flap;
        }
        // moon haze shimmer
        if (st.moonHaze) st.moonHaze.material.opacity = 0.6 + Math.sin(t * 0.8) * 0.12;
        // scrolling energy along the glowing PATH — light seeping toward the temple
        for (var pt = 0; pt < st.path.children.length; pt++) {
          var pm = st.path.children[pt].material;
          if (pm && pm.emissiveIntensity != null && pm._baseEmis == null) pm._baseEmis = pm.emissiveIntensity;
          if (pm && pm._baseEmis != null) pm.emissiveIntensity = pm._baseEmis * (0.82 + 0.18 * Math.sin(t * 2 - pt));
        }
      } else {
        st.controls.autoRotate = false;   // calm mode: no idle drift
      }

      st.controls.update();
      if (st.composer) st.composer.render(dt);
      else this.renderer.render(st.scene, st.cam);
      // keep DOM labels + minimap pinned to their projected nodes (throttled a touch when calm)
      this._syncLabels();
    },

    // Raycast clicks → the shared popover (grove in overview; concept in drill-in).
    _wirePick: function () {
      var self = this, cv = this.canvas;
      if (cv._pickWired) { cv._forest = this; return; }
      cv._pickWired = true; cv._forest = this;
      var ray = new T.Raycaster(), ndc = new T.Vector2();
      var downPt = null;
      cv.addEventListener("pointerdown", function (e) { downPt = { x: e.clientX, y: e.clientY }; });
      cv.addEventListener("pointerup", function (e) {
        var F = cv._forest; if (!F || !F.state) return;
        if (downPt && (Math.abs(e.clientX - downPt.x) > 6 || Math.abs(e.clientY - downPt.y) > 6)) return; // drag, not click
        var r = cv.getBoundingClientRect();
        ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
        ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
        ray.setFromCamera(ndc, F.state.cam);
        var objs = F.state.pickables.map(function (p) { return p.obj; });
        var hits = ray.intersectObjects(objs, true);
        if (!hits.length) { if (window.hideNodePop) window.hideNodePop(); return; }
        // walk up to the grove group
        var o = hits[0].object; while (o && !o.userData.grove) o = o.parent;
        if (!o || !o.userData.grove) return;
        F._onPick(o.userData.grove, e);
      });
    },

    _onPick: function (grove, evt) {
      if (this.mode === "overview") {
        if (window._openGrovePop) window._openGrovePop(grove, evt);
      } else {
        // drill-in: reuse the concept popover with the SPA's status resolver
        var cc = grove._concept; if (!cc) return;
        var self = this;
        var statusOf = function (n) {
          var all = (self.data.concepts || []).concat(self.data.context || []);
          for (var i = 0; i < all.length; i++) if (all[i].name === n) return all[i].status;
          return "lock";
        };
        if (window._openConceptPop) window._openConceptPop(cc, statusOf, evt);
      }
    },

    _disposeScene: function () {
      if (!this.state) return;
      if (window.hideNodePop) window.hideNodePop();
      if (this._labelLayer) this._labelLayer.innerHTML = "";
      this._labels = null; this._hoverIdx = null; this._selIdx = null;
      var st = this.state;
      if (st.controls) st.controls.dispose();
      if (st.composer) { try { st.composer.renderTarget1.dispose(); st.composer.renderTarget2.dispose();
        if (st.composer._bloom && st.composer._bloom.dispose) st.composer._bloom.dispose(); } catch (e) {} }
      // deep-dispose geometries/materials/textures
      st.scene.traverse(function (o) {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          var mats = Array.isArray(o.material) ? o.material : [o.material];
          mats.forEach(function (m) { if (m.map) m.map.dispose(); if (m.dispose) m.dispose(); });
        }
      });
      (st._extraDispose || []).forEach(function (d) {
        if (d && d.dispose) d.dispose();
        else if (d && d.mesh) { /* instanced group already traversed */ }
      });
      this.state = null;
    },

    dispose: function () {
      this._stop();
      this._disposeScene();
      if (this._onResize) window.removeEventListener("resize", this._onResize);
      if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss && this.renderer.forceContextLoss(); this.renderer = null; }
      this.mounted = false;
    },
  };

  window.Forest3D = API;
})();
