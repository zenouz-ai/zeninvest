---
tags: [open-source, launch, zeninvest, community, ci, legal, us-8.1]
status: planned
created: 2026-03-21
last_updated: 2026-03-21
---

# US-8.1 Open-Source Launch Preparation

> **Status:** Planned | **Priority:** P0 (prerequisite for repo going public) | **Effort:** Medium (2–3 days)
> Sprint delivery: Day 8 — see `docs/SPRINT_WEEK_1.md`.
> Roadmap entry: `docs/SOPHISTICATION_ROADMAP.md` § US-8.1 (Open-Source / Community).
> Related Week 1 handoff: `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md` captures the planned canonical community/operator entrypoint at `https://zeninvest.zenouz.ai`.

## Purpose

This document is the detailed specification for **US-8.1**, which covers the full set of repository hygiene, legal, community, and CI infrastructure tasks required before the ZenInvest repo is flipped from Private → Public on GitHub.

---

## Purpose

ZenInvest (formerly Investment Agent) is being open-sourced by Zenouz.ai under an MIT license. Before the repo goes public, it must have:

- A clean single-root repository structure (no nested duplicate)
- A clean git remote pointing exclusively to `github.com/zenouz-ai/zeninvest`
- Legal clarity: MIT LICENSE
- Community infrastructure: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY
- Developer UX: GitHub issue + PR templates
- Automated quality gate: GitHub Actions CI (pytest + mypy on every push/PR)

Without these, an open-source launch creates friction for early contributors, legal ambiguity, and no automated quality protection for incoming PRs.

The Week 1 sprint also tracks a related documentation-only handoff for `US-7.7 Dashboard HTTPS Domain & Canonical Access`. That work is not part of the US-8.1 implementation scope, but it supports the same community-facing launch posture by defining the intended canonical dashboard domain and production access model.

---

## Background

**Launch timeline:** The repo was pushed to `github.com/zenouz-ai/zeninvest` (Private) on 2026-03-19. The 12-week plan targets a public launch in Week 10. This story covers the Week 1–2 technical prep tasks from the ZenInvest Launch Handoff note.

**Strategy context:** The Zenouz.ai open-source playbook (following the OpenClaw pattern) requires MIT license, easy setup, and genuine utility for viral adoption. CONTRIBUTING.md and CI are table-stakes for open-source credibility — missing them increases early contributor drop-off significantly.

**Repo history:**
- Original remote: `github.com/KayvanNejabati/Investment-agent` (renamed `old-origin`)
- Current remote: `github.com/zenouz-ai/zeninvest` (origin)
- VPS (37.27.42.91): still running from old clone — unaffected until explicit migration

---

## Phase A — Repo Hygiene

### A1. Remove nested `Investment-agent/` subdirectory

A full duplicate of the project root exists at `./Investment-agent/` inside the repo. This creates confusion for contributors and CI tools.

**Verification first:**
```bash
ls Investment-agent/
# If this lists project files (src/, config/, etc.) — it's the duplicate. Safe to remove.
```

**Steps:**
```bash
git rm -r Investment-agent/
git commit -m "Remove nested Investment-agent/ duplicate subdirectory"
```

**Verification after:**
```bash
ls -la | grep -i investment  # should return nothing
poetry run pytest -v          # all tests must still pass
```

### A2. Clean git remotes

Remove the `old-origin` remote pointing to `github.com/KayvanNejabati/Investment-agent.git`. Confirm `origin` points to the new org.

**Verification first:**
```bash
git remote -v
# Expected: old-origin → ...KayvanNejabati/Investment-agent... (to be removed)
#           origin    → ...zenouz-ai/zeninvest...
```

**Steps:**
```bash
git remote remove old-origin
git remote -v  # confirm only origin remains
```

**Note:** This is a local+VPS operation. The remote itself (KayvanNejabati/Investment-agent) still exists on GitHub — this only removes the local reference.

---

## Phase B — Legal & Community Files

### B1. MIT LICENSE

Create `LICENSE` at the project root.

```
MIT License

Copyright (c) 2026 Zenouz.ai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### B2. CONTRIBUTING.md

Covers everything a first-time contributor needs to open a PR confidently.

**Required sections:**
1. **Prerequisites** — Python 3.11+, Poetry, Docker (optional)
2. **Installation** — `git clone`, `poetry install`, `cp config/.env.example .env`, `poetry run alembic upgrade head`
3. **Running tests** — `poetry run pytest -v` (no API keys needed; uses in-memory SQLite automatically)
4. **Type checking** — `poetry run mypy src/`
5. **Code style** — black + isort; `poetry run black src/ tests/` + `poetry run isort src/ tests/`
6. **Import rule** — always absolute (`from src.agents.strategy.engine import ...`); never relative
7. **Test pattern** — in-memory SQLite via `INVESTMENT_AGENT_USE_INMEMORY_DB=1`; stub heavy deps (yfinance, httpx) with `sys.modules` mocks; never write to `data/investment_agent.db`
8. **Adding features** — Alembic migration for schema changes; disable switch required; fall back to current behaviour
9. **Documentation** — all changes must update affected docs in the same PR (list from CLAUDE.md maintenance table)
10. **PR process** — fork → branch from `main` → open PR → CI must pass → one approval → squash merge
11. **Architecture overview** — brief pointer to CLAUDE.md and docs/ARCHITECTURE.md

### B3. CODE_OF_CONDUCT.md

Use the **Contributor Covenant v2.1** verbatim. Set enforcement contact to `zenouz.ai@gmail.com`.

Source: https://www.contributor-covenant.org/version/2/1/code_of_conduct/

### B4. SECURITY.md

Responsible disclosure policy.

**Required sections:**
1. **Supported versions** — latest `main` branch only
2. **What to report** — API key exposure, authentication bypass, SQL injection, remote code execution, dependency with known CVE being actively exploited
3. **What NOT to report** — theoretical issues without a realistic attack vector, issues requiring physical access, issues in dependencies not yet affecting this project
4. **How to report** — email `zenouz.ai@gmail.com` with subject `[SECURITY] <short description>`; do NOT open a public GitHub issue
5. **What to include** — description, reproduction steps, potential impact, suggested fix (if known)
6. **Response SLA** — acknowledge within 48 hours; initial assessment within 7 days; fix timeline communicated within 14 days
7. **Disclosure policy** — coordinated disclosure; reporter credited in release notes unless they prefer anonymity; no legal action against good-faith reporters

---

## Phase C — GitHub Infrastructure

### C1. GitHub issue templates

**`.github/ISSUE_TEMPLATE/bug_report.md`**

```yaml
---
name: Bug report
about: Something isn't working as expected
title: '[BUG] '
labels: bug
assignees: ''
---

**Describe the bug**
A clear description of what the bug is.

**To reproduce**
Steps to reproduce the behaviour.

**Expected behaviour**
What you expected to happen.

**Actual behaviour**
What actually happened.

**Environment**
- OS:
- Python version:
- Poetry version:
- Relevant config (trading.mode, cycle_frequency, etc.):

**Logs**
Paste relevant log output here (remove any API keys before posting).

**Additional context**
Any other context, screenshots, or information.
```

**`.github/ISSUE_TEMPLATE/feature_request.md`**

```yaml
---
name: Feature request
about: Suggest a new feature or improvement
title: '[FEATURE] '
labels: enhancement
assignees: ''
---

**Problem / motivation**
What problem does this solve? Why is it needed?

**Proposed solution**
Describe the feature you'd like.

**Alternatives considered**
Any alternative approaches you've thought about.

**Is this in the roadmap?**
Check `docs/SOPHISTICATION_ROADMAP.md` — is this already planned?

**Additional context**
Any other context, mockups, or references.
```

### C2. Pull request template

**`.github/PULL_REQUEST_TEMPLATE.md`**

```markdown
## Summary
<!-- What does this PR do? Why? -->

## Changes
<!-- List the key changes made -->

## Checklist
- [ ] All existing tests pass (`poetry run pytest -v`)
- [ ] New functionality is covered by tests
- [ ] Type annotations are correct (`poetry run mypy src/`)
- [ ] Affected docs updated (README.md, CLAUDE.md, docs/ — see CLAUDE.md maintenance table)
- [ ] No API keys, secrets, or `.env` contents included
- [ ] New features have a disable switch and fall back to current behaviour
- [ ] Alembic migration added if schema changed (`poetry run alembic revision --autogenerate -m "..."`)

## Test plan
<!-- How did you verify this works? -->

## Related issues
<!-- Closes #... -->
```

### C3. GitHub Actions CI workflow

**`.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Poetry
        uses: snok/install-poetry@v1
        with:
          version: latest
          virtualenvs-create: true
          virtualenvs-in-project: true

      - name: Cache Poetry venv
        uses: actions/cache@v4
        with:
          path: .venv
          key: ${{ runner.os }}-poetry-${{ hashFiles('**/poetry.lock') }}
          restore-keys: |
            ${{ runner.os }}-poetry-

      - name: Install dependencies
        run: poetry install --no-interaction

      - name: Run tests
        run: poetry run pytest -v
        env:
          INVESTMENT_AGENT_USE_INMEMORY_DB: "1"

      - name: Type check
        run: poetry run mypy src/
```

**Design notes:**
- Uses `INVESTMENT_AGENT_USE_INMEMORY_DB=1` so no external DB or API keys are needed in CI
- Poetry venv cached by `poetry.lock` hash for fast subsequent runs
- Runs on every push to `main` and every PR targeting `main`
- mypy step runs after pytest to ensure type coverage doesn't regress

---

## Acceptance Checklist

Operator verification — run after each phase:

```bash
# Phase A
ls -la | grep -i investment     # should be empty
git remote -v                   # only: origin → https://github.com/zenouz-ai/zeninvest.git
poetry run pytest -v            # all tests pass

# Phase B
ls LICENSE CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md   # all present

# Phase C
ls .github/ISSUE_TEMPLATE/bug_report.md
ls .github/ISSUE_TEMPLATE/feature_request.md
ls .github/PULL_REQUEST_TEMPLATE.md
ls .github/workflows/ci.yml
# Then push a test commit to main or open a draft PR to verify CI triggers
```

---

## VPS Migration Note

The VPS (37.27.42.91) continues running from the old `KayvanNejabati/Investment-agent` clone throughout this phase — no disruption. Once this story is complete and the repo structure is clean, migrate using a **fresh clone** (not `git pull`) because the nested directory removal changes the folder layout:

```bash
# On VPS — do this after US-8.1 is complete and pushed
git clone https://github.com/zenouz-ai/zeninvest.git zeninvest-new
cp ../investment-agent/.env zeninvest-new/
cp ../investment-agent/data/investment_agent.db zeninvest-new/data/
cd ../investment-agent && docker compose down
cd ../zeninvest-new && docker compose up -d --build
```

See handoff note (2026-03-19) for full VPS migration steps.

---

## Related Docs

- [SOPHISTICATION_ROADMAP.md](SOPHISTICATION_ROADMAP.md) — full feature backlog
- [ARCHITECTURE.md](ARCHITECTURE.md) — pipeline and component overview
- [DEPLOYMENT.md](DEPLOYMENT.md) — VPS deployment guide
- [DASHBOARD_DEPLOYMENT.md](DASHBOARD_DEPLOYMENT.md) — dashboard VPS deployment
- [CLAUDE.md](../CLAUDE.md) — AI context file; documentation maintenance table
