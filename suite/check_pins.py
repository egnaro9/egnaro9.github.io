"""Validate every pin in sources.json, and the verifier pin, against the public bytes each names.

The verifier pin is the vac-protocol commit in requirements-dev.txt and suite.yml together with
the verify.py sha256 recorded in refusals.json (see verifier_pin()).

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
REQUIREMENTS = HERE / "requirements-dev.txt"
SUITE_WORKFLOW = HERE.parent / ".github" / "workflows" / "suite.yml"
REFUSALS = HERE / "refusals.json"
RAW = "https://raw.githubusercontent.com/"
_VAC_REQ = re.compile(r"vac-protocol\s*@\s*git\+https://github\.com/egnaro9/vac-protocol@([0-9a-f]+)")
_VAC_CHECKOUT = re.compile(r"repository:\s*egnaro9/vac-protocol\s*,\s*ref:\s*([0-9a-f]+)")


def verifier_pin() -> tuple[dict, str]:
    """The verifier the browser port was derived from, checked like a panel pin.

    It is not in sources.json because it is not a panel, and until this existed nothing weekly
    read it at all: the port's refusal table could fall any number of commits behind vac-protocol
    and every job stayed quiet. It is spread over three files that have to agree, and nothing else
    checks that they do. requirements-dev.txt installs vac-verify from a commit, suite.yml checks
    the same repository out at a commit for the tests and runner.py, and refusals.json records the
    sha256 of the verify.py its table was parsed from.

    Returns (entry, fault). A non-empty fault is BROKEN without fetching anything."""
    reqs = _VAC_REQ.findall(REQUIREMENTS.read_text(encoding="utf-8"))
    outs = _VAC_CHECKOUT.findall(SUITE_WORKFLOW.read_text(encoding="utf-8"))
    derived = json.loads(REFUSALS.read_text(encoding="utf-8")).get("derived_from", {})
    commit = reqs[0] if len(reqs) == 1 else ""
    entry = {
        "panel": "vac-verify (the browser port's refusal table)",
        "label": "Reference verifier that suite/refusals.json was derived from",
        "artifact": f"vac-protocol/{derived.get('path', '?')}",
        "issuer_commit": commit[:12] or "?",
        "sha256": derived.get("sha256", ""),
        "public_url": f"https://github.com/egnaro9/vac-protocol/blob/{commit}/vac/verify.py",
        "derivation": "suite/refusals.py, derived_from in suite/refusals.json",
        "declared_in": f"suite/{REFUSALS.name} derived_from.sha256",
    }
    fault = ""
    if len(reqs) != 1 or len(outs) != 1:
        fault = (f"expected one vac-protocol commit in each of {REQUIREMENTS.name} and "
                 f"{SUITE_WORKFLOW.name}, found {len(reqs)} and {len(outs)}")
    elif any(len(c) != 40 for c in (*reqs, *outs)):
        fault = ("a vac-protocol pin is not a full 40-character sha; actions/checkout resolves "
                 "anything shorter as a branch or tag")
    elif reqs[0] != outs[0]:
        fault = (f"{REQUIREMENTS.name} installs vac-verify from {reqs[0][:12]} but "
                 f"{SUITE_WORKFLOW.name} checks out {outs[0][:12]}; the tests would run one "
                 "commit's verifier over another commit's fixtures")
    elif derived.get("path") != "vac/verify.py":
        fault = f"{REFUSALS.name} derived_from names {derived.get('path')!r}, not vac/verify.py"
    return entry, fault


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
        # Both in full, and the declaring file by name. Cut to 12 characters, a pin that differs
        # in its last nibble printed two identical hashes under BROKEN, and "manifest" named
        # sources.json even when the value came from refusals.json.
        where = entry.get("declared_in", f"suite/{MANIFEST.name}")
        return "BROKEN", f"pinned bytes hash {got}, {where} declares {entry['sha256']}"

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
          f"pinned_as_of={man['pinned_as_of']}  ({len(man['sources'])} sources, "
          "plus the verifier pin)\n")

    worst = []
    for e, fault in [*((s, "") for s in man["sources"]), verifier_pin()]:
        state, why = ("BROKEN", fault) if fault else check(e)
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
    print("For the verifier pin, steps 2 to 4 are instead: move the vac-protocol commit in")
    print("suite/requirements-dev.txt and .github/workflows/suite.yml together, then re-run")
    print("suite/refusals.py, suite/build.py and suite/runner.py against a HOME checked out at")
    print("suite.yml's refs, and commit what they wrote.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
