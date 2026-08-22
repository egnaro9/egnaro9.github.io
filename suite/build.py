"""Build the one page that shows the eval suite as one system.

WHY IT IS GENERATED AND NOT WRITTEN. A hand-typed portfolio page rots: a claim-audit of this
estate once found 19 problems across 56 claims, most of them pre-existing, because numbers were
copied at the moment they were true and never revisited. So every number here is READ from the
artifact the tool actually commits, at build time. Nothing on the page is typed by a person, and
a number that changes upstream changes here on the next build or the build fails loudly.

THE RULE THAT MAKES "VERIFIED" MEAN SOMETHING. A missing or unreadable artifact renders as a
visible ABSENT panel naming the path it wanted. It never falls back to a remembered value, never
hides the panel, and never quietly keeps yesterday's number: a page that silently drops a source
looks identical to a page whose sources are all healthy, which is the failure this whole estate
is built to refuse. Absence has to be louder than presence for the word "verified" to be earned.

Each panel therefore carries three things: the number, the exact file it came from, and a link to
that file on GitHub so a reader can check it in one click. The claim and the evidence never travel
separately.

    python3 build.py            # writes index.html next to this file
"""
from __future__ import annotations

import hashlib
import html
import json
import pathlib
import subprocess

HOME = pathlib.Path.home()
OUT = pathlib.Path(__file__).resolve().parent / "index.html"
GH = "https://github.com/egnaro9"


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def read(rel: str):
    """Load a repo artifact, or return None. Never raises: a broken source must become a visible
    ABSENT panel rather than a traceback that stops the whole page from building."""
    p = HOME / rel
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def sha8(rel: str) -> str:
    p = HOME / rel
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:8]
    except Exception:
        return "missing"


def commit(repo: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(HOME / repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


# Each panel is (title, what the tool answers, repo, artifact path, extractor).
# The extractor returns (headline, [(label, value), ...]) or raises to mark the panel ABSENT.

def _evalmut(d):
    t = d["tally"]
    holes = sum(len(v) for v in d["holes"].values())
    return (f"{d['score']:.1%}", [
        ("mutation score", f"{d['score']:.1%}"),
        ("caught / applied", f"{t['caught']} / {t['caught'] + t['missed'] + t['flagged']}"),
        ("holes found", str(holes)),
        ("declined, not guessed", str(t["na"])),
    ])


def _fleet(d):
    rows = d["rows"]
    suites = len({r["suite"] for r in rows})
    caught = sum(1 for r in rows if float(r.get("detection_rate") or 0) > 0)
    return (f"{caught}/{len(rows)}", [
        ("suite x member results", str(len(rows))),
        ("suite archetypes", str(suites)),
        ("pairs with any detection", f"{caught} of {len(rows)}"),
        ("fleet commit", str(d.get("fleet_commit", "?"))[:7]),
    ])


def _drift(d):
    real = [s for s in d["series"] if not str(s).startswith("mock:")]
    return (str(len(real)), [
        ("models tracked", str(len(real))),
        ("suite size", str(d["suite_size"])),
        ("last run", str(d["updated"])[:10]),
        ("control series", str(len(d["series"]) - len(real))),
    ])


def _certlab(d):
    s = d["results"]["summary"]
    return (f"{s['fixed']}/{s['tasks']}", [
        ("seeded defects fixed", f"{s['fixed']} of {s['tasks']}"),
        ("capability", str(d["claim"]["capability"]).split(" - ")[0][:60]),
        ("failure modes", str(len(s.get("failure_modes") or {}))),
    ])


def _crashkit(d):
    checks = d.get("results", {}).get("checks") or []
    return (f"{len(checks)}", [
        ("declared checks in bundle", str(len(checks))),
        ("capability", str(d["claim"]["capability"])[:70]),
    ])


def _vac(d):
    return (str(len(d["entries"])), [
        ("bundles in registry", str(len(d["entries"]))),
        ("pending", str(len(d.get("pending") or []))),
        ("registry version", str(d.get("registry_version"))),
    ])


PANELS = [
    ("evalmut", "Does your eval suite actually check anything?",
     "evalmut", "evalmut/docs/dogfood_gradecore.json", _evalmut),
    ("reference-fleet", "Which defect classes does a suite catch, against a known answer key?",
     "reference-fleet", "reference-fleet/board/results.json", _fleet),
    ("model-drift", "Did a model move, or is that inside the noise floor?",
     "model-drift", "model-drift/dashboard/metrics.json", _drift),
    ("agent-certlab", "Can this agent repair seeded defects under a stated policy?",
     "agent-certlab", "agent-certlab/certifications/claude-code-cloud-2026-08-14/vac.json", _certlab),
    ("crashkit", "Do the graders bite, with no LLM judge anywhere?",
     "crashkit", "crashkit/vac/vac.json", _crashkit),
    ("vac-protocol", "Can a stranger verify these bundles offline?",
     "vac-protocol", "vac-protocol/registry.json", _vac),
]

CSS = """
:root{color-scheme:dark light;--ink:#0e1316;--panel:#141c21;--raised:#1b252b;
--line:rgba(255,255,255,.09);--line-2:rgba(255,255,255,.05);
--fg:#dae2e4;--fg-dim:#8a989e;--fg-faint:#5e6c72;
--amber:#f2a53c;--amber-soft:rgba(242,165,60,.13);--amber-line:rgba(242,165,60,.34);
--teal:#48c1ac;--hot:#e0785f;
--mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--maxw:980px}
@media (prefers-color-scheme:light){:root{--ink:#e9edee;--panel:#f4f6f6;--raised:#fff;
--line:rgba(12,26,32,.12);--line-2:rgba(12,26,32,.07);--fg:#131c20;--fg-dim:#4d5a60;
--fg-faint:#7c888d;--amber:#b7761a;--amber-soft:rgba(200,128,26,.12);
--amber-line:rgba(200,128,26,.4);--teal:#1c8f7d;--hot:#a8412c}}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--fg);font:15px/1.55 var(--sans);
-webkit-font-smoothing:antialiased}
.nav{position:fixed;top:12px;left:14px;z-index:99;display:flex;gap:8px;font-family:var(--mono);
font-size:13px;font-weight:600}
.nav a{color:var(--amber);background:var(--panel);border:1px solid var(--amber-line);
border-radius:4px;padding:6px 11px;text-decoration:none}
.wrap{max-width:var(--maxw);margin:0 auto;padding:4.5rem 1.25rem 4rem}
.kicker{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;color:var(--amber);
text-transform:uppercase}
h1{font-size:1.9rem;line-height:1.2;letter-spacing:-.02em;margin:.5rem 0 .7rem;font-weight:650}
.lede{color:var(--fg-dim);max-width:60ch;margin:0 0 .9rem}
.lede b{color:var(--fg)}
.stamp{font-family:var(--mono);font-size:.72rem;color:var(--fg-faint);
border-top:1px solid var(--line);padding-top:.8rem;margin:1.6rem 0 2rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:.8rem}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:1.1rem 1.2rem;
display:flex;flex-direction:column}
.card.absent{border-color:var(--hot);border-style:dashed}
.card h2{font-family:var(--mono);font-size:.92rem;margin:0;color:var(--fg);font-weight:600}
.card .q{color:var(--fg-faint);font-size:.8rem;margin:.35rem 0 .9rem;min-height:2.4em}
.big{font-size:2rem;font-weight:650;letter-spacing:-.02em;color:var(--amber);
font-variant-numeric:tabular-nums;line-height:1}
.card.absent .big{color:var(--hot);font-size:1.1rem}
dl{margin:.9rem 0 0;font-family:var(--mono);font-size:.74rem;
display:grid;grid-template-columns:1fr auto;gap:.3rem .8rem}
dt{color:var(--fg-faint)}
dd{margin:0;color:var(--fg);text-align:right;font-variant-numeric:tabular-nums}
.src{margin-top:auto;padding-top:.9rem;border-top:1px dashed var(--line);font-family:var(--mono);
font-size:.68rem;color:var(--fg-faint);word-break:break-all}
.src a{color:var(--fg-faint);text-decoration:none;border-bottom:1px solid var(--line)}
.src a:hover{color:var(--amber);border-bottom-color:var(--amber-line)}
footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--fg-faint);
font-size:.78rem;line-height:1.7;max-width:62ch}
footer b{color:var(--fg-dim)}
"""


def build() -> str:
    cards, absent = [], 0
    for title, question, repo, rel, extract in PANELS:
        d = read(rel)
        ok = d is not None
        if ok:
            try:
                big, pairs = extract(d)
            except Exception as e:
                ok, big, pairs = False, f"unreadable: {type(e).__name__}", []
        else:
            big, pairs = "artifact not found", []
        if not ok:
            absent += 1
        rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in pairs)
        cards.append(f"""<div class="card{'' if ok else ' absent'}">
<h2>{_e(title)}</h2><p class="q">{_e(question)}</p>
<div class="big">{_e(big)}</div>
{f'<dl>{rows}</dl>' if rows else ''}
<p class="src">read from <a href="{GH}/{_e(repo)}/blob/main/{_e(rel.split('/',1)[1])}">{_e(rel.split('/',1)[1])}</a><br>
sha256 {_e(sha8(rel))} &middot; {_e(repo)}@{_e(commit(repo))}</p></div>""")

    note = ("Every panel read cleanly." if not absent else
            f"<b>{absent} panel(s) could not read their artifact</b> and say so above. "
            "A missing source is shown, never hidden and never replaced with a remembered value.")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The eval suite, as one system</title>
<meta name="description" content="Six eval tools, one page. Every number read from the artifact
its repo commits, with the file and its hash beside it.">
<link rel="icon" type="image/svg+xml" href="/favicon.svg"><style>{CSS}</style></head><body>
<div class="nav"><a href="/">&larr; Portfolio</a><span class="navsep"> &middot; </span><a href="https://agent-hub-exiz.onrender.com" target="erikhill-out">the constellation</a></div>
<div class="wrap">
<p class="kicker">One system</p>
<h1>Six tools that only mean something together</h1>
<p class="lede">Each answers a different question about whether an evaluation can be trusted, and
each one's number below is <b>read from the artifact that repo commits</b>, at build time. Nothing
here is typed by hand, because a page of copied numbers is true on the day it is written and
quietly wrong afterwards.</p>
<p class="lede">If a source cannot be read, its panel says so in red rather than falling back to a
remembered value. Absence is louder than presence, or the word verified means nothing.</p>
<div class="stamp">generated by suite/build.py &middot; each panel cites its file and that file's
sha256</div>
<div class="grid">{''.join(cards)}</div>
<footer>{note}<br><br>
These pages keep their own homes: each tool still has its own board, its own README and its own
deploy. This one exists because the tools share a spine (a run is graded, the grading is checked,
the check is audited) and nothing showed that.</footer>
</div></body></html>"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
