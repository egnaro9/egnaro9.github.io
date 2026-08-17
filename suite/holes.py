"""The surviving mutations, given the weight the score currently takes.

WHY THE HOLES ARE THE CONCLUSION. 91.3% is the least interesting true thing on this page. A
percentage invites the reader to file the result as good, and "good" is precisely the judgement
the program refuses to let a number make on its own. The four survivals are the finding: each one
is a specific defect that a specific check looked at and passed. So they render as the page's
terminal section, at card weight, with the text that got through printed verbatim.

THE DISTINCTION THIS MODULE EXISTS TO PROTECT. Two survivals are not the same kind of fact, and
evalmut already says so in `OperatorType`:

    KILL       a sound grader of this kind MUST catch this. The check is present and broken.
    DIAGNOSTIC this grader family is blind to this shape BY DESIGN and documents it. No check in
               the suite guards it, which is worth knowing, but the grader is not misbehaving.

Painting all four the same colour would be the mirror image of the overclaim this whole estate
exists to make fail: it would charge a check with a defect it never claimed to cover. So the
remedy line is DERIVED from each row's own op_type rather than written per hole, and the two
groups are separated visually and named differently.

EMPTY BUCKETS ARE PRINTED. evalmut classifies survivals into five kinds; three of them found
nothing here. Those are shown as zero rather than omitted, because a taxonomy that only lists its
non-empty categories lets a reader believe the categories were chosen after seeing the results.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

HOME = pathlib.Path.home()

# What each survival kind asserts, and what it does NOT. Wording follows evalmut's own
# OperatorType docstring; this module must never soften a category it did not define.
KINDS = {
    "blind": ("Blind spot",
              "the check ran, returned a pass, and was wrong. The defect sits inside the "
              "surface this check claims to cover."),
    "coverage_gap": ("Coverage gap",
                     "no check in the suite guards this shape. The grader documents the limit, "
                     "so this is a boundary made visible, not a check misbehaving."),
    "vacuous": ("Vacuous check",
                "the check passes everything it is shown, including output that cannot be "
                "correct. It is not testing anything."),
    "error": ("Grader error",
              "the check raised instead of judging, so its verdict on this shape is unknown."),
    "brittle": ("Brittle check",
                "the check failed an output that is correct, which makes its passes less "
                "informative."),
}

# Derived from the row, never chosen by hand: what a reader is supposed to do about it.
REMEDY = {
    "kill": "Fix the check. A sound grader of this kind is expected to catch this.",
    "diagnostic": "Add a check. This grader family is blind to this shape by design.",
    "sanity": "Investigate the grader. A floor probe should not survive.",
    "liveness": "Investigate the harness. The check may not have run at all.",
}


class HoleShapeError(ValueError):
    """A hole row is missing a field the card needs, or the tally disagrees with the rows."""


@dataclass(frozen=True)
class Hole:
    kind: str
    index: int
    case: str
    grader: str
    operator: str
    family: str
    op_type: str
    shape: str      # what was done to the output
    origin: str     # where this defect shape comes from in the world
    mutant: str     # the exact text that got through
    requirement: str
    clean: str = ""  # the CORRECT output for this case, from the pinned fixture manifest

    @property
    def pairing(self) -> str:
        """What SURVIVED actually means for this row, stated as the pair it is.

        A survival is not "the defective form passed". It is "the clean form passed AND the
        defective form passed", which is why the check cannot separate them. Naming only half
        the pair lets a reader hear an accusation about the system under test rather than a
        statement about the discrimination the check can make."""
        if not self.clean:
            return ("Clean form not resolvable from the pinned manifest, so this pair is shown "
                    "one-sided.")
        return ("Both forms passed this check under the recorded protocol, so the check does not "
                "separate them. That is the hole.")

    @property
    def label(self) -> str:
        return KINDS[self.kind][0]

    @property
    def means(self) -> str:
        return KINDS[self.kind][1]

    @property
    def remedy(self) -> str:
        if self.op_type not in REMEDY:
            raise HoleShapeError(
                f"{self.operator}: unknown op_type {self.op_type!r}. Refusing to print a remedy "
                "for a survival kind this page does not understand.")
        return REMEDY[self.op_type]

    @property
    def jq(self) -> str:
        """The expression that retrieves this exact row, so the card can be checked, not trusted."""
        return f".holes.{self.kind}[{self.index}]"


_REQUIRED = ("case_name", "grader_id", "operator_id", "family", "op_type",
             "defect_shape", "real_origin", "mutant_preview", "detail")


def clean_forms(manifest) -> dict[str, str]:
    """case name -> the correct output, read from the manifest that was hashed before the run.

    Taken from the PINNED manifest rather than from the results, because the clean form is an
    INPUT to the run. Reading it from the output would let a rerun quietly redefine what "clean"
    meant, which is the drift the manifest exists to prevent."""
    out = {}
    for c in manifest.get("cases", []):
        good = (c.get("fixture") or {}).get("good") or {}
        if "text" in good:
            out[c["name"]] = good["text"]
    return out


def holes(doc, manifest=None) -> list[Hole]:
    """Every survival in the bundle, in a fixed order, with no row silently dropped.

    Order is (kind as declared in KINDS, then index) rather than by severity or by anything
    computed here: a page that sorts findings by its own judgement has editorialised the
    evidence, and the reader cannot tell the sort from the data."""
    clean = clean_forms(manifest or {})
    out: list[Hole] = []
    for kind in KINDS:
        rows = doc["holes"].get(kind)
        if rows is None:
            raise HoleShapeError(
                f"the bundle has no {kind!r} bucket. This page names five survival kinds, and a "
                "missing bucket means the taxonomy moved underneath it.")
        for i, r in enumerate(rows):
            missing = [k for k in _REQUIRED if k not in r]
            if missing:
                raise HoleShapeError(f"holes.{kind}[{i}] is missing {missing}")
            out.append(Hole(kind=kind, index=i, case=r["case_name"], grader=r["grader_id"],
                            operator=r["operator_id"], family=r["family"], op_type=r["op_type"],
                            shape=r["defect_shape"], origin=r["real_origin"],
                            mutant=r["mutant_preview"], requirement=r["detail"],
                            clean=clean.get(r["case_name"], "")))
    return out


def counts(doc) -> list[tuple[str, str, int]]:
    """(kind, label, n) for every kind, including the ones that found nothing."""
    return [(k, KINDS[k][0], len(doc["holes"].get(k, []))) for k in KINDS]


def check_against_tally(doc, found: list[Hole]) -> None:
    """The cards and the headline are two views of one fact, so they are made to agree."""
    t = doc["tally"]
    if len(found) != t["missed"] + t["flagged"]:
        raise HoleShapeError(
            f"the explorer built {len(found)} cards but the tally reports "
            f"{t['missed']} missed + {t['flagged']} flagged. The page must not show a set of "
            "findings that disagrees with its own headline.")


def load(rel: str = "evalmut/docs/dogfood_gradecore.json"):
    doc = json.loads((HOME / rel).read_text())
    found = holes(doc)
    check_against_tally(doc, found)
    return doc, found
