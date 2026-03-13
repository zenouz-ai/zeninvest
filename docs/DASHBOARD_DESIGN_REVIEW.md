---
tags: [dashboard, frontend, ux, design]
status: current
last_updated: 2026-03-13
---

# Dashboard Design Review & Improvement Plan

> UX audit and implementation log. Review date: 2026-03-13. Phase 1–4 improvements implemented.

## Executive Summary

The dashboard has a solid foundation: consistent dark terminal aesthetic, clear information architecture, and good data depth. **Phase 1–3 improvements have been implemented:** active nav state, mobile hamburger menu, loading spinner, error handling with retry, button consistency, table sticky headers, card shadow, and focus styles.

---

## Current Strengths

| Area | Status |
|------|--------|
| **Color system** | Coherent palette (gain/loss/neutral/accent), appropriate for finance |
| **Typography** | Inter + JetBrains Mono, good hierarchy for data |
| **Card layout** | Consistent `.card` component, clear sections |
| **Data density** | Appropriate for power users, not overwhelming |
| **Real-time** | SSE feed, 30s polling where needed |
| **Transparency** | Full LLM outputs, committee reasoning, audit trail |
| **Page descriptions** | Each page has a brief "what & how" intro |

---

## Gaps & Recommended Changes

### P0 — Critical (Usability Blockers)

#### 1. **Navigation: No active state** ✅

**Fix applied:** `NavLink` with `isActive` → `border-accent text-accent` for current route. Desktop and mobile nav both show active state.

---

#### 2. **Mobile: Nav links hidden** ✅

**Fix applied:** Hamburger menu on `sm:hidden` viewports toggles a dropdown with all 7 nav links. Clicking a link navigates and closes the menu.

---

### P1 — High (UX & Polish)

#### 3. **Loading states** ✅

**Fix applied:** Shared `LoadingSpinner` component (animated border spinner). Used on all 8 pages. Skeleton placeholders deferred.
---

#### 4. **Empty states** — Deferred

`EmptyState` component created but not yet wired into all pages. Current plain-text empty messages retained.

---

#### 5. **Focus & keyboard accessibility** ✅

**Fix applied:** Base focus styles for `input` and `select`. Button variants (`.btn-primary`, `.btn-secondary`, `.btn-danger`) include `focus:ring-2 focus:ring-neutral`. Nav links and hamburger have focus ring.

---

#### 6. **Error handling** ✅

**Fix applied:** Per-page error state when fetches fail. Error message + "Retry" button on Dashboard, Portfolio, Run History, Costs, Order Management, Opportunity, Universe.

---

### P2 — Medium (Aesthetics & Consistency)

#### 7. **Button consistency** ✅

**Fix applied:** `btn-primary`, `btn-secondary`, `btn-danger`, `btn-danger-solid` in `index.css`. Dashboard Dry Run/Live Run, modal buttons, Run History Details use these classes.

---

#### 8. **Table header styling** ✅

**Fix applied:** `sticky top-0 bg-terminal-surface z-10` on thead for Universe, Opportunity, Order Management tables. Sort indicators unchanged (Universe already had them).

---

#### 9. **Chart tooltips & legends** — Deferred

Costs page has custom tooltip. Portfolio uses Recharts defaults. Standardisation deferred.

---

#### 10. **Card shadow & depth** ✅

**Fix applied:** `.card` now includes `box-shadow: 0 1px 3px rgba(0,0,0,0.2)`.

---

### P3 — Nice to Have

#### 11. **Breadcrumbs**

For deep pages or after navigation, breadcrumbs could help orientation. Low priority for 7 top-level pages.

---

#### 12. **"Last updated" timestamps**

Some pages show "Last Updated"; others don’t. Consider a consistent pattern (e.g. footer or header) for data freshness.

---

#### 13. **Reduced motion**

Add `prefers-reduced-motion: reduce` support for users who need it (e.g. disable animations, simplify transitions).

---

## Implementation Status

| Phase | Items | Status |
|-------|-------|--------|
| **Phase 1** | P0 #1 (active nav), P0 #2 (mobile nav) | Done |
| **Phase 2** | P1 #3 (loading), #4 (empty states), #5 (focus) | Loading, focus done; empty states deferred |
| **Phase 3** | P1 #6 (errors), P2 #7–9 (buttons, tables, charts) | Errors, buttons, tables done; charts deferred |
| **Phase 4** | P2 #10 (depth), P3 items | Card depth done |

---

## Files Modified

| Change | Files |
|--------|-------|
| Active nav, mobile nav | `App.tsx` |
| Loading spinner | New `components/LoadingSpinner.tsx` |
| Empty state (stub) | New `components/EmptyState.tsx` |
| Focus, buttons, card | `index.css` |
| Error + retry | All 8 pages |
| Sticky table headers | `Universe.tsx`, `Opportunity.tsx`, `OrderManagement.tsx` |
| Page 8: Roadmap | New `Roadmap.tsx` — project timeline, topic filter, architecture diagram |

---

## Design Tokens

See [DASHBOARD.md § Design Tokens](DASHBOARD.md#design-tokens) for the full colour palette, typography, and visual style. Focus rings added per this review.

---

## Conclusion

Phase 1–4 improvements are implemented. Remaining optional items: Empty states wiring, chart tooltip standardisation, breadcrumbs, last-updated timestamps, reduced motion. The dashboard now has active nav state, mobile hamburger menu, loading spinners, error handling with retry, consistent buttons, sticky table headers, and card depth.

---

## Related Notes

- [Dashboard](DASHBOARD.md) — architecture, API, pages, design tokens
- [Dashboard Deployment](DASHBOARD_DEPLOYMENT.md) — Docker, VPS
