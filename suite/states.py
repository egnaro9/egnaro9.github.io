"""The four states, and the rules that keep them from collapsing into pass/fail.

WHY FOUR AND NOT TWO. A two-state vocabulary forces three different things into the same box, and
each conflation is a lie the program exists to refuse:

  - A measured hole is not an error. `evalmut` finding that a declared defect survived is the tool
    WORKING. Painting it red teaches a reader to treat discovery as breakage, and the next person
    to run it will quietly stop declaring the defects that keep going red.
  - A missing artifact is not a capability finding. When the harness could not run, the honest
    output is "no conclusion", not "failed". Certlab learned this the expensive way: a cloud run
    died on billing and produced an uninvoked, artifact-less result that would have read as an
    agent incapability if the state vocabulary had had nowhere else to put it.
  - A refused tamper is not a system failure. The verifier rejecting forged evidence is the single
    strongest thing in the stack, and it must read as the machine working, loudly.

THE RULE ON GREEN. VERIFIED never means safe, correct, or trustworthy. It means exactly: this
bounded claim was re-earned under this recorded protocol. That is why `scope` is REQUIRED on a
verified state and the constructor refuses without it. An unscoped green is the unsupported claim
this whole program was built to make fail mechanically, and it should not be constructible here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    key: str
    label: str
    means: str          # what it asserts
    not_means: str      # what a reader must not take from it
    token: str          # CSS custom property, never used as the ONLY signal
    glyph: str          # so the state survives colour-blindness and greyscale print


VERIFIED = State(
    "verified", "Verified",
    "deterministic evidence exists and the required checks passed, for the stated scope",
    "not that the subject is safe, correct, or trustworthy. Only that this bounded claim was "
    "re-earned under this recorded protocol",
    "--ok", "✓")

SURVIVED = State(
    "survived", "Survived",
    "a declared defect was NOT detected. A measured hole, and a discovery",
    "not a system error and not a bug in the tool. The tool worked; the check under test did not",
    "--hole", "◆")

INCOMPLETE = State(
    "incomplete", "Incomplete",
    "infrastructure or required evidence failed, so no capability conclusion is available",
    "NOT a negative finding about the subject. An uninvoked agent is not an incapable agent",
    "--none", "○")

INVALIDATED = State(
    "invalidated", "Invalidated",
    "a claim or artifact was broken, deliberately or independently, and the verifier refused it "
    "by name",
    "not a crash. This is the refusal path firing, which is the strongest evidence in the stack",
    "--bad", "✕")

ALL = (VERIFIED, SURVIVED, INCOMPLETE, INVALIDATED)
BY_KEY = {s.key: s for s in ALL}


class UnscopedVerification(ValueError):
    """A verified state was constructed without saying what it covers."""


@dataclass(frozen=True)
class Finding:
    """One stage's outcome, with the boundary attached to the state rather than to a footnote."""

    state: State
    headline: str
    scope: str = ""       # required when VERIFIED: what this claim does and does not cover
    detail: str = ""      # the named predicate, the recomputation, the refusal reason
    source: str = ""      # the artifact a reader can open

    def __post_init__(self):
        if self.state is VERIFIED and not self.scope.strip():
            raise UnscopedVerification(
                f"VERIFIED requires a scope: {self.headline!r} would render as an unbounded green, "
                "which is the exact shape of the unsupported claim this program refuses. State "
                "what it covers, or use INCOMPLETE.")

    @property
    def is_conclusion(self) -> bool:
        """Does this row support ANY statement about the subject's capability?

        INCOMPLETE does not. Everything that renders a verdict, aggregates a rate, or writes a
        contract line must consult this rather than testing for absence of failure, because
        'not failed' silently includes 'never ran'."""
        return self.state is not INCOMPLETE

    @property
    def is_discovery(self) -> bool:
        """SURVIVED is the product, not the exception. Kept as a named property so reports can
        surface holes without reaching for a failure bucket."""
        return self.state is SURVIVED


def css_vars() -> str:
    """One place for the palette, so no page invents its own severity language.

    Deliberately NOT a green/red axis. Survived is amber because it is discovery; invalidated is
    the only red, reserved for a proven contradiction; incomplete is a cool grey that reads as
    absent rather than bad."""
    return (
        "--ok:#48c1ac;--ok-soft:rgba(72,193,172,.12);"
        "--hole:#f2a53c;--hole-soft:rgba(242,165,60,.13);"
        "--bad:#e0785f;--bad-soft:rgba(224,120,95,.12);"
        "--none:#7b8a90;--none-soft:rgba(123,138,144,.12);")


def legend_rows() -> list[tuple[str, str, str, str]]:
    """(glyph, label, means, does not mean) for rendering the legend that must appear on any page
    using these states. A reader who meets 'Survived' with no key will read it as failure."""
    return [(s.glyph, s.label, s.means, s.not_means) for s in ALL]
