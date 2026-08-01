# UX Audit — Mobile Responsiveness & Engagement / Memorability

**App:** Ekalavya AI coding tutor (`http://127.0.0.1:4646`)
**Audited:** 2026-08-01 · Playwright (Chrome) · mobile viewport 390×844 · full-page screenshots
**Scope:** PART A — mobile responsiveness of entry flow + all main views. PART B — engagement, narrative resonance, memorability.
**Method:** 13 full-page screenshots (`/tmp/uxm_*.png`), plus programmatic overflow / tap-target / DOM audits. READ-ONLY — no source changes, server not restarted.

---

## Overall verdict

The product has a **genuinely distinctive, premium soul**. The Ekalavya myth (the self-taught archer denied a teacher), the Cinzel/Cormorant serif type system, the gold-on-midnight palette, and the "unaided merit" honesty framing are already more memorable and emotionally coherent than 95% of coding tutors. The marketing landing (`/welcome`), the Journey page, and the Effectiveness ("Am I getting better?") page are portfolio-grade.

The gaps are **not** taste — they are (1) a handful of concrete mobile breakages concentrated in the logged-in **Arena**, and (2) engagement *loops* that are designed but under-surfaced, so a new mobile user may not feel the hook in the first 60 seconds. Fixing the Arena's horizontal overflow and tap targets, and pulling one or two reward/ceremony moments forward, would take this from "beautiful static thing" to "I want to come back tomorrow."

**What already works (keep, don't touch):** the `/welcome` scroll-narrative, the scroll-snap "↓ ENTER" auth reveal on `/login` + `/signup`, the 2-column stat-card grids on Journey/Dashboard, the ELO/strengths/"where to invest" honesty on Effectiveness, the Duolingo-style activity heatmap, and the whole serif+gold identity.

---

## Screenshot index

| File | View | Route |
|---|---|---|
| `uxm_welcome.png` | Marketing landing | `/welcome` |
| `uxm_login.png` | Login (scroll-snap auth) | `/login` |
| `uxm_signup.png` | Signup | `/signup` |
| `uxm_after_login_arena.png` / `uxm_spa_practice.png` | Arena — Practice | `/` |
| `uxm_dashboard.png` | Progress / Dashboard | `/dashboard` |
| `uxm_journey.png` | Journey (achievements, heatmap, XP) | `/journey` |
| `uxm_effectiveness.png` | Effectiveness ("Am I getting better?") | `/effectiveness` |
| `uxm_profile.png` / `uxm_profile_fold.png` | Profile | `/profile` |
| `uxm_spa_forest.png` | Forest Map | `/` → Forest |
| `uxm_spa_library.png` | Scriptorium / Library | `/` → Library |
| `uxm_spa_settings.png` | Settings | `/` → Settings |

---

# PART A — Mobile responsiveness

**Automated results (390px viewport):**

| View | Horizontal overflow (scrollWidth) | Verdict |
|---|---|---|
| `/welcome`, `/login`, `/signup` | 390 (none) | Clean |
| `/dashboard`, `/journey`, `/effectiveness`, `/profile` | 390 (none) | Clean |
| **`/` (Arena)** | **555px vs 390** | **Breaks** |

- **10 interactive elements are < 40px tall** (Apple HIG minimum tap target is 44px): the top HUD chips (`☰ CHATS` 33px, `▤ EDITOR` 30px, `☠ penalty on` 30px, the mode `<select>` 30px) and the bottom-nav labels (`ASHRAM/FOREST/LIBRARY/SETTINGS` at 37px tall, 40–53px wide).
- **Arena overflow root cause:** the editor toolbar strip (`Daily practice ▾ · Editor · Canvas · New · Run · Submit code`) does not wrap — the right-most `tab`/`submit` buttons extend to right≈572px, dragging page width to 555. Not the Monaco editor itself (it scrolls internally).

---

# Prioritized findings (P1 → P3)

## P1 — must fix (mobile breakage + first-impression risk)

### P1.1 — Arena has real horizontal overflow on mobile
- **Area:** Arena `/` (logged-in home) — editor toolbar row.
- **Observation:** Page scrollWidth is **555px on a 390px screen**. The `Daily practice ▾ / Editor / Canvas / New / Run / Submit code` control strip is a single non-wrapping row; its buttons push past the right edge, creating a horizontal scrollbar and letting the whole app rubber-band sideways. This is *the* view every returning user lands on.
- **Suggestion:** Let the toolbar wrap (`flex-wrap:wrap`) or collapse secondary controls (New/Canvas) into an overflow "⋯" menu under a mobile breakpoint; keep only the mode selector + **Run** + **Submit** on the primary row. Guard the shell with `overflow-x:hidden` on the arena container as a belt-and-suspenders.
- **Impact:** High. Removes the single worst mobile defect and the only view that fails the overflow test.

### P1.2 — Tap targets below 44px throughout the Arena chrome
- **Area:** Arena top HUD chips + bottom radial nav.
- **Observation:** 10 controls are 30–37px tall. The bottom-nav items are the primary navigation and are only 37px tall / 40px wide — thumb-missable, and the top chips (`penalty on`, mode select) are 30px.
- **Suggestion:** Raise interactive rows to a **44px min hit area** (padding, not just font). For the bottom nav, widen each item to fill the bar equally and add ~6px vertical padding. Tiny visual size is fine if the *hit area* is padded to 44px.
- **Impact:** High. Fixes the most-touched surfaces; cheap CSS.

### P1.3 — Top tab bar is truncated ("EFFECTIVEN")
- **Area:** Arena top tabs (`PRACTICE / PROGRESS / JOURNEY / EFFECTIVEN…`).
- **Observation:** The horizontal tab row clips the last label mid-word on 390px. It *is* horizontally scrollable (scrollbar hidden), but there is no affordance that more tabs exist, so users won't discover Effectiveness/Skill-Tree from the Arena.
- **Suggestion:** Either add a right-edge fade + faint chevron to signal scroll, or shorten labels on mobile (`EFFECT`, `TREE`), or move these into the existing bottom nav so nothing is hidden. Redundancy between the top tabs and the bottom radial nav should be reconciled on mobile — pick one primary navigation.
- **Impact:** Medium-High. Recovers discoverability of two of the best pages.

### P1.4 — Profile page is a 13,500px wall of text on mobile
- **Area:** `/profile` (~16 screen-heights of continuous markdown).
- **Observation:** The profile renders the entire learner dossier as one long prose document (Background / Relationship with Python / … ). On mobile it's an endless scroll with no anchors, no collapse, no "jump to." First-time mobile users will bounce before reaching the bottom.
- **Suggestion:** Collapse into accordion sections (Background · Skills · Goals · History) collapsed by default, or a sticky in-page section nav. At minimum cap the visible height and add "read more." This is content structure, not a rewrite.
- **Impact:** Medium-High. Turns an intimidating scroll into a scannable card set.

---

## P2 — should fix (engagement loops + polish)

### P2.1 — The first-run hook isn't emotional enough *inside* the app
- **Area:** Onboarding — the moment right after login (Arena).
- **Observation:** `/welcome` sells the myth beautifully ("The hall was closed to him. So he taught himself to outshoot the princes."). But the instant you log in, you land in a dense editor with a constraints paragraph and a code box — the *narrative goes silent*. There's no "Ekalavya greets you / here is your bow / take your first shot" beat. The emotional promise of the landing isn't paid off in the product.
- **Suggestion:** A 2–3 step, skippable **first-session ceremony**: the guru speaks one line, names the learner a "devotee," and hands them a deliberately-winnable first drill ("draw the string"). Duolingo and boot.dev both win the first 60 seconds this way. Reuse existing copy tone; no new systems.
- **Impact:** High for retention. This is the single biggest engagement lever.

### P2.2 — Rewards exist but aren't *felt* — surface XP/streak/ceremony feedback
- **Area:** Reward feedback loop.
- **Observation:** The systems are all there (XP, streaks, "Merit reclaimed +XP restored / The forest forgives the honest," achievements with progress bars, ELO, Souls-like death via `penalty on`, game modes gauntlet/blitz/boss/dragon — all confirmed in the DOM). But on first mobile view they're *passive*: a "1d" streak and "Lv 1 · 51%" chip in a cramped HUD. The reward is reported, not celebrated.
- **Suggestion:** Add a lightweight **completion moment** after each drill — animate the XP gain, pulse the streak flame, and occasionally fire an achievement toast (you already have the "reclaim" badge component — reuse its motion for wins, not just forgiveness). Duolingo's dopamine comes almost entirely from this 1-second celebration.
- **Impact:** High. Converts existing invisible mechanics into felt motivation.

### P2.3 — Game modes (⚔ gauntlet / ⚡ blitz / 🐉 boss) are hidden in a dropdown
- **Area:** Mode selection / motivation variety.
- **Observation:** The most *fun*, most memorable feature — Souls-like boss fights, blitz, gauntlet — is buried in a 30px-tall `<select>` next to the editor. Nothing signals that a dragon boss exists. This is premium-game material presented as a form control.
- **Suggestion:** Promote modes to a **visual chooser** (cards/orbs with the ⚔⚡🐉 glyphs + one-line stakes each) reachable from the Practice orb or Forest. Show boss fights as gated milestones on the Forest Map ("a dragon guards this grove"). Make the scary thing *look* scary.
- **Impact:** High for memorability & "attention-holding." This is your boot.dev-style differentiator.

### P2.4 — Forest Map is your signature image but is tiny/unreadable on mobile
- **Area:** Forest Map (`/` → Forest).
- **Observation:** "The Forest of Mastery — 197 groves on a winding path" is the most cinematic, most ownable visual in the app — and on 390px it's a small, faint, hard-to-read node graph squeezed under persistent Arena chrome. The metaphor's payoff is lost.
- **Suggestion:** On mobile, give the map a **full-height canvas** (hide the top HUD/tabs while in Forest), enable pinch/pan, and highlight the *next* grove with a glowing "you are here → next" marker so it doubles as a call-to-action. Make it the emotional centerpiece it deserves to be.
- **Impact:** Medium-High. Single most memorable screen; currently under-delivering on mobile.

### P2.5 — Arena chrome persists across Forest/Library/Settings
- **Area:** SPA view framing.
- **Observation:** When you switch to Forest / Library / Settings, the `EDITOR / penalty on / Lv 1 51%` HUD and editor tabs stay pinned at top, eating ~120px of a small screen on views that have nothing to do with the editor.
- **Suggestion:** Hide the editor HUD outside Practice; give each view its own full mobile height (ties into P2.4). Simple conditional on the active rail.
- **Impact:** Medium. More breathing room, less confusion about "am I still coding?"

### P2.6 — Empty states are on-brand but dead-ended
- **Area:** Library ("The Scriptorium is quiet…"), Effectiveness ("not enough unaided data yet"), Retention ("no cards have survived a review interval yet").
- **Observation:** The empty-state *copy* is lovely and in-voice — but each is a wall the new user hits with no button to move forward.
- **Suggestion:** Give every empty state a **single primary CTA** ("Ask the guru for your first lesson," "Do an AI-off check now"). Turn the poetic dead-end into a doorway.
- **Impact:** Medium. Converts admiration into action on day one.

---

## P3 — nice to have (delight & refinement)

### P3.1 — Add micro-motion to the entry ceremony
- **Area:** `/login` scroll-snap reveal.
- **Observation:** The "↓ ENTER" scroll-to-auth is a lovely Apple-style beat but static.
- **Suggestion:** A subtle drawn-bow/arrow flourish or gold shimmer on the wordmark as the auth card snaps in. One tasteful animation, not confetti.
- **Impact:** Low-Medium. Raises "premium" perception at the first touch.

### P3.2 — Personalize the Effectiveness verdict
- **Area:** Dashboard "UNDERCONFIDENT" / Effectiveness calibration.
- **Observation:** The honest calibration framing ("clarity · 0 confidently wrong · Brier 0.12") is a standout *rigorous* signal.
- **Suggestion:** Add one human sentence from the guru interpreting the number ("You know more than you trust — draw with confidence"). Turns a metric into a mentor.
- **Impact:** Low-Medium. Deepens the mentor relationship cheaply.

### P3.3 — Streak/loss-aversion nudge
- **Area:** Streak (`1d`) + Souls-like penalty theme.
- **Observation:** You have both a streak *and* a death/forgiveness mechanic — a rare combo. Nothing currently warns "your streak is at risk."
- **Suggestion:** A gentle same-day nudge ("the forest dims — one shot keeps the fire lit"). Reuse the death/forgiveness voice for loss-aversion without being naggy.
- **Impact:** Low-Medium. Duolingo's proven retention lever, in your voice.

### P3.4 — Reconcile dual navigation on mobile
- **Area:** Top tabs vs bottom radial nav.
- **Observation:** Two nav systems coexist (top tabs Practice/Progress/Journey/Effect/Profile/Tree; bottom orbs Ashram/Forest/Practice/Library/Settings) with overlapping-but-different destinations.
- **Suggestion:** On mobile, consolidate to the bottom radial nav (thumb-reachable) and drop the top tab row, or make them clearly hierarchical. Reduces cognitive load and reclaims vertical space.
- **Impact:** Low-Medium. Clarity + space.

---

## Suggested sequencing

1. **Ship P1 first** (overflow, tap targets, tab truncation, profile length) — pure responsiveness, low risk, removes the only broken view.
2. **Then P2.1 + P2.2** (first-session ceremony + felt rewards) — the highest-leverage engagement work; systems already exist, just need surfacing.
3. **Then P2.3 + P2.4** (game-mode chooser + full-screen Forest Map) — the memorability differentiators.
4. **P3** as polish once the loop closes.
