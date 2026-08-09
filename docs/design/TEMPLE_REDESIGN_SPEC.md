# Destination Temple Redesign — "Indian temple with deities"

> User directive (2026-08-03): the map's goal temple "doesn't look like an Indian temple with
> Indian deities." Rebuild `paintTemple()` in `forest2d.js` (currently an abstract 3-spire gold
> shikhara at lines ~487–594) into a recognizable Hindu temple complex WITH figural deities.
> **APPROVED CONCRETE DESIGN (2026-08-09): port `docs/design/temple_final.html`** — "Svarga-Dwāra,
> the Golden Gate of the Gods." The user reviewed the playground and chose this specific composition:
> a Puri-style *deul* (`spireD` + ribbed `amalaka` stack + Nila-`chakra` + streaming `longFlag`),
> Siddhivinayak `clusterSpire`s, Meenakshi `gopuram`s with stone-carved niches, an Angkor colonnade
> gallery wall of `reliefPanel` devatās, and the great gate with a **darshan sanctum** (seated
> `deity`, `flames`, `garland`, dvārapāla `stoneFig`s). Reproduce this architecture — the six
> playground variants are superseded by this file.
>
> `fix_frontend` has merged; `forest2d.js` is free to edit (integration HEAD 5be9b6c).

## ⛔ HARD CONSTRAINT — no cursor-follow / parallax on the temple (user bug report 2026-08-09)
In `temple_final.html` the pointer-parallax loop (lines ~425–432) eases every layer — including the
temple's `mid` group — toward the cursor, so the whole temple visibly slides left/right/up/down on
hover. **The user dislikes this. Do NOT port that behaviour.** The ported temple must be
POSITION-STATIC: no `pointermove`/`getBoundingClientRect` cursor tracking, no per-layer translate
toward the cursor. (The forest map already runs without parallax — `wireParallax` was removed.)
Also drop the click-to-offer-dīya handler (it would collide with grove clicks on the real map).
KEEP all ambient, non-cursor motion: diya/flame flicker, rising motes, waving flag, turning chakra,
apsara drift, water ripples, twinkling stars — all still gated behind `prefers-reduced-motion`.

## Silhouette (top-center goal, replaces the current wide 3-trapezoid stack)

```
          ╱▲╲        shikhara sanctum tower (Nagara) rising BEHIND,
         ╱███╲       curvilinear beehive profile, amalaka disc + kalasha
        ╱█[☺]█╲      finial on top; one deity murti in an upper niche
       ╱███████╲
   ▲  ╱█████████╲
 ╔═╧═╗───────────   GOPURAM gateway (Dravidian) IN FRONT — tapering
 ║☺⛊☺║              rectangular tower, 4–6 receding tiers, each tier a
 ╔╝☺⛊╚╗             ROW of small deity murtis in niches (the "deities")
 ║☺⛊☺⛊║             topped by a barrel-vaulted shala roof + row of kalasha
 ╔╝⛊☺⛊╚╗            pots along each cornice
 ║ ▓▓ॐ▓▓ ║           sanctum doorway at the base with the glowing idol
═╩═══════╩════════   plinth + steps + flanking dvarapala guardians + diyas
```

## Required elements
1. **Gopuram (front tower)** — 4–6 stacked tiers, each narrower than the one below (tapering),
   each cornice edged with a row of tiny **kalasha pot** finials. Every tier carries a horizontal
   **ROW of deity murtis** in shallow niches — small seated/standing figures (head + halo + body
   suggestion at map scale; on-palette gold/ember with subtle colour accents). Barrel-vaulted
   **shala** roof crowning the top with a row of larger kalashas.
2. **Shikhara (rear sanctum tower)** — Nagara curvilinear (beehive) profile rising behind/above
   the gopuram so both read; **amalaka** ribbed disc + **kalasha** finial on top; one deity murti
   in an upper gavaksha (kudu) niche.
3. **Deity idol in the sanctum** — a seated **murti** silhouette (crown/mukuta + halo/prabhavali
   arch + folded posture) glowing warm gold in the doorway; this is the visible "deity."
   Keep the progress-gated gate: shut/dim when far, idol-glow strengthening, gate OPEN + idol
   blazing at full mastery (reuse the existing `pct`/`gateOpen` logic).
4. **Dvarapala guardians** — two standing guardian figures flanking the sanctum doorway
   (mace/club posture), small but readable.
5. **Keep the working diegetic dressing**: marigold toran garland, flanking diyas (dusk/night
   boost), divine sunburst + slow nimbus aureole + templeGlow, god-rays, progress-driven luminance.

## Mood — divine, mythological, enchanted (user's core emphasis)

The complex must not merely be *architecturally* an Indian temple — it must feel **divine, godly,
and enchanted**, like a mythological abode of the gods (Kailasa / a swarga-loka shrine), the sacred
climax the whole journey climbs toward. Concrete treatments (all procedural, deterministic,
reduced-motion-safe, perf-bounded):

- **Radiant halo of godhood** — the sanctum idol sits inside a **prabhavali** (flaming arch aureole)
  with a soft breathing glow; a slow-turning nimbus of fine rays already exists — bias it warmer and
  let the idol cast a visible shaft of light down the entrance path (the goal literally lights the way).
- **Divine sunburst behind the shikhara** — the existing `divineG` sunburst reads as the deity's
  aura; make it feel like dawn breaking behind the tower (sacred backlight, gods emerging from light).
- **Floating sacred motes / golden fireflies (divya-jyoti)** drifting up around the towers — a few
  slow rising sparks of warm light, like blessings/embers ascending. Gate behind `reduced`.
- **Apsara / celestial touch** — one or two faint winged/flying celestial silhouettes (or hamsa —
  sacred swans) circling high near the shikhara, very subtle, to signal a heavenly realm. Keep tiny
  and non-distracting.
- **Sacred iconography woven in** — ॐ already present; add restrained **trishula / chakra / lotus**
  glyphs and a **kalasha-lined** skyline so the silhouette reads unmistakably sacred-Hindu, not
  generic-oriental.
- **Enchanted light, not flat gold** — layer warm gradients so the stone looks lit-from-within
  (temple as a lantern of the divine), with the gopuram tiers catching graded light top→bottom.
- **Progress = ascension to the divine** — far from mastery the temple is a distant, dim, mist-veiled
  silhouette (a mystery on the horizon); as `pct` rises it warms, the mist parts, the idol brightens,
  the motes multiply; at full mastery it BLAZES — gate open, idol radiant, sunburst full, a moment of
  darshan. The emotional arc is "climbing toward the gods."
- **Mythic scale cues** — the complex should feel monumental relative to the groves (it's the abode of
  the gods, not a roadside shrine) without occluding nodes/labels/path.

Guardrails: everything above stays deterministic-from-data, reduced-motion-safe (static frame must
still read as a divine temple), perf-bounded, on-palette, and never obscures groves/labels/path.

## Constraints (do not regress)
- **Procedural + deterministic** from data; no external images; pure SVG via the existing `el()` helper.
- **Progress-responsive** exactly as today: `pct` = blossoming/total; `lum`, gate open/shut, idol glow,
  sunburst all scale with it. At full mastery the whole complex blazes.
- **Reduced-motion safe** — all new motion gated behind the existing `reduced` flag; static frame legible.
- **Perf-bounded** — deity rows are many small elements; cap murti count per tier (~5–7) and reuse a
  single `murti(parent,x,y,s)` helper; no per-figure filters. Keep it one `<g>` subtree.
- **Legible at map scale AND when small** (onboarding 1-node map → full 22-node map). The complex must
  not overpower the groves; it's the horizon goal, not the subject.
- **On-palette** — gold/goldBright/goldDeep/ember + the sacred warm set already in `C`; add at most a
  couple of restrained accent hues for the murtis (e.g. a vermilion + a jade) so "deities" read as
  colourful without clashing with the indigo→dawn sky.
- Anchor at the same `tp = {x: VB.w*0.5, y:116}` origin; keep the footprint within the current band so
  the perspective funnel / band foliage / god-rays still compose.

## Acceptance
- A viewer instantly reads "Hindu temple" and can see **deity figures** on it (gopuram tiers + sanctum idol).
- It feels **divine / mythological / enchanted** — a sacred, godly destination, not a flat gold building.
- Renders identically across reloads (deterministic); reduced-motion gives a clean static complex.
- No node/label/path occlusion; onboarding and full-map both look intentional.
- Screenshot both the far (low pct) and near-complete (high pct) states to /tmp for review before merge.
