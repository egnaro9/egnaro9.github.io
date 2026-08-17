"""The hole explorer is a set of claims about defects, so each card is checked against the bundle.

Two tests carry the weight. `test_every_card_prints_the_bundles_exact_mutant` reads the RENDERED
page and requires each printed mutant to appear verbatim in the artifact, because a paraphrased
mutant is the finding restated by the page rather than reported by it. And
`test_remedy_follows_op_type_not_the_authors_opinion` pins the one place this page could quietly
turn a documented scope limit into an accusation.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import holes as H  # noqa: E402
from holes import HoleShapeError, check_against_tally, counts  # noqa: E402

HOME = pathlib.Path.home()
BUNDLE = HOME / "evalmut/docs/dogfood_gradecore.json"
PAGE = pathlib.Path(__file__).resolve().parents[1] / "runner.html"
needs_bundle = pytest.mark.skipif(not BUNDLE.exists(), reason="evalmut bundle not on this machine")
needs_page = pytest.mark.skipif(not PAGE.exists(), reason="page not built")


@pytest.fixture
def doc():
    return json.loads(BUNDLE.read_text())


# ---------------------------------------------------------------- the derivation

@needs_bundle
def test_every_survival_in_the_bundle_becomes_a_card(doc):
    """No row is dropped, including kinds this page did not expect to be populated."""
    found = H.holes(doc)
    assert len(found) == sum(len(v) for v in doc["holes"].values())
    check_against_tally(doc, found)


@needs_bundle
def test_a_card_set_that_disagrees_with_the_headline_raises(doc):
    """The cards and the h1 are two views of one fact. They are made to agree, not assumed to."""
    with pytest.raises(HoleShapeError) as e:
        check_against_tally(doc, H.holes(doc)[:-1])
    assert "disagrees with its own headline" in str(e.value)


@needs_bundle
def test_a_missing_bucket_raises_rather_than_rendering_fewer_kinds(doc):
    """If evalmut's taxonomy moves, this page must stop rather than silently narrow it."""
    doc["holes"].pop("brittle")
    with pytest.raises(HoleShapeError) as e:
        H.holes(doc)
    assert "taxonomy moved" in str(e.value)


@needs_bundle
def test_a_row_missing_a_field_raises(doc):
    doc["holes"]["blind"][0].pop("real_origin")
    with pytest.raises(HoleShapeError) as e:
        H.holes(doc)
    assert "real_origin" in str(e.value)


@needs_bundle
def test_remedy_follows_op_type_not_the_authors_opinion(doc):
    """The one place this page could turn a documented limit into an accusation.

    A DIAGNOSTIC survival means the grader family is blind to the shape BY DESIGN and says so.
    Rendering that as a broken check is the same overclaim the estate refuses, pointed the other
    way, so the remedy is looked up from the row and never chosen per hole."""
    by_op = {h.op_type for h in H.holes(doc)}
    assert {"kill", "diagnostic"} <= by_op, "the run should contain both kinds"
    for h in H.holes(doc):
        if h.op_type == "kill":
            assert h.remedy.startswith("Fix the check")
        if h.op_type == "diagnostic":
            assert h.remedy.startswith("Add a check")
            assert "broken" not in h.remedy.lower()


@needs_bundle
def test_an_unknown_op_type_refuses_to_print_a_remedy(doc):
    h = H.holes(doc)[0]
    bad = H.Hole(**{**h.__dict__, "op_type": "newly_invented"})
    with pytest.raises(HoleShapeError) as e:
        bad.remedy
    assert "does not understand" in str(e.value)


@needs_bundle
def test_empty_kinds_are_counted_not_dropped(doc):
    got = counts(doc)
    assert len(got) == len(H.KINDS)
    assert any(n == 0 for _, _, n in got), "this run has empty buckets and they must be reported"


# ---------------------------------------------------------------- the page a visitor reads

@needs_page
@needs_bundle
def test_every_card_prints_the_bundles_exact_mutant(doc):
    """A paraphrased mutant is the page restating the finding instead of reporting it.

    Read off the rendered HTML, unescaped, and required to appear byte for byte in the artifact."""
    page = PAGE.read_text()
    shown = [html.unescape(m) for m in re.findall(r'<code class="got">(.*?)</code>', page, re.S)]
    real = {r["mutant_preview"] for rows in doc["holes"].values() for r in rows}
    assert len(shown) == sum(len(v) for v in doc["holes"].values())
    for s in shown:
        assert s in real, f"page prints a mutant that is not in the bundle: {s!r}"


@needs_page
@needs_bundle
def test_the_page_states_the_requirement_the_mutant_defeated(doc):
    """"It passed" is only a finding if the reader can see what it was supposed to enforce."""
    page = PAGE.read_text()
    reqs = {r["detail"] for rows in doc["holes"].values() for r in rows}
    for r in reqs:
        assert html.escape(r) in page, f"the check's requirement {r!r} is not shown"


@needs_page
def test_holes_outrank_the_score_typographically():
    """Erik's condition: the survivals carry at least the weight of the percentage.

    Checked structurally rather than by eye: the score renders as a monospace row inside a step
    body, while each survival is an <article> under a section heading. If the score ever gets a
    heading of its own this test should be revisited rather than deleted."""
    page = PAGE.read_text()
    assert '<h2 class="hh">' in page
    assert page.count('<article class="hole">') == 4
    score = re.search(r"<dt>mutation score</dt><dd>(.*?)</dd>", page)
    assert score, "the score should still be present, just not the conclusion"
    assert f"<h1>{score.group(1)}" not in page
    assert f'<h2 class="hh">{score.group(1)}' not in page


@needs_page
def test_the_two_survival_kinds_are_not_flattened():
    """Both groups render, each with its own meaning line, so a reader cannot read a coverage gap
    as a broken check."""
    page = PAGE.read_text()
    assert page.count('<section class="hgroup">') == 2
    assert "Blind spot" in page and "Coverage gap" in page
    assert "no check in the suite guards this shape" in page
    assert "documents the limit" in page


@needs_page
def test_each_card_carries_its_own_retrieval_expression():
    page = PAGE.read_text()
    exprs = re.findall(r"jq '(\.holes\.[a-z_]+\[\d+\])'", page)
    assert len(exprs) == 4 and len(set(exprs)) == 4


@needs_page
def test_the_explorer_needs_no_javascript():
    page = PAGE.read_text()
    start = page.index('<section id="holes">')
    sec = page[start:page.index("</section>", page.rindex("</article>", start))]
    assert "<script" not in sec and "onclick" not in sec


# ---------------------------------------------------------------- pairing, state, scope limits

@needs_bundle
def test_clean_form_comes_from_the_pinned_manifest_not_the_results(doc):
    """The clean form is an INPUT to the run, so it is read from the manifest that was hashed
    before the run rather than from the output. Reading it from the results would let a rerun
    redefine what "clean" meant, which is the drift the manifest exists to prevent."""
    manifest = json.loads((HOME / "evalmut/docs/dogfood_fixtures.json").read_text())
    withm = {h.operator: h.clean for h in H.holes(doc, manifest)}
    assert all(withm.values()), "every survivor should resolve a clean form"
    # Same bundle, no manifest: the cards must degrade honestly rather than invent a clean form.
    without = H.holes(doc, None)
    assert all(h.clean == "" for h in without)
    assert all("one-sided" in h.pairing for h in without)


@needs_bundle
def test_a_manifest_that_renames_a_case_does_not_silently_mispair(doc):
    """A clean form attached to the wrong case is worse than none: it would show a reader a pair
    that never happened. The join is by case name, so a renamed case must drop out, not shift."""
    manifest = json.loads((HOME / "evalmut/docs/dogfood_fixtures.json").read_text())
    for c in manifest["cases"]:
        if c["name"] == "contains":
            c["name"] = "contains_RENAMED"
    got = {h.operator: h.clean for h in H.holes(doc, manifest) if h.case == "contains"}
    assert got and all(v == "" for v in got.values()), "a renamed case must not borrow a pair"


@needs_page
def test_every_card_names_its_state_in_words(doc=None):
    """Colour alone is not a state. A reader meeting an amber card with no word for it reads it
    as failure, which is the pass/fail collapse the four-state vocabulary exists to prevent."""
    page = PAGE.read_text()
    assert page.count('class="st"') == 4
    assert page.count("Survived</span>") >= 4 or page.count("Survived") >= 4


@needs_page
def test_the_page_states_what_survived_means_as_a_pair():
    page = PAGE.read_text()
    assert "clean form and the defective form BOTH passed" in page
    assert "not evidence that the system under test misbehaves in production" in page
    assert page.count("Both forms passed this check") == 4


@needs_page
def test_scope_limits_are_on_the_page_not_in_a_readme():
    """Hypothesis-generating, corpus-bound, and no framework-wide score: all three visible."""
    page = PAGE.read_text()
    for needed in ("Hypothesis-generating",
                   "nothing on this page\nconfirms detection power against an external suite",
                   "No percentage here is a score for any\nframework",
                   "Independent validity is unestablished"):
        assert needed in page, f"missing scope limit: {needed!r}"


@needs_page
def test_every_card_carries_a_replay_reference():
    page = PAGE.read_text()
    assert page.count("replay: the pinned route") == 4


@needs_page
def test_all_four_states_still_appear_in_the_legend():
    """The explorer must not quietly become the only place states are defined."""
    page = PAGE.read_text()
    for label in ("Verified", "Survived", "Incomplete", "Invalidated"):
        assert label in page
