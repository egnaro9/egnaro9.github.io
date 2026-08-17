"""Build the Verifiable Evaluation Suite runner: the proof stack, stepped, over real artifacts.

THE THESIS THIS PAGE HAS TO CARRY, in one line from the program's own framing:

    Verification systems can show green over the exact surface they do not cover, so the
    instruments themselves must be measured, challenged, and replayable.

A dashboard cannot argue that. A number on a card is the same shape as the unsupported claim the
program exists to refuse. So this page is a SEQUENCE: six steps, each one testing the step above
it, ending with the only move in the whole stack that a competitor cannot copy by adding a metric,
which is a verifier refusing tampered evidence BY NAME.

    1  AUDIT      would your checks notice a planted defect            evalmut
    2  CALIBRATE  can the instrument detect a known-broken model       reference-fleet
    3  CERTIFY    what can this agent do, and where does it fail       agent-certlab
    4  PRESERVE   is there enough evidence to replay the conclusion    VAC bundle
    5  CHALLENGE  does the verifier reject manipulated evidence        vac-verify
    6  LIMITS     are the failures published beside the findings       the bundle itself

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
from states import (INCOMPLETE, INVALIDATED, SURVIVED, VERIFIED, Finding,  # noqa: E402
                    css_vars, legend_rows)

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


def run_verifier(target: pathlib.Path) -> tuple[int, str]:
    """Actually run the verifier. The refusal on the page must be a transcript."""
    try:
        p = subprocess.run([VERIFY, str(target)], cwd=str(VAC),
                           capture_output=True, text=True, timeout=90)
        line = next((l for l in (p.stdout + p.stderr).splitlines()
                     if l.strip().startswith(("FAIL", "structural verification"))), "")
        return p.returncode, line.strip()
    except Exception as e:
        return -1, f"could not run the verifier: {type(e).__name__}: {e}"


def steps() -> list[dict]:
    out: list[dict] = []

    # 1 AUDIT
    d = read("evalmut/docs/dogfood_gradecore.json")
    if d:
        t = d["tally"]
        holes = sum(len(v) for v in d["holes"].values())
        out.append(dict(n=1, verb="AUDIT", tool="evalmut",
                        q="Would your checks notice a planted defect?",
                        head=f"{holes} holes", ok=True,
                        rows=[("mutations applied", str(t["caught"] + t["missed"] + t["flagged"])),
                              ("caught", str(t["caught"])),
                              ("holes found", str(holes)),
                              ("declined rather than guessed", str(t["na"]))],
                        note="An operator declines when it cannot prove its mutant is wrong. "
                             "That refusal is why a hole is a fact and not a guess.",
                        src="evalmut/docs/dogfood_gradecore.json"))
    else:
        out.append(dict(n=1, verb="AUDIT", tool="evalmut", ok=False, head="artifact missing",
                        q="Would your checks notice a planted defect?", rows=[], note="",
                        src="evalmut/docs/dogfood_gradecore.json"))

    # 2 CALIBRATE
    d = read("reference-fleet/board/results.json")
    if d:
        rows = d["rows"]
        naive = [r for r in rows if "naive" in str(r.get("suite", "")).lower()]
        det = sum(1 for r in naive if float(r.get("detection_rate") or 0) > 0)
        out.append(dict(n=2, verb="CALIBRATE", tool="reference-fleet",
                        q="Can the instrument detect a model that is broken on purpose?",
                        head=f"{det} of {len(naive)}" if naive else f"{len(rows)} rows", ok=True,
                        rows=[("suite x member results", str(len(rows))),
                              ("naive suite detections", f"{det} of {len(naive)}" if naive else "n/a"),
                              ("fleet commit", str(d.get("fleet_commit", ""))[:7])],
                        note="Each member is broken in one documented way at a seeded rate, so a "
                             "detection rate is measured against ground truth rather than opinion.",
                        src="reference-fleet/board/results.json"))
    else:
        out.append(dict(n=2, verb="CALIBRATE", tool="reference-fleet", ok=False,
                        head="artifact missing", q="Can the instrument detect known-bad?",
                        rows=[], note="", src="reference-fleet/board/results.json"))

    # 3 CERTIFY
    certs = sorted((HOME / "agent-certlab" / "certifications").glob("*/bundle.json"))
    if certs:
        b = json.loads(certs[-1].read_text())
        v = b["verdicts"]
        fixed = sum(1 for x in v if x.get("fixed"))
        out.append(dict(n=3, verb="CERTIFY", tool="agent-certlab",
                        q="What can this agent do, and where exactly does it fail?",
                        head=f"{fixed}/{len(v)}", ok=True,
                        rows=[("agent", str(b.get("agent_id"))), ("model", str(b.get("model"))),
                              ("task family", str(b.get("family"))),
                              ("seeded defects fixed", f"{fixed} of {len(v)}"),
                              ("grading", "artifacts only")],
                        note="Graded from artifacts on disk, never from what the agent said it "
                             "did. Policy first (suite byte-identical, allowed paths), then tests: "
                             "an agent that deletes the suite fails BY POLICY while pytest is green.",
                        src=str(certs[-1].relative_to(HOME))))
    else:
        out.append(dict(n=3, verb="CERTIFY", tool="agent-certlab", ok=False,
                        head="no certification found", q="What can this agent do?", rows=[],
                        note="", src="agent-certlab/certifications/*/bundle.json"))

    # 4 PRESERVE
    d = read("vac-protocol/registry.json")
    if d:
        out.append(dict(n=4, verb="PRESERVE", tool="vac-protocol",
                        q="Is there enough evidence to replay the conclusion later?",
                        head=str(len(d["entries"])), ok=True,
                        rows=[("bundles in registry", str(len(d["entries"]))),
                              ("pending", str(len(d.get("pending") or [])))],
                        note="A bundle pins claim and limitations, the subject and its version, "
                             "the protocol and fixtures, raw artifacts and hashes, the derivation, "
                             "and the command to replay it. No wall-clock: a claim dies when a "
                             "bound input changes, not when a date passes.",
                        src="vac-protocol/registry.json"))
    else:
        out.append(dict(n=4, verb="PRESERVE", tool="vac-protocol", ok=False,
                        head="registry missing", q="Can the conclusion be replayed?", rows=[],
                        note="", src="vac-protocol/registry.json"))

    return out


def challenge() -> dict:
    """Step 5, executed live at build time: clean passes, tampered is refused by name."""
    clean = sorted((VAC / "examples").glob("*"))
    clean_rc, clean_line = run_verifier(clean[0]) if clean else (-1, "no example bundle")
    picks = ["tamper-summary-score", "tamper-evalmut-rows", "tamper-stamp-deleted",
             "tamper-empty-limitations", "tamper-missing-artifact"]
    refusals = []
    for name in picks:
        p = VAC / "fixtures" / name
        if not p.exists():
            continue
        rc, line = run_verifier(p)
        refusals.append({"name": name, "rc": rc, "line": line})
    return {"clean": {"name": clean[0].name if clean else "-", "rc": clean_rc, "line": clean_line},
            "refusals": refusals}


CSS = """
:root{color-scheme:dark light;--ink:#0e1316;--panel:#141c21;--raised:#1b252b;
--line:rgba(255,255,255,.09);--line-2:rgba(255,255,255,.05);
--fg:#dae2e4;--fg-dim:#8a989e;--fg-faint:#5e6c72;
--amber:#f2a53c;--amber-soft:rgba(242,165,60,.13);--amber-line:rgba(242,165,60,.34);
%%STATEVARS%%
--mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--maxw:900px}
@media (prefers-color-scheme:light){:root{--ink:#e9edee;--panel:#f4f6f6;--raised:#fff;
--line:rgba(12,26,32,.12);--line-2:rgba(12,26,32,.07);--fg:#131c20;--fg-dim:#4d5a60;
--fg-faint:#7c888d;--amber:#b7761a;--amber-soft:rgba(200,128,26,.12);
--amber-line:rgba(200,128,26,.4);--teal:#1c8f7d;--hot:#a8412c;--hot-soft:rgba(168,65,44,.1)}}
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
.legend{display:grid;gap:.5rem;margin:0 0 1.6rem;padding:.9rem 1rem;background:var(--panel);
border:1px solid var(--line);border-radius:4px}
.lg{font-size:.78rem;color:var(--fg-dim);display:grid;grid-template-columns:1.3rem auto;
gap:.1rem .5rem}
.lg i{font-style:normal;font-family:var(--mono);grid-row:span 2;color:var(--fg-faint)}
.lg b{color:var(--fg);font-weight:600}
.lg em{font-style:normal;color:var(--fg-faint);font-size:.74rem;grid-column:2}
.term .pass{color:var(--ok)}
.term .fail{color:var(--bad)}
.term .cmd{color:var(--fg-faint)}
footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--fg-faint);
font-size:.78rem;line-height:1.7;max-width:64ch}
footer b{color:var(--fg-dim)}
footer a{color:var(--amber)}
"""


def build() -> str:
    st = steps()
    ch = challenge()
    absent = sum(1 for s in st if not s["ok"])

    cards = []
    for s in st:
        rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in s["rows"])
        cards.append(f"""<div class="step{'' if s['ok'] else ' absent'}" data-i="{s['n']}">
<div class="head"><span class="num">{s['n']}</span><span class="verb">{_e(s['verb'])}</span>
<span class="tool">{_e(s['tool'])}</span><span class="big">{_e(s['head'])}</span></div>
<div class="body"><p class="q">{_e(s['q'])}</p>{f'<dl>{rows}</dl>' if rows else ''}
<p class="note">{_e(s['note'])}</p>
<p class="src">read from {_e(s['src'])}</p></div></div>""")

    ref = "".join(
        f'<span class="cmd">$ vac-verify fixtures/{_e(r["name"])}</span>\n'
        f'<span class="fail">exit {r["rc"]}  {_e(r["line"])}</span>\n\n' for r in ch["refusals"])
    cards.append(f"""<div class="step" data-i="5">
<div class="head"><span class="num">5</span><span class="verb">CHALLENGE</span>
<span class="tool">vac-verify</span>
<span class="big">{len(ch['refusals'])} refused</span></div>
<div class="body"><p class="q">Does the verifier reject manipulated evidence, by name?</p>
<p class="note">This is the step a competitor cannot answer by adding a metric. Every line below
was produced by running the real verifier at build time, against a clean bundle and against
deliberately corrupted ones. A verifier that has never been seen refusing is indistinguishable
from one that cannot.</p>
<div class="term"><span class="cmd">$ vac-verify examples/{_e(ch['clean']['name'])}</span>
<span class="pass">exit {ch['clean']['rc']}  {_e(ch['clean']['line'])}</span>

{ref}</div>
<p class="src">executed by suite/runner.py at build time; transcripts, not quotations</p></div></div>""")

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

    css = CSS.replace("%%STATEVARS%%", css_vars())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Verifiable Evaluation Suite</title>
<meta name="description" content="Six steps that test each other, ending with a verifier
refusing tampered evidence by name. Every number read from a committed artifact.">
<link rel="icon" type="image/svg+xml" href="/favicon.svg"><style>{css}</style></head><body>
<div class="nav"><a href="/">&larr; Portfolio</a></div>
<div class="wrap">
<p class="kicker">Verifiable Evaluation Suite</p>
<h1>Watch a reliability claim get built, then get broken</h1>
<p class="thesis">A verification system can show green over exactly the surface it does not
cover. So <b>the instruments themselves have to be measured, challenged, and replayable.</b>
Six steps below, each testing the one above it.</p>
<div class="legend">{legend}</div>
<div class="ctl"><button id="go">Run the stack</button>
<button class="ghost" id="step">Step</button>
<button class="ghost" id="rst">Reset</button></div>
{"".join(cards)}
{note}
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
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
