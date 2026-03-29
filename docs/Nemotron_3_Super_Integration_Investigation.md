---
title: Nemotron 3 Super Integration Investigation
tags: [nemotron, investigation, moderation, cost-optimization]
status: archive
last_updated: 2026-03-29
user_stories: [US-2.4]
---

> **Archived:** Investigation stalled; no active integration plan. See [SOPHISTICATION_ROADMAP.md](SOPHISTICATION_ROADMAP.md) US-2.4.

# Nemotron 3 Super Integration Investigation

> Investigation of Nemotron 3 Super as a potential committee model, with shadow-test gates before any production promotion.

## Purpose

This document evaluates whether NVIDIA Nemotron 3 Super should be added to the investment agent's committee architecture. It defines strategic rationale, a phased investigation plan, provider options, and promotion criteria.

Current status is investigation only. No production integration is implied by this document.

---

## Context

NVIDIA Nemotron 3 Super (120B total / 12B active parameters) is a hybrid Mamba-Transformer MoE model released 2026-03-11, purpose-built for agentic reasoning, tool calling, and multi-step workflows. It uses an OpenAI-compatible API, making it a candidate for a committee role in this project.

Key properties:
- **Architecture:** Latent MoE with Mamba-2 + Transformer layers, Multi-Token Prediction
- **Context window:** 1M tokens (native, not bolted on)
- **Throughput:** ~450 tokens/sec, 2.2x faster than GPT-OSS-120B, 7.5x faster than Qwen3.5-122B
- **Benchmarks:** #1 on DeepResearch Bench, 85.6% PinchBench, 60.47% SWE-Bench Verified, 91.75% RULER at 1M context
- **Reasoning toggle:** Chain-of-thought can be enabled/disabled per request via `enable_thinking`
- **License:** NVIDIA Nemotron Open Model License (commercially usable)
- **Self-hosting:** Not feasible on current hardware (needs 64GB+ VRAM/unified memory; current MacBook Air has 24GB)

## Strategic Rationale

### Why investigate this for the investment agent?

1. **Cost reduction** — OpenRouter offers a free tier; paid tiers are about $0.30/$0.80 per million tokens (input/output), materially lower than Claude Sonnet and GPT-4o.
2. **Agentic alignment** — RL-trained for multi-step tool calling and sequential reasoning workflows, aligned with committee behavior.
3. **Large context** — 1M context could support larger decision history, filings, and macro inputs with less truncation.
4. **Vendor diversification** — reduces single-provider concentration and preserves future self-host options with stronger hardware.
5. **Throughput** — faster inference may improve cycle-time headroom.

### Recommended target role

**Risk Scorer (currently Gemini Flash)** is the primary candidate role. Nemotron's structured reasoning and tool-calling strengths map naturally to risk scoring.

Secondary option: **Skeptic Moderator** if shadow testing shows strong adversarial reasoning quality.

---

## Investigation Plan

### Phase 1: API Access and Smoke Test
- [ ] Create accounts on OpenRouter and/or build.nvidia.com
- [ ] Obtain API keys
- [ ] Run a basic completion test using OpenAI-compatible client wiring:

```python
from openai import OpenAI

# Option A: OpenRouter (free tier available)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="OPENROUTER_API_KEY",
)

# Option B: NVIDIA NIM
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="NVIDIA_API_KEY",
)

response = client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",  # or ":free" suffix on OpenRouter
    messages=[
        {"role": "system", "content": "You are a financial risk analyst..."},
        {"role": "user", "content": "Assess the risk profile of holding NVDA given current market conditions..."},
    ],
    temperature=0.6,
    top_p=0.95,
)
```

- [ ] Verify response schema, latency, and token usage
- [ ] Compare `enable_thinking: true` vs disabled for quality/cost trade-off

### Phase 1 Status Update (2026-03-16)

Smoke test was run successfully via OpenRouter using model `nvidia/nemotron-3-super-120b-a12b:free`.

| Check | Result |
|------|--------|
| API connectivity | Pass |
| Response latency | ~4.2s (text prompt); ~8.9s in strict-JSON prompt run |
| Token usage observed | 153 total (text run), 296 total (JSON run) |
| Output quality | Usable and relevant for risk commentary |
| Structured output reliability | Mixed (strict JSON prompt did not reliably return parseable JSON) |

Implication for integration:
- Nemotron is reachable and can produce useful risk content for this project.
- For shadow-mode integration, add robust output normalization/retry rules (for example: JSON schema validator + fallback parser) before making it a scored committee signal.

### Phase 2: Shadow-Mode Integration
- [ ] Create a committee class (for example `NemotronRiskScorer`) alongside `GeminiFlashRiskAssessor`
- [ ] Feed identical inputs as Gemini
- [ ] Log Nemotron risk scores, reasoning traces, and latency in the audit trail
- [ ] Run both in parallel for at least 5 full cycles (about 60 hours)
- [ ] Keep Nemotron output non-binding in this phase

### Phase 3: Comparative Analysis
- [ ] Compare Nemotron vs Gemini across:
  - Risk-score accuracy (did flagged risks materialize?)
  - Reasoning depth/specificity and false positives/negatives
  - Latency per call
  - Token usage and cost per cycle
  - Consistency across repeat runs on same inputs
- [ ] Record findings in decision logs

### Phase 4: Promotion Decision
- [ ] If Nemotron meets/exceeds Gemini quality:
  - Promote Nemotron to live risk-scoring role
  - Keep Gemini as fallback in cost/degradation chain
  - Update alerts to show model attribution
- [ ] If close but not sufficient:
  - Consider adding Nemotron as an extra committee voice
  - Reassess whether large-context benefits justify added complexity
- [ ] If underperforming:
  - Archive findings and revisit on model updates
  - Evaluate Nemotron 3 Nano for lighter workloads

### Phase 5: Extended Context Experiment (Optional)
- [ ] If promoted, test expanded-context inputs:
  - Full 30-day price history
  - Full earnings call transcripts
  - Prior 10 decisions with outcomes
  - Multiple analyst reports per ticker
- [ ] Measure quality lift vs baseline context
- [ ] Monitor cost impact of large-context usage

---

## API Provider Comparison

| Provider | Base URL | Pricing (Input/Output per 1M tokens) | Notes |
|----------|----------|---------------------------------------|-------|
| OpenRouter (free) | `https://openrouter.ai/api/v1` | $0 / $0 | Rate limited, good for testing |
| OpenRouter (paid) | `https://openrouter.ai/api/v1` | ~$0.30 / $0.80 | Production-viable option |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | Free trial credits | First-party endpoint |
| Together AI | `https://api.together.xyz/v1` | TBD (verify current pricing) | Often reliable for open models |
| DeepInfra | `https://api.deepinfra.com/v1/openai` | TBD (verify current pricing) | Often low-cost for open models |

## Architectural Notes

- Uses OpenAI-compatible APIs (same `openai` package with provider-specific `base_url` + `model`)
- Supports tool/function calling natively (relevant to agentic research workflows)
- Reasoning mode is request-level toggleable via `enable_thinking`
- Any rollout should be wired into cost-aware degradation and fallback handling before promotion

## Sources

- [NVIDIA Blog Post](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/)
- [Hugging Face (FP8)](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8)
- [NVIDIA NIM Endpoint](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
- [OpenRouter](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free)
- [GitHub - Nemotron Resources](https://github.com/NVIDIA-NeMo/Nemotron)
- [Technical Report](https://research.nvidia.com/labs/nemotron/Nemotron-3-Super/)

## Relation to Existing Roadmap

- **Connects to:** Agentic Research — native tool-calling fit for research-enabled committee flows
- **Connects to:** Dashboard — potential model output visibility in committee views
- **Connects to:** Cost degradation tracking — adds provider path and budget monitoring dimension
- **Connects to:** Macro intelligence — large context may support broader macro evidence ingestion
- **Follows pattern:** Data-rationale promotion gate ("earn your place" via shadow testing)
- **Follows pattern:** Shadow -> analysis -> promotion lifecycle used in other model/infrastructure changes

---

## Related Notes

- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — investigation tracking and prioritization
- [Architecture](ARCHITECTURE.md) — current live pipeline and moderation design
- [Governance](GOVERNANCE.md) — model promotion controls, audit trail, and cost controls
- [Local Setup](LOCAL_SETUP.md) — environment-variable guidance for optional providers
- [Agentic Research](AGENTIC_RESEARCH.md) — committee tool-use architecture
