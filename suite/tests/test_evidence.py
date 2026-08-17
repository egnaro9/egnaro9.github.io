"""The drawer is a claim about where numbers come from, so it is tested like one.

The load-bearing test is `test_rendered_commands_reproduce_the_shown_values`: it reads the shipped
HTML, pulls each (shown value, command) pair out of the table a visitor actually sees, RUNS the
command, and requires the output to match. Testing the generator would only prove that the
function agrees with itself. Every other test here exists to prove this one can fail.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import evidence  # noqa: E402
import runner  # noqa: E402
from evidence import ProvenanceError, producing_command, source, value  # noqa: E402

HOME = pathlib.Path.home()
BUNDLE = "docs/dogfood_gradecore.json"
JQ = shutil.which("jq")
PAGE = pathlib.Path(__file__).resolve().parents[1] / "runner.html"
needs_jq = pytest.mark.skipif(not JQ, reason="jq not installed")
needs_repo = pytest.mark.skipif(not (HOME / "evalmut" / BUNDLE).exists(),
                                reason="evalmut bundle not on this machine")


# ---------------------------------------------------------------- the binding can fail

@needs_repo
@needs_jq
def test_disagreement_between_the_two_derivations_raises():
    """The cross-check's whole value is that it can fail. A pair that always agrees is decoration.

    Here the Python side deliberately returns a wrong number while the jq expression stays
    correct, which is exactly the shape of a stale hand-maintained value."""
    src = source("evalmut", BUNDLE)
    doc = json.loads((HOME / "evalmut" / BUNDLE).read_text())
    with pytest.raises(ProvenanceError) as e:
        value(src, doc, "caught", ".tally.caught", lambda d: d["tally"]["caught"] + 1)
    assert "must not pick a winner" in str(e.value)


@needs_repo
@needs_jq
def test_a_wrong_path_cannot_render_a_right_number():
    """A pointer that does not lead to the value fails loudly rather than displaying a caption."""
    src = source("evalmut", BUNDLE)
    doc = json.loads((HOME / "evalmut" / BUNDLE).read_text())
    with pytest.raises(ProvenanceError):
        value(src, doc, "caught", ".tally.cauhgt", lambda d: d["tally"]["caught"])


@needs_repo
def test_recorded_command_is_extracted_not_typed():
    assert producing_command("evalmut", BUNDLE) == (
        "evalmut run demos/dogfood_gradecore.py --json --all")


@needs_repo
def test_unknown_artifact_refuses_rather_than_guessing():
    with pytest.raises(ProvenanceError) as e:
        producing_command("evalmut", "docs/not_emitted_by_anything.json")
    assert "no entry emitting" in str(e.value)


@needs_repo
def test_digest_matches_an_independent_hasher():
    """Our sha256 is checked against the system tool, not against another call to hashlib."""
    src = source("evalmut", BUNDLE)
    out = subprocess.run(["shasum", "-a", "256", str(HOME / src.rel)],
                         capture_output=True, text=True, check=True).stdout.split()[0]
    assert src.sha256 == out


# ---------------------------------------------------------------- the page a visitor reads

def _rows(page: str) -> list[tuple[str, str]]:
    """(shown value, command) for every provenance row in the rendered page."""
    out = []
    for tr in re.findall(r"<tr><td>.*?</tr>", page, re.S):
        shown = re.search(r'<td class="n">(.*?)</td>', tr)
        cmd = re.search(r"<code>(.*?)</code>", tr, re.S)
        if shown and cmd:
            out.append((html.unescape(shown.group(1)), html.unescape(cmd.group(1))))
    return out


@pytest.mark.skipif(not PAGE.exists(), reason="page not built")
def test_the_page_carries_a_drawer_for_every_headline_number():
    page = PAGE.read_text()
    assert page.count('<details class="ev">') >= 2, "headline and step 1 each need a route"
    rows = _rows(page)
    assert len(rows) >= 9, f"expected the headline and audit values, found {len(rows)}"


@needs_repo
@needs_jq
@pytest.mark.skipif(not PAGE.exists(), reason="page not built")
def test_rendered_commands_reproduce_the_shown_values():
    """Run what the page tells a reader to run, against the file the page names.

    This is the assertion that closes the loop. It does not consult the generator, the Source
    object, or any Python derivation: it takes the command text out of the HTML, executes it in
    the repo the page points at, and compares to the number printed beside it."""
    repo = HOME / "evalmut"
    checked = 0
    for shown, cmd in _rows(PAGE.read_text()):
        m = re.fullmatch(r"jq '(.+)' (\S+)", cmd)
        assert m, f"row command is not runnable as printed: {cmd!r}"
        expr, target = m.group(1), m.group(2)
        p = subprocess.run([JQ, "-e", expr, target], cwd=repo, capture_output=True, text=True)
        assert p.returncode in (0, 1), f"{cmd} failed: {p.stderr.strip()}"
        raw = json.loads(p.stdout)
        rendered = f"{raw:.1%}" if isinstance(raw, float) else str(raw)
        assert rendered == shown, f"page shows {shown!r} for `{cmd}` which returns {rendered!r}"
        checked += 1
    assert checked >= 9


@needs_repo
@pytest.mark.skipif(not PAGE.exists(), reason="page not built")
def test_page_digest_matches_the_file_on_disk_now():
    """A stale drawer is the failure mode this whole module exists to prevent, so it is asserted
    against the current bytes rather than against the value captured at build time."""
    page = PAGE.read_text()
    shown = re.search(r"<dt>sha256</dt><dd>([0-9a-f]{64})</dd>", page)
    assert shown, "the drawer must publish a digest"
    live = subprocess.run(["shasum", "-a", "256", str(HOME / "evalmut" / BUNDLE)],
                          capture_output=True, text=True, check=True).stdout.split()[0]
    assert shown.group(1) == live, "the page's digest no longer matches the artifact; rebuild"


@pytest.mark.skipif(not PAGE.exists(), reason="page not built")
def test_replay_route_is_pinned_to_a_commit_not_to_main():
    """`git clone && run` off main reproduces whatever is true today, which is not a replay of
    this claim. The route must name the commit the numbers came from."""
    page = PAGE.read_text()
    m = re.search(r"git checkout ([0-9a-f]{7,40})", page)
    assert m, "the replay route must pin a commit"
    assert "checkout main" not in page


@pytest.mark.skipif(not PAGE.exists(), reason="page not built")
def test_the_drawer_needs_no_javascript():
    """Evidence a skeptic can only reach by running our script is evidence with a precondition."""
    page = PAGE.read_text()
    body = page[page.index('<details class="ev">'):page.index("</details>")]
    assert "onclick" not in body and "<script" not in body


@needs_repo
def test_cross_check_state_is_reported_not_assumed(monkeypatch):
    """With jq absent the page still renders, and says the commands were not executed here.

    The tempting bug is to treat 'no checker available' as 'nothing wrong'. That is the exact
    failure this estate has hit before: a gate that could not tell 'checked and clean' from
    'never checked'."""
    monkeypatch.setattr(evidence, "JQ", None)
    src = source("evalmut", BUNDLE)
    doc = json.loads((HOME / "evalmut" / BUNDLE).read_text())
    v = value(src, doc, "caught", ".tally.caught", lambda d: d["tally"]["caught"])
    assert v.cross_checked is False
    assert "NOT" in evidence.unchecked_note([v])
    assert "matched" not in evidence.unchecked_note([v])


@needs_repo
@needs_jq
def test_build_refuses_when_a_displayed_value_drifts(tmp_path, monkeypatch):
    """End to end: change the artifact under the page and the build must not quietly re-render a
    number whose Python derivation was pinned elsewhere."""
    src = source("evalmut", BUNDLE)
    doc = json.loads((HOME / "evalmut" / BUNDLE).read_text())
    doc["tally"]["caught"] += 7  # the parsed doc drifts away from the bytes jq will read
    with pytest.raises(ProvenanceError):
        runner.claim_values(src, doc)


@needs_repo
def test_the_cited_commit_is_the_one_that_touched_the_artifact_not_head():
    """Pinning to HEAD is a false provenance claim, and it churns this page on unrelated commits.

    Caught in production by the staleness gate: a docs-only commit to evalmut moved the commit
    this page cites, though it could not change a byte of the bundle. The assertion is written
    against `git log -1 -- <path>` rather than against a captured string, so it keeps holding as
    the bundle is legitimately re-emitted."""
    src = source("evalmut", BUNDLE)
    expected = subprocess.run(
        ["git", "-C", str(HOME / "evalmut"), "log", "-1", "--format=%H", "--", BUNDLE],
        capture_output=True, text=True, check=True).stdout.strip()[:12]
    assert src.commit == expected
    head = subprocess.run(["git", "-C", str(HOME / "evalmut"), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()[:12]
    if head != expected:
        assert src.commit != head, "the page is pinned to HEAD, which did not produce the bundle"
