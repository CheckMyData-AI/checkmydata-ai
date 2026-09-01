#!/usr/bin/env python3
"""Compare a deployment's config against the code defaults, and say what drifted.

Why this exists as a command rather than a paragraph
----------------------------------------------------
On 2026-08-23 an audit found ten boolean environment variables set in production that
the code declared `False` — including `CROSS_CONNECTION_LEARNINGS_ENABLED`, which
`vision.md` §7 names an invariant. Nothing had flagged them, because nothing compared
the two. They were unset on 2026-08-25.

A *deliberate* divergence is legitimate — production runs billing, the MCP server and the
daily knowledge sync, none of which are on by default. But an undocumented deliberate
divergence is indistinguishable from drift, so every audit re-raises it, and eventually
someone silences the finding rather than the cause.

So the deliberate ones are listed below with a reason each. Anything diverging that is
*not* on that list is drift, and this script exits non-zero on it. The list is the
record; the exit code is what keeps the record true.

Usage
-----
    python3 scripts/config_drift.py                      # reads `heroku config --json`
    python3 scripts/config_drift.py --app checkmydata-api
    python3 scripts/config_drift.py --from-json cfg.json  # offline, for CI or a test
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_PY = REPO / "backend" / "app" / "config.py"

#: Divergences that are decisions, with the decision. A key here is *expected* to differ
#: from the code default; anything else that differs is drift.
#:
#: Adding a key is how you record a decision. Removing one is how you retire it. Both
#: belong in the same change as the `heroku config:set` they describe.
DELIBERATE: dict[str, str] = {
    "BILLING_ENABLED": (
        "Production is the paid deployment. The default is off so a self-hosted "
        "install does not surface Stripe routes it has no keys for."
    ),
    "DAILY_KNOWLEDGE_SYNC_ENABLED": (
        "The 03:00 repo-index → DB-index → code↔DB refresh. Off by default under the "
        "ingestion-automation house rule (nothing calls out on a schedule unasked); on "
        "here because keeping the knowledge layer current is what the product sells."
    ),
    "GIT_AGENT_AUTO_PULL": (
        "GitAgent answers from the local clone, and a clone that lags indexed HEAD "
        "produces answers that are stale without saying so. Off by default because it "
        "writes to a working tree the operator may own."
    ),
    "MCP_ENABLED": (
        "The MCP server is a shipped feature of this deployment. Off by default: it is "
        "an additional authenticated surface, and a self-hosted install should opt in."
    ),
    "DEFAULT_LLM_PROVIDER": (
        "Production routes every LLM call through OpenRouter, not OpenAI directly — "
        "6 338 of 6 479 recorded calls. The code default is 'openai' so a self-hosted "
        "install with only an OPENAI_API_KEY works out of the box. Found on 2026-08-28 "
        "by widening this checker past booleans; it had never been recorded, and the "
        "boolean-only version could not have seen it."
    ),
    "VECTOR_STORE_BACKEND": (
        "pgvector, because ChromaDB persisted to the dyno's container filesystem — "
        "wiped on every restart, unshared between web and worker — which made the "
        "repo index force a full rebuild it could not afford (16 completions in 94 "
        "runs). The condition recorded here is MET: pgvector went live on 2026-08-28 "
        "(v285), a full rebuild ran 2026-08-31 08:32-11:57 UTC and finished "
        "`completed`, and doc_embeddings holds 34 348 rows. The code default is now "
        "`auto`, which resolves to pgvector on a Postgres DATABASE_URL, so this "
        "variable is REDUNDANT rather than a divergence — unset it once that code is "
        "deployed and delete this entry. It stays until then: unsetting it against a "
        "code default of \"chroma\" would move the whole knowledge layer back onto the "
        "dyno's local disk."
    ),
    "MCP_MOUNT_ENABLED": (
        "Multi-tenant remote MCP at /mcp, which is the only mode that resolves a "
        "principal per request. Requires MCP_ENABLED, and is off by default for the "
        "same reason."
    ),
}

#: `name: bool = True`, with an optional trailing comment.
#:
#: The comment is not cosmetic to allow. Anchoring on end-of-line silently dropped three
#: of 58 declarations — `code_graph_enabled`, `lineage_enabled` and `auth_cookie_secure`
#: — because each carries a `# W6: …`-style note. Two of those three are the flags most
#: worth watching, and a checker that cannot see a setting reports it as "no drift".
_BOOL_DEFAULT = re.compile(r"^\s*(\w+)\s*:\s*bool\s*=\s*(True|False)\s*(?:#.*)?$", re.M)

#: `name: str = "x"` and `name: int = 7`, same trailing-comment tolerance.
#:
#: Added 2026-08-28, because the checker had been boolean-shaped since it was written
#: and the risk never was. `VECTOR_STORE_BACKEND` decides whether the entire knowledge
#: layer reads from Postgres or from a dyno's local disk; it is a `str`, it was set in
#: production against a code default of "chroma", and this script printed "No drift".
#: The tool was built after ten *boolean* divergences were found, and inherited the
#: shape of its first evidence as an assumption about the whole problem.
_STR_DEFAULT = re.compile(r'^\s*(\w+)\s*:\s*str\s*=\s*"([^"]*)"\s*(?:#.*)?$', re.M)
_INT_DEFAULT = re.compile(r"^\s*(\w+)\s*:\s*int\s*=\s*(-?\d+)\s*(?:#.*)?$", re.M)


def code_defaults() -> dict[str, str]:
    """Every `name: bool|str|int = X` in the settings module, keyed by env-var name.

    Values come back as strings so one comparison path serves all three; booleans are
    normalised to "true"/"false" so `TRUE`, `1` and `on` all match a `True` default.
    """
    text = CONFIG_PY.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for name, value in _BOOL_DEFAULT.findall(text):
        out[name.upper()] = value.lower()
    for name, value in _STR_DEFAULT.findall(text):
        out[name.upper()] = value
    for name, value in _INT_DEFAULT.findall(text):
        out[name.upper()] = value
    return out


def _as_bool(raw: str) -> bool | None:
    lowered = str(raw).strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return None


def deployed_config(app: str | None, from_json: Path | None) -> dict[str, str]:
    if from_json is not None:
        return json.loads(from_json.read_text(encoding="utf-8"))
    cmd = ["heroku", "config", "--json"]
    if app:
        cmd += ["-a", app]
    return json.loads(
        subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    )


#: Settings whose value is a property of WHERE the code runs, not a decision about what
#: it does. A container path differs from a relative dev path by construction and always
#: will; a production URL is not a deployment "choosing" a different behaviour.
#:
#: The distinction is behaviour versus location, and it is the difference between a tool
#: worth reading and a list worth skimming. `DEFAULT_LLM_PROVIDER` belongs in DELIBERATE
#: because it changes which vendor answers a question. `REPO_CLONE_BASE_DIR` belongs
#: here because it changes nothing except where a clone lands.
ENVIRONMENT_SHAPED = {
    "APP_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "JWT_SECRET",
    "CHROMA_PERSIST_DIR",
    "CUSTOM_RULES_DIR",
    "REPO_CLONE_BASE_DIR",
    "BM25_DATA_DIR",
    "SSH_KNOWN_HOSTS_PATH",
    "BACKUP_DIR",
}


#: Names whose VALUE must never reach stdout. The check is on the name because the
#: value is exactly what must not be looked at to decide. Belt to the braces of the
#: empty-default skip above: a secret that ever acquires a non-empty code default would
#: otherwise be printed by the same line that reports it.
_SECRET_HINT = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "DSN",
    "URL",
    "CREDENTIAL",
    "SALT",
    "SIGNATURE",
)


def mask(key: str, value: str) -> str:
    """Return a value safe to print — the real one, or its shape."""
    if any(hint in key.upper() for hint in _SECRET_HINT):
        return f"<{len(str(value))} chars, hidden>"
    return str(value)


def compare(
    config: dict[str, str], defaults: dict[str, str]
) -> tuple[list, list, list]:
    """(drifted, recorded, unparseable) — each a list of (key, deployed, default)."""
    drifted, recorded, unparseable = [], [], []
    for key, raw in sorted(config.items()):
        if key not in defaults:
            continue
        default = defaults[key]
        # An empty string default is not a default — it is "the environment supplies
        # this", which is how every credential in `config.py` is declared. Comparing a
        # deployed secret against "" reports every one of them as drift AND prints its
        # value; the first run of the widened checker put the Fernet master key, the
        # OpenRouter key and the Redis password on stdout, which is where CI logs live.
        # Absence of a default means the question this tool asks does not apply.
        if default == "" or key in ENVIRONMENT_SHAPED:
            continue
        if default in ("true", "false"):
            parsed = _as_bool(raw)
            if parsed is None:
                # A boolean setting whose value is neither true nor false is worth
                # naming: pydantic will either coerce it or refuse to boot, and both
                # are surprises.
                unparseable.append((key, raw, default))
                continue
            deployed: str = "true" if parsed else "false"
        else:
            deployed = str(raw).strip()
        if deployed == default:
            continue
        (recorded if key in DELIBERATE else drifted).append((key, deployed, default))
    return drifted, recorded, unparseable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", help="Heroku app name (defaults to the git remote's app)")
    ap.add_argument(
        "--from-json", type=Path, help="read config from a JSON file instead"
    )
    ap.add_argument("--quiet", action="store_true", help="print only drift")
    args = ap.parse_args()

    defaults = code_defaults()
    if not defaults:
        print(
            "could not read any bool defaults from backend/app/config.py",
            file=sys.stderr,
        )
        return 2

    try:
        config = deployed_config(args.app, args.from_json)
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        json.JSONDecodeError,
    ) as exc:
        print(f"could not read the deployed config: {exc}", file=sys.stderr)
        return 2

    drifted, recorded, unparseable = compare(config, defaults)

    if not args.quiet:
        print(
            f"{len(defaults)} boolean settings in config.py, {len(config)} vars deployed\n"
        )
        if recorded:
            print("Recorded divergences (decisions, not drift):")
            for key, deployed, default in recorded:
                print(
                    f"  {key:34} deployed={mask(key, deployed):5} code={mask(key, default)}"
                )
                print(f"      {DELIBERATE[key]}")
            print()

    for key, raw, default in unparseable:
        print(
            f"UNPARSEABLE  {key:30} deployed={mask(key, raw)} "
            f"is neither true nor false (code={mask(key, default)})"
        )

    if drifted:
        print("DRIFT — deployed but not recorded as a decision:")
        for key, deployed, default in drifted:
            print(
                f"  {key:34} deployed={mask(key, deployed):5} code={mask(key, default)}"
            )
        print(
            "\nEach of these is either a mistake to unset, or a decision to add to "
            "DELIBERATE in this file with its reason. Leaving it in neither place is "
            "how the last ten got there."
        )
        return 1

    if unparseable:
        return 1
    if not args.quiet:
        print(
            "No drift: every deployed setting matches the code, is recorded above, or is\n"
            "shaped by the environment rather than chosen."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
