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
  var COL = {
    nightTop: 0x080a18, nightMid: 0x0c1226, nightLow: 0x141024,
    fog: 0x0d1224,
    ground: 0x131a2e, groundLit: 0x1b2540,
    gold: 0xe7b64b, goldBright: 0xf7d98a, goldDeep: 0xb8862f,
    teal: 0x57d3ce, tealBright: 0x8ff0e0,
    green: 0x52a061, greenLit: 0x7fce7f,
    ember: 0xff9b45, moon: 0xfff6df,
    trunk: 0x6e421f, trunkDark: 0x4c2d15,
    locked: 0x3a4258, lockedLeaf: 0x2b3450,
  };
  // status → a small style descriptor the tree/particle builders read.
  function styleFor(status) {
    switch (status) {
      case "blossoming": return { leaf: COL.gold, leaf2: COL.goldBright, glow: COL.gold, bare: false, lush: 1.15, emissive: 0.32 };
      case "active":     return { leaf: COL.teal, leaf2: COL.tealBright, glow: COL.teal, bare: false, lush: 1.05, emissive: 0.3 };
      case "unlocked":   return { leaf: COL.green, leaf2: COL.greenLit, glow: COL.green, bare: false, lush: 0.95, emissive: 0.16 };
      default:           return { leaf: COL.lockedLeaf, leaf2: COL.locked, glow: COL.locked, bare: true, lush: 0.6, emissive: 0.0 };
    }
  }

  // ---- module state --------------------------------------------------------
  var S = null;   // the live scene bundle (null when disposed)

  function reduced() {
    try { return !!(window._reduced && window._reduced()); } catch (e) { return false; }
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
    var W = 260, D = 340, segW = 90, segD = 110;
    var geo = new T.PlaneGeometry(W, D, segW, segD);
    geo.rotateX(-Math.PI / 2);
    var pos = geo.attributes.position, v = new T.Vector3();
    for (var i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      var z = v.z, x = v.x;
      // gentle rolling ground
      var h = Math.sin(x * 0.05) * 1.6 + Math.cos(z * 0.045 + x * 0.02) * 2.0
            + Math.sin(x * 0.11 + z * 0.03) * 0.8;
      // temple hill rises at the far edge (z very negative)
      var hill = Math.max(0, (-z - 90)) * 0.42;
      // keep a gently flat central corridor for the path (shallow — no dark trench)
      var corridor = Math.exp(-(x * x) / 1400) * 1.0;
      pos.setY(i, h + hill - corridor);
    }
    geo.computeVertexNormals();
    // a mossy blue-green ground, warmer near the corridor (vertex colours read as moonlit turf)
    var mat = new T.MeshStandardMaterial({
      color: COL.ground, roughness: 1.0, metalness: 0.0, flatShading: true,
      emissive: 0x0a1428, emissiveIntensity: 0.35,
    });
    var mesh = new T.Mesh(geo, mat);
    mesh.receiveShadow = false;
    return mesh;
  }

  // Sample the terrain height analytically (mirror of the displacement above) so we
  // can plant trees, the path and props ON the ground without raycasting per frame.
  function groundY(x, z) {
    var h = Math.sin(x * 0.05) * 1.6 + Math.cos(z * 0.045 + x * 0.02) * 2.0
          + Math.sin(x * 0.11 + z * 0.03) * 0.8;
    var hill = Math.max(0, (-z - 90)) * 0.42;
    var corridor = Math.exp(-(x * x) / 1400) * 1.0;
    return h + hill - corridor;
  }

  // A stylised MILESTONE tree: a tapered swirled trunk (cone) + a cluster of leaf
  // spheres forming a rounded painterly crown, tinted by status. Bare (locked)
  // trees are just dim limbs. Returns a Group centred at its base (y=0 at ground).
  function buildTree(style, scale, seed) {
    var g = new T.Group();
    var r = rng(seed);
    var s = (scale || 1) * (style.lush || 1);

    // trunk — a slightly tapered, gently leaning cylinder (toon-shaded)
    var trunkH = 6 * s, trunkR = 0.7 * s;
    var tGeo = new T.CylinderGeometry(trunkR * 0.55, trunkR, trunkH, 7);
    var tMat = toonMat({ color: style.bare ? COL.trunkDark : COL.trunk });
    var trunk = new T.Mesh(tGeo, tMat);
    trunk.position.y = trunkH / 2;
    trunk.rotation.z = (r() - 0.5) * 0.12;
    g.add(trunk);

    if (style.bare) {
      // a few dim bare limbs for a locked sapling
      var limbMat = toonMat({ color: COL.trunkDark });
      for (var l = 0; l < 4; l++) {
        var lb = new T.Mesh(new T.CylinderGeometry(0.08 * s, 0.16 * s, 2.4 * s, 5), limbMat);
        lb.position.y = trunkH * (0.7 + 0.08 * l);
        lb.rotation.z = (l % 2 ? 1 : -1) * (0.7 + r() * 0.4);
        lb.rotation.y = r() * 6.28;
        g.add(lb);
      }
      g.userData.canopy = null;
      return g;
    }

    // crown — a cluster of leaf blobs; a shared canopy group so it can sway as one.
    // Toon-shaded with a gradient ramp + height-masked wind (canopy waves, trunk plants).
    var canopy = new T.Group();
    canopy.position.y = trunkH + 1.2 * s;
    // keep emissive LOW so the toon-shaded base colour (gold / teal / green) reads true;
    // the aura sprite + bloom supply the magical glow around the tree, not the leaves.
    var leafMat = toonMat({ color: style.leaf, emissive: style.leaf,
      emissiveIntensity: style.emissive * 0.35, wind: 0.5 });
    var leafMat2 = toonMat({ color: style.leaf2, emissive: style.leaf2,
      emissiveIntensity: style.emissive * 0.45, wind: 0.5 });
    var blobs = [
      [0, 0.6, 0, 2.6], [-1.5, 0.0, 0.3, 1.9], [1.5, 0.1, -0.2, 1.9],
      [-0.6, 1.5, -0.4, 1.6], [0.7, 1.4, 0.5, 1.7], [0.0, -0.5, 0.9, 1.7],
      [0.2, 0.2, -1.1, 1.6],
    ];
    for (var b = 0; b < blobs.length; b++) {
      var bl = blobs[b];
      var rad = bl[3] * s * (0.85 + r() * 0.3);
      var m = new T.Mesh(new T.IcosahedronGeometry(rad, 0), b % 3 === 0 ? leafMat2 : leafMat);
      m.position.set(bl[0] * s, bl[1] * s, bl[2] * s);
      m.rotation.set(r() * 6.28, r() * 6.28, r() * 6.28);
      canopy.add(m);
    }
    g.add(canopy);
    g.userData.canopy = canopy;
    g.userData.mats = [leafMat, leafMat2, tMat];   // for disposal
    return g;
  }

  // A distant golden TEMPLE on the far hill: stacked tapering tiers + a spire, all
  // emissive gold so it glows like the reference art's Sunset-Peak temple.
  function buildTemple() {
    var g = new T.Group();
    var mat = new T.MeshStandardMaterial({
      color: COL.gold, emissive: COL.gold, emissiveIntensity: 1.4,
      roughness: 0.4, metalness: 0.3, flatShading: true,
    });
    var y = 0;
    var tiers = [[14, 6], [11, 5], [8, 5], [5.5, 5], [3.5, 4]];
    for (var i = 0; i < tiers.length; i++) {
      var w = tiers[i][0], h = tiers[i][1];
      var box = new T.Mesh(new T.BoxGeometry(w, h, w * 0.7), mat);
      box.position.y = y + h / 2; g.add(box);
      y += h * 0.82;
    }
    var spire = new T.Mesh(new T.ConeGeometry(2.4, 9, 6), mat);
    spire.position.y = y + 4; g.add(spire);
    // a warm glow the temple casts + a halo sprite
    var glow = new T.PointLight(COL.goldBright, 2.4, 160, 2.0);
    glow.position.y = y * 0.6; g.add(glow);
    g.userData.mats = [mat];
    return g;
  }

  // Soft radial glow sprite (moon halo, grove auras, temple bloom) — a canvas
  // gradient on an additive sprite so it reads as luminous haze, not a flat disc.
  function glowSprite(color, size, opacity) {
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
      depthWrite: false, opacity: opacity == null ? 1 : opacity });
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

    function tube(t0, t1, color, emissive, radius, op) {
      var n = Math.max(4, Math.round((t1 - t0) * 120));
      var sub = [];
      for (var i = 0; i <= n; i++) sub.push(curve.getPoint(t0 + (t1 - t0) * i / n));
      var c2 = new T.CatmullRomCurve3(sub);
      var geo = new T.TubeGeometry(c2, n, radius, 8, false);
      var mat = new T.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: emissive,
        roughness: 0.5, transparent: true, opacity: op });
      var m = new T.Mesh(geo, mat);
      g.add(m); g.userData.disposables = (g.userData.disposables || []).concat([geo, mat]);
      return m;
    }
    // traveled (warm gold, bright, HDR emissive → blooms) → then ahead (cool teal, dim)
    tube(0, travT, COL.gold, 2.2, 0.85, 0.98);
    if (travT < 1) tube(travT, 1, COL.teal, 0.7, 0.6, 0.55);
    g.userData.curve = curve;
    return g;
  }

  // FIREFLY / mote points — a capped cloud of warm points drifting over the wood.
  function buildFireflies(count, spread) {
    var geo = new T.BufferGeometry();
    var pos = new Float32Array(count * 3);
    var phase = new Float32Array(count);
    var base = [];
    for (var i = 0; i < count; i++) {
      var x = (Math.random() - 0.5) * spread;
      var z = (Math.random() - 0.5) * spread * 1.2 - 40;
      var y = groundY(x, z) + 2 + Math.random() * 22;
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
      phase[i] = Math.random() * 6.28;
      base.push({ x: x, y: y, z: z });
    }
    geo.setAttribute("position", new T.BufferAttribute(pos, 3));
    var mat = new T.PointsMaterial({ color: COL.goldBright, size: 1.5, sizeAttenuation: true,
      transparent: true, opacity: 0.9, blending: T.AdditiveBlending, depthWrite: false });
    var pts = new T.Points(geo, mat);
    pts.userData = { base: base, phase: phase, geo: geo, mat: mat };
    return pts;
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

  // A glowing PelagicTeal POND nestled in the wood (alt5 reference) — a flat disc with a
  // luminous rim + a haze sprite. Placed procedurally off the path corridor.
  function buildPond(x, z) {
    var g = new T.Group();
    var gy = groundY(x, z);
    var disc = new T.Mesh(new T.CircleGeometry(11, 40),
      new T.MeshStandardMaterial({ color: 0x0e3b46, emissive: COL.teal, emissiveIntensity: 0.45,
        roughness: 0.2, metalness: 0.4, transparent: true, opacity: 0.92 }));
    disc.rotation.x = -Math.PI / 2; disc.position.set(x, gy + 0.25, z); g.add(disc);
    var rim = new T.Mesh(new T.TorusGeometry(11, 0.5, 8, 44),
      new T.MeshBasicMaterial({ color: COL.tealBright, transparent: true, opacity: 0.7 }));
    rim.rotation.x = Math.PI / 2; rim.position.set(x, gy + 0.3, z); g.add(rim);
    var haze = glowSprite(COL.teal, 26, 0.35); haze.position.set(x, gy + 4, z); g.add(haze);
    return g;
  }

  // A hanging LANTERN — a warm ember point on a thin thread, dangling from the canopy.
  function buildLantern(x, y, z, seed) {
    var g = new T.Group();
    var body = new T.Mesh(new T.SphereGeometry(0.7, 8, 8),
      new T.MeshBasicMaterial({ color: COL.ember }));
    body.position.set(x, y, z); g.add(body);
    var glow = glowSprite(COL.ember, 7, 0.85); glow.position.set(x, y, z); g.add(glow);
    var thread = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 4, 4),
      new T.MeshBasicMaterial({ color: 0x3a2c14 }));
    thread.position.set(x, y + 2.2, z); g.add(thread);
    g.userData = { glow: glow, phase: (seed % 100) / 16 };
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

  // Dark FOREGROUND framing foliage (a vignette of arching branches at the near edges),
  // giving the scene the alt5 "looking out from under the trees" depth. Silhouette only.
  function buildFraming() {
    var g = new T.Group();
    var mat = new T.MeshStandardMaterial({ color: 0x060810, roughness: 1, flatShading: true });
    // two big near trunks arching in from the left & right foreground
    [[-60, 55, 1], [62, 60, -1]].forEach(function (a) {
      var x = a[0], z = a[1], dir = a[2];
      var trunk = new T.Mesh(new T.CylinderGeometry(2.5, 4, 60, 7), mat);
      trunk.position.set(x, groundY(x, z) + 20, z); trunk.rotation.z = dir * 0.2; g.add(trunk);
      for (var b = 0; b < 4; b++) {
        var crown = new T.Mesh(new T.IcosahedronGeometry(9 + Math.random() * 5, 0), mat);
        crown.position.set(x - dir * (4 + b * 3), groundY(x, z) + 40 + b * 5, z + (Math.random() - 0.5) * 8);
        g.add(crown);
      }
    });
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

  // Lay grove positions out along a gently-serpentine path receding toward the
  // temple (−Z). Order comes from data (`order`); we snake x so it curves.
  function layoutGroves(groves) {
    var n = groves.length;
    var out = [];
    // The path spans a fixed depth toward the temple; spacing scales with N so a
    // 3-pillar and a 16-pillar curriculum both read as a walkable journey (spacing
    // clamps so groves never crowd or sprawl). Nothing here is keyed to a pillar.
    var spacing = Math.max(16, Math.min(30, 150 / Math.max(1, n)));
    var zStart = 78, zEnd = zStart - (n - 1) * spacing;
    for (var i = 0; i < n; i++) {
      var z = n > 1 ? zStart - i * spacing : 30;
      // serpentine sway in x, amplitude easing so far groves hug the temple axis
      var ease = 1 - i / Math.max(1, n - 1);
      var x = Math.sin(i * 1.15 + 0.4) * (38 * (0.35 + 0.65 * ease));
      out.push({ x: x, z: z, grove: groves[i] });
    }
    return out;
  }

  // Build the entire static scene from a forest_map payload. `mode` is
  // 'overview' (groves) or 'grove' (concepts sub-forest).
  function buildScene(data, mode) {
    _windUniforms = [];   // fresh wind-uniform collector for this scene's toon materials
    var scene = new T.Scene();
    // fog color matched to the sky horizon so distant trees melt into the night, not
    // pop as flat silhouettes (the brief's depth/atmosphere lever).
    scene.fog = new T.FogExp2(COL.nightMid, reduced() ? 0.006 : 0.0072);
    scene.background = new T.Color(COL.nightMid);

    // --- sky dome: a big inverted sphere with a vertical indigo gradient -----
    var skyGeo = new T.SphereGeometry(400, 24, 16);
    var skyMat = new T.ShaderMaterial({
      side: T.BackSide, depthWrite: false,
      uniforms: {
        top: { value: new T.Color(COL.nightTop) },
        mid: { value: new T.Color(COL.nightMid) },
        low: { value: new T.Color(COL.nightLow) },
      },
      vertexShader: "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader:
        "varying vec3 vP; uniform vec3 top; uniform vec3 mid; uniform vec3 low;" +
        "void main(){ float h = normalize(vP).y*0.5+0.5;" +
        " vec3 c = mix(low, mid, smoothstep(0.0,0.5,h)); c = mix(c, top, smoothstep(0.5,1.0,h));" +
        " gl_FragColor = vec4(c,1.0);}",
    });
    scene.add(new T.Mesh(skyGeo, skyMat));

    // --- lights: cool ambient + a warm moon key + a subtle teal fill ---------
    scene.add(new T.HemisphereLight(0x8ea6d8, 0x0a1020, 0.7));   // cool sky / dark ground
    var moon = new T.DirectionalLight(0xdfe6ff, 0.75);           // pale-cool moonlight
    moon.position.set(80, 120, 60); scene.add(moon);
    var fill = new T.DirectionalLight(COL.teal, 0.14);
    fill.position.set(-60, 40, -80); scene.add(fill);

    // --- moon disc + haze up in the sky (top-right) --------------------------
    var moonGroup = new T.Group();
    var moonDisc = new T.Mesh(new T.CircleGeometry(14, 32),
      new T.MeshBasicMaterial({ color: COL.moon }));
    var moonHaze = glowSprite(COL.goldBright, 90, 0.7);
    moonGroup.add(moonHaze); moonGroup.add(moonDisc);
    moonGroup.position.set(120, 130, -240);
    moonGroup.lookAt(0, 20, 40);
    scene.add(moonGroup);

    // --- terrain -------------------------------------------------------------
    scene.add(buildTerrain());

    // --- god-rays sweeping from the moon (overview only; motion-gated) --------
    var godrays = null;
    if (mode === "overview" && !reduced()) { godrays = buildGodrays(); scene.add(godrays); }

    // --- the milestone groves (or concept sub-forest) along the path ---------
    // ARCHITECTURE (Dead Cells / Hades-style procedural stitching):
    //   • FIXED BOOKENDS — the path always begins at a hand-tuned entrance in the
    //     foreground and ends at the golden TEMPLE on the far hill (authored, stable).
    //   • PROCEDURAL MIDDLE — one grove per curriculum PILLAR, each assembled from a
    //     POOL of modular grove archetypes chosen deterministically by a seed derived
    //     from the pillar KEY (stable across reloads, varied across pillars). Nothing
    //     is keyed to a specific pillar name, so adding/removing/reordering pillars
    //     re-stitches the middle and re-frames the camera with zero code changes.
    var laid = layoutGroves(mode === "overview" ? data.groves
      : conceptGroves(data));
    var activeIndex = 0;
    for (var i = 0; i < laid.length; i++) if (laid[i].grove._active) activeIndex = i;

    // FIXED END bookend: the temple sits just beyond the last grove, on the hill.
    var templeZ = -150;
    if (mode === "overview") {
      var lastZ = laid.length ? laid[laid.length - 1].z : 0;
      templeZ = Math.min(-120, lastZ - 46);
      var temple = buildTemple();
      var tgy = groundY(0, templeZ);
      temple.position.set(0, tgy + 2, templeZ);
      temple.scale.set(1.5, 1.5, 1.5);
      scene.add(temple);
      var bloom = glowSprite(COL.goldBright, 170, 0.5);
      bloom.position.set(0, tgy + 46, templeZ); scene.add(bloom);
    }

    // --- background instanced trees for depth & lushness ---------------------
    var bgGroup = buildInstancedForest();
    scene.add(bgGroup.mesh); scene.add(bgGroup.mesh2);

    // --- dark foreground FRAMING foliage (vignette of arching branches) -------
    if (mode === "overview") scene.add(buildFraming());

    // --- FIXED START bookend: a little entrance marker where the trail begins -
    if (mode === "overview" && laid.length) {
      var e0 = laid[0], egy = groundY(e0.x, e0.z);
      // two warm gate-lanterns flanking the entrance path
      scene.add(buildLantern(e0.x - 6, egy + 7, e0.z + 8, 11));
      scene.add(buildLantern(e0.x + 6, egy + 7, e0.z + 8, 37));
    }

    // the glowing winding PATH between the bookends (traveled glow runs start→active)
    var path = buildPath(laid, activeIndex, templeZ, mode === "overview");
    scene.add(path);

    // --- a glowing POND nestled beside the path (procedurally seeded position) -
    var pond = null;
    if (mode === "overview" && laid.length >= 2) {
      var pIdx = 1 + (hashStr(data.groves[0] ? data.groves[0].pillar : "pond") % Math.max(1, laid.length - 1));
      pIdx = Math.min(pIdx, laid.length - 1);
      var pl = laid[pIdx];
      var side = (hashStr("side" + pIdx) % 2) ? 1 : -1;
      pond = buildPond(pl.x + side * 40, pl.z + 10);
      scene.add(pond);
    }

    var pickables = [];   // { mesh(group), grove, pos } for raycasting
    var auras = [];       // grove aura sprites to pulse
    var youHere = null;

    var lanterns = [];    // hanging lanterns to gently bob/flicker
    for (var j = 0; j < laid.length; j++) {
      var L = laid[j], gd = L.grove;
      var st = styleFor(gd.status);
      var gy = groundY(L.x, L.z);
      var scale = mode === "overview" ? 1.25 : 0.85;
      // seed EVERYTHING about this grove from the pillar KEY → stable across reloads,
      // distinct across pillars (the roguelike "prefab picked by seed" idea).
      var seed = hashStr(gd.pillar || gd.name);
      var arche = GROVE_ARCHES[seed % GROVE_ARCHES.length];

      var piece = new T.Group();
      piece.position.set(L.x, gy, L.z);
      // the milestone TREE (the pickable heart of the piece)
      var tree = buildTree(st, scale, seed);
      piece.add(tree);
      // archetype-specific modular decor, recoloured by status
      arche.decor(piece, st, scale, rng(seed), COL);
      piece.userData.grove = gd; piece.userData.arche = arche.name;
      scene.add(piece);
      pickables.push({ obj: tree, grove: gd, x: L.x, y: gy, z: L.z, piece: piece });

      // aura sprite behind lit trees (mastered / active / available) — a soft halo, kept
      // subtle so bloom lifts it without washing the tree's silhouette away.
      if (!st.bare) {
        var aura = glowSprite(st.glow, 26 * scale, gd.status === "locked" ? 0 : 0.26);
        aura.position.set(L.x, gy + 11 * scale, L.z - 2);
        scene.add(aura); auras.push({ sp: aura, status: gd.status });
      }
      // a hanging LANTERN dangling from the canopy of every lit grove (alt5 look);
      // groves with SAVED ARTIFACTS get an extra scroll-glint lantern (data-driven).
      if (!st.bare) {
        var lan = buildLantern(L.x + 5 * scale, gy + 11 * scale, L.z + 3, seed);
        scene.add(lan); lanterns.push(lan);
      }
      if ((gd.artifacts || 0) > 0) {
        var lan2 = buildLantern(L.x - 5 * scale, gy + 9 * scale, L.z + 1, seed + 7);
        scene.add(lan2); lanterns.push(lan2);
      }
      // "YOU ARE HERE" teal ground ring + beam on the active grove
      if (gd._active) {
        youHere = buildYouHere(st);
        youHere.position.set(L.x, gy + 0.1, L.z);
        scene.add(youHere);
      }
    }

    // --- fireflies + birds ---------------------------------------------------
    var fireflies = null, birds = [];
    if (!reduced()) {
      fireflies = buildFireflies(Math.min(140, 60 + laid.length * 8), 200);
      scene.add(fireflies);
      var nBirds = Math.min(4, Math.max(2, Math.floor(laid.length / 2)));
      for (var bk = 0; bk < nBirds; bk++) {
        var bird = buildBird();
        bird.userData.t = Math.random(); bird.userData.speed = 0.02 + Math.random() * 0.02;
        bird.userData.curve = path.userData.curve;
        bird.userData.height = 18 + Math.random() * 14;
        scene.add(bird); birds.push(bird);
      }
    }

    return {
      scene: scene, pickables: pickables, auras: auras, youHere: youHere,
      fireflies: fireflies, birds: birds, path: path, moonHaze: moonHaze,
      lanterns: lanterns, pond: pond, godrays: godrays,
      laid: laid, activeIndex: activeIndex,
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

  // The teal "YOU ARE HERE" ring: a glowing torus flat on the ground + a floating
  // beacon. Pulsed in the animation loop (static under reduced motion).
  function buildYouHere(style) {
    var g = new T.Group();
    var ringGeo = new T.TorusGeometry(7, 0.35, 8, 48);
    var ringMat = new T.MeshBasicMaterial({ color: COL.teal, transparent: true, opacity: 0.9 });
    var ring = new T.Mesh(ringGeo, ringMat); ring.rotation.x = Math.PI / 2;
    g.add(ring);
    var glow = glowSprite(COL.tealBright, 22, 0.5); glow.position.y = 6; g.add(glow);
    // a soft vertical LIGHT BEAM rising through the ring (the alt5 "you are here" shaft)
    var beamGeo = new T.CylinderGeometry(6.5, 7.2, 34, 20, 1, true);
    var beamMat = new T.MeshBasicMaterial({ color: COL.teal, transparent: true, opacity: 0.11,
      side: T.DoubleSide, blending: T.AdditiveBlending, depthWrite: false });
    var beam = new T.Mesh(beamGeo, beamMat); beam.position.y = 17; g.add(beam);
    // a floating pin beacon
    var pin = new T.Mesh(new T.ConeGeometry(1.2, 3, 6),
      new T.MeshBasicMaterial({ color: COL.tealBright }));
    pin.position.y = 20; pin.rotation.x = Math.PI; g.add(pin);
    g.userData = { ring: ring, ringMat: ringMat, ringGeo: ringGeo, glow: glow, pin: pin,
      beam: beam, disposables: [ringGeo, ringMat, beamGeo, beamMat] };
    return g;
  }

  // Instanced BACKGROUND trees — a lush, cheap woodland filling the scene with
  // depth. Two instanced meshes (trunks + crowns) so the whole wood is a handful
  // of draw calls regardless of tree count.
  function buildInstancedForest() {
    var COUNT = reduced() ? 120 : 220;
    var trunkGeo = new T.CylinderGeometry(0.35, 0.6, 6, 5);
    var trunkMat = new T.MeshStandardMaterial({ color: COL.trunkDark, roughness: 1, flatShading: true });
    var crownGeo = new T.IcosahedronGeometry(2.2, 0);
    var crownMat = new T.MeshStandardMaterial({ roughness: 0.9, flatShading: true,
      emissive: 0x0b1428, emissiveIntensity: 0.25, vertexColors: false });
    var trunks = new T.InstancedMesh(trunkGeo, trunkMat, COUNT);
    var crowns = new T.InstancedMesh(crownGeo, crownMat, COUNT);
    var m = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), pos = new T.Vector3();
    var r = rng(20240802);
    // a small painterly palette for the background canopy (deep blues → forest teals,
    // an occasional warm glint) so the wood reads lush, not a field of identical cones.
    var palette = [0x1b2c46, 0x17324a, 0x1d3a44, 0x223a52, 0x2a3a30, 0x3a3320];
    var col = new T.Color();
    var placed = 0;
    for (var i = 0; i < COUNT; i++) {
      // scatter in a ring/band around the path corridor, avoiding the very centre
      var ang = r() * 6.28, rad = 30 + r() * 100;
      var x = Math.cos(ang) * rad * (0.7 + r() * 0.6);
      var z = -140 + r() * 220;
      if (Math.abs(x) < 16 && z > -60) continue;      // keep the walking corridor clear
      var s = 0.6 + r() * 1.1;
      var gy = groundY(x, z);
      pos.set(x, gy + 3 * s, z); sc.set(s, s, s);
      m.compose(pos, q, sc); crowns.setMatrixAt(placed, m);
      col.setHex(palette[(r() * palette.length) | 0]); crowns.setColorAt(placed, col);
      pos.set(x, gy + 3 * s, z); sc.set(s, s * (0.9 + r() * 0.4), s);
      m.compose(pos, q, sc); trunks.setMatrixAt(placed, m);
      placed++;
    }
    trunks.count = placed; crowns.count = placed;
    trunks.instanceMatrix.needsUpdate = true; crowns.instanceMatrix.needsUpdate = true;
    if (crowns.instanceColor) crowns.instanceColor.needsUpdate = true;
    return { mesh: trunks, mesh2: crowns,
      dispose: function () { trunkGeo.dispose(); trunkMat.dispose(); crownGeo.dispose(); crownMat.dispose(); } };
  }

  // =========================================================================
  // RENDERER / CONTROLS / LOOP
  // =========================================================================

  function makeRenderer(canvas) {
    var r = new T.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.setClearColor(COL.nightMid, 1);
    // ACES filmic tone mapping — the single biggest flat→cinematic upgrade. Exposure
    // tuned against the rendered scene (a touch under 1 keeps the night moody).
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
      uShadow: { value: new T.Color(0x0b1230) },   // indigo lift in the darks
      uHi: { value: new T.Color(0xffe6b0) },        // warm gold in the brights
    },
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader:
      "varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uVignette;" +
      "uniform vec3 uShadow; uniform vec3 uHi;" +
      "void main(){ vec4 c = texture2D(tDiffuse, vUv);" +
      " float l = dot(c.rgb, vec3(0.299,0.587,0.114));" +
      // tint shadows indigo, highlights warm — a gentle split-tone
      " vec3 tinted = c.rgb + uShadow*(1.0-l)*0.22 + (uHi-vec3(1.0))*l*0.10;" +
      // vignette: darken toward the corners
      " float d = distance(vUv, vec2(0.5)); float vig = smoothstep(0.85, 0.35*uVignette, d);" +
      " tinted *= mix(0.62, 1.0, vig);" +
      " gl_FragColor = vec4(tinted, c.a); }",
  };

  // Build the composer pipeline: scene render → bloom → grade/vignette. Bloom picks out
  // the high-emissive path, lanterns, temple and fireflies as glowing light.
  function makeComposer(renderer, scene, cam, w, h) {
    var composer = new T.EffectComposer(renderer);
    composer.addPass(new T.RenderPass(scene, cam));
    var bloom = new T.UnrealBloomPass(new T.Vector2(w, h), 0.62, 0.55, 0.82);
    composer.addPass(bloom);
    var grade = new T.ShaderPass(GradeShader);
    grade.renderToScreen = true;
    composer.addPass(grade);
    composer.setSize(w, h);
    composer._bloom = bloom;
    return composer;
  }

  function makeCamera(w, h) {
    var cam = new T.PerspectiveCamera(52, w / Math.max(1, h), 0.5, 900);
    return cam;
  }

  function makeControls(cam, dom) {
    var c = new T.OrbitControls(cam, dom);
    c.enableDamping = true; c.dampingFactor = 0.08;
    c.minDistance = 20; c.maxDistance = 180;
    c.maxPolarAngle = Math.PI * 0.49;     // don't dip under the ground
    c.minPolarAngle = Math.PI * 0.18;     // don't fly straight overhead
    c.enablePan = true; c.screenSpacePanning = false;
    c.panSpeed = 0.6; c.rotateSpeed = 0.55; c.zoomSpeed = 0.8;
    c.autoRotate = false; c.autoRotateSpeed = 0.18;   // gentle idle drift (brief §4)
    return c;
  }

  // Frame the camera to rest near a world point (the active grove), looking toward
  // the temple. Smoothly if animating, instantly under reduced motion.
  function restNear(state, target, height, dist, instant) {
    var cam = state.cam, ctl = state.controls;
    // look a good way DOWN the path toward the temple so the journey + destination read
    var look = new T.Vector3(target.x * 0.3, target.y + 4, target.z - 55);
    var eye = new T.Vector3(target.x + 6, target.y + (height || 26), target.z + (dist || 42));
    if (instant || reduced()) {
      cam.position.copy(eye); ctl.target.copy(look); ctl.update();
    } else {
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
      // rest the camera near the active grove, looking toward the temple
      var ai = this.state.activeIndex, L = this.state.laid[ai];
      if (L) restNear(this.state, { x: L.x, y: groundY(L.x, L.z), z: L.z }, 26, 46, true);
      else restNear(this.state, { x: 0, y: 0, z: 30 }, 30, 60, true);
    },

    // Build the drill-in CONCEPT sub-forest for a pillar.
    renderGrove: function (data, pillar) {
      if (!this.ok()) return;
      this.data = data; this.mode = "grove"; this.curPillar = pillar;
      this._install(buildScene(data, "grove"));
      var ai = this.state.activeIndex, L = this.state.laid[ai];
      if (L) restNear(this.state, { x: L.x, y: groundY(L.x, L.z), z: L.z }, 22, 40, true);
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
      this._resize();
      this._wirePick();
      if (this.visible) this._start();
    },

    // Constrained orbit is via OrbitControls; these expose the HUD zoom buttons.
    zoom: function (mult) {
      if (!this.state) return;
      var c = this.state.controls, cam = this.state.cam;
      var dir = cam.position.clone().sub(c.target);
      var d = dir.length() / mult;
      d = Math.max(c.minDistance, Math.min(c.maxDistance, d));
      cam.position.copy(c.target).add(dir.setLength(d)); c.update();
    },
    zoomReset: function () {
      if (!this.state) return;
      var ai = this.state.activeIndex, L = this.state.laid[ai];
      if (L) restNear(this.state, { x: L.x, y: groundY(L.x, L.z), z: L.z }, 26, 46, false);
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
      this.state.cam.aspect = w / Math.max(1, h); this.state.cam.updateProjectionMatrix();
      if (this.state.composer) this.state.composer.setSize(w, h);
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

      if (!calm) {
        // gentle idle camera drift so the scene always breathes (brief §4); user input via
        // OrbitControls damping overrides it while dragging.
        st.controls.autoRotate = true;
        // drive the shared WIND uniform on every toon material (height-masked sway in-shader)
        for (var wu = 0; wu < _windUniforms.length; wu++) _windUniforms[wu].value = t;
        // extra whole-canopy sway on the hero milestone trees for readable life up close
        for (var i = 0; i < st.pickables.length; i++) {
          var tr = st.pickables[i].obj, cp = tr.userData.canopy;
          if (cp) cp.rotation.z = Math.sin(t * 0.8 + i) * 0.03;
        }
        // aura pulse
        for (var a = 0; a < st.auras.length; a++) {
          var au = st.auras[a];
          var base = au.status === "active" ? 0.32 : au.status === "blossoming" ? 0.26 :
                     au.status === "lantern" ? 0.85 : 0.2;
          au.sp.material.opacity = base + Math.sin(t * 1.6 + a) * 0.1;
        }
        // you-are-here ring pulse + beam shimmer
        if (st.youHere) {
          var yh = st.youHere.userData;
          var s = 1 + Math.sin(t * 2.0) * 0.08;
          yh.ring.scale.set(s, s, s);
          yh.pin.position.y = 20 + Math.sin(t * 1.5) * 1.2;
          if (yh.beam) yh.beam.material.opacity = 0.09 + Math.sin(t * 1.3) * 0.04;
        }
        // hanging lanterns bob + flicker
        for (var ln = 0; ln < st.lanterns.length; ln++) {
          var lu = st.lanterns[ln].userData;
          if (lu && lu.glow) lu.glow.material.opacity = 0.75 + Math.sin(t * 3 + lu.phase) * 0.2;
        }
        // pond rim shimmer + god-ray breath
        if (st.godrays) st.godrays.userData.mat.opacity = 0.04 + Math.sin(t * 0.6) * 0.03;
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
          ff.mat.opacity = 0.6 + Math.sin(t * 2) * 0.25;
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
