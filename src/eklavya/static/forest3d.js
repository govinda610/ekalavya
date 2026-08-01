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
      // emissive kept LOW (leaves get their colour from lighting + the toon ramp); the glow
      // comes from the aura halo + bloom, so the tree keeps a defined silhouette.
      case "blossoming": return { leaf: 0xd9a63e, leaf2: COL.goldBright, glow: COL.gold, bare: false, lush: 1.15, emissive: 0.1 };
      case "active":     return { leaf: 0x3fb8b0, leaf2: COL.tealBright, glow: COL.teal, bare: false, lush: 1.05, emissive: 0.12 };
      case "unlocked":   return { leaf: COL.green, leaf2: COL.greenLit, glow: COL.green, bare: false, lush: 0.95, emissive: 0.08 };
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
    var W = 320, D = 420, segW = 100, segD = 120;
    var geo = new T.PlaneGeometry(W, D, segW, segD);
    geo.rotateX(-Math.PI / 2);
    var pos = geo.attributes.position, v = new T.Vector3(), col = new T.Color();
    var colors = new Float32Array(pos.count * 3);
    for (var i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      var y = groundY(v.x, v.z);
      pos.setY(i, y);
      // vertex-tint: warmer moss near the path corridor, cooler indigo out in the deep wood
      var nearPath = Math.exp(-(v.x * v.x) / 2600);
      col.setHex(COL.ground).lerp(new T.Color(0x243a30), nearPath * 0.7);
      colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b;
    }
    geo.setAttribute("color", new T.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    var mat = new T.MeshStandardMaterial({
      vertexColors: true, roughness: 1.0, metalness: 0.0, flatShading: true,
      emissive: 0x0a1428, emissiveIntensity: 0.3,
    });
    return new T.Mesh(geo, mat);
  }

  // Sample the terrain height analytically (single source of truth for terrain + props).
  // A rolling floor + a prominent TEMPLE HILL rising at the far (−Z) end so the temple
  // sits elevated and readable; a shallow flat corridor keeps the path walkable.
  function groundY(x, z) {
    var h = Math.sin(x * 0.05) * 1.6 + Math.cos(z * 0.045 + x * 0.02) * 2.0
          + Math.sin(x * 0.11 + z * 0.03) * 0.9;
    // hill ramps up smoothly toward the back, cresting under the temple
    var hill = Math.max(0, (-z - 70)) * 0.62;
    var corridor = Math.exp(-(x * x) / 1600) * 1.0;
    return h + hill - corridor;
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
      // locked: crooked bare limbs, dim, no leaves
      for (var l = 0; l < 5; l++) {
        var ang = l / 5 * 6.28 + r();
        var f = new T.Vector3(top.x, top.y * (0.6 + 0.1 * l), top.z);
        var t2 = new T.Vector3(Math.cos(ang) * 3 * s, top.y + (0.4 + r()) * 2 * s, Math.sin(ang) * 3 * s);
        g.add(_limb(f, t2, f.clone().lerp(t2, 0.5).add(new T.Vector3(0, s, 0)), 0.18 * s, 0.05 * s, barkMat));
      }
      g.userData.canopy = null;
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

  // The golden TEMPLE — the composition's ANCHOR on the far hill. An ornate stepped
  // shikhara (central tower + tapering tiers + spire) on a wide platform, flanked by two
  // smaller towers, all emissive gold so it glows like the reference Sunset-Peak temple.
  function buildTemple() {
    var g = new T.Group();
    var mat = new T.MeshStandardMaterial({
      color: COL.goldBright, emissive: COL.gold, emissiveIntensity: 1.15,
      roughness: 0.3, metalness: 0.4, flatShading: true, fog: false,
    });
    // wide base platform
    var plat = new T.Mesh(new T.BoxGeometry(30, 3, 20), mat); plat.position.y = 1.5; g.add(plat);
    // a central stepped tower (shikhara)
    function tower(cx, cz, tiers, top) {
      var y = 3;
      for (var i = 0; i < tiers.length; i++) {
        var w = tiers[i][0], h = tiers[i][1];
        var box = new T.Mesh(new T.BoxGeometry(w, h, w * 0.72), mat);
        box.position.set(cx, y + h / 2, cz); g.add(box);
        y += h * 0.84;
      }
      var spire = new T.Mesh(new T.ConeGeometry(top || 2.4, 9, 6), mat);
      spire.position.set(cx, y + 4, cz); g.add(spire);
      return y + 8;
    }
    var topY = tower(0, 0, [[15, 7], [12, 6], [9, 6], [6, 6], [4, 5]], 2.6);
    tower(-11, -1, [[8, 5], [6, 4.5], [4, 4]], 1.6);
    tower(11, -1, [[8, 5], [6, 4.5], [4, 4]], 1.6);
    // a modest warm point-light + a small halo so the temple reads as a beacon (not a nuke)
    var glow = new T.PointLight(0xffd98a, 1.4, 140, 2.0); glow.position.y = topY * 0.5; g.add(glow);
    var halo = glowSprite(COL.goldBright, 60, 0.4, true); halo.position.y = topY * 0.5; g.add(halo);
    g.userData.mats = [mat]; g.userData.topY = topY;
    return g;
  }

  // Warm upward LIGHT SHAFTS rising behind the temple (its aura on the horizon) — a few
  // tall additive planes fanning up, like the glow behind the temple in both refs.
  function buildTempleRays(topY) {
    var g = new T.Group();
    var mat = new T.MeshBasicMaterial({ color: 0xffe6a8, transparent: true, opacity: 0.045,
      blending: T.AdditiveBlending, depthWrite: false, side: T.DoubleSide, fog: false });
    for (var i = -3; i <= 3; i++) {
      var pl = new T.Mesh(new T.PlaneGeometry(6, 120), mat);
      pl.position.set(i * 9, topY + 26, -4); pl.rotation.z = i * 0.05; g.add(pl);
    }
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

    // The path is a WIDE flat glowing RIBBON hugging the ground (a flattened tube), so it
    // reads clearly as a luminous trail from the high camera (like both refs) rather than a
    // thin pipe hidden by foliage. Fog-free emissive keeps it glowing into the distance.
    function ribbon(t0, t1, color, emissive, width, op) {
      var n = Math.max(6, Math.round((t1 - t0) * 140));
      var sub = [];
      for (var i = 0; i <= n; i++) sub.push(curve.getPoint(t0 + (t1 - t0) * i / n));
      var c2 = new T.CatmullRomCurve3(sub);
      var geo = new T.TubeGeometry(c2, n, width, 8, false);
      geo.scale(1, 0.28, 1);   // flatten → a ribbon on the ground, not a pipe
      var mat = new T.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: emissive,
        roughness: 0.4, transparent: true, opacity: op, fog: false });
      var m = new T.Mesh(geo, mat);
      g.add(m); g.userData.disposables = (g.userData.disposables || []).concat([geo, mat]);
      // a soft glow strip just under it so the trail bleeds light onto the ground
      var gmat = new T.MeshBasicMaterial({ color: color, transparent: true, opacity: op * 0.35,
        blending: T.AdditiveBlending, depthWrite: false, fog: false });
      var geo2 = new T.TubeGeometry(c2, n, width * 2.1, 8, false); geo2.scale(1, 0.06, 1);
      var m2 = new T.Mesh(geo2, gmat); m2.position.y -= 0.2; g.add(m2);
      g.userData.disposables = g.userData.disposables.concat([geo2, gmat]);
      return m;
    }
    // traveled (warm gold, bright HDR → blooms) → then ahead (cool teal, dimmer)
    ribbon(0, travT, COL.gold, 2.4, 2.2, 0.98);
    if (travT < 1) ribbon(travT, 1, COL.teal, 1.0, 1.7, 0.7);
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
    var body = new T.Mesh(new T.SphereGeometry(0.7, 8, 8),
      new T.MeshBasicMaterial({ color: 0xffcf7a }));
    body.position.set(x, y, z); g.add(body);
    var glow = glowSprite(COL.ember, 8, 0.9); glow.position.set(x, y, z); g.add(glow);
    var thread = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 4, 4),
      new T.MeshBasicMaterial({ color: 0x3a2c14 }));
    thread.position.set(x, y + 2.2, z); g.add(thread);
    var pl = null;
    if (light) { pl = new T.PointLight(0xffb15a, 1.1, 42, 2.0); pl.position.set(x, y, z); g.add(pl); }
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
  function buildFraming(cam) {
    var g = new T.Group();
    var lanterns = [];
    var bark = new T.MeshStandardMaterial({ color: 0x090b14, roughness: 1, flatShading: true });
    var leaf = new T.MeshStandardMaterial({ color: 0x0b1220, roughness: 1, flatShading: true,
      emissive: 0x0a1428, emissiveIntensity: 0.12 });
    var r = rng(777);

    // --- two BIG corner trees close to camera, trunks arching inward, dense crowns up the
    //     side edges — the ornate proscenium that frames the vista in both refs. ----------
    [[-40, 52, 1], [42, 56, -1]].forEach(function (a) {
      var x = a[0], z = a[1], dir = a[2], gy = groundY(x, z);
      // a massive gnarled trunk sweeping up and inward across the side of frame
      var trunk = _limb(new T.Vector3(x, gy - 8, z),
        new T.Vector3(x - dir * 16, gy + 60, z - 8),
        new T.Vector3(x - dir * 3, gy + 28, z - 3), 6.5, 3.0, bark);
      g.add(trunk);
      // a thick wall of dark crowns climbing + arching over the side edge
      for (var b = 0; b < 13; b++) {
        var cy = gy + 10 + b * 5.2;
        var cx = x - dir * (1 + b * 1.7);
        var cr = 11 + r() * 7;
        var m = new T.Mesh(new T.IcosahedronGeometry(cr, 0), leaf);
        m.position.set(cx, cy, z - 4 + (r() - 0.5) * 10); g.add(m);
      }
      // hanging lanterns from the corner branches, dangling into frame (glow only — real
      // point-lights are reserved for the path/groves so the light budget stays capped)
      for (var k = 0; k < 2; k++) {
        var lx = x - dir * (16 + k * 10), ly = gy + 44 - k * 8, lz = z - 8;
        var lan = buildLantern(lx, ly, lz, (r() * 1e5) | 0, false);
        g.add(lan); lanterns.push(lan);
      }
    });

    // --- TOP overhang: a row of dark leaf-masses hanging down from above the frame ----
    for (var o = 0; o < 12; o++) {
      var ox = -60 + o * 11 + (r() - 0.5) * 6;
      var oy = 62 + (r() - 0.5) * 8;
      var oz = 18 + (r() - 0.5) * 10;
      var om = new T.Mesh(new T.IcosahedronGeometry(10 + r() * 7, 0), leaf);
      om.position.set(ox, oy, oz); g.add(om);
      // a branch stub the mass hangs from
      var stub = new T.Mesh(new T.CylinderGeometry(0.5, 1.2, 10, 5), bark);
      stub.position.set(ox, oy + 7, oz); g.add(stub);
    }
    // a few lanterns hanging from the top overhang, dangling into the upper frame
    for (var tl = 0; tl < 3; tl++) {
      var tx = -34 + tl * 34, ty = 50 - r() * 6, tz = 16;
      var tlan = buildLantern(tx, ty, tz, (r() * 1e5) | 0);
      g.add(tlan); lanterns.push(tlan);
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
    var shrubMat = toonMat({ color: 0x1e3a2c });
    var shrubMat2 = toonMat({ color: 0x24402e });
    var count = reduced() ? 45 : 85;   // capped: keeps draw-calls modest on lean hardware
    for (var i = 0; i < count; i++) {
      // bias placement near the path curve so the trail feels planted-in, not floating
      var t = r();
      var cp = curve ? curve.getPoint(t) : new T.Vector3((r() - 0.5) * 120, 0, -40 + r() * 120);
      var off = 6 + r() * 40, side = r() < 0.5 ? -1 : 1;
      var x = cp.x + side * off + (r() - 0.5) * 10;
      var z = cp.z + (r() - 0.5) * 24;
      if (Math.abs(x) > 150 || z > 90 || z < -150) continue;
      var gy = groundY(x, z);
      var kind = r();
      if (kind < 0.5) {
        // a shrub: a squashed leaf blob
        var sh = new T.Mesh(new T.IcosahedronGeometry(1.2 + r() * 1.4, 0), r() < 0.5 ? shrubMat : shrubMat2);
        sh.position.set(x, gy + 0.8, z); sh.scale.y = 0.7; g.add(sh);
      } else if (kind < 0.8) {
        // a fern: a few thin cones fanning up
        for (var f = 0; f < 4; f++) {
          var blade = new T.Mesh(new T.ConeGeometry(0.22, 2.4 + r(), 4), shrubMat2);
          blade.position.set(x + (r() - 0.5) * 1.2, gy + 1.2, z + (r() - 0.5) * 1.2);
          blade.rotation.z = (r() - 0.5) * 0.9; g.add(blade);
        }
      } else {
        // a glowing mushroom (teal or violet accent) — the magical understory
        var mcol = r() < 0.5 ? 0x57d3ce : 0xb07bd6;
        var cap = new T.Mesh(new T.SphereGeometry(0.5 + r() * 0.3, 8, 6, 0, 6.28, 0, 1.7),
          new T.MeshBasicMaterial({ color: mcol }));
        cap.position.set(x, gy + 1.1, z); g.add(cap);
        var stem = new T.Mesh(new T.CylinderGeometry(0.1, 0.14, 1, 5),
          new T.MeshStandardMaterial({ color: 0xdfe6ea }));
        stem.position.set(x, gy + 0.5, z); g.add(stem);
        var mg = glowSprite(mcol, 3, 0.6); mg.position.set(x, gy + 1.2, z); g.add(mg);
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

  // Lay grove positions out along a gently-serpentine path receding toward the
  // temple (−Z). Order comes from data (`order`); we snake x so it curves.
  function layoutGroves(groves) {
    var n = groves.length;
    var out = [];
    // The path climbs from the foreground toward the temple (−Z). Spacing scales with N
    // so 3 or 16 pillars both read as a walkable journey. The serpentine sway EASES to
    // near-zero at the far end so the last grove + path funnel onto the temple's centre
    // axis — leading the eye to the anchor (both refs do this). Nothing keyed to a pillar.
    var spacing = Math.max(17, Math.min(30, 160 / Math.max(1, n)));
    var zStart = 74;
    for (var i = 0; i < n; i++) {
      var z = n > 1 ? zStart - i * spacing : 34;
      var ease = 1 - i / Math.max(1, n - 1);          // 1 near … 0 far
      var x = Math.sin(i * 1.05 + 0.5) * (40 * ease * ease);   // sway collapses toward the temple
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
    // lighter fog so the temple + far tree-wall stay readable (not swallowed); still enough
    // to melt the deepest trees into night and give depth layering.
    scene.fog = new T.FogExp2(0x111a30, reduced() ? 0.004 : 0.0052);
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

    // --- lights: cool sky fill + a brighter moon key + a warm horizon fill ----
    scene.add(new T.HemisphereLight(0x9fb6e0, 0x0e1526, 0.95));  // cool sky / dark ground
    var moon = new T.DirectionalLight(0xe6ecff, 1.0);            // pale moonlight key
    moon.position.set(70, 120, 40); scene.add(moon);
    var warm = new T.DirectionalLight(0xffdca0, 0.35);          // warm bounce from the temple side
    warm.position.set(0, 30, -120); scene.add(warm);

    // --- moon disc + haze, high over the far ridge (up-right of the temple) ----
    var moonGroup = new T.Group();
    var moonDisc = new T.Mesh(new T.CircleGeometry(13, 32),
      new T.MeshBasicMaterial({ color: COL.moon, fog: false }));
    var moonHaze = glowSprite(0xdfe8ff, 90, 0.6);
    moonGroup.add(moonHaze); moonGroup.add(moonDisc);
    moonGroup.position.set(140, 150, -230);
    moonGroup.lookAt(0, 20, 40);
    scene.add(moonGroup);

    // --- terrain -------------------------------------------------------------
    scene.add(buildTerrain());

    // --- god-rays sweeping from the moon (motion-gated) ----------------------
    var godrays = null;
    if (!reduced()) { godrays = buildGodrays(); scene.add(godrays); }

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

    // FIXED END bookend: the TEMPLE — the composition anchor — beyond the last grove, high
    // on the hill, straight ahead on the path's centre axis so the eye is led to it.
    var lastZ = laid.length ? laid[laid.length - 1].z : 0;
    var templeZ = Math.min(-150, lastZ - 60);         // further back → reads as a distant anchor
    var templeTopY = 0;
    if (mode === "overview") {
      var temple = buildTemple();
      var tgy = groundY(0, templeZ);
      temple.position.set(0, tgy + 2, templeZ);
      temple.scale.set(1.3, 1.3, 1.3);
      scene.add(temple);
      templeTopY = tgy + temple.userData.topY * 1.4;
      scene.add(buildTempleRays(templeTopY));
      // a soft warm halo behind the temple (small + gentle so the temple stays a defined
      // glowing structure, not a white sunburst) — fog-free so it reads on the horizon.
      var tbloom = glowSprite(0xffdc94, 100, 0.28, true);
      tbloom.position.set(0, tgy + 26, templeZ - 8); scene.add(tbloom);
    }

    // --- DENSE background tree walls (both modes) ----------------------------
    var bgGroup = buildInstancedForest();
    scene.add(bgGroup.mesh); scene.add(bgGroup.mesh2);

    // --- the glowing winding PATH (traveled glow runs start→active) ----------
    var path = buildPath(laid, activeIndex, templeZ, mode === "overview");
    scene.add(path);

    // --- low ground FOLIAGE + drifting MIST layers (both modes) --------------
    scene.add(buildGroundFoliage(path.userData.curve));
    var mist = null;
    if (!reduced()) { mist = buildMist(); scene.add(mist); }

    // --- PROSCENIUM framing (dark overhanging foliage + hanging lanterns) ----
    var framing = buildFraming();
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

    var pickables = [];   // { obj, grove, x/y/z } for raycasting
    var auras = [];       // grove aura sprites to pulse
    var youHere = null;

    for (var j = 0; j < laid.length; j++) {
      var L = laid[j], gd = L.grove;
      var st = styleFor(gd.status);
      var gy = groundY(L.x, L.z);
      var scale = mode === "overview" ? 1.3 : 1.0;
      var seed = hashStr(gd.pillar || gd.name);
      var arche = GROVE_ARCHES[seed % GROVE_ARCHES.length];
      // the ACTIVE grove always gets a hero banyan/willow; others vary by seed.
      var variant = gd._active ? (seed % 2 ? "banyan" : "willow")
        : ["oak", "banyan", "blossom", "oak", "willow"][seed % 5];

      var piece = new T.Group();
      piece.position.set(L.x, gy, L.z);
      var tree = buildTree(st, scale, seed, variant);
      piece.add(tree);
      arche.decor(piece, st, scale, rng(seed), COL);
      piece.userData.grove = gd; piece.userData.arche = arche.name;
      scene.add(piece);
      pickables.push({ obj: tree, grove: gd, x: L.x, y: gy, z: L.z, piece: piece });

      // soft aura HALO behind lit trees (subtle — bloom lifts it without washing the tree)
      if (!st.bare) {
        var aura = glowSprite(st.glow, 30 * scale, 0.22);
        aura.position.set(L.x, gy + 12 * scale, L.z - 2);
        scene.add(aura); auras.push({ sp: aura, status: gd.status });
      }
      // hanging LANTERN(s) from each lit grove; a real warm light on the nearest few.
      if (!st.bare) {
        var lan = buildLantern(L.x + 5 * scale, gy + 12 * scale, L.z + 3, seed, lightBudget-- > 0);
        scene.add(lan); lanterns.push(lan);
      }
      if ((gd.artifacts || 0) > 0) {
        var lan2 = buildLantern(L.x - 5 * scale, gy + 10 * scale, L.z + 1, seed + 7, false);
        scene.add(lan2); lanterns.push(lan2);
      }
      // "YOU ARE HERE" teal ring encircling the active grove
      if (gd._active) {
        youHere = buildYouHere(st);
        youHere.position.set(L.x, gy + 0.1, L.z);
        scene.add(youHere);
      }
    }

    // --- fireflies + birds ---------------------------------------------------
    var fireflies = null, birds = [];
    if (!reduced()) {
      fireflies = buildFireflies(Math.min(240, 120 + laid.length * 12), 220);
      scene.add(fireflies);
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
      fireflies: fireflies, birds: birds, path: path, moonHaze: moonHaze,
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
    // ground glow disc filling the ring (soft, additive — no edges)
    var disc = glowSprite(COL.teal, 26, 0.3); disc.position.y = 1.2;
    disc.material.rotation = 0; g.add(disc);
    // a faint upward glow column made of stacked fading sprites (soft, edgeless)
    var col = new T.Group();
    for (var i = 0; i < 4; i++) {
      var sp = glowSprite(COL.tealBright, 16 - i * 2, 0.16 - i * 0.03);
      sp.position.y = 6 + i * 7; col.add(sp);
    }
    g.add(col);
    g.userData = { ring: ring, ring2: ring2, glow: disc, col: col,
      disposables: [ringGeo, ringMat, ring2Geo, ring2Mat] };
    return g;
  }

  // Instanced BACKGROUND trees — a lush, cheap woodland filling the scene with
  // depth. Two instanced meshes (trunks + crowns) so the whole wood is a handful
  // of draw calls regardless of tree count.
  function buildInstancedForest() {
    var COUNT = reduced() ? 260 : 520;               // a DENSE wood — you can't see through it
    var trunkGeo = new T.CylinderGeometry(0.3, 0.55, 6, 5);
    var trunkMat = new T.MeshStandardMaterial({ color: 0x0e1524, roughness: 1, flatShading: true });
    // two crown layers so the canopy has variety + a fuller silhouette
    var crownGeo = new T.IcosahedronGeometry(2.4, 0);
    var crownMat = new T.MeshStandardMaterial({ roughness: 0.9, flatShading: true,
      emissive: 0x0a1220, emissiveIntensity: 0.2, vertexColors: true });
    var trunks = new T.InstancedMesh(trunkGeo, trunkMat, COUNT);
    var crowns = new T.InstancedMesh(crownGeo, crownMat, COUNT);
    var m = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), pos = new T.Vector3();
    var r = rng(20240802);
    // painterly canopy palette: deep indigos, forest teals, emerald, a violet whisper +
    // an occasional warm glint — the colour VARIETY the refs have (not a monochrome navy).
    var palette = [0x16243c, 0x14304a, 0x1a3a40, 0x244a34, 0x2f4a28, 0x2a2440, 0x3a3320, 0x1d2a44];
    var col = new T.Color();
    var placed = 0;
    for (var i = 0; i < COUNT && placed < COUNT; i++) {
      // DEPTH BANDS: denser and further-spread toward the back so far trees form a wall
      // that fades into fog; nearer bands sparser so the mid-ground stays readable.
      var band = r();                        // 0 near … 1 far
      var z = 60 - band * 210;               // near (+z) → far (−z)
      var spreadX = 40 + band * 120;
      var x = (r() - 0.5) * 2 * spreadX;
      // keep the central walking corridor + the temple footprint clear
      if (Math.abs(x) < 14 && z > -40) continue;
      if (Math.abs(x) < 24 && z < -120) continue;
      var s = (0.7 + r() * 1.2) * (1 + band * 0.5);   // far trees a bit bigger (they're a wall)
      var gy = groundY(x, z);
      pos.set(x, gy + 3 * s, z); sc.set(s, s * (0.9 + r() * 0.5), s);
      m.compose(pos, q, sc); crowns.setMatrixAt(placed, m);
      col.setHex(palette[(r() * palette.length) | 0]);
      // fade far crowns toward the fog/sky colour so the wall dissolves into night
      col.lerp(new T.Color(COL.nightMid), band * 0.4);
      crowns.setColorAt(placed, col);
      pos.set(x, gy + 2.6 * s, z);
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
    r.toneMappingExposure = 1.05;
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
      // split-tone: indigo into shadows, warm gold into highlights (a touch stronger warmth)
      " vec3 tinted = c.rgb + uShadow*(1.0-l)*0.22 + (uHi-vec3(1.0))*l*0.16;" +
      // a gentle overall saturation lift so the emerald/teal/gold read (not washed navy)
      " float g = dot(tinted, vec3(0.299,0.587,0.114));" +
      " tinted = mix(vec3(g), tinted, 1.18);" +
      // vignette: darken toward the corners to hold the eye on the glowing path/temple
      " float d = distance(vUv, vec2(0.5)); float vig = smoothstep(0.9, 0.35*uVignette, d);" +
      " tinted *= mix(0.6, 1.0, vig);" +
      " gl_FragColor = vec4(tinted, c.a); }",
  };

  // Build the composer pipeline: scene render → bloom → grade/vignette. Bloom picks out
  // the high-emissive path, lanterns, temple and fireflies as glowing light.
  function makeComposer(renderer, scene, cam, w, h) {
    var composer = new T.EffectComposer(renderer);
    composer.addPass(new T.RenderPass(scene, cam));
    // strength moderate, radius soft, threshold HIGH so only the truly bright emitters
    // (path, lanterns, temple, fireflies, rings) bloom — the lit tree crowns keep their
    // silhouette instead of washing to a white blob.
    var bloom = new T.UnrealBloomPass(new T.Vector2(w, h), 0.5, 0.65, 1.0);
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
    c.minDistance = 24; c.maxDistance = 130;
    c.maxPolarAngle = Math.PI * 0.5;      // don't dip under the ground
    c.minPolarAngle = Math.PI * 0.24;     // keep a grounded, cinematic eye-level (temple stays framed)
    c.enablePan = true; c.screenSpacePanning = false;
    c.panSpeed = 0.6; c.rotateSpeed = 0.5; c.zoomSpeed = 0.8;
    c.autoRotate = false; c.autoRotateSpeed = 0.14;   // gentle idle drift (brief §4)
    return c;
  }

  // Frame the DEFAULT camera so the composition reads foreground → winding path → glowing
  // TEMPLE at the focal third (both refs). We sit behind/above the active grove and aim the
  // look-target up the path toward the temple, so the temple lands high-centre in frame and
  // the path leads the eye to it. Smooth tween unless instant/reduced.
  function restNear(state, target, height, dist, instant) {
    var cam = state.cam, ctl = state.controls;
    var tZ = state.templeZ != null ? state.templeZ : target.z - 34;   // no temple → aim just ahead
    // Aim roughly a THIRD of the way from the active grove toward the temple, lifted a
    // little — so the active grove + its ring sit lower-centre, the path recedes through
    // the middle, and the temple crowns the upper third.
    var look = new T.Vector3(target.x * 0.25, target.y + 8, target.z + (tZ - target.z) * 0.4);
    // Eye sits behind + above the active grove; not so far back that the grove drops off
    // the bottom (dist tuned so the active grove lands ~lower third of frame).
    var eye = new T.Vector3(target.x * 0.5, target.y + (height || 34), target.z + (dist || 50));
    if (instant || reduced()) {
      cam.position.copy(eye); ctl.target.copy(look); ctl.update();
    } else {
      state._tween = { fromE: cam.position.clone(), toE: eye,
        fromT: ctl.target.clone(), toT: look, t: 0, dur: 1.2 };
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
      // frame foreground → path → temple, from a high vantage behind the active grove
      var ai = this.state.activeIndex, L = this.state.laid[ai];
      if (L) restNear(this.state, { x: L.x, y: groundY(L.x, L.z), z: L.z }, 34, 52, true);
      else restNear(this.state, { x: 0, y: 0, z: 34 }, 38, 60, true);
    },

    // Build the drill-in CONCEPT sub-forest for a pillar (same lush assembly as overview).
    // No temple here, so we frame TIGHTER on the active concept (a closer, lower eye) so
    // the concept trees are the heroes rather than a distant emptiness.
    renderGrove: function (data, pillar) {
      if (!this.ok()) return;
      this.data = data; this.mode = "grove"; this.curPillar = pillar;
      this._install(buildScene(data, "grove"));
      this.state.templeZ = null;   // no anchor → restNear frames locally, not toward a temple
      var ai = this.state.activeIndex, L = this.state.laid[ai];
      if (L) restNear(this.state, { x: L.x, y: groundY(L.x, L.z), z: L.z }, 24, 44, true);
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
        // aura pulse (soft halo behind lit groves)
        for (var a = 0; a < st.auras.length; a++) {
          var au = st.auras[a];
          var base = au.status === "active" ? 0.28 : au.status === "blossoming" ? 0.24 : 0.18;
          au.sp.material.opacity = base + Math.sin(t * 1.6 + a) * 0.08;
        }
        // you-are-here ring pulse (breathes) + soft glow shimmer
        if (st.youHere) {
          var yh = st.youHere.userData;
          var s = 1 + Math.sin(t * 1.6) * 0.05;
          yh.ring.scale.set(s, s, s);
          if (yh.ring2) yh.ring2.material.opacity = 0.28 + Math.sin(t * 1.6) * 0.1;
          if (yh.glow) yh.glow.material.opacity = 0.26 + Math.sin(t * 1.6) * 0.08;
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
