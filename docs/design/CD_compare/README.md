# Ekalavya — C × D Comparison & Selection Playground

A single self-contained file (`index.html`) that puts the two finished art directions
for **Ekalavya** (the AI coding tutor) side by side so the founder can compare them,
pick elements from each, leave comments, and export a portable summary for **Claude Design**
and a coding agent.

- **Direction C** — *Raji: Cinematic Indian-Epic Game UI* (`../C_raji_game/index.html`) — gold, dramatic, 17-petal mandala HUD, radial mobile nav.
- **Direction D** — *The Synthesis / Forest Manuscript* (`../D_synthesis/index.html`) — leads with the outsider story, paper-guru voice, walkable forest-map skill overview.

Both directions honor the same soul: **Ekalavya**, the Bhil outsider refused by Droṇa,
who taught himself alone in the forest before a clay statue. The real styles, palettes,
fonts, and SVG components from C and D are reused verbatim (namespaced `.c-scope` / `.d-scope`),
not reinvented.

## What's in the file

1. **View both fully** (header toggle) — each direction rendered as a complete top-to-bottom set of screens.
2. **Element-by-element** — 18 rows, each showing the **C version beside the D version**:
   wordmark/hero, outsider onboarding, character HUD / rank medallion, XP indicator,
   streak, achievement toast, level-up ceremony, loss screen, quest banner, buttons+inputs,
   card system, skill-tree overview (mandala vs forest-map), single-track view,
   activity heatmap, XP-over-time curve, practice (chat+editor) screen, dashboard, mobile nav.
3. **Pick & choose** — per row: **Prefer C / Prefer D / Mix / Undecided** plus a notes textarea.
   Everything persists to `localStorage` (key `ekalavya_cd_selections_v1`).
4. **§ XP alternatives** — six alternative progress representations (forest trail/journey bar ★,
   radial ring, filling quiver, arrow-to-bullseye, growing tree/diya, numeric+arc baseline),
   each with its own preference + notes control. The **forest trail** is the recommended primary
   readout for "how far have I come"; the bowstring-draw is proposed as a momentary XP-gain
   animation only.

## Export & where selections land

Click **"Export selections + comments"** (top right). It renders your choices on-page and lets you:

- **Download `.md`** → `ekalavya_cd_selections.md` (human-readable tally + per-element table + XP pick).
- **Download `.json`** → `ekalavya_cd_selections.json` (machine-readable; a coding agent reads this verbatim).
- **Copy** the current view to clipboard.

Selections survive a page reload (localStorage). **Reset picks** clears them.

## Claude Design workflow

1. Open **claude.ai/design**.
2. **Import** this folder (or `index.html`) as context.
3. Use the inline preference buttons + note fields here (and Claude Design's own commenting)
   to refine toward a converged aesthetic.
4. **Export** from Claude Design.
5. Hand off to **Claude Code** to build the final app in `src/` (which this file never touches).

## Notes

- Self-contained: inline CSS + inline SVG, only Google Fonts over CDN. Open `index.html` directly.
- `preview.png` / `preview_mobile.png` are reference screenshots (1280 and 390 wide).
- This is a design artifact for founder review — it does **not** modify the real app.
