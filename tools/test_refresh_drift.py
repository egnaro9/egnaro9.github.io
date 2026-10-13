"""Tests for refresh_drift.py.

The script's job is to *refuse* more readily than it writes, so most of these
tests assert that a bad paragraph changes nothing and exits non-zero. They run
fully offline: `--source` takes a `file://` URL pointing at a fixture, so the
whole fetch -> validate -> splice -> write path is exercised without network.

This is also the coverage the script's own docstring promises for
`--print-current` ("the thing the PR body shows is covered by the same tests").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import refresh_drift as rd

# A minimal page with the two markers and a placeholder paragraph between them.
PAGE = """<!doctype html>
<html><body>
  <section>
    <!-- drift:start — generated -->
    <p>old placeholder paragraph that is here before the splice</p>
    <!-- drift:end -->
  </section>
</body></html>
"""

GOOD = ("<strong>Sonnet 4.6</strong> leads this week at 0.91 accuracy while two "
        "models slipped; the board has been green for nine consecutive runs.")


def _src(tmp_path: Path, payload: dict) -> str:
    p = tmp_path / "narrative.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p.as_uri()  # file:// URL urllib can open


def _page(tmp_path: Path, html: str = PAGE) -> Path:
    p = tmp_path / "index.html"
    p.write_text(html, encoding="utf-8")
    return p


# --- splice(): pure string surgery -----------------------------------------

def test_splice_replaces_between_markers_and_keeps_them():
    out = rd.splice(PAGE, "<p>fresh</p>")
    assert "<p>fresh</p>" in out
    assert "old placeholder" not in out
    assert rd.START in out and rd.END in out  # markers survive


def test_splice_preserves_marker_indentation():
    out = rd.splice(PAGE, "<p>fresh</p>")
    # the new paragraph sits at the same indent as the drift:end marker (4 sp)
    assert "\n    <p>fresh</p>\n    <!-- drift:end -->" in out


def test_splice_missing_start_marker_raises():
    with pytest.raises(SystemExit):
        rd.splice("<html>no markers here</html>", "<p>x</p>")


def test_splice_missing_end_marker_raises():
    with pytest.raises(SystemExit):
        rd.splice("<!-- drift:start -->\nno close", "<p>x</p>")


# --- main(): the refuse-or-write policy, run offline over file:// -----------

def test_main_writes_good_paragraph(tmp_path):
    page = _page(tmp_path)
    rc = rd.main(["--source", _src(tmp_path, {"html": GOOD, "updated": "2026-07-20"}),
                  "--index", str(page)])
    assert rc == 0
    assert GOOD in page.read_text(encoding="utf-8")
    assert "old placeholder" not in page.read_text(encoding="utf-8")


def test_main_wraps_bare_paragraph_in_p(tmp_path):
    page = _page(tmp_path)
    rd.main(["--source", _src(tmp_path, {"html": GOOD}), "--index", str(page)])
    assert f"<p>{GOOD}</p>" in page.read_text(encoding="utf-8")


def test_main_refuses_too_short(tmp_path):
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    rc = rd.main(["--source", _src(tmp_path, {"html": "too short"}), "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before  # unchanged


def test_main_refuses_disallowed_tag(tmp_path):
    # An <img/onerror=...> is exactly the payload the old block-list walked past.
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    payload = {"html": "<p>a paragraph long enough to pass the length gate, "
                        "but with a sneaky <img/onerror=alert(1)> in the middle "
                        "that the allow-list must catch and refuse outright.</p>"}
    rc = rd.main(["--source", _src(tmp_path, payload), "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before


def test_main_refuses_event_handler(tmp_path):
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    payload = {"html": "<p>a long-enough paragraph with an inline handler "
                       "<a href='#' onclick='steal()'>click</a> that must be "
                       "refused even though every tag is on the allow-list.</p>"}
    rc = rd.main(["--source", _src(tmp_path, payload), "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before


def test_main_refuses_nested_markers(tmp_path):
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    payload = {"html": "<p>a long-enough paragraph that tries to smuggle a "
                       "drift:start marker inside itself, which would break the "
                       "next splice and must therefore be refused up front.</p>"}
    rc = rd.main(["--source", _src(tmp_path, payload), "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before


def test_main_check_reports_behind_without_writing(tmp_path):
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    rc = rd.main(["--source", _src(tmp_path, {"html": GOOD}), "--index", str(page), "--check"])
    assert rc == 1                                   # behind
    assert page.read_text(encoding="utf-8") == before  # but wrote nothing


def test_main_idempotent_second_run_is_noop(tmp_path):
    page = _page(tmp_path)
    src = _src(tmp_path, {"html": GOOD})
    rd.main(["--source", src, "--index", str(page)])
    after_first = page.read_text(encoding="utf-8")
    rc = rd.main(["--source", src, "--index", str(page)])  # already matches
    assert rc == 0
    assert page.read_text(encoding="utf-8") == after_first  # no second change


def test_main_unreadable_source_refuses(tmp_path):
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    missing = (tmp_path / "nope.json").as_uri()
    rc = rd.main(["--source", missing, "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before


# --- --print-current: the path the PR body renders -------------------------

def test_print_current_strips_tags_and_whitespace(tmp_path, capsys):
    html = PAGE.replace("old placeholder paragraph that is here before the splice",
                        "<strong>Hi</strong>   there\n  friend")
    page = _page(tmp_path, html)
    rc = rd.main(["--print-current", "--index", str(page)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "Hi there friend"


# --- house style: no em-dash reaches the page ------------------------------

GENERATED_WITH_DASHES = (
    "A frozen, deterministically-graded suite against <strong>17 models across 5 labs</strong>. "
    "<strong>OpenAI's cheaper tiers match its own flagship</strong> \u2014 GPT-5 mini at 100% and "
    "GPT-5 nano at 100%, against GPT-5 at 100% \u2014 so within that lab, on this suite, paying "
    "more buys no accuracy. <strong>Grok 4.3 answers fastest and scores lowest</strong> "
    "(300 ms at 80%) \u2014 a speed/quality tradeoff you can see rather than argue about. "
    "<em>Generated from the run of 13 Oct 2026 \u2014 this paragraph is rebuilt from the "
    "board's own numbers, never hand-written.</em>")


def test_house_style_places_every_generated_em_dash():
    """The four shapes model-drift's narrative.py actually emits, 2026-10-13."""
    out = rd.house_style(GENERATED_WITH_DASHES)
    assert "\u2014" not in out
    assert "flagship</strong>: GPT-5 mini" in out
    assert "at 100%, so within that lab" in out
    assert "(300 ms at 80%), a speed/quality tradeoff" in out
    assert "13 Oct 2026. This paragraph is rebuilt" in out


def test_house_style_moves_only_punctuation():
    """Every number and name survives: strip the punctuation that changed and
    the two texts carry the same words in the same order."""
    import re
    words = lambda s: re.findall(r"[a-z0-9%]+(?:[.-][a-z0-9%]+)*", s.lower())
    out = rd.house_style(GENERATED_WITH_DASHES)
    assert words(out) == words(GENERATED_WITH_DASHES)


def test_main_writes_the_page_without_em_dashes(tmp_path):
    page = _page(tmp_path)
    rc = rd.main(["--source", _src(tmp_path, {"html": GENERATED_WITH_DASHES}),
                  "--index", str(page)])
    assert rc == 0
    body = page.read_text(encoding="utf-8")
    para = body[body.find("-->", body.find("drift:start")) + 3:body.find("drift:end")]
    assert "\u2014" not in para
    assert "GPT-5 nano at 100%" in para


def test_main_refuses_an_em_dash_it_cannot_place(tmp_path):
    """A dash with no spaces around it has no safe replacement. Refuse and
    leave the page alone, as every other refusal here does."""
    page = _page(tmp_path)
    before = page.read_text(encoding="utf-8")
    rc = rd.main(["--source", _src(tmp_path, {"html": GOOD + " A\u2014B."}),
                  "--index", str(page)])
    assert rc == 1
    assert page.read_text(encoding="utf-8") == before
