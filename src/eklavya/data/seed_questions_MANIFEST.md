# Seed Interview-Question Bank — Manifest

`seed_questions.json` is the initial, curated interview-question bank Eklavya ships
with so a fresh install isn't empty. A backend loader imports it into each new user's
`questions` table via `add_question(question, topic, difficulty, role, company, source)`
(deduped on `question` — the table has a UNIQUE index on that column).

## Schema

Each item is an object with exactly these six keys (matching `add_question(...)`):

```json
{
  "question": "self-contained question text a tutor can pose as-is",
  "topic": "free tag e.g. arrays | system-design | ml | rag | llm | statistics | sql | behavioral",
  "difficulty": "easy | medium | hard",
  "role": "swe | senior-swe | ml-engineer | ai-engineer | data-scientist | \"\"",
  "company": "ONLY if the source genuinely attributes it, else \"\"",
  "source": "url or list name"
}
```

Empty string `""` means "unknown / not applicable". The loader/DB stores empty
strings as NULL (see `tools.add_question`); the seed file uses `""` per the shared
contract with the backend agent.

## Totals

- **322 questions**, de-duplicated by question text (case-insensitive).
- **Every** question carries a `source`.
- Difficulty mix: **74 easy · 179 medium · 69 hard**.

## Coverage by topic

| Topic | Count |
|---|---|
| ml | 47 |
| llm | 40 |
| behavioral | 30 |
| rag | 29 |
| system-design | 25 |
| statistics | 23 |
| deep-learning | 20 |
| sql | 20 |
| trees | 13 |
| dynamic-programming | 11 |
| ml-system-design | 10 |
| graphs | 8 |
| strings | 7 |
| arrays | 6 |
| bit-manipulation | 6 |
| intervals | 5 |
| linked-list | 5 |
| agents | 4 |
| heap | 3 |
| matrix | 3 |
| binary-search | 2 |
| greedy | 2 |
| stack / two-pointers / design | 1 each |

DSA topics (arrays, strings, hashing, two-pointers, trees, graphs, DP, greedy,
intervals, linked-list, heap, matrix, bit-manipulation, binary-search, stack, design)
together account for ~85 questions — the full canonical **Blind 75** set plus a few
common extras (LRU Cache, Merge Two Sorted Lists, etc.).

## Coverage by target role

data-scientist 90 · swe 74 · ai-engineer 73 · ml-engineer 30 · senior-swe 25 ·
`""` (role-agnostic, mostly behavioral) 30.

## Sources used

| Area | Source |
|---|---|
| DSA (Blind 75) | designgurus.io/blind75 + LeetCode discuss "Blind 75" |
| System design | designgurus.io FAANG top-25 system-design list |
| Machine learning | GeeksforGeeks ML interview questions; Analytics Vidhya bias-variance guide |
| Deep learning | youssefHosni *Data-Science-Interview-Questions-Answers* (GitHub); GeeksforGeeks |
| LLM / transformers | amirteymoori.com *50 AI & LLM Engineer Interview Questions (2025)* |
| RAG / agents | DataCamp *Top 30 RAG Interview Questions* |
| Statistics / probability | DataLemur *Top 20 Statistics Data-Science Interview Questions* |
| SQL / data | Common SQL interview lists (GeeksforGeeks / DataLemur) |
| Behavioral (Amazon) | DataLemur *Amazon Behavioral Interview Guide* |
| Behavioral (general) | Common STAR-method interview guides |
| ML system design | Common ML-system-design interview guides |

All gathered via live web search (Serper / WebFetch) in August 2026.

## Honesty policy for company attribution

`company` is set **only** where the source genuinely attributes the question to a
specific company. Applying that rule strictly:

- **16 questions are company-attributed — all to Amazon**, taken from DataLemur's
  *Amazon Behavioral Interview Guide*, which explicitly presents them as Amazon's
  leadership-principles behavioral questions.
- **The other 306 questions have `company: ""`.** They come from general "top /
  most-common interview questions" lists (Blind 75, FAANG system-design roundups,
  ML/LLM/RAG/stats guides). These lists describe questions *frequently asked across*
  big-tech interviews but do **not** attribute any individual question to one named
  company — so tagging them with Meta/Google/etc. would be fabricated. We leave
  `company` blank rather than guess.

No attribution was invented. Where a list named several companies for one question
(e.g. the community system-design roundup), we did **not** copy those multi-company
tags onto individual items, because such crowd-sourced "asked at X, Y, Z" claims are
not reliable single-company attribution.

## Question quality rules applied

- Each question is **self-contained** and posable as-is by a tutor (LeetCode problems
  were rewritten from bare titles into full one-line prompts, keeping the canonical
  name in parentheses for recognizability).
- **No answers** are embedded.
- **No near-duplicate paraphrases**: deduped on question text; overlapping items across
  source lists (e.g. "explain self-attention", "what is overfitting") appear once.

## Regeneration

The file was produced by `build_seed.py` at the repo root (a one-off generator, not part
of the shipped package). Re-run `python3 build_seed.py` from the repo root to rebuild
and re-print the counts.
