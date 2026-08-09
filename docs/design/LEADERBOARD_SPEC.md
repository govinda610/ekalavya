# Deployed Leaderboard — Spec (decisions locked 2026-08-09)

A competitive board on the **deployed multi-user** app where opted-in users compare stats.
Local/single-user mode: the board is simply empty/hidden (only meaningful with multiple accounts).

## Locked decisions
- **Identity:** each user picks a public **handle** (unique, 3–24 chars). Email + real name are NEVER
  shown. Handle chosen at opt-in (editable later in Settings).
- **Visibility:** **opt-in**, private by default. A user appears ONLY after opting in. Non-opted-in
  users still see the board, topped by a reminder CTA: "You're not on the board yet — opt in from
  Settings to compete." Opting out removes them immediately.
- **Default rank:** **Level/XP** descending. **All columns sortable** (click header to re-sort).
- **Columns:** Rank · Handle · Level/XP · Current streak (days) · Questions solved · Achievements
  unlocked · Forest progress (mastered groves / total → %) · **Unassisted skill** (AI-off Elo,
  visually featured as the prestige/honesty flex) · **Eklavya Score** (composite, sortable).
- **Your row:** highlighted; a "You are #N of M" banner. Ties broken by Eklavya Score, then handle.
- **Scope:** all-time, global across opted-in users. (Weekly/period board = possible later, out of scope now.)
- **Timing:** build BEFORE the Lightsail deploy; ships day one.

## Eklavya Score (transparent composite — shown in a tooltip)
Each component is mapped to a 0–1000 sub-score, then weighted. Weights sum to 1.0:
- **40% Unassisted skill** — the AI-off rating (the honest core of the product) →
  `clamp((rating - 800) / 12, 0, 1000)` (≈800 floor → 0, ≈12800 → capped 1000; tune to real range).
- **20% Mastery** — forest progress → `mastered_groves / total_groves * 1000`.
- **20% XP** — `min(xp, XP_CAP) / XP_CAP * 1000` (XP_CAP chosen from real data spread).
- **10% Streak** — `min(streak_days, 100) / 100 * 1000`.
- **10% Achievements** — `unlocked / total_achievements * 1000`.

`EklavyaScore = round(0.40*u + 0.20*m + 0.20*xp + 0.10*s + 0.10*a)` → 0–1000 integer.
Tooltip states the weighting plainly ("40% unassisted skill · 20% mastery · 20% XP · 10% streak ·
10% achievements") so nothing is a black box. Normalization constants live in one place and are easy
to retune once real user data exists.

## Data model (central multi-user store)
The central `users` store gains per-user leaderboard fields (additive, guarded migration):
- `lb_opted_in` (bool, default 0)
- `lb_handle` (text, unique when non-null; case-insensitive unique)
- `lb_joined_at` (ts)
Per-user metrics stay in each user's own SQLite; the board aggregates them at read time.

## Aggregation (privacy-safe, small-N)
- A `leaderboard()` builder iterates ONLY opted-in users, opens each one's store read-only, pulls the
  metric set (xp/level, streak, questions-solved count, achievements unlocked, mastered/total groves,
  unassisted rating), computes Eklavya Score, returns rows sorted by the requested column.
- Light in-process cache (e.g. 30–60s TTL) so a page load doesn't re-scan every DB each time.
- Never expose email/real name/raw internal ids — only handle + the numeric columns.
- Reuses the existing per-user metric helpers (report/effectiveness modules); no new truth source.

## API
- `GET /api/leaderboard?sort=<col>&dir=<asc|desc>` → `{me:{opted_in, handle, rank}, rows:[...], total}`.
  Rows carry handle + all columns; `me.rank` lets the UI show "You are #N".
- `POST /api/leaderboard/opt-in` `{handle}` → validates+uniquifies handle, sets opted_in.
- `POST /api/leaderboard/opt-out`.
- All require auth; handle validation (charset, length, uniqueness, profanity-light optional).

## UI
- New **Leaderboard** nav entry (desktop + mobile). Forest/award-tier styling consistent with the app.
- Sortable table, your row highlighted, prestige styling on the Unassisted-skill column, Eklavya Score
  with the explainer tooltip.
- Non-opted-in state: full board visible + top CTA banner linking to the Settings toggle.
- **Settings:** "Leaderboard" section — Join/Leave toggle + handle field (pick/edit), with a note that
  only the handle + stats are shown, never email/name.

## Constraints
- Additive, guarded migration (copy-verify pattern); MUST NOT alter existing user data/handles/streaks.
- Deployed-only behavior gated by the existing DEPLOYED/multi-user posture; local mode hides the board.
- Tests: migration additive + reversible; opt-in/opt-out flips visibility; non-opted-in user is absent
  from rows; handle uniqueness enforced; sorting each column; Eklavya Score determinism; a user can
  never see another's email/name via any leaderboard route.
- No AI attribution in commits. No push / no deploy without explicit approval.
