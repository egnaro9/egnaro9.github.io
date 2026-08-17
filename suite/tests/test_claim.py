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
import subprocess
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
    subprocess.run([sys.executable, str(ROOT / "runner.py")], cwd=str(ROOT),
                   check=True, capture_output=True)
    return (ROOT / "runner.html").read_text()


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


def test_the_page_shows_one_example_only():
    """The handoff forbids a multi-repository product story before one slice is evidence-backed."""
    html = _build()
    for other in ("CALIBRATE", "CERTIFY", "PRESERVE"):
        assert other not in html, f"{other} panel is back; the page is widening again"
