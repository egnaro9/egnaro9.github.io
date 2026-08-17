"""Provenance for every number on the page, derived rather than asserted.

THE PROBLEM A DRAWER IS SUPPOSED TO SOLVE. A page can print "42" beside a filename and be lying
in two independent ways: the number can be stale, or the filename can be wrong. A caption is not
evidence, because a caption is typed by the same hand that typed the number, and it stays put
while the number moves. So the drawer here never TAKES a provenance string as an argument to
display. It takes an executable path into the document, uses that path to produce the value it
shows, and prints the same path it used. A wrong path cannot render a right number.

WHY EVERY VALUE IS COMPUTED TWICE, IN TWO LANGUAGES. The path shown to a reader is a jq
expression, and it is RUN at build time against the same file, then compared against an
independent Python computation of the same quantity. They must agree or the build raises. This is
not belt-and-braces, it is the only version of this check that can fail: a single implementation
that prints its own path agrees with itself by construction, which is the shape of an instrument
that cannot report a problem. Two implementations of one derivation can disagree, and that is
precisely what makes agreement worth showing. This estate has already paid for that lesson twice,
once when a determinism test and a golden file both stayed green through a 69-diff divergence
because both ran on one runtime, and once when a gate could not distinguish "checked and clean"
from "never checked".

WHAT HAPPENS WHEN jq IS ABSENT. The value still renders, and the drawer says the command was not
executed at build time. It does not silently claim a verification that did not run. An
unverifiable claim printed as verified is worse than no claim, and "absence is louder than
presence" is the rule the whole estate is built on.

THE RECORDED COMMAND IS ALSO NOT TYPED. It is extracted from the emitter's own argv table by
parsing that source file, so a page can never advertise a command that no longer produces the
artifact. If the table stops containing the artifact, this raises rather than guessing.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

HOME = pathlib.Path.home()
JQ = shutil.which("jq")


class ProvenanceError(ValueError):
    """A value could not be bound to its source, or the two derivations disagreed."""


@dataclass(frozen=True)
class Source:
    """One committed artifact, identified by content rather than by name alone."""

    rel: str          # path under $HOME, e.g. evalmut/docs/dogfood_gradecore.json
    repo: str         # the repo directory name
    in_repo: str      # path within the repo
    sha256: str       # full digest of the exact bytes read
    size: int
    commit: str       # last commit that TOUCHED this artifact, never the repo's HEAD
    produced_by: str  # the command that emits this artifact, read from the emitter

    @property
    def url(self) -> str:
        return f"https://github.com/egnaro9/{self.repo}/blob/{self.commit}/{self.in_repo}"

    @property
    def replay(self) -> str:
        """Exactly what a stranger runs to get these bytes, pinned to a commit and not to main."""
        return (f"git clone https://github.com/egnaro9/{self.repo} && cd {self.repo}\n"
                f"git checkout {self.commit}\n"
                f"{self.produced_by}   # regenerates {self.in_repo}\n"
                f"shasum -a 256 {self.in_repo}   # expect {self.sha256[:16]}...")


@dataclass(frozen=True)
class Value:
    """A number on the page, plus the executable expression that produced it."""

    label: str
    shown: str
    jq: str           # the expression a reader can run, and the one that WAS run
    src: Source
    cross_checked: bool  # jq ran at build time and agreed with the Python derivation

    @property
    def command(self) -> str:
        return f"jq '{self.jq}' {self.src.in_repo}"


def _sha256(p: pathlib.Path) -> tuple[str, int]:
    b = p.read_bytes()
    return hashlib.sha256(b).hexdigest(), len(b)


def _commit(repo_dir: pathlib.Path, in_repo: str) -> str:
    """The last commit that TOUCHED this artifact, not the repo's HEAD.

    HEAD is the wrong pin and the staleness gate proved it within minutes of shipping: committing
    a docs-only file to evalmut moved this page's cited commit, even though that commit cannot
    change a single byte of the bundle. Two things go wrong with HEAD. The page cites a commit
    that did not produce the artifact, which is a false provenance claim even when replay happens
    to still work; and every unrelated commit anywhere in the source repo forces a rebuild here,
    which trains whoever maintains this to regenerate without reading the diff.

    The path-scoped commit is both stable and the claim actually being made: these bytes came from
    here."""
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), "log", "-1", "--format=%H", "--",
                              in_repo], capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:
        raise ProvenanceError(
            f"cannot read the commit for {repo_dir}/{in_repo}: {type(e).__name__}: {e}. A source "
            "with no commit cannot be replayed, so it is not evidence.") from e
    if not out:
        raise ProvenanceError(
            f"{repo_dir}/{in_repo} has no commit touching it. An uncommitted artifact cannot be "
            "replayed by anyone else, so it must not be cited as evidence.")
    return out[:12]


def producing_command(repo: str, in_repo: str, emitter: str = "emit_vac.py",
                      cli: str | None = None) -> str:
    """Extract the argv that emits this artifact from the emitter's own table.

    Parsed, not imported: importing a sibling repo's script runs its module body. Parsed, not
    typed: a hand-copied command is a caption, and captions go stale silently while the artifact
    keeps changing underneath them."""
    src = HOME / repo / emitter
    try:
        tree = ast.parse(src.read_text())
    except Exception as e:
        raise ProvenanceError(f"cannot parse {src}: {type(e).__name__}: {e}") from e

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "ARTIFACTS" for t in node.targets)):
            continue
        try:
            table = ast.literal_eval(node.value)
        except Exception as e:
            raise ProvenanceError(f"{src}: ARTIFACTS is not a literal table: {e}") from e
        for argv, path in table:
            if path == in_repo:
                return " ".join((cli or repo, *argv))
        raise ProvenanceError(
            f"{src}: ARTIFACTS has no entry emitting {in_repo!r}. Refusing to print a command "
            "that does not produce the artifact on this page.")
    raise ProvenanceError(f"{src}: no ARTIFACTS table found")


def source(repo: str, in_repo: str, **kw) -> Source:
    p = HOME / repo / in_repo
    if not p.exists():
        raise ProvenanceError(f"{p} does not exist")
    digest, size = _sha256(p)
    return Source(rel=f"{repo}/{in_repo}", repo=repo, in_repo=in_repo, sha256=digest,
                  size=size, commit=_commit(HOME / repo, in_repo),
                  produced_by=producing_command(repo, in_repo, **kw))


def _run_jq(expr: str, path: pathlib.Path):
    p = subprocess.run([JQ, "-e", expr, str(path)], capture_output=True, text=True, timeout=30)
    if p.returncode not in (0, 1):  # 1 is jq's "null or false", still a real answer
        raise ProvenanceError(f"jq '{expr}' failed on {path}: {p.stderr.strip()}")
    return json.loads(p.stdout)


def _agree(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def value(src: Source, doc, label: str, jq: str, py, fmt=str) -> Value:
    """Bind one displayed number to an expression that reproduces it.

    `py` derives the value from the parsed document; `jq` derives it again from the bytes on disk.
    Disagreement raises, because the only useful outcome of a cross-check is that it can fail."""
    raw = py(doc)
    checked = False
    if JQ:
        other = _run_jq(jq, HOME / src.rel)
        if not _agree(raw, other):
            raise ProvenanceError(
                f"{label}: the page would show {raw!r} but `jq '{jq}' {src.in_repo}` returns "
                f"{other!r}. One of the two derivations is wrong and the page must not pick a "
                "winner.")
        checked = True
    return Value(label=label, shown=fmt(raw), jq=jq, src=src, cross_checked=checked)


def unchecked_note(values: list[Value]) -> str:
    """One line stating whether the cross-check actually ran. Never silently omitted."""
    n = sum(1 for v in values if v.cross_checked)
    if n == len(values) and values:
        return (f"All {n} values were recomputed with jq against the file's bytes at build time "
                "and matched. A mismatch fails the build.")
    return ("jq was not available when this page was built, so the commands below were NOT "
            "executed here. They are still the expressions used to derive each value.")
