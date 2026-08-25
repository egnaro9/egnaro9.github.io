"""The claim gate's grammar, and the one file that owns its own gate.

suite/sources.json was policed twice: it matched .claim-paths for the generic pre-commit loop
AND had a dedicated checker. The two disagreed on grammar. The generic loop parses
`<path> :: <KIND> <REF>` and accepts only EVIDENCE or OVERRIDE, so the `PIN` receipt the
dedicated checker demands was rejected as a malformed line. Passing required TWO receipts for
one file, and only in the order EVIDENCE-then-PIN, because the generic loop reads
`grep -F "<path> ::" | head -1`. That ordering was load-bearing and recorded nowhere.

These tests pin the repair: one file, one gate, no ordering dependency.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = "suite/sources.json"


def _checker():
    spec = importlib.util.spec_from_file_location(
        "sources_receipt", ROOT / ".githooks" / "sources_receipt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the exemption
def test_the_generic_loop_does_not_claim_the_manifest():
    """.claim-paths must not match suite/sources.json, by pattern OR by basename.

    The hook tries both, so removing the literal line is not enough on its own: a pattern like
    *.json or *manifest*.json would silently re-enrol the file and bring the grammar clash back.
    """
    patterns = [l.strip() for l in (ROOT / ".claim-paths").read_text().splitlines()
                if l.strip() and not l.strip().startswith("#")]
    base = TARGET.split("/")[-1]
    matched = [p for p in patterns
               if fnmatch.fnmatch(TARGET, p) or fnmatch.fnmatch(base, p)]
    assert not matched, (
        f"{TARGET} is still claimed by the generic loop via {matched}; it would be parsed with "
        f"the EVIDENCE/OVERRIDE grammar, which cannot express a PIN receipt")


def test_the_generic_grammar_still_rejects_pin():
    """Not a regression test for a bug to fix: a statement of why the exemption is the repair.

    The generic parser is deliberately left alone. This records that a PIN line remains
    unparseable by it, so anyone tempted to re-list the manifest sees the consequence.
    """
    hook = (ROOT / ".githooks" / "pre-commit").read_text()
    assert "OVERRIDE)" in hook and "EVIDENCE)" in hook
    assert "PIN)" not in hook, (
        "the generic loop now has a PIN branch; if that is intended, this test and the "
        "exemption in .claim-paths need revisiting together")


# ---------------------------------------------------------------- the dedicated gate
def _repo(tmp_path, sources_before, sources_after, ack_lines, stage_index_html=True):
    """A throwaway git repo with a staged manifest change. No network, no real remote."""
    r = tmp_path / "repo"
    (r / "suite").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True, capture_output=True)
    run("config", "user.email", "t@t"); run("config", "user.name", "t")
    (r / "suite/sources.json").write_text(sources_before)
    (r / "suite/index.html").write_text("<!doctype html>before")
    run("add", "-A"); run("commit", "-qm", "base")
    (r / "suite/sources.json").write_text(sources_after)
    if stage_index_html:
        (r / "suite/index.html").write_text("<!doctype html>after")
    run("add", TARGET, *(["suite/index.html"] if stage_index_html else []))
    (r / ".claim-review-ack").write_text("\n".join(ack_lines) + "\n")
    return r


SHA_OLD = "a" * 64
SHA_NEW = "b" * 64
URL = "https://github.com/egnaro9/model-drift/blob/{c}/dashboard/metrics.json"


def _manifest(commit, sha):
    return ('{"manifest_version": 1, "pinned_as_of": "2026-01-01", "sources": [{'
            f'"panel": "model-drift", "label": "L", "question": "Q", '
            f'"artifact": "model-drift/dashboard/metrics.json", '
            f'"issuer_commit": "{commit}", "sha256": "{sha}", '
            f'"public_url": "{URL.format(c=commit)}", "derivation": "drift_metrics@1"}}]}}')


@pytest.fixture
def stub_fetch(monkeypatch):
    """Serve bytes that hash to SHA_NEW without touching the network."""
    mod = _checker()
    payload = b"x"

    import hashlib
    real = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(mod, "_fetch", lambda url: (payload, ""))
    return mod, real


def test_one_pin_receipt_passes_and_needs_no_evidence_line(tmp_path, stub_fetch):
    mod, real_sha = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", real_sha),
              ["suite/sources.json :: PIN model-drift e596720->b051750"])
    assert mod.main(repo=r) == 0, "a single, correctly-formed PIN receipt must pass"


def test_receipt_order_is_not_load_bearing(tmp_path, stub_fetch):
    """The old workaround needed EVIDENCE first. Neither order may matter now."""
    mod, real_sha = stub_fetch
    pin = "suite/sources.json :: PIN model-drift e596720->b051750"
    ev = "suite/sources.json :: EVIDENCE https://example.invalid/x"
    for order in ([pin], [pin, ev], [ev, pin]):
        r = _repo(tmp_path / f"o{len(order)}{order[0][:30]}",
                  _manifest("e596720c7909", SHA_OLD),
                  _manifest("b05175032282", real_sha), order)
        assert mod.main(repo=r) == 0, f"ordering changed the verdict: {order}"


def test_a_missing_pin_receipt_fails(tmp_path, stub_fetch):
    mod, real_sha = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", real_sha),
              ["suite/sources.json :: EVIDENCE https://example.invalid/x"])
    assert mod.main(repo=r) == 1, "an EVIDENCE line alone must not pass the dedicated gate"


def test_a_pin_receipt_naming_the_wrong_commits_fails(tmp_path, stub_fetch):
    mod, real_sha = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", real_sha),
              ["suite/sources.json :: PIN model-drift 1111111->2222222"])
    assert mod.main(repo=r) == 1, "a receipt must name the commits that actually moved"


def test_a_receipt_cannot_pass_bytes_that_do_not_hash(tmp_path, stub_fetch):
    """The load-bearing property: the receipt is not the evidence, the bytes are."""
    mod, _ = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", SHA_NEW),
              ["suite/sources.json :: PIN model-drift e596720->b051750"])
    assert mod.main(repo=r) == 1


# ---------------------------------------------------------------- the audit record
def test_a_verified_pin_writes_an_audit_record(tmp_path, stub_fetch):
    mod, real_sha = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", real_sha),
              ["suite/sources.json :: PIN model-drift e596720->b051750"])
    assert mod.main(repo=r) == 0
    log = (r / ".claim-review-audit.log").read_text()
    assert "commit PIN (verified)" in log
    assert "PIN model-drift e596720->b051750" in log, "the recorded intent must survive"
    assert real_sha in log, "the record must carry the hash that was actually verified"
    assert "blob/b05175032282/" in log, "the record must carry the url that was fetched"


def test_a_refused_pin_writes_no_audit_record(tmp_path, stub_fetch):
    """The log records what was proven. A blocked commit proved nothing."""
    mod, _ = stub_fetch
    r = _repo(tmp_path, _manifest("e596720c7909", SHA_OLD), _manifest("b05175032282", SHA_NEW),
              ["suite/sources.json :: PIN model-drift e596720->b051750"])
    assert mod.main(repo=r) == 1
    assert not (r / ".claim-review-audit.log").exists()
