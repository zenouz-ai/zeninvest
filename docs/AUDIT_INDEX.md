---
tags: [audit, index, security, quality]
status: active
last_updated: 2026-03-29
---

# Audit Index

> Cross-reference of all audit findings across the four audit documents. Use this to navigate to specific findings or assess overall remediation progress.

## Audit Documents

| Document | Focus | Findings | Date |
|----------|-------|----------|------|
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | Architectural completeness and codebase quality | 2C + 5I + 4M | 2026-03-17 |
| [TRADING_SYSTEM_AUDIT.md](TRADING_SYSTEM_AUDIT.md) | Execution safety and financial risk | 3C + 6H + 12M + 13L | 2026-03-19 |
| [AGENT_LOGIC_AUDIT.md](AGENT_LOGIC_AUDIT.md) | LLM decision pipeline correctness | 5C + 6H + 9M + 6L | 2026-03-20 |
| [FORMAL_VERIFICATION_AUDIT.md](FORMAL_VERIFICATION_AUDIT.md) | State machines, concurrency, invariants | 3C + 7W + 8I | 2026-03-21 |

## Remediation Summary

| Severity | Total | Fixed | Pending | Accepted |
|----------|-------|-------|---------|----------|
| Critical | 13 | 11 | 1 | 1 |
| High | 12 | 12 | 0 | 0 |
| Important | 5 | 2 | 2 | 1 |
| Medium | 21 | 4 | 17 | 0 |
| Warning | 7 | 4 | 3 | 0 |
| Low | 19 | 0 | 19 | 0 |
| Info | 8 | 0 | 0 | 8 |

**All Critical and High findings are resolved.** Remaining Medium/Low items are tracked but non-blocking for POC operation.

## Critical Findings

| Doc ID | ID | Title | Status | Document |
|--------|----|-------|--------|----------|
| AR-C1 | C1 | Dashboard has no authentication | Fixed (US-7.1) | AUDIT_REPORT |
| AR-C2 | C2 | No US holiday calendar | Fixed | AUDIT_REPORT |
| TSA-C-1 | C-1 | Tenacity retries duplicate real orders | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-C-2 | C-2 | Order placed before DB record exists | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-C-3 | C-3 | liquidate_all assumes filled | Fixed | TRADING_SYSTEM_AUDIT |
| ALA-C-1 | C-1 | MODIFY verdicts silently ignored | Fixed | AGENT_LOGIC_AUDIT |
| ALA-C-2 | C-2 | CAUTION consensus ineffective | Fixed | AGENT_LOGIC_AUDIT |
| ALA-C-3 | C-3 | No conviction score validation | Fixed | AGENT_LOGIC_AUDIT |
| ALA-C-4 | C-4 | Gemini score extraction unbounded | Fixed | AGENT_LOGIC_AUDIT |
| ALA-C-5 | C-5 | Orphaned submitting orders unsynced | Fixed | AGENT_LOGIC_AUDIT |
| FVA-1.1 | 1.1 | Concurrent cycle execution possible | Fixed | FORMAL_VERIFICATION |
| FVA-1.2 | 1.2 | Strategy decisions not deduplicated | Fixed | FORMAL_VERIFICATION |
| FVA-6.3 | 6.3 | Stop-loss placement not atomic with BUY | Fixed | FORMAL_VERIFICATION |

## High Findings

| Doc ID | ID | Title | Status | Document |
|--------|----|-------|--------|----------|
| TSA-H-1 | H-1 | Cancel-then-replace stop not atomic | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-H-2 | H-2 | Portfolio data stale throughout cycle | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-H-3 | H-3 | Correlation check disabled | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-H-4 | H-4 | Daily loss halt disabled | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-H-5 | H-5 | GPT-4o defaults AGREE on parse failure | Fixed | TRADING_SYSTEM_AUDIT |
| TSA-H-6 | H-6 | Session leaks in orchestrator | Fixed | TRADING_SYSTEM_AUDIT |
| ALA-H-1 | H-1 | Risk SELL/REDUCE skip critical checks | Fixed | AGENT_LOGIC_AUDIT |
| ALA-H-2 | H-2 | entry_type undefined in schema | Fixed | AGENT_LOGIC_AUDIT |
| ALA-H-3 | H-3 | Strategy tool-use timeout too short | Fixed | AGENT_LOGIC_AUDIT |
| ALA-H-4 | H-4 | Consensus not recorded on moderation log | Fixed | AGENT_LOGIC_AUDIT |
| ALA-H-5 | H-5 | Repaired JSON produces partial decisions | Fixed | AGENT_LOGIC_AUDIT |
| ALA-H-6 | H-6 | No dedup of strategy decisions by ticker | Fixed | AGENT_LOGIC_AUDIT |
