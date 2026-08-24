"""Differential conformance harness: browser verifier vs. Python reference.

The only thing this file computes is a COMPARISON. It never decides whether a
bundle is honest -- it runs `vac-verify` (the reference) and `bv_harness.js`
(the browser port, under node) over the same bytes on disk and diffs what came
back. If it re-implemented a check, it would be grading one of my
implementations against another.

Three corpora, all materialised to real directories so both verifiers read
identical bytes:

  whole    the 22 fixtures + examples/outsider, exactly as committed.
  sliced   the same bundles with the profiles the browser port does not
           implement (modeldrift-board-v1, crashkit-variance-v1) removed,
           along with the evidence only those checks read and the summary
           subtree only those checks recompute. Without this the port abstains
           on 21 of 23 bundles and the comparison proves nothing.
  derived  minimal edits that provoke refusal classes no fixture reaches.

A run where the browser port abstains (INCOMPLETE) is NOT a match. It is
recorded as EXPECTED-DIVERGENT with the reason it abstained, and it is still
held to a floor: every refusal it did emit must be an ordered subsequence of
the reference's, so an abstaining run cannot smuggle in an invented refusal.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

VAC_ROOT = pathlib.Path("/Users/lonimua/vac-protocol")
SUITE = pathlib.Path(__file__).resolve().parent.parent
# Resolve from PATH first, exactly as runner.py and the other suite tests do. Hardcoding a
# .venv inside a sibling repo made all 16 conformance tests skip in CI while passing on a
# machine that happened to have that layout, so the two verifier implementations were only
# ever compared where it was least necessary.
VAC_VERIFY = pathlib.Path(shutil.which("vac-verify") or VAC_ROOT / ".venv" / "bin" / "vac-verify")
HARNESS = SUITE / "bv_harness.js"
REFUSALS_JSON = SUITE / "refusals.json"

# Profiles the browser port declares it does not implement. Named here so a
# port that quietly starts abstaining on a THIRD profile shows up as a
# mismatch instead of being absorbed as "expected".
UNPORTED_PROFILES = {"modeldrift-board-v1", "crashkit-variance-v1"}

# Refusal classes that cannot be reached by a directory bundle at all, with the
# reason. These are reported as NO COVERAGE, never as agreement.
UNREACHABLE = {
    "unsafe-archive": (
        "tar path only: fires while unpacking a .tar.gz. A directory bundle "
        "never enters that code path in either implementation."
    ),
}

MATCH = "MATCH"
DIVERGENT = "EXPECTED-DIVERGENT"
MISMATCH = "MISMATCH"


# ---------------------------------------------------------------- the two runs
def reference_verify(path: pathlib.Path) -> dict:
    """Run the Python reference verifier."""
    r = subprocess.run(
        [str(VAC_VERIFY), str(path)], capture_output=True, text=True,
    )
    lines = [ln[len("FAIL "):] for ln in r.stdout.splitlines()
             if ln.startswith("FAIL ")]
    return {
        "verdict": "PASS" if r.returncode == 0 else "FAIL",
        "exit": r.returncode,
        "lines": lines,
        "names": [ln.split(":", 1)[0] for ln in lines],
        "stderr": r.stderr.strip(),
    }


def browser_verify(path: pathlib.Path) -> dict:
    """Run the browser verifier's own code under node, over the same bytes."""
    r = subprocess.run(
        ["node", str(HARNESS), "verify", str(path)],
        capture_output=True, text=True, cwd=str(SUITE),
    )
    if r.returncode != 0:
        return {"verdict": "ERROR", "lines": [], "names": [], "unported": [],
                "error": (r.stderr.strip() or r.stdout.strip())[:2000]}
    d = json.loads(r.stdout)
    lines = list(d["failures"])
    return {
        "verdict": d["verdict"],
        "lines": lines,
        "names": [ln.split(":", 1)[0] for ln in lines],
        "unported": list(d.get("unported") or []),
        "ran": list(d.get("ran") or []),
        "error": None,
    }


# ------------------------------------------------------------------- the slice
def _listed_paths(m: dict) -> set:
    return {e["path"] for e in (m.get("evidence") or [])
            if isinstance(e, dict) and isinstance(e.get("path"), str)}


def _check_refs(check, listed: set) -> set:
    if not isinstance(check, dict):
        return set()
    return {v for v in check.values() if isinstance(v, str) and v in listed}


def slice_unported(src: pathlib.Path, dest: pathlib.Path):
    """Write `src` to `dest` with unported-profile checks removed.

    Returns None when the bundle declares no unported profile (nothing to
    slice), otherwise a dict describing what was dropped.

    Removing a check is not enough on its own: the reference refuses a bundle
    whose evidence no check reads (`evidence-unchecked`) and whose summary
    declares a number no check recomputes (`summary-outruns-checks`). So the
    evidence read ONLY by dropped checks is dropped with them, and the summary
    subtree those checks own goes too. Artifacts still referenced by a
    surviving check are kept, hashes untouched.
    """
    m = json.loads((src / "vac.json").read_text())
    results = m.get("results") or {}
    checks = results.get("checks") or []
    listed = _listed_paths(m)

    # filter by identity, not equality: two byte-identical check objects must
    # not both vanish because one of them named an unported profile
    drop_ids = {id(c) for c in checks
                if isinstance(c, dict) and c.get("profile") in UNPORTED_PROFILES}
    if not drop_ids:
        return None
    dropped = [c for c in checks if id(c) in drop_ids]
    kept = [c for c in checks if id(c) not in drop_ids]

    kept_refs = set().union(*[_check_refs(c, listed) for c in kept]) if kept else set()
    dropped_refs = set().union(*[_check_refs(c, listed) for c in dropped])
    orphaned = sorted(dropped_refs - kept_refs)

    m["evidence"] = [e for e in m["evidence"] if e["path"] not in orphaned]
    results["checks"] = kept
    summary = results.get("summary")
    dropped_summary = []
    if isinstance(summary, dict) and "drift" in summary:
        # the modeldrift board is the only check that recomputes summary.drift
        dropped_summary = ["drift"]
        results["summary"] = {k: v for k, v in summary.items() if k != "drift"}

    dest.mkdir(parents=True, exist_ok=True)
    for e in m["evidence"]:
        s, d = src / e["path"], dest / e["path"]
        if s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    (dest / "vac.json").write_text(json.dumps(m, indent=2) + "\n")
    return {
        "profiles": [c.get("profile") for c in dropped],
        "evidence": orphaned,
        "summary_keys": dropped_summary,
    }


# ----------------------------------------------------------------- the corpora
def bundle_paths() -> list:
    """examples/outsider plus every fixture directory (make_fixtures.py is
    a generator script, not a bundle)."""
    fixtures = sorted(p for p in (VAC_ROOT / "fixtures").iterdir() if p.is_dir())
    return [VAC_ROOT / "examples" / "outsider"] + fixtures


def _edit(dest: pathlib.Path, fn):
    m = json.loads((dest / "vac.json").read_text())
    if fn(dest, m) is not False:
        (dest / "vac.json").write_text(json.dumps(m, indent=2) + "\n")


def _d_missing_manifest(d, m):
    (d / "vac.json").unlink()
    return False


def _d_invalid_json(d, m):
    (d / "vac.json").write_text('{\n "claim": 1,\n bad\n}\n')
    return False


def _d_invalid_utf8(d, m):
    (d / "vac.json").write_bytes(b'{"vac_version": "0.1", "x": "\xff\xfe"}')
    return False


def _d_utf8_bom(d, m):
    """A leading U+FEFF. This case exists because its absence hid a false green.

    TextDecoder('utf-8', {fatal: true}) defaults ignoreBOM to false, which SILENTLY STRIPS a
    leading BOM, while Python's read_text() refuses it. The browser returned PASS on a bundle the
    reference verifier refused, and the whole conformance suite stayed green because not one of
    the 23 committed bundles, their per-profile slices, or the derived cases carried a BOM. A
    corpus with no instance of a difference cannot detect that difference."""
    (d / "vac.json").write_bytes(b"\xef\xbb\xbf" + (d / "vac.json").read_bytes())
    return False


def _d_schema_violation(d, m):
    m["vac_version"] = "9.9"


def _d_unknown_profile(d, m):
    m["results"]["checks"][0]["profile"] = "not-a-real-profile-v1"


def _d_duplicate_artifact(d, m):
    m["evidence"].append(dict(m["evidence"][0]))


def _d_unlisted_file(d, m):
    (d / "evidence" / "stray.txt").write_text("not in the manifest\n")
    return False


def _d_check_artifact_not_listed(d, m):
    m["results"]["checks"][0]["artifact"] = "evidence/nowhere.json"


def _d_issuer_commit_mismatch(d, m):
    m["replay"]["issuer_commit"] = "deadbee"


DERIVED = [
    ("missing-manifest", _d_missing_manifest, "vac.json removed"),
    ("invalid-json", _d_invalid_json, "manifest is not parseable JSON"),
    ("invalid-utf8", _d_invalid_utf8, "manifest holds invalid UTF-8"),
    ("utf8-bom", _d_utf8_bom, "manifest carries a leading UTF-8 BOM"),
    ("schema-violation", _d_schema_violation, "vac_version bumped to 9.9"),
    ("unknown-profile", _d_unknown_profile, "checks[0].profile renamed"),
    ("duplicate-artifact", _d_duplicate_artifact, "evidence[0] listed twice"),
    ("unlisted-file", _d_unlisted_file, "stray file added under evidence/"),
    ("check-artifact-not-listed", _d_check_artifact_not_listed,
     "checks[0].artifact points outside the evidence list"),
    ("issuer-commit-mismatch", _d_issuer_commit_mismatch,
     "replay.issuer_commit diverges from protocol.issuer_commit"),
]


def build_corpus(tmp: pathlib.Path) -> list:
    """Materialise every case. Each entry is (family, name, path, note)."""
    cases = []
    for p in bundle_paths():
        cases.append(("whole", p.name, p, "committed bytes, unmodified"))

    sliced_root = tmp / "sliced"
    for p in bundle_paths():
        dest = sliced_root / p.name
        info = slice_unported(p, dest)
        if info is None:
            continue
        note = ("dropped %s; evidence %s; summary %s"
                % (", ".join(info["profiles"]),
                   ", ".join(info["evidence"]) or "(none)",
                   ", ".join(info["summary_keys"]) or "(none)"))
        cases.append(("sliced", p.name, dest, note))

    # derived cases are built on a sliced clean bundle so the browser port can
    # run to completion and actually be compared
    base = tmp / "derived" / "_base"
    if slice_unported(VAC_ROOT / "fixtures" / "valid", base) is None:
        raise RuntimeError("fixtures/valid no longer declares an unported profile")
    for name, fn, note in DERIVED:
        dest = tmp / "derived" / name
        shutil.copytree(base, dest)
        _edit(dest, fn)
        cases.append(("derived", name, dest, note))
    return cases


# -------------------------------------------------------------- the comparison
def _is_ordered_subsequence(small, big) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def compare(ref: dict, js: dict) -> dict:
    """Classify one case. Returns status plus everything needed to explain it."""
    detail_exact = ref["lines"] == js["lines"]
    names_exact = ref["names"] == js["names"]

    if js["verdict"] == "ERROR":
        return {"status": MISMATCH, "reason": "browser verifier crashed: "
                + js.get("error", ""), "names_exact": False,
                "detail_exact": False}

    if js["verdict"] == "INCOMPLETE":
        unported = js.get("unported") or []
        if not unported:
            return {"status": MISMATCH,
                    "reason": "abstained (INCOMPLETE) without naming an "
                              "unported profile",
                    "names_exact": names_exact, "detail_exact": detail_exact}
        stray = [p for p in unported if p not in UNPORTED_PROFILES]
        if stray:
            return {"status": MISMATCH,
                    "reason": "abstained on profile(s) not on the declared "
                              "unported list: " + ", ".join(stray),
                    "names_exact": names_exact, "detail_exact": detail_exact}
        # floor: an abstaining run may emit FEWER refusals, never different
        # ones and never in a different order.
        if not _is_ordered_subsequence(js["names"], ref["names"]):
            return {"status": MISMATCH,
                    "reason": "abstaining run emitted refusals that are not an "
                              "ordered subsequence of the reference's: "
                              f"browser={js['names']} reference={ref['names']}",
                    "names_exact": names_exact, "detail_exact": detail_exact}
        emitted = [ln for ln in js["lines"] if ln not in ref["lines"]]
        if emitted:
            return {"status": MISMATCH,
                    "reason": "abstaining run emitted a refusal line the "
                              "reference never produced: " + emitted[0],
                    "names_exact": names_exact, "detail_exact": detail_exact}
        return {"status": DIVERGENT,
                "reason": "browser port does not implement "
                          + ", ".join(unported)
                          + "; the bundle declares it, so the port abstains "
                            "rather than return a verdict it did not earn "
                            f"(withheld {len(ref['names']) - len(js['names'])} "
                            "of the reference's refusals)",
                "names_exact": names_exact, "detail_exact": detail_exact}

    js_verdict = {"REFUSED": "FAIL", "PASS": "PASS"}.get(js["verdict"],
                                                         js["verdict"])
    if js_verdict != ref["verdict"]:
        return {"status": MISMATCH,
                "reason": f"verdict: reference={ref['verdict']} "
                          f"browser={js['verdict']}",
                "names_exact": names_exact, "detail_exact": detail_exact}
    if not names_exact:
        return {"status": MISMATCH,
                "reason": f"ordered refusals: reference={ref['names']} "
                          f"browser={js['names']}",
                "names_exact": False, "detail_exact": detail_exact}
    return {"status": MATCH, "reason": "", "names_exact": True,
            "detail_exact": detail_exact}


def run_conformance(tmp: pathlib.Path) -> dict:
    cases = build_corpus(tmp)
    records = []
    for family, name, path, note in cases:
        ref = reference_verify(path)
        js = browser_verify(path)
        verdict = compare(ref, js)
        records.append({
            "family": family, "name": name, "note": note,
            "path": str(path),
            "ref_verdict": ref["verdict"], "ref_names": ref["names"],
            "ref_lines": ref["lines"],
            "js_verdict": js["verdict"], "js_names": js["names"],
            "js_lines": js["lines"], "js_unported": js.get("unported") or [],
            **verdict,
        })
    return {"records": records, "coverage": coverage(records)}


def coverage(records: list) -> dict:
    """Which refusal classes were actually compared in a run the browser
    carried to completion. A class only seen in an abstaining run is NOT
    covered -- the port never rendered a verdict on it."""
    spec = json.loads(REFUSALS_JSON.read_text())
    all_classes = [r["name"] for r in spec["refusals"]]
    tested = {}
    for rec in records:
        if rec["status"] != MATCH:
            continue
        for n in set(rec["ref_names"]):
            tested.setdefault(n, []).append(f"{rec['family']}/{rec['name']}")
    seen_abstaining = set()
    for rec in records:
        if rec["status"] == DIVERGENT:
            seen_abstaining |= set(rec["ref_names"])
    uncovered = [c for c in all_classes if c not in tested]
    return {
        "all_classes": all_classes,
        "tested": tested,
        "uncovered": uncovered,
        "uncovered_reasons": {
            c: UNREACHABLE.get(
                c,
                "no corpus entry provokes it"
                + (" in a run the browser completes (seen only where the port "
                   "abstained)" if c in seen_abstaining else ""))
            for c in uncovered
        },
    }


def format_report(report: dict) -> str:
    recs = report["records"]
    out = []
    counts = {}
    for r in recs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out.append("=" * 78)
    out.append("VAC CONFORMANCE: browser verifier vs. Python reference")
    out.append("=" * 78)
    for fam in ("whole", "sliced", "derived"):
        fr = [r for r in recs if r["family"] == fam]
        if not fr:
            continue
        out.append("")
        out.append(f"--- {fam} ({len(fr)} cases) " + "-" * (60 - len(fam)))
        for r in fr:
            flag = {MATCH: "  ok", DIVERGENT: "  ~~", MISMATCH: "FAIL"}[r["status"]]
            det = "" if r["detail_exact"] else "  [detail text differs]"
            out.append(f"{flag}  {r['name']:<30} ref={r['ref_verdict']:<5}"
                       f" browser={r['js_verdict']:<10}"
                       f" refusals={len(r['ref_names'])}{det}")
            if r["status"] != MATCH:
                out.append(f"        reason: {r['reason']}")
            if not r["detail_exact"] and r["status"] == MATCH:
                for a, b in zip(r["ref_lines"], r["js_lines"]):
                    if a != b:
                        out.append(f"        reference: {a}")
                        out.append(f"        browser  : {b}")
                        break
    out.append("")
    out.append("-" * 78)
    out.append(f"total cases      : {len(recs)}")
    out.append(f"MATCH            : {counts.get(MATCH, 0)}")
    out.append(f"EXPECTED-DIVERGENT: {counts.get(DIVERGENT, 0)}")
    out.append(f"MISMATCH         : {counts.get(MISMATCH, 0)}")
    dt = sum(1 for r in recs if not r["detail_exact"] and r["status"] == MATCH)
    out.append(f"matches whose detail TEXT differs: {dt}")
    cov = report["coverage"]
    out.append("")
    out.append(f"refusal classes in refusals.json : {len(cov['all_classes'])}")
    out.append(f"covered by a completed comparison: {len(cov['tested'])}")
    for c in cov["all_classes"]:
        if c in cov["tested"]:
            where = cov["tested"][c]
            out.append(f"  ok  {c:<28} {len(where)} case(s), e.g. {where[0]}")
    out.append(f"NO COVERAGE                      : {len(cov['uncovered'])}")
    for c in cov["uncovered"]:
        out.append(f"  --  {c:<28} {cov['uncovered_reasons'][c]}")
    return "\n".join(out)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rep = run_conformance(pathlib.Path(td))
        print(format_report(rep))
