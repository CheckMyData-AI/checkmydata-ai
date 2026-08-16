# CheckMyData.ai — Design System

The product UI runs on **`ledger`**, a style pack from
[sheleg-design](https://github.com/ssheleg/sheleg-design-skill) 1.35.0, extracted
from `basedash.com` on 2026-08-15 by reading its live computed styles and its two
shipped stylesheets.

**The pack is the source of truth for values; this document is the source of truth
for how they are used here.** Every colour, radius, duration and curve below is a
measurement from that reference, not a preference — so the way to change one is to
change the pack and re-copy its token layer, never to edit a hex in this repo.

| Where | What it holds |
|---|---|
| `plugins/sheleg-design/skills/sheleg-design/styles/ledger.md` (in the skill) | the pack: palette, type, texture, components, hero, responsive, bans, traps |
| `frontend/src/app/globals.css` | that pack's `tokens/ledger.css` **copied byte for byte**, then this project's alias layer |
| `frontend/src/components/shadcn/` | shadcn/ui primitives, re-themed onto the pack |
| `frontend/src/components/ui/` | this project's own components, built on those primitives |

Three checks keep the document and the code from drifting apart, and each was
watched failing against a planted defect:
`frontend/src/__tests__/theme-tokens.test.ts` (the token contract),
`frontend/src/__tests__/pack-bans.test.ts` (the pack's two bans),
`frontend/src/__tests__/theme-store.test.ts` (both theme selectors).

---

## 1. Foundations

### 1.1 The one rule

**The accent never fills a control.** The primary button is filled in **ink**;
the terracotta labels, marks, strokes a chart and rules a selected edge. On the
pack's reference, of eleven accent-coloured elements on the page, five are a 10px
monospace uppercase label and **none** is a button. One accent-filled button and
the orange stops meaning "look here" everywhere else — which is why it is a test
(`pack-bans.test.ts`) and not a paragraph.

### 1.2 Colour

Light is the default register; dark is a first-class twin from the same tokens,
and it is **not** the light theme inverted — its alpha ramp is a different set of
steps, its accent a different hex, its warning a different amber.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` | `#fcf9f5` | `#080706` | the page |
| `--panel` | `#fffdfa` | `#0c0b0a` | the raised card |
| `--panel-2` | `#ffffff` | `#171513` | the data plane: tables, menus, popovers |
| `--ink` | `#14100c` | `#fffcf8` | primary text, and the primary button's fill |
| `--ink-2` | ink 72% | ink 70% | secondary prose |
| `--muted` | ink 55% | ink 50% | column heads, axis ticks, row numbers |
| `--faint` | ink 22% | ink 20% | disabled, hairline ticks |
| `--border` | ink 12% | ink 10% | **the elevation device** |
| `--border-strong` | ink 22% | ink 20% | the hover edge |
| `--accent` | `#c2410c` | `#f49556` | THE accent — labels and marks, never a fill |
| `--accent-mark` | `#e8792f` | `#e8792f` | the accent as a fill or a stroke |
| `--on-ink` | `#fcf9f5` | `#14100c` | text **on** `--ink`; it flips with the theme |
| `--ok` | `#2fa86b` | `#2fa86b` | positive delta, healthy |
| `--warn` | amber-500 | amber-300 | needs a human, ambiguous |
| `--danger` | `#f84747` | `#f84747` | negative delta, failed |
| `--info` | `#0891b2` | `#22d3ee` | verified, running |
| `--chart-1…5` | `#ea863f` `#4679f2` `#2fa86b` `#f47bd0` `#4ebcfc` | same | chart series, named for shadcn's `ChartConfig` |

**Status is never by colour alone.** Four of the five semantic colours sit under
4.5:1 on the light field and two under 3:1, so in light mode the colour is
reinforcement and the *word or the sign* is the message: `+23.9%` carries its
plus, a seal carries its word, a failed run says "failed". The values are the
reference's own and are not re-stepped here — a colour invented in this repo
would be exactly what a measured pack exists to prevent.

**`--muted` is 4.13:1 on the field, under AA by 0.37.** It is correct for column
heads, axis ticks and row numbers, where position repeats the word. A label a
decision rests on takes `--ink-2` (7.47:1). Do not darken the token: it paints
every surface, not just this one.

Three vocabularies resolve to those tokens, and two names collide across them —
the pack wins both, because it is the half that is measured. In this repo
`--accent` is the brand terracotta (**not** shadcn's hover surface, which is
`--surface-hover`), and `--muted` is muted ink (**not** shadcn's muted surface,
which is `--inset`).

### 1.3 Typography

| Family | CSS variable | Tailwind class | Role |
|---|---|---|---|
| **Inter** | `--font-ui-webfont` | `font-sans` | all product UI |
| **system monospace** (`ui-monospace, SFMono-Regular, Menlo, …`) | `--font-data` | `font-mono` | **all data**: ids, metrics, timestamps, row numbers, SQL, chips, logs — zero webfont bytes |
| **Space Grotesk** | `--font-display-webfont` | `font-display` | marketing headlines only. Never in product UI |

The pack's own display face is licensed and self-hosted by its reference; per the
pack, a project without that licence points the product display at the UI face,
which is what `--font-display` resolves to here.

The ramp ships as tokens, so "no ad-hoc font size in the diff" is checkable:

| Utility | Size | Use |
|---|---|---|
| `text-kicker` | 10px | the mono kicker and the seal — uppercase, `tracking-kicker` (+0.1em) |
| `text-meta` | 12px | labels, column heads, row numbers |
| `text-body` | 14px | dense UI, table cells, buttons |
| `text-prose` | 15px | running text |
| `text-card` | 18px | card titles, weight 500 |
| `text-title` | 34px | page titles and the big figure on a stat tile — weight 400, `tracking-title` (−0.03em) |

The large figure on a stat tile is the **UI face**, not the monospace: the
reference sets `$4.40M` in Inter and keeps the monospace for the rows under it.
Weights are 400 / 500 / 600 only — 700 exists in the reference's theme and is
never used on its page.

### 1.4 Texture, radius and spacing

**Elevation is a 1px hairline at 12% ink, and no card casts a shadow.** 103 of
the reference's surfaces are exactly that: transparent or `--panel` fill, 1px
`--border`, `--r-card`. Depth comes from the fill step (`--bg` → `--panel` →
`--panel-2`) and from the line. One shadow token, `--shadow-1`, exists for true
overlays — dialogs, popovers, menus — and there is no second one to reach for.

Radii are the reference's ×1.25 ramp, and Tailwind's own scale is remapped onto
it so existing markup inherits it: `rounded-sm` 5 · `rounded-md` 7.5 ·
`rounded-lg` 10 · `rounded-xl` 15 · `rounded-2xl` 20. Named aliases:
`rounded-inset` 7.5 · `rounded-control` 10 · `rounded-card` 15 · `rounded-panel` 20.

**Nesting is concentric**: an inner radius is the outer radius minus the padding
between them. A 15px track with 4px of padding holds a 10px thumb, never a second
15 — two identical radii nested inside one another is the tell of a
stuck-together interface.

Grid is 4px: 4 / 8 / 12 / 16 / 20 / 24 / 32. Buttons pad 8×20, cards 20, table
cells 0×8, a segmented track 4. Fixed heights: data row **32px**, control 30px,
field 38px.

### 1.4a Overlays

A dialog is one of the two places this design permits a shadow, and there is
exactly one token to reach for: `--shadow-1`. A dialog sits on `--panel` at
`--r-panel` (20px); a popover, select or menu sits on `--panel-2`.

**The scrim is `.lg-scrim` — the ink at 45%, never black.** A black wash over a
cream field reads as another product's modal, and over a near-black field it
does nothing at all. Nine surfaces carried their own `bg-black/40…60` before the
class existed; `pack-bans.test.ts` fails if a tenth appears.

`FormModal` and `ConfirmModal` run on Radix through `components/shadcn/dialog.tsx`.
Their hand-rolled focus traps — a `keydown` listener on `window` plus a
`querySelectorAll` per Tab, maintained in two files that had drifted — are gone,
and with them two gaps neither version covered: inert background content, and
focus restored to whatever opened the dialog. Both keep their `open`/`onClose`
API, so call sites did not move.

### 1.4b Fields and selects

A field is 38px on `--panel-2`, radius 10, hairline border, and focus is the 2px
accent ring at 2px offset — `inputBaseCls` in `components/ui/Input.tsx`.

A `<select>` stays **native**. That is what the pack's reference does, and it
keeps the platform's keyboard behaviour and its mobile picker for free; the only
thing it costs is the chevron, which `.lg-select` draws from
`--select-chevron`. Twenty-two selects across eleven files had eleven slightly
different field styles before they all pointed at `selectBaseCls`, and
`pack-bans.test.ts` fails if a twelfth appears.

**`--select-chevron` is a gap in the pack, not a decision here.** The pack has no
slot for the mark, so it lives in this project's layer and should move into
`tokens/ledger.css` the next time that file is edited.

### 1.5 Motion

One curve carries the interface: `--ease` = `cubic-bezier(0.22, 1, 0.36, 1)`,
the reference's own default timing function. `--ease-out` for things entering,
`--ease-in-out` for movement on screen. **`ease-in` is banned in UI.**

Durations are `--dur-xs` 75ms · `--dur-sm` 0.1s · `--dur` 0.15s (the default) ·
`--dur-lg` 0.2s · `--dur-xl` 0.3s, and nothing runs longer than 0.3s. Press
feedback is `scale(0.97)` on controls and nothing else moves.

**Exactly three loops are legal**, all of them state and all stopping when the
state does: the typing cursor while tokens stream, the thinking dots while a run
works, and a 1.4s heartbeat on a live indicator. `prefers-reduced-motion: reduce`
zeroes every duration token and the press scale, and stops all three.

Nothing on the 100+/day path animates: the command palette opens instantly, tab
switches are instant, the segmented control responds on the keypress.

### 1.6 The seal — the one element this product is remembered by

Every answer that states a figure carries a seal saying **how it is known**:
`Verified` (a query the reader can open), `Inferred` (derived by a step the system
can name), `Unverified` (it cannot say). It is `Seal.tsx`, its state comes from
`sealStateFor()` — derived from the answer's own evidence, never from a second
guess — and the scenario is SCN-122.

Three rules decide whether it is honest rather than decorative: every state must
be reachable, the label must be derivable from something real, and it seals a
**card**, not a screen. The badge it replaced was fed
`response_type === "sql_result" ? "unverified" : undefined`, so two of its three
words were unreachable and it told the reader the same thing about every answer.

### 1.7 Icons

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
w-full py-2.5 bg-primary text-primary-foreground rounded-control text-body font-semibold
hover:bg-primary/92 disabled:opacity-50 transition-colors
```

`--primary` is **ink**, and `--primary-foreground` is `--on-ink`, so the button
inverts with the theme: near-black on cream in light, cream on coal in dark.
Filling it with the accent is the pack's one ban and `pack-bans.test.ts` fails on
it. Prefer the primitive — `<Button>` in `components/ui/Button.tsx`, which wraps
`components/shadcn/button.tsx` — over hand-written classes.

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
px-3 h-[30px] text-meta rounded-control border border-danger text-danger
bg-transparent hover:bg-danger-weak transition-colors
disabled:opacity-40 disabled:cursor-not-allowed
```

The destructive control is a **bordered ghost that fills only on hover**: a red
slab makes the decision for the reader before they have made it.

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

Shared React primitives (import from `@/components/ui/`):

| Component | Path | Notes |
|-----------|------|-------|
| `Button` | `Button.tsx` | `primary` / `secondary` / `destructive` / `ghost`; `:active` uses `.ui-pressable` |
| `Input` | `Input.tsx` | Export `inputBaseCls` for legacy forms; prefer `<Input />` for new code |
| `Card` | `Card.tsx` | `Card`, `CardHeader`, `CardBody` |
| `Badge` | `Badge.tsx` | Neutral status chips |
| `ProgressBar` | `ProgressBar.tsx` | GPU `scaleX` fill; `role="progressbar"` |
| `StatusBadge` | `StatusBadge.tsx` | Pipeline stage status → `Icon` + `aria-label` |

Pipeline-specific chat components (`@/components/chat/`):

| Component | Purpose |
|-----------|---------|
| `StageRow` | Collapsed/expanded stage line with tool pill |
| `CheckpointCard` | Checkpoint preview table + Continue / Modify / Retry |
| `StageProgress` | Header progress bar, progressive disclosure, composes the above |

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

**Semantic variants** (defined in `ToastContainer.tsx`, fully tokenized):

| Type | Classes |
|------|---------|
| `success` | `bg-success-muted border-success/30 text-success` |
| `error` | `bg-error-muted border-error/30 text-error` |
| `info` | `bg-surface-2/90 border-border-default text-text-primary` |

Each toast has `role="alert"`, `aria-live="polite"`, and a dismiss button with `aria-label="Dismiss notification"`.

> New toast types must follow the same pattern: `bg-{semantic}-muted` + `border-{semantic}/30` + `text-{semantic}`. Never use raw palette classes.

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
| Checkpoint reveal | 0.24s | `checkpoint-reveal` | `.checkpoint-reveal` | Checkpoint card entrance |
| Progress fill | 0.3s | (transition) | `.pipeline-progress-fill` | Pipeline progress bar (scaleX) |
| Press feedback | 0.14s | (transition) | `.ui-pressable:active` | Button scale(0.97) |
| Stage glow | 2.4s infinite | `stage-glow` | `.stage-active-glow` | Active pipeline stage breathing highlight |
| Stage shake | 0.34s | `stage-shake` | `.stage-failed-shake` | Failed pipeline stage error emphasis |
| Data row cascade | 0.26s | `data-row-enter` | `.data-row-enter` | Result table rows fading in with per-row `animation-delay` (capped at 16 rows) |

> Pipeline stage *entrances* are now driven by Framer Motion springs in `StageRow.tsx` (the old `.pipeline-stage-enter` CSS class was removed).

**Custom easing tokens** (defined in `@theme` and `:root` in `globals.css`):

| Token | Value | Usage |
|-------|-------|-------|
| `--ease-out-quart` | `cubic-bezier(0.23, 1, 0.32, 1)` | UI enter, feedback, progress fill |
| `--ease-in-out-strong` | `cubic-bezier(0.77, 0, 0.175, 1)` | On-screen morph |
| `--ease-drawer` | `cubic-bezier(0.32, 0.72, 0, 1)` | Checkpoint / drawer reveal |

Utility classes: `.ease-out-quart`, `.ease-in-out-strong`, `.ease-drawer` set `transition-timing-function`.
- UI transitions: 0.15s-0.25s `ease-out`.
- Looping indicators: 1.5s+ `ease-in-out infinite`.
- Never add new `@keyframes` without documenting them here.
- `transition-colors` on all interactive elements for hover/focus state changes. Use `transition-all duration-150` for buttons with multiple changing properties.

#### Motion libraries & shared tokens

Three motion layers coexist; pick the right one:

| Layer | Where | Library | Entry points |
|-------|-------|---------|--------------|
| Scroll storytelling | Marketing pages only | GSAP 3 + ScrollTrigger + Lenis | `lib/motion/gsap.ts`, `components/marketing/SmoothScroll.tsx`, `DataStory.tsx`, `WordLight.tsx`, `CountUp.tsx` |
| State choreography | `/app` product UI | Framer Motion (`motion/react`) | `StageRow.tsx`, `ChatPanel.tsx`, `FaqAccordion.tsx` |
| Micro-motion | Everywhere | Pure CSS keyframes/transitions | `globals.css` (table above) |

Shared numeric tokens live in `frontend/src/lib/motion/tokens.ts` — `DUR`, `EASE` (cubic-bezier), `GSAP_EASE`, `SPRING` (Framer Motion presets: `chip`, `message`, `panel`), `STAGGER`. Always import from there instead of inventing new durations/eases inline.

Preference hooks live in `frontend/src/lib/motion/useMotionPreferences.ts` — `useReducedMotion`, `useCoarsePointer`, `useCinematicCapable` (desktop + fine pointer + motion OK). The `/app` page wraps everything in `<MotionConfig reducedMotion="user">`, so Framer Motion animations auto-respect the OS setting. Lenis smooth scrolling (`SmoothScroll`) disables itself on reduced-motion and coarse pointers.

#### Cinematic landing system (`cmd-*`)

A separate, opt-in 2.5D motion layer used **only** on the marketing landing (`(marketing)/page.tsx`). All keyframes live in `globals.css`, are prefixed `cmd-` to avoid collisions, animate only GPU-safe properties (`transform`, `opacity`, `filter`, `clip-path`, `offset-distance`), and are fully neutralized by the global `prefers-reduced-motion` rule. Decorative layers are `aria-hidden`. Reveals are orchestrated by `components/marketing/CinematicEngine.tsx` (IntersectionObserver + rAF parallax; disabled on reduced-motion, parallax also disabled on `pointer: coarse`). A `<noscript>` failsafe in the marketing layout forces revealed state when JS is off.

| Utility / class | Keyframe | Purpose |
|-----------------|----------|---------|
| `.cmd-reveal` (+ `-left` / `-right` / `-scale` / `-rise`) | (transition) | Scroll entrance, toggled by `.is-visible`. Stagger via `--cmd-i`. |
| `.cmd-float` | `cmd-float` | Gentle 9s hover loop for hero/showcase elements |
| `.cmd-glow` | `cmd-glow-pulse` | Blurred atmospheric blob (use a non-animated wrapper for positioning/parallax) |
| `.cmd-grid` | `cmd-grid-drift` | Drifting masked technical grid (depth-0) |
| `.cmd-flow` | `cmd-data-flow` | Flowing dashes along SVG edges. Speed via `--cmd-flow-dur` |
| `.cmd-travel` | `cmd-travel` | Pulse traveling an `offset-path`. `--cmd-path` / `--cmd-travel-dur` / `--cmd-travel-delay` |
| `.cmd-node-pulse` | `cmd-node-pulse` | Soft pulse for graph nodes / core. `--cmd-node-dur` |
| `.cmd-ring` | `cmd-ring` | Expanding core rings. `--cmd-ring-dur` / `--cmd-ring-delay` |
| `.cmd-bar` | `cmd-bar-grow` | Growing answer-chart bars. `--cmd-bar-delay` |
| `.cmd-orbit` | `cmd-orbit` | Slow dashed orbit rotation. `--cmd-orbit-dur` |
| `.cmd-scan` | `cmd-scan` | Vertical scan sweep over the showcase frame |
| `.cmd-parallax` / `.cmd-stage` | (JS / perspective) | Parallax transform target / perspective container |
| `.cmd-story` / `.cmd-story-fallback` | (media query) | Pinned hero scrollytelling vs static fallback. The pinned story renders only at `min-width: 1024px` + `prefers-reduced-motion: no-preference` + `pointer: fine` |
| `.cmd-caret` | `cmd-caret-blink` | Blinking terminal caret in the hero story |

> `.cmd-shimmer-text` (gradient text sweep) was removed — accent headings use plain `text-accent` + `font-display`. Scroll-driven word lighting is done by the `WordLight` component (GSAP opacity scrub) instead.

**Cinematic rules:**
- This layer is for the landing only — do not use `cmd-*` classes in app UI.
- Parallax positioning and `cmd-glow`/`cmd-node-pulse` must not share an element (both write `transform`); put parallax/positioning on a wrapper and the animated class on a child.
- Every decorative `cmd-*` element gets `aria-hidden="true"`.
- Colors come from semantic tokens (incl. `color-mix(in srgb, var(--color-*) N%, transparent)` for glow tints).

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

Visible only on keyboard focus. Uses `bg-primary text-primary-foreground rounded-control text-body`.

### 4.3 Reduced Motion

Global rule in `globals.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-delay: 0ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    transition-delay: 0ms !important;
  }
}
```

All CSS animations, transitions, and stagger delays are neutralized. JS-driven motion opts out separately:
- Framer Motion: `<MotionConfig reducedMotion="user">` at the `/app` root.
- GSAP/Lenis (marketing): components check `useReducedMotion` / `matchMedia` before animating; `DataStory` swaps to a static fallback via the `.cmd-story` media query.
- Recharts: `ChartRenderer` passes `isAnimationActive: false` when reduced motion is detected, and caps the draw-on at 300 ms otherwise — the pack's ceiling, where the Chart.js version it replaced ran 800 ms with a per-datum stagger.

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
| `bg-blue-600` | `bg-primary` | Skip-link; the fill is ink, never the accent |
| `hover:bg-zinc-700` | `hover:bg-surface-2` | |
| `ring-zinc-500/40` | `outline-ring` | Focus is a 2px `--accent` ring at 2px offset — an outline, not a ring utility |

### 5.2 Components Needing Migration

All previously flagged `ui/` components (`ConfirmModal`, `ToastContainer`, `Spinner`, `ChatInput`) have been migrated to semantic tokens. No outstanding raw-palette migrations remain in the shared component layer.

Known optional/tokenization follow-ups (acceptable as-is, not blocking):

| Area | File | Note |
|------|------|------|
| ~~Chart palette~~ | `components/viz/ChartRenderer.tsx` | **Done.** Runs on Recharts through `components/shadcn/chart.tsx`; series colour is `--chart-1…5`, and past the fifth series the ramp repeats darkened toward the ink — a derived rule, because the reference never shows more than five. chart.js and react-chartjs-2 are uninstalled. |
| Feature panels | `components/{insights,schedules,notes,learnings,batch,usage,billing,settings,connections}/` | **Measured rather than assumed:** those nine directories held **eleven** card-shaped containers between them, not the wall of hand-rolled cards the file count suggested. Six were cards at the *control* radius and are now at `--r-card`; two were further copies of the one field and now compose from `inputBaseCls`; the rest were already correct. What remains in them is layout, not geometry. |

When touching these files, prefer migrating to CSS-variable-driven values.

---

## 6. Adding to the Design System

When introducing a new token, component, or pattern:

1. Add the token to the `@theme` block in `frontend/src/app/globals.css`.
2. Document it in the appropriate section of this file.
3. If it's a new animation, add the `@keyframes` to `globals.css` and list it in Section 3.2.
4. If it's a new UI component, place it in `frontend/src/components/ui/` and document its variants, sizes, and ARIA requirements in Section 2.
5. Never introduce a new raw Tailwind color class when a semantic token exists or can be created.
