# Ekalavya — Design-Fidelity Audit

**Date:** 2026-07-30
**Templates (source of truth):**
- `docs/design/Ekalavya-Template-v2.html` — PRIMARY (Claude-Design-polished full set, "Direction E · Merged / Cinematic Forest"). Supersedes E_merged and adds the guru-is-answering/streaming state, the live `.ed-tests` test-arrow panel, and the focus/affordance/review-chrome/disabled-state refinement layer.
- `docs/design/E_merged/index.html` — Option E (identical A–K screen structure; a subset of v2). Used only to confirm nothing in v2 is a regression from E.

**App implementation audited:** `src/eklavya/webapp.py` (`_INDEX` SPA arena, `_LOGIN`, `_LANDING`, `_CANVAS`), `dashboard.py`, `journey.py`, `profileview.py`, `report.py` (skill-tree), `static/eklavya.css`.

**Evidence:** live screenshots in `docs/design/app_shots/` (arena, dashboard, tree, canvas, landing, login, drawer, death/states, empty states — desktop + mobile) plus source reading. No app code was modified.

**Legend:** ✅ FAITHFUL · ⚠️ CHANGED (with justified/regression call) · ❌ MISSING

**Headline:** The shared design system (palette, fonts, gold-hairline frames, Pithora-paper guru bubbles, semantic mastery ramp gold/teal/vermilion/muted, film grain) is ported faithfully and consistently across every page. The **static/marketing/product-reference screens** (Landing, Login, Canvas scaffold) are near-verbatim ports of the template markup. The **data-driven product screens** (Dashboard, Journey, Profile, Progress) are faithful adaptations — same structure and semantics, wired to real data, plus one justified addition (the calibration / "illusion of knowing" card). The **live practice arena** diverges most: it drops the template's rank-ring HUD and left rail, keeps a legacy emoji HUD, keeps the literal "YOU DIED / Souls" copy the template explicitly re-themed, and treats Canvas as a separate non-wired scaffold rather than an in-arena Editor↔Canvas toggle. Several **components exist in CSS but are never instantiated** by the app (XP progress gallery, achievement toast, level-up ceremony, themed error card, dedicated Settings screen, mobile radial nav).

---

## Note on `static/eklavya.css`

`static/eklavya.css` is a **verbatim copy of the template's entire `<style>` block** — every component class (`.toast`, `.ceremony`, `.loss`, `.prog-gallery`, `.rank-ring`, `.setrow`, `.m-nav`, `.app-shell`, `.htab`, `.seg`, `.ed-tests`, …) is *defined*. It is loaded by `_LOGIN`, `_LANDING`, and `_CANVAS`. The arena SPA (`_INDEX`) and the Python-rendered pages (`dashboard.py`/`journey.py`/`profileview.py`) each **inline their own scoped CSS instead** and do not use most of those template class hooks. So a class being present in the stylesheet does **not** mean it is used — the audit below tracks what the app actually *renders*, not what CSS exists.

---

## A · KEY SCREENS

### Landing (`/welcome` → `_LANDING`) — ✅ FAITHFUL
Near-verbatim port of template A. Nav + brand bow-mark, outsider H1 ("The hall was closed to him / So he taught himself to outshoot the princes"), italic lead, dual CTA (Enter the forest / See the method), 197 · unaided · 17 proof stats, the archer-before-idol-under-sun illustration, and three varied-weight feature frames (`.feat.big` + two). Colours, fonts, gold discipline all match.
- ⚠️ Nav links are **The Method / Skill Forest / Manifesto** (3) vs template's **The Method / Skill Forest / Pricing / Manifesto** (4). "Pricing" dropped — justified (no pricing yet).
- Note: template's landing art is a static SVG (the animated shot-loop belongs to the design-doc hero band, not the landing screen), so the app's static illustration is faithful, not a regression.

### Auth / Login (`/login` → `_LOGIN`) — ⚠️ CHANGED
Left brand panel (archer with a fully-drawn bowstring, sun, stars, ridge, guru's-vow quote) and right form ("Welcome back, devotee" / "The forest remembers where you left the string" / email + password / "Sign in — draw the string") are a faithful port of template B.
- ❌ **Login/Signup tabs missing.** Template B has a `.auth-tabs` toggle (Log in ↔ Sign up, "Raise your own statue →"). App is login-only; no signup screen/route.
- ❌ **OAuth buttons missing.** Template shows "Continue with GitHub / Continue with Google" (`.oauth`). App has email+password only.
- Whether these are regressions depends on product scope (email/password may be the intended MVP); flagging as gaps against the template.

### Onboarding — ⚠️ CHANGED (justified)
Template C is a two-part screen: a cinematic **"Cross the threshold / प्रवेश"** hero, then a conversational intake on the guru's paper with a step-rail (`.onb-steps`) and one-tap answer chips (`.gchip`).
- The app has **no dedicated onboarding screen/route and no threshold hero, no step-rail, no answer chips.** Onboarding is delivered *conversationally inside the arena* (`mode='onboard'` kickoff; a résumé-upload bar appears — a nice touch not in the template). The conversational-intake *intent* is preserved; the framed threshold presentation and chip affordances are not.

### Practice Arena (`/` → `_INDEX`) — ⚠️ CHANGED (several regressions)
The core loop is present and on-theme (guru-on-Pithora-paper vs teal "you" bubbles, collapsible tool-trace, streaming reply with typing caret, inline run-output block, Monaco editor, mode `<select>`, New/Run/Submit, chats button, penalty toggle). Confirmed in `arena_desktop.png` / `state_stream_trace.png`.
Divergences from template D:
- ❌ **Left rail missing.** Template D has a `.p-rail` (Practice / Progress / Forest Map / Library / Settings + a mini-HUD showing name + "Vana-Dhanurdhara" title). The app has **no rail at all**; all nav is top tabs.
- ⚠️ **HUD is the legacy emoji readout, not the rank-ring.** App shows `🔥 <streak>  ⭐ Lv <n>  <Rank>  [thin xpbar]`. Template D's `.mini-hud` is a **radial rank-ring SVG** (`ringArcApp`, `stroke-dashoffset`) with a stylised flame glyph — the whole point of the template's "FIX: XP is no longer an emoji/bar" note. This is a **regression** against the template's central progress-indicator decision.
- ❌ **Live test-arrow panel (`.ed-tests`) missing.** Template D fills the editor pane below the code with per-test pass/fail "arrows" (2/3 strike, hint line). App's editor has no test panel; test results only appear as run-output text.
- ⚠️ **Editor↔Canvas segmented control replaced by an Editor show/hide toggle.** Template D's right pane has a `.seg` "▤ Editor / ✦ Canvas" tab control; app has a header "▤ Editor" toggle that just hides/shows the code column. Canvas is a separate route (see below), not an in-pane tab.
- ⚠️ **Header tabs differ.** App: Practice / Progress / Journey / Profile / Skill Tree. Template D htabs: Practice / Progress / Journey / Profile / Skill Tree / **Library**. No Library tab (see Artifacts Library).
- ❌ **Highlight-to-ask echo (`.art-echo`) not in the arena.** Template D shows a "◆ asking about a selection in the canvas" echo bubble in chat; not present.
- ✅ Bash-approval card — faithful (`state_approval.png`: "⏻ RUN THIS COMMAND?", command, why, Approve & run / Reject). Copy is upper-cased vs template's "◆ Run this command?" but structurally identical.
- ✅ AI-assistant panel — present in AI-enabled interview mode (`state_assist.png`): "AI Assistant — allowed here, but it's imperfect. Verify it.", you/bot bubbles, ask bar. Faithful; placement is top-of-right-pane rather than a standalone card, acceptable.
- ✅ Mode selector — faithful (`<select>`: Daily practice / Mock interview / AI-enabled interview / Take-home / First-time setup) — matches template D exactly.
- ✅ Arena loading/empty state — `arena_welcome_desktop.png`: bow-mark + "एकलव्य / Nock the first arrow / …drawing the bow…" + pulsing dots. Well-themed, matches template K's "Drawing the string…" loading spirit.

### Death / Loss overlay — ⚠️ CHANGED (regression)
App shows a full-screen vermilion overlay: **"YOU DIED"**, italic subtext, "Souls dropped: −<n> XP. Streak broken. Your code is untouched. Type your next answer yourself to reclaim your souls." + CONTINUE (`state_death.png`, `states_desktop.png`).
- ⚠️ The template **explicitly re-themes this away from Dark-Souls** to epic-not-punitive: headline **"YOUR AIM FALTERED / पुण्य क्षीण"** (`.loss`/`.death` `.dbig`/`.ddeva`), a stone-**cracks** SVG, and a gold **`.lmerit`** "merit lost" badge with the exact XP. The app kept the literal **"YOU DIED"** and **"Souls"** (Dark Souls) language the template was designed to replace — no Devanagari, no cracks SVG, no merit badge. The vermilion gradient, "code untouched" promise and Continue button are on-theme, but the headline copy + motifs are a **regression** against the template's intent.
- ⚠️ **Reclaim toast** — app shows "⚔ SOULS RECLAIMED +<n> XP" (`#reclaim`, `state_reclaim.png`). Template's reclaim toast is "◆ Merit reclaimed / +180 XP restored / The forest forgives the honest." Same mechanic; **"Souls" vs "Merit" copy** and glyph differ (regression, same root cause as above). Template's teal-bordered `.toast` styling is replaced by a simpler gold pill.

### Canvas / Artifacts (`/canvas` → `_CANVAS`) — ⚠️ CHANGED (justified stub)
Pixel-faithful **static** port of template E (`canvas_desktop.png`): Editor/Canvas seg control, artifact tabs (lesson · code · visual · html), a rendered markdown lesson with देवा subtitle + gold callout, the "Ask about this ✦" highlight-to-ask popover, and the interactive call-depth chart.
- ⚠️ **Non-functional scaffold** — the page's own footnote says "Full authoring wiring lands in a later task." Highlight-to-ask is a static popover (no real selection→ask flow); artifact tabs aren't wired; nothing saves.
- ⚠️ **Not integrated into the arena.** Template E's Canvas is the practice right-pane's second tab; the app serves it as a **separate `/canvas` route** not reachable from the arena's Editor toggle. Justified as a phased build, but currently a gap in the live product flow.

### Artifacts Library — ❌ MISSING
Template F is a full "Scriptorium" screen (searchable per-user collection, type-filter pills All/Lessons/Code/Visuals/HTML, a pinned/featured `.artcard.feat`, revisit counts). The app has **no library screen, no route, no Library tab, and no persistence of artifacts.** Entirely absent.

### Progress Dashboard (`/dashboard` → `dashboard.py`) — ⚠️ CHANGED (faithful + justified addition)
Confirmed `dashboard_desktop.png` / `dashboard_empty_desktop.png`. Faithful, data-driven port of template G, asymmetric bento:
- ✅ Today's Quest banner (vermilion eyebrow + sword icon, prescriptive weakest-skill quest, reviews-due meta). ⚠️ Minor: no `.qseal` target-medallion SVG and no right-side `+XP` reward number that template shows.
- ✅ Pillar × axis skill map with the exact gold/teal/vermilion/muted mastery ramp + legend — the anchor. Faithful.
- ✅ Per-axis mastery bars, ✅ Active quests (horizon tags long/med/short), ✅ Unaided-vs-AI gap with day-trend bars, ✅ Achievements badge grid, ✅ Chronicle table. All match template G.
- ⚠️ **Character block uses a circular level-medallion + horizontal xpbar + streak/xp chips**, not template G's **rank-ring** (`ringArcPdash` arc as the progress fill). The streak chip still uses a **🔥 emoji** (template retired emoji everywhere but the bow/skull). Close, but the progress-as-ring decision isn't honoured here either.
- ⚠️ **ADDED: "The illusion of knowing" calibration card** (clarity score ring, over/under-confident lean, Brier/bias, confidently-wrong count) — **not in the template**. This is the product's headline metric and a **justified data-driven addition**, on-theme (gold conic ring). Well-integrated.
- ✅ Empty state handled gracefully per-card ("No skills yet — run onboarding", etc.).

### Journey (`/journey` → `journey.py`) — ✅ FAITHFUL
Confirmed `journey_desktop.png`. Faithful, data-driven port of template H: 6-cell stat ribbon (Level / Rank / Streak / Total XP / **Clarity** [added, on-theme] / Skills strong), vertical milestone timeline with icon dots + connector line, achievements gallery showing **earned AND locked badges with progress bars** (matches template's earned-vs-yet-to-earn), the diya-lamp activity heatmap (12 weeks), and the XP curve. Icons are line-icons (template retired emoji — honoured here). Strong match.
- ⚠️ Minor: template's milestone dots vary the icon per event type in a decorated timeline; app's timeline is slightly plainer but structurally identical.

### Profile (`/profile` → `profileview.py`) — ✅ FAITHFUL
Confirmed `profile_desktop.png`. Faithful port of template I: rendered profile.md (view) with an Edit → mono `<textarea>` → Save/Cancel that writes straight back to profile.md ("saved ✓"), the exact active Goals with horizon tags + deadlines, and the Mastery map reusing the dashboard's coloured cells. Matches the template's view/edit + goals + mastery layout.
- ⚠️ Minor: template shows view and edit **side by side** as two device mockups for illustration; the app toggles in place (correct real-app behaviour).

### Skill Tree (`/tree` in arena → `report.py` Mermaid) — ⚠️ CHANGED (known; being rebuilt)
Confirmed `tree_desktop.png` / `tree_all_desktop.png`. **KNOWN GAP — the forest-map is being rebuilt separately (see `feat/forest-skilltree`); noted and moving on.** For completeness:
- ❌ Template J's **forest-map overview** (walkable groves as trees on a winding gold path, diya glow, MASTERED/LOCKED labels) is replaced by a flat **Mermaid boxes-and-arrows** graph.
- ❌ Template J's **single-track drill-in panel** (`.track-panel` with node-dots done/active/locked + XP per node) is also absent — the Mermaid graph is the only view.
- ✅ **Preserved:** the track-filter `<select>` (overview vs single pillar), the pillar-level "17 groves not 197 nodes" overview vs single-track drill-in split, and the **gold=mastered / teal=unlocked / muted=locked** semantic ramp (Mermaid classDefs). So the *information architecture and colour semantics* survive; only the *illustrated forest presentation* is lost.

### Chats Drawer — ✅ FAITHFUL
Confirmed `state_drawer.png`. Slides over the arena with a scrim, "Chats" header + ×, "+ New chat", and a history list (title + mode · timestamp, hover-reveal rename ✎). Matches template K's chats drawer.

### Settings — ❌ MISSING (mechanic partially present)
Template K has a dedicated Settings screen (`.setrow` rows + `.toggle`s): **Cheat penalty** (vermilion when armed), **Reduced motion**, **Guru voice**, **Provider**.
- The app has **no Settings screen/route/panel.** Only the **cheat-penalty** control survives, as a single header button ("☠ penalty on/off", `PUT /api/settings`). Reduced-motion, guru-voice, and provider-selection UI are absent. Provider is shown read-only in the arena header ("GLM · glm-…"). So the *most important* toggle exists but the Settings screen as designed does not.

### Empty / Loading / Error states — ⚠️ CHANGED
Template K draws three themed cards: **Empty** ("The forest is quiet" + archer SVG), **Loading** (spinner + skeleton "Drawing the string…"), **Error** ("The arrow found no wind" + Retry).
- ✅ **Loading:** arena welcome/loading is well-themed ("…drawing the bow…" + pulsing dots). Dashboard/journey/profile degrade with graceful per-card empty copy.
- ⚠️ **Empty:** handled as inline per-card muted copy rather than the template's dedicated illustrated "forest is quiet" card. Functional but less expressive.
- ⚠️ **Error:** handled as inline dim text ("_(connection error)_", "could not load…", "assistant unavailable") — **no themed error card and no Retry button.** Regression against template K's error state.

---

## B · COMPONENTS

| Component | Status | Notes |
|---|---|---|
| Palette + colour semantics (gold=earned, vermilion=loss, teal=live/unlocked, forest-green=growth, clay=guru, muted=unknown) | ✅ FAITHFUL | Identical `:root` tokens across every page; mastery ramp used consistently in dashboard/profile cells and Mermaid classDefs. |
| Type system (Cinzel/Marcellus/Spectral/Cormorant/Tiro-Devanagari/JetBrains-Mono) | ✅ FAITHFUL | Same font stack + roles everywhere. |
| Gold-hairline frame + corner ticks (`.frame`/`.corner-tr`/`.corner-bl`) | ✅ FAITHFUL | Used on landing feats, canvas, dashboard hero/cards. |
| Film grain + fixed atmospheric glows | ✅ FAITHFUL | Present on dashboard/journey/profile and landing. |
| Buttons (gold/stone/ghost/teal/danger) | ✅ FAITHFUL | Landing/login use the shared `.btn` set; arena buttons are re-styled but visually consistent. |
| Pills / chips | ✅ FAITHFUL | Used in canvas, dashboard quests, drawer. |
| Guru Pithora-paper bubble + dotwork texture | ✅ FAITHFUL | Arena + canvas; dark-on-cream contrast preserved. |
| Tool-trace (collapsible) | ✅ FAITHFUL | Arena "N steps · tap to view", call/res lines. |
| Streaming "guru is answering" (thinking dots + caret) | ✅ FAITHFUL | Arena reply uses a typing caret; the intent of v2's added state is met (simpler than the template's ink-dots label but present). |
| Run-output block (`.runout`) | ✅ FAITHFUL | Arena "▶ ran · Ns" + stdout/stderr. |
| Bash-approval card (`.approve`) | ✅ FAITHFUL | Arena; copy upper-cased. |
| AI-assistant panel (`.assist`) | ✅ FAITHFUL | AI-interview mode only. |
| Mandala HUD / rank-ring progress indicator | ⚠️ CHANGED | **Not used.** Arena = emoji+xpbar; dashboard = medallion+xpbar. The rank-ring (the template's core progress-indicator choice) is defined in CSS but never rendered. Regression. |
| **XP progress-indicator gallery** (radial ring / arrow-to-target bar / filling diya "pick one") | ❌ MISSING | The template's signature "FIXED XP" gallery is absent entirely; no `.prog-gallery`/`.rank-ring`/`.oil-fill` instantiated. |
| Streak component (`.streak` big flame + combo) | ⚠️ CHANGED | Shown as a small emoji chip in HUD/dashboard, not the template's dedicated flame-glyph streak card. |
| **Achievement toast** (transient, top, sheen) | ❌ MISSING | No on-earn celebration toast. Achievements only appear statically in dashboard/journey grids. |
| **Level-up ceremony** (`.ceremony` bloom + rays + diyas + rank title) | ❌ MISSING | No level-up moment anywhere in the app. |
| Achievements badge grid (earned) | ✅ FAITHFUL | Dashboard + journey. |
| Achievements gallery (earned + locked w/ progress) | ✅ FAITHFUL | Journey shows locked badges with progress bars, per template H. |
| Skill map (pillar × axis coloured cells) | ✅ FAITHFUL | Dashboard + profile. |
| Heatmap (diya lamps) | ✅ FAITHFUL | Journey activity heatmap. |
| XP curve | ✅ FAITHFUL | Journey sparkline. |
| Quest banner (`.quest`) | ✅ FAITHFUL | Dashboard today's-quest; minus the seal SVG + reward number. |
| Empty state card (illustrated "forest is quiet") | ⚠️ CHANGED | Replaced by inline per-card muted copy. |
| Loading (spinner + skeleton) | ✅ FAITHFUL | Arena loading is well-themed; template's skeleton shimmer not reused verbatim but intent met. |
| Error card + Retry | ❌ MISSING | Errors are inline dim text; no themed card/Retry. |
| Settings rows + toggles (`.setrow`/`.toggle`) | ⚠️ CHANGED | Only the cheat-penalty toggle survives as a header button; no Settings screen. |
| Canvas artifact types (md / code / html / interactive visual) | ⚠️ CHANGED | Present as a static scaffold only (not wired, not persisted). |
| Highlight-to-ask popover (`.selpop` "Ask about this ✦") | ⚠️ CHANGED | Static/decorative in `/canvas`; no real selection→ask behaviour. |
| Mobile radial bottom-nav (`.m-nav` + centre practice orb) | ❌ MISSING | App is responsive (tabs scroll, panes stack) but has no dedicated mobile radial nav. |
| Focus system + disabled/invalid field states (v2 refinement layer) | ✅ FAITHFUL (partial) | `:focus-visible` gold outline is applied app-wide; `.is-disabled`/`.is-invalid`/`.field-err` are defined but rarely instantiated (no complex forms). |

---

## C · PRIORITISED GAP LIST (most visible / important first)

1. **Death / loss screen still says "YOU DIED" + "Souls"** — the single most jarring divergence. The template deliberately re-themed this to **"YOUR AIM FALTERED / पुण्य क्षीण"** with stone-cracks + a gold merit badge, and "Merit" (not "Souls") throughout. High-visibility copy/motif regression, low effort to fix (also the reclaim toast: "Souls reclaimed" → "Merit reclaimed").
2. **Arena HUD is the retired emoji+xpbar, not the rank-ring** — contradicts the template's headline "FIX: XP is a continuous rank-ring fill, not an emoji/bar." Affects every practice session. Same fix should bring the dashboard character block onto the rank-ring.
3. **No Artifacts Library** (template F) — a whole screen + the persistence layer behind "a guru that writes, saved to a library you revisit" (a landing promise). Currently unbuilt.
4. **Canvas is a non-wired scaffold on a separate route** — not reachable as the arena's Editor↔Canvas tab, highlight-to-ask is decorative, nothing saves. The "guru that writes" pillar is visually mocked but not functional.
5. **No Settings screen** — reduced-motion, guru-voice, and provider-selection toggles are absent (only cheat-penalty survives as a button). Template K screen unbuilt.
6. **No level-up ceremony and no achievement toast** — the game's two celebration moments. Achievements are shown but never *awarded* with a moment; levels tick up silently. Motivation/delight gap.
7. **No XP progress-indicator gallery** (template's radial-ring / arrow-bar / diya "pick one") — the founder-decision component was never instantiated; ties to gap #2.
8. **Practice arena left rail missing** — no Practice/Progress/Forest-Map/Library/Settings rail + mini-HUD title ("Vana-Dhanurdhara"). Nav is top-tabs only.
9. **Live test-arrow panel (`.ed-tests`) missing** from the editor — per-test pass/fail "arrows" that make grading legible; today only run-output text.
10. **Themed error state + Retry missing** — errors are inline dim text ("connection error"), not the "The arrow found no wind" card with a Retry button.
11. **Login lacks Signup tabs + OAuth** (template B) — email/password only; no "Raise your own statue" signup or GitHub/Google.
12. **Onboarding threshold screen missing** — the framed "Cross the threshold / प्रवेश" hero + step-rail + answer-chips are replaced by an in-arena conversational flow (intent kept, presentation lost).
13. **Skill-tree forest map** (template J overview + single-track drill-in) → flat Mermaid graph. **KNOWN — being rebuilt on `feat/forest-skilltree`.** Colour semantics + IA preserved; illustrated groves + track-panel drill-in lost.
14. **Mobile radial bottom-nav missing** — responsive but without the template's centre-orb nav.
15. **Minor:** dashboard today's-quest lacks the seal SVG + reward number; streak still uses a 🔥 emoji; landing dropped the "Pricing" nav link (justified).

**Justified adaptations (not regressions):** the calibration / "illusion of knowing" card (added, on-theme, the product's headline metric); résumé-upload during onboarding; view/edit-in-place on Profile; data-wired dashboard/journey/profile; dropping "Pricing".
