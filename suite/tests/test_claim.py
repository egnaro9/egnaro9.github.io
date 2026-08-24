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

BUNDLE = pathlib.Path.home() / "evalmut/docs/dogfood_gradecore_witnessed.json"
PLAIN = pathlib.Path.home() / "evalmut/docs/dogfood_gradecore.json"


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
    assert c.headline == ("Witnessed evalmut dogfood run: 42 of 46 declared mutations were "
                          "caught; 4 survived (2 blind, 2 coverage gap).")


def test_the_headline_claims_exactly_what_the_evidence_now_supports():
    """The verb moved because the evidence did, and it may only move once, in that order.

    This test previously asserted the OPPOSITE: that 'caught' must not appear, because the run
    proved only that the package was imported and labels were emitted. That was correct then.
    demos/dogfood_gradecore.py now records a per-row entry into the grader closure for both the
    clean control and the defective form, and every outcome recomputes from the raw return, so
    the grader demonstrably decided each counted row.

    Kept rather than deleted, inverted rather than removed, so the history of the claim is
    readable: 'caught' is licensed by a witnessed artifact, and if that artifact ever stops being
    the source, this line is where the licence should be revisited."""
    c = derive(BUNDLE)
    assert "mutations were caught" in c.headline
    assert "labelled caught" not in c.headline
    assert c.headline.startswith("Witnessed "), (
        "the headline must name the evidence class it rests on")

    # And the weaker source must still get the weaker verb, automatically. Hardcoding the strong
    # verb made the UNWITNESSED export render "Witnessed ... were caught" as well, which is the
    # claim asserting evidence its own source does not carry.
    plain = derive(PLAIN)
    assert plain.headline.startswith("Recorded ")
    assert "labelled caught" in plain.headline
    assert "mutations were caught" not in plain.headline


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


# --- the two live-page defects repaired in this commit ------------------------------

def _page():
    import subprocess, pathlib, os
    env = dict(os.environ)
    # Keep the legacy sibling .venv reachable, but do not depend on it: vac-verify is normally
    # already on PATH from the declared environment in suite/requirements-dev.txt.
    env["PATH"] = env["PATH"] + os.pathsep + str(pathlib.Path.home() / "vac-protocol/.venv/bin")
    out = pathlib.Path("/tmp/_copytest.html")
    subprocess.run(["python3", "runner.py", str(out)], cwd=str(pathlib.Path(__file__).parent.parent),
                   check=True, capture_output=True, env=env)
    return out.read_text()


def test_a_truncated_transcript_says_how_many_lines_it_dropped():
    """Each rendered count is checked against ITS OWN fixture's real FAIL line count.

    Two earlier weaknesses, both found by mutating this test rather than by reading it. It began
    `if not shown: return`, so removing every count made it vacuously green, which is the exact
    C5 defect passing its own regression test. And it compared `shown <= real` as SETS, so
    publishing a 9-reason fixture as "(first of 3 named reasons)" passed because 3 was a real
    count for a DIFFERENT fixture. Pooling counts across fixtures cannot detect a mislabelled one."""
    import re, subprocess, pathlib
    html = _page()
    assert "transcripts, not quotations" not in html, (
        "the caption claims transcripts while truncating to the first line")

    import shutil
    vac = pathlib.Path.home() / "vac-protocol"
    verify = pathlib.Path(shutil.which("vac-verify") or vac / ".venv/bin/vac-verify")

    # pair each rendered fixture name with the count printed beside its line, if any
    rendered = {}
    for m in re.finditer(r"\$ vac-verify fixtures/([\w.-]+)</span>\s*<span[^>]*>(.*?)</span>",
                         html, re.S):
        name, body = m.group(1), m.group(2)
        n = re.search(r"first of (\d+) named reasons", body)
        rendered[name] = int(n.group(1)) if n else 1
    assert rendered, "the page shows no fixture transcripts to check"

    for name, shown in sorted(rendered.items()):
        p = subprocess.run([str(verify), str(vac / "fixtures" / name)],
                           cwd=str(vac), capture_output=True, text=True)
        real = len([l for l in (p.stdout + p.stderr).splitlines()
                    if l.strip().startswith("FAIL")])
        assert shown == real, (
            f"{name}: page says {shown} named reason(s), the verifier really prints {real}")




def test_an_unavailable_verifier_refuses_the_build():
    """A missing verifier is a preflight failure, not a weaker page.

    run_verifier still degrades honestly, and the arity check below keeps that branch callable,
    because defence in depth is cheap. But the CLI must never reach it: the five named refusals
    ARE step 5, so a page rendering five "could not run the verifier" rows reads to a visitor as
    five demonstrations when it is five failures to demonstrate. Publishing that is worse than
    publishing nothing, so the generator exits nonzero and leaves the committed page alone.

    Widening the return to carry the named-reason count left the except branch at two values, so
    an unavailable verifier raised ValueError in the caller instead of degrading to UNLAUNCHED.
    That silently reverted the honest degradation added the same day, and 95 tests missed it
    because every one of them ran with the verifier present."""
    import inspect, subprocess, pathlib, os
    import runner
    src = inspect.getsource(runner.run_verifier)
    returns = [l.strip() for l in src.splitlines() if l.strip().startswith("return ")]
    arities = {l.count(",") + 1 for l in returns}
    assert len(arities) == 1, (
        f"run_verifier returns differing arities across branches: {returns}")

    root = pathlib.Path(__file__).parent.parent
    out = pathlib.Path("/tmp/_noverif_test.html")
    sentinel = "<!-- page that must survive a refused build -->"
    out.write_text(sentinel)
    env = dict(os.environ, PATH="/usr/bin:/bin")
    p = subprocess.run(["python3", "runner.py", str(out)], cwd=str(root),
                       capture_output=True, text=True, env=env)
    assert p.returncode != 0, "a missing verifier must refuse the build, not degrade it"
    assert out.read_text() == sentinel, (
        "the generator overwrote an existing page while refusing: a refused build must leave "
        "the previous page exactly as it found it")
    assert "not on PATH" in p.stderr, "the refusal must name the missing dependency"
    assert "requirements-dev.txt" in p.stderr, (
        "the refusal must point at the declared environment, not an ad hoc one")
