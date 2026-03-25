# CheckMyData.ai — Design System

Single source of truth for all visual design decisions.
Implementation lives in `frontend/src/app/globals.css` (`@theme` block) and `frontend/src/components/ui/`.

---

## 1. Foundations

### 1.1 Color System

The app uses a **dark-only** theme. All colors are defined as semantic tokens in the `@theme` block of `globals.css`. Every component must use these tokens — never raw Tailwind palette classes.

#### Surfaces

| Token | Hex | Tailwind class | Usage |
|-------|-----|----------------|-------|
| `--color-surface-0` | `#09090b` | `bg-surface-0` | Page background, root shell |
| `--color-surface-1` | `#18181b` | `bg-surface-1` | Cards, panels, sidebar, form inputs |
| `--color-surface-2` | `#27272a` | `bg-surface-2` | Hover states on surface-1 elements, nested panels |
| `--color-surface-3` | `#3f3f46` | `bg-surface-3` | Tooltips, elevated chips, scrollbar thumbs |

#### Borders

| Token | Hex | Tailwind class | Usage |
|-------|-----|----------------|-------|
| `--color-border-subtle` | `#27272a` | `border-border-subtle` | Default card/panel borders, dividers |
| `--color-border-default` | `#3f3f46` | `border-border-default` | Stronger borders, modal panels, tooltips |

#### Text

| Token | Hex | Tailwind class | Usage |
|-------|-----|----------------|-------|
| `--color-text-primary` | `#fafafa` | `text-text-primary` | Headings, primary body text, active labels |
| `--color-text-secondary` | `#a1a1aa` | `text-text-secondary` | Secondary labels, descriptions |
| `--color-text-tertiary` | `#71717a` | `text-text-tertiary` | Tertiary captions, timestamps |
| `--color-text-muted` | `#52525b` | `text-text-muted` | Placeholders, disabled text, idle icons |

#### Accent

| Token | Hex | Tailwind class | Usage |
|-------|-----|----------------|-------|
| `--color-accent` | `#3b82f6` | `bg-accent` / `text-accent` | Primary CTA, links, active tab indicators, focus rings |
| `--color-accent-hover` | `#60a5fa` | `bg-accent-hover` / `text-accent-hover` | Hover state for accent elements |
| `--color-accent-muted` | `#3b82f620` | `bg-accent-muted` | Faint accent tint for ghost-accent hover backgrounds |

#### Semantic Status

| Token | Hex | Tailwind class | Usage |
|-------|-----|----------------|-------|
| `--color-success` | `#34d399` | `text-success` / `bg-success` | Connected status, success messages |
| `--color-success-muted` | `#34d39920` | `bg-success-muted` | Success toast backgrounds |
| `--color-warning` | `#fbbf24` | `text-warning` / `bg-warning` | Warnings, loading indicators |
| `--color-warning-muted` | `#fbbf2420` | `bg-warning-muted` | Warning backgrounds |
| `--color-error` | `#f87171` | `text-error` / `bg-error` | Error messages, destructive indicators |
| `--color-error-muted` | `#f8717120` | `bg-error-muted` | Error backgrounds, destructive hover tint |
| `--color-info` | `#60a5fa` | `text-info` / `bg-info` | Info messages |
| `--color-info-muted` | `#60a5fa20` | `bg-info-muted` | Info backgrounds |

#### Brand Chrome

| Context | Value |
|---------|-------|
| PWA `theme-color` | `#3b82f6` (accent) |
| PWA `background_color` | `#09090b` (surface-0) |
| App icon gradient | `bg-gradient-to-br from-accent to-blue-700` |

### 1.2 Typography

Two typefaces loaded via `next/font/google` with `display: "swap"`:

| Family | CSS variable | Tailwind class | Role |
|--------|-------------|----------------|------|
| **DM Sans** | `--font-sans` | `font-sans` | All UI text: headings, body, labels, buttons |
| **JetBrains Mono** | `--font-mono` | `font-mono` | Code blocks, SQL, data tables, monospaced values |

#### Type Scale

| Role | Classes | Example |
|------|---------|---------|
| Page title | `text-2xl font-bold tracking-tight` | Auth screen heading |
| Section heading | `text-lg font-semibold` | Card titles, modal titles |
| Subsection heading | `text-base font-semibold` | Panel sub-headers |
| Body | `text-sm` | Chat messages, form labels, descriptions |
| Caption | `text-xs` | Error messages, timestamps, toast text, secondary actions |
| Micro | `text-[11px]` | Legal links, footnotes |
| Micro smallest | `text-[10px]` | Tooltip text, inline labels on icon buttons, validation hints |

#### Line Height and Tracking

- Default `leading-normal` for body text.
- `leading-relaxed` for multi-line descriptions and detail paragraphs in modals.
- `tracking-tight` on page titles (`text-2xl`).
- `tracking-wider` + `uppercase` for divider labels (e.g., "or" separator).

### 1.3 Spacing

Consistent use of Tailwind's spacing scale. Preferred values by context:

| Context | Padding | Gap | Margin |
|---------|---------|-----|--------|
| Icon button (xs) | `p-1` | — | — |
| Icon button (sm) | `p-1.5` | `gap-1` | — |
| Icon button (md) | `p-2` | `gap-1` | — |
| Form input | `px-3.5 py-2.5` | — | — |
| Text button / CTA | `px-4 py-1.5` (small) / `py-2.5` (full-width) | — | — |
| Card / panel interior | `p-5` or `p-6` | `space-y-4` | — |
| Section margin | — | — | `mb-4` / `mb-8` |
| Stacked form fields | — | `space-y-4` | — |
| Sidebar items | `px-2 py-1` to `px-3 py-2` | `gap-2` | — |
| Page-level padding | `p-4` | — | — |

### 1.4 Border Radius

| Class | Use case |
|-------|----------|
| `rounded` | Small inline elements, icon buttons (xs/sm), status dots |
| `rounded-md` | Icon buttons (md), code blocks, tags |
| `rounded-lg` | Inputs, text buttons, modals, toasts, skip-link |
| `rounded-xl` | Cards, panels, auth form containers |
| `rounded-2xl` | Brand logo container, large decorative elements |
| `rounded-full` | Spinners, status dots, avatar circles |

### 1.5 Shadows

| Class | Use case |
|-------|----------|
| `shadow-lg` | Toasts, dropdowns |
| `shadow-xl` | Modals, popover panels |

No shadows on cards or sidebar — elevation is conveyed through surface color difference and borders.

### 1.6 Icons

Custom `Icon` component (`frontend/src/components/ui/Icon.tsx`) rendering inline SVGs with Lucide-style paths.

**Properties:**
- `name`: typed union of available icon names (55+ icons).
- `size`: pixel value. Standard sizes: `10`, `12`, `14`, `16`, `20`, `28`.
- SVG uses `stroke="currentColor"`, `strokeWidth={2}`, `fill="none"` — color is controlled via parent text color classes.

**Size usage by context:**

| Size | Context |
|------|---------|
| 10 | ActionButton xs |
| 12 | ActionButton sm, inline error/validation icons |
| 14 | ActionButton md, sidebar icons |
| 16 | Default, standalone icons |
| 20 | Feature icons, section headers |
| 28 | Brand logo icon (zap) |

Do not import external icon packages. Add new icons to the `PATHS` record in `Icon.tsx` using 24x24 viewBox Lucide-style paths.

---

## 2. Components

### 2.1 Buttons

#### Primary (full-width CTA)

```
w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold
hover:bg-accent-hover disabled:opacity-50 transition-colors
```

Used for main form submissions (Sign In, Create Account, Save).

#### Secondary / Outlined

```
px-4 py-1.5 text-xs rounded border transition-colors
text-text-secondary border-border-default
hover:text-text-primary hover:border-border-default
```

Used for Cancel actions in modals and secondary choices.

#### Destructive (filled)

```
px-4 py-1.5 text-xs text-white rounded transition-colors
bg-red-600 hover:bg-red-500
disabled:opacity-40 disabled:cursor-not-allowed
```

Used for destructive confirmations (delete, disconnect).

#### ActionButton (icon buttons)

Three variants defined in `ActionButton.tsx`:

| Variant | Rest state | Hover state |
|---------|-----------|-------------|
| `ghost` | `text-text-muted` | `text-text-secondary bg-surface-2` |
| `danger` | `text-text-muted` | `text-error bg-error-muted` |
| `accent` | `text-text-muted` | `text-accent bg-accent-muted` |

Three sizes:

| Size | Padding | Min dimensions | Icon size | Radius |
|------|---------|---------------|-----------|--------|
| `xs` | `p-1` | `min-w-6 min-h-6` | 10px | `rounded` |
| `sm` | `p-1.5` | `min-w-8 min-h-8` | 12px | `rounded` |
| `md` | `p-2` | `min-w-9 min-h-9` | 14px | `rounded-md` |

All buttons have:
- `transition-all duration-150`
- Focus: `focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface-0`
- Disabled: `opacity-40 cursor-not-allowed`
- Every icon button must have `aria-label` and be wrapped in `<Tooltip>`.

#### Inline text buttons (links)

```
text-accent hover:text-accent-hover transition-colors
```

Used for inline actions (Register / Sign In toggle, footer links).

### 2.2 Form Inputs

Canonical class string for all text/email/password inputs:

```
w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm
border border-border-subtle
focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none
transition-colors placeholder-text-muted
```

**Validation states:**
- Error: `border-red-500 focus:border-red-500 focus:ring-red-500/30`
- Error hint: `text-[10px] text-red-400 mt-1 px-1`
- Neutral hint: `text-[10px] text-text-muted mt-1 px-1`

**Required attributes:**
- `aria-label` on every input.
- `aria-required="true"` on required fields.
- `aria-invalid` when validation fails.

### 2.3 Cards and Panels

```
bg-surface-1 rounded-xl border border-border-subtle p-5
```

or `p-6` for larger panels. Internal content uses `space-y-4` for vertical stacking.

Cards sit on `bg-surface-0` backgrounds. No shadow on cards — elevation is conveyed by the surface color step.

### 2.4 Modals

**Overlay:**
```
fixed inset-0 z-50 flex items-center justify-center bg-black/60
```

**Panel:**
```
bg-surface-1 border border-border-default rounded-lg p-5
max-w-sm w-full mx-4 shadow-xl
```

**Behavior:**
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby`.
- Focus trap: Tab cycles within focusable elements.
- Escape key closes the modal.
- Click outside (on overlay) closes the modal.
- Entry animation: `animate-in fade-in zoom-in-95 duration-150`.

### 2.5 Tooltips

```
pointer-events-none whitespace-nowrap px-2 py-1 rounded-md
text-[10px] font-medium leading-none
bg-surface-3 text-text-primary border border-border-default
animate-tooltip-in
```

- Rendered via `createPortal` to `document.body`.
- Positioned with `position: fixed` + `z-index: 9999`.
- 200ms delay before showing.
- Placements: `top`, `bottom` (default), `right`.
- Auto-repositions to stay within viewport.
- `aria-describedby` on the trigger element.

### 2.6 Toasts

Position: `fixed bottom-4 right-4 z-[60]`, stacked with `gap-2`, max width `max-w-sm`.

```
px-4 py-2.5 rounded-lg border text-xs shadow-lg
animate-[slideIn_0.2s_ease-out] flex items-start gap-2
```

**Semantic variants:**

| Type | Classes |
|------|---------|
| `success` | `bg-emerald-900/90 border-emerald-700 text-emerald-200` |
| `error` | `bg-red-900/90 border-red-700 text-red-200` |
| `info` | `bg-zinc-800/90 border-zinc-600 text-zinc-200` |

Each toast has `role="alert"`, `aria-live="polite"`, and a dismiss button with `aria-label="Dismiss notification"`.

> **Migration note:** toast colors use raw palette classes for the semi-transparent backgrounds. This is acceptable because the status variants need distinct hues beyond what the semantic tokens provide. If new toast types are added, follow the same `{hue}-900/90` + `{hue}-700` + `{hue}-200` pattern.

### 2.7 Status Dots

Defined in `StatusDot.tsx`. A colored circle indicating connection or process state.

**Sizes:**

| Size | Classes |
|------|---------|
| `sm` | `w-1.5 h-1.5` |
| `md` | `w-2 h-2` |

**Colors:** Use semantic tokens directly — `bg-success`, `bg-warning`, `bg-error`, `bg-info`, `bg-surface-3` (idle).

Common: `shrink-0 rounded-full inline-block`. Optional `animate-pulse-dot` for loading state.

Every status dot must have `role="img"` and `aria-label`.

### 2.8 Spinner

```
w-4 h-4 border-2 border-surface-3 border-t-text-secondary
rounded-full animate-spin
```

Wrapper: `flex justify-center py-3`. Must have `role="status"`, `aria-live="polite"`, and an `sr-only` "Loading..." label.

### 2.9 Scrollbars

Three scrollbar variants defined in `globals.css`:

| Class | Width | Thumb color | Use case |
|-------|-------|-------------|----------|
| `.sidebar-scroll` / `.scrollbar-thin` | 4px | `#3f3f46` (surface-3) | Sidebar, small panels |
| `.chat-scroll` | 6px | `#27272a` (border-subtle) | Main chat area |
| `.data-table-scroll` | 4px | `#3f3f46` (surface-3) | Data tables (with edge fade gradients) |

Also: `.chat-markdown pre` and `.chat-markdown table` get 4px horizontal scrollbars.

All use `scrollbar-width: thin` for Firefox and `::-webkit-scrollbar` for Chromium/Safari. Tracks are `transparent`.

---

## 3. Patterns

### 3.1 Layout

```
Full-height flex shell (100vh)
├── Sidebar (collapsible, hidden on mobile)
│   ├── Project selector
│   ├── Navigation sections (SidebarSection)
│   └── User/settings footer
├── Main content area (flex-1)
│   ├── Header (desktop) / Mobile header with hamburger
│   ├── Chat messages (scrollable, .chat-scroll)
│   └── Chat input (fixed bottom)
└── Notes drawer (right side, toggleable)
```

- Desktop: sidebar always visible (unless manually collapsed), main content fills remaining width.
- Mobile (`max-width: 767px`): sidebar hidden behind hamburger menu, full-width content, bottom-anchored input.
- All scrollable containers use the appropriate custom scrollbar class.
- `id="main-content"` on the main area for skip-link target.

### 3.2 Animations

All custom animations live in `globals.css`. Standard timing: `ease-out`.

| Animation | Duration | Keyframe | CSS class | Usage |
|-----------|----------|----------|-----------|-------|
| Fade in | 0.15s | `fade-in` | `.animate-fade-in` | Generic element entrance |
| Slide up | 0.25s | `slide-up` | `.animate-slide-up` | Mobile drawers, bottom sheets |
| Slide in from left | 0.2s | `slide-in-left` | `.animate-slide-in-left` | Sidebar items appearing |
| Slide in from top | 0.2s | `slideIn` | `animate-[slideIn_0.2s_ease-out]` | Toasts |
| Slide down | — | `slideDown` | (inline) | Dropdown menus |
| Tooltip entrance | 0.15s | `tooltip-in` | `.animate-tooltip-in` | Tooltips (fade + slight scale) |
| Pulse dot | 1.5s infinite | `pulse-dot` | `.animate-pulse-dot` | Loading/status indicators |
| Spin (slow) | — | `spin-slow` | (inline) | Background decorative rotation |
| Task item in | — | `taskItemIn` | (inline) | Staggered list items |
| Onboarding forward | 0.2s | `onboarding-slide-right` | `.animate-onboarding-forward` | Wizard step forward |
| Onboarding back | 0.2s | `onboarding-slide-left` | `.animate-onboarding-back` | Wizard step backward |
| Standard spin | built-in | `animate-spin` | Tailwind built-in | Spinner |

**Rules:**
- UI transitions: 0.15s-0.25s `ease-out`.
- Looping indicators: 1.5s+ `ease-in-out infinite`.
- Never add new `@keyframes` without documenting them here.
- `transition-colors` on all interactive elements for hover/focus state changes. Use `transition-all duration-150` for buttons with multiple changing properties.

### 3.3 Responsive Design

**Breakpoint:** Single mobile breakpoint at `max-width: 767px`.

**Touch targets:** Enforced globally via `@media (pointer: coarse)`:
- Default: `min-height: 44px; min-width: 44px` on all buttons, links, and submit inputs.
- Compact: `min-height: 36px; min-width: 36px` inside `.compact-touch` containers (dense sidebar lists, toolbars).

**Mobile chat:** Code blocks in chat constrained to `max-width: calc(100vw - 4rem)`.

**Viewport:**
- `width: device-width`, `initial-scale: 1`.
- `maximum-scale: 5`, `user-scalable: true` — never disable pinch zoom.

---

## 4. Accessibility

### 4.1 Focus Management

- Global `focus-visible` outline: `2px solid var(--color-accent)` with `2px` offset.
- Form inputs suppress the global outline and use their own `focus:ring-1 focus:ring-accent` + `focus:border-accent`.
- ActionButton focus: `focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-surface-0`.
- Modals trap focus and return it on close.

### 4.2 Skip Link

In `layout.tsx`:
```
<a href="#main-content" className="sr-only focus:not-sr-only ...">
  Skip to main content
</a>
```

Visible only on keyboard focus. Uses `bg-blue-600 text-white rounded-lg text-sm`.

### 4.3 Reduced Motion

Global rule in `globals.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

All animations and transitions are neutralized. No additional opt-out logic needed in components.

### 4.4 ARIA Patterns

| Component | Required attributes |
|-----------|-------------------|
| Icon buttons | `aria-label` (descriptive action) |
| Inputs | `aria-label`, `aria-required`, `aria-invalid` |
| Status dots | `role="img"`, `aria-label` |
| Spinner | `role="status"`, `aria-live="polite"`, `.sr-only` label |
| Modals | `role="dialog"`, `aria-modal="true"`, `aria-labelledby` |
| Toasts | `role="alert"`, `aria-live="polite"` |
| Tooltips | `role="tooltip"`, trigger has `aria-describedby` |
| Dismiss buttons | `aria-label="Dismiss notification"` or equivalent |

### 4.5 Touch Targets

See Section 3.3. Minimum 44x44px on touch devices, 36x36px in compact zones. Enforced via CSS, not per-component.

---

## 5. Migration Notes

### 5.1 Raw Class to Semantic Token Mapping

Some components still use raw Tailwind palette classes. The table below maps them to the correct semantic tokens. New code must always use the semantic column.

| Raw class | Semantic equivalent | Notes |
|-----------|-------------------|-------|
| `bg-zinc-900` | `bg-surface-1` | |
| `bg-zinc-800` | `bg-surface-2` | |
| `border-zinc-700` | `border-border-default` | |
| `border-zinc-700/50` | `border-border-default/50` | Opacity modifier preserved |
| `text-zinc-200` | `text-text-primary` | |
| `text-zinc-300` | `text-text-primary` | Close enough; use primary |
| `text-zinc-400` | `text-text-secondary` | |
| `text-zinc-500` | `text-text-muted` | |
| `text-zinc-600` | `text-text-muted` | |
| `border-zinc-600` | `border-border-default` | |
| `text-red-400` | `text-error` | |
| `text-yellow-400` | `text-warning` | |
| `bg-blue-600` | `bg-accent` | Skip-link only |
| `hover:bg-zinc-700` | `hover:bg-surface-2` | |
| `ring-zinc-500/40` | `ring-accent/40` | Use accent for focus rings |

### 5.2 Components Needing Migration

These components still use raw Tailwind classes where semantic tokens should be used:

| Component | File | Issue |
|-----------|------|-------|
| ConfirmModal | `components/ui/ConfirmModal.tsx` | Uses `bg-zinc-900`, `border-zinc-700`, `text-zinc-*` classes |
| ToastContainer | `components/ui/ToastContainer.tsx` | Uses raw palette for status variants (acceptable, see 2.6) |
| Spinner | `components/ui/Spinner.tsx` | Uses `border-zinc-600 border-t-zinc-300` |
| ChatInput | `components/chat/ChatInput.tsx` | Uses `border-zinc-*`, `ring-zinc-*` |

When touching these files, migrate them to semantic tokens.

---

## 6. Adding to the Design System

When introducing a new token, component, or pattern:

1. Add the token to the `@theme` block in `frontend/src/app/globals.css`.
2. Document it in the appropriate section of this file.
3. If it's a new animation, add the `@keyframes` to `globals.css` and list it in Section 3.2.
4. If it's a new UI component, place it in `frontend/src/components/ui/` and document its variants, sizes, and ARIA requirements in Section 2.
5. Never introduce a new raw Tailwind color class when a semantic token exists or can be created.
