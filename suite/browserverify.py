"""Embed a real VAC bundle in the page, with a verifier that actually runs.

WHY THIS EXISTS. The page advertised three modes and one of them did not exist:
"Browser tamper demo alters a local copy to show one named rejection path." The
page contained zero crypto calls and zero rejection paths. A claim about a
verifier, made by a page whose whole thesis is that unsupported claims must fail
mechanically, is the worst possible place to carry an unsupported claim. This
module makes the sentence true instead of deleting it.

WHAT IT EMBEDS. The committed bundle at vac-protocol/examples/outsider, byte for
byte, base64 encoded, with each file's sha256 and size taken from the bytes and
the path-scoped commit that produced them. Never a hand-made sample: a demo
bundle would prove the demo works, which nobody was asking.

WHAT IT REFUSES TO DO. If the bundle is unreadable there is no panel and no
mode line claiming one. The page says the demo is not in this build and names
the path, exactly as an absent step does. A page that keeps advertising a
feature whose source it could not read is the failure this whole stack refuses.
"""
from __future__ import annotations

import base64
import html
import json
import pathlib
import re

import evidence
import refusals

HOME = pathlib.Path.home()
BUNDLE_REPO = "vac-protocol"
BUNDLE_IN_REPO = "examples/outsider"
BUNDLE = HOME / BUNDLE_REPO / BUNDLE_IN_REPO
SUITE = pathlib.Path(__file__).resolve().parent
SCRIPTS = ("refusals.gen.js", "vacbrowser.js", "bv_ui.js")


class Unavailable(RuntimeError):
    """The panel cannot be built honestly. Say so; never render a fake one."""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def embed_bundle() -> dict:
    """The committed bundle, as bytes the page can hand to crypto.subtle."""
    if not BUNDLE.is_dir():
        raise Unavailable(f"{BUNDLE_REPO}/{BUNDLE_IN_REPO} is not a directory")
    files = sorted(p for p in BUNDLE.rglob("*") if p.is_file())
    if not files:
        raise Unavailable(f"{BUNDLE_REPO}/{BUNDLE_IN_REPO} holds no files")
    if not (BUNDLE / "vac.json").is_file():
        raise Unavailable(f"{BUNDLE_REPO}/{BUNDLE_IN_REPO} has no vac.json")
    try:
        commit = evidence._commit(HOME / BUNDLE_REPO, BUNDLE_IN_REPO)
    except evidence.ProvenanceError as e:
        raise Unavailable(str(e)) from e
    out = []
    for p in files:
        raw = p.read_bytes()
        digest, size = evidence._sha256(p)
        out.append({"path": p.relative_to(BUNDLE).as_posix(), "sha256": digest,
                    "size": size, "b64": base64.b64encode(raw).decode("ascii")})
    return {"root": BUNDLE.name, "source": f"{BUNDLE_REPO}/{BUNDLE_IN_REPO}",
            "commit": commit, "bytes": sum(f["size"] for f in out), "files": out}


def scripts() -> str:
    """The three scripts, inlined in load order. Generated table first."""
    parts = []
    for name in SCRIPTS:
        p = SUITE / name
        if not p.is_file():
            raise Unavailable(f"suite/{name} is missing")
        text = p.read_text(encoding="utf-8")
        if "</script" in text.lower():
            raise Unavailable(f"suite/{name} would close its own script tag")
        parts.append(f'<script>\n{text}\n</script>')
    return "\n".join(parts)


def cli_scope_lines(vocab: dict) -> list[str]:
    """The reference verifier's own words for what a structural run proves.

    Read out of verify.py's _report rather than paraphrased, so the browser
    cannot drift into claiming a wider scope than the command line claims.
    """
    # An earlier version dropped one _report line and justified it by saying the line
    # "belongs to the unreadable-replay error path, which this page never reaches". The page
    # reaches it: break-json and no-manifest are two of the sixteen buttons, and both are
    # exactly that path. So the one line describing what the CLI does in a case this panel
    # produces was the line being hidden. Keep every line. The long dash it punctuates with is
    # reproduced by codepoint, never typed, because nothing written here may contain one.
    lines = list(vocab["report_lines"])
    if not any(l.strip().startswith("proved offline:") for l in lines):
        raise Unavailable("verify.py's _report no longer states what it proved offline")
    if not any("semantic replay:" in l for l in lines):
        raise Unavailable("verify.py's _report no longer states that replay is not run")
    return lines


def port_coverage(vocab: dict) -> tuple[list[str], list[str]]:
    """Which refusals the hand-written verifier can actually emit, measured.

    Not asserted in prose: the port addresses the vocabulary as R.IDENTIFIER, so
    the identifiers it references ARE the refusals it can produce. Reading them
    back out of the source is the only version of this sentence that cannot rot.
    """
    js = (SUITE / "vacbrowser.js").read_text(encoding="utf-8")
    used = set(re.findall(r"\bR\.([A-Z0-9_]+)\b", js))
    covered = [r["name"] for r in vocab["refusals"] if r["const"] in used]
    missing = [r["name"] for r in vocab["refusals"] if r["const"] not in used]
    return covered, missing


CSS = """
.bv{border:1px solid var(--amber-line);border-radius:5px;margin:1.6rem 0 .7rem;
background:var(--panel)}
.bv .bvbody{padding:0 1.2rem 1.1rem}
.bv .big.ok{color:var(--ok)}.bv .big.bad{color:var(--bad)}.bv .big.warn{color:var(--amber)}
.bv .ctl{margin:.2rem 0 .8rem;gap:.4rem}
.bv .ctl button{font-size:.72rem;padding:.35rem .8rem}
.bv .ctl button.sel{outline:2px solid var(--amber);outline-offset:2px}
.bv .term{max-height:22rem;overflow-y:auto}
.bvblurb{color:var(--fg-dim);font-size:.82rem;margin:.2rem 0 .4rem;min-height:1.2em;
max-width:62ch}
.bvlabel{font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;color:var(--amber);
margin:.7rem 0 .3rem;text-transform:uppercase}
.bvlist{margin:0;padding-left:1.1rem;font-size:.78rem;color:var(--fg-dim)}
.bvlist li{margin:0 0 .25rem}
.bvlist.no li{color:var(--fg-faint)}
.bvquote{font-family:var(--mono);font-size:.7rem;color:var(--fg-faint);white-space:pre-wrap;
border-left:2px solid var(--line);padding-left:.7rem;margin:.8rem 0 0}
.bvvocab{font-family:var(--mono);font-size:.68rem;color:var(--fg-faint);margin:.6rem 0 0;
word-break:break-word}
"""


def panel() -> dict:
    """{'ok', 'mode', 'html', 'css'} for the build. Never raises upward."""
    try:
        vocab, provenance = refusals.load()
        bundle = embed_bundle()
        cli_lines = cli_scope_lines(vocab)
        js = scripts()
    except (Unavailable, refusals.ExtractionError) as e:
        return {
            "ok": False,
            "mode": ("<b>Browser tamper demo</b> is NOT in this build: "
                     f"{_e(e)}. Nothing on this page verifies anything in your browser."),
            "html": ('<p class="note" style="color:var(--bad)"><b>The in-browser verifier '
                     f'could not be built:</b> {_e(e)}. It is left out rather than '
                     'shipped as a mock.</p>'),
            "css": "",
        }

    covered, missing = port_coverage(vocab)
    archive = {r["name"] for r in vocab["refusals"] if r["archive_only"]}
    unexplained = [n for n in missing if n not in archive]
    if missing and not unexplained:
        gap = (f"It does not emit {_e(', '.join(missing))}, which verify.py reaches only "
               "through the archive path: this page embeds the bundle already unpacked, "
               "so that path does not exist here.")
    elif unexplained:
        gap = (f"It does NOT emit {_e(', '.join(missing))}. A bundle that would earn one of "
               "those is not fully checked here, and the run is reported INCOMPLETE rather "
               "than passed.")
    else:
        gap = "It emits every refusal the reference verifier can emit."
    d = vocab["derived_from"]
    files = ", ".join(f'{f["path"]} ({f["size"]} B)' for f in bundle["files"])

    body = f"""<div class="bv" id="bv">
<div class="head"><span class="num">5b</span><span class="verb">BREAK IT</span>
<span class="tool">this page</span><span class="big" id="bv-verdict">not run yet</span></div>
<div class="bvbody">
<p class="q">Does the verifier still refuse when <em>you</em> are the one tampering?</p>
<p class="note">Step 5 is a transcript of a verifier that ran on the build machine. You have
to take that on trust. This runs a structural verifier <b>in your browser, right now</b>,
over the bundle embedded in this page: {_e(files)}, from
<code>{_e(bundle["source"])}</code> at commit <code>{_e(bundle["commit"])}</code>. The sha256
comparisons are real SHA-256 through <code>crypto.subtle</code>. The first button re-verifies the
bundle unaltered; each of the sixteen after it alters an <b>in-memory copy</b> and re-verifies
that. The served bytes are read once and never written.</p>
<p class="note">The refusal names it prints are not typed into the JavaScript. They are
extracted from <code>vac/verify.py</code> at build time into one generated table that both
sides read, so a refusal the reference verifier renames cannot keep appearing here.</p>
<div class="ctl" id="bv-ctl"></div>
<p class="bvblurb" id="bv-blurb"></p>
<div class="term" id="bv-out"></div>
<details class="ev" open><summary>What this run checked, and what it did not</summary>
<div id="bv-scope"></div>
<p class="bvlabel">the reference verifier's own words for a structural run</p>
<p class="bvquote">{_e(chr(10).join(cli_lines))}</p>
<p class="bvvocab">That last line ends where the terminal above continues it: when the manifest
reads, the replay block echoed here is the bundle's own. When it does not read, there is no replay
block to echo and this panel shows none, while the command line prints a line naming that gap. The
break-json and no-manifest buttons are that case.</p>
</details>
<p class="bvvocab"><b>Vocabulary:</b> {_e(provenance)}. verify.py emits
{len(vocab["refusals"])} named refusals. This page's verifier references {len(covered)} of them
through the generated table, which is how it can emit them at all:
{_e(", ".join(covered))}. {gap}</p>
<p class="src">bundle sha256: {_e("; ".join(f'{f["path"]} {f["sha256"][:16]}'
                                          for f in bundle["files"]))}
&middot; verify.py sha256 {_e(d["sha256"][:16])} &middot; the panel is generated by
suite/browserverify.py and runs suite/vacbrowser.js</p>
</div></div>
<script type="application/json" id="bv-bundle">{json.dumps(bundle)}</script>
{js}"""

    return {
        "ok": True,
        "mode": ("<b>Browser tamper demo</b> alters an in-memory copy of the embedded bundle "
                 "and prints the named refusals its own verifier returns. It never writes to "
                 "the served bytes and it never replays anything."),
        "html": body,
        "css": CSS,
    }


if __name__ == "__main__":
    p = panel()
    print("ok:", p["ok"])
    print("mode:", p["mode"])
    print("html bytes:", len(p["html"]))
