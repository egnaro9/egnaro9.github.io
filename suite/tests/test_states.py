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


def _f(state, stage, dep="", scope="s"):
    from states import Finding
    return Finding(state, f"{stage} headline", scope=scope if state is VERIFIED else "",
                   stage=stage, depends_on=dep)


def test_a_verified_stage_is_downgraded_when_its_dependency_did_not_pass():
    """The load-bearing rule. A green stage 3 sitting on an INCOMPLETE stage 2 is a badge
    reachable without its dependencies."""
    from states import resolve_chain
    chain = resolve_chain([_f(INCOMPLETE, "calibrate"), _f(VERIFIED, "certify", "calibrate")])
    assert chain[1].state is INCOMPLETE
    assert "calibrate" in chain[1].detail and "No conclusion" in chain[1].detail


def test_the_downgrade_is_to_incomplete_never_to_a_failure():
    """The stage did not fail. It was never entitled to conclude, which is a different fact and
    sends the reader to a different place."""
    from states import resolve_chain
    chain = resolve_chain([_f(INVALIDATED, "verify"), _f(VERIFIED, "enforce", "verify")])
    assert chain[1].state is INCOMPLETE
    assert chain[1].state is not INVALIDATED


def test_an_intact_chain_is_left_alone():
    from states import resolve_chain
    chain = resolve_chain([_f(VERIFIED, "a"), _f(VERIFIED, "b", "a"), _f(VERIFIED, "c", "b")])
    assert [f.state for f in chain] == [VERIFIED, VERIFIED, VERIFIED]


def test_a_break_propagates_down_the_whole_chain():
    """One broken link must not leave later stages green just because their immediate parent was
    downgraded rather than originally failing."""
    from states import resolve_chain
    chain = resolve_chain([_f(SURVIVED, "a"), _f(VERIFIED, "b", "a"), _f(VERIFIED, "c", "b")])
    assert [f.state for f in chain] == [SURVIVED, INCOMPLETE, INCOMPLETE]


def test_a_dependency_that_never_ran_is_named_differently_than_one_that_failed():
    from states import resolve_chain
    chain = resolve_chain([_f(VERIFIED, "solo", "missing-stage")])
    assert "did not run" in chain[0].detail


def test_non_verified_states_are_not_gated():
    """SURVIVED and INVALIDATED are facts about what happened, not conclusions resting on a
    chain, so a broken dependency must not rewrite them."""
    from states import resolve_chain
    chain = resolve_chain([_f(INCOMPLETE, "a"), _f(SURVIVED, "b", "a"), _f(INVALIDATED, "c", "b")])
    assert [f.state for f in chain] == [INCOMPLETE, SURVIVED, INVALIDATED]
