"""The in-browser verifier held to the claim the page makes about it.

The page says a tamper demo alters an in-memory copy and shows a NAMED rejection
path. Three things have to be true for that sentence to survive, and each one is
a test below rather than a paragraph.

  1. The names are the reference verifier's names. Not similar ones, not ones
     typed into a .js file next to a comment saying they came from verify.py.
     Extracted, generated, and addressed by identifier, so a rename breaks.
  2. The refusals are the ones vac-verify emits for the same bytes. Every
     mutation the page offers is materialised on disk and run through the real
     verifier, and the two transcripts must agree line for line.
  3. The claim tracks the artifact. If the bundle or the reference implementation
     cannot be read, the mode line must stop advertising the demo.

The mutation test is the load-bearing one. It runs the SAME mutation functions
the page runs, so a mutation that stops exercising its refusal fails here rather
than quietly showing a visitor a path that no longer exists.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

SUITE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE))
import browserverify  # noqa: E402
import refusals  # noqa: E402

VAC = pathlib.Path.home() / "vac-protocol"
VERIFY = VAC / ".venv" / "bin" / "vac-verify"
BUNDLE = VAC / "examples" / "outsider"
NODE = shutil.which("node")
HANDWRITTEN_JS = ("vacbrowser.js", "bv_ui.js", "bv_harness.js")

needs_node = pytest.mark.skipif(not NODE, reason="node is not on PATH")
needs_vac = pytest.mark.skipif(
    not (VERIFY.exists() and BUNDLE.is_dir()),
    reason="the reference verifier or the example bundle is not on this machine")


def _node(*args):
    p = subprocess.run([NODE, *args], capture_output=True, text=True, cwd=str(SUITE),
                       timeout=120)
    assert p.returncode == 0, f"node {' '.join(args)} failed:\n{p.stderr}"
    return json.loads(p.stdout)


def _cli(target) -> list[str]:
    p = subprocess.run([str(VERIFY), str(target)], capture_output=True, text=True,
                       cwd=str(VAC), timeout=120)
    return [l[len("FAIL "):] for l in p.stdout.splitlines() if l.startswith("FAIL ")]


# --------------------------------------------------------------- vocabulary
@pytest.mark.skipif(not (VAC / "vac" / "verify.py").exists(),
                    reason="the reference implementation is not on this machine")
def test_the_generated_vocabulary_is_current():
    """The committed table must be what verify.py says TODAY.

    A stale table is worse than no table: it looks like a shared vocabulary and
    is a copy of an old one."""
    live = json.loads(json.dumps(refusals.extract()))
    committed = json.loads((SUITE / "refusals.json").read_text())
    assert live == committed, "run `python3 refusals.py`: verify.py has moved"
    assert (SUITE / "refusals.gen.js").read_text() == refusals.as_js(live)


def test_no_refusal_name_is_typed_into_hand_written_js():
    """The requirement the whole design exists to satisfy.

    If a name appears as a literal in a hand-written .js file, the browser has
    its own copy of the vocabulary and the generation step is decoration."""
    names = [r["name"] for r in json.loads((SUITE / "refusals.json").read_text())["refusals"]]
    assert names, "the vocabulary is empty, so this test proves nothing"
    for js in HANDWRITTEN_JS:
        text = (SUITE / js).read_text()
        found = sorted(n for n in names if n in text)
        assert not found, f"{js} spells {found} instead of addressing the generated table"


def test_the_generated_table_refuses_a_name_it_does_not_carry():
    """A renamed refusal must throw at the point of use, not print a stale name."""
    if not NODE:
        pytest.skip("node is not on PATH")
    p = subprocess.run(
        [NODE, "-e",
         "require('./refusals.gen.js');"
         "try { globalThis.VAC_REFUSALS.NO_SUCH_REFUSAL; console.log('NO THROW'); }"
         "catch (e) { console.log('THREW'); }"],
        capture_output=True, text=True, cwd=str(SUITE), timeout=60)
    assert p.stdout.strip() == "THREW", p.stdout + p.stderr


def test_nothing_written_here_carries_a_long_dash():
    """A standing rule for everything this repo emits, enforced rather than remembered.

    The two characters are spelled by codepoint on purpose: a test that had to
    contain them in order to forbid them would be the first thing it caught."""
    em, en, escaped = "\u2014", "\u2013", "\\u2014"
    for name in (*HANDWRITTEN_JS, "refusals.py", "browserverify.py",
                 "tests/test_browser_verifier.py"):
        text = (SUITE / name).read_text().replace(escaped, "")
        assert em not in text, f"{name} carries an em dash"
        assert en not in text, f"{name} carries an en dash"


# ------------------------------------------------------------ the verifier
@needs_node
@needs_vac
def test_the_clean_bundle_passes_in_both_implementations():
    got = _node("bv_harness.js", "verify", str(BUNDLE))
    assert _cli(BUNDLE) == [] and got["failures"] == []
    assert got["verdict"] == "PASS"
    assert got["ran"], "a PASS with no check that ran is not a pass"


@needs_node
@needs_vac
def test_every_mutation_produces_the_reference_verifier_s_own_refusal(tmp_path):
    """The claim on the page, one case per offered mutation.

    Both sides see the same bytes, so a disagreement means the page would show a
    refusal the reference implementation does not emit."""
    muts = _node("bv_harness.js", "list")
    assert len(muts) >= 3
    for m in muts:
        dest = tmp_path / m["id"]
        got = _node("bv_harness.js", "mutate", str(BUNDLE), m["id"], str(dest))
        want = _cli(dest)
        assert want, f"{m['id']} no longer makes vac-verify refuse anything"
        assert got["failures"] == want, f"{m['id']} disagrees with vac-verify"
        assert sorted(set(got["names"])) == sorted(set(m["expect"])), (
            f"{m['id']} no longer exercises the refusal it was written for")


@needs_node
@needs_vac
def test_the_three_named_mutations_are_offered():
    """The page promises these by name, so their absence is a broken claim."""
    ids = {m["id"] for m in _node("bv_harness.js", "list")}
    assert {"sha256-flip", "drop-artifact", "blank-the-limitations"} <= ids


@needs_node
@needs_vac
def test_mutations_never_touch_the_served_bytes(tmp_path):
    """Every run re-derives its copy, so the bundle on the page cannot drift."""
    before = {p.name: p.read_bytes() for p in BUNDLE.iterdir() if p.is_file()}
    for m in _node("bv_harness.js", "list"):
        _node("bv_harness.js", "mutate", str(BUNDLE), m["id"], str(tmp_path / m["id"]))
    after = {p.name: p.read_bytes() for p in BUNDLE.iterdir() if p.is_file()}
    assert before == after


@needs_node
@needs_vac
def test_an_unported_profile_is_never_a_pass():
    """Fail closed. The fixtures declare a profile this port does not implement,
    and the honest answer to that is INCOMPLETE, never green."""
    fixture = VAC / "fixtures" / "valid"
    if not fixture.is_dir():
        pytest.skip("the fixture set is not on this machine")
    got = _node("bv_harness.js", "verify", str(fixture))
    assert got["unported"], "this fixture was expected to declare an unported profile"
    assert got["verdict"] == "INCOMPLETE"
    assert any("does not implement" in s for s in got["scope"]["notRun"])


@needs_node
@needs_vac
def test_the_scope_statement_is_measured_and_not_boilerplate():
    """A run that stops at a missing manifest must not claim it hashed anything."""
    stopped = _node("bv_harness.js", "mutate", str(BUNDLE), "no-manifest")
    assert stopped["scope"]["ran"] == []
    assert any("never reached" in s for s in stopped["scope"]["notRun"])
    full = _node("bv_harness.js", "verify", str(BUNDLE))
    assert any("crypto.subtle" in s for s in full["scope"]["ran"])
    # rows-aggregate-v1 defines no stamp binding, so the page must not claim one
    assert any("no stamp was compared" in s for s in full["scope"]["notRun"])


def test_the_port_covers_every_refusal_except_the_archive_path():
    """The page prints this as a measured claim, so it has to hold.

    unsafe-archive is the only name verify.py reaches through unpacking a tar,
    and a page that embeds an already-unpacked bundle never takes that path."""
    vocab, _ = refusals.load()
    covered, missing = browserverify.port_coverage(vocab)
    archive = {r["name"] for r in vocab["refusals"] if r["archive_only"]}
    assert set(missing) == archive, (
        f"the port no longer references {sorted(set(missing) - archive)}, so the page "
        "would be claiming a coverage it does not have")
    assert len(covered) == len(vocab["refusals"]) - len(archive)


# ------------------------------------------------------------------ the page
def test_the_panel_is_built_from_the_committed_bundle():
    p = browserverify.panel()
    if not p["ok"]:
        pytest.skip(f"the panel is unavailable on this machine: {p['mode']}")
    blob = browserverify.embed_bundle()
    assert {f["path"] for f in blob["files"]} == {
        q.relative_to(browserverify.BUNDLE).as_posix()
        for q in browserverify.BUNDLE.rglob("*") if q.is_file()}
    assert "vac.json" in {f["path"] for f in blob["files"]}
    assert blob["commit"] and len(blob["commit"]) >= 7


def test_the_mode_line_tracks_whether_the_demo_exists():
    """The defect this whole change repairs: a page advertising a mode it lacks."""
    p = browserverify.panel()
    if p["ok"]:
        assert "in-memory copy" in p["mode"] and 'id="bv"' in p["html"]
    else:
        assert "NOT in this build" in p["mode"] and 'id="bv"' not in p["html"]


def test_the_built_page_carries_the_verifier_and_the_bundle(tmp_path):
    """Built to a scratch path and inspected, never by regenerating the artifact
    the test claims to check."""
    p = browserverify.panel()
    if not p["ok"]:
        pytest.skip("the panel is unavailable on this machine")
    dest = tmp_path / "runner.html"
    r = subprocess.run([sys.executable, str(SUITE / "runner.py"), str(dest)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    page = dest.read_text()
    assert 'id="bv-bundle"' in page and "VACBROWSER" in page
    assert "crypto.subtle" in page
    assert p["mode"] in page
    blob = json.loads(page.split('id="bv-bundle">')[1].split("</script>")[0])
    assert blob["files"] and all(f["b64"] for f in blob["files"])


# --- Five page-copy claims, each pinned to the artifact it describes. -------------------
# An adversarial pass found every one of these sentences false against the code it described.
# They are tested against DERIVED FACTS, not snapshots, so a sentence cannot drift back into
# truth-by-assertion while the thing it describes changes underneath it.

def _page():
    import subprocess, pathlib, os
    env = dict(os.environ)
    env["PATH"] = str(pathlib.Path.home() / "vac-protocol/.venv/bin") + os.pathsep + env["PATH"]
    out = pathlib.Path("/tmp/_copytest.html")
    subprocess.run(["python3", "runner.py", str(out)], cwd=str(pathlib.Path(__file__).parent.parent),
                   check=True, capture_output=True, env=env)
    return out.read_text()


def test_the_page_does_not_claim_the_replay_block_prints_on_every_run():
    """bv_ui.js guards renderReplay, so an unreadable manifest prints no replay block.

    The page said it "printed with every run". Two of its own buttons, break-json and
    no-manifest, are exactly the path where it does not."""
    html = _page()
    assert "printed with every run is the bundle's own" not in html, (
        "the page claims the replay block prints on every run; two of its buttons disprove it")
    assert "break-json and no-manifest" in html, (
        "the page must name the case where no replay block is echoed")


def test_the_cli_scope_quote_is_not_trimmed():
    """Every fixed line of verify.py's _report appears in the RENDERED QUOTE BLOCK.

    An earlier version filtered out the line punctuating with a long dash, justified by a comment
    claiming the page never reaches that path. break-json and no-manifest are that path.

    Scoped to <p class="bvquote"> on purpose. An earlier version of this test searched the whole
    page, and re-adding the exact filter it was written against left it GREEN, because the dropped
    line still occurs inside the inlined refusals.gen.js data table. A test that its own target
    defect cannot turn red is worse than no test."""
    import html as _html, json, pathlib, re
    root = pathlib.Path(__file__).parent.parent
    vocab = json.loads((root / "refusals.json").read_text())
    page = _page()
    blocks = re.findall(r'<p class="bvquote">(.*?)</p>', page, re.S)
    assert blocks, "the page renders no CLI scope quote block at all"
    # unescape: the page renders issuer's as issuer&#x27;s, and _report's lines are raw text
    quote = _html.unescape("\n".join(blocks))
    for line in vocab["report_lines"]:
        stem = line.strip().split("\u2014")[0].strip()
        assert stem and stem in quote, (
            f"_report line missing from the rendered quote block (not merely from the page): {stem!r}")
    assert len(vocab["report_lines"]) == len(
        [l for l in vocab["report_lines"] if l.strip().split("\u2014")[0].strip() in quote]), (
        "the quote block is a subset of _report's fixed lines")


def test_the_first_button_is_not_described_as_a_mutation():
    """bv_ui.js renders 'Verify the bundle as served' before the sixteen mutations."""
    html = _page()
    assert "Every button below alters an" not in html, (
        "the first button alters nothing; the sentence contradicts it one paragraph later")
    assert "The first button re-verifies the" in html


def test_the_published_line_count_matches_wc_l():
    """text.count('\\n') + 1 counted the empty string after a trailing newline, publishing
    1624 for a 1623-line file, one off from wc -l and beside an exact sha256."""
    import json, pathlib
    src = (pathlib.Path.home() / "vac-protocol/vac/verify.py").read_text()
    vocab = json.loads((pathlib.Path(__file__).parent.parent / "refusals.json").read_text())
    assert vocab["derived_from"]["lines"] == len(src.splitlines()), (
        "the published line count disagrees with the file it names")
    assert str(vocab["derived_from"]["lines"]) in _page()
