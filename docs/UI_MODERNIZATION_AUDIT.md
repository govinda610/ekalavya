# Ekalavya — UI Modernization Audit

**Goal:** make the web app as beautiful as — and more modern than — its own reference
design template **Option E** (`docs/design/E_merged/index.html`), carrying Option E's
elements over as literally as possible.

**Method:** full-page Playwright screenshots (chromium `channel="chrome"`, headless,
`device_scale_factor=2`) of (a) the Option E template and (b) every app surface, served
on port 4711 with a throwaway `EKLAVYA_DATA_ROOT`. Screenshots in `/tmp/ui_audit/`.

**Key finding:** the design *system* (`static/eklavya.css`) already contains Option E's
hero classes **verbatim** (`.hero`, `.hero-scene`, `.hero-copy`, `h1.eka`, `.eka-deva`,
`.hero-sub`, `.hero-meta`, `.scrollcue`, the whole cinematic scene + JS). The app chrome
(SPA views) is already high-fidelity to Option E. The one big regression is the **public
landing (`/welcome`) and the shared auth hero**, which were rewritten with a stripped-down
`.land-*` layout that threw away Option E's grandeur: no giant gold wordmark, no Hindi
line, no full poetic tagline, no four chips, no "enter the forest" cue.

Priorities: **P0** = restore Option E hero fidelity on `/welcome`; **P1** = auth pages
share the same weak hero; **P2** = minor polish on already-good SPA views.

---

## Screenshot index (`/tmp/ui_audit/`)

| File | Surface |
|---|---|
| `optionE_full.png`, `optionE_hero.png` | Option E template (gold standard) |
| `welcome_before.png`, `welcome_before_hero.png` | `/welcome` — before |
| `welcome_after.png` | `/welcome` — after the port (deliverable 3) |
| `login.png` / `signup.png` | auth pages |
| `spa_practice.png` | SPA · Arena / practice |
| `spa_dashboard.png` | SPA · Dashboard |
| `spa_journey.png` | SPA · Journey |
| `spa_effectiveness.png` | SPA · Effectiveness |
| `spa_forest.png` | SPA · Forest map |
| `spa_library.png` | SPA · Library |
| `spa_settings.png` | SPA · Settings |
| `spa_profile.png` | SPA · Profile |

---

## Option E hero — the target (what we must reproduce)

- **Cinematic eyebrow** in mono, wide-tracked, teal — a "THE MERGE — CINEMATIC FOREST"
  feel (we drop the literal `DIRECTION E ·` template-picker label).
- **GIANT gold-gradient `EKALAVYA` wordmark**: Cinzel 900, `clamp(52px,10vw,128px)`,
  `line-height:.9`, gold vertical gradient (`#fff6df → gold-bright → gold → gold-deep`)
  clipped to text, soft gold glow. This is the single anchor of the page.
- **Hindi line** `एकलव्य · स्वाध्याय` (Tiro Devanagari), just under the wordmark.
- **Full poetic tagline** (Cormorant italic, `max-width:64ch`): *"The hall was closed to
  him — so he walked into the forest, raised a statue of the guru who refused him, and
  taught himself to outshoot the princes. An AI coding tutor for the self-taught, the
  boundary-crossers, the ones told they couldn't be taught."* with `<b>` gold emphasis.
- **Four chips** (mono, bordered): `GURU: THE STATUE` / `ARENA: THE FOREST` /
  `PATH: SVĀDHYĀYA · SELF-STUDY` / `DAKSHINĀ: THE THUMB`.
- **`↓ ENTER THE FOREST`** scroll cue, bobbing, bottom-centered.
- **Scene**: full-bleed cinematic forest (archer + clay Droṇa + spinning sun + target),
  `preserveAspectRatio="xMidYMin slice"` — anchored to the **top**, ~62vh band, copy
  pinned to the bottom (`justify-content:flex-end`), all on ONE flat `#101528` indigo.

---

## Per-surface gaps

### 1. `/welcome` (public landing) — **P0, the main regression**

Before (`welcome_before.png`): a top nav bar, a smallish Cinzel headline "THE HALL WAS
CLOSED TO HIM / SO HE TAUGHT HIMSELF…", a **duplicated static mini-scene** in a bordered
box on the right, a two-button CTA row, three proof stats, then three feature cards.

Gaps vs Option E:
- **Missing the giant gold wordmark.** The word EKALAVYA appears only tiny in the nav.
  Option E makes the wordmark the hero anchor at ~128px. → **Fix:** use `<h1 class="eka">`.
- **Missing the Hindi `एकलव्य · स्वाध्याय` line.** → add `.eka-deva`.
- **Tagline is truncated & split into a headline + lead.** Option E keeps ONE flowing
  poetic sentence. → restore the full `.hero-sub` copy verbatim.
- **Missing the four GURU/ARENA/PATH/DAKSHINĀ chips.** → add `.hero-meta`.
- **Missing "↓ ENTER THE FOREST".** The old cue said just "↓ enter". → restore verbatim.
- **Boxiness / duplication:** the right-hand `.land-art` bordered box re-draws a second,
  smaller, *static* archer scene competing with the fixed animated one behind. Reads
  dated and redundant. → drop it; let the single full-bleed animated scene carry the art.
- **Scene sizing/anchor:** old landing pins the shared scene as a full-viewport `fixed`
  background (`xMidYMid slice`, centered) behind everything, heavily scrimmed — you barely
  read it. Option E gives the scene a dedicated top band (`xMidYMin slice`, top-anchored)
  so more of it is visible and it sits *above* the copy, not dimmed behind it. → adopt the
  `<header class="hero"><div class="hero-scene">…</div><div class="hero-copy">…` structure.
- **Typography scale:** headline ~58px vs Option E 128px; the page reads like a generic
  SaaS hero, not the cinematic wordmark statement. → the wordmark fix resolves this.

Concrete modern fix: **rewrite the hero block to Option E's exact markup** (already CSS-ready
in `eklavya.css`), keep the app-appropriate feature/method cards below the fold (those are
legit marketing content Option E doesn't have — Option E's below-hero content is a design
spec sheet, not app copy). Nav can stay but should not compete with the wordmark.

### 2. `/login` & `/signup` — **P1**

Share the same stripped hero as the old landing: a small inline `EKALAVYA` (Cinzel ~54px
in `.hero-brand`) + "the archer who taught himself" + a one-line truncated tagline, over the
full-viewport dimmed scene, with the glass auth card below. The glass card itself is clean
and modern. Gaps: same missing grandeur (no giant wordmark, no Hindi, no full tagline, no
chips). **Not in scope for this run** — flagged for the next pass. Fix will mirror the
landing hero, then float the glass auth card.

### 3. SPA · Arena / practice (`spa_practice.png`) — **P2, already strong**

Faithful to Option E's practice mockup: left ashram rail (Arena/Forest/Library + Progress
group), top HUD strip (chats/editor/penalty/timer/wrap-up + level medallion), Pithora-paper
guru bubble, editor pane with line numbers, gold Send. Minor: onboarding answer chips at
bottom-left of the bubble are a touch cramped; the top HUD button row is slightly busy. No
structural gap.

### 4. SPA · Dashboard (`spa_dashboard.png`) — **P2**

Strong: level medallion ring, "TODAY'S QUEST" banner, "The illusion of knowing" calibration
card, skill-map + skill-axes columns. Matches Option E's HUD/quest/heatmap vocabulary. Minor:
the empty-state rows ("No skills yet", "no reviews due") are a little flat/boxy; could use a
lighter empty-state treatment. Not a fidelity loss.

### 5. SPA · Journey (`spa_journey.png`) — **P2**

Strong: gold "YOUR JOURNEY" title, six stat cells, Milestones, Achievements grid with locked
badges, Activity heatmap + XP-over-time. On brand. Minor: achievement tiles read slightly
uniform/boxy; locked vs earned contrast could be stronger.

### 6. SPA · Effectiveness (`spa_effectiveness.png`) — **P2**

Strong: "AM I GETTING BETTER?" gold header, benchmark/unaided/dependency-gap/Elo cards, honest
empty states. On brand. Minor: several empty cards stacked read a bit repetitive; fine for a
new account.

### 7. SPA · Forest map (`spa_forest.png`) — **P2**

Header + zoom controls + empty grove canvas ("No forest yet — finish onboarding"). The empty
canvas is a large flat gradient rectangle — reads a little empty/boxy pre-onboarding, but that
is expected for a fresh account; with data it renders the winding-path grove map. No gap.

### 8. SPA · Library (`spa_library.png`) — **P2**

"THE SCRIPTORIUM" title, filter chips (All/Lessons/Code/Visuals/HTML), search, empty state. On
brand and clean.

### 9. SPA · Settings (`spa_settings.png`) — **P2**

"SETTINGS" title, four setrows (cheat penalty, reduced motion, guru voice, provider) with
themed toggles. Clean, modern, on brand.

### 10. SPA · Profile (`spa_profile.png`) — **P2**

"MY PROFILE" title, Your profile / Goals / Mastery-map cards with empty states. On brand.

---

## Summary

- **One real regression:** the `/welcome` (and shared auth) hero lost Option E's giant gold
  wordmark, Hindi line, full poetic tagline, four chips, and "enter the forest" cue, and
  buries the scene as a dimmed background instead of a top-anchored cinematic band.
- **The design system already carries Option E's hero verbatim** — the fix is markup, not CSS.
- **SPA app chrome is already high-fidelity** to Option E; only cosmetic polish remains (P2).

## This run's action

Deliverable 2 rewrites `_LANDING`'s hero to Option E's exact `<header class="hero">` markup
(wordmark, Hindi, full tagline, four chips, scroll cue) using the shared, already-present
Option E hero CSS, keeping the animated `_hero_scene()` sized/anchored like Option E and the
CTA behavior unchanged (`/welcome` → app root → `/login` in multi-user mode). Auth pages, SPA
polish, and a new About page are deferred to later passes per the brief.
