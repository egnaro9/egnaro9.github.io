"""Derive the page's headline from the bundle, and refuse to build when it cannot be derived.

WHY THIS IS A MODULE AND NOT AN f-STRING IN THE TEMPLATE. The headline is the most prominent
claim on the page and therefore the one most worth binding mechanically. A review of this very
work asserted "32/35 caught, three open holes" while the run on disk said 42/46 and four; the
number was correct when someone wrote it down and wrong two commits later. Transcribed numbers
rot. Derived ones cannot.

So the rule here is stronger than "read the fields": the derivation RECOMPUTES what it can and
refuses when the bundle contradicts itself. A tally whose parts do not sum, or a hole total that
disagrees with the hole breakdown, is not rendered with a caveat. It stops the build, because a
page that renders an internally inconsistent bundle has published a number nobody can stand
behind, and doing that in a proof console is worse than not shipping.

The scope and the non-claims are part of the header, not a footnote below it. A bounded claim
whose bound is a scroll away is an unbounded claim with an alibi.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


class UnderivableClaim(ValueError):
    """The bundle is missing a field the headline needs, or contradicts itself."""


@dataclass(frozen=True)
class Claim:
    caught: int
    applied: int
    score_pct: float
    holes_total: int
    holes_by_kind: dict[str, int]
    source: str

    @property
    def headline(self) -> str:
        """Generated, never typed. Reads as a sentence; every number comes from the bundle."""
        kinds = ", ".join(f"{n} {k.replace('_', ' ')}"
                          for k, n in sorted(self.holes_by_kind.items()))
        survived = (f"{self.holes_total} survived ({kinds})" if self.holes_total
                    else "none survived")
        return (f"Recorded evalmut dogfood run: {self.caught} of {self.applied} declared "
                f"mutations were labelled caught; {survived}.")

    @property
    def scope(self) -> str:
        return ("evalmut's own Corpus A protocol and tooling corpus, under the recorded "
                "environment, at the commit this bundle names.")

    @property
    def not_established(self) -> str:
        return ("independent operator validity, external evaluation-suite detection power, or "
                "production reliability of anything.")


def derive(path: str | pathlib.Path) -> Claim:
    """Read one dogfood export and recompute the headline's numbers from its own rows."""
    p = pathlib.Path(path)
    try:
        d = json.loads(p.read_text())
    except Exception as e:
        raise UnderivableClaim(f"cannot read {p}: {type(e).__name__}: {e}") from e

    for field in ("tally", "holes", "score"):
        if field not in d:
            raise UnderivableClaim(f"{p}: missing required field {field!r}")

    t = d["tally"]
    for k in ("caught", "missed", "flagged"):
        if k not in t:
            raise UnderivableClaim(f"{p}: tally is missing {k!r}")

    caught, missed, flagged = int(t["caught"]), int(t["missed"]), int(t["flagged"])
    applied = caught + missed + flagged
    if applied <= 0:
        raise UnderivableClaim(
            f"{p}: no mutations were applied, so there is no claim to make. An empty run is not "
            "a clean run.")

    by_kind = {k: len(v) for k, v in d["holes"].items() if v}
    holes_total = sum(by_kind.values())

    # Internal consistency: the hole buckets and the tally are two derivations of the same fact,
    # so a disagreement means at least one is wrong and the page must not choose a favourite.
    if holes_total != missed + flagged:
        raise UnderivableClaim(
            f"{p}: bundle contradicts itself. Hole buckets total {holes_total} "
            f"({by_kind}), but the tally reports {missed} missed + {flagged} flagged = "
            f"{missed + flagged}. Refusing to render a number nobody can stand behind.")

    score = float(d["score"]) * 100
    recomputed = caught / applied * 100
    if abs(score - recomputed) > 0.05:
        raise UnderivableClaim(
            f"{p}: declared score {score:.1f}% does not match {caught}/{applied} = "
            f"{recomputed:.1f}%. The summary outran its own rows.")

    return Claim(caught=caught, applied=applied, score_pct=round(score, 1),
                 holes_total=holes_total, holes_by_kind=by_kind, source=str(p))
