# Product

## Register

product

## Users

Data engineers, analysts, product managers, and engineering leads at teams that own production databases plus (often) a Git repo. They work at a desk, usually with multiple monitors, often in a dim office or home setup, under time pressure to answer data questions correctly the first time. Many are fluent in SQL but tired of re-deriving schema quirks, soft-delete flags, and cent-vs-dollar conventions on every query. Others are not SQL experts and need a safe path to trustworthy numbers.

Primary workflow: connect a project (DB + optional repo), wait for or trigger indexing, then ask questions in chat, inspect SQL and reasoning, save queries, share dashboards, and flag wrong answers so the system learns.

## Product Purpose

CheckMyData.ai is an intelligence layer between humans and their databases. It synthesizes schema, codebase, custom rules, and accumulated learnings into natural-language answers backed by validated, dialect-aware SQL (PostgreSQL, MySQL, ClickHouse, MongoDB). Success looks like: correct answers on the first attempt, visible traceability (SQL + reasoning + sources), institutional memory that compounds per connection, and confidence to share results with stakeholders.

The product is not a generic SQL editor or a BI dashboard-first tool. Conversation is the core interaction; visualizations and dashboards extend verified queries.

## Brand Personality

**Precise. Transparent. Calm.**

Voice is direct and technical without hype. The UI should feel like a serious workspace for data work: dense when needed, never theatrical. Show the work (SQL, pipeline stages, freshness warnings) instead of implying magic. Marketing surfaces may use more display typography and motion; the product UI stays restrained and task-focused.

## Anti-references

- Generic chatbot chrome that hides SQL, reasoning, or data sources
- BI dashboard tools where charts are the primary model and chat is an afterthought
- Cream / sand / warm-neutral SaaS marketing palettes bleeding into the product shell
- Hero-metric landing templates (big number, tiny label, gradient accent) on product screens
- Glassmorphism, gradient text, and decorative motion that does not convey state
- Identical icon + heading + blurb card grids for every settings section
- Side-stripe accent borders on list rows and callouts
- One-size-fits-all answers that ignore per-project schema, rules, and learnings

## Design Principles

1. **Show the work** — Every answer must remain inspectable: SQL, attempt history, rules applied, and freshness of underlying knowledge.
2. **Trust through verification** — Prefer warnings, gates, and investigation flows over silent wrong numbers; user feedback overrides model confidence.
3. **Task-first density** — Optimize for ongoing data investigation (sidebar, chat, pipeline status, tables), not marketing storytelling patterns inside `/app`.
4. **Graceful degradation** — Incomplete indexing or missing context surfaces explicit stale-state warnings; reduced capability beats hard failure.
5. **Memory with boundaries** — Learning and insights stay scoped per connection unless explicitly opted in; never leak conventions across unrelated databases.

## Accessibility & Inclusion

Target **WCAG 2.1 AA** for product UI. Existing system requirements (see `DESIGN_SYSTEM.md`):

- Global `prefers-reduced-motion: reduce` neutralizes CSS transitions/animations; Framer Motion uses `reducedMotion="user"` on `/app`; marketing motion opts out separately.
- Focus-visible rings on interactive elements; modals trap focus and restore on close.
- Icon buttons require descriptive `aria-label`; inputs use `aria-label` / `aria-required` / `aria-invalid` as appropriate.
- Touch targets: minimum 44×44px on coarse pointers; 36×36px allowed inside `.compact-touch` dense zones.
- Never disable pinch zoom (`maximum-scale: 5`, `user-scalable: true`).
- Skip link to `#main-content` on keyboard focus.

Color-blind users rely on semantic status colors plus text labels (not color alone) for connection health, pipeline stages, and toasts.
