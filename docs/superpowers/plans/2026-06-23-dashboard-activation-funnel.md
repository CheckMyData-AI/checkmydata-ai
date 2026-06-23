# Dashboard Activation Funnel — Implementation Plan (Phase 1 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut first-connection friction and remove the conflicting getting-started surfaces — paste a connection string to auto-detect type and autofill fields (fixes F6), and unify the onboarding order so SSH is no longer a false first step (fixes F1).

**Architecture:** A pure `parseConnectionString` util (no React) turns a URI into structured fields; a pure `applyConnectionString` helper merges a parse into the existing `FormState`; the connection create form gains a "paste to autofill" box wired to those pure functions; the sidebar getting-started checklist is reordered to match the wizard's DB-first flow.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind v4, Zustand, Vitest + Testing Library + jsdom.

**Source spec:** `docs/superpowers/specs/2026-06-23-dashboard-ux-audit-redesign-design.md` (§5.1 activation, §5.2 connections, findings F1 + F6).

## Global Constraints

- Supported `db_type` values (verbatim from `connection-form-helpers.ts`): `postgres | mysql | mongodb | clickhouse | mcp`. Default ports: postgres 5432, mysql 3306, mongodb 27017, clickhouse 9000.
- The parser is **pure** (no React/DOM imports) so it unit-tests cleanly and is reusable by the onboarding wizard later.
- Autofill is **additive** — it must not change the existing "Use connection string" mode or the structured-field path; it only pre-populates fields the user can edit.
- Semantic design tokens only (`bg-surface-*`, `text-text-*`, `text-accent`, etc.); no raw Tailwind palette, no hardcoded hex. Reuse `inputCls`/`halfInputCls` from `connection-form-helpers.ts`.
- A11y: the autofill input needs an `aria-label`; the detected-type hint is text, not color-only.
- Tests live in `frontend/src/__tests__/`, run with `npx vitest run`.
- Conventional commits ending with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer. Phase 1 ships additively (no flag).

---

### Task 1: `parseConnectionString` pure util

**Files:**
- Create: `frontend/src/lib/connection-string.ts`
- Test: `frontend/src/__tests__/connection-string.test.ts`

**Interfaces:**
- Produces:
  - `interface ParsedConnection { db_type: string; db_host: string; db_port: string; db_name: string; db_user: string; db_password: string }`
  - `function parseConnectionString(raw: string): ParsedConnection | null`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/connection-string.test.ts
import { describe, expect, it } from "vitest";
import { parseConnectionString } from "@/lib/connection-string";

describe("parseConnectionString", () => {
  it("parses a full postgres URI", () => {
    expect(parseConnectionString("postgres://alice:s3cret@db.example.com:6543/orders")).toEqual({
      db_type: "postgres",
      db_host: "db.example.com",
      db_port: "6543",
      db_name: "orders",
      db_user: "alice",
      db_password: "s3cret",
    });
  });

  it("maps postgresql:// scheme and defaults the port", () => {
    const r = parseConnectionString("postgresql://bob@localhost/app");
    expect(r?.db_type).toBe("postgres");
    expect(r?.db_port).toBe("5432");
    expect(r?.db_user).toBe("bob");
    expect(r?.db_name).toBe("app");
  });

  it("parses mysql and defaults port 3306", () => {
    const r = parseConnectionString("mysql://root:pw@10.0.0.5/shop");
    expect(r?.db_type).toBe("mysql");
    expect(r?.db_port).toBe("3306");
    expect(r?.db_host).toBe("10.0.0.5");
  });

  it("maps mongodb+srv to mongodb", () => {
    const r = parseConnectionString("mongodb+srv://u:p@cluster0.abcd.mongodb.net/analytics");
    expect(r?.db_type).toBe("mongodb");
    expect(r?.db_host).toBe("cluster0.abcd.mongodb.net");
    expect(r?.db_name).toBe("analytics");
  });

  it("maps clickhouse and tcp schemes", () => {
    expect(parseConnectionString("clickhouse://u:p@ch.host:9000/metrics")?.db_type).toBe("clickhouse");
    expect(parseConnectionString("tcp://u:p@ch.host:9000/metrics")?.db_type).toBe("clickhouse");
  });

  it("url-decodes credentials", () => {
    const r = parseConnectionString("postgres://user%40corp:p%40ss@h:5432/db");
    expect(r?.db_user).toBe("user@corp");
    expect(r?.db_password).toBe("p@ss");
  });

  it("returns null for unknown schemes or non-URIs", () => {
    expect(parseConnectionString("redis://h:6379")).toBeNull();
    expect(parseConnectionString("just some text")).toBeNull();
    expect(parseConnectionString("")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/connection-string.test.ts`
Expected: FAIL — cannot resolve `@/lib/connection-string`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lib/connection-string.ts
export interface ParsedConnection {
  db_type: string;
  db_host: string;
  db_port: string;
  db_name: string;
  db_user: string;
  db_password: string;
}

const SCHEME_TO_DB_TYPE: Record<string, string> = {
  postgres: "postgres",
  postgresql: "postgres",
  mysql: "mysql",
  mariadb: "mysql",
  mongodb: "mongodb",
  "mongodb+srv": "mongodb",
  clickhouse: "clickhouse",
  tcp: "clickhouse",
};

const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
};

export function parseConnectionString(raw: string): ParsedConnection | null {
  const trimmed = raw.trim();
  const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):\/\//);
  if (!schemeMatch) return null;

  const scheme = schemeMatch[1].toLowerCase();
  const db_type = SCHEME_TO_DB_TYPE[scheme];
  if (!db_type) return null;

  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }

  return {
    db_type,
    db_host: url.hostname || "",
    db_port: url.port || DEFAULT_PORTS[db_type] || "",
    db_name: decodeURIComponent(url.pathname.replace(/^\//, "").split("/")[0] || ""),
    db_user: decodeURIComponent(url.username || ""),
    db_password: decodeURIComponent(url.password || ""),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/connection-string.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/connection-string.ts frontend/src/__tests__/connection-string.test.ts
git commit -m "feat(connections): parse connection strings into structured fields" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `applyConnectionString` form-merge helper

**Files:**
- Modify: `frontend/src/components/connections/connection-form-helpers.ts`
- Test: `frontend/src/__tests__/connection-form-helpers.test.ts`

**Interfaces:**
- Consumes: `parseConnectionString`, `ParsedConnection` (Task 1); `FormState`, `EMPTY_FORM` (existing).
- Produces: `function applyConnectionString(form: FormState, raw: string): { form: FormState; detected: string | null }` — returns a new form with parsed fields merged in (only non-empty parsed values overwrite) and the detected db_type (or `null` if unparseable).

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/connection-form-helpers.test.ts
import { describe, expect, it } from "vitest";
import { EMPTY_FORM, applyConnectionString } from "@/components/connections/connection-form-helpers";

describe("applyConnectionString", () => {
  it("merges parsed fields and reports the detected type", () => {
    const { form, detected } = applyConnectionString(
      { ...EMPTY_FORM },
      "postgres://alice:s3cret@db.example.com:6543/orders",
    );
    expect(detected).toBe("postgres");
    expect(form.db_type).toBe("postgres");
    expect(form.db_host).toBe("db.example.com");
    expect(form.db_port).toBe("6543");
    expect(form.db_name).toBe("orders");
    expect(form.db_user).toBe("alice");
    expect(form.db_password).toBe("s3cret");
  });

  it("leaves the form untouched and reports null for an unparseable string", () => {
    const original = { ...EMPTY_FORM, db_host: "keep.me" };
    const { form, detected } = applyConnectionString(original, "not a uri");
    expect(detected).toBeNull();
    expect(form.db_host).toBe("keep.me");
  });

  it("does not clobber an existing password when the string omits one", () => {
    const original = { ...EMPTY_FORM, db_password: "existing" };
    const { form } = applyConnectionString(original, "mysql://root@h:3306/shop");
    expect(form.db_password).toBe("existing");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/connection-form-helpers.test.ts`
Expected: FAIL — `applyConnectionString` is not exported.

- [ ] **Step 3: Add the helper** (append to `connection-form-helpers.ts`, after `connToForm`)

First add the import at the top of `connection-form-helpers.ts` (below the existing imports):

```ts
import { parseConnectionString } from "@/lib/connection-string";
```

Then append:

```ts
export function applyConnectionString(
  form: FormState,
  raw: string,
): { form: FormState; detected: string | null } {
  const parsed = parseConnectionString(raw);
  if (!parsed) return { form, detected: null };
  const next: FormState = {
    ...form,
    db_type: parsed.db_type,
    ...(parsed.db_host ? { db_host: parsed.db_host } : {}),
    ...(parsed.db_port ? { db_port: parsed.db_port } : {}),
    ...(parsed.db_name ? { db_name: parsed.db_name } : {}),
    ...(parsed.db_user ? { db_user: parsed.db_user } : {}),
    ...(parsed.db_password ? { db_password: parsed.db_password } : {}),
  };
  return { form: next, detected: parsed.db_type };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/connection-form-helpers.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/connections/connection-form-helpers.ts frontend/src/__tests__/connection-form-helpers.test.ts
git commit -m "feat(connections): applyConnectionString form-merge helper" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: paste-to-autofill UI in the connection form

**Files:**
- Modify: `frontend/src/components/connections/ConnectionSelector.tsx`
- Test: `frontend/src/__tests__/ConnectionAutofill.test.tsx`

**Interfaces:**
- Consumes: `applyConnectionString` (Task 2), existing `form`/`setForm`, `inputCls`.
- Produces: an autofill `<input>` rendered at the top of the structured (non-MCP, non-`useConnString`) branch of `formUI`, plus a `detectedType` state + hint.

**Scene-setting:** `ConnectionSelector.tsx` holds the create/edit form in the `formUI` JSX (around lines 727–812 is the non-MCP block; the structured-fields branch is the `else` after `useConnString ? (...) : (...)`, around line 750). Add the autofill box as the first element inside that structured branch (i.e., right after `<>` at the start of the `: (` structured branch), so it appears above Host/Port. Read the file to confirm the exact JSX boundaries before editing.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/ConnectionAutofill.test.tsx
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionSelector } from "@/components/connections/ConnectionSelector";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: { connections: { indexDbStatus: vi.fn().mockResolvedValue({ is_indexed: false }), syncStatus: vi.fn().mockResolvedValue({ is_synced: false }), learningsStatus: vi.fn().mockResolvedValue({ total_active: 0 }) } },
}));

afterEach(cleanup);
beforeEach(() => {
  useAppStore.setState({
    activeProject: { id: "p1", name: "Proj" } as never,
    connections: [],
    activeConnection: null,
    sshKeys: [],
  } as never);
});

describe("connection autofill", () => {
  it("autofills host/port/db/user and detects type from a pasted string", () => {
    render(<ConnectionSelector createRequested onCreateHandled={() => {}} />);
    const box = screen.getByLabelText(/paste a connection string/i) as HTMLInputElement;
    fireEvent.change(box, {
      target: { value: "postgres://alice:s3cret@db.example.com:6543/orders" },
    });
    expect((screen.getByLabelText(/database host/i) as HTMLInputElement).value).toBe("db.example.com");
    expect((screen.getByLabelText(/database port/i) as HTMLInputElement).value).toBe("6543");
    expect((screen.getByLabelText(/database name/i) as HTMLInputElement).value).toBe("orders");
    expect((screen.getByLabelText(/database username/i) as HTMLInputElement).value).toBe("alice");
    expect(screen.getByText(/detected: postgres/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ConnectionAutofill.test.tsx`
Expected: FAIL — no element labelled "Paste a connection string".

- [ ] **Step 3: Implement the autofill box**

In `ConnectionSelector.tsx`:

1. Add to the imports from `./connection-form-helpers` (extend the existing import list): `applyConnectionString`.
2. Add state near the other `useState` calls (e.g. after `const [useConnString, setUseConnString] = useState(false);`):

```tsx
  const [detectedType, setDetectedType] = useState<string | null>(null);
```

3. Reset it in `resetForm` (add `setDetectedType(null);` inside `resetForm`).
4. Inside `formUI`, in the structured-fields branch (the `: (` after `useConnString ?`), insert as the FIRST child (above the Host/Port grid):

```tsx
              <div className="space-y-1">
                <input
                  onChange={(e) => {
                    const raw = e.target.value;
                    const { form: next, detected } = applyConnectionString(form, raw);
                    setDetectedType(detected);
                    if (detected) setForm(next);
                  }}
                  placeholder="Paste a connection string to autofill…"
                  aria-label="Paste a connection string"
                  className={inputCls}
                  maxLength={500}
                />
                {detectedType && (
                  <p className="text-[10px] text-success px-1">
                    Detected: {detectedType} — fields filled below, review &amp; add password if needed.
                  </p>
                )}
              </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ConnectionAutofill.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/connections/ConnectionSelector.tsx frontend/src/__tests__/ConnectionAutofill.test.tsx
git commit -m "feat(connections): paste-to-autofill connection string in the create form" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: unify the getting-started checklist (fix F1)

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx` (the two identical "Getting Started" checklist blocks — mobile ~lines 484–499 and desktop ~lines 678–719)

**Interfaces:** none (presentational change).

**Scene-setting:** The sidebar's getting-started checklist currently lists, in order: (1) Add an SSH key, (2) Create your first project, (3) Add a database connection. The onboarding wizard is DB-first and treats SSH as optional/just-in-time. This task aligns the checklist to the wizard: drop the SSH-first step (SSH is only needed for tunneled DBs) and order it project → connection → ask. There are TWO copies of the array (mobile + desktop renders); update BOTH identically.

- [ ] **Step 1: Read the file and locate both checklist arrays**

Run: `cd frontend && grep -n "Add an SSH key" src/components/Sidebar.tsx`
Expected: two matches (mobile + desktop). Read ~10 lines around each.

- [ ] **Step 2: Replace both checklist arrays**

In BOTH locations, replace the three-item array:

```tsx
                    { done: sshKeys.length > 0, step: 1, label: "Add an SSH key" },
                    { done: projects.length > 0, step: 2, label: "Create your first project" },
                    { done: connections.length > 0, step: 3, label: "Add a database connection" },
```

with the project-first, SSH-omitted version:

```tsx
                    { done: projects.length > 0, step: 1, label: "Create your first project" },
                    { done: connections.length > 0, step: 2, label: "Add a database connection" },
                    { done: connections.length > 0 && projects.some((p) => p.repo_url), step: 3, label: "Connect your code (optional)" },
```

(The desktop copy is formatted across multiple lines — match its exact indentation; the mobile copy is single-line per item. Use `replace_all` only if the two copies are byte-identical; otherwise edit each occurrence with enough surrounding context to disambiguate.)

- [ ] **Step 3: Verify the gate**

Run: `cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npx vitest run`
Expected: typecheck clean, zero warnings, all tests pass (the existing Sidebar tests still green).

- [ ] **Step 4: Manual check**

`npm run dev` → with no projects, the sidebar getting-started card shows project → connection → connect-code (no SSH-first step), matching the wizard.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Sidebar.tsx
git commit -m "fix(onboarding): unify getting-started checklist (drop SSH-first, match wizard)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage:** F6 (no connection-string parse) → Tasks 1–3 ✓. F1 (conflicting getting-started, SSH-first) → Task 4 ✓. Schema-grounded first-run prompts, non-blocking-indexing UX, and the post-activation digest from §5.1 are **deferred to a Phase 1b plan** (they need a backend prompt endpoint and the Ask-home surface from Phase 2) — out of this increment's scope by design.

**Placeholder scan:** none — all code/tests complete; commands have expected output.

**Type consistency:** `ParsedConnection`/`parseConnectionString` (Task 1) consumed verbatim by `applyConnectionString` (Task 2), consumed verbatim by the Task 3 UI. `FormState`/`EMPTY_FORM`/`inputCls` reused from the existing helpers module.

**Scope note:** Phase 1 of 6. Independently shippable, additive (no flag). Next: Phase 2 (Ask-home + calm answer).
