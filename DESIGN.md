---
name: CheckMyData.ai
description: Dark-first AI database agent — semantic tokens, DM Sans UI, blue accent
colors:
  surface-0: "#09090b"
  surface-1: "#18181b"
  surface-2: "#27272a"
  surface-3: "#3f3f46"
  border-subtle: "#27272a"
  border-default: "#3f3f46"
  text-primary: "#fafafa"
  text-secondary: "#a1a1aa"
  text-tertiary: "#84848e"
  text-muted: "#52525b"
  accent: "#3b82f6"
  accent-hover: "#60a5fa"
  accent-strong: "#1d4ed8"
  accent-muted: "#3b82f620"
  success: "#34d399"
  warning: "#fbbf24"
  error: "#f87171"
  info: "#60a5fa"
typography:
  display:
    fontFamily: "Space Grotesk, DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2rem, 5vw, 4rem)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  body:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "10px 16px"
  input-default:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "10px 14px"
  card-panel:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.xl}"
    padding: "20px 24px"
---

## Overview

CheckMyData.ai uses a **dark-only product theme** with layered zinc surfaces and a single blue accent. Semantic tokens live in `frontend/src/app/globals.css` (`@theme`) and must be used via Tailwind semantic classes (`bg-surface-*`, `text-text-*`, `border-border-*`, `text-accent`), never raw palette utilities like `bg-zinc-900`.

Two registers share one codebase:

- **Product (`/app`, settings, chat, dashboards):** DM Sans, restrained motion, density-friendly layouts, pipeline/status semantics.
- **Brand (marketing routes, `(marketing)/`):** Space Grotesk display headlines, optional cinematic scroll motion (`cmd-*` keyframes), GSAP/Lenis on landing only.

Canonical human doc: `DESIGN_SYSTEM.md`. This file is the machine-readable companion for Impeccable and other DESIGN.md-aware tools.

## Colors

**Strategy:** Restrained dark neutrals + one accent ≤10% of product chrome.

| Role | Token | Hex | Usage |
|------|-------|-----|-------|
| Page bg | `surface-0` | `#09090b` | Root shell, page background |
| Panel | `surface-1` | `#18181b` | Sidebar, cards, inputs |
| Hover | `surface-2` | `#27272a` | Hover on surface-1, nested panels |
| Elevated | `surface-3` | `#3f3f46` | Tooltips, scrollbar thumbs |
| Primary text | `text-primary` | `#fafafa` | Headings, body |
| Secondary | `text-secondary` | `#a1a1aa` | Labels, descriptions |
| Tertiary | `text-tertiary` | `#84848e` | Captions, timestamps |
| Placeholder | `text-muted` | `#52525b` | Disabled, placeholders (verify 4.5:1 on surface-1) |
| Accent | `accent` | `#3b82f6` | Primary actions, links, focus rings |
| Success / warning / error / info | `success`, `warning`, `error`, `info` | see tokens | Status dots, toasts, pipeline stages |

Borders: `border-subtle` on default dividers; `border-default` on modals and tooltips. Status backgrounds use `*-muted` tokens at ~12% opacity.

## Typography

| Context | Font | Scale |
|---------|------|-------|
| Product UI | DM Sans (`font-sans`) | Page title `text-2xl font-bold tracking-tight`; section `text-lg font-semibold`; body `text-sm`; caption `text-xs` |
| Code / SQL / data | JetBrains Mono (`font-mono`) | SQL blocks, tables, monospaced values |
| Marketing headlines only | Space Grotesk (`font-display`) | Never inside `/app` product chrome |

Use `text-wrap: balance` on marketing h1–h3; cap display clamp max at 6rem on landing heroes. Body prose max ~65–75ch where long-form text appears.

## Elevation

Flat product aesthetic: **no card shadows** on sidebar or default panels. Elevation comes from surface stepping (`surface-0` → `surface-1` → `surface-2`) plus borders.

| Level | Treatment |
|-------|-----------|
| Base | `surface-0` page, `surface-1` panels |
| Floating | `shadow-lg` toasts/dropdowns; `shadow-xl` modals |
| Active pipeline stage | Soft accent glow (`stage-active-glow` keyframe), not glass blur |

## Components

Shared primitives in `frontend/src/components/ui/`:

- **Icon** — custom SVG paths only (`Icon.tsx`); sizes 10–28px by context.
- **ActionButton** — variants: primary (accent), ghost, danger; focus-visible ring on accent.
- **Inputs** — `bg-surface-1`, `border-border-subtle`, focus ring accent (not global outline).
- **Modals** — `role="dialog"`, focus trap, Escape to close, `rounded-xl`, `shadow-xl`.
- **Toasts** — semantic muted backgrounds, `role="alert"`.
- **Pipeline UI** — stage rows use `pipeline-stage-enter` (200ms ease-out-quart); failures get one shake; active stage glow.

Touch: `@media (pointer: coarse)` enforces 44×44px targets globally; `.compact-touch` allows 36×36px in dense sidebars.

## Do's and Don'ts

**Do**

- Use semantic tokens from `@theme` for all new UI.
- Show connection health, indexing, and sync state with semantic colors plus text labels.
- Respect `prefers-reduced-motion` and `<MotionConfig reducedMotion="user">` in product routes.
- Keep marketing motion isolated to `(marketing)/` routes.

**Don't**

- Use raw Tailwind palette classes (`text-zinc-400`, `bg-blue-500`) in product code.
- Use Space Grotesk in `/app` settings, chat, or sidebar.
- Add gradient text, glass cards, side-stripe callouts, or hero-metric blocks to product UI.
- Nest cards inside cards.
- Hide SQL, reasoning, or pipeline progress behind decorative loading theatrics.
