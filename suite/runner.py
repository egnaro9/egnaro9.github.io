"""Build the Verifiable Evaluation Suite runner: the proof stack, stepped, over real artifacts.

THE THESIS THIS PAGE HAS TO CARRY, in one line from the program's own framing:

    Verification systems can show green over the exact surface they do not cover, so the
    instruments themselves must be measured, challenged, and replayable.

A dashboard cannot argue that. A number on a card is the same shape as the unsupported claim the
program exists to refuse. So this page is a SEQUENCE: six steps, each one testing the step above
it, ending with the only move in the whole stack that a competitor cannot copy by adding a metric,
which is a verifier refusing tampered evidence BY NAME.

    1  AUDIT      would these checks notice a planted defect          evalmut dogfood
    2  CALIBRATE  can the instrument detect a known-broken model      reference-fleet board
    3  CERTIFY    what can this agent do, and where does it fail      agent-certlab bundle
    4  PRESERVE   is there enough evidence to replay the conclusion   vac-protocol registry
    5  CHALLENGE  does the verifier reject manipulated evidence       vac-verify
    6  LIMITS     are the failures published beside the findings      the bundle itself

ONE ARTIFACT PER STEP, AND NOTHING AGGREGATED ACROSS THEM. Four repos appear here, which is the
shape a product pitch abuses, so the containment is mechanical rather than editorial. Each of the
four MEASURED steps (1 to 4) binds to exactly one committed file, carries its own provenance
drawer naming that file by hash and commit, and states a claim that stops at that file's scope.
No number is summed, averaged or compared across repos, and no step borrows another step's
evidence: a page that combined them would be making a claim no single artifact supports.

Steps 5 and 6 are deliberately not of that kind, and saying they are would be the same defect one
paragraph lower. Step 5 shows an EXECUTED transcript rather than read numbers, so its evidence is
the terminal block itself. Step 6 is derived from the bundle's own limitations field. Neither
carries a values drawer, and the test enforces the drawer rule on the steps that display read
numbers rather than on all six.

EVERY NUMBER IS READ, AND STEP 5 IS EXECUTED. The counts come from each repo's committed
artifact. The verifier output is captured by actually running `vac-verify` against a clean bundle
and against tamper fixtures at build time, so the refusal text on the page is a transcript, not a
quotation. If the verifier stops refusing, this page changes or the build fails; it cannot keep
showing a refusal that no longer happens.

A step whose artifact is missing renders ABSENT and names the path. It never falls back to a
remembered value: a page that silently drops a source looks exactly like a page whose sources are
healthy, and that is the failure the whole program refuses.
"""
from __future__ import annotations

import html
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from browserverify import panel as browser_panel  # noqa: E402
from witness_gate import accept as accept_witness  # noqa: E402
from claim import derive  # noqa: E402
from evidence import (ProvenanceError, bundled_recipe, documented_command,  # noqa: E402
                      source, unchecked_note, value)
from holes import counts, holes  # noqa: E402
from states import SURVIVED, css_vars, css_vars_light, legend_rows  # noqa: E402

HOME = pathlib.Path.home()
OUT = pathlib.Path(__file__).resolve().parent / "runner.html"
VAC = HOME / "vac-protocol"
VERIFY = "vac-verify"


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def read(rel: str):
    try:
        return json.loads((HOME / rel).read_text())
    except Exception:
        return None


def run_verifier(target: pathlib.Path) -> tuple[int, str, int]:
    """Actually run the verifier. The refusal on the page must be a transcript."""
    try:
        p = subprocess.run([VERIFY, str(target)], cwd=str(VAC),
                           capture_output=True, text=True, timeout=90)
        # COUNT the named reasons, do not just take the first. The caption below calls this
        # block a transcript. A transcript that silently drops eight of nine FAIL lines is a
        # quotation wearing the word. tamper-evalmut-rows really prints 9 and
        # tamper-stamp-deleted really prints 3; the page showed one, unmarked.
        named = [l.strip() for l in (p.stdout + p.stderr).splitlines()
                 if l.strip().startswith("FAIL")]
        matched = [l.strip() for l in (p.stdout + p.stderr).splitlines()
                   if l.strip().startswith(("FAIL", "structural verification"))]
        return p.returncode, (matched[0] if matched else ""), len(named)
    except Exception as e:
        # THREE values, matching the success path. Widening the return for the named-reason
        # count left this branch at two, so an unavailable verifier raised ValueError in the
        # caller instead of degrading to UNLAUNCHED. That silently un-fixed the honest
        # degradation this function exists for, and no test covered the path.
        return -1, f"could not run the verifier: {type(e).__name__}: {e}", 0


DOGFOOD = "docs/dogfood_gradecore.json"
WITNESS_ARTIFACT = "evalmut/docs/dogfood_gradecore_witnessed.json"
BOARD = "board/results.json"
REGISTRY = "registry.json"
CERTS = HOME / "agent-certlab" / "certifications"


def bound(repo: str, in_repo: str, how=None):
    """(source, parsed document) for one artifact, or (None, None) when it cannot be bound.

    Only the BINDING is guarded. A cross-check disagreement inside value() is left to propagate,
    because an artifact that is present and contradicts its own expression is a failing build and
    not an absent step. Collapsing those two into one quiet branch is how a page starts rendering
    ABSENT for a problem it was supposed to shout about.

    `how` is a callable rather than a dict so that deriving the provenance can itself fail into
    the absent path: a bundle whose recipe has drifted away from the bytes is exactly as
    unciteable as a file that is not there."""
    try:
        return (source(repo, in_repo, **(how() if how else {})),
                json.loads((HOME / repo / in_repo).read_text()))
    except (ProvenanceError, OSError, ValueError):
        return None, None


def latest_cert() -> pathlib.Path | None:
    """The certification step 3 reads, chosen by sorted order and never by result.

    Named here rather than inlined because the selection rule is part of the claim. Picking the
    best-scoring bundle out of seven would be the page grading itself, so the rule has to be one
    a reader can apply from the directory listing alone."""
    return next(reversed(sorted(CERTS.glob("*/bundle.json"))), None)


def audit_values(src, d) -> list:
    """The four numbers of step 1, each bound to the expression that reproduces it.

    Written as (label, jq, python) triples rather than as formatted strings, so the provenance
    shown in the drawer is the provenance used to build the row. There is no way to display a
    path here that was not walked."""
    spec = [
        ("mutations applied", ".tally | .caught + .missed + .flagged",
         lambda x: x["tally"]["caught"] + x["tally"]["missed"] + x["tally"]["flagged"], str),
        ("caught", ".tally.caught", lambda x: x["tally"]["caught"], str),
        ("holes found", "[.holes[] | length] | add",
         lambda x: sum(len(v) for v in x["holes"].values()), str),
        ("declined rather than guessed", ".tally.na", lambda x: x["tally"]["na"], str),
        ("mutation score", ".score", lambda x: x["score"], lambda v: f"{v:.1%}"),
    ]
    return [value(src, d, label, jq, py, fmt) for label, jq, py, fmt in spec]


def calibrate_values(src, d) -> list:
    """Step 2's numbers, bound exactly as step 1's are.

    The naive archetype is picked by the same substring test on both sides, so the jq printed in
    the drawer is the filter that built the row and not a description of one. A reader who
    disagrees with the filter can see it, which is the point of showing it."""
    naive = '.rows[] | select(.suite | ascii_downcase | contains("naive"))'
    spec = [
        ("suite x member results", ".rows | length", lambda x: len(x["rows"]), str),
        ("archetypes measured", ".rows | map(.suite) | unique | length",
         lambda x: len({r["suite"] for r in x["rows"]}), str),
        ("fleet members", ".rows | map(.member) | unique | length",
         lambda x: len({r["member"] for r in x["rows"]}), str),
        ("naive-archetype pairs", f"[{naive}] | length",
         lambda x: sum(1 for r in x["rows"] if "naive" in str(r.get("suite", "")).lower()), str),
        ("of those, detecting at all", f"[{naive} | select(.detection_rate > 0)] | length",
         lambda x: sum(1 for r in x["rows"] if "naive" in str(r.get("suite", "")).lower()
                       and float(r.get("detection_rate") or 0) > 0), str),
        ("responses graded", "[.rows[].n] | add", lambda x: sum(r["n"] for r in x["rows"]), str),
        ("false alarms raised", "[.rows[].false_alarms] | add",
         lambda x: sum(r["false_alarms"] for r in x["rows"]), str),
        ("fleet commit", ".fleet_commit", lambda x: x["fleet_commit"], str),
    ]
    return [value(src, d, label, jq, py, fmt) for label, jq, py, fmt in spec]


def certify_values(src, b) -> list:
    """Step 3's numbers, plus the identifiers that say WHICH agent and family they describe.

    The identifiers are bound the same way as the counts on purpose. An agent id or a task family
    typed beside a real count is the oldest way to publish a true number about the wrong subject,
    and it is invisible to any check that only recomputes the arithmetic.

    The three layers are shown separately rather than as one verdict because they can disagree,
    and the disagreement is the finding: an agent that deletes the suite reaches a green test
    layer and still fails by policy."""
    spec = [
        ("agent", ".agent_id", lambda x: x["agent_id"], str),
        ("model", ".model", lambda x: x["model"], lambda v: v if v else "not recorded"),
        ("task family", ".family", lambda x: x["family"], str),
        ("tasks in the family", ".verdicts | length", lambda x: len(x["verdicts"]), str),
        ("seeded defects fixed", "[.verdicts[] | select(.fixed)] | length",
         lambda x: sum(1 for v in x["verdicts"] if v["fixed"]), str),
        ("passed the policy layer", "[.verdicts[] | select(.policy_ok)] | length",
         lambda x: sum(1 for v in x["verdicts"] if v["policy_ok"]), str),
        ("passed the test layer", "[.verdicts[] | select(.tests_ok)] | length",
         lambda x: sum(1 for v in x["verdicts"] if v["tests_ok"]), str),
        ("files the agent changed", "[.verdicts[].changed_files | length] | add",
         lambda x: sum(len(v["changed_files"]) for v in x["verdicts"]), str),
    ]
    return [value(src, b, label, jq, py, fmt) for label, jq, py, fmt in spec]


def preserve_values(src, d) -> list:
    """Step 4's numbers. Pending is shown beside accepted, always, including when it is zero.

    A registry that printed only what it accepted would look identical whether nothing was
    rejected or nothing was ever examined. The count of artifacts pinned by digest is here for
    the same reason: it is the number that makes an entry replayable rather than merely listed."""
    spec = [
        ("bundles in registry", ".entries | length", lambda x: len(x["entries"]), str),
        ("accepted", '[.entries[] | select(.status == "accepted")] | length',
         lambda x: sum(1 for e in x["entries"] if e["status"] == "accepted"), str),
        ("pending", ".pending | length", lambda x: len(x.get("pending") or []), str),
        ("issuers represented", ".entries | map(.issuer) | unique | length",
         lambda x: len({e["issuer"] for e in x["entries"]}), str),
        ("artifacts pinned by sha256", "[.entries[].artifacts | length] | add",
         lambda x: sum(len(e["artifacts"]) for e in x["entries"]), str),
    ]
    return [value(src, d, label, jq, py, fmt) for label, jq, py, fmt in spec]


def claim_values(src, d) -> list:
    """The numbers a reader meets first, in the headline. Same binding, no exceptions."""
    spec = [
        ("caught", ".tally.caught", lambda x: x["tally"]["caught"], str),
        ("applied", ".tally | .caught + .missed + .flagged",
         lambda x: x["tally"]["caught"] + x["tally"]["missed"] + x["tally"]["flagged"], str),
        ("survived", "[.holes[] | length] | add",
         lambda x: sum(len(v) for v in x["holes"].values()), str),
        ("blind", ".holes.blind | length", lambda x: len(x["holes"]["blind"]), str),
        ("coverage gap", ".holes.coverage_gap | length",
         lambda x: len(x["holes"]["coverage_gap"]), str),
    ]
    return [value(src, d, label, jq, py, fmt) for label, jq, py, fmt in spec]


def drawer(title: str, values: list, src, extra: str = "", start_open: bool = False) -> str:
    """One route from a visible number to the bytes behind it.

    <details> and not a modal: it works with scripting off, it is keyboard reachable, and it
    prints when the page prints. Evidence that needs JavaScript to appear is evidence a skeptic
    cannot get to.

    THE HEADLINE'S DRAWER OPENS BY DEFAULT, the per-step ones do not. A reader who never clicks
    should still land on the claim WITH its derivation, because a derivation behind a click is
    close enough to a transcribed number to be read as one. The per-step drawers stay collapsed
    so the six-step argument is still legible above the fold."""
    rows = "".join(
        f'<tr><td>{_e(v.label)}</td><td class="n">{_e(v.shown)}</td>'
        f'<td><code>{_e(v.command)}</code></td></tr>'
        for v in values)
    return f"""<details class="ev"{' open' if start_open else ''}><summary>{_e(title)}</summary>
<table class="prov"><thead><tr><th>value</th><th>shown</th>
<th>expression that reproduces it, run from the repo root</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="xn">{_e(unchecked_note(values))}</p>
<dl class="srcmeta"><dt>file</dt><dd><a href="{_e(src.url)}">{_e(src.rel)}</a></dd>
<dt>sha256</dt><dd>{_e(src.sha256)}</dd>
<dt>bytes</dt><dd>{src.size}</dd>
<dt>bundle last changed in</dt><dd>{_e(src.commit)}<br><span class="pinnote">the last commit that touched this file, not the repository's current HEAD. An unrelated commit does not move this pin.</span></dd>
<dt>{_e(src.recipe_label)}</dt><dd>{_e(src.produced_by)}</dd></dl>
<p class="xn">{_e(src.replay_note)}</p>
<div class="term">{_e(src.replay)}</div>{extra}</details>"""


def hole_explorer(src, d) -> str:
    """The four survivals, at card weight, as the page's conclusion.

    Each card prints the mutant VERBATIM. A survival described in the abstract ("a negation was
    inserted") is a claim; the exact string that got past the check is the evidence, and it is
    short enough that a reader can judge for themselves whether the check should have caught it.

    The two groups are separated because they are different facts. Charging a documented scope
    limit as a broken check would be the same overclaim this program refuses, pointed the other
    way."""
    manifest = read("evalmut/docs/dogfood_fixtures.json") or {}
    found = holes(d, manifest)
    by_kind: dict[str, list] = {}
    for h in found:
        by_kind.setdefault(h.kind, []).append(h)

    tally = "".join(
        f'<span class="hk{"" if n else " zero"}"><b>{n}</b> {_e(label.lower())}'
        f'{"" if n == 1 else "s"}</span>' for _, label, n in counts(d))

    groups = []
    for kind, group in by_kind.items():
        cards = "".join(f"""<article class="hole">
<header><span class="st">{_e(SURVIVED.glyph)} {_e(SURVIVED.label)}</span>
<h3>{_e(h.operator)}</h3>
<span class="hmeta">scorer <b>{_e(h.grader)}</b> &middot; layer {_e(h.family)}
&middot; case {_e(h.case)}</span></header>
<p class="shape">{_e(h.shape)}</p>
<div class="mut"><span class="mlab">the check required</span>
<code>{_e(h.requirement)}</code>
<span class="mlab">clean form, passed</span>
<code class="ok">{_e(h.clean) if h.clean else "not resolvable from the manifest"}</code>
<span class="mlab">defective form, also passed</span>
<code class="got">{_e(h.mutant)}</code></div>
<p class="pair">{_e(h.pairing)}</p>
<p class="why"><b>Where this comes from.</b> {_e(h.origin)}</p>
<p class="rem">{_e(h.remedy)}</p>
<p class="hsrc"><code>jq '{_e(h.jq)}' {_e(DOGFOOD)}</code><br>
replay: the pinned route in the evidence drawer above regenerates this bundle at
{_e(src.commit)}.</p>
</article>""" for h in group)
        label, means = group[0].label, group[0].means
        groups.append(f"""<section class="hgroup">
<h2>{len(group)} &times; {_e(label)}</h2><p class="gmeans">{_e(means)}</p>
<div class="holes">{cards}</div></section>""")

    return f"""<section id="holes">
<p class="kicker">The finding</p>
<h2 class="hh">{len(found)} declared defects were not detected</h2>
<p class="hlede"><b>Survived</b> means the clean form and the defective form BOTH passed the same
check under the recorded protocol, so the check cannot separate them. That is a named coverage
hole in the check. It is not evidence that the system under test misbehaves in production, and
this run cannot support that reading.</p>
<div class="htally">{tally}</div>
{''.join(groups)}
<div class="limits"><p><b>What this run is.</b> Hypothesis-generating. It names places to look,
on one corpus, under one recorded protocol.</p>
<p><b>What it is not.</b> The fixtures here are evalmut's own corpus, so nothing on this page
confirms detection power against an external suite. No percentage here is a score for any
framework, and a per-scorer number is conditional on these fixtures rather than a property of
the scorer.</p>
<p><b>Independent validity is unestablished.</b> Whether these operators correspond to faults
anyone else would care about missing is an open question, currently out for external review.
See the status audit in the repository.</p></div>
<p class="hnote">The kinds with a zero above are printed rather than omitted. A taxonomy that
lists only its non-empty categories invites the reader to assume the categories were chosen after
the results were in.</p></section>"""


def steps(src, d) -> list[dict]:
    out: list[dict] = []

    # 1 AUDIT
    if d:
        vals = audit_values(src, d)
        holes = next(v.shown for v in vals if v.label == "holes found")
        out.append(dict(n=1, verb="AUDIT", tool="evalmut",
                        q="Would your checks notice a planted defect?",
                        head=f"{holes} holes", ok=True, values=vals, src=src,
                        note="An operator declines when it cannot prove its mutant is wrong. "
                             "That refusal is why a hole is a fact and not a guess."))
    else:
        out.append(dict(n=1, verb="AUDIT", tool="evalmut", ok=False, head="artifact missing",
                        q="Would your checks notice a planted defect?", values=[], src=None,
                        note=f"wanted evalmut/{DOGFOOD}"))

    # 2 CALIBRATE
    fleet_src, fleet = bound("reference-fleet", BOARD,
                             how=lambda: bundled_recipe("reference-fleet", BOARD,
                                                        "board/vac/vac.json"))
    if fleet:
        vals = calibrate_values(fleet_src, fleet)
        pairs = next(v.shown for v in vals if v.label == "naive-archetype pairs")
        det = next(v.shown for v in vals if v.label == "of those, detecting at all")
        out.append(dict(n=2, verb="CALIBRATE", tool="reference-fleet",
                        q="Can the instrument detect a model that is broken on purpose?",
                        head=f"{det} of {pairs}", ok=True, values=vals, src=fleet_src,
                        note="Each member is broken in one documented way at a seeded rate, so a "
                             "detection rate is measured against ground truth rather than "
                             "opinion. The head counts the naive archetype only: a suite that "
                             "misses a defect it was pointed at is the calibration, and reading "
                             "it as a ranking of the other archetypes would be a claim this one "
                             "board cannot carry."))
    else:
        out.append(dict(n=2, verb="CALIBRATE", tool="reference-fleet", ok=False,
                        head="artifact missing", q="Can the instrument detect known-bad?",
                        values=[], src=None, note=f"wanted reference-fleet/{BOARD}"))

    # 3 CERTIFY
    cert = latest_cert()
    rel = str(cert.relative_to(HOME / "agent-certlab")) if cert else "certifications/*/bundle.json"
    cert_src, b = bound("agent-certlab", rel,
                        how=lambda: bundled_recipe("agent-certlab", rel,
                                                   rel.replace("bundle.json", "vac.json")))
    if b:
        vals = certify_values(cert_src, b)
        fixed = next(v.shown for v in vals if v.label == "seeded defects fixed")
        tasks = next(v.shown for v in vals if v.label == "tasks in the family")
        out.append(dict(n=3, verb="CERTIFY", tool="agent-certlab",
                        q="What can this agent do, and where exactly does it fail?",
                        head=f"{fixed}/{tasks}", ok=True, values=vals, src=cert_src,
                        note="Graded from artifacts on disk, never from what the agent said it "
                             "did. Policy first (suite byte-identical, allowed paths), then "
                             "tests: an agent that deletes the suite fails BY POLICY while "
                             "pytest is green. This is the last certification directory in "
                             "sorted order, chosen before any result was read, because a page "
                             "that picked its best bundle would be grading itself."))
    else:
        out.append(dict(n=3, verb="CERTIFY", tool="agent-certlab", ok=False,
                        head="no certification found", q="What can this agent do?", values=[],
                        src=None, note=f"wanted agent-certlab/{rel}"))

    # 4 PRESERVE
    reg_src, reg = bound("vac-protocol", REGISTRY,
                         how=lambda: {"produced_by": documented_command(
                             "vac-protocol", REGISTRY, "vac/registry.py")})
    if reg:
        vals = preserve_values(reg_src, reg)
        entries = next(v.shown for v in vals if v.label == "bundles in registry")
        out.append(dict(n=4, verb="PRESERVE", tool="vac-protocol",
                        q="Is there enough evidence to replay the conclusion later?",
                        head=entries, ok=True, values=vals, src=reg_src,
                        note="A bundle pins claim and limitations, the subject and its version, "
                             "the protocol and fixtures, raw artifacts and hashes, the "
                             "derivation, and the command to replay it. No wall-clock: a claim "
                             "dies when a bound input changes, not when a date passes. The "
                             "registry is a reviewed file in the repo, so this count is what "
                             "survived the verifier, not what was submitted."))
    else:
        out.append(dict(n=4, verb="PRESERVE", tool="vac-protocol", ok=False,
                        head="registry missing", q="Can the conclusion be replayed?", values=[],
                        src=None, note=f"wanted vac-protocol/{REGISTRY}"))

    return out


def challenge() -> dict:
    """Step 5, executed live at build time: clean passes, tampered is refused by name.

    THE DEFECT THIS SHAPE EXISTS TO REFUSE. An earlier version appended every fixture it
    attempted to one `refusals` list and rendered len() of it as "N refused". When the verifier
    binary was not on PATH, all six invocations returned rc -1 and the page still published
    "5 refused" six lines above six FileNotFoundError transcripts. A count taken from the length
    of an attempt list is not a measurement, and this page exists to refuse exactly that.

    So an attempt is classified, never counted: REFUSED means the verifier ran and rejected the
    bundle, UNLAUNCHED means it never ran at all. Those are different facts and collapsing them
    is how a page starts showing green over a check that did not happen. An unlaunched verifier
    yields no capability conclusion, which is INCOMPLETE in this page's own vocabulary, and the
    step says so instead of reporting a number."""
    clean = sorted((VAC / "examples").glob("*"))
    clean_rc, clean_line, _ = run_verifier(clean[0]) if clean else (-1, "no example bundle", 0)
    picks = ["tamper-summary-score", "tamper-evalmut-rows", "tamper-stamp-deleted",
             "tamper-empty-limitations", "tamper-missing-artifact"]
    attempts = []
    for name in picks:
        fixture = VAC / "fixtures" / name
        if not fixture.exists():
            attempts.append({"name": name, "rc": None, "line": "fixture not on disk",
                             "state": "MISSING"})
            continue
        rc, line, n_named = run_verifier(fixture)
        if rc < 0:
            state = "UNLAUNCHED"
        elif rc == 0:
            state = "NOT_REFUSED"
        else:
            state = "REFUSED"
        attempts.append({"name": name, "rc": rc, "line": line, "state": state,
                         "n_named": n_named})

    refused = [a for a in attempts if a["state"] == "REFUSED"]
    unlaunched = [a for a in attempts if a["state"] == "UNLAUNCHED"]
    not_refused = [a for a in attempts if a["state"] == "NOT_REFUSED"]
    clean_launched = clean_rc >= 0

    if unlaunched or not clean_launched:
        ok, head = False, "verifier did not run"
    elif not_refused:
        ok, head = False, f"{len(not_refused)} tampered bundle(s) PASSED"
    elif clean_rc != 0:
        ok, head = False, "clean bundle was refused"
    else:
        ok, head = True, f"{len(refused)} of {len(attempts)} refused"

    return {"clean": {"name": clean[0].name if clean else "-", "rc": clean_rc,
                      "line": clean_line, "launched": clean_launched},
            "attempts": attempts, "refusals": refused, "ok": ok, "head": head}


CSS = """
:root{color-scheme:dark light;--ink:#0e1316;--panel:#141c21;--raised:#1b252b;
--line:rgba(255,255,255,.09);--line-2:rgba(255,255,255,.05);
--fg:#dae2e4;--fg-dim:#8a989e;--fg-faint:#5e6c72;
--amber:#f2a53c;--amber-soft:rgba(242,165,60,.13);--amber-line:rgba(242,165,60,.34);
/* The accent, restepped for text on a panel. The display amber measures 3.4:1 on the
   light surface, and the command in the evidence drawer is the one string a skeptic
   has to be able to read. Kept as a separate token so the decorative amber stays
   exactly as bright as it should be for rules, glyphs and headings. */
--amber-ink:#f2a53c;
%%STATEVARS%%
--mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--maxw:900px}
@media (prefers-color-scheme:light){:root{--ink:#e9edee;--panel:#f4f6f6;--raised:#fff;
--line:rgba(12,26,32,.12);--line-2:rgba(12,26,32,.07);--fg:#131c20;--fg-dim:#4d5a60;
--fg-faint:#7c888d;--amber:#b7761a;--amber-soft:rgba(200,128,26,.12);
--amber-line:rgba(200,128,26,.4);--amber-ink:#8a5610;--teal:#1c8f7d;--hot:#a8412c;
--hot-soft:rgba(168,65,44,.1);
%%STATEVARSLIGHT%%}}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--fg);font:15px/1.55 var(--sans);
-webkit-font-smoothing:antialiased}
.nav{position:fixed;top:12px;left:14px;z-index:99;font-family:var(--mono);font-size:13px}
.nav a{color:var(--amber);background:var(--panel);border:1px solid var(--amber-line);
border-radius:4px;padding:6px 11px;text-decoration:none;font-weight:600}
.wrap{max-width:var(--maxw);margin:0 auto;padding:4.5rem 1.25rem 4rem}
.kicker{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;color:var(--amber);
text-transform:uppercase}
h1{font-size:2rem;line-height:1.18;letter-spacing:-.02em;margin:.5rem 0 .8rem;font-weight:650;
max-width:22ch}
.thesis{border-left:2px solid var(--amber);padding-left:1rem;color:var(--fg-dim);
max-width:56ch;margin:0 0 1.6rem;font-size:1rem}
.thesis b{color:var(--fg)}
.ctl{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:0 0 2rem}
button{font-family:var(--mono);font-size:.78rem;color:var(--ink);background:var(--amber);
border:1px solid var(--amber);border-radius:999px;padding:.45rem 1.2rem;cursor:pointer;
font-weight:600}
button.ghost{color:var(--fg);background:var(--panel);border-color:var(--line)}
button:hover{filter:brightness(1.08)}
.step{border:1px solid var(--line);border-radius:5px;margin:0 0 .7rem;background:var(--panel);
opacity:.32;transition:opacity .35s ease,border-color .35s ease}
.step.on{opacity:1;border-color:var(--amber-line)}
.step.absent{border-color:var(--bad);border-style:dashed}
.head{display:flex;align-items:baseline;gap:.8rem;padding:1rem 1.2rem;flex-wrap:wrap}
.num{font-family:var(--mono);font-size:.7rem;color:var(--fg-faint);min-width:1.2rem}
.verb{font-family:var(--mono);font-size:.76rem;letter-spacing:.12em;color:var(--amber);
font-weight:700}
.tool{font-family:var(--mono);font-size:.74rem;color:var(--fg-faint)}
.big{margin-left:auto;font-family:var(--mono);font-size:1.25rem;font-weight:650;color:var(--fg);
font-variant-numeric:tabular-nums}
.step.absent .big{color:var(--bad);font-size:.85rem}
.body{padding:0 1.2rem 1.1rem;display:none}
.step.on .body{display:block}
.q{color:var(--fg);font-size:.95rem;margin:0 0 .8rem}
dl{margin:0 0 .9rem;font-family:var(--mono);font-size:.75rem;display:grid;
grid-template-columns:1fr auto;gap:.28rem 1rem}
dt{color:var(--fg-faint)}dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.note{color:var(--fg-dim);font-size:.85rem;margin:0 0 .8rem;max-width:60ch}
.src{font-family:var(--mono);font-size:.68rem;color:var(--fg-faint);border-top:1px dashed
var(--line);padding-top:.6rem;word-break:break-all}
.term{font-family:var(--mono);font-size:.74rem;background:var(--ink);border:1px solid var(--line);
border-radius:3px;padding:.7rem .8rem;margin:.5rem 0 0;overflow-x:auto;white-space:pre-wrap;
word-break:break-word}
.bounds{border:1px solid var(--line);border-radius:4px;padding:.9rem 1.1rem;margin:0 0 1.2rem;
background:var(--panel)}
.bounds p{margin:0 0 .5rem;font-size:.86rem;color:var(--fg-dim)}
.bounds b{color:var(--fg)}
.bounds .derived{font-size:.74rem;color:var(--fg-faint);margin:0}
.bounds a{color:var(--fg-faint)}
.modes{display:grid;gap:.35rem;margin:0 0 1.4rem;font-size:.76rem;color:var(--fg-faint)}
.modes b{color:var(--amber);font-weight:600}
.legend{display:grid;gap:.5rem;margin:0 0 1.6rem;padding:.9rem 1rem;background:var(--panel);
border:1px solid var(--line);border-radius:4px}
.lg{font-size:.78rem;color:var(--fg-dim);display:grid;grid-template-columns:1.3rem auto;
gap:.1rem .5rem}
/* The glyph is the state's NON-COLOUR encoding, the thing that survives greyscale print and
   colour blindness. Shipping it at --fg-faint measured 3.36:1 on the light ground, which
   makes the accessibility fallback itself the least legible mark on the page. */
.lg i{font-style:normal;font-family:var(--mono);grid-row:span 2;color:var(--fg-dim)}
.lg b{color:var(--fg);font-weight:600}
.lg em{font-style:normal;color:var(--fg-faint);font-size:.74rem;grid-column:2}
.term .pass{color:var(--ok)}
.term .fail{color:var(--bad)}
.term .warn{color:var(--amber)}
.provisional{margin:.5rem 0 0;font-size:.84rem;color:var(--fg-dim);max-width:64ch;
border-left:3px solid var(--amber);padding-left:.7rem}
.provisional b{color:var(--amber-ink,var(--amber))}
.term .cmd{color:var(--fg-faint)}
details.ev{border-top:1px dashed var(--line);margin:.9rem 0 0;padding-top:.6rem}
details.ev summary{font-family:var(--mono);font-size:.72rem;color:var(--fg-faint);cursor:pointer;
list-style:none}
details.ev summary::-webkit-details-marker{display:none}
details.ev summary::before{content:"\\25B8 ";color:var(--amber)}
details.ev[open] summary::before{content:"\\25BE "}
details.ev summary:hover{color:var(--amber)}
/* The command must be readable where it is printed. An expression that scrolls out of the
   viewport is a citation a reader has to work for, so the cell wraps and the container keeps
   overflow-x only as a floor for very narrow screens. */
table.prov{width:100%;border-collapse:collapse;margin:.7rem 0 .5rem;font-size:.7rem;
font-family:var(--mono);display:block;overflow-x:auto}
table.prov td:last-child{word-break:break-all;white-space:normal;line-height:1.45}
table.prov td:first-child,table.prov td.n{white-space:nowrap}
/* --fg-faint measures about 3.6:1 on the light panel, which is under AA for text this size.
   Column headers name what each column IS, so they take the readable token rather than the
   decorative one. The global token is left alone: it is correct for the incidental captions it
   was chosen for, and changing it would repaint every page in the estate. */
table.prov th{text-align:left;color:var(--fg-dim);font-weight:600;border-bottom:1px solid
var(--line);padding:.3rem .7rem .3rem 0}
table.prov td{padding:.28rem .7rem .28rem 0;border-bottom:1px solid var(--line-2);
color:var(--fg-dim);vertical-align:top}
table.prov td.n{color:var(--fg);text-align:right;font-variant-numeric:tabular-nums}
table.prov code{color:var(--amber-ink);background:none}
table.prov td.ck{color:var(--ok)}
.xn{font-size:.7rem;color:var(--fg-faint);margin:.5rem 0 .3rem;max-width:66ch;white-space:normal}
dl.srcmeta{margin:.6rem 0;font-family:var(--mono);font-size:.68rem;
grid-template-columns:max-content auto;gap:.2rem .9rem}
dl.srcmeta dt{color:var(--fg-faint)}
dl.srcmeta dd{margin:0;text-align:left;color:var(--fg-dim);word-break:break-all}
dl.srcmeta a{color:var(--fg-dim)}
.pinnote{display:block;color:var(--fg-faint);margin-top:.15rem;max-width:52ch;white-space:normal;line-height:1.5}
/* The holes are the conclusion, so they get the page's only full-weight section heading and the
   only cards. The score keeps monospace row treatment inside step 1: a percentage that outranks
   the findings typographically has made the reader's judgement for them. */
#holes{margin:3rem 0 0;padding-top:1.6rem;border-top:1px solid var(--hole)}
h2.hh{font-size:1.5rem;line-height:1.2;letter-spacing:-.015em;margin:.45rem 0 .7rem;
font-weight:650;max-width:20ch}
.hlede{color:var(--fg-dim);max-width:60ch;margin:0 0 1.2rem}
.htally{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1.8rem}
.hk{font-family:var(--mono);font-size:.72rem;color:var(--hole);background:var(--hole-soft);
border:1px solid var(--hole);border-radius:999px;padding:.25rem .7rem}
.hk b{font-variant-numeric:tabular-nums}
/* The zero chips are the whole point of printing empty buckets, so they are de-emphasised
   relative to the found ones but still have to be READ. --fg-faint put them at 3.09:1. */
.hk.zero{color:var(--fg-dim);background:none;border-color:var(--line)}
.hgroup{margin:0 0 1.8rem}
.hgroup h2{font-family:var(--mono);font-size:.82rem;letter-spacing:.06em;color:var(--hole);
margin:0 0 .3rem;font-weight:700;text-transform:uppercase}
.gmeans{color:var(--fg-dim);font-size:.86rem;margin:0 0 .9rem;max-width:62ch}
.holes{display:grid;grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));gap:.8rem}
.hole{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--hole);
border-radius:4px;padding:1rem 1.1rem;display:flex;flex-direction:column}
.hole header{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;margin:0 0 .5rem}
/* The state is named on the card, not just coloured. A reader who meets an amber card with no
   word for it will read it as failure, and the four-state vocabulary is the thing that stops
   this page collapsing into pass/fail. */
.hole .st{font-family:var(--mono);font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;
color:var(--hole);border:1px solid var(--hole);border-radius:3px;padding:.1rem .4rem;
white-space:nowrap}
.hole h3{font-family:var(--mono);font-size:.86rem;margin:0;font-weight:650;color:var(--fg);
word-break:break-word}
.hmeta{font-family:var(--mono);font-size:.68rem;color:var(--fg-faint);width:100%}
.shape{font-size:.88rem;color:var(--fg);margin:0 0 .8rem}
.mut{background:var(--ink);border:1px solid var(--line);border-radius:3px;padding:.6rem .7rem;
margin:0 0 .8rem;display:grid;gap:.25rem}
.mlab{font-family:var(--mono);font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;
color:var(--fg-faint)}
.mut code{font-family:var(--mono);font-size:.74rem;color:var(--fg-dim);word-break:break-word;
white-space:pre-wrap}
.mut code.ok{color:var(--ok)}
.mut code.got{color:var(--hole)}
.pair{font-size:.78rem;color:var(--fg-dim);margin:0 0 .7rem;max-width:60ch}
.hmeta b{color:var(--fg-dim);font-weight:600}
.limits{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--fg-faint);
border-radius:4px;padding:1rem 1.1rem;margin:.4rem 0 0}
.limits p{margin:0 0 .6rem;font-size:.82rem;color:var(--fg-dim);max-width:64ch}
.limits p:last-child{margin:0}
.limits b{color:var(--fg)}
.why{font-size:.78rem;color:var(--fg-dim);margin:0 0 .7rem;max-width:60ch}
.why b{color:var(--fg)}
.rem{font-size:.78rem;color:var(--fg);margin:0 0 .7rem;font-weight:500}
.hsrc{margin:auto 0 0;padding-top:.7rem;border-top:1px dashed var(--line);font-size:.66rem;
word-break:break-all}
.hsrc code{font-family:var(--mono);color:var(--amber-ink)}
.hnote{font-size:.76rem;color:var(--fg-faint);max-width:64ch;margin:1.2rem 0 0}
footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--fg-faint);
font-size:.78rem;line-height:1.7;max-width:64ch}
footer b{color:var(--fg-dim)}
footer a{color:var(--amber)}
"""


def build() -> str:
    # The publication boundary, run BEFORE anything is emitted. The console may only make an
    # invocation claim from the artifact its manifest pins, so a build that cannot accept that
    # evidence stops here rather than producing a page. Nothing is caught: there is no degraded
    # output to fall back to, by design.
    #
    # The accepted object is not yet rendered. Wiring the display is a separate, reviewable
    # change, and putting the gate in first means the boundary exists before anything depends
    # on it rather than being invented at the moment a claim gets upgraded.
    witness = accept_witness()

    src = source("evalmut", DOGFOOD)
    d = read(f"evalmut/{DOGFOOD}")
    # Derived from the ACCEPTED witness object, not from a second read of the unwitnessed
    # export. The two agree today, verified row by row, but only one of them has been hashed
    # against the manifest, and the headline may only come from that one.
    claim = derive(HOME / WITNESS_ARTIFACT, obj=witness)
    wp = witness["witness_protocol"]
    rc, stamp = wp["row_counts"], wp["stamp"]
    lib = ", ".join(f'{x["name"]} {x["version"]}' for x in wp["libraries"])
    # The headline derives from the witnessed artifact, so its drawer must cite THAT file. A
    # drawer naming a different export than the numbers came from is the cross-artifact mismatch
    # the publication gate exists to refuse, reproduced one layer up in the presentation.
    wsrc = source("evalmut", WITNESS_ARTIFACT.split("/", 1)[1],
                  produced_by=documented_command("evalmut", WITNESS_ARTIFACT.split("/", 1)[1],
                                                 "evalmut/invocation_witness.py"))
    _pin = json.loads((pathlib.Path(__file__).resolve().parent / "witness.manifest.json").read_text())
    art, sha, pub = _pin["artifact"], _pin["sha256"], _pin["public_url"]

    st = steps(src, d)
    ch = challenge()
    bv = browser_panel()
    absent = sum(1 for s in st if not s["ok"])

    cards = []
    for s in st:
        rows = "".join(f'<dt>{_e(v.label)}</dt><dd>{_e(v.shown)}</dd>' for v in s["values"])
        ev = drawer("Evidence for these numbers", s["values"], s["src"]) if s["values"] else ""
        cards.append(f"""<div class="step{'' if s['ok'] else ' absent'}" data-i="{s['n']}">
<div class="head"><span class="num">{s['n']}</span><span class="verb">{_e(s['verb'])}</span>
<span class="tool">{_e(s['tool'])}</span><span class="big">{_e(s['head'])}</span></div>
<div class="body"><p class="q">{_e(s['q'])}</p>{f'<dl>{rows}</dl>' if rows else ''}
<p class="note">{_e(s['note'])}</p>{ev}</div></div>""")

    def _more(r):
        n = r.get("n_named") or 0
        return f"   (first of {n} named reasons)" if n > 1 else ""

    ref = "".join(
        f'<span class="cmd">$ vac-verify fixtures/{_e(r["name"])}</span>\n'
        f'<span class="{"fail" if r["state"] == "REFUSED" else "warn"}">'
        f'exit {r["rc"]}  {_e(r["line"])}{_more(r)}</span>\n\n' for r in ch["attempts"])
    cards.append(f"""<div class="step{'' if ch['ok'] else ' absent'}" data-i="5">
<div class="head"><span class="num">5</span><span class="verb">CHALLENGE</span>
<span class="tool">vac-verify</span>
<span class="big">{_e(ch['head'])}</span></div>
<div class="body"><p class="q">Does the verifier reject manipulated evidence, by name?</p>
<p class="note">This is the step a competitor cannot answer by adding a metric. Every line below
was produced by running the real verifier at build time, against a clean bundle and against
deliberately corrupted ones. A verifier that has never been seen refusing is indistinguishable
from one that cannot.</p>
<div class="term"><span class="cmd">$ vac-verify examples/{_e(ch['clean']['name'])}</span>
<span class="pass">exit {ch['clean']['rc']}  {_e(ch['clean']['line'])}</span>

{ref}</div>
<p class="src">executed by suite/runner.py at build time. Each line is real output, not a
quotation. Where a fixture printed more than one named reason the first is shown and the count
says so; run the command yourself for the rest.</p></div></div>""")

    cards.append("""<div class="step" data-i="6">
<div class="head"><span class="num">6</span><span class="verb">LIMITS</span>
<span class="tool">the bundle</span><span class="big">published</span></div>
<div class="body"><p class="q">Are the failures published beside the findings?</p>
<p class="note">A bundle with empty limitations is refused, which is one of the failures shown
above. The claim and what it does not cover travel together or the bundle does not verify.</p>
<p class="note">What this stack does NOT establish: that any agent is safe, that an eval is
complete, or that a passing contract predicts behaviour outside the task families it names. It
establishes exactly what was tested, against what known-bad, with what evidence, and how to
re-run it.</p>
<p class="src">SPEC.md and INVALIDATION.md in vac-protocol</p></div></div>""")

    legend = "".join(
        f'<span class="lg"><i>{_e(g)}</i><b>{_e(lab)}</b> {_e(means)}'
        f'<em>not: {_e(nm)}</em></span>' for g, lab, means, nm in legend_rows())

    note = ("" if not absent else
            f'<p class="note" style="color:var(--bad)"><b>{absent} step(s) could not read their '
            "artifact</b> and are marked above. A missing source is shown, never replaced.</p>")

    css = (CSS.replace("%%STATEVARS%%", css_vars())
          .replace("%%STATEVARSLIGHT%%", css_vars_light()) + bv["css"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Verifiable Evaluation Suite</title>
<meta name="description" content="Six steps that test each other, ending with a verifier
refusing tampered evidence by name. Every number read from a committed artifact.">
<link rel="icon" type="image/svg+xml" href="/favicon.svg"><style>{css}</style></head><body>
<div class="nav"><a href="/">&larr; Portfolio</a></div>
<div class="wrap">
<p class="kicker">Verifiable Evaluation Suite &middot; Recorded proof run</p>
<h1>{_e(claim.headline)}</h1>
<p class="provisional"><b>Invocation witnesses: not captured per row.</b> This result is provisional. Wiring them may move the denominator, because a row with no witness is not a caught row and not a survivor, it is INCOMPLETE.</p>
<div class="bounds">
<p><b>Scope.</b> {_e(claim.scope)}</p>
<p><b>Does not establish.</b> {_e(claim.not_established)}</p>
<p><b>Invocation status.</b> These counts come from a pinned evalmut invocation-witness
artifact ({_e(wp["protocol"])}) for {_e(lib)}. Every counted row carries a recorded entry into
the named grader closure for both its clean control and its defective form, and each outcome
recomputes from the raw value that came back. Rows that cannot show that evidence are not counted
as outcomes: this run has {_e(str(rc["incomplete"]))} such rows out of {_e(str(rc["rows"]))}.
This page's build rejects a missing, hash-mismatched, incomplete or dirty-stamped artifact rather
than showing a weaker number.</p>
<p><b>What that is not.</b> A dogfood run against evalmut's own corpus. It is not an independent
benchmark, not a measurement of gradecore's quality, and not a claim about detection power on any
suite but this one. The witness proves the grader was entered and what it returned. It proves
nothing about what happened inside it.</p>
<dl class="srcmeta"><dt>artifact</dt><dd><a href="{_e(pub)}">{_e(art)}</a></dd>
<dt>sha256</dt><dd>{_e(sha)}</dd>
<dt>issuer commit</dt><dd>{_e(stamp["issuer_commit"])}</dd></dl>
<p class="derived">Every number above is derived from
<a href="{_e(src.url)}">{_e(DOGFOOD)}</a>
at build time. The build fails if that bundle contradicts itself.</p>
{drawer("Where each number in that sentence comes from", claim_values(wsrc, witness), wsrc,
        start_open=True)}</div>
<div class="modes">
<span><b>Recorded proof run</b> replays a completed run's artifacts. Nothing is executed here.</span>
<span>{bv['mode']}</span>
<span><b>Independent replay</b> re-runs the real verifier outside this page. Only this re-earns
the claim, and only this may be called live verification.</span></div>
<div class="legend">{legend}</div>
<div class="ctl"><button id="go">Run the stack</button>
<button class="ghost" id="step">Step</button>
<button class="ghost" id="rst">Reset</button></div>
{"".join(cards)}
{bv['html']}
{note}
{hole_explorer(src, d)}
<footer>Every number is read from the artifact its repo commits, and step 5 is <b>executed</b>
when this page is built, so the refusals are transcripts. Nothing here is typed by hand.<br><br>
This is not a benchmark and not a leaderboard. The point is to make an unsupported reliability
claim fail <b>mechanically</b> rather than merely look questionable.<br><br>
Try to falsify it: <a href="https://github.com/egnaro9/vac-protocol/blob/main/REPLAY_REQUEST.md">
REPLAY_REQUEST.md</a> names what to run, what it costs, and what counts as success, mismatch, or
cannot-decide.</footer>
</div>
<script>
const S=[...document.querySelectorAll('.step')];let i=0,t=null;
const g=id=>document.getElementById(id);
function step(){{ if(i>=S.length){{stop();return;}} S[i].classList.add('on');
  S[i].scrollIntoView({{behavior:'smooth',block:'center'}}); i++; }}
function stop(){{ clearInterval(t); t=null; g('go').textContent='Run the stack'; }}
g('go').onclick=()=>{{ if(t){{stop();return;}} g('go').textContent='Pause';
  step(); t=setInterval(step,1400); }};
g('step').onclick=()=>{{ stop(); step(); }};
g('rst').onclick=()=>{{ stop(); i=0; S.forEach(s=>s.classList.remove('on'));
  window.scrollTo({{top:0,behavior:'smooth'}}); }};
</script></body></html>"""


if __name__ == "__main__":
    # An optional destination so tests can build to a scratch path and COMPARE, instead of
    # overwriting the committed page. Without this the rendered-page tests silently regenerate
    # the artifact they claim to inspect, which means a stale committed runner.html passes every
    # one of them. That is the same failure shape as a green suite over a check that never ran.
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    dest.write_text(build(), encoding="utf-8")
    print(f"wrote {dest}")
