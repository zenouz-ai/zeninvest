---
tags: [investment-agent, meta, sync]
status: active
last_updated: 2026-03-18
---

# Obsidian Sync Instructions

> This file tells Claude how to perform a GitHub → Obsidian sync for the Investment Agent project.
> Copy this file to your GitHub repo at `docs/obsidian-sync/SYNC_INSTRUCTIONS.md` and keep both in sync.

---

## Purpose

The GitHub repo (`kayvannejabati/investment-agent`) contains detailed technical documentation.
The Obsidian vault (`12_Investment-Agent/`) holds high-level strategic notes for thinking and reference.

The sync job is **not** a copy — it is a **distillation**. Claude reads the GitHub docs and updates the Obsidian notes with anything that materially changed: new capabilities, shifted priorities, architectural decisions, learnings, and status.

---

## GitHub Source Files → Obsidian Target Notes

| GitHub file (relative to repo root) | Obsidian note | What to extract |
|---|---|---|
| `README.md` | `Project Overview.md` | Current status, recent deliveries, next priorities, tech stack changes |
| `docs/architecture.md` or `ARCHITECTURE.md` | `Multi-LLM Pipeline Architecture.md` | New agents, changed data flows, updated consensus logic |
| `docs/roadmap.md` or `ROADMAP.md` | `Sophistication Roadmap.md` | Items promoted from pipeline → in progress → delivered; new items added |
| `docs/risk.md` or any risk-related doc | `Risk and Governance Framework.md` | New hard rules, changed thresholds, new failure modes |
| `docs/data-pipeline.md` | `Data Pipeline Rationale.md` | New data sources added/removed, rationale changes |
| `docs/backtesting.md` | `Backtesting and Validation.md` | New validation runs, changed methodology, walk-forward results |
| `docs/order-management.md` | `Order Management and Execution.md` | New order types, changed stop-loss logic, execution changes |
| `CHANGELOG.md` or git commit summaries | All relevant notes | Learnings, surprises, things that didn't work |

> If a GitHub doc doesn't exist yet, skip it — don't create Obsidian content from nothing.

---

## What to Update vs What to Leave Alone

**Update freely:**
- `## Current Status` sections — replace with latest state
- `## Next Priorities` or roadmap lists — reflect current backlog
- Any section that tracks numbers (test count, feature count, cycle timing)
- Architecture diagrams/summaries when components change

**Update additively (append, don't replace):**
- `## Key Learnings` — add new ones, don't remove old ones
- `## Architectural Decisions` — add new ADRs with date, don't edit old ones
- `## Open Questions` — add new ones; remove only if explicitly resolved

**Leave completely alone:**
- The Obsidian frontmatter `tags` field
- `## Related Notes` link sections
- Any section marked `<!-- MANUAL -->` in the note

---

## Sync Scope Rules

- **Only update what changed.** If a section looks the same as what's already in Obsidian, skip it.
- **Preserve Obsidian voice.** Notes are written for personal reference, not as technical docs. Keep language concise and opinionated.
- **No code blocks** in Obsidian notes unless it's a short architecture diagram (like the pipeline tree in Project Overview).
- **No implementation detail** — Obsidian notes explain *what* and *why*, not *how*. Leave the *how* in GitHub.
- After each sync, update `last_updated` in the frontmatter of every note that was touched, and update `00_Index.md` if the Quick Reference table needs refreshing.

---

## Sync Frequency

Target: once every 2–4 weeks, or after a major milestone (new feature shipped, architecture change, significant learning).

---

## How to Trigger

Open Claude chat and paste the **Sync Prompt** (stored in this note below, and also in `12_Investment-Agent/SYNC_INSTRUCTIONS.md` in Obsidian).

---

## The Sync Prompt

Paste this into Claude chat to run a sync session:

```
I want to run a GitHub → Obsidian sync for my Investment Agent project.

GitHub repo: https://github.com/kayvannejabati/investment-agent

Please:
1. Fetch the key docs from GitHub (README, CHANGELOG, any docs/ folder files you can access via raw.githubusercontent.com)
2. Read my current Obsidian notes in 12_Investment-Agent/ using your MCP tools
3. For each note, identify what has materially changed since last_updated in the frontmatter
4. Update only the changed sections, following the rules in 12_Investment-Agent/SYNC_INSTRUCTIONS.md
5. Update last_updated frontmatter on any note you touch
6. Give me a brief summary of what you changed and what you skipped

Do not rewrite notes wholesale — surgical updates only. Preserve the existing voice and structure.
```
