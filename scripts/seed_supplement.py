"""Additive, deduplicated seeding of supplementary AI/ML topics (graphs, inference
engineering, frontier modeling, quant/probabilistic) onto the existing curriculum.

Dry run:  uv run python scripts/seed_supplement.py
Apply:    uv run python scripts/seed_supplement.py --apply

Safe: INSERT-only; dedupes against existing; validates prereqs resolve + acyclic.
Prereqs are pipe-delimited EXACT concept names.
"""

import sys

from eklavya import tools
from eklavya.db import connect, init_db

NEW_PILLARS = ["Graphs & Graph ML"]

SUPPLEMENT = [
    {"concept": "Graph theory fundamentals: nodes, edges, degree, paths, connectivity", "prereqs": "DS&A: recursion, backtracking, intro to graphs & BFS/DFS", "pillar": "Graphs & Graph ML"},
    {"concept": "Graph representations: adjacency matrix, adjacency list, sparse formats", "prereqs": "Graph theory fundamentals: nodes, edges, degree, paths, connectivity | Data science staples: NumPy (arrays, vectorized ops, broadcasting)", "pillar": "Graphs & Graph ML"},
    {"concept": "Network analysis: centrality measures, PageRank, community detection", "prereqs": "Graph representations: adjacency matrix, adjacency list, sparse formats", "pillar": "Graphs & Graph ML"},
    {"concept": "Spectral graph theory: graph Laplacian, spectral clustering", "prereqs": "Graph representations: adjacency matrix, adjacency list, sparse formats | Matrix decompositions: eigen, SVD, and change of basis", "pillar": "Graphs & Graph ML"},
    {"concept": "Knowledge graphs, ontologies, RDF, and entity-relationship modeling", "prereqs": "Graph theory fundamentals: nodes, edges, degree, paths, connectivity", "pillar": "Graphs & Graph ML"},
    {"concept": "Neo4j and Cypher: property graphs, pattern matching, traversals", "prereqs": "Knowledge graphs, ontologies, RDF, and entity-relationship modeling | Databases: SQL deep dive, indexing, transactions, PostgreSQL", "pillar": "Graphs & Graph ML"},
    {"concept": "Graph representation learning: node2vec, DeepWalk, random-walk embeddings", "prereqs": "Network analysis: centrality measures, PageRank, community detection | Word embeddings: word2vec, GloVe, fastText", "pillar": "Graphs & Graph ML"},
    {"concept": "Knowledge graph embeddings: TransE, DistMult, ComplEx, link prediction", "prereqs": "Graph representation learning: node2vec, DeepWalk, random-walk embeddings | Knowledge graphs, ontologies, RDF, and entity-relationship modeling", "pillar": "Graphs & Graph ML"},
    {"concept": "Graph Neural Networks: the message-passing framework", "prereqs": "Graph representation learning: node2vec, DeepWalk, random-walk embeddings | PyTorch: nn.Module, optimizers, training loops, and data loaders", "pillar": "Graphs & Graph ML"},
    {"concept": "GNN architectures: GCN, GraphSAGE, GAT, and inductive learning", "prereqs": "Graph Neural Networks: the message-passing framework", "pillar": "Graphs & Graph ML"},
    {"concept": "GNN applications: node classification, link prediction, graph classification", "prereqs": "GNN architectures: GCN, GraphSAGE, GAT, and inductive learning", "pillar": "Graphs & Graph ML"},
    {"concept": "GraphRAG construction: entity extraction, graph building, community summaries", "prereqs": "Neo4j and Cypher: property graphs, pattern matching, traversals | Graph RAG over knowledge graphs", "pillar": "Graphs & Graph ML"},
    {"concept": "Inference engineering overview: latency, throughput, tail latency, SLOs", "prereqs": "LLM serving stacks: vLLM, TGI, and throughput tuning", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "GPU architecture and the memory hierarchy for deep learning", "prereqs": "How computers work: CPU, memory hierarchy, binary, process model | PyTorch: tensors, autograd, and the computational graph", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "CUDA programming: kernels, threads, blocks, memory coalescing", "prereqs": "GPU architecture and the memory hierarchy for deep learning", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Triton and custom kernels for fused deep-learning ops", "prereqs": "CUDA programming: kernels, threads, blocks, memory coalescing", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Serving engines deep dive: SGLang and TensorRT-LLM", "prereqs": "Inference engineering overview: latency, throughput, tail latency, SLOs", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Structured-generation engines: Outlines, Guidance, XGrammar", "prereqs": "Structured and constrained decoding for JSON and grammars | Serving engines deep dive: SGLang and TensorRT-LLM", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Inference routing, load balancing, and GPU autoscaling", "prereqs": "Inference engineering overview: latency, throughput, tail latency, SLOs | Real-time inference and scaling architectures", "pillar": "System Design"},
    {"concept": "DSPy: programming and optimizing LM pipelines with compilers", "prereqs": "Prompt engineering: few-shot, chain-of-thought, decomposition | LLM evaluation: benchmarks, LLM-as-judge, and pitfalls", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Distributed training deep dive: FSDP, ZeRO, tensor and pipeline parallelism", "prereqs": "Training at scale: mixed precision, data and model parallelism, checkpointing", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Sequence and context parallelism for long-context training", "prereqs": "Distributed training deep dive: FSDP, ZeRO, tensor and pipeline parallelism | Context-length extension techniques", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Mixture-of-experts architectures: sparse routing, gating, load balancing", "prereqs": "The complete Transformer architecture: encoder and decoder | Distributed training deep dive: FSDP, ZeRO, tensor and pipeline parallelism", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Reasoning models and test-time compute: o1-style CoT scaling, self-consistency", "prereqs": "Scaling laws and emergent abilities | RLHF: reward models and PPO for LLM alignment", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "RL for reasoning: verifiable rewards, GRPO, and reasoning-model training", "prereqs": "Reasoning models and test-time compute: o1-style CoT scaling, self-consistency | DPO and preference optimization without RL", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Contrastive multimodal models: CLIP and joint image-text embeddings", "prereqs": "The complete Transformer architecture: encoder and decoder | Convolutional neural networks: filters, pooling, architectures", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Vision Transformers and image patch tokenization", "prereqs": "The complete Transformer architecture: encoder and decoder | Convolutional neural networks: filters, pooling, architectures", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Vision-language models: multimodal fusion and visual instruction tuning", "prereqs": "Contrastive multimodal models: CLIP and joint image-text embeddings | Instruction tuning and supervised fine-tuning of LLMs", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Diffusion models: forward and reverse processes, DDPM, score matching", "prereqs": "Neural networks and backpropagation from first principles | Probability foundations: distributions, expectation, Bayes rule", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Latent and guided diffusion: Stable Diffusion, classifier-free guidance", "prereqs": "Diffusion models: forward and reverse processes, DDPM, score matching | Vision Transformers and image patch tokenization", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Generative model families: VAEs, GANs, normalizing flows, and tradeoffs", "prereqs": "Diffusion models: forward and reverse processes, DDPM, score matching", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Synthetic data generation and model distillation for LLMs", "prereqs": "Instruction tuning and supervised fine-tuning of LLMs | LLM evaluation: benchmarks, LLM-as-judge, and pitfalls", "pillar": "LLM & Deep Learning Internals"},
    {"concept": "Stochastic processes: random walks, Markov chains, martingales", "prereqs": "Probability foundations: distributions, expectation, Bayes rule", "pillar": "ML Theory & Math Foundations"},
    {"concept": "Continuous-time processes: Brownian motion, Ito calculus, SDEs", "prereqs": "Stochastic processes: random walks, Markov chains, martingales | Calculus for ML: derivatives, gradients, chain rule, Jacobians", "pillar": "ML Theory & Math Foundations"},
    {"concept": "Monte Carlo methods: sampling, variance reduction, importance sampling", "prereqs": "Stochastic processes: random walks, Markov chains, martingales", "pillar": "ML Theory & Math Foundations"},
    {"concept": "MCMC: Metropolis-Hastings, Gibbs sampling, Hamiltonian Monte Carlo", "prereqs": "Monte Carlo methods: sampling, variance reduction, importance sampling | Maximum likelihood estimation and the Bayesian view", "pillar": "ML Theory & Math Foundations"},
    {"concept": "Bayesian inference: priors, posteriors, conjugacy, credible intervals", "prereqs": "Maximum likelihood estimation and the Bayesian view | Statistical inference: estimation, confidence intervals, hypothesis testing", "pillar": "Econometrics & Statistics"},
    {"concept": "Probabilistic programming with PyMC and NumPyro", "prereqs": "Bayesian inference: priors, posteriors, conjugacy, credible intervals | MCMC: Metropolis-Hastings, Gibbs sampling, Hamiltonian Monte Carlo", "pillar": "Econometrics & Statistics"},
    {"concept": "Variational inference and the ELBO", "prereqs": "Bayesian inference: priors, posteriors, conjugacy, credible intervals | Optimization and gradient descent: convexity, learning rate, SGD variants", "pillar": "ML Theory & Math Foundations"},
    {"concept": "Portfolio theory and mean-variance optimization", "prereqs": "Optimization and gradient descent: convexity, learning rate, SGD variants | Matrix decompositions: eigen, SVD, and change of basis", "pillar": "Econometrics & Statistics"},
    {"concept": "Volatility modeling: GARCH, EWMA, and heteroskedasticity", "prereqs": "Time-series fundamentals: stationarity, autocorrelation, decomposition | Continuous-time processes: Brownian motion, Ito calculus, SDEs", "pillar": "Econometrics & Statistics"},
    {"concept": "Causal inference: potential outcomes, confounding, DAGs, do-calculus", "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing | Graph theory fundamentals: nodes, edges, degree, paths, connectivity", "pillar": "Econometrics & Statistics"},
    {"concept": "A/B testing and online experimentation: power, sequential tests, CUPED", "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing", "pillar": "Econometrics & Statistics"},
    {"concept": "Learning-to-rank and recommender systems: matrix factorization, LambdaMART", "prereqs": "Bi-encoders vs cross-encoders for retrieval and ranking | Gradient boosting: XGBoost, LightGBM, CatBoost", "pillar": "NLP & Representation Learning"},
]


def main(apply: bool):
    init_db()
    conn = connect()
    existing = {r["concept"] for r in conn.execute("SELECT concept FROM curriculum")}
    known = set(existing) | {n["concept"] for n in SUPPLEMENT}

    unresolved, dup, seen = [], [], set()
    for n in SUPPLEMENT:
        if n["concept"] in existing:
            dup.append(n["concept"])
        for frag in n["prereqs"].split("|"):
            frag = frag.strip()
            if frag and frag not in known:
                unresolved.append((n["concept"], frag))
        seen.add(n["concept"])
    internal_dupes = len(SUPPLEMENT) - len(seen)

    # cycle check within SUPPLEMENT
    sup_prereqs = {n["concept"]: [p.strip() for p in n["prereqs"].split("|") if p.strip()] for n in SUPPLEMENT}
    def path(a, b, seen_):
        for p in sup_prereqs.get(a, []):
            if p == b:
                return True
            if p in sup_prereqs and p not in seen_:
                seen_.add(p)
                if path(p, b, seen_):
                    return True
        return False
    cycles = [c for c in sup_prereqs if path(c, c, set())]

    print(f"SUPPLEMENT: {len(SUPPLEMENT)} | dupes-vs-existing: {len(dup)} | internal-dupes: {internal_dupes} | unresolved prereqs: {len(unresolved)} | cycles: {len(cycles)}")
    for u in unresolved:
        print("  UNRESOLVED:", u)
    for c in cycles:
        print("  CYCLE:", c)
    if dup:
        print("  DUP (skip):", dup)
    conn.close()
    if not apply:
        print("\nDRY RUN — no writes.")
        return
    if unresolved or cycles or internal_dupes:
        print("\nABORT: fix issues first.")
        return
    for p in NEW_PILLARS:
        tools.add_pillar(p)
        for ax in tools.AXES:
            tools.set_baseline_rating(p, ax, "gap")
    added = 0
    for n in SUPPLEMENT:
        if n["concept"] in existing:
            continue
        tools.add_curriculum(n["concept"], n["prereqs"], n["pillar"])
        added += 1
    print(f"\nAPPLIED: +{len(NEW_PILLARS)} pillar, +{added} curriculum nodes.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
