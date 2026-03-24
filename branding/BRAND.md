# ZENOUZ.ai — Brand Guide

## Brand Architecture

- **Company:** `ZENOUZ.ai`
- **Product:** `ZenInvest`
- **Dashboard / operator experience:** `ZenInvest Agent`
- **Browser/app title format:** `ZENOUZ.ai - ZenInvest`

## Active Logo: Graph Theory Z

The Z letterform is constructed entirely from graph nodes and edges — no solid fills. The form emerges from a network structure, reflecting AI, mathematics, and connected intelligence.

### Structure
- **Top bar:** 4 nodes connected by edges (horizontal)
- **Diagonal:** 2 intermediate nodes connecting top-right to bottom-left
- **Bottom bar:** 4 nodes connected by edges (horizontal)
- **Cross-connections:** 4 faint diagonal edges linking non-adjacent nodes (graph theory adjacency)
- **Total:** 11 primary nodes, 10 primary edges, 4 secondary edges

### Logo Files
- `graph-theory-z.svg` — dark background version (cyan→emerald nodes)
- `graph-theory-z-light.svg` — light background version (deeper teal→green nodes)
- `zenouz-final.html` — full brand kit with all 5 shortlisted concepts for future use

---

## Colour Palette

### Primary Gradient (nodes & edges)
```
Cyan:    #00d4ff
Emerald: #00ffa3
```
CSS: `linear-gradient(135deg, #00d4ff, #00ffa3)`

### Accent (use sparingly)
```
Violet:  #6332ff
```

### Backgrounds
```
Dark primary:   #06060a
Dark card:      #0c0c14
Navy:           #0a1628
```

### Text
```
White (dark bg):  #ffffff
Dark (light bg):  #0a1628
```

### Light Background Variant
When on light backgrounds, use deeper versions:
```
Teal:    #00a8cc  (instead of #00d4ff)
Green:   #00cc88  (instead of #00ffa3)
Violet:  #5020cc  (instead of #6332ff)
```

---

## Typography

### Wordmark
- **Font:** Outfit
- **"ZENOUZ":** weight 600, letter-spacing 1px, white on dark / #0a1628 on light
- **".ai":** weight 400, filled with the cyan→emerald gradient

### UI / Dashboard
- **Hero headings / KPI callouts:** Syne (600–700)
- **Section headings / body UI:** Outfit (400–600)
- **Body:** Outfit (300–400)
- **Code / Monospace:** JetBrains Mono (400–500)
- **Data labels / Tags:** JetBrains Mono, 9–11px, uppercase, letter-spacing 2–4px

---

## Dashboard Design Tokens

Use these as CSS variables in the dashboard frontend:

```css
:root {
  /* Backgrounds */
  --bg-primary: #06060a;
  --bg-card: #0c0c14;
  --bg-elevated: #12121c;
  --border: rgba(255, 255, 255, 0.06);

  /* Brand */
  --cyan: #00d4ff;
  --emerald: #00ffa3;
  --violet: #6332ff;
  --navy: #0a1628;

  /* Semantic */
  --accent: #00d4ff;
  --positive: #00ffa3;
  --negative: #ff4466;
  --warning: #f7c948;
  --neutral: rgba(255, 255, 255, 0.4);

  /* Text */
  --text-primary: #ffffff;
  --text-secondary: rgba(255, 255, 255, 0.5);
  --text-muted: rgba(255, 255, 255, 0.25);

  /* Typography */
  --font-display: 'Outfit', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}
```

---

## Usage Guidelines

### Do
- Use the cyan→emerald gradient for active states, chart accents, progress indicators, and key metrics
- Use violet (#6332ff) as a secondary accent for hover states or to distinguish categories
- Keep the dark theme as default — it's the primary brand context
- Use the Graph Theory Z logomark as a favicon (simplified to 5 nodes at small sizes)
- Use JetBrains Mono for all data, numbers, timestamps, and code
- In product UI, show the company/product hierarchy as `ZENOUZ.ai` first and `ZenInvest` second

### Don't
- Don't place the logo on busy/patterned backgrounds without sufficient contrast
- Don't use the gradient on large background areas — keep it for accents and the logo
- Don't mix in other blues or greens that aren't in the palette
- Don't use the logo smaller than 24px (use simplified 5-node version below that)

### Scalability Rules
At smaller sizes, progressively reduce node count:
- **100px+:** Full 11 nodes + cross-connections
- **64px:** 7 nodes (3 per bar + 1 centre), no cross-connections
- **40px:** 5 nodes (2 per bar + 1 centre)
- **24px:** 5 nodes, thicker edges

---

## Alternative Concepts (in zenouz-final.html)

The following concepts are approved and available for future use:
1. **Circuit Z** — solid navy Z with glowing circuit nodes along diagonal
2. **Octagonal Z** — gradient Z inside octagonal frame with vertex nodes
3. **Graph Theory Z** ← ACTIVE
4. **Monogram Minimal** — three strokes, one dot, ultra-clean
5. **Graph Octagonal Z** — Graph Theory Z inside the octagonal frame (fusion)
