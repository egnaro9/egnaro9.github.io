"""A receipt must be bound to the blob it reviewed, not to a pathname.

THE DEFECT. The gate resolved a receipt with `grep -F "<path> ::" | head -1`: the FIRST
line mentioning the path won, whatever it said and whenever it was written. So a receipt
recorded for an earlier version of a file kept satisfying every later version of it. A
claim could be rewritten from "nine" to "eleven hundred" and the commit passed green, with
the hook reporting success along a path where it never examined the new content. That is
the same shape as the defect the repo's own paper is about: a check that succeeds without
looking.

THE REPAIR. A receipt carries the blob it was written against:

    <path> :: EVIDENCE <ref> :: blob <sha1>

The hook reads the staged blob (`git rev-parse :<path>`) and accepts only a receipt line
carrying that exact blob. A receipt for a different blob is a hard refusal naming the
mismatch, not a silent pass. This also retires the ordering dependency: selection is by
blob, so line order in .claim-review-ack no longer decides anything.

These tests drive the real hook in a throwaway repo. They assert on the hook's exit status
and its stderr, because that is the whole of its contract.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "pre-commit"


def _run(cwd, *args, **kw):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)


@pytest.fixture
def repo(tmp_path):
    """A sandbox repo with the real hook installed and one claim-bearing file."""
    r = tmp_path / "r"
    (r / ".githooks").mkdir(parents=True)
    shutil.copy(HOOK, r / ".githooks" / "pre-commit")
    (r / ".githooks" / "pre-commit").chmod(0o755)
    _run(r, "git", "init", "-q", ".")
    _run(r, "git", "config", "user.email", "t@t.t")
    _run(r, "git", "config", "user.name", "t")
    _run(r, "git", "config", "core.hooksPath", ".githooks")
    (r / ".claim-paths").write_text("index.html\n")
    (r / "evidence.txt").write_text("the artifact\n")
    (r / "index.html").write_text("<p>nine claims replayed in CI</p>\n")
    _run(r, "git", "add", "index.html", "evidence.txt", ".claim-paths")
    # bootstrap commit needs a receipt for the current blob
    blob = _run(r, "git", "rev-parse", ":index.html").stdout.strip()
    (r / ".claim-review-ack").write_text(
        f"index.html :: EVIDENCE ./evidence.txt :: blob {blob}\n")
    # --no-verify: the bootstrap must not depend on the grammar under test, or every case
    # errors in setup instead of failing on its own assertion.
    assert _run(r, "git", "commit", "--no-verify", "-qm", "baseline").returncode == 0
    return r


def _stage_new_claim(r, text="<p>ELEVEN HUNDRED claims replayed in CI</p>\n"):
    (r / "index.html").write_text(text)
    _run(r, "git", "add", "index.html")
    return _run(r, "git", "rev-parse", ":index.html").stdout.strip()


# --------------------------------------------------------- 1. the false green must die
def test_receipt_for_a_previous_blob_is_refused(repo):
    """The baseline defect: a receipt written for the OLD blob must not pass the NEW one."""
    _stage_new_claim(repo)  # .claim-review-ack still names the bootstrap blob
    p = _run(repo, "git", "commit", "-qm", "rewrite the claim, reuse the receipt")
    assert p.returncode != 0, (
        "FALSE GREEN: the claim text changed and a receipt written for the previous "
        "blob still satisfied the gate")


def test_the_refusal_names_a_blob_mismatch(repo):
    """Exit status alone is not enough. A nonzero exit could come from any other branch
    (missing file, unreadable .claim-paths, unresolved pointer). The diagnostic has to say
    the receipt was for a different blob, or the test does not prove which guard fired."""
    blob = _stage_new_claim(repo)
    p = _run(repo, "git", "commit", "-qm", "rewrite")
    err = p.stderr.lower()
    assert "blob" in err, f"diagnostic never mentions the blob: {p.stderr!r}"
    assert blob[:12] in p.stderr, (
        f"diagnostic does not name the staged blob {blob[:12]}: {p.stderr!r}")


# --------------------------------------------------------- 2. legacy path-only receipts
def test_a_path_only_receipt_no_longer_satisfies_anything(repo):
    """The old grammar carried no blob. Accepting it is exactly the hole, so it refuses."""
    _stage_new_claim(repo)
    (repo / ".claim-review-ack").write_text("index.html :: EVIDENCE ./evidence.txt\n")
    p = _run(repo, "git", "commit", "-qm", "legacy receipt")
    assert p.returncode != 0, "a path-only receipt still passed"


# --------------------------------------------------------- 3. the honest path still works
def test_a_receipt_for_the_staged_blob_passes(repo):
    blob = _stage_new_claim(repo)
    (repo / ".claim-review-ack").write_text(
        f"index.html :: EVIDENCE ./evidence.txt :: blob {blob}\n")
    p = _run(repo, "git", "commit", "-qm", "receipt matches the staged blob")
    assert p.returncode == 0, f"an honest, current receipt was refused: {p.stderr}"


def test_selection_is_by_blob_not_by_line_order(repo):
    """A stale line sitting FIRST must not shadow the correct one below it. This is the
    ordering dependency the old head -1 created; blob selection removes it."""
    blob = _stage_new_claim(repo)
    (repo / ".claim-review-ack").write_text(
        "index.html :: EVIDENCE ./evidence.txt :: blob 0000000000000000000000000000000000000000\n"
        f"index.html :: EVIDENCE ./evidence.txt :: blob {blob}\n")
    p = _run(repo, "git", "commit", "-qm", "correct receipt is not first")
    assert p.returncode == 0, f"line order still decided the outcome: {p.stderr}"


def test_override_is_also_blob_bound(repo):
    """OVERRIDE is the escape hatch; an escape hatch that never expires is the same hole."""
    _stage_new_claim(repo)
    (repo / ".claim-review-ack").write_text(
        "index.html :: OVERRIDE wording only :: blob 0000000000000000000000000000000000000000\n")
    p = _run(repo, "git", "commit", "-qm", "stale override")
    assert p.returncode != 0, "a stale OVERRIDE passed"


def test_a_blob_prefix_is_not_a_blob(repo):
    """A prefix match is not a match.

    Found by mutation, not by inspection: truncating the comparison to the blob's first
    four hex characters survived every other test in this file. Four characters collide
    constantly, so a prefix comparison would let a receipt written for a different version
    through whenever the two shas happened to share a head. The guard has to compare the
    whole thing.
    """
    blob = _stage_new_claim(repo)
    near = blob[:4] + "0" * (len(blob) - 4)
    assert near != blob, "constructed sha must differ from the staged blob"
    (repo / ".claim-review-ack").write_text(
        f"index.html :: EVIDENCE ./evidence.txt :: blob {near}\n")
    p = _run(repo, "git", "commit", "-qm", "receipt matches only the blob prefix")
    assert p.returncode != 0, (
        f"a receipt carrying only the blob prefix {blob[:4]} satisfied the gate")
