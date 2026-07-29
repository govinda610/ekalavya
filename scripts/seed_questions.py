"""Seed the interview QUESTION BANK with real, high-quality interview questions.

Run:   uv run python scripts/seed_questions.py            (seeds the db)
       uv run python scripts/seed_questions.py --count    (just report counts, no writes)

SOURCING & HONESTY
------------------
Every question below is a REAL interview question or a faithful paraphrase of one that
is widely and publicly documented. Sources fall into three honest buckets, recorded in
the `source` column:

  • curated:<list>  — from well-known PUBLIC, curated study lists (Blind 75 / NeetCode
    150 / Grokking-style System Design / "Cracking the Coding Interview" topics /
    Chip Huyen's ML-interviews book / the STAR behavioral canon). These lists publish
    the QUESTIONS themselves; we do NOT copy any answers or paywalled content, and we do
    NOT scrape LeetCode/HackerRank (anti-bot + ToS). We reference the canonical problem.
  • knowledge      — standard, universally-asked questions from the author's own domain
    knowledge (e.g. "explain the bias-variance tradeoff"); not attributable to one list.

COMPANY TAGGING
---------------
`company` is set ONLY where a question is genuinely and publicly associated with that
company (e.g. system-design prompts famously asked at that company, or a behavioral value
that company is publicly known to probe). When in doubt, company is left blank. We never
fabricate a company tag — a blank company is the honest default.

Idempotent: INSERT OR IGNORE on the unique question text, so re-running never duplicates.
"""

from __future__ import annotations

import sys

from eklavya.db import connect, init_db

# Each row: (question, topic, difficulty, role, company, source)
# role: swe | ml | ai-eng | ds | quant | any        difficulty: easy | medium | hard | ""
QUESTIONS: list[tuple[str, str, str, str, str, str]] = []


def _add(rows, topic, difficulty, role, company, source):
    for q in rows:
        QUESTIONS.append((q, topic, difficulty, role, company, source))


# =====================================================================================
# 1. DSA / ALGORITHMS  — the Blind 75 / NeetCode 150 canon (public curated lists).
# =====================================================================================
_add([
    "Two Sum: return indices of the two numbers in an array that add up to a target.",
    "Best Time to Buy and Sell Stock: maximize profit from a single buy/sell.",
    "Contains Duplicate: determine whether any value appears at least twice.",
    "Valid Anagram: check whether two strings are anagrams of each other.",
    "Valid Palindrome: check whether a string is a palindrome, ignoring non-alphanumerics.",
    "Merge Two Sorted Lists into one sorted linked list.",
    "Reverse a singly linked list, both iteratively and recursively.",
    "Invert / mirror a binary tree.",
    "Maximum Depth of a Binary Tree.",
    "Binary Search on a sorted array; explain the invariant and off-by-one pitfalls.",
    "Climbing Stairs: count distinct ways to reach the top (DP intro).",
    "Fizz Buzz — and how you'd keep it extensible.",
], "arrays-strings-basics", "easy", "swe", "", "curated:Blind75/NeetCode150")

_add([
    "Group Anagrams: group a list of strings that are anagrams of each other.",
    "Top K Frequent Elements in an array.",
    "Product of Array Except Self, without using division.",
    "Longest Consecutive Sequence in an unsorted array (O(n)).",
    "Longest Substring Without Repeating Characters (sliding window).",
    "Longest Repeating Character Replacement (sliding window).",
    "Minimum Window Substring containing all chars of a target string.",
    "3Sum: find all unique triplets that sum to zero.",
    "Container With Most Water.",
    "Two Sum II on a sorted array (two-pointer).",
    "Valid Parentheses using a stack.",
    "Min Stack: stack supporting push/pop/top/getMin in O(1).",
    "Daily Temperatures (monotonic stack).",
    "Search in Rotated Sorted Array.",
    "Find Minimum in Rotated Sorted Array.",
    "Koko Eating Bananas (binary search on the answer).",
    "Reorder List (linked list).",
    "Remove Nth Node From End of List.",
    "Linked List Cycle detection (Floyd's tortoise and hare).",
    "Add Two Numbers represented as linked lists.",
    "LRU Cache: design and implement with O(1) get/put.",
    "Number of Islands (grid DFS/BFS).",
    "Clone Graph.",
    "Course Schedule: detect a cycle / topological sort of prerequisites.",
    "Pacific Atlantic Water Flow.",
    "Validate a Binary Search Tree.",
    "Lowest Common Ancestor of a BST.",
    "Binary Tree Level Order Traversal (BFS).",
    "Kth Smallest Element in a BST.",
    "Construct Binary Tree from Preorder and Inorder traversal.",
    "Implement a Trie (prefix tree) with insert/search/startsWith.",
    "Word Search in a grid (backtracking).",
    "Combination Sum (backtracking).",
    "Permutations of a distinct-integer array (backtracking).",
    "Subsets: generate the power set.",
    "House Robber and House Robber II (circular) — DP.",
    "Coin Change: fewest coins to make an amount (DP).",
    "Longest Increasing Subsequence.",
    "Word Break: can a string be segmented using a dictionary?",
    "Unique Paths in a grid (DP).",
    "Longest Common Subsequence.",
    "Maximum Subarray (Kadane's algorithm).",
    "Jump Game: can you reach the last index?",
    "Merge Intervals.",
    "Insert Interval.",
    "Non-overlapping Intervals: min removals to make intervals non-overlapping.",
    "Meeting Rooms II: minimum conference rooms required.",
    "Rotate a matrix 90 degrees in place.",
    "Spiral Matrix traversal.",
    "Set Matrix Zeroes in place.",
], "algorithms", "medium", "swe", "", "curated:Blind75/NeetCode150")

_add([
    "Trapping Rain Water.",
    "Median of Two Sorted Arrays in O(log(m+n)).",
    "Merge k Sorted Lists.",
    "Serialize and Deserialize a Binary Tree.",
    "Binary Tree Maximum Path Sum.",
    "Word Ladder: shortest transformation sequence.",
    "Find Median from a Data Stream (two heaps).",
    "Alien Dictionary: derive character order via topological sort.",
    "Longest Valid Parentheses.",
    "Edit Distance (Levenshtein) between two strings.",
    "Regular Expression Matching with '.' and '*'.",
    "Sliding Window Maximum (monotonic deque).",
    "Design Twitter: post/follow/getNewsFeed.",
], "algorithms", "hard", "swe", "", "curated:Blind75/NeetCode150")

_add([
    "Reverse the bits of a 32-bit unsigned integer.",
    "Number of 1 Bits (Hamming weight).",
    "Counting Bits for every number from 0 to n.",
    "Missing Number in an array of 0..n.",
    "Sum of Two Integers without using + or -.",
], "bit-manipulation", "easy", "swe", "", "curated:NeetCode150")


# =====================================================================================
# 2. LANGUAGE / CORE-CS FUNDAMENTALS  (verbal screens; widely asked).
# =====================================================================================
_add([
    "Explain Python's GIL — what it protects, and how it affects CPU- vs I/O-bound code.",
    "Difference between a list, tuple, set, and dict; when would you pick each?",
    "How do Python decorators work? Write one that memoizes.",
    "Explain generators and the yield keyword; how do they save memory?",
    "What is the difference between deepcopy and shallow copy?",
    "How does Python manage memory — reference counting vs the cyclic garbage collector?",
    "What are *args and **kwargs, and when do you use them?",
    "Explain the difference between `is` and `==`.",
    "What is a context manager, and how would you write one two different ways?",
    "Mutable default argument pitfall — why is `def f(x=[])` dangerous?",
    "Difference between multiprocessing, threading, and asyncio in Python.",
    "What is duck typing, and how does it shape Python API design?",
], "python-fundamentals", "medium", "any", "", "knowledge")

_add([
    "Explain a hash table: expected O(1) lookups, collisions, and load factor.",
    "Compare a stack and a queue and give a real use case for each.",
    "Big-O of common operations on array vs linked list vs hash map vs balanced BST.",
    "What is the difference between BFS and DFS, and when do you prefer each?",
    "Explain dynamic programming vs greedy; how do you recognize a DP problem?",
    "What is amortized analysis? Explain it with a dynamic array's push.",
    "Explain a heap / priority queue and its complexity for the top-k pattern.",
], "cs-fundamentals", "medium", "any", "", "knowledge")

_add([
    "What are ACID properties in a database?",
    "SQL vs NoSQL — when would you choose each?",
    "What is a database index, and what is the cost of adding one?",
    "Explain normalization vs denormalization and the tradeoff.",
    "Difference between INNER, LEFT, RIGHT, and FULL OUTER JOIN.",
    "What is the N+1 query problem and how do you fix it?",
    "Write a SQL query for the second-highest salary in a table.",
    "Explain transactions and isolation levels (read committed vs serializable).",
], "databases-sql", "medium", "any", "", "knowledge")

_add([
    "What happens when you type a URL into the browser and press enter?",
    "Explain the difference between TCP and UDP.",
    "What is the difference between REST and gRPC? When choose each?",
    "Explain idempotency in HTTP and why PUT vs POST matters.",
    "What is a race condition, and how do you prevent one?",
    "Explain a deadlock and the four conditions required for it.",
    "What is eventual consistency, and where is it acceptable?",
], "systems-networking", "medium", "any", "", "knowledge")


# =====================================================================================
# 3. SYSTEM DESIGN  (Grokking / Alex Xu canon; company tags only where genuinely famous).
# =====================================================================================
_add([
    "Design a URL shortener (like TinyURL): key generation, redirects, and scale.",
    "Design a rate limiter (token bucket vs sliding window).",
    "Design a distributed key-value store / cache.",
    "Design a pastebin.",
    "Design a web crawler.",
    "Design a notification / push system.",
    "Design an API rate-limiting and quota system for a public API.",
    "Design a distributed unique-ID generator (Snowflake-style).",
    "Design a consistent-hashing scheme for a sharded cache.",
], "system-design", "hard", "swe", "", "curated:GrokkingSystemDesign")

_add([
    "Design a news feed (fan-out on write vs read tradeoffs).",
], "system-design", "hard", "swe", "Meta", "curated:GrokkingSystemDesign")
_add([
    "Design YouTube / a video-streaming service (upload, transcode, CDN, playback).",
], "system-design", "hard", "swe", "Google", "curated:GrokkingSystemDesign")
_add([
    "Design a ride-sharing service (matching drivers and riders, surge pricing).",
], "system-design", "hard", "swe", "Uber", "curated:GrokkingSystemDesign")
_add([
    "Design a chat / messaging system (delivery, presence, ordering).",
], "system-design", "hard", "swe", "WhatsApp", "curated:GrokkingSystemDesign")
_add([
    "Design a typeahead / search autocomplete service.",
], "system-design", "hard", "swe", "Google", "curated:GrokkingSystemDesign")
_add([
    "Design a global file-sync / storage service like Dropbox.",
], "system-design", "hard", "swe", "Dropbox", "curated:GrokkingSystemDesign")


# =====================================================================================
# 4. ML / DATA-SCIENCE FUNDAMENTALS  (Chip Huyen's ML-interviews canon + standard theory).
# =====================================================================================
_add([
    "Explain the bias-variance tradeoff.",
    "What is overfitting, and name three ways to prevent it.",
    "Difference between L1 and L2 regularization; why does L1 induce sparsity?",
    "Explain precision, recall, F1, and when accuracy is a misleading metric.",
    "What is ROC-AUC, and how do you interpret it?",
    "Explain cross-validation and why a single train/test split can mislead.",
    "What is data leakage? Give a concrete example and how to catch it.",
    "How do you handle class imbalance?",
    "Explain the difference between bagging and boosting.",
    "How does a decision tree decide splits (Gini vs entropy)?",
    "Explain how gradient boosting (XGBoost) works at a high level.",
    "What is the curse of dimensionality?",
    "How does PCA work, and what does it optimize?",
    "Explain k-means; how do you choose k and what are its failure modes?",
    "Difference between generative and discriminative models.",
    "Explain the vanishing/exploding gradient problem and how to mitigate it.",
    "What is dropout and why does it work?",
    "Explain batch norm vs layer norm and when each is used.",
    "Why do we use cross-entropy loss for classification rather than MSE?",
    "Explain gradient descent variants: SGD, momentum, Adam.",
    "What is the difference between a parameter and a hyperparameter?",
    "How would you detect and handle covariate shift / model drift in production?",
], "ml-fundamentals", "medium", "ml", "", "curated:ChipHuyen-MLInterviews")

_add([
    "Design the ML system for a recommendation feed: features, model, serving, feedback loop.",
    "How would you build a fraud-detection system end to end?",
    "Design an A/B testing framework and explain how you'd measure lift.",
    "How do you decide between an offline metric and an online metric?",
    "Walk through building an ML model from problem framing to deployment.",
    "How would you serve a model at low latency and high throughput?",
    "How do you monitor a deployed model, and what do you alert on?",
], "ml-system-design", "hard", "ml", "", "curated:ChipHuyen-MLInterviews")


# =====================================================================================
# 5. AI / LLM / GENAI ENGINEERING  (standard current interview questions for AI-eng roles).
# =====================================================================================
_add([
    "Explain self-attention: what are queries, keys, and values, and why the scaling?",
    "Why is multi-head attention used instead of a single attention head?",
    "Walk through a single transformer decoder block.",
    "What are positional encodings, and how do RoPE / ALiBi differ from absolute ones?",
    "Explain the difference between encoder-only (BERT), decoder-only (GPT), and encoder-decoder (T5).",
    "What is the KV cache, and why does it matter for inference latency?",
    "Explain temperature, top-k, and top-p (nucleus) sampling.",
    "What are scaling laws, and what do they tell us about compute vs data vs params?",
    "Explain the difference between pretraining, SFT, and RLHF.",
    "What is DPO, and how does it differ from RLHF/PPO?",
    "Explain LoRA and QLoRA — what is being trained and why it's efficient.",
    "What is quantization (INT8/INT4), and what accuracy tradeoffs does it introduce?",
    "Explain FlashAttention at a high level — what problem does it solve?",
    "What is speculative decoding?",
    "Why do LLMs hallucinate, and what techniques reduce it?",
    "Explain grouped-query attention vs multi-query attention.",
], "llm-internals", "hard", "ai-eng", "", "knowledge")

_add([
    "Explain a baseline RAG pipeline: chunk, embed, retrieve, augment, generate.",
    "How do you choose a chunking strategy, and why does overlap matter?",
    "Cosine similarity vs dot product for embeddings — when does normalization matter?",
    "Explain HNSW and how an approximate nearest-neighbor index trades recall for speed.",
    "What is hybrid retrieval (BM25 + dense) and reciprocal rank fusion?",
    "When and why would you add a cross-encoder re-ranker to a RAG pipeline?",
    "How do you evaluate a RAG system (recall@k, MRR, nDCG, faithfulness)?",
    "What is Graph RAG, and when does it beat vanilla vector RAG?",
    "How would you reduce hallucination in a RAG system when retrieval is weak?",
    "Design a production RAG system over 10M internal documents with access control.",
], "rag", "hard", "ai-eng", "", "knowledge")

_add([
    "Explain the ReAct (reason + act) agent loop.",
    "How does tool / function calling work, and how do you handle a tool that times out?",
    "What are the failure modes of autonomous agents, and how do you guard against loops?",
    "Explain the types of agent memory: working, episodic, semantic, procedural.",
    "What is prompt injection, and how do you defend an agent against it?",
    "Compare a supervisor multi-agent pattern with a choreography pattern.",
    "How do you make an agent's tool calls idempotent and safe to retry?",
    "How would you evaluate an agent's end-to-end task success?",
    "Design a customer-support agent with tools, guardrails, and human handoff.",
], "agents", "hard", "ai-eng", "", "knowledge")

_add([
    "How would you evaluate an LLM feature — offline benchmarks vs LLM-as-judge vs human eval?",
    "What are the pitfalls of using an LLM as a judge?",
    "How do you do prompt engineering systematically (few-shot, CoT, decomposition)?",
    "How would you get structured JSON output reliably from an LLM?",
    "How do you cost- and latency-optimize an LLM application in production?",
    "How do you handle PII and safety in an LLM product?",
    "How would you fine-tune an open model vs use a hosted API — decision factors?",
], "ai-engineering", "medium", "ai-eng", "", "knowledge")


# =====================================================================================
# 6. QUANT  (standard quant-interview probability/brainteaser canon).
# =====================================================================================
_add([
    "Expected number of coin flips to get two heads in a row.",
    "You have a fair coin; simulate a fair die roll (1..6).",
    "Given a stream of numbers, sample one uniformly at random (reservoir sampling).",
    "What is the probability that two people in a room of 23 share a birthday?",
    "Explain the difference between correlation and covariance.",
    "What is a martingale? Give an example.",
    "Explain the Central Limit Theorem and why it matters.",
    "Expected value of the maximum of two uniform(0,1) draws.",
    "How would you estimate pi with a Monte Carlo simulation?",
], "quant-probability", "medium", "quant", "", "knowledge")


# =====================================================================================
# 7. BEHAVIORAL  (the STAR canon; Amazon Leadership Principles tagged honestly).
# =====================================================================================
_add([
    "Tell me about yourself and why this role.",
    "Tell me about a time you failed and what you learned.",
    "Tell me about a challenging technical problem you solved.",
    "Tell me about a conflict with a teammate and how you resolved it.",
    "Describe a time you had to make a decision with incomplete information.",
    "Tell me about a time you disagreed with your manager.",
    "Describe a project you're most proud of and your specific contribution.",
    "Tell me about a time you received difficult feedback.",
    "How do you prioritize when everything is urgent?",
    "Tell me about a time you had to learn something quickly.",
    "Describe a time you missed a deadline; what happened?",
    "Why do you want to leave your current role?",
], "behavioral", "", "any", "", "curated:STAR-canon")

_add([
    "Tell me about a time you took ownership of something outside your job scope. (Ownership)",
    "Describe a time you disagreed and committed. (Have Backbone; Disagree and Commit)",
    "Tell me about a time you dove deep into data to find a root cause. (Dive Deep)",
    "Describe a time you delivered results under a tight deadline. (Deliver Results)",
    "Tell me about a time you invented a simpler solution. (Invent and Simplify)",
    "Describe a time you earned trust with a skeptical stakeholder. (Earn Trust)",
    "Tell me about a time you were frugal / did more with less. (Frugality)",
], "behavioral", "", "any", "Amazon", "curated:AmazonLeadershipPrinciples")


def main(count_only: bool) -> None:
    init_db()
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
        if count_only:
            print(f"defined: {len(QUESTIONS)} questions | already in db: {before}")
            _report(conn)
            return
        conn.executemany(
            "INSERT OR IGNORE INTO questions(question, topic, difficulty, role, company, source) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            [(q, topic, diff or None, role or None, company or None, source)
             for (q, topic, diff, role, company, source) in QUESTIONS],
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
        print(f"seeded: +{after - before} new (defined {len(QUESTIONS)}, total now {after})")
        _report(conn)
    finally:
        conn.close()


def _report(conn) -> None:
    print("\nby topic:")
    for r in conn.execute(
        "SELECT topic, COUNT(*) n FROM questions GROUP BY topic ORDER BY n DESC"
    ):
        print(f"  {r['topic'] or '(none)':22} {r['n']}")
    print("\nby difficulty:")
    for r in conn.execute(
        "SELECT COALESCE(difficulty,'(n/a)') d, COUNT(*) n FROM questions GROUP BY difficulty ORDER BY n DESC"
    ):
        print(f"  {r['d']:8} {r['n']}")
    tagged = conn.execute("SELECT COUNT(*) n FROM questions WHERE company IS NOT NULL").fetchone()["n"]
    print(f"\ncompany-tagged (honest): {tagged}")


if __name__ == "__main__":
    main(count_only="--count" in sys.argv)
