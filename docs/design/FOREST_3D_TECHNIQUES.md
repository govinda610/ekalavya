# Techniques Brief: Gorgeous Real-Time 3D "Enchanted Mythological Forest" in Three.js

> Research brief for the Forest Map 3D rebuild. No-build, vendored, offline. Target: Journey × Studio Ghibli × ancient-India mythological illustration. Nighttime, deep-indigo sky, warm gold + luminous teal + ember firelight, winding glowing path to a distant golden temple, milestone trees, fireflies, gliding birds, gentle wind. 60fps, data-driven.

**North-star principle:** In WebGL, beauty is ~80% post-processing + lighting + color, ~15% composition/atmosphere, ~5% model detail. A low-poly scene with ACES tone mapping, tuned bloom, layered fog, and warm/cool contrast reads as a painterly illustration. The same scene raw reads as programmer-art. Spend effort where the leverage is.

## 0) Versions & setup
- Current stable Three.js: **0.185.1 (r185)**, rolling rNNN scheme (not semver). Pin one exact version.
- Addons under `three/examples/jsm/...`, aliased `three/addons/...` in import maps. Core + addons imported separately.
- **r150+ gotcha:** `three.module.js` depends on `three.core.js` — vendor BOTH.
- Never mix an addon file from one release with a core from another.

## 1) Post-processing & lighting — biggest beauty levers
Pipeline (order is load-bearing): RenderPass → UnrealBloomPass → (vignette/grade ShaderPass) → OutputPass (must be LAST; applies tone map + sRGB). Call `composer.render()`.
- `renderer.toneMapping = THREE.ACESFilmicToneMapping` + `toneMappingExposure` 0.8–1.3 — single biggest look upgrade.
- UnrealBloomPass(res, strength 0.8–1.5, radius 0.4–0.8, threshold 0.6–0.85). Nighttime enchanted → lower threshold ~0.7 + moderate strength. Bloom BEFORE OutputPass so it blooms HDR values. High `emissiveIntensity` on path/lanterns/temple/fireflies so bloom picks them out. Selective bloom if trees must stay grounded.
- Color grade + vignette in one small ShaderPass: indigo shadows, gold/teal highlights, darkened corners (`smoothstep` on uv distance). Optional LUTPass for baked film grade.
- DoF: BokehPass, subtle (focus=temple dist, aperture ~0.0002, maxblur ~0.008). Keep subtle.
- God-rays, cheapest→best: (1) additive translucent ConeGeometry from temple/moon; (2) screen-space GPU-Gems radial blur (official godrays example); (3) `three-good-godrays` (verify r185 compat, else pin 0.182).
- Lighting: cool hemisphere/ambient (indigo→dark ground) + one warm directional "moonlight" (pale gold, low) + warm emissive lantern/temple meshes. Keep real shadow-casting lights to 1–2; fake the rest with emissive + bloom. **Warm/cool contrast is the whole game.**

## 2) Stylized forest
- **Instanced trees** (InstancedMesh, one draw call). Per-instance `timeShift` (0–2π) for out-of-phase sway — most important anti-robotic trick. 3–4 base meshes for variety.
- Hero/milestone trees = real low-poly glTF near path; mid = instanced; distant wall = billboards behind fog (implies infinite depth cheaply).
- **FogExp2** (density ~0.01–0.03), color MATCHED to sky horizon or trees pop as flat silhouettes. 3-layer depth: near sharp → mid slight fog → far billboards fading to sky.
- **Gradient sky dome**: big inverted sphere, BackSide, depthWrite false; shader mixes indigo zenith → warm horizon glow (+ soft moon/temple glow via power-of-luminance).
- **Wind sway** via `material.onBeforeCompile` (keep MeshToon/Standard lighting). Sum 2–3 sines along wind dir × uTime + per-instance timeShift, masked by vertex height (trunks planted, canopies move).
- **Painterly = MeshToonMaterial** + tiny 3–5 step gradientMap (NearestFilter). Avoid full PBR — it fights stylization and costs more.
- Ground: subdivided plane, gentle simplex-noise displacement, `flatShading:true` faceted low-poly.
- **Glowing path (hero):** CatmullRomCurve3 → TubeGeometry, high emissive teal/gold + bloom. Animate flow toward temple by offsetting emissiveMap.offset each frame. Place milestones/lanterns via `curve.getPointAt(t)`.
- Pond: flat plane, scrolling normal map or sine shader, teal Fresnel tint, quiet reflective pool.

## 3) Particles & life — bias to core Three.js Points + custom shader (light, offline)
- **Fireflies/motes:** THREE.Points + ShaderMaterial. Vertex: drift `sin(uTime*speed+seed)`, per-point size, distance attenuation. Fragment: soft radial falloff, warm-gold/teal, AdditiveBlending, depthWrite false. Bloom turns dots into fireflies (Bruno Simon's Fireflies pattern). Flicker via alpha `sin`.
- Mist: few large soft semi-transparent billboards drifting at ground level.
- Lantern/temple glow: emissive mesh + additive radial-gradient glow sprite halo.
- **Birds:** billboards (2-frame flap) or low-poly along own CatmullRomCurves; `getPointAt` position + `getTangentAt`/lookAt orientation. Handful silhouetted against sky. Boids overkill.
- Libraries: `troika-three-text` (MIT, SDF labels, fog-aware) ONLY if text labels needed. **Skip `three-nebula`** — bundles its own three copy (~double include), footgun for vendored setup; core Points is lighter.

## 4) Camera & feel
- OrbitControls: `enableDamping` (dampingFactor ~0.05), min/maxDistance (8–40, no clipping/space), min/maxPolarAngle (0.6–1.45, above ground/below zenith), optional azimuth clamp to keep temple framed, `autoRotate` speed ~0.15 idle drift, `enablePan=false` to protect composition.
- OrbitControls can't fly-to alone → tween `camera.position` + `controls.target` together (`@tweenjs/tween.js`). OR use `yomotsu/camera-controls` (MIT) for polished `setLookAt`/`lerpLookAt`/`fitToSphere` + `rest` event — recommended if fly-to is central.
- Feel: constant subtle idle drift, ease everything (nothing snaps), constrain hard (never break composition/reveal backstage), parallax + DoF + fog for depth. Click-to-fly ~1.2s ease-out → reveal label/panel on arrival.

## 5) Inspiration (steal list)
- Codrops **Three.js Instances (2025)** — InstancedMesh forest + per-instance timeShift wind. Closest match.
- Codrops **Fractals to Forests (2025)** — multi-sine wind GLSL, branch/leaf animation.
- Codrops **Infinite Tubes** / Mamboleoo **Tunnel** — TubeGeometry-from-CatmullRom glowing path.
- maya-ndljk **Custom Toon Shader** / douges.dev **Fluffy Trees** — banded toon lighting ramp.
- Wael Yasmina **Selective Bloom** — only path/temple/fireflies glow.
- **Three.js Journey — Fireflies & Portal** — exact fireflies-as-Points + emissive portal glow (temple doorway).
- **bruno-simon.com** — heavy instancing, game-like alive-but-navigable feel.
- Nugget8 **Ocean Scene** — gradient sky + moon glow + cheap water. ianww **Skydome** — object-space-Y gradient dome.
- three.js **godrays example** + Andrew Berg walkthrough — radial-blur shaft toward temple/moon.

## 6) Free stylized assets (prefer CC0; verify per-model)
- **Quaternius — Stylized Nature MegaKit** (CC0, 40 trees/27 rocks, Ghibli-inspired), Ultimate/Textured Trees. glTF.
- **KayKit** structures (CC0, verify pack) — temple/buildings. **Kenney.nl** (CC0) — props/lanterns.
- **Poly Pizza** (mostly CC-BY, some CC0 — check each) — lanterns/temple/one-offs. **Sketchfab** filter Downloadable+CC0.
- Workflow: download glTF/GLB, `GLTFLoader`, re-material to toon/gradient for cohesion, decimate in Blender if needed.

## 7) No-build vendored offline plan
Vendor `three.module.js` + `three.core.js` + the specific addon files (EffectComposer, RenderPass, UnrealBloomPass, OutputPass, ShaderPass, OrbitControls, GLTFLoader) AND the `jsm/shaders/` chunks those passes import (simplest: vendor whole `examples/jsm/`). Import map in `<head>` BEFORE the module script:
```
{"imports":{"three":"./vendor/three.module.js","three/addons/":"./vendor/addons/"}}
```
Gotchas: import map before module script; serve over http:// not file:// (CORS); don't mix versions; let renderer.toneMapping + OutputPass do sRGB/tonemap (don't double-apply); optional `es-module-shims` for old browsers.

## 8) Biggest bang for the buck (do first — demo → illustration)
1. ACESFilmic tone mapping + tuned exposure (one line, biggest flat→cinematic jump).
2. UnrealBloomPass tuned (strength ~0.9, radius ~0.5, threshold ~0.7) + high emissive on path/lanterns/temple/fireflies.
3. Warm/cool color grade + vignette (one ShaderPass): indigo shadows, gold/teal highlights, dark corners.
4. FogExp2 horizon-matched + 3-layer depth (near mesh / mid instanced / far billboards → sky).
5. Gradient sky dome (indigo zenith → warm horizon glow behind temple).
6. Fireflies as additive Points (bloom → living light).
7. Glowing emissive path (Tube + scrolling emissive) leading eye to temple — composition spine.

Toon materials, wind, birds, DoF are the next tier. Tune bloom/exposure/fog against the ACTUAL scene — these are visual dials, not fixed numbers.
