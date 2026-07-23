"""One-shot, additive, deduplicated seeding of the AI-engineering curriculum.

Run dry (validate only):   uv run python scripts/seed_ai_curriculum.py
Run for real (writes db):  uv run python scripts/seed_ai_curriculum.py --apply

Safe: only INSERTs new curriculum/pillars/ratings; never deletes or overwrites
existing rows. Snapshot the state first (backups.snapshot). Concept/pillar strings
below use HTML entities as authored; they are html.unescape()'d at runtime.
"""

import html
import sys

from eklavya import tools
from eklavya.db import connect, init_db

NEW_PILLARS = [
    "NLP & Representation Learning", "RAG & Vector Retrieval", "AI Agents & Orchestration",
    "Interpretability & Explainability", "Time-Series & Forecasting", "MLOps & LLMOps",
]

NEW_RAW = [
    {"concept": "Linear algebra for ML: vectors, matrices, dot products, norms", "prereqs": "Data science staples: NumPy (arrays, vectorized ops, broadcasting)", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Matrix decompositions: eigen, SVD, and change of basis", "prereqs": "Linear algebra for ML: vectors, matrices, dot products, norms", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Probability foundations: distributions, expectation, Bayes rule", "prereqs": "Data science staples: NumPy (arrays, vectorized ops, broadcasting)", "pillar": "Econometrics &amp; Statistics"},
    {"concept": "Statistical inference: estimation, confidence intervals, hypothesis testing", "prereqs": "Probability foundations: distributions, expectation, Bayes rule", "pillar": "Econometrics &amp; Statistics"},
    {"concept": "Maximum likelihood estimation and the Bayesian view", "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing", "pillar": "Econometrics &amp; Statistics"},
    {"concept": "Calculus for ML: derivatives, gradients, chain rule, Jacobians", "prereqs": "Linear algebra for ML: vectors, matrices, dot products, norms", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Optimization and gradient descent: convexity, learning rate, SGD variants", "prereqs": "Calculus for ML: derivatives, gradients, chain rule, Jacobians", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Linear regression: least squares, assumptions, normal equations", "prereqs": "Optimization and gradient descent: convexity, learning rate, SGD variants ; Statistical inference: estimation, confidence intervals, hypothesis testing", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Regularization: ridge, lasso, elastic net, and the bias-variance tradeoff", "prereqs": "Linear regression: least squares, assumptions, normal equations", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Logistic regression and generalized linear models", "prereqs": "Linear regression: least squares, assumptions, normal equations ; Maximum likelihood estimation and the Bayesian view", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Model evaluation: train/val/test, cross-validation, and data leakage", "prereqs": "Logistic regression and generalized linear models", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Classification metrics: precision, recall, F1, ROC-AUC, PR curves", "prereqs": "Model evaluation: train/val/test, cross-validation, and data leakage", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "k-Nearest Neighbors and distance metrics", "prereqs": "Model evaluation: train/val/test, cross-validation, and data leakage", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Naive Bayes classifiers", "prereqs": "Probability foundations: distributions, expectation, Bayes rule ; Model evaluation: train/val/test, cross-validation, and data leakage", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Support vector machines and the kernel trick", "prereqs": "Logistic regression and generalized linear models", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Decision trees: splitting criteria, pruning, overfitting", "prereqs": "Model evaluation: train/val/test, cross-validation, and data leakage", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Bagging and random forests", "prereqs": "Decision trees: splitting criteria, pruning, overfitting", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Gradient boosting: XGBoost, LightGBM, CatBoost", "prereqs": "Bagging and random forests", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Feature engineering: encoding, scaling, interactions, target leakage", "prereqs": "Classification metrics: precision, recall, F1, ROC-AUC, PR curves", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Hyperparameter tuning: grid, random, and Bayesian search", "prereqs": "Gradient boosting: XGBoost, LightGBM, CatBoost", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Clustering: k-means, hierarchical, DBSCAN", "prereqs": "k-Nearest Neighbors and distance metrics", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Dimensionality reduction: PCA", "prereqs": "Matrix decompositions: eigen, SVD, and change of basis ; Clustering: k-means, hierarchical, DBSCAN", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Manifold learning and visualization: t-SNE and UMAP", "prereqs": "Dimensionality reduction: PCA", "pillar": "ML Theory &amp; Math Foundations"},
    {"concept": "Neural networks and backpropagation from first principles", "prereqs": "Optimization and gradient descent: convexity, learning rate, SGD variants", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Activation functions: sigmoid, tanh, ReLU, GELU and their tradeoffs", "prereqs": "Neural networks and backpropagation from first principles", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Loss functions: MSE, cross-entropy, and when to use each", "prereqs": "Neural networks and backpropagation from first principles", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Optimizers for deep learning: momentum, RMSProp, Adam, AdamW", "prereqs": "Neural networks and backpropagation from first principles", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Deep learning regularization: dropout, weight decay, early stopping", "prereqs": "Activation functions: sigmoid, tanh, ReLU, GELU and their tradeoffs", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Normalization: batch norm, layer norm, and RMSNorm", "prereqs": "Deep learning regularization: dropout, weight decay, early stopping", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "PyTorch: tensors, autograd, and the computational graph", "prereqs": "Neural networks and backpropagation from first principles", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "PyTorch: nn.Module, optimizers, training loops, and data loaders", "prereqs": "PyTorch: tensors, autograd, and the computational graph ; Optimizers for deep learning: momentum, RMSProp, Adam, AdamW", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Embedding layers and learned representations", "prereqs": "PyTorch: nn.Module, optimizers, training loops, and data loaders", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Convolutional neural networks: filters, pooling, architectures", "prereqs": "PyTorch: nn.Module, optimizers, training loops, and data loaders ; Normalization: batch norm, layer norm, and RMSNorm", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Recurrent networks: RNN, LSTM, GRU and vanishing gradients", "prereqs": "PyTorch: nn.Module, optimizers, training loops, and data loaders ; Embedding layers and learned representations", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Debugging training: loss not decreasing, overfitting, gradient issues, reproducibility", "prereqs": "PyTorch: nn.Module, optimizers, training loops, and data loaders ; Deep learning regularization: dropout, weight decay, early stopping", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "JAX: functional arrays, jit, grad, vmap", "prereqs": "PyTorch: tensors, autograd, and the computational graph", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Training at scale: mixed precision, data and model parallelism, checkpointing", "prereqs": "Debugging training: loss not decreasing, overfitting, gradient issues, reproducibility", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Text preprocessing and tokenization fundamentals", "prereqs": "Pandas: Series, DataFrame, indexing, groupby, merge, reshaping", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Bag-of-words and TF-IDF text representations", "prereqs": "Text preprocessing and tokenization fundamentals", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "N-gram language models and smoothing", "prereqs": "Text preprocessing and tokenization fundamentals ; Probability foundations: distributions, expectation, Bayes rule", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Text classification with classical ML", "prereqs": "Bag-of-words and TF-IDF text representations ; Classification metrics: precision, recall, F1, ROC-AUC, PR curves", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Text clustering and topic modeling with LDA", "prereqs": "Bag-of-words and TF-IDF text representations ; Clustering: k-means, hierarchical, DBSCAN", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Word embeddings: word2vec, GloVe, fastText", "prereqs": "Bag-of-words and TF-IDF text representations ; Embedding layers and learned representations", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Sequence labeling: POS tagging, NER, HMMs and CRFs", "prereqs": "N-gram language models and smoothing ; Text classification with classical ML", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Sequence-to-sequence and encoder-decoder architectures", "prereqs": "Recurrent networks: RNN, LSTM, GRU and vanishing gradients ; Word embeddings: word2vec, GloVe, fastText", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "The original attention mechanism for seq2seq", "prereqs": "Sequence-to-sequence and encoder-decoder architectures", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Self-attention: queries, keys, values, and scaled dot-product", "prereqs": "The original attention mechanism for seq2seq ; Normalization: batch norm, layer norm, and RMSNorm", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Multi-head attention and the full Transformer block", "prereqs": "Self-attention: queries, keys, values, and scaled dot-product", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Positional encodings: absolute, rotary (RoPE), and ALiBi", "prereqs": "Multi-head attention and the full Transformer block", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "The complete Transformer architecture: encoder and decoder", "prereqs": "Positional encodings: absolute, rotary (RoPE), and ALiBi", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Attention masking: causal vs bidirectional, cross-attention", "prereqs": "The complete Transformer architecture: encoder and decoder", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Efficient attention: multi-query, grouped-query, FlashAttention", "prereqs": "Attention masking: causal vs bidirectional, cross-attention", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Sparse and linear attention for long context", "prereqs": "Efficient attention: multi-query, grouped-query, FlashAttention", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Context-length extension techniques", "prereqs": "Sparse and linear attention for long context", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Contextual embeddings and the Transformer encoder for representation", "prereqs": "The complete Transformer architecture: encoder and decoder", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "BERT: masked language modeling and next-sentence prediction", "prereqs": "Contextual embeddings and the Transformer encoder for representation", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "BERT variants: RoBERTa, DistilBERT, ALBERT, ELECTRA, DeBERTa", "prereqs": "BERT: masked language modeling and next-sentence prediction", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Fine-tuning encoders for classification and token tasks", "prereqs": "BERT: masked language modeling and next-sentence prediction ; Text classification with classical ML", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Sentence embeddings with Sentence-BERT", "prereqs": "Fine-tuning encoders for classification and token tasks", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "Bi-encoders vs cross-encoders for retrieval and ranking", "prereqs": "Sentence embeddings with Sentence-BERT", "pillar": "NLP &amp; Representation Learning"},
    {"concept": "The language modeling objective and autoregressive generation", "prereqs": "Attention masking: causal vs bidirectional, cross-attention", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Subword tokenization: BPE, WordPiece, SentencePiece", "prereqs": "The language modeling objective and autoregressive generation ; Text preprocessing and tokenization fundamentals", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Building a GPT from scratch", "prereqs": "The language modeling objective and autoregressive generation ; Subword tokenization: BPE, WordPiece, SentencePiece", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "LLM pretraining: data, objectives, and training dynamics", "prereqs": "Building a GPT from scratch ; Training at scale: mixed precision, data and model parallelism, checkpointing", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Scaling laws and emergent abilities", "prereqs": "LLM pretraining: data, objectives, and training dynamics", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "World models as a concept", "prereqs": "Scaling laws and emergent abilities", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Reinforcement learning fundamentals: MDPs, rewards, value functions", "prereqs": "Probability foundations: distributions, expectation, Bayes rule ; Neural networks and backpropagation from first principles", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Policy gradients and actor-critic methods", "prereqs": "Reinforcement learning fundamentals: MDPs, rewards, value functions", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "Instruction tuning and supervised fine-tuning of LLMs", "prereqs": "Scaling laws and emergent abilities", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "RLHF: reward models and PPO for LLM alignment", "prereqs": "Instruction tuning and supervised fine-tuning of LLMs ; Policy gradients and actor-critic methods", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "DPO and preference optimization without RL", "prereqs": "RLHF: reward models and PPO for LLM alignment", "pillar": "LLM &amp; Deep Learning Internals"},
    {"concept": "PEFT and LoRA: low-rank adapters for efficient fine-tuning", "prereqs": "Instruction tuning and supervised fine-tuning of LLMs ; Matrix decompositions: eigen, SVD, and change of basis", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "QLoRA and adapter methods on quantized models", "prereqs": "PEFT and LoRA: low-rank adapters for efficient fine-tuning", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Quantization: post-training quant, GPTQ, AWQ, bitsandbytes, GGUF", "prereqs": "PEFT and LoRA: low-rank adapters for efficient fine-tuning", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Decoding strategies: temperature, top-k, top-p, beam search", "prereqs": "The language modeling objective and autoregressive generation", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Structured and constrained decoding for JSON and grammars", "prereqs": "Decoding strategies: temperature, top-k, top-p, beam search", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "KV cache, prompt caching, and continuous batching", "prereqs": "Decoding strategies: temperature, top-k, top-p, beam search ; Efficient attention: multi-query, grouped-query, FlashAttention", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Speculative decoding and latency optimization", "prereqs": "KV cache, prompt caching, and continuous batching", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "LLM serving stacks: vLLM, TGI, and throughput tuning", "prereqs": "KV cache, prompt caching, and continuous batching ; Quantization: post-training quant, GPTQ, AWQ, bitsandbytes, GGUF", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Prompt engineering: few-shot, chain-of-thought, decomposition", "prereqs": "Decoding strategies: temperature, top-k, top-p, beam search", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "LLM evaluation: benchmarks, LLM-as-judge, and pitfalls", "prereqs": "Prompt engineering: few-shot, chain-of-thought, decomposition", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Embedding similarity: cosine vs dot product and normalization", "prereqs": "Vector databases &amp; retrieval: embeddings, similarity search, FAISS, Pinecone, Neo4j ; Bi-encoders vs cross-encoders for retrieval and ranking", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Chunking strategies and overlap for retrieval", "prereqs": "Embedding similarity: cosine vs dot product and normalization", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Vector index internals: HNSW, IVF, and product quantization", "prereqs": "Embedding similarity: cosine vs dot product and normalization", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Baseline RAG pipeline: retrieve, augment, generate", "prereqs": "Chunking strategies and overlap for retrieval ; Prompt engineering: few-shot, chain-of-thought, decomposition", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Hybrid retrieval: BM25 plus dense with Reciprocal Rank Fusion", "prereqs": "Baseline RAG pipeline: retrieve, augment, generate ; Vector index internals: HNSW, IVF, and product quantization", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Re-ranking with cross-encoders and MMR diversification", "prereqs": "Hybrid retrieval: BM25 plus dense with Reciprocal Rank Fusion", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Advanced retrieval: HyDE and parent-document retrieval", "prereqs": "Re-ranking with cross-encoders and MMR diversification", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "RAG evaluation: recall@k, MRR, nDCG, and RAGAS", "prereqs": "Baseline RAG pipeline: retrieve, augment, generate ; LLM evaluation: benchmarks, LLM-as-judge, and pitfalls", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Graph RAG over knowledge graphs", "prereqs": "Advanced retrieval: HyDE and parent-document retrieval", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Multi-tenant retrieval isolation and metadata filtering", "prereqs": "Hybrid retrieval: BM25 plus dense with Reciprocal Rank Fusion", "pillar": "RAG &amp; Vector Retrieval"},
    {"concept": "Agent fundamentals and the ReAct reason-act loop", "prereqs": "Prompt engineering: few-shot, chain-of-thought, decomposition", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Tool and function calling: schemas, status, timeouts, retries, idempotency", "prereqs": "Agent fundamentals and the ReAct reason-act loop ; Web protocols: REST, WebSockets, SSE, JSON, serialization", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Agent memory: working, episodic, semantic, procedural", "prereqs": "Agent fundamentals and the ReAct reason-act loop ; Baseline RAG pipeline: retrieve, augment, generate", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Planning, reflection, and self-correction in agents", "prereqs": "Tool and function calling: schemas, status, timeouts, retries, idempotency", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Guardrails and robustness against prompt injection", "prereqs": "Tool and function calling: schemas, status, timeouts, retries, idempotency", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "LangChain: chains, prompts, tools, and LCEL", "prereqs": "Tool and function calling: schemas, status, timeouts, retries, idempotency", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "LangGraph: state graphs, nodes, edges, checkpointing, human-in-the-loop", "prereqs": "LangChain: chains, prompts, tools, and LCEL ; Planning, reflection, and self-correction in agents", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Multi-agent orchestration: supervisor, choreography, map-reduce", "prereqs": "LangGraph: state graphs, nodes, edges, checkpointing, human-in-the-loop ; Agent memory: working, episodic, semantic, procedural", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Agentic RAG", "prereqs": "Multi-agent orchestration: supervisor, choreography, map-reduce ; Graph RAG over knowledge graphs", "pillar": "AI Agents &amp; Orchestration"},
    {"concept": "Model explainability: feature importance and partial dependence", "prereqs": "Gradient boosting: XGBoost, LightGBM, CatBoost", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "SHAP and LIME for local and global explanations", "prereqs": "Model explainability: feature importance and partial dependence", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "Probing and attention analysis in Transformers", "prereqs": "Multi-head attention and the full Transformer block ; Fine-tuning encoders for classification and token tasks", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "Mechanistic interpretability: circuits, features, superposition", "prereqs": "Probing and attention analysis in Transformers ; Building a GPT from scratch", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "Activation patching and causal interventions", "prereqs": "Mechanistic interpretability: circuits, features, superposition", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "Sparse autoencoders for feature disentanglement", "prereqs": "Activation patching and causal interventions", "pillar": "Interpretability &amp; Explainability"},
    {"concept": "Time-series fundamentals: stationarity, autocorrelation, decomposition", "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing ; Pandas: Series, DataFrame, indexing, groupby, merge, reshaping", "pillar": "Time-Series &amp; Forecasting"},
    {"concept": "Classical forecasting: ARIMA, SARIMA, exponential smoothing, Prophet", "prereqs": "Time-series fundamentals: stationarity, autocorrelation, decomposition", "pillar": "Time-Series &amp; Forecasting"},
    {"concept": "Forecast evaluation and backtesting with rolling windows", "prereqs": "Classical forecasting: ARIMA, SARIMA, exponential smoothing, Prophet", "pillar": "Time-Series &amp; Forecasting"},
    {"concept": "ML and deep forecasting: gradient boosting, N-BEATS, Temporal Fusion Transformer", "prereqs": "Forecast evaluation and backtesting with rolling windows ; Recurrent networks: RNN, LSTM, GRU and vanishing gradients", "pillar": "Time-Series &amp; Forecasting"},
    {"concept": "Text-to-SQL correctness: dates, dialects, and validation", "prereqs": "Databases: SQL deep dive, indexing, transactions, PostgreSQL ; Tool and function calling: schemas, status, timeouts, retries, idempotency", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Semantic and metrics layer as a single source of truth", "prereqs": "Text-to-SQL correctness: dates, dialects, and validation", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Row-level security and least-privilege data access for AI apps", "prereqs": "Semantic and metrics layer as a single source of truth", "pillar": "GenAI/ML Engineering Stack"},
    {"concept": "Experiment tracking with MLflow and Weights and Biases", "prereqs": "Debugging training: loss not decreasing, overfitting, gradient issues, reproducibility", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "Model serving and deployment with FastAPI endpoints", "prereqs": "FastAPI deep dive: request lifecycle, routing, middleware, dependency injection ; PyTorch: nn.Module, optimizers, training loops, and data loaders", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "Containers and scaling: Docker and orchestration basics", "prereqs": "Model serving and deployment with FastAPI endpoints ; Cloud &amp; AWS fundamentals: EC2, S3, IAM, networking, serverless", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "CI/CD for ML: pipelines, testing, and model registries", "prereqs": "Containers and scaling: Docker and orchestration basics ; Experiment tracking with MLflow and Weights and Biases", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "Observability and distributed tracing: OpenTelemetry, LangSmith, p95 latency", "prereqs": "Model serving and deployment with FastAPI endpoints ; LangGraph: state graphs, nodes, edges, checkpointing, human-in-the-loop", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "Production monitoring: drift detection and online evaluation", "prereqs": "Observability and distributed tracing: OpenTelemetry, LangSmith, p95 latency ; RAG evaluation: recall@k, MRR, nDCG, and RAGAS", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "Cost and latency optimization: caching and right-sizing models", "prereqs": "LLM serving stacks: vLLM, TGI, and throughput tuning ; Speculative decoding and latency optimization", "pillar": "MLOps &amp; LLMOps"},
    {"concept": "ML pipelines end-to-end: data, features, training, serving", "prereqs": "CI/CD for ML: pipelines, testing, and model registries ; Feature engineering: encoding, scaling, interactions, target leakage", "pillar": "System Design"},
    {"concept": "Designing production RAG systems", "prereqs": "Production monitoring: drift detection and online evaluation ; Multi-tenant retrieval isolation and metadata filtering", "pillar": "System Design"},
    {"concept": "Designing agent systems for reliability and scale", "prereqs": "Agentic RAG ; Guardrails and robustness against prompt injection", "pillar": "System Design"},
    {"concept": "Real-time inference and scaling architectures", "prereqs": "Cost and latency optimization: caching and right-sizing models ; Containers and scaling: Docker and orchestration basics", "pillar": "System Design"},
    {"concept": "Designing multi-tenant AI platforms", "prereqs": "Designing production RAG systems ; Row-level security and least-privilege data access for AI apps", "pillar": "System Design"},
]


def unescape(node):
    return {k: html.unescape(v) for k, v in node.items()}


def main(apply: bool):
    init_db()
    conn = connect()
    existing = [r["concept"] for r in conn.execute("SELECT concept FROM curriculum ORDER BY id")]
    new = [unescape(n) for n in NEW_RAW]
    all_names = list(existing) + [n["concept"] for n in new]

    def resolve(frag: str):
        frag = frag.strip()
        if not frag:
            return None
        if frag in all_names:
            return frag
        head = frag.split(":")[0].strip()
        cands = [n for n in all_names if n.startswith(frag) or n.split(":")[0].strip() == head]
        if cands:
            exact = [n for n in cands if n.startswith(frag)]
            return exact[0] if exact else cands[0]
        sub = [n for n in all_names if frag in n or n in frag]
        return sub[0] if len(sub) == 1 else None

    unresolved = []
    resolved = []
    for n in new:
        outp = []
        for frag in n["prereqs"].split(";"):
            if not frag.strip():
                continue
            r = resolve(frag)
            if r is None:
                unresolved.append((n["concept"], frag.strip()))
            elif r not in outp:
                outp.append(r)
        resolved.append({**n, "prereqs": " | ".join(outp)})

    # cycle check over resolved edges (concept depends on its prereqs)
    name_to_prereqs = {r["concept"]: [p.strip() for p in r["prereqs"].split("|") if p.strip()] for r in resolved}
    existing_set = set(existing)
    cycles = []
    def has_path(a, b, seen):  # is there a dependency path a -> ... -> b within NEW nodes
        for p in name_to_prereqs.get(a, []):
            if p == b:
                return True
            if p not in seen and p not in existing_set:
                seen.add(p)
                if has_path(p, b, seen):
                    return True
        return False
    for c in name_to_prereqs:
        if has_path(c, c, set()):
            cycles.append(c)

    # substring collisions among ALL concept names (would confuse the legacy parser; new uses pipes so ok)
    collisions = [(a, b) for a in all_names for b in all_names if a != b and a in b]

    dup = [n["concept"] for n in new if n["concept"] in existing_set]

    print(f"NEW nodes: {len(new)} | already-present dupes: {len(dup)} | unresolved prereqs: {len(unresolved)} | cycles: {len(cycles)}")
    for u in unresolved:
        print("  UNRESOLVED:", u)
    for c in cycles:
        print("  CYCLE:", c)
    if dup:
        print("  DUP (will skip):", dup)
    print(f"  (name-substring pairs: {len(collisions)} — harmless, new prereqs are pipe-delimited exact)")

    if not apply:
        print("\nDRY RUN — no writes. Re-run with --apply to seed.")
        conn.close()
        return
    if unresolved or cycles:
        print("\nABORT: resolve unresolved/cycles before applying.")
        conn.close()
        return

    for p in NEW_PILLARS:
        tools.add_pillar(p)
    for p in NEW_PILLARS:
        for ax in tools.AXES:
            tools.set_baseline_rating(p, ax, "gap")
    added = 0
    for r in resolved:
        if r["concept"] in existing_set:
            continue
        tools.add_curriculum(r["concept"], r["prereqs"], r["pillar"])
        added += 1
    conn.close()
    print(f"\nAPPLIED: +{len(NEW_PILLARS)} pillars, +{added} curriculum nodes.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
