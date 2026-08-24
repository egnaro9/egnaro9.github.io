"""The single boundary between evidence on disk and a claim on the page.

WHY A GATE AND NOT A READ. Every other artifact this console shows is read straight from a sibling
checkout, so the page silently follows whatever is there. That is acceptable for a number the page
already frames as recorded. It is not acceptable for the invocation claim, because upgrading that
claim is a publication decision and an artifact changing in another repository is not one. The
manifest is the decision; the checkout is byte transport.

FAIL CLOSED, WITH NO FALLBACK IN THE CODE. There is deliberately no branch here that returns a
degraded result. A caller either receives an accepted artifact or an exception. A gate with a
quiet path is the failure this whole project keeps finding: a check that cannot distinguish
"looked and it was fine" from "never looked".

ONE COMPARISON POLICY FOR VERSIONS. The gate never hard-codes a library version. The manifest
declares the intent, the artifact states the observed fact, and the gate requires them equal.
gradecore 0.10.1 shipped reporting itself as 0.10.0 because two hand-maintained copies of a
version drifted; adding a third literal here would rebuild that defect on the consumer side.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import urllib.request

HOME = pathlib.Path.home()
MANIFEST = pathlib.Path(__file__).resolve().parent / "witness.manifest.json"

_REQUIRED_STAMP = ("issuer_commit", "code_paths", "dirty", "rule")


class WitnessRejected(Exception):
    """The evidence is not publishable. Never caught to produce a weaker page."""


def _reject(field: str, expected, observed) -> None:
    raise WitnessRejected(
        f"{field}: expected {expected!r}, observed {observed!r}. The console publishes an "
        f"invocation claim only from the pinned artifact, so this stops the build rather than "
        f"weakening the claim.")


def _check_url_agrees(m: dict) -> None:
    """A manifest can be internally plausible and mutually inconsistent.

    The url is the only field a reader can act on, so a url pointing at a different repo, commit
    or path than the fields beside it would send them to evidence this build never saw."""
    u = m.get("public_url", "")
    parsed = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([0-9a-f]{7,40})/(.+)$", u)
    if not parsed:
        _reject("public_url", "a github blob url pinned to a commit", u)
    owner, repo, commit, path = parsed.groups()
    art = m["artifact"]
    if not art.startswith(repo + "/"):
        _reject("public_url repo", f"{art.split('/')[0]!r} to match artifact path", repo)
    if path != art.split("/", 1)[1]:
        _reject("public_url path", art.split("/", 1)[1], path)

    # The url is addressed at pinned_commit, NOT issuer_commit. issuer_commit is the code state
    # the run was stamped at; the artifact is committed afterwards, so its bytes live in a later
    # tree. Checking the url against issuer_commit sent readers to a commit where this file did
    # not yet hold these bytes, and the mismatch was invisible because nothing fetched it.
    pin = m.get("pinned_commit")
    if not pin:
        _reject("manifest.pinned_commit", "present", "absent")
    if not commit.startswith(pin) and not pin.startswith(commit):
        _reject("public_url commit", pin, commit)



def _check_url_serves_declared_bytes(m: dict) -> None:
    """Fetch the pinned url and hash what it serves.

    FIELD AGREEMENT IS NOT VERIFICATION. Every field can agree perfectly while the url serves
    different bytes than the sha256 beside it, which is exactly what happened: the page printed
    779b0b56 next to a link resolving to 62834d45, because the url was addressed at issuer_commit
    instead of the commit that holds the artifact. Nothing fetched it, so nothing noticed.

    This runs LAST, after every local check. A reader who clicks the link and hashes it is running
    this by hand; running it earlier would mask a local failure behind a network one.
    """
    owner, repo, commit, path = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([0-9a-f]{7,40})/(.+)$", m["public_url"]).groups()
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(raw, timeout=30) as r:
            served = hashlib.sha256(r.read()).hexdigest()
    except Exception as e:
        _reject("public_url fetch", f"readable at {raw}", f"{type(e).__name__}: {e}")
    if served != m["sha256"]:
        _reject("public_url bytes", f"sha256 {m['sha256']}", f"sha256 {served} served by {raw}")


def accept(manifest_path: pathlib.Path | None = None, home: pathlib.Path | None = None) -> dict:
    """Return the accepted artifact, or raise. There is no third outcome."""
    home = home or HOME
    mp = manifest_path or MANIFEST
    try:
        m = json.loads(mp.read_text())
    except Exception as e:
        raise WitnessRejected(f"manifest unreadable at {mp}: {type(e).__name__}: {e}") from None

    for k in ("artifact", "sha256", "protocol", "library", "issuer_commit", "public_url"):
        if k not in m:
            _reject(f"manifest.{k}", "present", "absent")
    _check_url_agrees(m)

    path = home / m["artifact"]
    try:
        raw = path.read_bytes()
    except Exception:
        _reject("artifact", f"readable at {path}", "missing")

    got = hashlib.sha256(raw).hexdigest()
    if got != m["sha256"]:
        _reject("sha256", m["sha256"], got)

    try:
        a = json.loads(raw)
    except Exception as e:
        raise WitnessRejected(f"artifact is not JSON: {type(e).__name__}: {e}") from None

    wp = a.get("witness_protocol")
    if not isinstance(wp, dict):
        _reject("witness_protocol", "an object", type(wp).__name__)
    if wp.get("protocol") != m["protocol"]:
        _reject("protocol", m["protocol"], wp.get("protocol"))

    libs = wp.get("libraries") or []
    want = {"name": m["library"]["name"], "version": m["library"]["version"]}
    if want not in libs:
        _reject("library", want, libs)

    stamp = wp.get("stamp")
    if not isinstance(stamp, dict):
        _reject("stamp", "an object", type(stamp).__name__)
    for k in _REQUIRED_STAMP:
        if k not in stamp:
            _reject(f"stamp.{k}", "present", "absent")
    if not isinstance(stamp["code_paths"], list) or not stamp["code_paths"]:
        _reject("stamp.code_paths", "a non-empty list", stamp["code_paths"])
    if not isinstance(stamp["rule"], str) or not stamp["rule"].strip():
        _reject("stamp.rule", "a non-empty string", stamp["rule"])
    if stamp["dirty"] is not False:
        _reject("stamp.dirty", False, stamp["dirty"])
    if stamp["issuer_commit"] != m["issuer_commit"]:
        _reject("stamp.issuer_commit", m["issuer_commit"], stamp["issuer_commit"])

    rc = wp.get("row_counts") or {}
    if rc.get("incomplete") != 0:
        _reject("row_counts.incomplete", 0, rc.get("incomplete"))

    rows = a.get("results") or []
    unattributed = sum((r.get("witness") or {}).get("unattributed_calls") or 0 for r in rows)
    if unattributed != 0:
        _reject("unattributed invocation calls", 0, unattributed)

    _reconcile(a)
    _check_url_serves_declared_bytes(m)
    return a


def _reconcile(a: dict) -> None:
    """Rebuild every headline count from the raw upstream returns alone.

    Not a re-read of the tally. The point is that the numbers the page will show are recomputable
    from the evidence rather than asserted beside it, so a tally edited by hand cannot pass."""
    counts = {"caught": 0, "missed": 0, "flagged": 0}
    for r in rows_witnessed(a):
        raw = [x for x in r["witness"]["defect_decision"]["raw_upstream"] if x.get("kind") == "return"]
        if not raw:
            _reject(f"raw_upstream for {r.get('case_name')}/{r.get('operator_id')}",
                    "at least one recorded return", "none")
        passed = bool(raw[-1].get("passed"))
        defect = r.get("polarity") == "defect"
        outcome = "caught" if (defect != passed) else ("missed" if defect else "flagged")
        if outcome != r.get("outcome"):
            _reject(f"outcome for {r.get('case_name')}/{r.get('operator_id')}",
                    outcome, r.get("outcome"))
        counts[outcome] += 1
    t = a.get("tally") or {}
    for k, v in counts.items():
        if t.get(k) != v:
            _reject(f"tally.{k} recomputed from raw returns", v, t.get(k))


def rows_witnessed(a: dict) -> list:
    return [r for r in (a.get("results") or []) if r.get("witness_status") == "WITNESSED"]


def headline(a: dict) -> dict:
    """The only values the console may render for the invocation claim."""
    t = a["tally"]
    applied = t["caught"] + t["missed"] + t["flagged"]
    wp = a["witness_protocol"]
    return {"caught": t["caught"], "missed": t["missed"], "applied": applied,
            "not_applicable": t["na"], "incomplete": t["incomplete"],
            "rows": wp["row_counts"]["rows"],
            "score": a["score"], "scored": applied > 0,
            "protocol": wp["protocol"], "library": wp["libraries"],
            "issuer_commit": wp["stamp"]["issuer_commit"],
            "sha256": json.loads(MANIFEST.read_text())["sha256"],
            "public_url": json.loads(MANIFEST.read_text())["public_url"]}
