# Ekalavya — Desktop UX Audit (1600×950)

> Senior product-design review of the web UI at `http://127.0.0.1:4646`.
> Method: authenticated Playwright/Chrome full-page screenshots of every standalone route
> (`/welcome`, `/login`, `/signup`, `/dashboard`, `/journey`, `/effectiveness`, `/profile`)
> and of the SPA at `/` (practice/chat, Forest Map, Library, Settings, Canvas, chats drawer,
> and the mode dropdown incl. Gauntlet / Boss / AI-interview). Screenshots in `/tmp/ux_*.png`.
> Read-only: no source changed, server untouched.

**One-line verdict:** The *marketing/auth surface* (`/welcome`) is genuinely premium — cinematic type, restrained gold-on-indigo, a real point of view. The *product surface* (SPA + dashboards) is the opposite: information-dense but templated, with a duplicated nav, a broken drawer z-index, lots of near-empty placeholder boxes, and pervasive card-height mismatch. The gap between the landing page's craft and the app's polish is the single biggest problem.

---

## P1 — High impact (fix first)

### P1-1 · SPA · Duplicated navigation (top tabs **and** left sidebar)
- **Issue:** The `/` app shows the same destinations twice — top bar `PRACTICE / PROGRESS / JOURNEY / EFFECTIVENESS / PROFILE / SKILL TREE` **and** left sidebar `Practice / Progress / Forest Map / Library / Settings`. Overlapping but not identical sets (top has Skill Tree/Effectiveness; sidebar has Forest Map/Library) so the user can't tell which is authoritative.
- **Fix:** Pick one primary nav. Keep the left sidebar as the app rail (it reads as the "in-app" nav), collapse the top bar to just brand + global status + account. Move Skill Tree / Effectiveness into the sidebar so all destinations live in one place.
- **Why:** Two competing navs double the cognitive load, waste ~64px of vertical space, and signal "assembled from parts" rather than designed.

### P1-2 · SPA · Chats drawer overlaps the top bar (z-index / no scrim on header)
- **Issue:** Opening `☰ CHATS` slides a drawer whose `CHATS ×` header sits *on top of* the EKALAVYA logo and top tabs — text bleeds through (logo + "Practice/Progress/Settings" labels are visible under the drawer). The drawer also does not dim or close the top nav, and persists visually while switching modes.
- **Fix:** Render the drawer above a full-height scrim that also covers the top bar, give the drawer an opaque background, and raise its z-index above the header. Close/scrim on outside-click.
- **Why:** Overlapping legible text is a hard visual bug — instantly reads as broken and undermines all the premium styling elsewhere.

### P1-3 · SPA · Top-right status cluster looks like raw debug output
- **Issue:** The top-right shows `Auto (balanced) · rotates across 4 provider(s)` as left-aligned wrapped body text jammed next to `Lv 1 · 51% → R2`, a flame icon, and `Novice`. No card, no alignment grid, mixed type sizes — it reads like console logging, not a designed status HUD.
- **Fix:** Put provider/rotation info behind a small pill or icon with a tooltip; reserve the visible HUD for level, streak, and XP with consistent baseline alignment. Right-align as a tidy cluster.
- **Why:** The first thing the eye hits top-right is unpolished text; it cheapens the whole header.

### P1-4 · Practice · Empty center + no mode differentiation
- **Issue:** The default Practice view is a large blank column with a permanent loading state ("NOCK THE FIRST ARROW / Ekalavya is drawing the bow…"). Switching modes (Daily / Mock / **⚔ Gauntlet** / **🐉 Boss fight** / **⚡ Blitz**) changes only the dropdown label — no theming, timer, stakes UI, or copy change. The emojis promise drama the UI never delivers.
- **Fix:** Give the empty state a real CTA ("Start today's drill →") instead of an indefinite spinner. Make each mode visually distinct — Gauntlet = timer + lives, Boss = accent color shift + banner, Blitz = countdown — even if lightweight.
- **Why:** The core loop currently feels inert and identical across modes; the gamified names set an expectation the product breaks.

### P1-5 · /login & /signup · Massive dead space above the form
- **Issue:** Both auth pages stack a tall hero (statue + archer + orbital motif) and then push the actual form into a separate dark panel far below the fold, with a large empty gap between the "↓ ENTER" divider and the form. On a 950px viewport the form is barely visible without scrolling.
- **Fix:** Either (a) split-screen: art left, form right, both above the fold; or (b) tighten the hero to ~40vh and float the form card immediately under it. Remove the redundant "↓ ENTER" scroll divider.
- **Why:** Sign-in is the highest-intent moment; making users hunt/scroll for the form adds friction and looks like two unrelated screens glued together.

### P1-6 · /profile · Wall-of-text dump, not a designed page
- **Issue:** `/profile` is a single very long column of dense prose paragraphs and section headers with a giant raw-looking table at the very bottom. No cards, no columns, no scannable hierarchy — it looks like a rendered markdown file, not a product screen.
- **Fix:** Break into scannable cards/columns (identity summary, skills, history), collapse the long prose behind "read more," and style the bottom table as a real data table with zebra rows and aligned numerics.
- **Why:** It's the most templated screen in the app and the one a recruiter/user would judge you on; it currently reads as unfinished.

---

## P2 — Medium impact

### P2-1 · Effectiveness & Dashboard · Placeholder boxes waste vertical space
- **Issue:** `/effectiveness` opens with two large padded banners that say only "No answers yet / Not enough data yet," plus several more empty "trajectory" boxes below — big boxes, almost no content. Same pattern on `/dashboard` (Chronicle card nearly empty).
- **Fix:** Collapse empty modules to a compact single-line hint, or merge the "not enough data" states into one onboarding strip. Only expand a module to full card height once it has data.
- **Why:** Full-height empty cards make a first-run user feel the product is broken/abandoned, and they create most of the height-mismatch issues in the box-sweep below.

### P2-2 · /welcome · Headline kerning/leading is loose on the big display type
- **Issue:** "THE HALL WAS CLOSED TO HIM. / SO HE TAUGHT HIMSELF TO OUTSHOOT THE PRINCES." — strong copy, but the all-caps display face has loose tracking and generous leading that makes the multi-line headline feel slightly airy/unanchored versus the tight editorial feel it's going for.
- **Fix:** Tighten tracking (~-0.02em) and leading on the H1; consider a hard max-width so line breaks are intentional, not viewport-driven.
- **Why:** This is the hero moment; small type refinement pushes it from "good" to "memorable."

### P2-3 · SPA · Right editor pane dominates; center chat feels secondary
- **Issue:** In Practice the right-hand Editor/Canvas pane is visually heavier (bordered, buttons, code) than the center chat, which is the actual tutoring surface. The `☠ penalty on` toggle in the header is cryptic and easy to mis-hit.
- **Fix:** Rebalance widths (give the tutor/chat more presence), and move `penalty on` into Settings-style context or add a label/tooltip.
- **Why:** The teaching conversation is the product's soul; the layout currently subordinates it to the code editor.

### P2-4 · Library · Good empty state, but filters look disabled
- **Issue:** `The Scriptorium` empty state copy is nicely on-brand, but the `ALL / Lessons / Code / Visuals / HTML` filter pills sit above an empty list and read as inert (no active styling on `ALL`). Search bar is well-styled but floats far right, misaligned from the filter row baseline.
- **Fix:** Show `ALL` as visibly active; left-align search to the content grid or move it into the filter row so the two share a baseline.
- **Why:** Alignment + active-state are cheap fixes that make the module feel wired-up rather than stubbed.

### P2-5 · Global · Two visual languages (marketing vs app)
- **Issue:** `/welcome` uses warm cinematic art, generous space, and editorial type. The app uses a cool near-black grid of thin-bordered cards with tiny mono-ish labels. They don't feel like the same product.
- **Fix:** Carry one or two hero motifs (the archer mark, the gold arc, the warmer indigo) into the app chrome — e.g., the header, empty states, and section dividers — to bridge the two worlds.
- **Why:** Consistency of world-building is what makes it feel expert-crafted rather than a landing page bolted onto a dashboard.

### P2-6 · /journey · Achievements row mixes locked/unlocked with no clear state
- **Issue:** The Achievements strip shows badges (On Fire, Week Warrior, Unbroken, Adept, Fast History, Sharpened, Initiate, Directed) at uniform styling; it's hard to tell earned vs locked at a glance.
- **Fix:** Desaturate/lock unearned badges, add a subtle gold ring on earned ones, and a small "3/8 earned" counter.
- **Why:** Achievement systems only motivate if progress is legible.

---

## P3 — Polish / lower impact

- **P3-1 · Settings · Toggle colors inconsistent:** Cheat-penalty toggle is red-on, Guru-voice is gold-on, Reduced-motion is white-on. Standardize the "on" color (gold) so state reads consistently; reserve red only for destructive.
- **P3-2 · Forest Map · Legend cramped bottom-left:** The `dormant/active/…` legend is tiny and low-contrast against the map. Enlarge and give it a small backing panel.
- **P3-3 · Dashboard · Skill-map cell colors lack a key:** The dense colored grid (green/amber/red per topic) has no visible legend near it; add an inline key.
- **P3-4 · /welcome footer cards:** The three cards ("Grades what you can do alone / A forest to walk / A guru that writes") are good, but their heading weights and body lengths differ enough to make the row look ragged — normalize.
- **P3-5 · Mono label overuse:** Tiny letter-spaced mono labels are used everywhere in the app (nav, stats, sections). It's a look, but at this density it reduces scannability; reserve mono for data, use the humanist face for labels.
- **P3-6 · Chats drawer list:** "Practice session · 2026-08-01 …" rows are generic; show first user line or topic as the title (one row already does — "frankly I dont know how to solve this…"), which is far more useful.

---

## Box-size / height-consistency sweep

Every card/box that mismatches its neighbours or leaves an awkward empty gap, per page. This is the most systemic visual issue in the app.

### /dashboard  (`ux_dashboard_full.png`)
- **Bottom 3-col row — Active Quests / Achievements / Chronicle:** three different heights. Active Quests is tallest (3 quest rows), Achievements medium, **Chronicle noticeably shorter with dead space** below it inside the row. → Equalize to a shared row height or align to a grid.
- **Right column stack vs left Skill Map:** the left "Skill Map" card is very tall; the right column ("Skill Bars", "100% Diligence", the tall gold streak card) doesn't sum to the same height — the right column ends well above the left, leaving an L-shaped gap.
- **"88 Under-confident" calibration banner:** full-width but sparsely filled (big number, two small stats, lots of empty horizontal space) — height feels arbitrary vs the tight rows around it.

### /journey  (`ux_journey.png`)
- **Bottom row — activity square (left) vs line-chart card (right):** the small square "activity" tile is much shorter than the wide line-chart card beside it; the row baseline doesn't align and the left tile leaves empty space under it.
- **Stat pills row (Level/Streak/Total XP/Cadence/Skills):** the 5 top stat boxes are consistent — good — but the "Milestones" card directly below is a nearly-empty full-width box (one line "Began the journey"), disproportionately tall for its content.
- **Achievements grid:** uniform tile heights (good), but the last row is partially filled, leaving an uneven trailing gap.

### /effectiveness  (`ux_effectiveness.png`)
- **Top two banners** ("Not enough graded data yet" / "…answer a few drills…"): both large padded boxes holding one sentence each — height far exceeds content.
- **Second row three boxes** ("Graded accuracy over time" / "The redemption gap" / "Ability trajectory"): mismatched heights, each mostly empty placeholder.
- **Bottom 3-col row — Retention (left) / 88 Calibration (center) / stats grid (right):** three clearly different heights. Retention is the tallest (paragraph), Calibration medium (floating "88" with empty space above/below), **stats grid shortest** — the row bottom is ragged.
- **Strengths vs What-to-revisit (2-col):** these two *do* match — cite as the reference height the rest of the page should follow.

### / (SPA practice)  (`ux_spa_practice.png`)
- **Editor pane vs chat column:** the editor pane has a defined bordered box height; the center chat has none, so the two columns don't share a bottom baseline — the composer inputs sit at slightly different heights.
- **Header control chips** (`penalty on`, `Novice/Lv`, `EDITOR`): differing paddings/heights make the header row visually uneven.

### /welcome  (`ux_welcome.png`)
- **Three footer cards:** near-equal but body-copy length differences make heights ragged; pin to equal height.

### /login & /signup  (`ux_login.png`, `ux_signup.png`)
- **Hero block vs form card:** enormous height disparity — hero occupies most of the viewport, form card is a small box floated far below, with a large empty gap between them (the core P1-5 issue, restated here as a box-height mismatch).

---

## Screenshot index
`/tmp/ux_welcome.png`, `ux_login.png`, `ux_signup.png`, `ux_dashboard.png`, `ux_dashboard_full.png`,
`ux_journey.png`, `ux_effectiveness.png`, `ux_profile.png`, `ux_spa_practice.png`, `ux_forestmap.png`,
`ux_library.png`, `ux_settings.png`, `ux_canvas.png`, `ux_chats_drawer.png`, `ux_mode_dropdown.png`,
`ux_mode_gauntlet.png`, `ux_mode_boss.png`, `ux_mode_aiinterview.png`, `ux_progress.png`.
