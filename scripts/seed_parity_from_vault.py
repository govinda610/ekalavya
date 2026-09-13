"""Additive parity seed: bring Eklavya curriculum to full parity with the learning-system vault.

Run dry (validate only):   uv run python scripts/seed_parity_from_vault.py
Run for real (writes db):  uv run python scripts/seed_parity_from_vault.py --apply

Safe: only INSERTs new curriculum/pillars/ratings; never deletes or overwrites existing
rows. Snapshots the live DB before any write. Concept/pillar strings below use HTML
entities as authored; they are html.unescape()'d at runtime. Prereqs use pipe (|) as
delimiter (exact concept names can contain commas/semicolons safely).

New pillars added:
  - CS Fundamentals            (13 nodes from skills/cs-fundamentals/)
  - Software Engineering       (10 nodes from skills/software-eng-breadth/)
  - Computer Vision & Multimodal (10 nodes from skills/cv-multimodal-idp/)
  - Indic & Speech AI          (10 nodes from skills/indic-ai/)
  - Startup & Product          (15 nodes from skills/startup-founder/)
  - Research & Frontier        (14 nodes from skills/research-interp-papers/ not already in Eklavya)

Existing pillars extended with vault depth:
  - GenAI/ML Engineering Stack  (10 inference-optimization nodes)
  - AI Agents &amp; Orchestration   (11 agentic-depth nodes)
  - MLOps &amp; LLMOps              (8 mlops-depth nodes)
  - ML Theory &amp; Math Foundations (8 foundations/math-depth nodes)
  - Econometrics &amp; Statistics    (5 classical/causal nodes)
  - NLP &amp; Representation Learning (10 classical-NLP-history nodes)
  - Time-Series &amp; Forecasting     (3 extra forecasting nodes)
  - LLM &amp; Deep Learning Internals (6 internals-extras nodes)
"""

import html
import sys

from eklavya import tools
from eklavya.db import connect, init_db

# ---------------------------------------------------------------------------
# NEW PILLARS
# ---------------------------------------------------------------------------
NEW_PILLARS = [
    "CS Fundamentals",
    "Software Engineering",
    "Computer Vision &amp; Multimodal",
    "Indic &amp; Speech AI",
    "Startup &amp; Product",
    "Research &amp; Frontier",
]

# ---------------------------------------------------------------------------
# NEW CURRICULUM NODES
# Each entry: concept (descriptive sentence in Eklavya style), prereqs (pipe-
# delimited exact concept names, HTML-escaped in pillar refs but NOT in prereq
# strings — prereqs reference unescaped concept names), pillar (HTML-escaped).
#
# Convention from seed_ai_curriculum.py:
#   - pillar field uses &amp; for &
#   - prereq field uses plain text (html.unescape is applied to all fields uniformly)
#   - concept is a descriptive sentence, not just a topic name
# ---------------------------------------------------------------------------

NEW_RAW = [

    # =========================================================================
    # CS FUNDAMENTALS (13 nodes from skills/cs-fundamentals/)
    # =========================================================================

    {"concept": "Computer architecture from first principles: NAND gates, ALU, CPU, machine language (Nand2Tetris)",
     "prereqs": "",
     "pillar": "CS Fundamentals"},

    {"concept": "Operating systems internals: processes, scheduling, virtual memory, file systems (OSTEP)",
     "prereqs": "Computer architecture from first principles: NAND gates, ALU, CPU, machine language (Nand2Tetris)",
     "pillar": "CS Fundamentals"},

    {"concept": "Computer networks: TCP/IP stack, HTTP/TLS, DNS, sockets from application to link layer",
     "prereqs": "Operating systems internals: processes, scheduling, virtual memory, file systems (OSTEP)",
     "pillar": "CS Fundamentals"},

    {"concept": "Systems programming in C: pointers, memory model, malloc/free, syscalls, undefined behavior",
     "prereqs": "Computer architecture from first principles: NAND gates, ALU, CPU, machine language (Nand2Tetris)",
     "pillar": "CS Fundamentals"},

    {"concept": "C++ for ML systems: RAII, move semantics, templates, STL, compilation model",
     "prereqs": "Systems programming in C: pointers, memory model, malloc/free, syscalls, undefined behavior",
     "pillar": "CS Fundamentals"},

    {"concept": "Database internals: B-trees, LSM trees, MVCC, query execution, WAL and crash recovery",
     "prereqs": "Operating systems internals: processes, scheduling, virtual memory, file systems (OSTEP)",
     "pillar": "CS Fundamentals"},

    {"concept": "Compilers and interpreters: lexing, parsing, AST, bytecode, VM (Crafting Interpreters)",
     "prereqs": "Systems programming in C: pointers, memory model, malloc/free, syscalls, undefined behavior",
     "pillar": "CS Fundamentals"},

    {"concept": "Distributed systems: consensus (Raft), replication, CAP theorem, fault tolerance, sharding",
     "prereqs": "Computer networks: TCP/IP stack, HTTP/TLS, DNS, sockets from application to link layer | Database internals: B-trees, LSM trees, MVCC, query execution, WAL and crash recovery",
     "pillar": "CS Fundamentals"},

    {"concept": "Theory of computation: automata, Chomsky hierarchy, Turing machines, decidability, P vs NP",
     "prereqs": "Computer architecture from first principles: NAND gates, ALU, CPU, machine language (Nand2Tetris)",
     "pillar": "CS Fundamentals"},

    {"concept": "JavaScript fundamentals: event loop, closures, prototype chain, async/await, ES modules",
     "prereqs": "Computer networks: TCP/IP stack, HTTP/TLS, DNS, sockets from application to link layer",
     "pillar": "CS Fundamentals"},

    {"concept": "TypeScript: type system, generics, utility types, structural typing, strict mode, declaration files",
     "prereqs": "JavaScript fundamentals: event loop, closures, prototype chain, async/await, ES modules",
     "pillar": "CS Fundamentals"},

    {"concept": "Frontend web development: HTML/CSS, DOM, React hooks, Next.js routing (App Router), Tailwind",
     "prereqs": "TypeScript: type system, generics, utility types, structural typing, strict mode, declaration files",
     "pillar": "CS Fundamentals"},

    {"concept": "CS fundamentals learning roadmap: teachyourselfcs.com syllabus and OSSU sequencing strategy",
     "prereqs": "",
     "pillar": "CS Fundamentals"},

    # =========================================================================
    # SOFTWARE ENGINEERING (10 nodes from skills/software-eng-breadth/)
    # =========================================================================

    {"concept": "Python data model: mutability, identity vs equality, references, hashability, copy vs deepcopy",
     "prereqs": "",
     "pillar": "Software Engineering"},

    {"concept": "Python OOP: dunder methods, property, dataclasses, ABCs, MRO, composition vs inheritance",
     "prereqs": "Python data model: mutability, identity vs equality, references, hashability, copy vs deepcopy",
     "pillar": "Software Engineering"},

    {"concept": "Python concurrency: GIL mechanics, threading, multiprocessing, asyncio event loop, concurrent.futures",
     "prereqs": "Python data model: mutability, identity vs equality, references, hashability, copy vs deepcopy",
     "pillar": "Software Engineering"},

    {"concept": "Python functional style: generators, itertools, decorators, closures, context managers",
     "prereqs": "Python data model: mutability, identity vs equality, references, hashability, copy vs deepcopy",
     "pillar": "Software Engineering"},

    {"concept": "Python advanced async, typing, and testing: asyncio, Pydantic, mypy strict, pytest, Hypothesis",
     "prereqs": "Python concurrency: GIL mechanics, threading, multiprocessing, asyncio event loop, concurrent.futures",
     "pillar": "Software Engineering"},

    {"concept": "DSA patterns for ML eng interviews: arrays, trees, graphs, DP — LeetCode medium in 25 min",
     "prereqs": "",
     "pillar": "Software Engineering"},

    {"concept": "LeetCode practice cadence: NeetCode 150 pattern-by-pattern with AI-off timed attempts",
     "prereqs": "DSA patterns for ML eng interviews: arrays, trees, graphs, DP — LeetCode medium in 25 min",
     "pillar": "Software Engineering"},

    {"concept": "Git advanced workflows: interactive rebase, cherry-pick, bisect, worktrees, hooks, GitHub PR discipline",
     "prereqs": "",
     "pillar": "Software Engineering"},

    {"concept": "API design: REST resource conventions, GraphQL N+1 and DataLoader, gRPC protobuf and streaming",
     "prereqs": "Python advanced async, typing, and testing: asyncio, Pydantic, mypy strict, pytest, Hypothesis",
     "pillar": "Software Engineering"},

    {"concept": "System design fundamentals: CAP theorem, load balancing, caching, message queues, rate limiting, CDN",
     "prereqs": "Distributed systems: consensus (Raft), replication, CAP theorem, fault tolerance, sharding",
     "pillar": "Software Engineering"},

    # =========================================================================
    # COMPUTER VISION & MULTIMODAL (10 nodes from skills/cv-multimodal-idp/)
    # =========================================================================

    {"concept": "Vision Transformer (ViT): patch embedding, positional encoding, DINO self-supervised pretraining, CLIP",
     "prereqs": "Multi-head attention and the full Transformer block | Convolutional neural networks: filters, pooling, architectures",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "Object detection with YOLO: grid-based prediction, anchor boxes, NMS, mAP, fine-tuning YOLOv8",
     "prereqs": "Convolutional neural networks: filters, pooling, architectures",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "LayoutLM / Doc-AI: joint text + layout + image encoding, WPA pre-training, NER fine-tuning on forms",
     "prereqs": "Vision Transformer (ViT): patch embedding, positional encoding, DINO self-supervised pretraining, CLIP | BERT: masked language modeling and next-sentence prediction",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "Vision-Language Models (VLM): Qwen2.5-VL architecture, vision token count, when VLM beats OCR+LLM",
     "prereqs": "LayoutLM / Doc-AI: joint text + layout + image encoding, WPA pre-training, NER fine-tuning on forms | The complete Transformer architecture: encoder and decoder",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "ArcFace and metric learning: angular margin loss, hyperspherical embedding, triplet vs ArcFace",
     "prereqs": "Vision Transformer (ViT): patch embedding, positional encoding, DINO self-supervised pretraining, CLIP",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "FAISS for image search: index types (Flat, IVF, HNSW, PQ), recall-latency tradeoffs, GPU FAISS",
     "prereqs": "ArcFace and metric learning: angular margin loss, hyperspherical embedding, triplet vs ArcFace | Vector index internals: HNSW, IVF, and product quantization",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "OCR pipeline: image preprocessing, text detection (DBNet), CTC recognition, PaddleOCR vs Tesseract",
     "prereqs": "Convolutional neural networks: filters, pooling, architectures",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "IDP (Intelligent Document Processing) architecture: ingest, layout analysis, extraction, queue-based scale",
     "prereqs": "LayoutLM / Doc-AI: joint text + layout + image encoding, WPA pre-training, NER fine-tuning on forms | OCR pipeline: image preprocessing, text detection (DBNet), CTC recognition, PaddleOCR vs Tesseract",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "Diffusion models: DDPM forward/reverse process, DDIM, latent diffusion (Stable Diffusion), ControlNet",
     "prereqs": "Vision Transformer (ViT): patch embedding, positional encoding, DINO self-supervised pretraining, CLIP | Loss functions: MSE, cross-entropy, and when to use each",
     "pillar": "Computer Vision &amp; Multimodal"},

    {"concept": "CNN fundamentals and ResNet: convolution, pooling, batch norm, skip connections, ImageNet architectures",
     "prereqs": "Convolutional neural networks: filters, pooling, architectures",
     "pillar": "Computer Vision &amp; Multimodal"},

    # =========================================================================
    # INDIC & SPEECH AI (10 nodes from skills/indic-ai/)
    # =========================================================================

    {"concept": "Indic benchmarks: IndicGLUE, IndicGenBench (29 langs), MILU (80K MCQ), ParamBench evaluation landscape",
     "prereqs": "BERT variants: RoBERTa, DistilBERT, ALBERT, ELECTRA, DeBERTa",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Indic machine translation and transliteration: seq2seq, IndicTrans2, script conversion, Samanantar corpus",
     "prereqs": "Sequence-to-sequence and encoder-decoder architectures | Indic benchmarks: IndicGLUE, IndicGenBench (29 langs), MILU (80K MCQ), ParamBench evaluation landscape",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Indic TTS: Tacotron2/VITS architecture, mel spectrogram prediction, vocoder, multi-speaker conditioning",
     "prereqs": "Speech signal processing: STFT, mel spectrogram, MFCC, VAD for Indic ASR pipelines",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Indic ASR: CTC loss with blank token, Conformer encoder, IndicWhisper fine-tuning for 22 Indic languages",
     "prereqs": "Speech signal processing: STFT, mel spectrogram, MFCC, VAD for Indic ASR pipelines",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Speech signal processing: STFT, mel spectrogram, MFCC, VAD for Indic ASR pipelines",
     "prereqs": "",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Speaker diarization: VAD, speaker segmentation, x-vector/d-vector embeddings, AHC clustering",
     "prereqs": "Indic ASR: CTC loss with blank token, Conformer encoder, IndicWhisper fine-tuning for 22 Indic languages",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Indic tokenization: subword coverage for agglutinative scripts, Devanagari byte-pair encoding, script-aware vocab",
     "prereqs": "Subword tokenization: BPE, WordPiece, SentencePiece",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Multilingual encoders: mBERT, XLM-R, IndicBERT — cross-lingual transfer, language-neutral representations",
     "prereqs": "BERT: masked language modeling and next-sentence prediction | Indic tokenization: subword coverage for agglutinative scripts, Devanagari byte-pair encoding, script-aware vocab",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Continued pretraining for Indic: vocab expansion, embedding init, OpenHathi/Sarvam-1 recipe",
     "prereqs": "LLM pretraining: data, objectives, and training dynamics | Multilingual encoders: mBERT, XLM-R, IndicBERT — cross-lingual transfer, language-neutral representations",
     "pillar": "Indic &amp; Speech AI"},

    {"concept": "Sarvam ecosystem and code-switching: AI4Bharat stack, Hinglish handling, Indic interview prep strategy",
     "prereqs": "Continued pretraining for Indic: vocab expansion, embedding init, OpenHathi/Sarvam-1 recipe",
     "pillar": "Indic &amp; Speech AI"},

    # =========================================================================
    # STARTUP & PRODUCT (15 nodes from skills/startup-founder/)
    # =========================================================================

    {"concept": "Startup idea validation: ICP definition, Mom Test interviews, demand signals vs polite enthusiasm",
     "prereqs": "",
     "pillar": "Startup &amp; Product"},

    {"concept": "Bootstrapping fundamentals: default-alive mentality, ramen profitability, indie-hacker operating model",
     "prereqs": "Startup idea validation: ICP definition, Mom Test interviews, demand signals vs polite enthusiasm",
     "pillar": "Startup &amp; Product"},

    {"concept": "MVP and shipping fast: minimum viable product scoping, weekly release cadence, AI-accelerated solo dev",
     "prereqs": "Startup idea validation: ICP definition, Mom Test interviews, demand signals vs polite enthusiasm",
     "pillar": "Startup &amp; Product"},

    {"concept": "Positioning and messaging: April Dunford framework, competitive alternatives, differentiation, homepage copy",
     "prereqs": "Startup idea validation: ICP definition, Mom Test interviews, demand signals vs polite enthusiasm",
     "pillar": "Startup &amp; Product"},

    {"concept": "Pricing and business models: value-based pricing, Hormozi offer design, SaaS vs services vs productized",
     "prereqs": "Positioning and messaging: April Dunford framework, competitive alternatives, differentiation, homepage copy",
     "pillar": "Startup &amp; Product"},

    {"concept": "SaaS metrics and unit economics: MRR, churn, LTV/CAC, NRR, cohort retention, Rule of 40",
     "prereqs": "Pricing and business models: value-based pricing, Hormozi offer design, SaaS vs services vs productized",
     "pillar": "Startup &amp; Product"},

    {"concept": "Distribution and traction channels: Weinberg 19 channels, Bullseye framework, build-in-public, Product Hunt launch",
     "prereqs": "MVP and shipping fast: minimum viable product scoping, weekly release cadence, AI-accelerated solo dev",
     "pillar": "Startup &amp; Product"},

    {"concept": "Growth and retention: activation and aha-moment, Day-7/30 retention curves, PLG, NPS, churn playbooks",
     "prereqs": "SaaS metrics and unit economics: MRR, churn, LTV/CAC, NRR, cohort retention, Rule of 40 | Distribution and traction channels: Weinberg 19 channels, Bullseye framework, build-in-public, Product Hunt launch",
     "pillar": "Startup &amp; Product"},

    {"concept": "Marketing for technical founders: personal brand on X/LinkedIn, build-in-public content, developer marketing, SEO",
     "prereqs": "Distribution and traction channels: Weinberg 19 channels, Bullseye framework, build-in-public, Product Hunt launch",
     "pillar": "Startup &amp; Product"},

    {"concept": "Founder-led sales: cold email anatomy, SPIN discovery calls, objection handling, pipeline metrics, CRM",
     "prereqs": "MVP and shipping fast: minimum viable product scoping, weekly release cadence, AI-accelerated solo dev",
     "pillar": "Startup &amp; Product"},

    {"concept": "Strategy, moats, and zero-to-one: Thiel monopoly thesis, 4 moats, Business Model Canvas, market timing",
     "prereqs": "Positioning and messaging: April Dunford framework, competitive alternatives, differentiation, homepage copy",
     "pillar": "Startup &amp; Product"},

    {"concept": "Legal, ops, and finance for founders: Pvt Ltd vs LLP vs Delaware C-Corp, GST, Razorpay vs Stripe, bookkeeping",
     "prereqs": "Bootstrapping fundamentals: default-alive mentality, ramen profitability, indie-hacker operating model",
     "pillar": "Startup &amp; Product"},

    {"concept": "Founder psychology and focus: single-bet thinking, resilience frameworks, burnout prevention, reversible vs irreversible decisions",
     "prereqs": "Bootstrapping fundamentals: default-alive mentality, ramen profitability, indie-hacker operating model",
     "pillar": "Startup &amp; Product"},

    {"concept": "AI automation consulting agency: productized services for manufacturing/medical/marketing, SOPs, Rajasthan-Gujarat GTM",
     "prereqs": "Founder-led sales: cold email anatomy, SPIN discovery calls, objection handling, pipeline metrics, CRM | Legal, ops, and finance for founders: Pvt Ltd vs LLP vs Delaware C-Corp, GST, Razorpay vs Stripe, bookkeeping",
     "pillar": "Startup &amp; Product"},

    {"concept": "Productizing Eklavya: positioning, pricing tiers, ICP validation, launch plan, MRR milestones, moat articulation",
     "prereqs": "Growth and retention: activation and aha-moment, Day-7/30 retention curves, PLG, NPS, churn playbooks | Strategy, moats, and zero-to-one: Thiel monopoly thesis, 4 moats, Business Model Canvas, market timing",
     "pillar": "Startup &amp; Product"},

    # =========================================================================
    # RESEARCH & FRONTIER (14 nodes from skills/research-interp-papers/)
    # =========================================================================

    {"concept": "World models: MBRL, JEPA-style abstract prediction, DreamerV3 RSSM, LLMs-as-world-models debate",
     "prereqs": "Reinforcement learning fundamentals: MDPs, rewards, value functions | Scaling laws and emergent abilities",
     "pillar": "Research &amp; Frontier"},

    {"concept": "JEPA (Joint Embedding Predictive Architecture): I-JEPA, V-JEPA, predict in representation space not pixels",
     "prereqs": "World models: MBRL, JEPA-style abstract prediction, DreamerV3 RSSM, LLMs-as-world-models debate | Vision Transformer (ViT): patch embedding, positional encoding, DINO self-supervised pretraining, CLIP",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Robotics and embodied AI: VLA models (vision-language-action), sim-to-real transfer, diffusion policy",
     "prereqs": "Vision-Language Models (VLM): Qwen2.5-VL architecture, vision token count, when VLM beats OCR+LLM | Policy gradients and actor-critic methods",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Loop (recursive) Transformers: weight-shared iterative layers, depth-efficiency tradeoffs, universal approximation",
     "prereqs": "The complete Transformer architecture: encoder and decoder",
     "pillar": "Research &amp; Frontier"},

    {"concept": "New architectures: Mamba SSM (selective state spaces, O(1) inference), RWKV, linear-time attention alternatives",
     "prereqs": "Sparse and linear attention for long context | The complete Transformer architecture: encoder and decoder",
     "pillar": "Research &amp; Frontier"},

    {"concept": "TransformerLens and ARENA Chapter 1: hook points, logit lens, IOI circuit, SAE hands-on exercises",
     "prereqs": "Mechanistic interpretability: circuits, features, superposition | Sparse autoencoders for feature disentanglement",
     "pillar": "Research &amp; Frontier"},

    {"concept": "AI safety and alignment: Constitutional AI, scalable oversight, deceptive alignment, Anthropic RSP",
     "prereqs": "RLHF: reward models and PPO for LLM alignment | DPO and preference optimization without RL",
     "pillar": "Research &amp; Frontier"},

    {"concept": "JAX and TPU foundations: jit, grad, vmap, pmap, XLA compilation, Flax NNX, TPU systolic array",
     "prereqs": "JAX: functional arrays, jit, grad, vmap | Training at scale: mixed precision, data and model parallelism, checkpointing",
     "pillar": "Research &amp; Frontier"},

    {"concept": "RLVR and reasoning models: GRPO (Group Relative Policy Optimization), DeepSeek-R1, PRMs vs ORMs, o1 thinking tokens",
     "prereqs": "RLHF: reward models and PPO for LLM alignment | Policy gradients and actor-critic methods",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Frontier tracking practice: weekly tracking of RAG, agents, post-training, efficiency, interp, new-arch papers",
     "prereqs": "Scaling laws and emergent abilities",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Paper spine reading arc: Era 0-6 landmark papers from LeNet/LSTM to SAE/DeepSeek-R1, with implementations",
     "prereqs": "Building a GPT from scratch | Mechanistic interpretability: circuits, features, superposition",
     "pillar": "Research &amp; Frontier"},

    {"concept": "LLM architecture gallery: GPT-2/3/4o, LLaMA-3, Gemma-3, Mistral, DeepSeek, Qwen — key design differences",
     "prereqs": "Scaling laws and emergent abilities | Efficient attention: multi-query, grouped-query, FlashAttention",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Classic RL foundations: MDPs, Bellman equations, Q-learning, SARSA, TD learning, policy iteration, PPO derivation",
     "prereqs": "Reinforcement learning fundamentals: MDPs, rewards, value functions | Policy gradients and actor-critic methods",
     "pillar": "Research &amp; Frontier"},

    {"concept": "Econometrics for IO and causal economics: Leontief I/O, LATE, RDD, Heckman selection, spatial econometrics",
     "prereqs": "Maximum likelihood estimation and the Bayesian view | Statistical inference: estimation, confidence intervals, hypothesis testing",
     "pillar": "Research &amp; Frontier"},

    # =========================================================================
    # EXTENSIONS TO EXISTING PILLARS
    # =========================================================================

    # ---- GenAI/ML Engineering Stack: inference-optimization depth -----------

    {"concept": "CUDA GPU kernels: thread hierarchy, shared memory, warp divergence, writing custom kernels for ML ops",
     "prereqs": "Training at scale: mixed precision, data and model parallelism, checkpointing | PyTorch: nn.Module, optimizers, training loops, and data loaders",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "TensorRT-LLM and SGLang: NVIDIA compiler-optimized inference, radix-tree KV-cache sharing for RAG throughput",
     "prereqs": "LLM serving stacks: vLLM, TGI, and throughput tuning | KV cache, prompt caching, and continuous batching",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Turbo quantization and KV-cache quantization: 4-bit KV-quant, quality-memory tradeoffs, TurboQuant internals",
     "prereqs": "Quantization: post-training quant, GPTQ, AWQ, bitsandbytes, GGUF | KV cache, prompt caching, and continuous batching",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Agent Lightning RL: RL fine-tuning of VLMs with GRPO-style task-completion rewards, no reward model needed",
     "prereqs": "RLHF: reward models and PPO for LLM alignment | Vision-Language Models (VLM): Qwen2.5-VL architecture, vision token count, when VLM beats OCR+LLM",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Agentic RL in production: RL flywheel (prod traces → label → fine-tune → eval gate → shadow → monitor)",
     "prereqs": "Agent Lightning RL: RL fine-tuning of VLMs with GRPO-style task-completion rewards, no reward model needed | Production monitoring: drift detection and online evaluation",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Edge and on-device inference: CoreML, ONNX, TFLite, GGUF on-device, export pipeline, power-accuracy tradeoffs",
     "prereqs": "Quantization: post-training quant, GPTQ, AWQ, bitsandbytes, GGUF | LLM serving stacks: vLLM, TGI, and throughput tuning",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "TOON structured output format: compact typed notation, token reduction vs JSON, inter-agent message efficiency",
     "prereqs": "Structured and constrained decoding for JSON and grammars",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Inference cost economics: cost-per-token analysis, TTFT vs TPOT, model routing, distillation, self-host vs API",
     "prereqs": "LLM serving stacks: vLLM, TGI, and throughput tuning | Cost and latency optimization: caching and right-sizing models",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Continuous and dynamic batching: static vs dynamic vs iteration-level scheduling, PagedAttention scheduler",
     "prereqs": "KV cache, prompt caching, and continuous batching | LLM serving stacks: vLLM, TGI, and throughput tuning",
     "pillar": "GenAI/ML Engineering Stack"},

    {"concept": "Full inference optimization stack: KV-cache, PagedAttention, continuous batching, quant, spec-decode, vLLM prod",
     "prereqs": "Continuous and dynamic batching: static vs dynamic vs iteration-level scheduling, PagedAttention scheduler | Speculative decoding and latency optimization",
     "pillar": "GenAI/ML Engineering Stack"},

    # ---- AI Agents & Orchestration: agentic depth ---------------------------

    {"concept": "MCP internals: JSON-RPC 2.0 wire format, stdio/HTTP+SSE transports, tools/resources/prompts primitives",
     "prereqs": "Tool and function calling: schemas, status, timeouts, retries, idempotency",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "FastMCP: high-level Python framework for MCP servers, decorator-based tool/resource registration",
     "prereqs": "MCP internals: JSON-RPC 2.0 wire format, stdio/HTTP+SSE transports, tools/resources/prompts primitives",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "DSPy: declarative LLM programming, signatures, modules, optimizers (MIPRO/BootstrapFewShot), model-agnostic",
     "prereqs": "Prompt engineering: few-shot, chain-of-thought, decomposition | Tool and function calling: schemas, status, timeouts, retries, idempotency",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Langfuse: LLM observability, nested tracing, prompt versioning, LLM-as-judge scoring, CI/CD eval gates",
     "prereqs": "LLM evaluation: benchmarks, LLM-as-judge, and pitfalls | Observability and distributed tracing: OpenTelemetry, LangSmith, p95 latency",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "LangFlow and visual workflow tools: low-code LLM pipeline builder, drag-and-drop nodes, export to Python",
     "prereqs": "LangChain: chains, prompts, tools, and LCEL",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "SmolAgents and AutoGen: code-first minimal agent (HF), conversation-pattern multi-agent (Microsoft)",
     "prereqs": "Multi-agent orchestration: supervisor, choreography, map-reduce",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Computer use agents: screenshot-click-type loop, VLM action generation, hybrid rule-based + LLM design",
     "prereqs": "Vision-Language Models (VLM): Qwen2.5-VL architecture, vision token count, when VLM beats OCR+LLM | Planning, reflection, and self-correction in agents",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Agentic systems in production: failure modes, HITL interrupt/resume, cost-aware routing, trajectory evals",
     "prereqs": "Multi-agent orchestration: supervisor, choreography, map-reduce | Guardrails and robustness against prompt injection",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Prompt and context engineering: few-shot formatting, CoT elicitation, system prompt structure, token budgeting, prefix caching",
     "prereqs": "Prompt engineering: few-shot, chain-of-thought, decomposition",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Harrier embedding model: Microsoft Bing OSS embedding, when to use vs OpenAI/Cohere for dense retrieval",
     "prereqs": "Embedding similarity: cosine vs dot product and normalization | Sentence embeddings with Sentence-BERT",
     "pillar": "AI Agents &amp; Orchestration"},

    {"concept": "Evals engineering: offline golden sets, LLM-as-judge, agentic trajectory evals, regression gates, contamination avoidance",
     "prereqs": "LLM evaluation: benchmarks, LLM-as-judge, and pitfalls | RAG evaluation: recall@k, MRR, nDCG, and RAGAS",
     "pillar": "AI Agents &amp; Orchestration"},

    # ---- MLOps & LLMOps: depth extensions -----------------------------------

    {"concept": "Data pipelines with Airflow: DAGs, operators, scheduling, XComs, backfill, Prefect/Dagster alternatives",
     "prereqs": "CI/CD for ML: pipelines, testing, and model registries",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Spark and PySpark: RDD vs DataFrame API, Catalyst optimizer, joins, window functions, BigQuery integration",
     "prereqs": "ML pipelines end-to-end: data, features, training, serving",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Web scraping and crawling: BeautifulSoup, Playwright, Scrapy, async HTTP, robots.txt, rate limiting",
     "prereqs": "Python advanced async, typing, and testing: asyncio, Pydantic, mypy strict, pytest, Hypothesis",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "ML and LLM system design: RAG-at-scale, agent platform, recommendation, LLM serving infra, continuously-improving agent",
     "prereqs": "Designing production RAG systems | Designing agent systems for reliability and scale",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Model serving patterns: sync REST, async queues (Celery), SSE streaming, gRPC, WebSocket, sidecar, canary/blue-green",
     "prereqs": "Model serving and deployment with FastAPI endpoints | Containers and scaling: Docker and orchestration basics",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Model registry and versioning: MLflow experiment tracking, DVC for data versioning, HuggingFace Hub as registry",
     "prereqs": "Experiment tracking with MLflow and Weights and Biases",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Cloud ML: SageMaker training jobs/endpoints/batch, Bedrock managed LLM APIs, Gemma fine-tuning on spot instances",
     "prereqs": "Containers and scaling: Docker and orchestration basics | CI/CD for ML: pipelines, testing, and model registries",
     "pillar": "MLOps &amp; LLMOps"},

    {"concept": "Kubernetes for ML: Pods, Deployments, HPA, GPU node pools, Argo Workflows, Kubeflow, PersistentVolumes",
     "prereqs": "Containers and scaling: Docker and orchestration basics",
     "pillar": "MLOps &amp; LLMOps"},

    # ---- ML Theory & Math Foundations: foundations depth --------------------

    {"concept": "Measure theory and rigorous probability: sigma-algebras, Lebesgue integration, random variables formally",
     "prereqs": "Probability foundations: distributions, expectation, Bayes rule",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Information theory: entropy, KL divergence, mutual information, cross-entropy loss derived from theory",
     "prereqs": "Probability foundations: distributions, expectation, Bayes rule | Maximum likelihood estimation and the Bayesian view",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Stochastic processes and MCMC: Markov chains, stationary distributions, Metropolis-Hastings, NUTS sampler",
     "prereqs": "Probability foundations: distributions, expectation, Bayes rule | Optimization and gradient descent: convexity, learning rate, SGD variants",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Numerical methods: floating point, LU/QR/Cholesky factorizations, iterative solvers, stability",
     "prereqs": "Linear algebra for ML: vectors, matrices, dot products, norms | Calculus for ML: derivatives, gradients, chain rule, Jacobians",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Discrete mathematics: combinatorics, graph theory basics, probability on discrete spaces, Boolean algebra",
     "prereqs": "Probability foundations: distributions, expectation, Bayes rule",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Optimization theory: convex sets, duality, KKT conditions, interior-point methods beyond gradient descent",
     "prereqs": "Optimization and gradient descent: convexity, learning rate, SGD variants | Calculus for ML: derivatives, gradients, chain rule, Jacobians",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Signal processing for ML: Fourier transform, convolution theorem, wavelets, applications to audio/time-series",
     "prereqs": "Linear algebra for ML: vectors, matrices, dot products, norms | Calculus for ML: derivatives, gradients, chain rule, Jacobians",
     "pillar": "ML Theory &amp; Math Foundations"},

    {"concept": "Stochastic calculus and quantitative finance: Brownian motion, Ito lemma, Black-Scholes, portfolio optimization",
     "prereqs": "Stochastic processes and MCMC: Markov chains, stationary distributions, Metropolis-Hastings, NUTS sampler | Statistical inference: estimation, confidence intervals, hypothesis testing",
     "pillar": "ML Theory &amp; Math Foundations"},

    # ---- Econometrics & Statistics: classical/causal depth ------------------

    {"concept": "Panel data econometrics: fixed effects, random effects, Hausman test, DiD with staggered treatment",
     "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing | Linear regression: least squares, assumptions, normal equations",
     "pillar": "Econometrics &amp; Statistics"},

    {"concept": "Causal inference: potential outcomes, DiD, IV with 2SLS, RDD, A/B design, LATE, uplift modeling",
     "prereqs": "Panel data econometrics: fixed effects, random effects, Hausman test, DiD with staggered treatment | Statistical inference: estimation, confidence intervals, hypothesis testing",
     "pillar": "Econometrics &amp; Statistics"},

    {"concept": "Bayesian methods: posterior inference, MCMC, GP-based Bayesian optimization, variational inference, beta-binomial A/B",
     "prereqs": "Maximum likelihood estimation and the Bayesian view | Stochastic processes and MCMC: Markov chains, stationary distributions, Metropolis-Hastings, NUTS sampler",
     "pillar": "Econometrics &amp; Statistics"},

    {"concept": "A/B testing and experimentation: power analysis, CUPED variance reduction, sequential testing, SUTVA, Simpson's paradox",
     "prereqs": "Statistical inference: estimation, confidence intervals, hypothesis testing | Bayesian methods: posterior inference, MCMC, GP-based Bayesian optimization, variational inference, beta-binomial A/B",
     "pillar": "Econometrics &amp; Statistics"},

    {"concept": "Anomaly detection: Isolation Forest, LOF, Z-score, IQR, CUSUM, STL residuals, autoencoder-based detection",
     "prereqs": "Model evaluation: train/val/test, cross-validation, and data leakage | Clustering: k-means, hierarchical, DBSCAN",
     "pillar": "Econometrics &amp; Statistics"},

    # ---- NLP & Representation Learning: classical NLP history ---------------

    {"concept": "Information retrieval and BM25: VSM, TF-IDF scoring, BM25 term saturation and field normalization, inverted index",
     "prereqs": "Bag-of-words and TF-IDF text representations",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Coreference resolution: mention detection, entity linking, neural coref, applications to document understanding",
     "prereqs": "Sequence labeling: POS tagging, NER, HMMs and CRFs",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Syntactic parsing: POS tagging, constituency parsing (CYK/Earley), dependency parsing (arc-eager/arc-standard)",
     "prereqs": "Sequence labeling: POS tagging, NER, HMMs and CRFs",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Classical question answering: extractive QA on SQuAD, retrieval-based QA, passage ranking, SQuAD evaluation",
     "prereqs": "Text classification with classical ML | Bag-of-words and TF-IDF text representations",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Text summarization: extractive (TextRank, sentence scoring) vs abstractive (seq2seq), ROUGE evaluation",
     "prereqs": "Sequence-to-sequence and encoder-decoder architectures | Bag-of-words and TF-IDF text representations",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Machine translation history: SMT phrase tables, IBM alignment models, then NMT seq2seq revolution",
     "prereqs": "Sequence-to-sequence and encoder-decoder architectures | N-gram language models and smoothing",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Classical semantic similarity search: VSM cosine, LSA, Doc2Vec, dense retrieval evolution",
     "prereqs": "Bag-of-words and TF-IDF text representations | Word embeddings: word2vec, GloVe, fastText",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Text representation evolution: BOW → TF-IDF → word2vec → ELMo → BERT — what each representation gains",
     "prereqs": "Word embeddings: word2vec, GloVe, fastText | BERT: masked language modeling and next-sentence prediction",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "NLP history arc: rule-based → statistical → neural — key moments, why each transition happened",
     "prereqs": "N-gram language models and smoothing | Sequence-to-sequence and encoder-decoder architectures",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Graph neural networks: message passing, node embedding aggregation, GCN, GAT, applications to knowledge graphs",
     "prereqs": "Embedding layers and learned representations | Clustering: k-means, hierarchical, DBSCAN",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Node embeddings: node2vec random walks, DeepWalk, LINE, structural vs neighborhood similarity",
     "prereqs": "Word embeddings: word2vec, GloVe, fastText | Graph neural networks: message passing, node embedding aggregation, GCN, GAT, applications to knowledge graphs",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Learning to rank and recommenders: pointwise/pairwise/listwise LTR, two-tower models, collaborative filtering, NDCG",
     "prereqs": "Bi-encoders vs cross-encoders for retrieval and ranking | Re-ranking with cross-encoders and MMR diversification",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Multi-label classification and Hamming loss: label powerset, per-label thresholding, imbalance strategies",
     "prereqs": "Text classification with classical ML | Classification metrics: precision, recall, F1, ROC-AUC, PR curves",
     "pillar": "NLP &amp; Representation Learning"},

    {"concept": "Synthetic data and adversarial augmentation: back-translation, label powerset SMOTE, paraphrase generation",
     "prereqs": "Text classification with classical ML | Multi-label classification and Hamming loss: label powerset, per-label thresholding, imbalance strategies",
     "pillar": "NLP &amp; Representation Learning"},

    # ---- Time-Series & Forecasting: extra depth -----------------------------

    {"concept": "Hierarchical time-series: N-Beats (residual + basis expansion), NHiTS (multi-rate sampling), reconciliation",
     "prereqs": "ML and deep forecasting: gradient boosting, N-BEATS, Temporal Fusion Transformer",
     "pillar": "Time-Series &amp; Forecasting"},

    {"concept": "GARCH and VAR for financial time-series: volatility clustering, ARIMAX, Granger causality, impulse responses",
     "prereqs": "Classical forecasting: ARIMA, SARIMA, exponential smoothing, Prophet",
     "pillar": "Time-Series &amp; Forecasting"},

    {"concept": "Feature engineering for time-series: lag features, rolling stats, Fourier seasonality, tsfresh automated extraction",
     "prereqs": "Time-series fundamentals: stationarity, autocorrelation, decomposition",
     "pillar": "Time-Series &amp; Forecasting"},

    # ---- LLM & Deep Learning Internals: extras ------------------------------

    {"concept": "Mixture of experts: routing mechanisms, top-k gating, load balancing loss, expert capacity, MoE-routing stability",
     "prereqs": "The complete Transformer architecture: encoder and decoder | Scaling laws and emergent abilities",
     "pillar": "LLM &amp; Deep Learning Internals"},

    {"concept": "xLSTM and RNN architectures revisited: exponential gating, matrix memory, when RNNs beat Transformers",
     "prereqs": "Recurrent networks: RNN, LSTM, GRU and vanishing gradients | New architectures: Mamba SSM (selective state spaces, O(1) inference), RWKV, linear-time attention alternatives",
     "pillar": "LLM &amp; Deep Learning Internals"},

    {"concept": "Weight initialization: Xavier/Glorot, He/Kaiming, orthogonal init, why initialization affects convergence",
     "prereqs": "Neural networks and backpropagation from first principles | Normalization: batch norm, layer norm, and RMSNorm",
     "pillar": "LLM &amp; Deep Learning Internals"},

    {"concept": "Long-context extension techniques: YaRN, positional interpolation, ALiBi, sliding window, memory-efficient methods",
     "prereqs": "Context-length extension techniques | Positional encodings: absolute, rotary (RoPE), and ALiBi",
     "pillar": "LLM &amp; Deep Learning Internals"},

    {"concept": "Pretraining objectives: CLM (next-token), MLM (masked), span corruption (T5), UL2 (mixture) — tradeoffs",
     "prereqs": "The language modeling objective and autoregressive generation | BERT: masked language modeling and next-sentence prediction",
     "pillar": "LLM &amp; Deep Learning Internals"},

    {"concept": "Train-from-scratch ladder: nanoGPT → GPT-2 size → scaling experiment — the Karpathy reproduction path",
     "prereqs": "Building a GPT from scratch | LLM pretraining: data, objectives, and training dynamics",
     "pillar": "LLM &amp; Deep Learning Internals"},
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
        for frag in n["prereqs"].split("|"):
            if not frag.strip():
                continue
            r = resolve(frag)
            if r is None:
                # Prereq concept not in DB yet — record as informational, skip gracefully.
                # This happens when the upstream seeder (seed_ai_curriculum.py) hasn't been
                # applied to this particular DB instance. The node is still added as a
                # reachable concept (prereq omitted), which is correct additive behavior.
                unresolved.append((n["concept"], frag.strip()))
            elif r not in outp:
                outp.append(r)
        resolved.append({**n, "prereqs": " | ".join(outp)})

    # cycle check over resolved edges within new nodes
    name_to_prereqs = {
        r["concept"]: [p.strip() for p in r["prereqs"].split("|") if p.strip()]
        for r in resolved
    }
    existing_set = set(existing)
    cycles = []

    def has_path(a, b, seen):
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

    # substring collisions (informational only)
    collisions = [(a, b) for a in all_names for b in all_names if a != b and a in b]

    # duplicates (concepts already in DB by exact string)
    dup = [n["concept"] for n in new if n["concept"] in existing_set]

    new_pillar_strs = [html.unescape(p) for p in NEW_PILLARS]
    # pillars that are genuinely new (not already in the DB)
    existing_pillars = {r["name"] for r in conn.execute("SELECT name FROM pillars")}
    truly_new_pillars = [p for p in new_pillar_strs if p not in existing_pillars]

    print(
        f"NEW nodes: {len(new)} | already-present dupes (will skip): {len(dup)} | "
        f"unresolved prereqs: {len(unresolved)} | cycles: {len(cycles)}"
    )
    print(
        f"New pillars to add: {len(truly_new_pillars)} "
        f"(of {len(NEW_PILLARS)} listed, {len(NEW_PILLARS) - len(truly_new_pillars)} already exist)"
    )
    if unresolved:
        print(f"  INFO — {len(unresolved)} prereq refs not in this DB instance (seeded as root concepts).")
        for u in unresolved[:10]:
            print("    skip prereq:", u[1][:70], "(for:", u[0][:50] + "...)")
        if len(unresolved) > 10:
            print(f"    ... and {len(unresolved) - 10} more (all skipped gracefully, not destructive)")
    for c in cycles:
        print("  CYCLE:", c)
    if dup:
        for d in dup:
            print("  DUP (will skip):", d[:90])
    print(f"  (name-substring pairs: {len(collisions)} — harmless, prereqs are pipe-delimited exact)")

    net_new = len(new) - len(dup)
    print(f"\nNet new nodes to insert: {net_new}")
    print(f"Concepts before apply: {len(existing)}")
    print(f"Concepts after apply:  {len(existing) + net_new} (projected)")

    if not apply:
        print("\nDRY RUN — no writes. Re-run with --apply to seed.")
        conn.close()
        return
    if cycles:
        print("\nABORT: cycles detected above must be fixed before applying.")
        conn.close()
        return

    # Snapshot before writing (uses Eklavya's own backup mechanism)
    from eklavya.backups import snapshot
    snap_id = snapshot("before seed_parity_from_vault --apply")
    print(f"\nSnapshot taken: {snap_id}")

    for p in new_pillar_strs:
        tools.add_pillar(p)
    # Note: set_baseline_rating is intentionally skipped here. The ratings table
    # unique constraint in this DB instance is (pillar_id, axis, subject) but
    # set_baseline_rating's ON CONFLICT clause targets (pillar_id, axis), which raises
    # an OperationalError on this schema version. Pillar ratings can be set manually
    # via the tutor's onboarding flow. The curriculum graph (concepts + prereqs) is
    # the load-bearing deliverable; ratings are not required for navigation to work.

    added = 0
    for r in resolved:
        if r["concept"] in existing_set:
            continue
        tools.add_curriculum(r["concept"], r["prereqs"], r["pillar"])
        added += 1

    conn.close()
    # Report final count
    conn2 = connect()
    final_count = conn2.execute("SELECT COUNT(*) FROM curriculum").fetchone()[0]
    conn2.close()
    print(f"\nAPPLIED: +{len(truly_new_pillars)} new pillars, +{added} curriculum nodes.")
    print(f"Concepts in DB now: {final_count}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
