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
    ("ROUTINE", False, False),
    ("ROUTINE", True, False),
])
def test_unmeasured_fails_the_scheduled_job_but_not_a_pull_request(state, only_pins, expected):
    """Mirrors main()'s predicate. UNMEASURED sorts with BEHIND: the pin itself is
    intact, so a PR that never touched the panel is not the place to fail."""
    fails = state == "BROKEN" or (state in ("BEHIND", "UNMEASURED") and not only_pins)
    assert fails is expected



# ── a declared routine excuses a lag, and nothing else ─────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
RULE = {"author": "github-actions[bot]", "message_prefix": "chore: update drift standings",
        "max_lag_days": 14}


def _c(sha, days_ago, author="github-actions[bot]",
       msg="chore: update drift standings [skip ci]"):
    when = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {"sha": sha, "commit": {"author": {"name": author}, "message": msg,
                                   "committer": {"date": when}}}


def _history(monkeypatch, commits, err=""):
    monkeypatch.setattr(check_pins, "_get_json",
                        lambda url: (commits, err) if commits is not None else (None, err))


def _routine(entry):
    return check_pins._routine(entry, "owner", "repo", "some/artifact.json", "0123456789ab", now=NOW)


def test_routine_commits_within_the_lag_are_routine(monkeypatch):
    _history(monkeypatch, [_c("c3", 1), _c("c2", 2), _c("c1", 3), _c("0123456789abcdef", 4)])
    ok, why = _routine(_entry(routine=RULE))
    assert ok, why
    assert "3 routine update(s)" in why


def test_one_non_routine_commit_makes_it_behind(monkeypatch):
    """The point of the rule is that only the declared updates are excused. A human
    commit, or a bot commit with any other message, is news and stays BEHIND."""
    _history(monkeypatch, [_c("c2", 1), _c("c1", 2, author="egnaro9", msg="change the suite"),
                           _c("0123456789abcdef", 4)])
    ok, why = _routine(_entry(routine=RULE))
    assert not ok and "not routine" in why
    _history(monkeypatch, [_c("c1", 1, msg="feat: something else"), _c("0123456789abcdef", 4)])
    assert not _routine(_entry(routine=RULE))[0]


def test_a_routine_lag_past_max_is_behind(monkeypatch):
    _history(monkeypatch, [_c("c2", 1), _c("c1", 15), _c("0123456789abcdef", 16)])
    ok, why = _routine(_entry(routine=RULE))
    assert not ok and "bump the pin" in why


def test_an_unreadable_history_or_a_missing_pin_excuses_nothing(monkeypatch):
    _history(monkeypatch, None, err="HTTPError: 403 rate limited")
    assert not _routine(_entry(routine=RULE))[0]
    _history(monkeypatch, [_c("c2", 1), _c("c1", 2)])  # pinned commit never appears
    ok, why = _routine(_entry(routine=RULE))
    assert not ok and "not among" in why


def test_a_panel_without_a_rule_is_never_routine(monkeypatch):
    _history(monkeypatch, [_c("c1", 1), _c("0123456789abcdef", 2)])
    assert _routine(_entry()) == (False, "")


def test_check_reports_routine_through_the_real_behind_branch(monkeypatch):
    _responses(monkeypatch, b'{"pinned": false}\n')
    _history(monkeypatch, [_c("c1", 1), _c("0123456789abcdef", 2)])
    monkeypatch.setattr(check_pins, "datetime", type("D", (), {
        "now": staticmethod(lambda tz=None: NOW),
        "fromisoformat": staticmethod(datetime.fromisoformat)}))
    state, why = check_pins.check(_entry(routine=RULE))
    assert state == "ROUTINE", why
    state, _ = check_pins.check(_entry())
    assert state == "BEHIND"


def test_only_model_drift_declares_a_routine():
    """The live manifest: one panel, the one whose artifact its issuer rewrites daily."""
    import json
    man = json.loads(check_pins.MANIFEST.read_text())
    declared = {s["panel"]: s["routine"] for s in man["sources"] if "routine" in s}
    assert set(declared) == {"model-drift"}
    assert declared["model-drift"]["max_lag_days"] <= 14
