---
name: frontend-design-system
description: >
  Enforces the CheckMyData.ai design system on all frontend work. Ensures consistent use of semantic
  color tokens, typography scale, component patterns, spacing, animation catalog, and accessibility
  requirements as documented in DESIGN_SYSTEM.md. Use PROACTIVELY whenever creating, editing, styling,
  or reviewing frontend components, pages, layouts, or UI elements. Also use when the user mentions
  "design", "UI", "component", "style", "color", "button", "form", "input", "modal", "card", "layout",
  "CSS", "Tailwind", "frontend", "responsive", "dark mode", "theme", "token", "font", "typography",
  "icon", "animation", "toast", "tooltip", "sidebar", "mobile", "accessibility", "a11y", "ARIA",
  or any visual/styling discussion.
---

# Frontend Design System

Before creating or modifying any frontend code, read `DESIGN_SYSTEM.md` in the project root to load the full design context.

## When to Apply

- Creating a new component or page
- Modifying the appearance of an existing component
- Adding or changing colors, borders, backgrounds, or text styles
- Implementing interactive states (hover, focus, disabled, loading)
- Adding animations or transitions
- Building responsive layouts or mobile adaptations
- Reviewing UI code for consistency
- Adding or modifying icons

## Process

1. **Read** `DESIGN_SYSTEM.md` to load the current design tokens, component specs, and rules
2. **Identify** which design system elements the work touches (colors, typography, spacing, components, animations, accessibility)
3. **Apply** the correct patterns:
   - Use semantic color tokens from the `@theme` block — never raw Tailwind palette classes (no `zinc-*`, `blue-*`, etc. in component code)
   - Follow the documented type scale (Section 1.2)
   - Use the established component patterns (Section 2) for buttons, inputs, cards, modals, tooltips, toasts
   - Use animations only from the approved catalog (Section 3.2)
   - Include all required ARIA attributes (Section 4.4)
4. **Verify** the checklist below before finishing

## Rules

### Colors
- Always use semantic tokens: `bg-surface-*`, `text-text-*`, `border-border-*`, `bg-accent`, `text-error`, etc.
- Never introduce raw Tailwind palette classes (`bg-zinc-900`, `text-blue-500`, etc.) in component code.
- If no semantic token fits, propose adding one to `@theme` in `globals.css` and document it in `DESIGN_SYSTEM.md`.
- The only exception is toast status variants, which use `{hue}-900/90` patterns for semi-transparent backgrounds.

### Typography
- DM Sans (`font-sans`) for all UI text. JetBrains Mono (`font-mono`) only for code, SQL, and data values.
- Follow the type scale: `text-2xl` for page titles, `text-lg` for section headings, `text-sm` for body, `text-xs` for captions, `text-[10px]`/`text-[11px]` for micro text.
- Never use arbitrary font sizes outside the documented scale without updating the design system.

### Components
- Buttons: use the established variant patterns (primary, secondary, destructive, ghost, accent-ghost, inline-link). See Section 2.1.
- Inputs: use the canonical `inputCls` pattern from Section 2.2. Include `aria-label`, `aria-required`, `aria-invalid`.
- Cards: `bg-surface-1 rounded-xl border border-border-subtle`. No shadow on cards.
- Modals: overlay `bg-black/60`, panel `bg-surface-1 border border-border-default rounded-lg shadow-xl`. Must have focus trap, Escape-to-close, and proper ARIA.
- Icons: use the `Icon` component from `components/ui/Icon.tsx`. Add new paths to its `PATHS` record — do not import external icon packages.

### Animations
- Only use animations from the approved catalog in `globals.css` (Section 3.2 of design system).
- UI transitions: 0.15s–0.25s `ease-out`. Looping indicators: 1.5s+ `ease-in-out infinite`.
- Always use `transition-colors` or `transition-all duration-150` on interactive elements.

### Accessibility
- Every icon button: `aria-label` + `<Tooltip>` wrapper.
- Every form input: `aria-label`, `aria-required` where needed, `aria-invalid` on error.
- Modals: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trap, Escape to close.
- Status indicators: `role="img"` + `aria-label`, or `role="status"` + `aria-live="polite"`.
- Touch targets: minimum 44x44px (enforced by CSS, but be aware for custom elements).
- Never disable pinch-zoom or user scaling.

### Responsive
- Single breakpoint: `max-width: 767px`.
- Mobile: full-width layouts, hidden sidebar, bottom-anchored inputs.
- Use `.compact-touch` wrapper to allow 36px touch targets in dense areas.

## Migration Awareness

When editing a file listed in Section 5.2 of the design system (ConfirmModal, Spinner, ChatInput, etc.), migrate its raw Tailwind classes to semantic tokens. Consult the mapping table in Section 5.1.

## Alignment Checklist

- [ ] All colors use semantic tokens from `@theme` (no raw `zinc-*`, `blue-*`, `red-*`, etc.)
- [ ] Typography follows the documented scale (DM Sans for UI, JetBrains Mono for code)
- [ ] Spacing uses standard Tailwind scale values per the documented patterns
- [ ] Border radius matches component type (cards: `rounded-xl`, inputs: `rounded-lg`, etc.)
- [ ] Component patterns match design system specs (buttons, inputs, cards, modals, etc.)
- [ ] Animations use only approved keyframes from `globals.css`
- [ ] All interactive elements have `transition-colors` or `transition-all`
- [ ] ARIA attributes present on all interactive and status elements
- [ ] Focus styles are visible and use accent color
- [ ] Touch targets meet 44px minimum (or 36px in `.compact-touch`)
- [ ] If new tokens/animations were added — they are documented in `DESIGN_SYSTEM.md`
