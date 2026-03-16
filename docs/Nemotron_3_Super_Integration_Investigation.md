# Nemotron 3 Super — Integration Investigation & Roadmap Item

> **Status:** To Investigate
> **Priority:** Medium-High
> **Added:** 2026-03-16
> **Category:** Committee Architecture / Cost Optimisation

---

## Context

NVIDIA Nemotron 3 Super (120B total / 12B active parameters) is a hybrid Mamba-Transformer MoE model released 2026-03-11, purpose-built for agentic reasoning, tool calling, and multi-step workflows. It uses an OpenAI-compatible API, making it a drop-in candidate for one of the investment agent's committee member roles.

Key properties:
- **Architecture:** Latent MoE with Mamba-2 + Transformer layers, Multi-Token Prediction
- **Context window:** 1M tokens (native, not bolted on)
- **Throughput:** ~450 tokens/sec, 2.2x faster than GPT-OSS-120B, 7.5x faster than Qwen3.5-122B
- **Benchmarks:** #1 on DeepResearch Bench, 85.6% PinchBench, 60.47% SWE-Bench Verified, 91.75% RULER at 1M context
- **Reasoning toggle:** Chain-of-thought can be enabled/disabled per request via `enable_thinking` flag
- **Licence:** NVIDIA Nemotron Open Model License (commercially usable)
- **Self-hosting:** Not feasible on current hardware (needs 64GB+ VRAM/unified memory; MacBook Air has 24GB)

## Strategic Rationale

### Why investigate this for the investment agent?

1. **Cost reduction** — OpenRouter offers a free tier; paid tiers are ~$0.30/$0.80 per million tokens (input/output), significantly cheaper than Claude Sonnet or GPT-4o
2. **Agentic alignment** — RL-trained specifically for multi-step tool calling, structured reasoning pipelines, and sequential action planning — exactly what the committee members do
3. **1M context window** — Could allow feeding substantially more market history, previous decisions, and full earnings reports without truncation/summarisation
4. **Vendor diversification** — Reduces dependency on any single provider; open-weight model means future self-hosting is possible with infrastructure upgrades
5. **Throughput** — Faster inference could tighten the agent's decision loop within trading cycles

### Recommended target role

**Risk Scorer (currently Gemini Flash)** — Nemotron's structured reasoning and tool-calling strength maps well to disciplined risk assessment. It's less suited to replace Claude Sonnet's qualitative strategy synthesis or GPT-4o's skeptic/moderator nuance.

Secondary option: **Skeptic Moderator** — if shadow testing shows strong adversarial reasoning quality.

## Investigation Plan

### Phase 1: API Access & Smoke Test
- [ ] Create accounts on OpenRouter and/or build.nvidia.com
- [ ] Obtain API keys
- [ ] Run basic completion test using OpenAI-compatible Python client:

```python
from openai import OpenAI

# Option A: OpenRouter (free tier available)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="OPENROUTER_API_KEY"
)

# Option B: NVIDIA NIM
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="NVIDIA_API_KEY"
)

response = client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",  # or ":free" suffix on OpenRouter
    messages=[
        {"role": "system", "content": "You are a financial risk analyst..."},
        {"role": "user", "content": "Assess the risk profile of holding NVDA given current market conditions..."}
    ],
    temperature=0.6,
    top_p=0.95
)
```

- [ ] Verify response format, latency, and token usage
- [ ] Test with reasoning enabled (`enable_thinking: true`) vs disabled — compare quality and cost

### Phase 2: Shadow Mode Integration
- [ ] Create a new committee member class (e.g., `NemotronRiskScorer`) alongside existing `GeminiFlashRiskAssessor`
- [ ] Wire it to receive the same input data as Gemini Flash
- [ ] Log Nemotron's risk scores, reasoning traces, and latency to the decision audit trail
- [ ] Run both in parallel for minimum 5 full trading cycles (60 hours)
- [ ] Do NOT let Nemotron's output influence actual trades during this phase

### Phase 3: Comparative Analysis
- [ ] Compare Nemotron vs Gemini Flash outputs across dimensions:
  - Risk score accuracy (did the flagged risks materialise?)
  - Reasoning quality (depth, specificity, false positives/negatives)
  - Latency per call
  - Token usage and cost per cycle
  - Consistency across repeated calls with same input
- [ ] Document findings in decision log

### Phase 4: Promotion Decision
- [ ] If Nemotron meets or exceeds Gemini Flash quality:
  - Swap Nemotron into the live risk scoring role
  - Keep Gemini Flash as fallback (cost-aware graceful degradation pattern)
  - Update Slack notifications to identify which model produced each assessment
- [ ] If Nemotron is close but not quite:
  - Consider using it as an additional committee voice (4th member) rather than a replacement
  - Evaluate whether the 1M context window alone justifies the addition
- [ ] If Nemotron underperforms:
  - Archive findings, revisit when model is updated
  - Consider Nemotron 3 Nano (30B/3B active) for lighter-weight tasks instead

### Phase 5: Extended Context Experiment (Optional)
- [ ] If Phase 4 is successful, experiment with feeding significantly more context:
  - Full 30-day price history instead of summarised
  - Complete earnings call transcripts
  - Previous 10 trading decisions with outcomes
  - Multiple analyst reports per ticker
- [ ] Measure whether expanded context improves risk assessment quality
- [ ] Monitor token costs — 1M context is available but not free to fill

## API Provider Comparison

| Provider | Base URL | Pricing (Input/Output per 1M tokens) | Notes |
|----------|----------|---------------------------------------|-------|
| OpenRouter (free) | `https://openrouter.ai/api/v1` | $0 / $0 | Rate limited, good for testing |
| OpenRouter (paid) | `https://openrouter.ai/api/v1` | ~$0.30 / $0.80 | Production viable |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | Free trial credits | First-party, may have best optimisation |
| Together AI | `https://api.together.xyz/v1` | TBD — check current pricing | Good reliability track record |
| DeepInfra | `https://api.deepinfra.com/v1/openai` | TBD — check current pricing | Often cheapest for open models |

## Architectural Notes

- Uses OpenAI-compatible API — same `openai` Python package, just different `base_url` and `model` string
- Supports tool/function calling natively (important for agentic research phases B-E)
- Reasoning mode is per-request toggleable — can use thinking mode for complex analysis, skip it for simple lookups
- If integrated, add provider config to the agent's cost-aware degradation system so it falls back gracefully if the provider has issues

## Links

- [NVIDIA Blog Post](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/)
- [Hugging Face (FP8)](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8)
- [NVIDIA NIM Endpoint](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
- [OpenRouter](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free)
- [GitHub - Nemotron Resources](https://github.com/NVIDIA-NeMo/Nemotron)
- [Technical Report](https://research.nvidia.com/labs/nemotron/Nemotron-3-Super/)

## Relation to Existing Roadmap

- **Connects to:** Agentic Research Project (Phases B-E) — Nemotron's native tool calling could serve research tasks
- **Connects to:** Dashboard — new model's outputs would appear in committee decision views
- **Connects to:** Cost Degradation Tracking — new provider adds another dimension to monitor
- **Connects to:** Proactive Macro News Intelligence — 1M context window could ingest broader macro context
- **Follows pattern:** "Earn Your Place" Data Rationale — Nemotron must justify its seat via shadow testing before going live
- **Follows pattern:** Backtesting with Walk-Forward Validation and Promotion Gates — shadow mode → analysis → promotion decision
