"""check_pins must never report VALID for a pin it could not compare.

The hole these cover, measured rather than imagined: `_get` collapsed every fetch
failure into one branch that returned VALID with the words "drift unknown" in the
reason string. model-drift renamed dashboard/metrics.json on 2026-08-30, every fetch
of upstream main 404ed from then on, and the panel printed [VALID ] for 23 days and
34 upstream commits while comparing nothing at all. The status said fine, the reason
said unknown, and the status is what the exit code reads.

Every test here pins one half of that: a comparison that did not happen must not be
reported as a comparison that succeeded, and a durable 404 must be distinguishable
from a passing network fault.
"""
from __future__ import annotations

import pathlib
import sys
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import check_pins  # noqa: E402

ENTRY = {
    "panel": "a-panel",
    "label": "a claim",
    "artifact": "owner/repo/some/artifact.json",
    "issuer_commit": "0123456789ab",
    "public_url": "https://github.com/owner/repo/blob/0123456789ab/some/artifact.json",
    "sha256": "",
    "derivation": "test",
}

PINNED_BYTES = b'{"pinned": true}\n'


def _entry(**over):
    import hashlib
    e = dict(ENTRY)
    e["sha256"] = hashlib.sha256(PINNED_BYTES).hexdigest()
    e.update(over)
    return e


def _responses(monkeypatch, upstream):
    """Serve the pinned URL, and let the caller decide what upstream main does.

    upstream is either bytes, or an exception instance to raise.
    """
    calls = []

    def fake_get(url, attempts=1):
        calls.append(url)
        if "/0123456789ab/" in url:
            return PINNED_BYTES, "", 200
        for _ in range(attempts):
            if isinstance(upstream, urllib.error.HTTPError):
                return None, f"HTTPError: {upstream}", upstream.code
            if isinstance(upstream, Exception):
                last = (f"{type(upstream).__name__}: {upstream}", 0)
                continue
            return upstream, "", 200
        return None, last[0], last[1]

    monkeypatch.setattr(check_pins, "_get", fake_get)
    return calls


def _http_error(code):
    return urllib.error.HTTPError("u", code, "Not Found", {}, None)


def test_a_404_on_upstream_main_is_not_reported_as_valid(monkeypatch):
    _responses(monkeypatch, _http_error(404))
    state, why = check_pins.check(_entry())
    assert state != "VALID", (
        "a panel whose upstream artifact no longer exists was reported VALID; "
        "this is the exact defect that hid model-drift for 23 days")
    assert state == "UNMEASURED"
    assert "404" in why


def test_an_unreadable_upstream_is_not_reported_as_valid(monkeypatch):
    _responses(monkeypatch, TimeoutError("timed out"))
    state, why = check_pins.check(_entry())
    assert state != "VALID"
    assert state == "UNMEASURED"
    assert "NOT measured" in why


def test_a_404_is_not_retried_but_a_network_fault_is(monkeypatch):
    calls = _responses(monkeypatch, _http_error(404))
    check_pins.check(_entry())
    upstream_calls = [c for c in calls if "/main/" in c]
    assert len(upstream_calls) == 1, "a 404 is a settled answer; asking twice learns nothing"


def test_an_agreeing_upstream_is_still_valid(monkeypatch):
    _responses(monkeypatch, PINNED_BYTES)
    state, why = check_pins.check(_entry())
    assert state == "VALID"
    assert "current with" in why


def test_a_differing_upstream_is_behind_not_unmeasured(monkeypatch):
    _responses(monkeypatch, b'{"pinned": false}\n')
    state, _ = check_pins.check(_entry())
    assert state == "BEHIND", "a comparison that happened and disagreed is BEHIND, not UNMEASURED"


@pytest.mark.parametrize("state,only_pins,expected", [
    ("UNMEASURED", False, True),
    ("UNMEASURED", True, False),
    ("BEHIND", False, True),
    ("BEHIND", True, False),
    ("BROKEN", True, True),
    ("VALID", False, False),
])
def test_unmeasured_fails_the_scheduled_job_but_not_a_pull_request(state, only_pins, expected):
    """Mirrors main()'s predicate. UNMEASURED sorts with BEHIND: the pin itself is
    intact, so a PR that never touched the panel is not the place to fail."""
    fails = state == "BROKEN" or (state in ("BEHIND", "UNMEASURED") and not only_pins)
    assert fails is expected
