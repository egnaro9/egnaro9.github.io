"""Differential conformance harness: browser verifier vs. Python reference.

The only thing this file computes is a COMPARISON. It never decides whether a
bundle is honest -- it runs `vac-verify` (the reference) and `bv_harness.js`
(the browser port, under node) over the same bytes on disk and diffs what came
back. If it re-implemented a check, it would be grading one of my
implementations against another.

Three corpora, all materialised to real directories so both verifiers read
identical bytes:

  whole    the 26 fixtures + examples/outsider, exactly as committed.
  sliced   the same bundles with the profiles the browser port does not
           implement (modeldrift-board-v1, crashkit-variance-v1) removed,
           along with the evidence only those checks read and the summary
           subtree only those checks recompute. Without this the port abstains
           on 25 of 27 bundles and the comparison proves nothing.
  derived  minimal edits that provoke refusal classes no fixture reaches, and
           that pin each rule the port gained from c441011's verify.py on
           the fixture it would otherwise go unexercised by.

A run where the browser port abstains (INCOMPLETE) is NOT a match. It is
recorded as EXPECTED-DIVERGENT with the reason it abstained, and it is still
held to a floor: every refusal it did emit must be an ordered subsequence of
the reference's, so an abstaining run cannot smuggle in an invented refusal.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess

# An absolute path to one person's home directory, committed to a public repo. It survived
# because the skipif above hid every test that used it, so the harness never ran anywhere
# that path did not exist. VAC_DIR lets CI point at its own checkout.
VAC_ROOT = pathlib.Path(os.environ.get("VAC_DIR") or pathlib.Path.home() / "vac-protocol")
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

# Refusal classes no bundle the browser port can be handed will ever earn, with
# the reason. These are reported as NO COVERAGE, never as agreement, and the
# set must equal what refusals.json flags from verify.py's own structure
# (archive_only, symlink_only), so it cannot grow by hand.
UNREACHABLE = {
    "unsafe-archive": (
        "tar path only: fires while unpacking a .tar.gz. A directory bundle "
        "never enters that code path in either implementation."
    ),
    "unsafe-bundle": (
        "symlink only: verify.py emits it only after asking is_symlink() of a "
        "path in a bundle directory. The port's input is a map from path to "
        "bytes, which has no way to express a link: the page embeds bytes, "
        "browserverify.bundle_files refuses to embed a bundle holding a link, "
        "and bv_harness.js refuses to read one. "
        "test_a_symlink_never_reaches_the_port checks all three against the "
        "reference's own refusal."
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


# ------------------------------------------------- JSON nesting depth (SPEC 4)
# SPEC 4 bounds nesting at 256 levels and requires the decision to be made
# BEFORE parsing, so the verdict belongs to the verifier and not to whichever
# stack the host happens to give a recursive parser. Both sides of the boundary
# are built here: a document AT the limit must verify exactly as it did before,
# one level past it must be refused as invalid-json, and the cases below also
# pin the counting rules that decide where that boundary falls.
MAX_JSON_DEPTH = 256


def _deep_key(text: str, k: int) -> str:
    """`text` (a JSON object) with one extra first member holding k nested
    arrays, so the document is exactly k + 1 levels deep. SPEC 2 permits the
    unknown key, so depth is the only thing that moves."""
    assert text.startswith("{"), text[:40]
    return '{"deep": ' + "[" * k + "]" * k + ", " + text[1:]


def _repin(d: pathlib.Path, m: dict, rel: str) -> None:
    """Re-pin one artifact's sha256 so the edit under test is the depth and not
    a hash mismatch that would refuse the bundle before anything parses it."""
    digest = hashlib.sha256((d / rel).read_bytes()).hexdigest()
    for e in m["evidence"]:
        if e["path"] == rel:
            e["sha256"] = digest
            return
    raise KeyError(f"{rel} is not listed in the manifest")


def _rewrite_lines(d: pathlib.Path, rel: str, fn) -> None:
    p = d / rel
    lines = p.read_text().splitlines(keepends=True)
    fn(lines)
    p.write_text("".join(lines))


def _d_manifest_at_the_depth_limit(d, m):
    """Exactly 256 levels. Nothing about this bundle is dishonest, so both
    verifiers must still pass it: a limit that also refuses the last legal
    document would be a different limit."""
    p = d / "vac.json"
    p.write_text(_deep_key(p.read_text(), MAX_JSON_DEPTH - 1))
    return False


def _d_manifest_past_the_depth_limit(d, m):
    p = d / "vac.json"
    p.write_text(_deep_key(p.read_text(), MAX_JSON_DEPTH))
    return False


def _d_manifest_far_past_the_depth_limit(d, m):
    """20000 levels: past CPython 3.12's stack and inside 3.14's, which is the
    pair of hosts that used to return opposite verdicts on the same bytes."""
    p = d / "vac.json"
    p.write_text(_deep_key(p.read_text(), 20000))
    return False


def _d_artifact_past_the_depth_limit(d, m):
    rel = "evidence/bundle.json"
    p = d / rel
    p.write_text(_deep_key(p.read_text(), MAX_JSON_DEPTH))
    _repin(d, m, rel)


def _d_jsonl_line_past_the_depth_limit(d, m):
    rel = "evidence/raw_results.jsonl"
    _rewrite_lines(d, rel,
                   lambda ls: ls.__setitem__(1, _deep_key(ls[1], MAX_JSON_DEPTH)))
    _repin(d, m, rel)


def _d_jsonl_deep_line_behind_a_broken_one(d, m):
    """Line 1 will not parse and line 3 is too deep. A parser stops at the
    first error, so the only way line 3 is named is if every line was measured
    before any line was parsed."""
    rel = "evidence/raw_results.jsonl"

    def edit(ls):
        ls[2] = _deep_key(ls[2], MAX_JSON_DEPTH)
        ls[0] = "{not json\n"

    _rewrite_lines(d, rel, edit)
    _repin(d, m, rel)


def _d_brackets_inside_a_string_are_not_nesting(d, m):
    """400 opening brackets, all of them string content. A counter that read
    them as containers would refuse an honest bundle."""
    m["deep_looking"] = "[" * 400 + ' "' + "{" * 400


def _d_stray_closers_before_deep_nesting(d, m):
    """Four closers with nothing open, then 258 real levels. A counter that let
    the depth go negative would read the 258 as 254 and hand the document to
    the parser, which names a different refusal on a different line."""
    rel = "evidence/bundle.json"
    n = MAX_JSON_DEPTH + 2
    (d / rel).write_text("]]]]" + "[" * n + "]" * n + "\n")
    _repin(d, m, rel)


def _d_utf8_bom_on_a_deep_manifest(d, m):
    """A byte-order mark opens the document, so the document is refused at its
    first character whatever its depth. Measuring it would be the first step to
    accepting text the parser refuses."""
    p = d / "vac.json"
    p.write_bytes(b"\xef\xbb\xbf" + _deep_key(p.read_text(), 20000).encode())
    return False


def _d_jsonl_blank_lines_before_a_deep_one(d, m):
    """Blank lines hold no row, but they are still lines. The number a refusal
    names has to be the one an editor shows, so the two implementations must
    count the same things as lines."""
    rel = "evidence/raw_results.jsonl"

    def edit(ls):
        ls[1] = _deep_key(ls[1], MAX_JSON_DEPTH)
        ls.insert(1, "\n\n")

    _rewrite_lines(d, rel, edit)
    _repin(d, m, rel)


def _d_jsonl_carriage_returns_before_a_deep_line(d, m):
    """The same artifact written with carriage returns for line endings.
    read_text() turns a lone CR, and a CRLF pair, into one line feed before the
    reference counts lines, so a port that measured on line feeds alone would
    read this whole file as one line and name the wrong number."""
    rel = "evidence/raw_results.jsonl"

    def edit(ls):
        ls[3] = _deep_key(ls[3], MAX_JSON_DEPTH)
        for i, ln in enumerate(ls):
            ls[i] = ln.replace("\n", "\r")

    _rewrite_lines(d, rel, edit)
    _repin(d, m, rel)


def _rewrite_json(d: pathlib.Path, m: dict, rel: str, fn) -> None:
    """Edit one JSON evidence artifact in place and re-pin it, so the edit under
    test is what the check reads and not a hash mismatch in front of it."""
    p = d / rel
    data = json.loads(p.read_text())
    fn(data)
    p.write_text(json.dumps(data, indent=2) + "\n")
    _repin(d, m, rel)


def _move_artifact(d: pathlib.Path, m: dict, old: str, new: str) -> None:
    """Move an artifact, and every reference to it, to a new path. The bytes and
    their sha256 do not change, so the only thing that moves is the name."""
    (d / new).parent.mkdir(parents=True, exist_ok=True)
    (d / old).rename(d / new)
    for e in m["evidence"]:
        if e["path"] == old:
            e["path"] = new
    for c in m["results"]["checks"]:
        for k, v in list(c.items()):
            if v == old:
                c[k] = new


def _d_utf8_bom_on_a_deep_jsonl_line(d, m):
    """The mark opens line 3, not the text, so only that line goes unmeasured
    and the parser names it at its first character, as it did before."""
    rel = "evidence/raw_results.jsonl"

    def edit(ls):
        ls[2] = "\ufeff" + _deep_key(ls[2], 20000)

    _rewrite_lines(d, rel, edit)
    _repin(d, m, rel)


# ------------------------------------ rules the port took from c441011 (v0.1)
# Each of these was a rule verify.py had and the port did not, and every one
# of them passed a bundle here that the command line refused, or the reverse.
# The fixtures exercise none of them, so without a case each would be ported
# on trust.
def _d_evalmut_corpus_in_an_unknown_shape(d, m):
    _rewrite_json(d, m, "evidence/evalmut_fixtures.json",
                  lambda fx: fx.__setitem__("manifest_version", 2))


def _d_evalmut_corpus_miscounts_its_cases(d, m):
    _rewrite_json(d, m, "evidence/evalmut_fixtures.json",
                  lambda fx: fx.__setitem__("case_count", 3))


def _d_evalmut_rows_cite_an_absent_case(d, m):
    """toy-exact leaves the corpus manifest and its count is corrected, so the
    only thing wrong is that four rows still cite it."""
    def edit(fx):
        fx["cases"] = [c for c in fx["cases"] if c["name"] != "toy-exact"]
        fx["case_count"] = len(fx["cases"])

    _rewrite_json(d, m, "evidence/evalmut_fixtures.json", edit)


def _d_evalmut_operator_id_is_a_list(d, m):
    _rewrite_json(d, m, "evidence/evalmut_run.json",
                  lambda r: r["results"][0].__setitem__("operator_id", ["toy-blank"]))


def _d_certlab_verdict_is_not_an_object(d, m):
    _rewrite_json(d, m, "evidence/bundle.json", lambda b: b["verdicts"].append("fixed"))


def _d_fleet_row_is_not_an_object(d, m):
    _rewrite_json(d, m, "evidence/results.json", lambda a: a["rows"].append(5))


def _d_fleet_raw_line_is_not_an_object(d, m):
    rel = "evidence/raw_results.jsonl"
    _rewrite_lines(d, rel, lambda ls: ls.append("[1]\n"))
    _repin(d, m, rel)


def _d_fleet_member_is_a_list_after_a_contradiction(d, m):
    """Line 1 contradicts its own pair and line 3 names a list as its member.
    The reference names line 1, then stops at line 3, so this pins the ORDER as
    well as the stop: a port that checked every line's type first would drop
    the first reason."""
    rel = "evidence/raw_results.jsonl"

    def edit(ls):
        first = json.loads(ls[0])
        first["detected"] = False
        ls[0] = json.dumps(first) + "\n"
        third = json.loads(ls[2])
        third["member"] = [third["member"]]
        ls[2] = json.dumps(third) + "\n"

    _rewrite_lines(d, rel, edit)
    _repin(d, m, rel)


def _d_limitation_blank_only_to_python(d, m):
    """U+001C is whitespace to str.strip() and not to String.prototype.trim(),
    so the port read this as a stated limitation and passed a bundle the
    reference refuses as stating none."""
    m["claim"]["limitations"] = ["\u001c"]


def _d_capability_a_lone_byte_order_mark(d, m):
    """The other direction: trim() strips U+FEFF and str.strip() keeps it, so
    the port refused as empty a capability the reference accepts."""
    m["claim"]["capability"] = "\ufeff"


def _d_summary_numeral_behind_a_u001c(d, m):
    """A numeral in quotes is refused once stripped. Stripped by trim(), the
    U+001C stayed on, the numeral pattern missed, and the string walked past."""
    m["results"]["summary"]["verdicts"] = "\u001c3"


# ---------------------------------------------------------- vac_version 0.2
# Built on fixtures/v02-twin-arms, sliced, the clean 0.2 control. Every one of
# these would be refused as schema-violation by a port that knew only 0.1, so
# each is the reference's 0.2 semantics or nothing.
def _d_v02_declared_scope(d, m):
    m["results"]["checks"][0]["scope"] = "bundle"


def _d_v02_scope_without_a_stem(d, m):
    """A leading dot leaves nothing before the first '.', so no scope."""
    _move_artifact(d, m, "evidence/eval_run_safe.json", "evidence/.eval_run_safe.json")


def _d_v02_scope_claimed_twice(d, m):
    """The safe arm moves into a directory under the unsafe arm's filename. Two
    checks, one scope, and a summary path that could no longer say which."""
    _move_artifact(d, m, "evidence/eval_run_safe.json", "evidence/safe/eval_run.json")


def _d_v02_summary_has_no_fallback(d, m):
    """0.5 is the unsafe arm's recomputed accuracy, so at 0.1 the fallback tier
    would admit it under any name. At 0.2 a path no check recomputes is refused."""
    m["results"]["summary"]["headline"] = 0.5


def _d_v02_fleet_rate_from_another_level(d, m):
    """1.0 is one member's detection rate. The suite's is 0.75, and at 0.2 the
    suite_ key holds only that. The bare detection_rate beside it is the 0.1
    key, which merged all three levels and would admit 0.75; at 0.2 it names
    nothing any check recomputes, so both leaves are refused."""
    m["results"]["summary"]["results"] = {"detection_rate": 0.75,
                                          "suite_detection_rate": 1.0}


DERIVED_V02 = [
    ("v02-declared-scope", _d_v02_declared_scope,
     "0.2: checks[0] declares a scope, which 0.2 derives and never accepts"),
    ("v02-scope-without-a-stem", _d_v02_scope_without_a_stem,
     "0.2: the safe arm renamed .eval_run_safe.json, which yields no scope"),
    ("v02-scope-claimed-twice", _d_v02_scope_claimed_twice,
     "0.2: the safe arm moved to safe/eval_run.json, the unsafe arm's scope"),
    ("v02-summary-has-no-fallback", _d_v02_summary_has_no_fallback,
     "0.2: summary.headline 0.5, a recomputed value under no check's path"),
    ("v02-fleet-rate-from-another-level", _d_v02_fleet_rate_from_another_level,
     "0.2: summary.results carries a member's rate under suite_ and the "
     "merged 0.1 key"),
]


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
    ("json-depth-manifest-at-limit", _d_manifest_at_the_depth_limit,
     "manifest nests exactly 256 levels"),
    ("json-depth-manifest-over", _d_manifest_past_the_depth_limit,
     "manifest nests 257 levels, one past the limit"),
    ("json-depth-manifest-20000", _d_manifest_far_past_the_depth_limit,
     "manifest nests 20001 levels, past one host's stack and inside another's"),
    ("json-depth-artifact-over", _d_artifact_past_the_depth_limit,
     "evidence/bundle.json nests 257 levels"),
    ("json-depth-jsonl-over", _d_jsonl_line_past_the_depth_limit,
     "raw_results.jsonl line 2 nests 257 levels"),
    ("json-depth-jsonl-behind-broken-line", _d_jsonl_deep_line_behind_a_broken_one,
     "raw_results.jsonl line 1 is malformed and line 3 nests 257 levels"),
    ("json-depth-brackets-in-string", _d_brackets_inside_a_string_are_not_nesting,
     "800 brackets inside a manifest string value, none of them containers"),
    ("json-depth-stray-closers", _d_stray_closers_before_deep_nesting,
     "evidence/bundle.json opens with four unmatched closers, then 258 levels"),
    ("json-depth-bom-manifest", _d_utf8_bom_on_a_deep_manifest,
     "manifest carries a BOM and nests 20001 levels"),
    ("json-depth-bom-jsonl-line", _d_utf8_bom_on_a_deep_jsonl_line,
     "raw_results.jsonl line 3 carries a BOM and nests 20001 levels"),
    ("json-depth-jsonl-blank-lines", _d_jsonl_blank_lines_before_a_deep_one,
     "two blank lines pushed ahead of the 257-level line in raw_results.jsonl"),
    ("json-depth-jsonl-cr", _d_jsonl_carriage_returns_before_a_deep_line,
     "raw_results.jsonl rewritten with CR endings, line 4 nests 257 levels"),
    ("evalmut-corpus-unknown-shape", _d_evalmut_corpus_in_an_unknown_shape,
     "evalmut_fixtures.json manifest_version 2, a shape the check does not read"),
    ("evalmut-corpus-miscount", _d_evalmut_corpus_miscounts_its_cases,
     "evalmut_fixtures.json case_count 3 over 2 cases"),
    ("evalmut-rows-cite-absent-case", _d_evalmut_rows_cite_an_absent_case,
     "toy-exact dropped from evalmut_fixtures.json while rows still cite it"),
    ("evalmut-operator-id-list", _d_evalmut_operator_id_is_a_list,
     "evalmut_run.json results[0].operator_id is a list"),
    ("certlab-verdict-not-object", _d_certlab_verdict_is_not_an_object,
     "bundle.json verdicts[] gains a string"),
    ("fleet-row-not-object", _d_fleet_row_is_not_an_object,
     "results.json rows[] gains a number"),
    ("fleet-raw-line-not-object", _d_fleet_raw_line_is_not_an_object,
     "raw_results.jsonl gains a line holding an array"),
    ("fleet-member-list-after-contradiction",
     _d_fleet_member_is_a_list_after_a_contradiction,
     "raw_results.jsonl line 1 contradicts its pair, line 3's member is a list"),
    ("limitation-blank-only-to-python", _d_limitation_blank_only_to_python,
     "claim.limitations is one U+001C, blank to str.strip() and not to trim()"),
    ("capability-lone-bom", _d_capability_a_lone_byte_order_mark,
     "claim.capability is one U+FEFF, blank to trim() and not to str.strip()"),
    ("summary-numeral-behind-u001c", _d_summary_numeral_behind_a_u001c,
     "summary.verdicts is the string U+001C then 3"),
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
    base02 = tmp / "derived" / "_base02"
    if slice_unported(VAC_ROOT / "fixtures" / "v02-twin-arms", base02) is None:
        raise RuntimeError("fixtures/v02-twin-arms no longer declares an unported profile")
    for root, family in ((base, DERIVED), (base02, DERIVED_V02)):
        for name, fn, note in family:
            dest = tmp / "derived" / name
            shutil.copytree(root, dest)
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
