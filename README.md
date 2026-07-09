# Ekalavya 🏹

**A coding tutor that lives in your terminal and makes you *earn* the answer.**

> स्वाध्याय · साधना · सिद्धि — *self-study · devoted practice · mastery*

I built this because AI quietly took the joy out of coding for me. The good part
of programming was always the struggle — wrestling a hard problem for hours until
it finally clicks. Reaching for an assistant every time skips the struggle, and
the struggle was where the learning lived. Ekalavya is my attempt to get that
back: it teaches Socratically, drills me daily, tracks what I actually know, and
refuses to just hand me the solution.

It's named after the self-taught archer from the Mahābhārata who reached mastery
alone, through sheer devotion — no teacher handing him anything.

<p align="center">
  <img src="docs/screenshots/tui.png" width="80%" alt="Ekalavya practice session in the terminal">
</p>

## What it does

- **Onboards you once** — a Socratic interview that figures out where you're
  strong, where you're weak, and what you're actually trying to build, then saves
  a profile it improves over time.
- **Drills you daily** — small, gated exercises aimed at your weakest spots. You
  state your confidence *first*, then attempt it yourself. Your code runs in a
  sandbox and is graded against hidden tests.
- **Remembers with spaced repetition** — concepts come back exactly when you're
  about to forget them (FSRS).
- **Scores calibration, not just correctness** — being confident *and wrong* (the
  illusion of knowing) costs you far more than an honest "I'm not sure." That's
  the signal that actually moves you forward.
- **Won't let you cheat** — the built-in editor is where you write code. Paste an
  answer from an AI and you *die*, Souls-style: souls dropped, streak broken. It
  only counts if it came from your own head.
- **Learns from your real code** — point it at a repo you work on and it tailors
  your practice to the frameworks you actually use.
- **Shows your progress** — a mastery heatmap, streak, level, and XP.

## Screenshots

| Practice (TUI) | Progress dashboard |
|---|---|
| ![TUI](docs/screenshots/tui.png) | ![Dashboard](docs/screenshots/dashboard.png) |

Paste an answer from an AI, and:

<p align="center">
  <img src="docs/screenshots/anticheat.png" width="70%" alt="You Died — pasted code is penalised">
</p>

<p align="center">
  <img src="docs/screenshots/cli.png" width="60%" alt="Ekalavya CLI">
</p>

## Getting started

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/). It talks to any
Anthropic-compatible model endpoint — I use GLM and MiniMax.

```bash
uv sync --extra agent --extra tui --extra web
cp .env.example .env          # add a key (GLM and/or MiniMax)
uv run eklavya doctor         # check the setup
uv run eklavya onboard        # one-time — builds your baseline
uv run eklavya tui            # then practice
```

## Commands

| Command | What it does |
|---|---|
| `eklavya onboard` | One-time Socratic interview → your baseline mastery map |
| `eklavya tui` | The immersive terminal UI, with a built-in code editor |
| `eklavya practice --minutes N` | A plain-CLI practice session |
| `eklavya serve` | A local web dashboard of your progress |
| `eklavya scan PATH` | Tailor your pillars to a repo you work on (asks first) |
| `eklavya doctor` | Check Python, dependencies, providers, and state |

## How it works

The teaching brain is an agent (built on
[deepagents](https://github.com/langchain-ai/deepagents) / LangGraph). Everything
that has to be reliable — running code, grading, ratings, spaced-repetition
scheduling, streaks — is plain Python the agent calls as tools. The agent decides
*when*; the tools decide *what actually happens*, so your record never depends on
a model remembering. State lives locally in SQLite; the learner profile is a
markdown file you can read.

## Running the tests

```bash
uv run pytest        # fast, offline, no API key needed
```

There are also a few live checks under `scripts/` that hit a real model to verify
the providers and the end-to-end grading loop.

## License

MIT
