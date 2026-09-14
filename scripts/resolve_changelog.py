#!/usr/bin/env python3
"""Resolve a CHANGELOG conflict where both sides add sections under one heading.

**Why this exists.** Every PR prepends to the same `## [Unreleased]` heading, so the
first one to merge conflicts all the others by construction — with several in flight
that is a guarantee, not a risk, and `CLAUDE.md` says so. Four of them arose in one
afternoon and each was resolved by hand, which is three more hand-resolutions than the
class deserves.

**The checks GATE the write, and that is the whole design.** An earlier version
asserted its result *after* a shell `&&` chain had already committed, and conflict
markers reached the history. This one validates before `write_text` and exits non-zero
so the chain behind it stops. It has refused twice and was right both times: the
`## [Unreleased]` heading sits *above* the conflict in this file, so a resolver that
helpfully adds one produces two.

Usage, after `git merge` reports a CHANGELOG conflict::

    python3 scripts/resolve_changelog.py && git add CHANGELOG.md && git commit --no-edit
"""
import pathlib, re, sys

p = pathlib.Path("CHANGELOG.md")
s = p.read_text()
m = re.search(r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n", s, re.S)
if not m:
    sys.exit("no conflict block found")
merged = m.group(1).strip("\n") + "\n\n" + m.group(2).strip("\n") + "\n\n"
out = s[: m.start()] + merged + s[m.end() :]
head = out.split("Only `<<<<<<< `")[0]
if "<<<<<<< HEAD" in head or ">>>>>>> " in head:
    sys.exit("markers remain — refusing to write")
n = len(re.findall(r"^## \[Unreleased\]$", out, re.M))
if n != 1:
    sys.exit(f"expected one Unreleased heading, found {n} — refusing to write")
p.write_text(out)
print("resolved; checks passed before the write")
