"""The state vocabulary held to the conflations it exists to prevent.

Each test below is one of the three lies a two-state vocabulary tells. If any of them starts
passing by accident, the console is back to pass/fail wearing four labels.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from states import (ALL, INCOMPLETE, INVALIDATED, SURVIVED, VERIFIED, Finding,  # noqa: E402
                    UnscopedVerification, css_vars, legend_rows)


def test_an_unscoped_verification_cannot_be_constructed():
    """The load-bearing rule. Green means 'this bounded claim was re-earned', so a green with no
    boundary is the unsupported claim the program refuses and must not be representable."""
    with pytest.raises(UnscopedVerification, match="unbounded green"):
        Finding(VERIFIED, "6/6 repaired")
    ok = Finding(VERIFIED, "6/6 repaired", scope="ledger family, pinned config, human merge gate")
    assert ok.state is VERIFIED


def test_only_verified_demands_a_scope():
    """The other three describe the RUN, not a claim about the subject, so a missing scope there
    is a documentation gap and not a false assertion."""
    for st in (SURVIVED, INCOMPLETE, INVALIDATED):
        Finding(st, "x")     # must not raise


def test_incomplete_supports_no_capability_conclusion():
    """An uninvoked agent is not an incapable agent. Certlab produced exactly this when a cloud
    run died on billing; the state has to carry that, not a footnote."""
    assert Finding(INCOMPLETE, "agent unavailable").is_conclusion is False
    for st in (VERIFIED, SURVIVED, INVALIDATED):
        f = Finding(st, "x", scope="s" if st is VERIFIED else "")
        assert f.is_conclusion is True


def test_a_survived_hole_is_a_discovery_not_a_failure():
    """SURVIVED is the product. A report that files it under failures teaches the reader to stop
    declaring the defects that keep going red."""
    assert Finding(SURVIVED, "expected-answer removal").is_discovery is True
    assert Finding(INVALIDATED, "tampered").is_discovery is False
    assert Finding(INCOMPLETE, "no artifacts").is_discovery is False


def test_survived_and_invalidated_do_not_share_a_colour():
    """A measured hole and a proven contradiction mean opposite things to whoever must act."""
    assert SURVIVED.token != INVALIDATED.token
    assert INCOMPLETE.token not in (SURVIVED.token, INVALIDATED.token, VERIFIED.token)
    assert len({s.token for s in ALL}) == 4


def test_every_state_survives_greyscale():
    """Colour is never the only signal: each state carries a distinct glyph and a spelled label."""
    assert len({s.glyph for s in ALL}) == 4
    assert len({s.label for s in ALL}) == 4


def test_every_state_says_what_it_does_not_mean():
    """The not_means text is the whole point of the vocabulary and cannot be left blank."""
    for s in ALL:
        assert s.means.strip() and s.not_means.strip()
    assert "not that the subject is safe" in VERIFIED.not_means


def test_the_palette_is_not_a_green_red_axis():
    v = css_vars()
    for name in ("--ok:", "--hole:", "--bad:", "--none:"):
        assert name in v
    hexes = re.findall(r"#[0-9a-f]{6}", v)
    assert len(hexes) == 4 and len(set(hexes)) == 4, "four distinct hues, one per state"
    # the hole colour must not be the failure colour: discovery and contradiction differ
    assert "--hole:#f2a53c" in v and "--bad:#e0785f" in v


def test_the_legend_covers_all_four():
    rows = legend_rows()
    assert len(rows) == 4
    assert all(len(r) == 4 and all(str(x).strip() for x in r) for r in rows)
