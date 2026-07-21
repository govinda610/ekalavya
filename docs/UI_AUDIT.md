# Ekalavya — UI/UX Audit & Redesign Spec

> **Purpose:** Move the product from "looks AI-generated / bland" to "looks human-crafted and beautiful," while **keeping the cyberpunk/terminal identity** (Rajdhani + Inter + JetBrains Mono; near-black bg; neon `--acc #5ef2b8` / `--cyan #57d3ff` / `--violet #b48cff` / `--amber #ffcf6b`).
> **Scope:** This is a paper spec. No product code has been changed. Implementation happens later.
> **Evidence:** Every diagnosis below was verified against the live rendered UI. Audit screenshots live in `docs/screenshots/audit_*.png` (captured 2026-07 at 1440×900, Chrome). Source read: `src/eklavya/webapp.py` (the `_INDEX` SPA), `src/eklavya/dashboard.py` (`render` + `_CSS`), `src/eklavya/journey.py` (`render` + `_JCSS`).

---

## 0. TL;DR — Why it reads as "AI-generated"

The palette, fonts and accent choices are actually *good*. The blandness is **not** a color problem — it's a **craft** problem. Five root causes, in priority order:

1. **No spatial rhythm.** Content sits in a rigid `1fr 1fr` split (Practice) or a repeated 2-column card grid (Dashboard/Journey). Everything is the same weight, so nothing leads the eye. Real designers vary card size (bento), density and emphasis.
2. **Vast dead space, never intentional.** Empty Practice chat column, empty editor, half-empty milestone band, empty XP box, empty skill tree — all render as *large voids with a sentence floating in them*. Award-level UIs turn emptiness into designed empty-states with art, structure and a CTA.
3. **Flat depth.** One border color (`--line #1d2a3c`), one card gradient, shadows that are all `box-shadow:0 …px …px #000`. No surface ladder, no hairline top-edge highlight, so panels look like colored rectangles, not physical layers.
4. **No motion or state feedback.** The only animations are the death pulse, reclaim toast, and typing caret. No hover transitions on cards, no skeletons while streaming/loading iframes, no level-up celebration, no number roll-ups. Static = "template."
5. **Emoji as iconography.** 🏹⚔◈▲✦◎🏅📜🔥⭐ everywhere. Emoji render inconsistently per-OS, break the monochrome terminal mood, and are the single strongest "AI slop" tell. A hand-made product uses a coherent icon set.

Plus two **known layout defects** confirmed on screen:
- **Practice editor overflows / clips** on the right (Monaco lines run under the viewport edge; toolbar buttons crowd the right rail — see `audit_assist_panel.png` where the "Ask" button is half-cut).
- **Journey stacks full-width bands with huge dead zones** (milestones = one line in a tall band; achievements fill top-left and leave the entire right half empty; XP box is empty — see `audit_journey_full.png`).

Fix these five + two and the product stops looking generated.

---

## 1. Refined Design Tokens

Keep the identity; add the *structure* that makes it look crafted. These are drop-in replacements/additions for the `:root` blocks in `webapp.py` and `dashboard.py` (currently duplicated — **unify into one shared token block**, see §7 quick wins).

### 1.1 Color — add a surface ladder + tinted black (Linear's core trick)

Current: two near-blacks (`--bg #080b11`, `--panel #111a28`) with one border. Too flat. Replace with a **4-step elevation ladder**, each step a touch lighter with the *same* blue-violet tint, plus **hairline borders that lighten with elevation**:

```
/* base canvas — keep the tinted near-black, do NOT go pure #000 */
--bg:        #070a10;   /* app background (was #080b11) */
--surface-0: #0b1019;   /* sunken wells (editor, tracks, code blocks) */
--surface-1: #0e1521;   /* base card / panel */
--surface-2: #131c2b;   /* raised card / drawer / active state */
--surface-3: #182335;   /* modal / popover / hover-lifted card */

/* borders lighten with elevation (was single --line) */
--line-0:  #16202e;     /* faintest divider */
--line-1:  #1f2c3e;     /* default card border (≈ old --line) */
--line-2:  #2a3a52;     /* raised / hover border */
--edge:    #ffffff0f;   /* 6% white top-edge highlight on lifted panels */

/* ink */
--ink:   #dbe6f2;  --dim: #8394ac;  --faint: #566579;

/* accents — UNCHANGED (identity) but define tint-only + glow variants */
--acc:#5ef2b8; --cyan:#57d3ff; --violet:#b48cff; --amber:#ffcf6b; --pink:#ff7ab6; --red:#ff5c7a;
--acc-dim:#5ef2b81f;   /* 12% wash for backgrounds */
--acc-line:#5ef2b855;  /* 33% for tinted borders */
--acc-glow:0 0 18px #5ef2b855;
```

**Rule (borrow from Linear):** the accent is a *flashlight*, not paint. It appears only on: the active tab, the primary CTA, focus rings, the XP fill, "strong"/"mastered" states, and level-up moments. **Strip accent from decorative section headings** — right now every `<h2>` is `--acc` uppercase, which flattens hierarchy and screams template. Make headings `--ink`; reserve accent for the one action/metric per card.

### 1.2 Typography — a real scale + tabular numerals

Current type is ad-hoc (`14.5px`, `13px`, `17px`, `30px`…). Adopt a **modular scale** and make every metric use **tabular numerals** (the Geist/dev-tool signature — numbers that don't jitter):

```
--fs-hero:  clamp(28px, 4vw, 44px);  /* logo / big level number */
--fs-h1:    22px;   /* view title (Rajdhani 700, letter-spacing .06em) */
--fs-h2:    13px;   /* section label (Rajdhani 600, UPPER, letter-spacing .14em, color:--dim) */
--fs-body:  14px;   /* Inter 400/500 */
--fs-sm:    12.5px; /* meta */
--fs-xs:    11px;   /* mono captions */
/* numerals everywhere they matter */
.num, .hud, .xptext, .agstat b, .chron .xp, .lvlnum { font-variant-numeric: tabular-nums; }
```

Hierarchy fixes:
- **Section headers** (`h2`) become quiet mono/Rajdhani labels in `--dim`, NOT loud accent. Let the *content* be the loudest thing.
- **Body line-height** 1.6, max measure ~68ch in chat (currently `max-width:92%` lets lines run too wide on 1440px).
- Rajdhani only for display (logo, level, view titles, big stat numbers). Inter for all prose. JetBrains Mono for code, metrics, captions, meta timestamps.

### 1.3 Spacing — an 8pt rhythm (currently arbitrary)

Values today: `12px 20px`, `18px 20px`, `9px 12px`, `11px 13px`, `16px 22px`… no system. Adopt:

```
--s1:4px --s2:8px --s3:12px --s4:16px --s5:24px --s6:32px --s7:48px --s8:64px
```
Card padding → `--s5` (24). Section gap → `--s5`. Inline gaps → `--s2`/`--s3`. Page gutter → `--s6`. **Consistency here alone removes ~30% of the "off" feeling.**

### 1.4 Radius

Current mix: 8/9/10/11/12/14/16/18/999. Too many. Collapse to a 3-step + pill:
```
--r-sm:8px   (inputs, chips, cells, small buttons)
--r-md:14px  (cards, drawers, messages, editor frame)
--r-lg:20px  (hero, modal, death card)
--r-pill:999px (xp bars, tags, streak chip)
```

### 1.5 Shadow & elevation (the "physical layer" look)

Replace every `box-shadow:0 …px …px #000` with a **two-part elevation recipe**: a soft ambient shadow **plus** the 6% top-edge highlight (Linear's "pixel-rendered" trick). This is the single biggest "handcrafted" upgrade.

```
--elev-1: 0 1px 0 var(--edge) inset, 0 8px 24px -16px #000a;   /* base card */
--elev-2: 0 1px 0 var(--edge) inset, 0 18px 44px -22px #000c;  /* drawer/raised */
--elev-3: 0 1px 0 var(--edge) inset, 0 30px 70px -30px #000e;  /* modal/death */
```
Cards get `--elev-1`; on hover lift to `--elev-2` + `translateY(-2px)` + `border-color:--line-2` (250ms cubic-bezier).

### 1.6 Motion — define a vocabulary (currently almost none)

```
--ease: cubic-bezier(.22,.61,.36,1);   /* standard */
--ease-out: cubic-bezier(.16,1,.3,1);  /* enter/celebrate */
--dur-fast:120ms --dur:220ms --dur-slow:420ms
```
**Frequency-gate motion** (Warp/Raycast principle): expressive/celebratory motion for *rare* events (level-up, badge unlock, death), subtle 120–220ms for *common* ones (hover, tab switch, send), and **zero** for high-frequency streaming tokens. Everything respects `@media (prefers-reduced-motion: reduce)`.

### 1.7 Iconography — retire emoji, adopt a line-icon set

Swap the emoji (🏹⚔◈▲✦◎🏅📜🔥⭐💎🗡️👑🔒📈🗓️) for a single **inline-SVG line-icon set** (Lucide/Feather-style, `stroke:currentColor`, 1.5px, 18px). Keep exactly two mascot marks as brand: the **🏹 bow** may stay as a hand-drawn SVG logo glyph, and the **YOU DIED** skull moment. Everything else → monochrome SVG that inherits the accent only when active. This is the highest-leverage single change for "not AI-generated."

---

## 2. Per-View Diagnosis + Redesign Direction

### 2.1 Practice (streaming chat + Monaco editor + Chats drawer + HUD)
*Evidence: `audit_practice.png`, `audit_assist_panel.png`, `audit_chats_drawer.png`.*

**What's bland / broken:**
- **Editor overflow/clip (known defect):** Monaco lines and the `.edtoolbar` run to the hard viewport edge with no right padding; in aiinterview mode the "Ask" button and editor scrollbar are clipped (`audit_assist_panel.png`). Root cause: `#practice{grid-template-columns:1fr 1fr}` with the right `.col` having no inner gutter, and `#editor{flex:1}` bleeding under the 100vw edge.
- **Dead chat column:** at session start the left column is one welcome bubble floating in a huge black void (`audit_practice.png`). No visual anchor, no example prompts, no session context.
- **Editor is empty + featureless:** just `# write your solution here` and 2 line numbers in an ocean of black. No file/problem header, no language pill styling, no run-result surface — so the right half looks unfinished.
- **HUD is a cramped mono string** jammed top-right (`🔥 0 ⭐ Lv 1 Novice ▁▁`). The xp bar is a tiny 88px sliver, easy to miss; emoji flame/star clash with the terminal type.
- **Message bubbles** are generic rounded rectangles; "you" vs "Ekalavya" differ only by a subtle bg. No avatar/rail, no code-block chrome beyond a border.
- **Chats drawer** items are plain rows; active state is a faint bg change; the rename affordance is a bare `✎`. Header "CHATS" + `×` is minimal to the point of unfinished.

**Redesign direction (concrete):**

- **Fix the grid:** `#practice{grid-template-columns: minmax(420px,1fr) minmax(520px,1.15fr); gap:1px; background:var(--line-0)}` (the 1px gap over a line-colored background gives a crisp hairline seam instead of a heavy border). Give the right `.col` `padding-inline:0` but wrap `#editor` in a framed container with `--r-md`, `--s3` inset, and its own header bar so Monaco never touches the viewport edge. Set `#editor{min-height:0}` and a bordered frame `border:1px solid var(--line-1); border-radius:var(--r-md); overflow:hidden` to kill the clip.
- **Editor gets a "problem card" header:** a thin bar showing `● problem title · difficulty pill · language pill · timer` (mono, tabular). This alone makes the right column read as *designed*, not empty.
- **Add a results/verify strip** under the editor (collapsed until Submit): pass/fail chips with accent(pass)/red(fail), runtime, and the self-check note rendered as a styled callout, not inline italic text.
- **Chat empty-state:** when a session starts, render **2–3 suggested-prompt chips** below the welcome bubble ("Explain your approach", "I'm stuck on X", "Review my code") + a faint monospace watermark (a subtle ASCII bow or `स्वाध्याय` glyph at 4% opacity) so the void becomes intentional atmosphere.
- **Message redesign:** add a 22px speaker rail on the left of each message (accent dot for Ekalavya, dim dot for you) with a hairline connecting line — turns a list of rectangles into a *conversation thread*. Code blocks get a top chrome bar (lang label + copy button) like a real editor.
- **HUD → a compact stat cluster**, not a string. Three pill-cards: `STREAK 🔥→flame-icon | LEVEL · rank | XP ▓▓▓░ 40/100`. Widen the xp bar to ~140px, add the `--acc-glow`, and animate the fill width on change (`transition:width .5s var(--ease)`). Tabular numerals throughout.
- **Streaming skeleton:** while the first token is pending, show a 3-line shimmer skeleton in the AI bubble (not just a blinking caret) — perceived-performance win, and looks intentional.
- **Chats drawer:** give each item a mode-color left accent bar (2px), a relative timestamp ("2h ago" not `2026-07-21 16:49`), and a proper hover-reveal action row (rename + open). Header gets the bow glyph + count ("Chats · 7"). Active item uses `--surface-2` + `--acc-line` left border.

### 2.2 Progress Dashboard
*Evidence: `audit_dashboard_full.png`, `audit_dashboard.png`.*

**What's bland / AI-generated:**
- **Uniform 3×(1fr 1fr) card grid** — six equal boxes stacked. This is the archetypal "AI dashboard": no hierarchy, no hero metric, everything the same size. The eye has nowhere to land.
- **Emoji section headers** (◈ ▲ ✦ ◎ 🏅 📜) in accent-uppercase — every card shouts equally.
- **Character/hero row** is decent (level ring is the best element on the page) but the ring, xp bar and chips are cramped into the top-right; the left brand block and right char block don't feel balanced.
- **Skill map heatmap** uses tiny mono text cells with faint tinted bg — reads as a spreadsheet, not a "skill map." Legend is a mono footnote.
- **Axis bars** are thin flat tracks — functional but lifeless; labels are dim mono, all identical weight.
- **"Today's Quest" banner** is genuinely good (accent left-border, glow) — this is the template for how other cards should feel. Keep and elevate.
- **Empty states** ("No skills yet — run onboarding", "No quests yet.", "No attempts yet…") are bare sentences in big cards → the whole page reads half-built for a new user (`audit_dashboard_full.png` shows this starkly).

**Redesign direction — go bento (Awwwards pattern):**

- **Replace the uniform grid with a bento layout:** an asymmetric grid where the **Skill Map is the hero** (spans 2 cols / 2 rows), the **level/rank/XP "character" card** is a tall left column, and the smaller cards (quests, ai-gap, achievements, chronicle) fill varied 1×1 / 2×1 tiles around it. Example area map:
  ```
  grid-template-columns: repeat(6, 1fr);
  hero character card:  span 2 cols, span 2 rows
  Skill Map:            span 4 cols, span 2 rows   ← the star
  Today's Quest:        span 6 cols (full-width banner, keep)
  Axis bars:            span 3 cols
  AI-gap:               span 3 cols
  Achievements:         span 4 cols
  Chronicle:            span 2 cols
  ```
- **One hero metric.** Make the level ring bigger (96px), center it in the character card with the rank below and an animated conic-gradient XP ring around it (replaces the flat bar as the primary progress signal). This is the "land here first" element.
- **Skill map as a real heat-grid:** larger cells, rounded, with the level word replaced by a **filled dot + subtle bar** and color from the existing `LEVEL_COLOR` map; hover raises the cell and shows the rating in a tooltip chip. Add row/column hover highlighting. Keep the 4-color legend but style it as inline chips, not a footnote.
- **Axis bars → radial or thicker segmented bars** with the axis color, a subtle track inset shadow, and the value shown as a tabular-num on the right. Animate width-in on load.
- **Quiet the headers:** `h2` → `--dim` mono label + a small line icon; drop the accent-uppercase-on-everything.
- **Empty states become designed** (see §4): each empty card gets an icon, one line of copy, and a CTA button ("Run onboarding →"), not a bare sentence. Turn the new-user dashboard into an onboarding checklist ("Step 1 of 3: map your skills") — endowed-progress effect.

### 2.3 Journey (milestones / achievements / heatmap / XP curve)
*Evidence: `audit_journey_full.png`, `audit_journey.png`. **This is the worst-offending view.***

**What's broken (known dead-space defect, confirmed):**
- **Milestones card** = a full-width band containing *one sentence* ("Your journey begins…") → a tall empty rectangle. Even when populated, `.timeline` is a single vertical thread hugging the left edge, leaving 80% of the band empty.
- **Achievements** pack 9 tiles into a left-aligned `flex-wrap` → they fill the top-left and leave the **entire right half of the card empty** (`audit_journey_full.png`). Classic "stacked with dead space."
- **Activity heatmap** is a small 12×7 block floating in a big card with tons of empty space to its right; **XP-over-time card next to it is completely empty** ("Your XP curve appears as you practise.") — two half-empty cards side by side.
- **Locked achievements** use a 🔒 emoji + dashed border + `opacity:.6` — reads as broken/disabled, not "aspirational goal."
- No hero, no summary stats, no sense of *time* — ironic for a "Journey."

**Redesign direction:**

- **Journey hero = a stat ribbon** across the top: `DAYS ACTIVE · TOTAL XP · LONGEST STREAK · SKILLS MASTERED · BADGES x/9` as 4–5 tabular-num tiles. Instantly fills the top with meaning and gives the page a heartbeat.
- **Milestones → a horizontal timeline** (or a 2-column vertical rail) with connective line, node icons (line-icons, not emoji), and cards that alternate left/right so the band is *used*. Most-recent-first, with a subtle gradient fade at the ends. When empty, show 3 *ghosted future* milestones ("Level 5", "First mastery", "7-day streak") as dashed placeholders → the empty state teaches the reward loop (Duolingo aspiration pattern).
- **Achievements → a full-width responsive grid** `grid-template-columns:repeat(auto-fill,minmax(180px,1fr))` so tiles fill the whole card at every width (kills the right-side void). Earned tiles glow with their accent + a subtle sheen; **locked tiles keep full opacity** but go monochrome with a thin progress ring and `2/5` label — aspirational, not disabled. Retire the 🔒 for a line "lock" icon or, better, a dim version of the badge's own icon.
- **Heatmap gets a header row of month labels + weekday labels** (GitHub-style), fills its card width (`grid-auto-columns:1fr` capped), and pairs with a small "N practices this quarter" stat so it's not floating.
- **XP curve** — make it always render *something*: even with 0–1 points, show a baseline axis, a "0 XP" origin dot, and ghosted target lines at level thresholds (100/200/300 XP) so the card is never empty. When data exists, area-fill under the line with an `--acc` gradient, add end-point dot + last-value label, and light gridlines.
- Collapse the two half-empty side-by-side cards (heatmap + XP) into a **single wider "Activity" card** with the heatmap on top and the sparkline curve below, if data density stays low.

### 2.4 Skill Tree (Mermaid graph)
*Evidence: `audit_tree.png`.*

**What's bland:**
- Empty state is a centered gray sentence in a totally black full-height view — the single most "unfinished" screen in the app.
- Even when populated, it's a raw Mermaid `theme:'dark'` render — generic gray boxes with default Mermaid styling, zero brand. A Mermaid default graph is an instant "auto-generated" tell.
- The legend ("green = mastered · cyan = unlocked · dim = locked") is a plain dim line at top; the diagram is just dropped in a `.mermaid` box centered on the page.

**Redesign direction:**
- **Theme Mermaid to the brand:** pass a custom `themeVariables` (node fill = `--surface-1`, node border = state color from your palette, edge = `--line-2`, font = Rajdhani, mono for labels) or post-style the rendered SVG. Mastered nodes get `--acc` fill-glow, unlocked get `--cyan` border, locked get `--faint` dashed. This turns "default Mermaid" into "the Ekalavya skill constellation."
- **Frame it:** put the graph on a subtle dotted-grid or radial-vignette background (`--bg` radial like the rest of the app) inside a bordered stage with the legend as styled chips top-right, and a zoom/fit control (mono ghost buttons) — so it reads as an interactive map, not a floating image.
- **Empty state (see §4):** replace the lone sentence with an illustrated node-cluster placeholder (3–4 ghost nodes connected by dashed edges) + heading "Your skill tree isn't drawn yet" + CTA "Finish onboarding →". Teaches what the feature *will* look like.

### 2.5 Onboarding flow
*Rendered as `mode:'onboard'` in Practice (`audit_practice.png` shows the first-run onboarding kickoff).*

**What's bland:**
- First-run onboarding is just the normal Practice split with a welcome message on the left and an empty editor on the right — the empty editor during a *conversational* onboarding is confusing dead space, and there's no sense of "this is a special first-time flow."
- No progress indicator, no framing, no reduced chrome — a brand-new user sees the full HUD (`Lv 1`, empty xp bar), all four tabs, the editor, and a wall of black.

**Redesign direction:**
- **Dedicated onboarding chrome:** during `onboard` mode, collapse/hide the code editor column (it's not needed for a conversation) and give the chat column the full width with a centered max-measure (~680px), so the welcome reads like a warm intro, not a lonely bubble in a void.
- **Add a lightweight step rail** ("Getting to know you · 1 of ~5") using the endowed-progress pattern — even if the conversation is free-form, show momentum.
- **Suggested first answers** as chips (the reply affordance) so a new user is never staring at a blank input.
- Dim/disable the Progress/Journey/Skill-Tree tabs until onboarding completes (they're empty anyway) — removes the half-built feeling and focuses the first run.

### 2.6 "YOU DIED" death overlay
*Evidence: `audit_death.png`.*

**Assessment:** This is the **best, most human-crafted screen in the app** — the Dark Souls homage, red radial vignette, glowing pulse, "SOULS DROPPED" copy all land. It proves the team *can* make characterful UI. **Don't dilute it; refine it.**

**Refinements:**
- The `YOU DIED` uses Rajdhani — good, but tighten the letter-spacing consistency and consider a very subtle CRT scanline/grain overlay on the vignette for texture (2–3% opacity) to sell the terminal/game mood.
- Add a **short entrance sequence:** vignette fades in (already), then the text does a quick chromatic-aberration/red-shift settle (150ms), then the sub-copy and button fade up staggered. Cheap, high-impact, respects reduced-motion.
- The `CONTINUE` button is a bit plain — give it the same top-edge highlight + a red glow on hover to match the moment.
- Make the "-40 XP / streak broken" numbers **count down** with a tick animation rather than appearing static — reinforces loss aversion (the whole point of the mechanic).
- Mirror this quality on the **inverse moment:** the reclaim toast is currently a small pill. Consider a matching (but green, celebratory) "SOULS RECLAIMED" flash with the same production value — right now the punishment is beautiful and the reward is a plain toast. Balance them.

### 2.7 AI-Assistant drawer (aiinterview mode)
*Evidence: `audit_assist_panel.png`.*

**What's bland / broken:**
- The assistant panel is a violet-tinted box that **splits the right column awkwardly** (42% assistant / editor below), and the "Ask" button + input are **clipped at the right viewport edge** (same overflow defect as §2.1).
- Header is `🤖 AI Assistant — allowed here, but it's imperfect. Verify it.` — the emoji + inline hint reads as a placeholder, not a designed disclaimer.
- The panel and the main chat use *different* bubble styles (`.am` vs `.msg`) with no shared design language — feels like two different apps bolted together.
- Empty assistant log = another void.

**Redesign direction:**
- **Fix overflow first** (shared with §2.1): the right column needs inner padding; the assist input row must respect the container, not run to 100vw.
- **Distinguish by accent, not by inconsistency:** the assistant is the "AI is allowed but fallible" surface — theme it `--violet` (borders, header, avatar) but reuse the *same* message component, rail, and code-chrome as the main chat, so it feels like one product with a sub-mode.
- **Turn the disclaimer into a designed banner:** a slim violet-tinted strip with a warning line-icon + "AI assistance is on — it can be wrong. Your unaided score is tracked separately." This ties it to the dashboard's "Unaided vs AI-assisted" metric and makes the pedagogy legible.
- **Empty state:** "Ask the assistant anything — but you'll be graded on what you can do without it." + 2 example chips.
- Consider making the assistant a **collapsible right sub-panel or a tab** within the editor column rather than a fixed 42% split, so the editor keeps room and nothing clips.

---

## 3. Cross-Cutting Polish Details (the "handcrafted" layer)

- **Hairline seams over heavy borders:** use 1px gaps over a `--line-0` background for grid seams (Practice split, bento gutters) — crisper than 1px solid borders everywhere.
- **Top-edge highlight** (`--edge`) on every raised surface — the #1 "rendered by a designer" cue.
- **Focus rings:** a consistent `outline: 2px solid var(--acc); outline-offset:2px` on all interactive elements (currently inputs have none) — accessibility *and* polish.
- **Hover states on everything clickable:** tabs, cards, chat items, badges, cells — 120–220ms transitions. Their absence is a major "static template" tell.
- **Number roll-ups:** XP, level, streak animate on change (tabular-num + count transition). Level-up = a brief accent flash + the ring filling to 100 then resetting.
- **Skeletons** for: iframe-loaded Dashboard/Journey (currently a white/black flash while the iframe loads — replace with a matching skeleton), streaming first token, and Mermaid render.
- **Scrollbars:** style them (thin, `--surface-2` thumb) — default OS scrollbars in a cyberpunk UI are a tell.
- **Custom selection color:** `::selection{background:var(--acc-line);color:#04120c}`.
- **Grain/scanline option:** a *very* subtle (2–4%) noise or scanline overlay on the app background sells "terminal" without hurting readability. Behind a setting/reduced-motion.
- **Consistent line-icon set** replacing all emoji except the two brand moments (bow logo, death skull).
- **Iframe → in-place render (optional, deeper):** Dashboard and Journey are loaded via `<iframe src="/dashboard">`. Iframes cause the load flash, block shared tokens, and prevent shared motion. Consider fetching their HTML and injecting, or (later) rendering these views client-side from `/api/overview`. Not required for the redesign but removes a class of jank.

---

## 4. Empty-State System (turns the biggest weakness into a strength)

Every void identified above uses the **same reusable empty-state component**:
```
[ line-icon, 40px, --dim ]
[ Heading — Rajdhani, --ink, one short line ]
[ Subtext — Inter, --dim, one sentence of what appears here ]
[ CTA button — accent ghost, "Run onboarding →" ]
[ optional: ghosted preview of the populated state ]
```
Apply to: new-user Dashboard cards, empty Skill Tree, empty Journey milestones/XP, empty chat log, empty assistant log, empty Chats drawer. Where it's a *first action*, frame it as a mini-achievement / checklist step (endowed-progress: "Step 1 of 3"). Where it's *future content*, show a ghosted preview (dashed placeholders) so the user learns the reward. This single system erases the "half-built" feeling across the whole app.

---

## 5. Prioritized Punch-List

### P0 — Quick wins (hours; high impact, low risk)
1. **Kill emoji → line-icon set** (keep bow logo + death skull). *Biggest single de-slop move.*
2. **Fix Practice/assist right-column overflow & editor clipping** — wrap `#editor` in a bordered frame with inner gutter; constrain the assist input row. *Known defect.*
3. **Fix Journey dead space** — achievements → `auto-fill minmax(180px,1fr)` grid; milestones alternating/rail layout; merge or fill the empty XP/heatmap cards. *Known defect.*
4. **Add the surface ladder + top-edge highlight + hover lifts** — swap tokens, add `--elev-*`, add card hover transitions. *Transforms flatness immediately.*
5. **Quiet the headers** — `h2` from accent-uppercase to dim mono label; reserve accent for one metric/action per card.
6. **Design the empty states** (§4 component) across all voids.
7. **Style scrollbars, add focus rings, `::selection`, tabular numerals.**
8. **Unify duplicated tokens** — one shared `:root` block (webapp/dashboard/journey currently duplicate colors and drift).

### P1 — Structural (day-scale; medium risk)
9. **Bento layout for Dashboard** — Skill Map hero, character card tall, varied tiles.
10. **HUD → stat cluster** with wide glowing XP bar + tabular nums + fill animation.
11. **Chat message thread redesign** — speaker rail, code-block chrome (lang + copy), suggested-prompt chips.
12. **Editor "problem card" header + verify/results strip.**
13. **Journey hero stat ribbon** + timeline redesign + always-render XP curve.
14. **Chats drawer polish** — mode accent bars, relative time, hover action row, count in header.
15. **Skeletons** for streaming + iframe loads + Mermaid.
16. **Onboarding dedicated chrome** — full-width chat, hide editor, step rail, suggested answers, dim other tabs.

### P2 — Deep / delightful (multi-day)
17. **Theme Mermaid skill tree to the brand** + framed interactive stage + illustrated empty state.
18. **Number roll-ups + level-up celebration** + balanced "SOULS RECLAIMED" flash to match death quality.
19. **Death overlay entrance sequence** + count-down numbers + optional scanline grain.
20. **Radial/segmented axis bars + interactive heat-grid** with hover highlighting.
21. **Retire iframes** for Dashboard/Journey → client-render from `/api/overview` for shared tokens + motion (optional).
22. **Subtle grain/scanline overlay** + custom cursor accents (behind reduced-motion).

---

## 6. Award References — exactly what to emulate

| Reference | Steal this, specifically |
|---|---|
| **Linear** (design refresh writeups) | The **surface ladder** (`#08→#0f→#16→#23` near-blacks, tinted not pure black); **hairline 0.5–1px borders instead of shadows**; the **6% white top-edge highlight** on lifted panels; **accent as a flashlight** (only on actions/focus, never decoration); tiny radius/spacing/type vocabulary; light font weights + tight tracking over bold. → Directly informs §1.1, §1.5, §3. |
| **Vercel Geist** | **Tabular numerals everywhere** metrics appear (XP, level, ratings, timestamps) — the "engineering-grade" tell; **accent as punctuation** in an otherwise neutral field; dark-mode-as-canonical; consistent action/secondary/escape button vocabulary. → §1.2, §1.1. |
| **Warp / Raycast** | **Frequency-gated motion** (celebrate rare events like level-up/death; keep frequent actions instant); block-based command/result UI → the editor "problem card + results strip" pattern; gradient accent used sparingly on a dark IDE chrome. → §1.6, §2.1. |
| **Awwwards bento-grid winners** (Paradigm Solutions, Artone Studio, Design Waves) | **Asymmetric bento** with a clear hero tile + varied tile sizes and micro-interactions (glow/gradient on hover) — the fix for the uniform 2-col dashboard. → §2.2. |
| **Duolingo** | **Loss-aversion streak** made highly visible (your death mechanic already nails this — extend it: streak-freeze/repair, visible streak in HUD); **tiered/aspirational badges** shown even when locked (full-color aspiration, not grayed-disabled); color = consistent meaning (green success / amber streak / red loss). → §2.3, §2.6. |
| **GitHub contribution graph** | **Activity heatmap chrome:** month + weekday axis labels, consistent cell sizing filling width, hover tooltip with date + count. → §2.3. |
| **Empty-state best practice** (Pencil&Paper / UXPin) | Empty ≠ void: **icon + heading + one-line purpose + CTA**, and turn first-actions into mini-achievements / checklist (endowed-progress). Ghosted previews of the populated state teach the reward loop. → §4. |
| **Skeleton-screen best practice** (LogRocket / Carbon) | Show skeletons within ~300ms, **match final layout**, cross-fade to content, only on containers/lists/cards (not buttons); optimistic UI for frequent low-risk actions. → §3 (streaming + iframe loads). |

---

## 6.5 Committing to a bold aesthetic direction (frontend-design skill principles)

The audit above fixes *craft*. But "not bland" also requires a **committed point of view** — the frontend-design skill's core warning is that AI slop comes from timid, evenly-distributed, "safe" choices. Ekalavya already owns a strong lane; the job is to **push it further, not soften it**. Decision: commit hard to **"terminal-as-dojo / cyberpunk RPG"** — dark, characterful, game-like, with the Sanskrit creed and the Dark-Souls death moment as anchors. Concrete implications the redesign should adopt:

- **Pick an extreme and execute with precision.** The death overlay is the tonal north star — every other surface should feel like it belongs in the *same game*. Right now the dashboard/journey feel like a generic SaaS admin panel wearing the same colors. Bring the *character* (the dojo/archer/souls metaphor) into the ambient design of every view, not just the punishment screen.
- **Typography tension to resolve (flagged):** the frontend-design skill explicitly calls out **Inter** and system fonts as a generic "AI" tell. Ekalavya's identity *locks* Inter for body — that's a legitimate constraint and Inter is fine as a workhorse. **Recommendation:** keep Inter for long prose (chat, descriptions) where readability rules, but **lean much harder on Rajdhani + JetBrains Mono for all UI chrome** (labels, metrics, nav, chips, headers, buttons) so the *characterful* fonts dominate the visible surface and Inter recedes to body text only. This keeps the identity while removing the "Inter everywhere" flatness. (If the owner is open to it, an optional upgrade: swap Inter for a slightly more distinctive humanist sans for body — but this is a judgment call for the owner, not a required change.)
- **Atmosphere over flat fills (skill: backgrounds).** The app already has two radial gradients on `--bg` — good instinct, currently underused. Extend it: a **very subtle gradient-mesh + noise/grain layer** behind content, faint scanlines on framed stages (editor, skill-tree, death), and layered transparency so surfaces feel like glass over a lit substrate rather than opaque cards. This is the difference between "dark theme" and "atmosphere."
- **One orchestrated page-load reveal per view (skill: motion).** More memorable than scattered micro-interactions: on each view mount, **stagger the entrance** — hero/HUD first, then cards cascade in with `animation-delay` (40–60ms steps), XP bars/rings fill from zero, numbers roll up. One well-timed 400ms cascade per view = instant "crafted." Gate behind `prefers-reduced-motion`.
- **Grid-breaking / asymmetry (skill: spatial composition).** The bento move in §2.2 is exactly this; extend the instinct — let the level ring or a hero stat *overlap* a card edge, let the skill-tree stage bleed to the gutter, break the rigid symmetry that currently makes every view feel machine-laid.
- **A signature memorable element.** The skill asks: "what's the one thing someone remembers?" Ekalavya's answer should be deliberate — candidates: the **YOU DIED / SOULS RECLAIMED loss-aversion loop** (strongest — lean into it), the **animated XP/level ring**, or a **living skill-constellation** skill tree. Pick one and over-invest in it so there's a clear signature, rather than spreading polish evenly.

## 7. One-paragraph brief for the implementing engineer

Unify the duplicated `:root` into a single shared token block and introduce a **4-step surface ladder + elevation recipe with a 6% top-edge highlight** — this is what turns flat colored rectangles into physical layers. **Replace every emoji with a monochrome line-icon set** (keep only the bow logo and the death skull) and **quiet the section headers** so the accent becomes a flashlight, not paint. Fix the two structural defects (Practice/assist **right-column overflow + editor clipping**, Journey **dead-space stacking**). Re-lay the **Dashboard as a bento grid** with the Skill Map as hero and the level ring as the one place-your-eye metric, and give **Journey a stat-ribbon hero** plus timeline/heatmap/XP treatments that always render something. Add **hover transitions, focus rings, tabular numerals, styled scrollbars, skeletons, and a single reusable empty-state component** everywhere there is currently a void. Preserve — and slightly extend — the **YOU DIED** overlay, which already proves this product can look handcrafted; make the reward moments match its production value. Do it token-first so the whole app upgrades from one place.
