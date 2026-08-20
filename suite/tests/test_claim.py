"""The headline, held to the failure that actually happened.

A review of this work asserted "32/35 caught, three open holes" while the run on disk said 42/46
and four. The number was right when someone wrote it down and wrong two commits later. These
tests exist so the page cannot repeat that: the headline is derived, the build refuses an
inconsistent bundle, and the RENDERED html is checked against the current fields rather than
trusted because the generator was correct.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from claim import UnderivableClaim, derive  # noqa: E402

BUNDLE = pathlib.Path.home() / "evalmut/docs/dogfood_gradecore.json"


def test_the_live_bundle_still_says_what_the_page_claims():
    """Snapshot of the real numbers. If evalmut's dogfood moves, this fails and the page copy
    must be re-derived rather than quietly drifting."""
    c = derive(BUNDLE)
    assert (c.caught, c.applied) == (42, 46)
    assert c.score_pct == 91.3
    assert c.holes_total == 4
    assert c.holes_by_kind == {"blind": 2, "coverage_gap": 2}


def test_the_headline_is_generated_from_those_fields():
    c = derive(BUNDLE)
    assert c.headline == ("Recorded evalmut dogfood run: 42 of 46 declared mutations were "
                          "caught; 4 survived (2 blind, 2 coverage gap).")


def test_a_bundle_that_contradicts_itself_stops_the_build(tmp_path):
    """Hole buckets and the tally are two derivations of one fact. A disagreement means one is
    wrong and the page must not pick a favourite."""
    d = json.loads(BUNDLE.read_text())
    d["holes"] = {"blind": d["holes"]["blind"]}          # drop rows, leave the tally alone
    p = tmp_path / "b.json"; p.write_text(json.dumps(d))
    with pytest.raises(UnderivableClaim, match="contradicts itself"):
        derive(p)


def test_a_summary_that_outruns_its_rows_stops_the_build(tmp_path):
    d = json.loads(BUNDLE.read_text())
    d["score"] = 0.99
    p = tmp_path / "b.json"; p.write_text(json.dumps(d))
    with pytest.raises(UnderivableClaim, match="outran its own rows"):
        derive(p)


def test_an_empty_run_is_not_a_clean_run(tmp_path):
    d = json.loads(BUNDLE.read_text())
    d["tally"] = {"caught": 0, "missed": 0, "flagged": 0, "na": 5}
    d["holes"] = {}
    p = tmp_path / "b.json"; p.write_text(json.dumps(d))
    with pytest.raises(UnderivableClaim, match="no claim to make"):
        derive(p)


# ── the rendered page, not just the generator ────────────────────────────────

def _build() -> str:
    """Build to a scratch path and read THAT.

    It used to build over runner.html itself, which quietly made every rendered-page test in this
    repo self-fulfilling: the test regenerated the artifact microseconds before inspecting it, so
    a stale committed page could never fail. Tests that rebuild what they audit are the same
    shape as a gate that cannot tell "checked and clean" from "never checked". The committed file
    is now guarded separately, by test_the_committed_page_is_not_stale."""
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "runner.html"
        subprocess.run([sys.executable, str(ROOT / "runner.py"), str(out)], cwd=str(ROOT),
                       check=True, capture_output=True)
        return out.read_text()


def test_the_committed_page_is_not_stale():
    """The artifact in git must equal what the current code produces.

    This is the assertion that lets every other rendered-page test be trusted. Without it the
    suite can be fully green while the file actually served to a reader was built from code that
    no longer exists."""
    assert _build() == (ROOT / "runner.html").read_text(), (
        "runner.html on disk differs from a fresh build. Run `python runner.py` and commit the "
        "result, or the published page is showing output of code that is no longer here.")


def test_the_rendered_html_carries_the_current_headline_and_bounds():
    """Correct data in one layer can still ship as stale static HTML from another. This asserts
    the artifact a reader actually opens, not the function that made it."""
    html = _build()
    c = derive(BUNDLE)
    assert c.headline in html, "the rendered page is not showing the derived headline"
    assert "Does not establish" in html
    assert "Corpus A protocol and tooling" in html


def test_the_three_modes_are_labelled_exactly_and_live_is_reserved():
    html = _build()
    for label in ("Recorded proof run", "Browser tamper demo", "Independent replay"):
        assert label in html, f"missing exact mode label {label!r}"
    assert html.lower().count("live verification") == 1, (
        "'live verification' must appear once, reserved for independent replay")
    i = html.lower().index("live verification")
    assert "Independent replay" in html[max(0, i - 400):i], (
        "'live verification' is not attached to the independent-replay mode")


def test_every_measured_step_is_bound_to_its_own_artifact():
    """Four repos on one page is the shape a product pitch abuses, so the containment is checked.

    An earlier draft enforced this by deleting three of the six steps. It is enforced here by
    binding instead: every step that shows numbers names exactly one committed file, carries its
    own provenance drawer, and shares neither the file nor the repo with another step. A step
    with no drawer, or one borrowing another step's evidence, would be making a claim its own
    artifact does not carry, which is the failure the deletion was avoiding."""
    html = _build()
    cards = html.split('<div class="step')[1:]
    assert [re.search(r'data-i="(\d)"', c).group(1) for c in cards] == list("123456"), (
        "the six steps must render in order, numbered as the module docstring lists them")

    # Steps that DISPLAY READ NUMBERS must carry a drawer. Selecting them by shape rather than
    # by index is the point: `cards[:4]` hardcoded the exemption for 5 and 6 while this test's
    # own docstring claimed it checked every step, so it passed by scope and not by coverage.
    measured = [c for c in cards if "<dl>" in c]
    assert len(measured) == 4, f"expected four measured steps, found {len(measured)}"

    files = []
    for card in measured:
        assert card.count('<details class="ev">') == 1, (
            "a step that shows numbers with no provenance drawer is an unbound claim")
        named = re.findall(r"<dt>file</dt><dd><a [^>]*>([^<]+)</a>", card)
        assert len(named) == 1, f"a step must name exactly one artifact, found {named}"
        files.append(named[0])
    assert len(set(files)) == 4, f"two steps rest on the same artifact: {files}"
    assert len({f.split("/")[0] for f in files}) == 4, f"two steps rest on one repo: {files}"


def test_step_five_never_reports_a_refusal_it_did_not_earn():
    """A count taken from the length of an attempt list is not a measurement.

    THE DEFECT THIS PINS. challenge() once appended every fixture it attempted to one list and
    rendered len() of it as "N refused". With the verifier binary off PATH all six invocations
    returned rc -1, and the deployed page published "5 refused" directly above six
    FileNotFoundError transcripts. It shipped that way from the first deploy. The page whose
    thesis is that a verification system can show green over the surface it does not cover was
    doing exactly that, on the step it calls the one a competitor cannot copy.

    So the headline may only claim refusals that a running verifier actually produced."""
    import runner

    for state, expect_ok, expect_in_head in (
        ("REFUSED", True, "refused"),
        ("UNLAUNCHED", False, "did not run"),
        ("NOT_REFUSED", False, "PASSED"),
    ):
        attempts = [{"name": "f", "rc": 1, "line": "FAIL x", "state": state}]
        refused = [a for a in attempts if a["state"] == "REFUSED"]
        unlaunched = [a for a in attempts if a["state"] == "UNLAUNCHED"]
        not_refused = [a for a in attempts if a["state"] == "NOT_REFUSED"]
        if unlaunched:
            ok, head = False, "verifier did not run"
        elif not_refused:
            ok, head = False, f"{len(not_refused)} tampered bundle(s) PASSED"
        else:
            ok, head = True, f"{len(refused)} of {len(attempts)} refused"
        assert ok is expect_ok, f"{state} classified wrong"
        assert expect_in_head in head, f"{state} head was {head!r}"

    src = pathlib.Path(runner.__file__).read_text()
    assert "{len(ch['refusals'])} refused" not in src, (
        "the headline is counting attempts again, which is the defect this test exists for")
