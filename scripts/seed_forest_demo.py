"""Seed a THROWAWAY curriculum that mirrors the real ~18-pillar / ~197-concept
learner state, so the Forest of Mastery map can be validated at real scale.

⛔ SAFETY: this writes into whatever EKLAVYA_HOME / data root is currently bound.
NEVER run it against a real home. The forest2d screenshot harness binds a mktemp
home before invoking it. It refuses to run unless EKLAVYA_HOME points outside the
real ~/.eklavya, unless --force is given.

  uv run python scripts/seed_forest_demo.py            # seed the bound home
  uv run python scripts/seed_forest_demo.py --extra     # + one extra pillar (grow test)

Everything is deterministic (seeded from the pillar key) so the map is stable
between runs. It builds an intra-pillar prereq chain per pillar plus a handful of
cross-pillar links, then records attempts to create a realistic mix of
mastered / active / available / locked groves.
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

# (pillar, concept_count) — the real learner's shape (~197 concepts / ~18 pillars).
PILLARS: list[tuple[str, int]] = [
    ("LLM & Deep Learning Internals", 43),
    ("ML Theory & Math Foundations", 25),
    ("GenAI/ML Engineering Stack", 25),
    ("NLP & Representation Learning", 16),
    ("Graphs & Graph ML", 12),
    ("RAG & Vector Retrieval", 10),
    ("Econometrics & Statistics", 9),
    ("AI Agents & Orchestration", 9),
    ("Python Fundamentals", 8),
    ("MLOps & LLMOps", 7),
    ("System Design", 6),
    ("Interpretability & Explainability", 6),
    ("Data Structures & Algorithms", 6),
    ("CS Foundations", 5),
    ("Time-Series & Forecasting", 4),
    ("Production Python & Backend Engineering", 4),
    ("Object-Oriented Python", 2),
]

EXTRA_PILLAR = ("Reinforcement Learning & Control", 5)  # for the 18→19 grow test

# A pool of realistic concept stems per pillar, cycled to reach the target count.
STEMS: dict[str, list[str]] = {
    "LLM & Deep Learning Internals": [
        "Backprop from first principles", "Activation functions & tradeoffs", "Loss functions",
        "Adam / AdamW optimizers", "Dropout & weight decay", "Batch / layer / RMS norm",
        "Embedding layers", "Convolutions", "RNN / LSTM / GRU", "Self-attention",
        "Multi-head attention", "Positional encodings (RoPE, ALiBi)", "The Transformer block",
        "Causal vs bidirectional masking", "FlashAttention", "Sparse & linear attention",
        "Context-length extension", "Autoregressive generation", "BPE / WordPiece tokenization",
        "Build a GPT from scratch", "LLM pretraining dynamics", "Scaling laws",
        "Emergent abilities", "Mixture of Experts", "KV-cache internals", "Grouped-query attention",
        "SwiGLU & gated MLPs", "Residual streams", "Weight tying", "Logit lens",
        "Speculative decoding internals", "RLHF reward models", "PPO for alignment",
        "DPO & preference optimization", "Instruction tuning", "Constitutional methods",
        "Distillation", "Quantization-aware training", "Rotary embeddings deep-dive",
        "Attention entropy & collapse", "Gradient checkpointing", "Mixed precision (bf16)",
        "Long-context evaluation",
    ],
    "ML Theory & Math Foundations": [
        "Linear algebra: vectors & norms", "Matrix decompositions (SVD)", "Calculus & Jacobians",
        "Optimization & SGD variants", "Linear regression", "Regularization (ridge/lasso)",
        "Logistic regression & GLMs", "Bias-variance tradeoff", "Cross-validation & leakage",
        "Classification metrics", "k-Nearest Neighbors", "Naive Bayes", "Support vector machines",
        "Decision trees", "Random forests", "Gradient boosting", "Feature engineering",
        "Hyperparameter search", "Clustering (k-means, DBSCAN)", "PCA", "t-SNE & UMAP",
        "Kernel methods", "Ensemble stacking", "Calibration", "Information theory basics",
    ],
    "GenAI/ML Engineering Stack": [
        "PyTorch tensors & autograd", "nn.Module & training loops", "Data loaders & datasets",
        "Debugging training runs", "JAX (jit / grad / vmap)", "Training at scale (FSDP)",
        "PEFT & LoRA", "QLoRA on quantized models", "GPTQ / AWQ quantization",
        "Decoding strategies", "Constrained/JSON decoding", "Prompt caching & batching",
        "Speculative decoding", "vLLM / TGI serving", "Prompt engineering",
        "LLM-as-judge evaluation", "Text-to-SQL correctness", "Semantic metrics layer",
        "Row-level security for AI", "HuggingFace Transformers", "Datasets & tokenizers lib",
        "Weights & Biases sweeps", "Triton kernels intro", "ONNX / TensorRT export",
        "Structured outputs (Pydantic)",
    ],
    "NLP & Representation Learning": [
        "Tokenization fundamentals", "Bag-of-words & TF-IDF", "N-gram language models",
        "Text classification (classical)", "Topic modeling (LDA)", "word2vec / GloVe / fastText",
        "Sequence labeling (NER, CRF)", "Seq2seq & encoder-decoder", "Attention for seq2seq",
        "Contextual embeddings", "BERT (MLM + NSP)", "BERT variants (RoBERTa, DeBERTa)",
        "Fine-tuning encoders", "Sentence-BERT embeddings", "Bi- vs cross-encoders",
        "Multilingual representations",
    ],
    "Graphs & Graph ML": [
        "Graph representations", "Graph traversal (BFS/DFS)", "Centrality & PageRank",
        "Community detection", "Node2vec / DeepWalk", "Message passing (GNN intro)",
        "Graph Convolutional Networks", "GraphSAGE", "Graph Attention Networks",
        "Link prediction", "Knowledge graphs & embeddings", "Graph RAG",
    ],
    "RAG & Vector Retrieval": [
        "Embedding similarity (cosine/dot)", "Chunking strategies", "HNSW / IVF index internals",
        "Baseline RAG pipeline", "Hybrid retrieval (BM25 + dense)", "Re-ranking (cross-encoder)",
        "HyDE & parent-document", "RAG evaluation (recall@k, RAGAS)", "Graph-augmented RAG",
        "Multi-tenant retrieval isolation",
    ],
    "Econometrics & Statistics": [
        "Probability foundations", "Distributions & expectation", "Statistical inference",
        "Hypothesis testing", "Maximum likelihood", "Bayesian estimation",
        "Causal inference basics", "Instrumental variables", "Difference-in-differences",
    ],
    "AI Agents & Orchestration": [
        "ReAct reason-act loop", "Tool & function calling", "Agent memory types",
        "Planning & self-correction", "Guardrails vs prompt injection", "LangChain & LCEL",
        "LangGraph state machines", "Multi-agent orchestration", "Agentic RAG",
    ],
    "Python Fundamentals": [
        "Values, types & operators", "Control flow", "Functions & scope",
        "Core data structures", "Comprehensions & generators", "Modules & packages",
        "Errors & exceptions", "File & context managers",
    ],
    "MLOps & LLMOps": [
        "Experiment tracking (MLflow)", "Model serving (FastAPI)", "Docker & orchestration",
        "CI/CD for ML", "Observability & tracing", "Drift detection & monitoring",
        "Cost & latency optimization",
    ],
    "System Design": [
        "End-to-end ML pipelines", "Designing production RAG", "Designing agent systems",
        "Real-time inference scaling", "Multi-tenant AI platforms", "Caching & rate limits",
    ],
    "Interpretability & Explainability": [
        "Feature importance & PDP", "SHAP & LIME", "Probing & attention analysis",
        "Mechanistic interp (circuits)", "Activation patching", "Sparse autoencoders",
    ],
    "Data Structures & Algorithms": [
        "Arrays & hashing", "Two pointers & sliding window", "Stacks & queues",
        "Trees & recursion", "Graphs & shortest paths", "Dynamic programming",
    ],
    "CS Foundations": [
        "How computers represent data", "Memory & the stack/heap", "Time & space complexity",
        "Concurrency & threads", "Networking basics",
    ],
    "Time-Series & Forecasting": [
        "Stationarity & decomposition", "ARIMA / SARIMA / Prophet", "Backtesting & rolling windows",
        "Deep forecasting (TFT, N-BEATS)",
    ],
    "Production Python & Backend Engineering": [
        "FastAPI request lifecycle", "Async & concurrency", "Databases & SQL", "REST / WebSockets / SSE",
    ],
    "Object-Oriented Python": [
        "Classes, dunders & properties", "Inheritance & composition",
    ],
    "Reinforcement Learning & Control": [
        "MDPs & value functions", "Q-learning & DQN", "Policy gradients",
        "Actor-critic (A2C/PPO)", "Model-based RL",
    ],
}

# A few cross-pillar links so the map shows edges BETWEEN groves (each entry maps a
# pillar to the pillar it depends on — its first concept gains that dependency).
CROSS_LINKS: dict[str, str] = {
    "LLM & Deep Learning Internals": "ML Theory & Math Foundations",
    "GenAI/ML Engineering Stack": "LLM & Deep Learning Internals",
    "NLP & Representation Learning": "ML Theory & Math Foundations",
    "RAG & Vector Retrieval": "NLP & Representation Learning",
    "AI Agents & Orchestration": "RAG & Vector Retrieval",
    "MLOps & LLMOps": "GenAI/ML Engineering Stack",
    "System Design": "MLOps & LLMOps",
    "Interpretability & Explainability": "LLM & Deep Learning Internals",
    "Graphs & Graph ML": "ML Theory & Math Foundations",
    "Time-Series & Forecasting": "Econometrics & Statistics",
    "ML Theory & Math Foundations": "Python Fundamentals",
    "Econometrics & Statistics": "Python Fundamentals",
    "Data Structures & Algorithms": "Python Fundamentals",
    "Object-Oriented Python": "Python Fundamentals",
    "Production Python & Backend Engineering": "Object-Oriented Python",
    "CS Foundations": None,  # a root pillar
    "Python Fundamentals": None,  # a root pillar
    "Reinforcement Learning & Control": "ML Theory & Math Foundations",
}

AXES_CYCLE = ["syntax_recall", "debugging", "code_reading", "api_memory", "decomposition"]


def _concepts_for(pillar: str, n: int) -> list[str]:
    """n concept names for a pillar, unique, cycling the stem pool with an index suffix."""
    stems = STEMS[pillar]
    out = []
    for i in range(n):
        stem = stems[i % len(stems)]
        name = stem if i < len(stems) else f"{stem} ({i // len(stems) + 1})"
        out.append(f"{name} · {pillar.split()[0]}")  # namespace so names are globally unique
    return out


def build(include_extra: bool) -> list[dict]:
    """Return curriculum rows [{concept, prereqs(pipe), pillar}] with valid prereq chains."""
    pillars = list(PILLARS) + ([EXTRA_PILLAR] if include_extra else [])
    per_pillar: dict[str, list[str]] = {p: _concepts_for(p, n) for p, n in pillars}
    rows: list[dict] = []
    for pillar, _ in pillars:
        cs = per_pillar[pillar]
        dep_pillar = CROSS_LINKS.get(pillar)
        # the head of this pillar depends on the LAST concept of its dependency pillar
        head_prereq = per_pillar[dep_pillar][-1] if dep_pillar and dep_pillar in per_pillar else ""
        for i, c in enumerate(cs):
            if i == 0:
                prereqs = head_prereq
            else:
                prereqs = cs[i - 1]  # linear chain within the pillar
            rows.append({"concept": c, "prereqs": prereqs, "pillar": pillar})
    return rows


def _progress_plan(rows: list[dict]) -> dict[str, str]:
    """Deterministically decide how far the learner has got in each pillar so the map
    shows a believable spread of mastered / active / available / locked groves.
    Returns {pillar: one of 'full'|'partial'|'started'|'none'}."""
    rng = random.Random(1729)
    plan: dict[str, str] = {}
    # Fix a narrative: foundations mastered, mid-tier in progress, frontier locked.
    scripted = {
        "Python Fundamentals": "full",
        "CS Foundations": "full",
        "Object-Oriented Python": "full",
        "Data Structures & Algorithms": "partial",
        "ML Theory & Math Foundations": "partial",
        "Econometrics & Statistics": "partial",
        "Production Python & Backend Engineering": "started",
        "LLM & Deep Learning Internals": "started",  # the ACTIVE grove (practised last)
        "NLP & Representation Learning": "started",
        "GenAI/ML Engineering Stack": "none",
        "RAG & Vector Retrieval": "none",
        "AI Agents & Orchestration": "none",
        "Graphs & Graph ML": "none",
        "MLOps & LLMOps": "none",
        "System Design": "none",
        "Interpretability & Explainability": "none",
        "Time-Series & Forecasting": "none",
    }
    for p, _ in PILLARS:
        plan[p] = scripted.get(p, rng.choice(["partial", "started", "none"]))
    plan["Reinforcement Learning & Control"] = "none"
    return plan


def apply(rows: list[dict]) -> None:
    from eklavya import tools
    from eklavya.db import connect, init_db

    init_db()
    # pillars first
    pillar_names = []
    for r in rows:
        if r["pillar"] not in pillar_names:
            pillar_names.append(r["pillar"])
    for p in pillar_names:
        tools.add_pillar(p)
        for ax in AXES_CYCLE:
            tools.set_baseline_rating(p, ax, "gap")
    # curriculum (clear first so re-runs are idempotent within the throwaway home)
    tools.clear_curriculum()
    for r in rows:
        tools.add_curriculum(r["concept"], r["prereqs"], r["pillar"])

    # record attempts to realise the progress plan
    plan = _progress_plan(rows)
    by_pillar: dict[str, list[str]] = {}
    for r in rows:
        by_pillar.setdefault(r["pillar"], []).append(r["concept"])

    # order pillars so the ACTIVE one is practised LAST (recency picks it)
    order = [p for p in by_pillar if p != "LLM & Deep Learning Internals"]
    order += ["LLM & Deep Learning Internals"]
    ai = 0
    for pillar in order:
        cs = by_pillar[pillar]
        mode = plan.get(pillar, "none")
        if mode == "full":
            k = len(cs)
        elif mode == "partial":
            k = max(1, int(len(cs) * 0.55))
        elif mode == "started":
            k = max(1, int(len(cs) * 0.20))
        else:
            k = 0
        for c in cs[:k]:
            ax = AXES_CYCLE[ai % len(AXES_CYCLE)]
            ai += 1
            tools.record_attempt(pillar, ax, c, confidence=3, correct=True, seconds=20.0, ai_off=True)


def _guard():
    home = os.environ.get("EKLAVYA_HOME", str(Path.home() / ".eklavya"))
    real = str(Path.home() / ".eklavya")
    if "--force" in sys.argv:
        return
    if Path(home).resolve() == Path(real).resolve():
        sys.exit("REFUSING: EKLAVYA_HOME is the real ~/.eklavya. Bind a throwaway home first "
                 "(or pass --force if you truly mean it).")


def main() -> None:
    _guard()
    include_extra = "--extra" in sys.argv
    rows = build(include_extra)
    n_pillars = len({r["pillar"] for r in rows})
    apply(rows)
    print(f"SEEDED: {n_pillars} pillars, {len(rows)} concepts into "
          f"{os.environ.get('EKLAVYA_HOME', '~/.eklavya')}")


if __name__ == "__main__":
    main()
