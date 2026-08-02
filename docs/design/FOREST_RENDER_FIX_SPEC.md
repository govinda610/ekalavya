# Ekalavya — Forest of Mastery: 3D Render Fix Spec (v2)

Closing the gap between the current Three.js render and the three concept references.

**v2 changes:** revised after seeing the third reference (the labelled game-map). Sections 1, 5, 9 and 12 are materially rewritten; sections 0.5, 3b and 13 are new.

---

## 0. What is actually wrong (root causes, not symptoms)

| # | Root cause | Symptom in the screenshots |
|---|---|---|
| 1 | Camera is inside the forest at eye level | Trees crowd and clip the frame edges; you can never see more than 2 of the 7 groves; it doesn't read as a *map* |
| 2 | No shadows, no rim light, single flat key | Trees are dark blobs floating over grey; no volume, no ground contact |
| 3 | One tree archetype instanced hundreds of times, all the same colour | Uniform visual noise; groves are indistinguishable from filler and from each other |
| 4 | Neutral grey ground + neutral grey fog | Every colour in the scene is muddied; the image reads dead |
| 5 | Bloom threshold near zero, emissive is pure white | Temple is an unreadable white slab; "mastered" trees clip to white and read as **snow** |
| 6 | Only two depth planes, no foreground framing | Flat; the references' dark arching foreground is entirely absent |
| 7 | All labels live inside click popups | The map carries no information until you click it — it's decoration with a hit-test |

Points 3 (colour) and 7 are the two biggest *functional* misses, and they're the cheapest to fix.

---

## 0.5 First: decide what this screen is

The three references are pulling in two directions, and the current build is caught between them.

- **References B and C** (the "Progress Map" vista and the "You are here" panorama) are **cinematic**: deep recession, a distant temple, a path vanishing toward it. Beautiful, but only 3–4 nodes are legible.
- **Reference A** (the labelled night-forest with Temple of Brahma, Serpent Grove, Lotus Pond, Ancient Ruins, Ascension Peak) is a **functional map**: shallow depth, wide lateral spread, every node visible and named at once, a visible path network, HUD baked into the corners.

The Forest of Mastery has to answer "where am I, what's next, what's left" at a glance. **That is reference A's job, not B and C's.** Build the map to A. Keep B and C's cinematic language for moments where recession is affordable:

- the load-in camera move (start on the vista, settle into the map framing)
- the grove-entry transition
- the Journey / Dashboard hero image
- an empty-state or milestone celebration

The current build has B/C's camera doing A's job, which is why it looks atmospheric and reads as useless.

---

## 1. Camera and composition — REVISED

**Target: a wide, shallow, near-orthographic diorama panel.** Think stage set, not landscape photograph.

- Camera **35–50 units above** terrain, pitched down **22–30°** (shallower than v1's 28–38° — reference A is flatter than I first specified).
- FOV **30–36°**, or go **fully orthographic**. Orthographic is worth testing seriously: it removes perspective distortion at the frame edges, keeps distant groves at readable scale, and is what makes reference A feel like a *map*. Your current wide-FOV perspective is why edge trees smear and the middle of the frame is empty grey.
- **Horizon at ~22–28% from the top.** Sky is a thin band, not a third of the image.
- **Spread groves laterally, not in depth.** Currently the layout runs away from the camera, so far groves are tiny and occluded. Reference A places nodes across the width at similar apparent scale, using small elevation steps and overlapping foliage for depth instead of distance.
- **The foreground grey plane must go.** In screenshots 1, 5 and 6 the bottom 30% is empty grey terrain. Fill it with the foreground framing layer (§6) — dark ferns, rocks, a branch — or crop it out with the camera.

**Hard requirement:** the default framing shows **all 7 groves, all labelled, no occlusion.** Fit-to-bounds on load with ~12% padding. If a grove is hidden behind a tree, the layout is wrong, not the camera.

**Constrain the camera.** Free orbit is how a good scene gets framed badly by the user. Limit yaw to ±20°, pitch to ±8°, and offer "wander mode" as a separate, deliberate secondary state.

---

## 2. Lighting

Nothing currently casts a shadow. In order:

1. **Key light** — directional, warm `#FFD9A0`, from behind and above the temple, intensity ~1.8–2.4. Backlighting is what gives reference trees their golden rims and dark undersides. This is the single change that makes trees stop looking like blobs.
2. **Sky fill** — `HemisphereLight`, sky `#3A2F6B` → ground `#16403A`, intensity ~0.5. Puts *colour* in the shadows instead of grey.
3. **Separation rim** — dim cool directional from camera-left, `#7FD8D0`, intensity ~0.35, so overlapping midground canopies don't merge into one mass.
4. **Local point lights** at each grove node and lantern — warm amber, tight falloff, pooling visibly on the ground.

**Shadows:** `PCFSoftShadowMap`, 2048–4096, tight ortho frustum. Trees cast onto terrain and onto each other. Without this, nothing else in this document will save the render.

**AO:** SSAO/GTAO, or bake vertex AO into the tree meshes and darken terrain vertex colours under canopy clusters.

**Tone mapping:** ACESFilmic or AgX, exposure **0.85–1.0**. The current output looks unclamped.

---

## 3. Tree geometry and silhouette

Replace the single icosphere-on-a-stick with **6–8 archetypes** with genuinely different outlines:

| Archetype | Silhouette cue | Use |
|---|---|---|
| Banyan | Wide crown, hanging aerial-root strands | Hero grove nodes |
| Peepal / bodhi | Slender trunk, heart-leaf cloud, slight lean | Temple-adjacent groves |
| Weeping willow | Drooping fronds, twisted low trunk | Water-side groves |
| Broad oak | Heavy horizontal branching, flat wide canopy | Gateway / guardian groves |
| Conifer spire | Tall narrow triangle | Distant ridgeline backdrop only |
| Sapling | Thin, sparse, small | Locked concepts |
| Bare | Branch structure, no foliage | Locked concepts |
| Shrub | Low round mass | Density filler, LOD-swapped |

- **Hero trees 2.5–4× filler height**, with visible branch geometry. Right now a grove node and a background tree are the same object at different scales, which is the root of the "which one do I click" problem.
- **Foliage as 3–7 overlapping clustered volumes** with per-instance rotation, not one closed mesh. Alpha-cutout leaf cards for anything near-camera.
- **Trunks:** the current orange-tan (~`#C8865A`) is too saturated and too uniform, and it's one of the loudest "programmer art" tells in the frame. Go desaturated brown-violet, `#4A3A44` shadow → `#8A7060` lit, ±4% per-instance hue jitter.

---

## 3b. Canopy colour as grove identity — NEW, high value

This is the most valuable single idea in reference A and it is completely absent from the current build.

In reference A, each grove has its own canopy hue — gold, teal, emerald, violet, amber. You can tell the groves apart, count them, and locate the one you want **before reading a single label**. Colour is doing information work, not decoration.

Right now every tree in your scene is the same olive-black, so the map has exactly one visual variable (brightness) carrying both "which grove is this" and "what state is it in" — and it can't carry both.

Assign each of the 7 groves a signature canopy hue:

```
DSA              emerald    #2E7D5B
Systems Design   teal       #2A7D8C
Math / Stats     violet     #6B4C9A
ML Theory        gold       #B8893A
Concurrency      copper     #A85C3C
Databases        jade       #3E8C6A
Interview Prep   plum       #7A3F63
```

Rules:
- Filler trees stay neutral dark (`#1B3A34`) so hero canopies pop.
- Within a grove, vary the signature hue ±8% in value and ±5° in hue across the concept trees so it reads as a *stand of related trees*, not seven flat-shaded copies.
- Reserve **gold** for the mastered state and **teal glow** for available — so grove identity and node state stay on separate channels (hue vs. glow/emissive).

**Also fix:** the white/frosted trees in screenshots 1, 5 and 6 read as snow-covered, which is jarring against a warm jungle-ashram world. If that's the "mastered" state, it's the wrong colour — mastered should be **golden-canopied and blossoming**, as in every reference. If it's just bloom clipping, see §7.

---

## 4. Scattering, terrain, ground contact

**Ground contact is broken** — several trees appear to hover, and every trunk meets the ground on a hard clean line.

- Raycast every instance down to terrain, snap Y with a **small negative offset** (~0.15) so trunks sink slightly.
- Add a **root flare** (slightly wider cone at the base) plus 4–8 grass/fern cards ringing every trunk. This hides the intersection and is doing enormous work in all three references.
- Darkening decal or vertex-colour multiply in a small radius under each tree.

**Scattering:**
- **Poisson-disc with clustering** — trees should form *stands* with real clearings. The current even random scatter is why the midground reads as noise.
- Density **falls off near the path and near grove nodes**, **rises toward frame edges** to form natural framing.
- Per-instance rotation, non-uniform scale 0.85–1.3, lean ±6°.

**Terrain:**
- Currently near-flat with one shallow ridge, reading as a grey plane. Drive it from a heightmap or layered simplex noise with real elevation change.
- Add a **ground scatter layer**: grass tufts, ferns, rocks, mushrooms, fallen logs, flowering plants. The references are *dense* at ground level; your screenshots have vast empty grey.
- Add **water** — a pond or stream. Reference A has both a lotus pond and a waterfall; reference C has a reflecting pool. Reflection is a cheap, enormous depth cue.

---

## 5. Colour palette — REVISED

Kill the neutral grey. Every neutral surface in the current render is desaturating the whole image.

```
--forest-shadow      #101C2B   deep indigo — darkest value, never black
--forest-canopy-dark #1B3A34   filler canopy in shadow (teal-green, NOT olive-black)
--forest-canopy-lit  #4E7A56   canopy catching key light
--forest-ground      #1E3B3A   terrain base — saturated teal, NOT grey
--forest-ground-lit  #6E7F5C   terrain in light — warm sage
--path-glow          #EAD9A8   luminous path
--accent-gold        #E8B44F   lanterns, mastered state, temple
--accent-teal        #6FD8C6   available state, spirit wisps, path network
--accent-magenta     #C86BA8   flower accents, used sparingly
--sky-high           #241A45   upper sky
--sky-horizon        #6B5A8C   horizon, warming to gold toward the temple
```

- **Shadows are blue-violet, never grey or black.** Biggest palette difference from all three references.
- **Clamp the range** — darkest ~`#0D1520`, lightest ~`#F4EBD6`. Nothing hits pure black or pure white.
- **Warm/cool split:** warm near temple and path, cool in the deep forest. That temperature contrast carries most of reference B's depth.
- Magenta/pink is **rare** — 5–8 instances in the whole frame, as sparkle.
- Layer the **grove signature hues from §3b on top of this base** — the base palette is the world; the signature hues are the content.

---

## 6. Atmosphere and depth layering

Build **six explicit planes**, each lighter, cooler and lower-contrast than the last:

1. **Foreground frame — completely missing today.** Dark near-silhouette, unlit, slightly blurred: an arching branch across the top corners, ferns and rock in the bottom corners, hanging vines. All three references have this proscenium and it's a large part of why they read as composed rather than screenshotted. Render at ~15% brightness, out of focus. **This also solves the empty grey foreground problem in §1.**
2. Near foliage — full contrast and saturation.
3. Hero trees / grove nodes — the focal band.
4. Midground stands — 60% contrast, fog beginning.
5. Distant hills — 25% contrast, heavily fogged, cool.
6. Temple + sky — light, warm, glowing.

**Fog:** `FogExp2`, tuned so the far ridge desaturates *into* the sky colour. Tint warm gold within a radius of the temple, cool indigo elsewhere.

**Mist:** 3–5 large low-altitude alpha planes, slowly drifting. Hides the hard terrain/sky seam currently visible in screenshots 1, 5 and 6.

**Light shafts** from the temple direction — radial-blur god-ray pass, or cheap additive cone geometry with a soft gradient. Reference C uses these prominently.

**Sky:** currently a flat purple gradient with visible banding and nothing in it. Add a **crescent moon, stars, and soft cloud banding** (reference A). Cheap, and it instantly reads as a night world rather than an empty backdrop.

---

## 7. Bloom, glow, and the temple

**Bloom is the most obviously broken post effect.**
- `threshold` → ~0.85 (currently appears near 0), `strength` → ~0.35–0.5, `radius` → ~0.6.
- **Emissive must be coloured, never pure white.** Amber `#E8B44F`, teal `#6FD8C6`. White emissive is why the temple is a featureless slab and the mastered trees look snow-covered.
- Emissive intensity low enough that **surface detail survives inside the glow**.

**The temple.** Currently a flat white blocky mass on a hard rectangular slab, floating with no terrain connection. Two valid treatments:

- **Vista treatment** (references B/C): rebuild as a proper shikhara/pagoda — stepped tiers, multiple spires of varying height, gateway arch, plinth with steps. Warm gold with real light and shade, glow *behind* it as a halo so architecture reads as dark-to-gold against bright sky. Push it further and scale it up. Occlude the base with mist so it never shows a ground seam.
- **Map treatment** (reference A): a smaller, jewel-like golden shrine sitting *within* the map as the final node, with an ornate icon medallion and a label. Less cinematic, more legible.

Given §0.5, **the map treatment is probably right for this screen** and the vista treatment belongs in the load-in animation and the Journey hero.

Either way: subtle pulse, 0.5–1.5% scale or emissive breathing on a ~6s cycle.

---

## 8. Particles, life, and scale

**Current particles read as a snowstorm** — uniform white dots, uniform size, uniform distribution across the whole frame.

- **Fireflies:** varied size (0.4–1.6×), varied colour (amber, pale green, cyan), individual flicker with random phase, slow Perlin drift, **density clustered near light sources and the path** rather than filling the frame.
- **Spirit wisps:** 3–6 larger slow motes with soft ribbon trails, drifting along the path.
- **Petals / leaves:** a few alpha-card leaves tumbling with rotation.
- **Fauna:** 2–4 animated birds or butterflies on looping splines. All three references have visible life — peacocks, birds, glowing hummingbirds. Even 4-frame billboarded sprites will do it.

**Add a player avatar.** References B and C both place a small glowing figure on the path. Nothing in your current render establishes scale, which is a major reason it feels like an abstract diagram. A small silhouetted figure with a lantern at the current position fixes scale, answers "where am I", and gives the composition a focal anchor.

---

## 9. Node design and labels — REVISED

The current markers look like debug gizmos: a plain white torus and an untextured white ring.

**Design each node as a shrine:**
- Carved stone **pedestal/plinth** the tree grows from
- **Engraved ring decal** in the terrain — a mandala/rangoli texture, not a wireframe torus
- **Hanging diya or lantern** on a branch (you already have these — they're the best-looking thing in the current render, lean into them)
- **Soft vertical pillar of light** for the active node, low opacity, slowly rotating

**Icon medallions — new, from reference A.** Every node in reference A carries a small circular gold-rimmed medallion with a glyph inside (lotus, flame, leaf, serpent). It sits above the tree and is the actual click target. This solves three problems at once: it gives a consistent hit-target regardless of tree shape, it works at any zoom, and it lets you encode state in the medallion's rim while the canopy carries grove identity.

**Labels must be permanently visible — this is the biggest functional gap.** Right now grove names only exist inside click popups (screenshots 2 and 6), so the map tells you nothing until you interact with it. Reference A labels every node all the time and still isn't cluttered, because labels sit in the dark bands *between* canopies.

- Billboarded **CSS2DRenderer / DOM labels**, not textures in the scene
- App serif face, letterspaced small caps, soft dark gradient plate behind
- Fade opacity with distance; hide on heavy overlap with a simple collision pass
- Mark the current node **"YOU ARE HERE"** in accent teal, exactly as reference A does
- Don't imitate the references' garbled lettering — that's an AI-generation artifact, not a style

**State encoding must be legible without clicking:**

| State | Canopy | Medallion | Ring | Label |
|---|---|---|---|---|
| Mastered | Grove hue + gold blossoms, particles rising | Solid gold, filled glyph | Solid gold engraved | Full opacity |
| Current focus | Grove hue, brightest, amber pillar of light | Gold, pulsing rim | Pulsing gold | "YOU ARE HERE", teal |
| Available | Grove hue, moderate, soft teal glow | Teal rim, outline glyph | Thin teal | Full opacity |
| Locked | Bare branches, frost-blue, ~40% scale | Dim grey, no glyph | Broken/faded | 40% opacity |

---

## 10. The path — expanded

The path is currently a flat pale ribbon that gets lost in the grey. In all three references it's the primary structural element, and in reference A it's an explicit **graph**.

- Make it **emissive** with gentle animated flow (scrolling UV or a shader gradient), bloomed lightly.
- **S-curve routing** between nodes; taper width with distance.
- **Show the topology.** Reference A draws visible glowing threads between nodes with small bead-markers along each edge. Your groves have prerequisite relationships (screenshot 6's popup shows "builds on: Arrays & Hashing / unlocks next: Dynamic Programming") — that structure should be drawn on the map as connecting paths, not hidden in a popup.
- **Style the edges by state:** solid gold for traversed, glowing teal for available-next, dim dashed for locked.
- Grove nodes sit as **bright pools directly on the path**, so the eye can walk the whole progression without interruption.

---

## 11. Grove interior view (screenshots 2 and 4) — needs its own pass

The drilled-in view is currently *worse* than the overview: one lonely tree in a sea of identical dark blobs, and there's no way to tell which trees are concepts.

- **Cut background tree count by ~70%** inside a grove. They're set dressing and they're currently competing with the content.
- **Make the 4 concept trees enormous** — 30–40% of frame height — with distinct archetypes per concept.
- **Arrange them along a readable path in dependency order**, so "builds on → unlocks next" is visible spatially rather than only in the popup.
- **Draw dependency edges** as glowing root or vine connections along the ground between concept trees. This is the single highest-value change to the grove view — it turns decoration into information.
- Apply the grove's **signature canopy hue** (§3b) throughout, so entering a grove feels like entering somewhere specific.

---

## 12. Render quality — expanded

- **Anti-aliasing:** visible stair-stepping on the temple edges and path. If you're using `EffectComposer`, `antialias: true` on the renderer does nothing — add an `SMAAPass` or render to a multisampled target.
- **Pixel ratio:** `min(devicePixelRatio, 2)`; make sure you aren't pinned at 1.
- **Vignette:** subtle — the foreground frame geometry should do most of this work.
- **Film grain:** ~2–3%. All three references have painterly texture; clean digital gradients read as cheap.
- **Chromatic aberration:** ~0.5px at frame edges, sparingly.
- **Depth of field:** focus the midground focal band, blur the foreground frame and far distance. If full DOF is too costly, pre-blur the foreground frame textures.

---

## 13. UI, chrome, and layout — REVISED

**Full-bleed the canvas.** The 3D scene currently sits in a rounded box with a hard border, floating in a much darker page. It reads as a window into a screensaver rather than a place. Let it fill the content area and fade into the chrome with an edge gradient mask.

**Make the HUD diegetic** (reference A). Right now `penalty on / Timer / Wrap up / GLM` are utility chips in a dark bar above a mythic forest — a total tonal mismatch. Reference A puts its HUD *in* the world: compass rose top-left, currency counters top-right, control hints along the bottom, all in the scene's own gold-on-dark ornamental language.

- **Compass rose** in a corner, in the app's Indic ornament style (reference A and B both have one)
- **Minimap** top-left showing all 7 groves and current position (reference B) — this also hedges the "can't see everything at once" problem when zoomed in
- **Legend** for node states, small, in a corner
- **Restyle the zoom stack** — the `← + − ↺` column reads as debug UI. Small circular brass-rimmed buttons, or remove it entirely in favour of scroll-zoom plus a single "reset view" affordance.

**Mobile (screenshot 3) is the worst offender.** The header consumes ~40% of the viewport across three stacked rows, leaving the map a narrow slice, and the info card then covers a third of what's left. Collapse to a single row — logo, streak, overflow menu — let the map fill the screen, and float the overlay chips over it rather than stacking bars above it. On mobile the diorama camera from §1 matters even more, since there's no room for a foreground/midground/background vista.

---

## Suggested order of work

1. Decide vista vs. map (§0.5), then camera + FOV + default framing (§1)
2. Lighting, shadows, tone mapping (§2)
3. Palette swap, especially killing the grey ground (§5)
4. **Grove signature canopy colours (§3b)** — cheap, high impact, mostly a data change
5. **Permanent labels + icon medallions (§9)** — turns the map into a map
6. Bloom/emissive fix + temple rebuild (§7)
7. Foreground framing layer, fog, mist, sky (§6)
8. Path as visible graph (§10)
9. Tree archetype library (§3)
10. Scattering, ground contact, ground scatter (§4)
11. Grove interior pass (§11)
12. Particles, fauna, avatar (§8)
13. Render polish (§12), UI and chrome (§13)

Steps 1–5 are where the perceived quality jump lives, and none of them require new 3D assets. Steps 7, 9 and 10 are the labour-intensive ones and can be staged.

---

## One caution about the references

All three are painted or AI-generated illustrations. They get much of their depth from hand-painted atmospheric perspective and brush texture that no real-time renderer reproduces literally — and reference A's apparent density is partly painted detail that would cost you thousands of draw calls.

Don't chase fidelity. Chase **composition, value structure, colour-temperature split, silhouette variety, and colour-as-information**. All five transfer completely to a low-poly stylized renderer. A well-lit, well-composed low-poly scene reads as a deliberate style; a badly-lit detailed one just reads as broken.
