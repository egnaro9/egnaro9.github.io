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

A PANEL MAY DECLARE ITS ROUTINE. model-drift's dashboard/drift_board.json is rewritten every day
by that repo's own probe, so its pin is BEHIND within a day of every bump, and the weekly scheduled
run went red every Monday on news that was not news. A source entry may carry a "routine" rule
naming the one author and commit-message prefix its routine updates use and a max_lag_days. When a
pin is BEHIND and EVERY commit that touched the artifact since the pin matches that rule, and the
oldest of them is within max_lag_days, the state is ROUTINE: reported, not failed. Any other
commit, a history that cannot be read, a pinned commit that cannot be found, or a longer lag is
BEHIND exactly as before. The rule only ever excuses; it never bumps.

    python3 suite/check_pins.py           # exit 0 only when every pin is VALID, current, or ROUTINE
    python3 suite/check_pins.py --pins    # ignore BEHIND; fail only on a BROKEN pin
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "sources.json"
REQUIREMENTS = HERE / "requirements-dev.txt"
SUITE_WORKFLOW = HERE.parent / ".github" / "workflows" / "suite.yml"
REFUSALS = HERE / "refusals.json"
RAW = "https://raw.githubusercontent.com/"
API = "https://api.github.com/"
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


def _get(url: str, attempts: int = 1):
    """Fetch url, returning (bytes, error, http_status).

    http_status is the code the server answered with, and 0 when nothing answered at
    all. The caller needs that difference. A 404 is a durable fact about the artifact,
    a timeout is a passing fact about the network, and collapsing the two is how this
    script spent 2026-08-30 to 2026-09-22 printing VALID for a panel it never managed
    to look at: model-drift's dashboard/metrics.json was renamed upstream, every fetch
    of it 404ed, and "could not look" was recorded as "looked, and it was fine".
    """
    err, code = "", 0
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read(), "", r.status
        except urllib.error.HTTPError as e:
            # The server answered. Retrying will get the same answer, so do not.
            return None, f"HTTPError: {e}", e.code
        except Exception as e:
            err, code = f"{type(e).__name__}: {e}", 0
    return None, err, code


def _get_json(url: str):
    """GitHub API GET, returning (parsed, error). Uses GITHUB_TOKEN when present, because the
    unauthenticated limit is 60 requests an hour and a scheduled runner shares an address."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "egnaro9.github.io/check_pins"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _routine(entry: dict, owner: str, repo: str, path: str, commit: str,
             now: datetime | None = None) -> tuple[bool, str]:
    """(True, why) when the lag behind main is made only of the panel's declared routine
    commits and is within its max_lag_days; (False, why) otherwise. Never raises."""
    rule = entry.get("routine")
    if not isinstance(rule, dict):
        return False, ""
    author, prefix = rule.get("author"), rule.get("message_prefix")
    max_lag = rule.get("max_lag_days")
    if not author or not prefix or not isinstance(max_lag, (int, float)):
        return False, "routine rule is incomplete, so it excuses nothing"
    url = (f"{API}repos/{owner}/{repo}/commits?sha=main&per_page=100&path="
           f"{urllib.parse.quote(path)}")
    data, err = _get_json(url)
    if not isinstance(data, list):
        return False, f"routine rule not applied: commit history unreadable ({err or 'not a list'})"
    since = []
    for c in data:
        if str(c.get("sha", "")).startswith(commit):
            break
        since.append(c)
    else:
        return False, (f"routine rule not applied: the pinned commit {commit} is not among the "
                       f"last {len(data)} commits touching {path}")
    if not since:
        return False, "routine rule not applied: main's bytes differ but no commit since the pin touched the artifact"
    for c in since:
        cm = c.get("commit") or {}
        who = (cm.get("author") or {}).get("name", "")
        msg = cm.get("message", "")
        if who != author or not msg.startswith(prefix):
            return False, (f"not routine: {str(c.get('sha', ''))[:7]} by {who!r} "
                           f"({msg.splitlines()[0][:60] if msg else 'no message'!r}) is not a declared routine update")
    dates = [(c.get("commit") or {}).get("committer", {}).get("date", "") for c in since]
    try:
        oldest = min(datetime.fromisoformat(d.replace("Z", "+00:00")) for d in dates)
    except ValueError:
        return False, "routine rule not applied: a commit date could not be read"
    lag = ((now or datetime.now(timezone.utc)) - oldest).total_seconds() / 86400
    if lag > max_lag:
        return False, (f"{len(since)} routine update(s), but the oldest is {lag:.1f} days old, past "
                       f"max_lag_days {max_lag}: bump the pin")
    return True, (f"{len(since)} routine update(s) since the pin, oldest {lag:.1f} days old, within "
                  f"max_lag_days {max_lag}")


def check(entry: dict) -> tuple[str, str]:
    p = _parts(entry)
    if not p:
        return "BROKEN", f"public_url is not pinned to a commit: {entry['public_url']}"
    owner, repo, commit, path = p

    pinned, err, _ = _get(f"{RAW}{owner}/{repo}/{commit}/{path}")
    if pinned is None:
        return "BROKEN", f"pinned url did not resolve ({err})"
    got = hashlib.sha256(pinned).hexdigest()
    if got != entry["sha256"]:
        # Both in full, and the declaring file by name. Cut to 12 characters, a pin that differs
        # in its last nibble printed two identical hashes under BROKEN, and "manifest" named
        # sources.json even when the value came from refusals.json.
        where = entry.get("declared_in", f"suite/{MANIFEST.name}")
        return "BROKEN", f"pinned bytes hash {got}, {where} declares {entry['sha256']}"

    # Two attempts, because a single transient failure should not be reported as a
    # finding about the artifact. A 404 short-circuits inside _get and is not retried.
    head, err, code = _get(f"{RAW}{owner}/{repo}/main/{path}", attempts=2)
    if head is None:
        if code == 404:
            return "UNMEASURED", (
                f"pin verified, but {repo}@main no longer serves {path} (HTTP 404). "
                "The artifact was renamed or removed upstream, so there is nothing to "
                "compare the pin against and this panel has had no drift coverage since "
                "it moved. Find where the artifact went and repoint public_url, or drop "
                "the panel.")
        return "UNMEASURED", (
            f"pin verified, but {repo}@main could not be read after 2 attempts ({err}); "
            "drift was NOT measured on this run")
    hh = hashlib.sha256(head).hexdigest()
    if hh != got:
        ok, why = _routine(entry, owner, repo, path, commit)
        if ok:
            return "ROUTINE", (f"pin verified; {repo}@main now serves {hh[:12]} (pinned "
                               f"{got[:12]}), and the lag is routine: {why}")
        return "BEHIND", (f"pin verified, but {repo}@main now serves {hh[:12]} "
                          f"(pinned {got[:12]}); a human decides whether to bump"
                          + (f". {why}" if why else ""))
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
        print(f"[{state:10}] {e['panel']}")
        print(f"          claim      {e['label']}")
        print(f"          artifact   {e['artifact']}")
        print(f"          pinned     {owner_repo}@{e['issuer_commit']}")
        print(f"          expected   sha256 {e['sha256']}")
        print(f"          observed   {why}")
        print(f"          derivation {e['derivation']}\n")
        # UNMEASURED sorts with BEHIND rather than BROKEN, for the reason BEHIND is
        # already excused here: the pin itself resolves and hashes, so a pull request
        # that never touched this panel should not fail on it. It is still a finding,
        # and the scheduled job says so out loud.
        if state == "BROKEN" or (state in ("BEHIND", "UNMEASURED") and not only_pins):
            worst.append((e["panel"], state))

    if not worst:
        print("every pin resolves publicly and hashes to its declared sha256.")
        return 0

    print("DRIFT DETECTED: " + ", ".join(f"{n} ({s})" for n, s in worst))
    if any(s == "UNMEASURED" for _, s in worst):
        print("\nUNMEASURED is not a milder BEHIND. It means this run could not compare the")
        print("pin to anything, so that panel's drift is unknown rather than absent. A 404")
        print("says the artifact is no longer at the path public_url names; find where it")
        print("went, then repoint the panel or retire it.")
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
