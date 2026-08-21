"""Differential conformance: the browser verifier must agree with vac-verify.

Runs both implementations over identical bytes for every fixture, every
per-profile slice, and a set of derived bundles that reach refusal classes no
fixture touches. Compares the verdict AND the ordered list of named refusals.

Print the whole table with:
    cd suite && ~/vac-protocol/.venv/bin/python tests/conformance.py
"""

import pathlib
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import conformance as C  # noqa: E402


pytestmark = pytest.mark.skipif(
    not C.VAC_VERIFY.is_file() or shutil.which("node") is None,
    reason="needs the vac-protocol venv's vac-verify and node on PATH",
)


# Detail-text divergences the port has disclosed. A MATCH on the refusal names
# whose message text differs is allowed only if it is on this list, so a new
# one has to be argued for rather than absorbed.
# Cases where both implementations refuse with the SAME ordered refusal names but the human-readable
# detail text differs. The name is the contract; the detail is CPython's or V8's own wording. Each
# entry carries its reason so a future reader can judge whether it is still acceptable, and an
# undeclared divergence fails the suite rather than being tolerated.
KNOWN_DETAIL_DIVERGENCE = {
    ("derived", "invalid-utf8"):
        "CPython reports the offending byte and its position ('utf-8' codec can't decode byte 0xff "
        "in position 29: invalid start byte); the browser port reports only that the file's bytes "
        "could not be decoded. TextDecoder does not expose the byte offset.",
    ("derived", "utf8-bom"):
        "CPython names the BOM specifically (Unexpected UTF-8 BOM, decode using utf-8-sig); JS "
        "reports the generic 'Expecting value: line 1 column 1' once the BOM is kept in the "
        "string rather than stripped. Both refuse with invalid-json, which is the contract.",
}


@pytest.fixture(scope="module")
def report():
    with tempfile.TemporaryDirectory() as td:
        yield C.run_conformance(pathlib.Path(td))


def test_the_whole_committed_corpus_is_present(report):
    """22 fixtures + examples/outsider, none dropped on the way in."""
    whole = [r for r in report["records"] if r["family"] == "whole"]
    assert len(whole) == 23, [r["name"] for r in whole]
    fixtures = [r["name"] for r in whole if r["name"] != "outsider"]
    assert len(fixtures) == 22
    assert "make_fixtures.py" not in fixtures


def test_no_mismatch_between_the_two_implementations(report):
    """The whole point. Every case is a match or a reasoned divergence."""
    bad = [r for r in report["records"] if r["status"] == C.MISMATCH]
    assert not bad, "\n".join(
        f"{r['family']}/{r['name']}: {r['reason']}\n"
        f"    reference: {r['ref_verdict']} {r['ref_names']}\n"
        f"    browser  : {r['js_verdict']} {r['js_names']}"
        for r in bad
    )


def test_every_case_is_classified_and_nothing_is_skipped(report):
    recs = report["records"]
    assert len(recs) == 54, len(recs)
    assert all(r["status"] in (C.MATCH, C.DIVERGENT, C.MISMATCH) for r in recs)
    # a divergence with no reason is a silent skip wearing a label
    for r in recs:
        if r["status"] == C.DIVERGENT:
            assert r["reason"].strip(), r["name"]


def test_divergences_are_only_ever_unported_profile_abstentions(report):
    """EXPECTED-DIVERGENT must mean 'the port refused to answer', never
    'the port answered differently'."""
    for r in report["records"]:
        if r["status"] != C.DIVERGENT:
            continue
        assert r["js_verdict"] == "INCOMPLETE", (r["name"], r["js_verdict"])
        assert r["js_unported"], r["name"]
        assert set(r["js_unported"]) <= C.UNPORTED_PROFILES, r["js_unported"]


def test_an_abstaining_run_never_invents_a_refusal(report):
    """A port that abstains may withhold refusals. It may not add one, reorder
    them, or change their text."""
    for r in report["records"]:
        if r["status"] != C.DIVERGENT:
            continue
        assert C._is_ordered_subsequence(r["js_names"], r["ref_names"]), r["name"]
        for line in r["js_lines"]:
            assert line in r["ref_lines"], (r["name"], line)


def test_the_clean_bundles_agree(report):
    """PASS on both sides, with no refusals, for the bundles that are honest."""
    clean = {("whole", "outsider"), ("sliced", "valid")}
    got = {(r["family"], r["name"]) for r in report["records"]
           if r["ref_verdict"] == "PASS" and r["js_verdict"] == "PASS"
           and r["status"] == C.MATCH}
    assert clean <= got, got


def test_agreement_is_not_only_on_the_happy_path(report):
    """Guards against a suite that reports agreement it never tested: the
    matches must be dominated by bundles the reference REFUSED."""
    matches = [r for r in report["records"] if r["status"] == C.MATCH]
    refused = [r for r in matches if r["ref_verdict"] == "FAIL"]
    assert len(refused) >= 25, len(refused)
    assert sum(len(r["ref_names"]) for r in refused) >= 60


def test_every_implemented_refusal_class_has_coverage(report):
    """At least one case per refusal class, compared in a run the browser
    carried to a verdict. Classes with none are named, with a reason."""
    cov = report["coverage"]
    uncovered = set(cov["uncovered"])
    assert uncovered <= set(C.UNREACHABLE), (
        "refusal classes with NO conformance coverage: "
        + ", ".join(sorted(uncovered - set(C.UNREACHABLE)))
    )
    assert len(cov["tested"]) == 19, sorted(cov["tested"])


def test_detail_text_divergences_are_declared(report):
    """Names matching while messages differ is a real, smaller divergence.
    It has to be on the declared list."""
    found = {(r["family"], r["name"]) for r in report["records"]
             if r["status"] == C.MATCH and not r["detail_exact"]}
    assert found == set(KNOWN_DETAIL_DIVERGENCE), (
        f"undeclared: {sorted(found - set(KNOWN_DETAIL_DIVERGENCE))}, "
        f"declared but gone: {sorted(set(KNOWN_DETAIL_DIVERGENCE) - found)}"
    )


def test_slicing_preserved_the_tamper(report):
    """The slice must not have quietly repaired the bundle it was cut from.
    Every sliced case except the two whose tamper lived in the dropped profile
    still fails on the reference."""
    sliced = {r["name"]: r for r in report["records"] if r["family"] == "sliced"}
    repaired_by_design = {"tamper-modeldrift-rows", "tamper-modeldrift-standings",
                          "valid"}
    for name, r in sliced.items():
        if name in repaired_by_design:
            assert r["ref_verdict"] == "PASS", name
        else:
            assert r["ref_verdict"] == "FAIL", name


# ------------------------------------------------------------------ meta-tests
# A conformance comparator that has never returned MISMATCH is not known to
# work. These drive the comparator with fabricated results.
def test_comparator_flags_a_wrong_refusal_name():
    ref = {"verdict": "FAIL", "lines": ["sha256-mismatch: x"],
           "names": ["sha256-mismatch"]}
    js = {"verdict": "REFUSED", "lines": ["sha256-mismatched: x"],
          "names": ["sha256-mismatched"], "unported": []}
    assert C.compare(ref, js)["status"] == C.MISMATCH


def test_comparator_flags_a_wrong_order():
    ref = {"verdict": "FAIL", "lines": ["a: 1", "b: 2"], "names": ["a", "b"]}
    js = {"verdict": "REFUSED", "lines": ["b: 2", "a: 1"], "names": ["b", "a"],
          "unported": []}
    assert C.compare(ref, js)["status"] == C.MISMATCH


def test_comparator_flags_a_false_pass():
    ref = {"verdict": "FAIL", "lines": ["sha256-mismatch: x"],
           "names": ["sha256-mismatch"]}
    js = {"verdict": "PASS", "lines": [], "names": [], "unported": []}
    assert C.compare(ref, js)["status"] == C.MISMATCH


def test_comparator_does_not_let_an_abstention_hide_an_invented_refusal():
    ref = {"verdict": "FAIL", "lines": ["a: 1"], "names": ["a"]}
    js = {"verdict": "INCOMPLETE", "lines": ["z: 9"], "names": ["z"],
          "unported": ["modeldrift-board-v1"]}
    assert C.compare(ref, js)["status"] == C.MISMATCH


def test_comparator_rejects_an_abstention_on_an_undeclared_profile():
    ref = {"verdict": "FAIL", "lines": ["a: 1"], "names": ["a"]}
    js = {"verdict": "INCOMPLETE", "lines": [], "names": [],
          "unported": ["certlab-bundle-v1"]}
    assert C.compare(ref, js)["status"] == C.MISMATCH


def test_comparator_accepts_a_real_agreement():
    ref = {"verdict": "FAIL", "lines": ["a: 1"], "names": ["a"]}
    js = {"verdict": "REFUSED", "lines": ["a: 1"], "names": ["a"],
          "unported": []}
    assert C.compare(ref, js)["status"] == C.MATCH
