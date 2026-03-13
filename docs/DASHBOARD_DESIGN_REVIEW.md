# Dashboard Design Review & Improvement Plan

> Review date: 2026-03-13. Assessment against industry best practices for financial/trading dashboards.

## Executive Summary

The dashboard has a solid foundation: consistent dark terminal aesthetic, clear information architecture, and good data depth. Several gaps affect usability (especially mobile), clarity (navigation state), and polish. This plan prioritises changes by impact.

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

#### 1. **Navigation: No active state**

**Problem:** All nav links look identical. Users cannot tell which page they are on.

**Fix:** Use `NavLink` (or `useLocation`) to apply `border-accent` and `text-accent` for the current route.

```tsx
// App.tsx: replace Link with NavLink, add active class
<NavLink to="/" className={({ isActive }) => 
  `inline-flex ... ${isActive ? 'border-accent text-accent' : 'border-transparent'}`
}>
```

---

#### 2. **Mobile: Nav links hidden**

**Problem:** `hidden sm:flex` hides all 7 nav items on viewports &lt; 640px. Mobile users see only the logo and have no way to navigate.

**Fix:**
- Add a hamburger menu that toggles a dropdown/drawer with nav links on small screens.
- Alternatively, show a scrollable horizontal nav (`flex overflow-x-auto`) that doesn’t wrap, so all links remain visible.

---

### P1 — High (UX & Polish)

#### 3. **Loading states**

**Problem:** Generic "Loading..." text; no indication of progress or structure.

**Fix:**
- Add a shared `LoadingSpinner` or `Skeleton` component.
- Use skeleton placeholders for cards/tables so layout doesn’t jump.
- Consider a subtle spinner in the nav or page header during fetches.

---

#### 4. **Empty states**

**Problem:** Empty states vary ("No runs found", "No cost data.", "No orders yet."). Some are plain text; none suggest next actions.

**Fix:**
- Centralise empty-state styling (icon + message + optional CTA).
- Add brief guidance where useful (e.g. "Run a cycle to see activity", "Check back after the next run").

---

#### 5. **Focus & keyboard accessibility**

**Problem:** Some interactive elements lack visible focus styles; keyboard navigation may be unclear.

**Fix:**
- Use consistent `focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg` (or equivalent) for buttons, inputs, links.
- Ensure tables and expandable rows can be operated via keyboard (Enter/Space to expand).

---

#### 6. **Error handling**

**Problem:** API errors often log to console only; no user-facing error state or retry.

**Fix:**
- Add error boundaries or per-page error state when fetches fail.
- Show a simple message + "Retry" button.
- Optional: global toast/notification for transient errors.

---

### P2 — Medium (Aesthetics & Consistency)

#### 7. **Button consistency**

**Problem:** Mixed styles: inline Tailwind vs `.btn-primary`/`.btn-secondary`. Dry Run / Live Run use custom classes; Run History uses `.btn-secondary`.

**Fix:**
- Define and use shared button variants (e.g. `btn-primary`, `btn-secondary`, `btn-danger`) in `index.css`.
- Apply them consistently across all pages.

---

#### 8. **Table header styling**

**Problem:** Table headers are somewhat flat; sortable headers could be clearer.

**Fix:**
- Use `sticky top-0` and stronger background (`bg-terminal-surface`) for thead.
- Make sort indicators more prominent.
- Optional: add row hover highlight across all tables.

---

#### 9. **Chart tooltips & legends**

**Problem:** Recharts tooltips are customised on Costs; Portfolio/Run History charts use defaults. Legend placement and styling differ.

**Fix:**
- Standardise chart tooltip styling (dark theme, border, typography).
- Use shared legend styling.
- Ensure charts have sufficient contrast for accessibility.

---

#### 10. **Card shadow & depth**

**Problem:** All cards look flat; no visual hierarchy beyond borders.

**Fix:**
- Add subtle shadow: `shadow-sm` or `box-shadow: 0 1px 3px rgba(0,0,0,0.2)` for cards.
- Optional: stronger shadow on hover for interactive cards.

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

## Implementation Order

| Phase | Items | Effort |
|-------|-------|--------|
| **Phase 1** | P0 #1 (active nav), P0 #2 (mobile nav) | 1–2 hrs |
| **Phase 2** | P1 #3 (loading), #4 (empty states), #5 (focus) | 2–3 hrs |
| **Phase 3** | P1 #6 (errors), P2 #7–9 (buttons, tables, charts) | 2–3 hrs |
| **Phase 4** | P2 #10 (depth), P3 items as needed | 1–2 hrs |

---

## Files to Modify

| Change | Files |
|--------|-------|
| Active nav | `App.tsx` |
| Mobile nav | `App.tsx`, possibly `index.css` |
| Loading/empty | New `components/LoadingSpinner.tsx`, `components/EmptyState.tsx`; each page |
| Focus styles | `index.css`, form/button components |
| Error handling | `api/client.ts`, each page’s `useEffect` |
| Buttons | `index.css`, `Dashboard.tsx`, `RunHistory.tsx`, etc. |
| Tables | `Universe.tsx`, `Portfolio.tsx`, `OrderManagement.tsx`, `Opportunity.tsx`, `Costs.tsx` |
| Charts | `Portfolio.tsx`, `Costs.tsx` |

---

## Design Tokens (Reference)

Current Tailwind theme:

```
terminal-bg:    #0d1117
terminal-surface: #161b22
terminal-border:  #30363d
terminal-text:   #e6edf3
terminal-text-dim: #8b949e
gain:    #00ff88
loss:    #ff4444
neutral: #58a6ff
accent:  #d4a017
warning: #ffaa00
```

Keep these; they align with the terminal aesthetic. Consider adding a `focus-ring` token for consistency.

---

## Conclusion

The dashboard is functional and visually coherent. The highest-impact improvements are:

1. **Active navigation state** — so users know where they are.
2. **Mobile navigation** — so small-screen users can access all pages.
3. **Loading and empty states** — for better perceived performance and guidance.
4. **Error handling** — so failures are visible and recoverable.

Implementing Phase 1 and 2 will materially improve usability with modest effort.
