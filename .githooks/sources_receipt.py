"""Claim-gate check for suite/sources.json, the file that defines public source provenance.

WHY THIS FILE GETS ITS OWN CHECK. Every other claim-bearing file is prose or a generated page,
and a receipt pointing at an artifact is enough. sources.json is different: editing one hex
string here silently republishes a different public number. A prose receipt saying "bumped the
pin, verified upstream" is exactly the kind of note this gate exists to distrust, so nothing
here is taken on the receipt's word. The hook re-fetches the new pinned URL and hashes it.

THE FORMATTING EXEMPTION IS NARROW ON PURPOSE. Reordering entries or reflowing the file changes
no claim, so it needs no receipt. That decision is made by comparing the semantic tuples, not by
diffing text: if the (panel, artifact, issuer_commit, sha256, public_url, derivation) set is
identical, nothing a reader can see has moved. Anything else, including a new or removed panel,
requires a receipt naming the panel and both commits.

    <path> :: PIN <panel> <old_commit7>-><new_commit7>
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET = "suite/sources.json"
KEYS = ("panel", "artifact", "issuer_commit", "sha256", "public_url", "derivation")


def _git(*a) -> bytes | None:
    p = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def _tuples(raw: bytes | None) -> dict:
    if raw is None:
        return {}
    try:
        doc = json.loads(raw)
    except Exception:
        return {}
    return {e["panel"]: tuple(e.get(k, "") for k in KEYS) for e in doc.get("sources", [])}


def _fetch(url: str):
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([0-9a-f]{7,40})/(.+)$", url)
    if not m:
        return None, "public_url is not pinned to a commit"
    o, r, c, p = m.groups()
    try:
        with urllib.request.urlopen(
                f"https://raw.githubusercontent.com/{o}/{r}/{c}/{p}", timeout=30) as resp:
            return resp.read(), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    staged = _git("show", f":{TARGET}")
    if staged is None:
        return 0

    before, after = _tuples(_git("show", f"HEAD:{TARGET}")), _tuples(staged)
    if before == after:
        return 0  # formatting or order only: no claim moved

    changed = sorted({p for p in set(before) | set(after) if before.get(p) != after.get(p)})
    ack = (REPO / ".claim-review-ack")
    lines = ack.read_text().splitlines() if ack.exists() else []
    doc = json.loads(staged)
    entries = {e["panel"]: e for e in doc["sources"]}

    known = set()
    try:
        sys.path.insert(0, str(REPO / "suite"))
        import build as _b  # noqa: E402
        known = set(_b.DERIVATIONS)
    except Exception:
        pass

    problems = []
    for panel in changed:
        e = entries.get(panel)
        if e is None:
            problems.append(f"{panel}: removed from the manifest; record why in a PIN receipt")
            continue
        old = (before.get(panel) or ("", "", "", "", "", ""))[2] or "none"
        new = e["issuer_commit"]
        want = f"PIN {panel} {old[:7]}->{new[:7]}"
        if not any(l.strip().startswith(f"{TARGET} ::") and want in l for l in lines):
            problems.append(f"{panel}: no receipt line. Add:\n"
                            f"      {TARGET} :: {want}")
            continue
        raw, err = _fetch(e["public_url"])
        if raw is None:
            problems.append(f"{panel}: new pinned url did not resolve ({err})")
            continue
        got = hashlib.sha256(raw).hexdigest()
        if got != e["sha256"]:
            problems.append(f"{panel}: pinned bytes hash {got[:12]}, manifest declares "
                            f"{e['sha256'][:12]}. The receipt is not the evidence; these bytes are.")
            continue
        if known and e["derivation"] not in known:
            problems.append(f"{panel}: derivation {e['derivation']!r} is not implemented in "
                            f"suite/build.py ({sorted(known)})")

    also = (_git("diff", "--cached", "--name-only", "--diff-filter=ACMR") or b"").decode().split()
    if not problems and "suite/index.html" not in also:
        problems.append("suite/index.html is not staged. A pin moved, so the generated page must "
                        "be rebuilt and committed with it: run python3 suite/build.py")

    if problems:
        print("claim gate: suite/sources.json changed a public claim.", file=sys.stderr)
        print(f"\nPanels whose provenance moved: {', '.join(changed)}\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nA PIN receipt records the decision; this hook independently re-fetches the new\n"
              "pinned URL and hashes it, so a receipt alone cannot pass a claim.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
