"""Validate every pin in sources.json against the public bytes it names.

TWO DIFFERENT FAILURES, REPORTED APART. A pin can be BROKEN (the commit-pinned URL does not
resolve, or the bytes it serves do not hash to the declared sha256) or it can be BEHIND (the pin
still resolves perfectly, but the issuer's default branch has moved past it). Only the first is
a fault in this repo. The second is the normal, expected consequence of someone else shipping,
and it is exactly the signal a human should act on deliberately.

WHY THIS NEVER FIXES ANYTHING. Bumping a pin republishes a public claim, so it stays a reviewed
edit. A job that silently advanced pins would turn the manifest from a promise into a mirror of
whatever main happens to say today, which is the property this whole arc removed.

    python3 suite/check_pins.py           # exit 0 only when every pin is VALID and current
    python3 suite/check_pins.py --pins    # ignore BEHIND; fail only on a BROKEN pin
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "sources.json"
RAW = "https://raw.githubusercontent.com/"


def _parts(entry: dict):
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([0-9a-f]{7,40})/(.+)$",
                 entry["public_url"])
    return m.groups() if m else None


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read(), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def check(entry: dict) -> tuple[str, str]:
    p = _parts(entry)
    if not p:
        return "BROKEN", f"public_url is not pinned to a commit: {entry['public_url']}"
    owner, repo, commit, path = p

    pinned, err = _get(f"{RAW}{owner}/{repo}/{commit}/{path}")
    if pinned is None:
        return "BROKEN", f"pinned url did not resolve ({err})"
    got = hashlib.sha256(pinned).hexdigest()
    if got != entry["sha256"]:
        return "BROKEN", f"pinned bytes hash {got[:12]}, manifest declares {entry['sha256'][:12]}"

    head, err = _get(f"{RAW}{owner}/{repo}/main/{path}")
    if head is None:
        return "VALID", f"pin verified; upstream main unreadable ({err}), drift unknown"
    hh = hashlib.sha256(head).hexdigest()
    if hh != got:
        return "BEHIND", (f"pin verified, but {repo}@main now serves {hh[:12]} "
                          f"(pinned {got[:12]}); a human decides whether to bump")
    return "VALID", f"pin verified and current with {repo}@main"


def main() -> int:
    only_pins = "--pins" in sys.argv
    man = json.loads(MANIFEST.read_text())
    print(f"sources.json manifest_version={man['manifest_version']} "
          f"pinned_as_of={man['pinned_as_of']}  ({len(man['sources'])} sources)\n")

    worst = []
    for e in man["sources"]:
        state, why = check(e)
        owner_repo = e["artifact"].split("/")[0]
        print(f"[{state:6}] {e['panel']}")
        print(f"          claim      {e['label']}")
        print(f"          artifact   {e['artifact']}")
        print(f"          pinned     {owner_repo}@{e['issuer_commit']}")
        print(f"          expected   sha256 {e['sha256']}")
        print(f"          observed   {why}")
        print(f"          derivation {e['derivation']}\n")
        if state == "BROKEN" or (state == "BEHIND" and not only_pins):
            worst.append((e["panel"], state))

    if not worst:
        print("every pin resolves publicly and hashes to its declared sha256.")
        return 0

    print("DRIFT DETECTED: " + ", ".join(f"{n} ({s})" for n, s in worst))
    print("\nThis run does not change anything. To act on it, deliberately:")
    print("  1. review the upstream change and decide whether the claim still holds")
    print("  2. update issuer_commit, sha256 and public_url for that panel in suite/sources.json")
    print("  3. update pinned_as_of")
    print("  4. re-run suite/build.py and commit the regenerated page with a claim receipt")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
