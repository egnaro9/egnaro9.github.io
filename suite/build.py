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

THE PIN, NOT THE CHECKOUT. Every source is declared in sources.json with an immutable issuer
commit, the sha256 its bytes must have, and a commit-pinned public URL. A sibling checkout is
only byte transport: bytes that do not hash to the pin are refused, and the panel renders STALE
naming expected and found rather than keeping the value it printed yesterday. Nothing here reads
a local HEAD or links a mutable branch, because both go false silently on someone else's push.

    python3 build.py            # writes index.html next to this file
"""
from __future__ import annotations

import hashlib
import html
import json
import pathlib
import re
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
OUT = HERE / "index.html"
MANIFEST = HERE / "sources.json"
RAW = "https://raw.githubusercontent.com/"


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


class Resolved:
    """One source, resolved to exactly one of three states. There is no fourth."""

    def __init__(self, state, data=None, found=None, detail=""):
        self.state, self.data, self.found, self.detail = state, data, found, detail


def _raw_url(entry: dict) -> str:
    """The pinned blob url rewritten to the bytes endpoint. Same commit, same path."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([0-9a-f]{7,40})/(.+)$",
                 entry["public_url"])
    if not m:
        return ""
    owner, repo, commit, path = m.groups()
    return f"{RAW}{owner}/{repo}/{commit}/{path}"


def _fetch(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except Exception:
        return None


def resolve(entry: dict) -> Resolved:
    """Obtain the pinned bytes, from anywhere, and prove they are the pinned bytes.

    The local checkout is tried first because it is fast and works offline, but it carries no
    authority: it is accepted only when it hashes to the pin. Otherwise the commit-pinned URL is
    fetched, which is the copy a reader would check. If neither yields the pinned bytes and some
    bytes did arrive, that is STALE and the panel loses its number. Nothing arriving is ABSENT."""
    want = entry["sha256"]
    attempts, saw = [], None

    local = HOME / entry["artifact"]
    try:
        attempts.append(("local checkout", local.read_bytes()))
    except Exception:
        pass

    url = _raw_url(entry)
    if not url:
        return Resolved("ABSENT", detail=f"public_url is not pinned to a commit: {entry['public_url']}")
    if not attempts or hashlib.sha256(attempts[0][1]).hexdigest() != want:
        got = _fetch(url)
        if got is not None:
            attempts.append(("pinned url", got))

    for origin, raw in attempts:
        got = hashlib.sha256(raw).hexdigest()
        if got == want:
            try:
                return Resolved("VALID", data=json.loads(raw), found=got)
            except Exception as e:
                return Resolved("ABSENT", detail=f"pinned bytes are not JSON: {type(e).__name__}")
        saw = (origin, got)

    if saw:
        return Resolved("STALE", found=saw[1],
                        detail=f"{saw[0]} has sha256 {saw[1][:8]}, pin declares {want[:8]}")
    return Resolved("ABSENT", detail=f"no bytes from {local} or {url}")


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


# A derivation is a named, versioned reader for ONE artifact shape. sources.json names the
# derivation per panel, so a later refactor cannot silently point a reader at a different
# artifact: an unknown name is a hard build failure, not a quietly empty panel.
DERIVATIONS = {
    "evalmut_dogfood@1": _evalmut,
    "fleet_board@1": _fleet,
    "drift_metrics@1": _drift,
    "certlab_bundle@1": _certlab,
    "crashkit_bundle@1": _crashkit,
    "vac_registry@1": _vac,
}


def load_manifest() -> dict:
    m = json.loads(MANIFEST.read_text())
    for e in m["sources"]:
        if e["derivation"] not in DERIVATIONS:
            raise SystemExit(f"sources.json: unknown derivation {e['derivation']!r} "
                             f"for panel {e['panel']!r}. Known: {sorted(DERIVATIONS)}")
    return m


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
.card.stale{border-color:var(--hot);border-style:dashed}
.card.stale .big,.card.absent .big{color:var(--hot);font-size:1.1rem}
.state{font-family:var(--mono);font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;
color:var(--hot);border:1px solid var(--hot);border-radius:2px;padding:1px 5px;margin-left:.5rem}
.why{font-family:var(--mono);font-size:.68rem;color:var(--hot);margin:.6rem 0 0;word-break:break-all}
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
    man = load_manifest()
    cards, bad = [], []
    for e in man["sources"]:
        r = resolve(e)
        big, pairs, why = "", [], ""
        if r.state == "VALID":
            try:
                big, pairs = DERIVATIONS[e["derivation"]](r.data)
            except Exception as ex:
                r = Resolved("ABSENT", detail=f"{e['derivation']} could not read the pinned "
                                              f"artifact: {type(ex).__name__}")
        if r.state == "STALE":
            big, why = "source moved off its pin", r.detail
        elif r.state == "ABSENT":
            big, why = "artifact not obtainable", r.detail
        if r.state != "VALID":
            bad.append((e["panel"], r.state))

        cls = "" if r.state == "VALID" else f" {r.state.lower()}"
        badge = "" if r.state == "VALID" else f'<span class="state">{r.state}</span>'
        rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in pairs)
        short = e["artifact"].split("/", 1)[1]
        cards.append(f"""<div class="card{cls}">
<h2>{_e(e['panel'])}{badge}</h2><p class="q">{_e(e['question'])}</p>
<div class="big">{_e(big)}</div>
{f'<dl>{rows}</dl>' if rows else ''}
{f'<p class="why">{_e(why)}</p>' if why else ''}
<p class="src">{_e(e['label'])}<br>
pinned to <a href="{_e(e['public_url'])}">{_e(short)}</a><br>
sha256 {_e(e['sha256'][:8])} &middot; {_e(e['artifact'].split('/')[0])}@{_e(e['issuer_commit'][:7])}
&middot; {_e(e['derivation'])}</p></div>""")

    if not bad:
        note = ("Every panel matched its pin. Each number below was recomputed from bytes that "
                "hash to the sha256 printed beside it.")
    else:
        listed = ", ".join(f"{n} ({st})" for n, st in bad)
        note = (f"<b>{len(bad)} panel(s) did not match their pin</b> and say so above: {listed}. "
                "A source that moved off its pin loses its number here rather than keeping the "
                "one it printed before.")

    gen = hashlib.sha256(pathlib.Path(__file__).resolve().read_bytes()).hexdigest()[:8]
    mfst = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:8]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The eval suite, as one system</title>
<meta name="description" content="Six eval tools, one page. Every number recomputed from bytes
pinned by sha256 to a named issuer commit.">
<link rel="icon" type="image/svg+xml" href="/favicon.svg"><style>{CSS}</style></head><body>
<div class="nav"><a href="/">&larr; Portfolio</a><span class="navsep"> &middot; </span><a href="https://agent-hub-exiz.onrender.com" target="erikhill-out">the constellation</a></div>
<div class="wrap">
<p class="kicker">One system</p>
<h1>Six tools that only mean something together</h1>
<p class="lede">Each answers a different question about whether an evaluation can be trusted, and
each one's number below is <b>recomputed from bytes pinned by sha256</b> to the issuer commit
named on that panel. Nothing here is typed by hand, because a page of copied numbers is true on
the day it is written and quietly wrong afterwards.</p>
<p class="lede">If a source stops matching its pin it renders STALE and loses its number; if it
cannot be obtained at all it renders ABSENT. Neither one keeps the value it printed yesterday,
or the word verified means nothing.</p>
<div class="stamp">generated by suite/build.py (build {gen}, manifest {mfst}) &middot; sources
pinned as of {_e(man['pinned_as_of'])}, each to the issuer commit on its panel and not to
current main &middot; fetch any link and hash it: it must match the sha256 beside it</div>
<div class="grid">{''.join(cards)}</div>
<footer>{note}<br><br>
These pages keep their own homes: each tool still has its own board, its own README and its own
deploy. This one exists because the tools share a spine (a run is graded, the grading is checked,
the check is audited) and nothing showed that.</footer>
</div></body></html>"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
