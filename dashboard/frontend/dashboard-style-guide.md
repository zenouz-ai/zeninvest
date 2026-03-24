# ZenInvest Dashboard Style Guide

Use this document to style the ZenInvest React dashboard so it feels like part of `ZENOUZ.ai`.

Brand hierarchy for the product shell:

- company: `ZENOUZ.ai`
- product: `ZenInvest`
- authenticated dashboard home: `ZenInvest Agent`

The goal is not to clone the landing page section-for-section. The goal is to translate the website's visual language into a product UI:

- dark, premium, editorial
- research-led, technical, high-signal
- vivid cyan/violet/emerald accents on restrained surfaces
- clear hierarchy, generous spacing, rounded panels, subtle glow

## Core Intent

The dashboard should feel like:

- a serious decision system
- a premium control room
- a founder-led AI product with strong research taste

It should not feel like:

- a generic SaaS admin template
- a white-label enterprise console
- a crypto casino
- a fintech hype UI overloaded with gradients everywhere

## Brand Tokens

Use these values as the base theme.

```css
:root {
  --color-bg: #06060a;
  --color-surface: rgba(13, 14, 24, 0.88);
  --color-surface-strong: rgba(17, 19, 31, 0.94);
  --color-surface-soft: rgba(255, 255, 255, 0.04);
  --color-text: #f1f3fb;
  --color-text-muted: #adb3cb;
  --color-text-dim: #7c8299;
  --color-border: rgba(255, 255, 255, 0.08);
  --color-border-strong: rgba(255, 255, 255, 0.16);

  --color-violet: #6332ff;
  --color-cyan: #00d4ff;
  --color-emerald: #00ffa3;

  --color-violet-soft: rgba(99, 50, 255, 0.16);
  --color-cyan-soft: rgba(0, 212, 255, 0.16);
  --color-emerald-soft: rgba(0, 255, 163, 0.16);

  --gradient-brand: linear-gradient(135deg, #6332ff 0%, #00d4ff 48%, #00ffa3 100%);
  --gradient-panel: linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));

  --shadow-panel: 0 30px 80px rgba(0, 0, 0, 0.28);
  --shadow-glow: 0 16px 48px rgba(0, 212, 255, 0.18);
  --shadow-glow-strong: 0 8px 32px rgba(0, 212, 255, 0.28), 0 0 64px rgba(99, 50, 255, 0.12);
  --shadow-card-hover: 0 24px 64px rgba(0, 0, 0, 0.32), 0 8px 24px rgba(0, 212, 255, 0.08);

  --font-body: "Outfit", sans-serif;
  --font-heading: "Syne", sans-serif;
  --font-mono: "JetBrains Mono", monospace;

  --radius-xs: 0.75rem;
  --radius-sm: 1rem;
  --radius-md: 1.5rem;
  --radius-lg: 2rem;

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-7: 3rem;
  --space-8: 4rem;

  --transition-fast: 180ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-base: 280ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

## Typography

- Use `Outfit` for most UI copy, labels, data rows, and controls.
- Use `Syne` for major dashboard headings, section titles, hero metrics, and large callouts.
- Use `JetBrains Mono` for timestamps, tickers, IDs, system state, status labels, and numeric microcopy.

Rules:

- Main page titles should feel editorial, not corporate.
- Small labels should be uppercase mono with generous tracking.
- Muted text should stay legible; avoid low-contrast gray-on-dark mush.
- Numbers should be bold and high-contrast.

Recommended scale:

- Page title: `clamp(2rem, 4vw, 3.5rem)` in `Syne`
- Section title: `1.35rem` to `1.75rem` in `Syne`
- Card title: `1.1rem` to `1.35rem`
- Body copy: `0.98rem` to `1.05rem`
- Meta / eyebrow / label: `0.72rem` to `0.78rem` in mono uppercase

## Layout Translation for a Dashboard

Do not reuse the marketing page layout. Adapt the same language to a product shell.

Preferred app structure:

- fixed or sticky top bar with blur and subtle border
- optional left sidebar for navigation
- content area on a max-width canvas, not edge-to-edge chaos
- large top summary area with 2 to 4 hero metrics
- secondary grid of panels for signals, charts, positions, model outputs, and logs

Recommended shell:

- background stays `--color-bg`
- add a faint grid or soft atmospheric orbs in the page background
- keep content width around `1200px` to `1440px`
- use generous gutters: `24px` desktop, `16px` mobile

## Surface Language

Panels, cards, and modules should use the website’s glass-dark treatment:

```css
.dashboard-panel {
  border: 1px solid var(--color-border);
  background:
    radial-gradient(circle at top, rgba(255, 255, 255, 0.06), transparent 42%),
    rgba(14, 16, 28, 0.86);
  box-shadow: var(--shadow-panel);
  border-radius: 1.5rem;
}
```

Use stronger panels for hero modules and key decision areas:

- slightly larger radius
- more padding
- a restrained cyan/violet atmospheric glow in the background

Use softer surfaces for nested cards:

- `rgba(255,255,255,0.03)` background
- lighter border
- less shadow

## Dashboard Component Rules

### App Header

- sticky top bar
- blurred dark background
- subtle bottom border
- left: product mark + product name
- right: key actions, environment tag, user menu

### Sidebar

- dark but slightly lighter than the page background
- use mono or compact sans for section labels
- selected item can use a soft gradient pill or cyan border glow
- avoid giant icon-only navigation unless the product truly needs it

### KPI Cards

- large value in `Syne` or bold `Outfit`
- small mono label above
- muted supporting sentence below
- optional delta chip in emerald, cyan, or violet
- keep icons minimal

### Charts

- chart containers should match panel styling
- grid lines should be faint
- axes and legends in muted text
- primary series in cyan
- secondary series in violet
- positive or confirmed signal in emerald
- avoid rainbow color sets

### Tables

- dark table surface
- soft row separators
- sticky headers if useful
- header labels in mono uppercase
- numeric columns right-aligned
- hover state can slightly brighten the row background

### Status and Tags

Mirror the site’s pill treatment:

- rounded full pills
- thin border
- subtle tinted background
- mono uppercase

Suggested mappings:

- `featured` or `live`: cyan
- `active` or `healthy`: emerald
- `upcoming`, `draft`, or `experimental`: violet
- `risk`, `blocked`, or `alert`: use a restrained red only when truly needed

### Buttons

Primary button:

- gradient fill
- dark text
- soft glow shadow

Secondary button:

- transparent or very dark fill
- thin border
- brightens on hover

Do not make every button primary.

### Forms and Filters

- inputs should be dark rounded fields
- borders use `--color-border`
- focus state uses cyan outline or glow
- segmented controls and tabs should feel like refined product controls, not browser defaults

## Motion

Motion should be present but restrained.

Use:

- fade-in / slide-up reveals for panels
- subtle hover lift on cards
- fast focus/hover transitions
- smooth tab and route transitions if the app supports them

Avoid:

- bouncing widgets
- constant pulsing glows
- animated gradients on everything
- delayed UX for core interactions

Respect `prefers-reduced-motion`.

## Background and Atmosphere

The site background works because it is layered, not loud.

For the dashboard:

- keep a near-black base
- add 1 to 3 soft blurred orb accents
- optionally add a faint grid
- keep atmospheric effects behind content
- never reduce readability for mood

Good pattern:

```css
.dashboard-shell::before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(99, 50, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99, 50, 255, 0.05) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: radial-gradient(circle at center, rgba(0, 0, 0, 0.72), transparent 92%);
  pointer-events: none;
}
```

## React Implementation Guidance

Ask the AI agent to:

- implement a shared theme file first
- define tokens as CSS variables or a theme object
- create reusable primitives for:
  - `DashboardShell`
  - `Panel`
  - `MetricCard`
  - `StatusPill`
  - `SectionHeader`
  - `Tag`
  - `PrimaryButton`
  - `SecondaryButton`
- style the dashboard at the system level before polishing individual screens

If using CSS Modules, styled-components, Tailwind, or shadcn:

- keep the token names above
- preserve the typography roles
- preserve the dark surface language
- do not swap in a generic gray palette or default blue accent

## What to Avoid

- flat black panels with no depth
- generic template dashboards with square cards
- white cards on dark background
- default React table styling
- too many competing accent colors
- overuse of charts, badges, shadows, and gradients in one view
- loud “trading app” aesthetics

## Acceptance Criteria

The dashboard should look like it belongs to `zenouz.ai` if:

- the color system is immediately recognizable
- typography matches the site’s editorial hierarchy
- panels and cards share the same rounded dark-glass language
- buttons, pills, and labels feel consistent with the website
- the UI stays readable and disciplined under dense data
- it feels premium and research-led rather than generic SaaS

## Short Prompt for Another AI Agent

Use this if you want a compact handoff:

> Style this React dashboard so it matches the `zenouz.ai` website. Use a dark premium editorial aesthetic with `Outfit` body text, `Syne` headings, and `JetBrains Mono` for labels/status/meta. Use near-black backgrounds, dark glass panels, thin borders, large rounded corners, and restrained cyan/violet/emerald accents. Primary actions use the site gradient (`#6332ff -> #00d4ff -> #00ffa3`). Panels should feel like a serious AI decision system, not a generic SaaS admin template. Build shared theme tokens and reusable primitives first, then apply them across header, sidebar, KPI cards, tables, charts, forms, and status pills. Keep motion subtle, spacing generous, and hierarchy clear.
