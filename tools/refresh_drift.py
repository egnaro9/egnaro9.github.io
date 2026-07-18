"""Replace the drift paragraph in index.html with the one model-drift generated.

The paragraph describing the drift board used to be written by hand, and twice
it went false — not by carelessness, but because a weekly cron kept moving the
numbers underneath frozen prose. It is generated now, next to the data, by
model-drift's `narrative.py`, where every sentence is a predicate over the
board's own numbers. This script only carries that text across and splices it
between the markers.

It refuses more readily than it writes. An empty paragraph, a missing marker, a
suspiciously short body, or unreachable JSON all exit non-zero and change
nothing — a stale-but-true paragraph is a far better failure than a blanked or
mangled one on the page a hiring manager is reading.

    python tools/refresh_drift.py            # rewrite index.html in place
    python tools/refresh_drift.py --check    # exit 1 if it *would* change
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCE = ("https://raw.githubusercontent.com/egnaro9/model-drift/main/"
          "dashboard/narrative.json")
START = "<!-- drift:start"
END = "<!-- drift:end -->"
USER_AGENT = "egnaro9.github.io/refresh-drift (+https://egnaro9.github.io)"
MIN_CHARS = 120          # a real paragraph; below this something went wrong


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def splice(html: str, paragraph: str) -> str:
    """Replace whatever sits between the markers, keeping the markers."""
    start = html.find(START)
    if start == -1:
        raise SystemExit(f"marker {START!r} not found in index.html")
    open_end = html.find("-->", start)
    end = html.find(END, open_end)
    if end == -1:
        raise SystemExit(f"marker {END!r} not found after {START!r}")
    indent = " " * (start - html.rfind("\n", 0, start) - 1)
    return html[:open_end + 3] + f"\n{indent}{paragraph}\n{indent}" + html[end:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--index", default=str(Path(__file__).resolve().parent.parent / "index.html"))
    ap.add_argument("--check", action="store_true",
                    help="report whether the page is behind; write nothing")
    ap.add_argument("--print-current", action="store_true",
                    help="print the page's current paragraph as plain text and exit")
    args = ap.parse_args(argv)

    if args.print_current:
        # Lives here rather than inline in the workflow: a python -c block
        # indented inside YAML is an IndentationError waiting to happen, and
        # this way the thing the PR body shows is covered by the same tests.
        html = Path(args.index).read_text(encoding="utf-8")
        start = html.find(START)
        end = html.find(END, start)
        if start == -1 or end == -1:
            print("markers not found", file=sys.stderr)
            return 1
        body = html[html.find("-->", start) + 3:end]
        print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip())
        return 0

    try:
        data = fetch(args.source)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"could not read {args.source}: {e}", file=sys.stderr)
        return 1

    paragraph = (data.get("html") or "").strip()
    if len(paragraph) < MIN_CHARS:
        print(f"generated paragraph is {len(paragraph)} chars — refusing to "
              f"splice something that short", file=sys.stderr)
        return 1
    # The paragraph is inline content — it opens with a word, not a tag — so
    # "starts with '<'" is the wrong test. What matters is that nothing
    # executable rides in with it.
    if re.search(r"<\s*script|javascript:|\son\w+\s*=|<\s*iframe", paragraph, re.I):
        print("generated paragraph contains executable markup — refusing",
              file=sys.stderr)
        return 1
    if "drift:start" in paragraph or "drift:end" in paragraph:
        print("generated paragraph contains the markers — refusing to nest them",
              file=sys.stderr)
        return 1

    index = Path(args.index)
    html = index.read_text(encoding="utf-8")
    updated = splice(html, f"<p>{paragraph}</p>" if not paragraph.startswith("<p")
                     else paragraph)

    if updated == html:
        print("index.html already matches the board")
        return 0
    if args.check:
        print("index.html is behind the board — run without --check to update")
        return 1
    index.write_text(updated, encoding="utf-8")
    print(f"updated index.html from the run of {data.get('updated', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
