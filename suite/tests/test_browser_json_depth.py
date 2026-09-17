"""The depth at which the browser port refuses JSON is the verifier's, not V8's.

vac/verify.py bounds nesting at 256 levels and decides it before parsing, so
one set of bytes gets one verdict on every CPython. This file holds the browser
port to the same boundary, by the same rules, for the cases the differential
corpus cannot express.

The corpus covers the behaviour end to end (tests/conformance.py, the
json-depth-* derived cases, run by tests/test_conformance.py). What is here is
what a bundle cannot show: the counter compared against the reference counter
value for value, a depth far past any stack, the ORDER in which a byte-order
mark and a depth are decided (which the corpus records as an allowed
message-text divergence and so cannot pin), and the structural property that no
verification path parses JSON except through the loader that measures first.

Backslashes are built from chr(92) rather than written, so nothing here depends
on how many layers of escaping a reader, or a tool, applies on the way in.
"""
from __future__ import annotations

import json
import pathlib
import random
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import conformance as C  # noqa: E402

SUITE = C.SUITE
VACBROWSER = SUITE / "vacbrowser.js"
VERIFY_PY = C.VAC_ROOT / "vac" / "verify.py"
BS = chr(92)                      # one backslash
BOM = chr(0xFEFF)
LF = chr(10)
CR = chr(13)

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not on PATH")
needs_reference = pytest.mark.skipif(
    not VERIFY_PY.is_file(),
    reason="the reference implementation is not on this machine")


def _node_eval(body: str, payload=None):
    """Run `body` against the port's own exports and return its JSON result.

    The payload arrives on stdin, so no test has to spell a JS string literal
    for the characters these tests are about.
    """
    src = ("require('./refusals.gen.js');" + LF
           + "const V = require('./vacbrowser.js');" + LF
           + "const IN = JSON.parse(require('fs').readFileSync(0, 'utf8'));" + LF
           + body)
    r = subprocess.run(["node", "-e", src], input=json.dumps(payload),
                       capture_output=True, text=True, cwd=str(SUITE), timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _reference():
    sys.path.insert(0, str(C.VAC_ROOT))
    import vac.verify as ref  # noqa: PLC0415
    return ref


# ------------------------------------------------------------- the constant
@needs_node
@needs_reference
def test_the_port_carries_the_reference_limit_and_not_a_number_of_its_own():
    """A port with its own idea of the limit would agree on today's corpus and
    disagree on the first document that fell between the two numbers."""
    assert _reference().MAX_JSON_DEPTH == 256
    assert _node_eval("console.log(JSON.stringify(V.MAX_JSON_DEPTH));") == 256


# -------------------------------------------------------------- the counting
# The reference's own parametrised table, as (text, deepest nesting level).
COUNTING = [
    ("0", 0),
    ('"a [ string"', 0),
    ("[]", 1),
    ("{}", 1),
    ("[[]]", 2),
    ('{"a": [1, {"b": []}]}', 4),
    ('["[[[[", "]]"]', 1),                    # brackets inside strings
    ('["' + BS + '"[[[["]', 1),               # an escaped quote does not close
    ('["' + BS + BS + '", [[]]]', 3),         # nor does an escaped backslash
    ("[]]]][[", 2),                           # a closer with nothing open is ignored
    ('["unterminated [[[[[', 1),              # the rest of the text is the string
    ('["trailing escape ' + BS, 1),
]


@needs_node
def test_nesting_is_counted_from_the_outermost_container():
    """Level 1 is the outermost array or object. Counted lexically, so text the
    parser would reject still gets a depth, and never by recursing."""
    got = _node_eval(
        "console.log(JSON.stringify(IN.map(([t, d]) => "
        "[V.nestingExceeds(t, d), d ? V.nestingExceeds(t, d - 1) : null])));",
        COUNTING)
    for (text, deepest), (at, below) in zip(COUNTING, got):
        assert at is False, (text, deepest)
        if deepest:
            assert below is True, (text, deepest)


@needs_node
@needs_reference
def test_the_counter_returns_what_the_reference_counter_returns():
    """Value for value over a corpus of the characters that decide the count.
    A table of hand-picked cases proves the cases in the table; this compares
    the two functions."""
    alphabet = list('[]{}" ,:abc' + BS + LF + chr(13) + chr(9))
    alphabet += [BS + '"', BS + BS, BOM]
    rng = random.Random(20260917)
    texts = [''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
             for _ in range(2000)]
    texts += ["", "[", "]", '"', BS, '["' + BS, "[]]]][[", '{"a":[[[]]]}']
    limits = [0, 1, 2, 3, 5]
    exceeds = _reference()._nesting_exceeds
    want = [[exceeds(t, L) for L in limits] for t in texts]
    got = _node_eval(
        "console.log(JSON.stringify(IN.texts.map(t => "
        "IN.limits.map(L => V.nestingExceeds(t, L)))));",
        {"texts": texts, "limits": limits})
    bad = [(t, w, g) for t, w, g in zip(texts, want, got) if w != g]
    assert not bad, bad[:5]


@needs_node
def test_the_count_itself_does_not_recurse():
    """A depth far past any host's stack, so a recursive count would die. This
    is the whole reason the limit is decided before the parser sees the text."""
    assert _node_eval(
        "const t = '['.repeat(100000) + ']'.repeat(100000);"
        "console.log(JSON.stringify("
        "[V.nestingExceeds(t, 100000), V.nestingExceeds(t, 99999)]));"
    ) == [False, True]


@needs_node
def test_the_loader_refuses_past_the_limit_and_parses_at_it():
    """Both sides of the boundary, and the line a JSON Lines refusal names."""
    at = "[" * 256 + "]" * 256
    over = "[" * 257 + "]" * 257
    got = _node_eval("""
      const out = {};
      out.at = Array.isArray(V.jsonLoads(IN.at));
      for (const [k, text, opts] of [['over', IN.over, undefined],
                                     ['line', IN.lines, { lines: true }],
                                     ['cr', IN.cr, { lines: true }],
                                     ['crlf', IN.crlf, { lines: true }]]) {
        try { V.jsonLoads(text, opts); out[k] = 'no throw'; }
        catch (e) { out[k] = (e instanceof V.TooDeep) + ': ' + e.message; }
      }
      console.log(JSON.stringify(out));
    """, {"at": at, "over": over,
          "lines": "{}" + LF + over + LF,
          # read_text() turns a lone CR, and a CRLF pair, into one line feed
          # before the reference counts lines, so the line NUMBER has to come
          # out the same however the artifact was written.
          "cr": "{}" + CR + "{}" + CR + over + CR,
          "crlf": "{}" + CR + LF + "{}" + CR + LF + over + CR + LF})
    assert got == {
        "at": True,
        "over": "true: nested deeper than 256 levels",
        "line": "true: line 2 nested deeper than 256 levels",
        "cr": "true: line 3 nested deeper than 256 levels",
        "crlf": "true: line 3 nested deeper than 256 levels",
    }


# ------------------------------------------------ the mark decides first
@needs_node
def test_a_document_that_opens_with_a_byte_order_mark_is_not_measured():
    """The corpus records this pair as a message-text divergence, because
    CPython names the mark and V8 does not, so the corpus alone cannot tell a
    port that measured the marked text from one that did not: both still refuse
    under the same name. The browser's own message is pinned here instead. A
    port that stripped the mark to measure it would print the depth."""
    deep = "[" * 300 + "]" * 300          # 300 levels, well past the limit
    got = _node_eval("""
      const out = {};
      for (const [k, text, opts] of [['text', IN.text, undefined],
                                     ['lines', IN.lines, { lines: true }],
                                     ['line', IN.line, { lines: true }]]) {
        try { V.jsonLoads(text, opts); out[k] = 'no throw'; }
        catch (e) { out[k] = e.message; }
      }
      console.log(JSON.stringify(out));
    """, {"text": BOM + deep,
          # the mark opens the whole artifact, so NO line is measured and the
          # deep third line never gets to take the reason
          "lines": BOM + "{}" + LF + "{}" + LF + deep + LF,
          # the mark opens line 3 only, so that one line goes unmeasured
          "line": "{}" + LF + BOM + deep + LF})
    # the parser's own offset-0 reason, at 300 levels, and not the depth
    assert got["text"] == "Expecting value: line 1 column 1 (char 0)"
    assert got["lines"] == "Expecting value: line 1 column 1 (char 0)"
    assert got["line"] == "Expecting value: line 1 column 1 (char 0)"
    # and the same text without the mark IS refused for its depth, so the
    # assertions above cannot pass because the text was never deep enough
    assert _node_eval(
        "try { V.jsonLoads(IN.deep); console.log('\"no throw\"'); }"
        "catch (e) { console.log(JSON.stringify(e.message)); }",
        {"deep": deep}) == "nested deeper than 256 levels"


# -------------------------------------------------------------- structural
# The functions that may hold a jsonParse call, and why. jsonLoads is the one
# loader on a verification path: it measures every line before it parses any.
# The other two are the page's byte-precise mutation tooling, which needs the
# spans the loader does not return and never decides a verdict.
MAY_PARSE = {"jsonLoads", "spliceValue", "valueText"}


def _enclosing_functions(source: str, call: str) -> set:
    """Every function in the module body that contains `call`.

    A function's own declaration line is where it is defined, not a place it is
    called, so the head line opens a function and is never itself a hit.
    """
    current, found = None, set()
    for line in source.splitlines():
        head = next((h for h in ("  function ", "  async function ")
                     if line.startswith(h)), None)
        if head:
            current = line.split("function ", 1)[1].split("(", 1)[0]
            continue
        if call in line and not line.lstrip().startswith("//"):
            found.add(current)
    return found


def test_the_parser_is_reached_only_through_the_loader_that_measures_first():
    """Structural, so a new parse added anywhere else in the port is red here
    rather than on whichever document happens to be deep enough to notice."""
    stray = _enclosing_functions(VACBROWSER.read_text(), "jsonParse(") - MAY_PARSE
    stray.discard(None)                    # the export list at the end of the file
    assert not stray, f"jsonParse called outside the loader, in {sorted(stray)}"


def test_the_detector_sees_a_parse_it_is_meant_to_see():
    """Liveness for the structural test above: a detector that found nothing
    would pass it while the port parsed JSON anywhere it liked."""
    fake = ("  function innocent() {" + LF
            + "    return jsonParse(text).value;" + LF
            + "  }" + LF)
    assert _enclosing_functions(fake, "jsonParse(") == {"innocent"}
    # and the parser's own declaration is not counted as a call to itself
    assert _enclosing_functions("  function jsonParse(text) {" + LF,
                                "jsonParse(") == set()
    assert _enclosing_functions(VACBROWSER.read_text(), "jsonParse(") & MAY_PARSE


# ------------------------------------------------- what counts as a blank row
# Which rows the reference parses is `if row.strip()` (vac/verify.py:169), and
# trim() is not str.strip(): ECMAScript strips U+FEFF and Python does not. A row
# that is only a byte-order mark is the smallest input where the port drops a
# row the reference parses, and so passes an artifact the reference refuses. The
# comparison below is of OUTCOMES, refused or a row count, because the two
# implementations word a parse failure differently and always have.
BLANK_ROW_CASES = [
    ('{"a": 1}' + LF + BOM, "a row that is only a byte order mark"),
    ('{"a": 1}' + LF + BOM + LF + '{"b": 2}', "a mark row between two rows"),
    ('{"a": 1}' + LF + "   ", "a row of spaces"),
    ('{"a": 1}' + LF + chr(9), "a row of one tab"),
    ('{"a": 1}' + LF + chr(0xA0), "a row of one no break space"),
    ('{"a": 1}' + LF + chr(0x3000), "a row of one ideographic space"),
    ('{"a": 1}' + LF + chr(0x200B), "a row of one zero width space"),
    ('{"a": 1}' + LF + LF + '{"b": 2}', "an empty row"),
]


@needs_node
@needs_reference
@pytest.mark.parametrize("text,what", BLANK_ROW_CASES,
                         ids=[w.replace(" ", "_") for _, w in BLANK_ROW_CASES])
def test_the_port_drops_the_rows_the_reference_drops_and_no_others(text, what):
    """A dropped row is not a smaller answer, it is a different artifact: the
    reference refuses what it cannot parse, so a row dropped here is a refusal
    that never happens and a bundle that passes in the browser alone."""
    ref = _reference()
    try:
        expected = ["rows", len(ref._json_loads(text, lines=True))]
    except Exception:                      # noqa: BLE001 - the name is the point
        expected = ["refused"]
    observed = _node_eval(
        "let out;" + LF
        + "try { out = ['rows', V.jsonLoads(IN, { lines: true }).length]; }" + LF
        + "catch (e) { out = ['refused']; }" + LF
        + "console.log(JSON.stringify(out));", text)
    assert observed == expected, what


def test_nothing_written_here_carries_a_long_dash():
    """The standing rule, extended to the files this change touches."""
    em, en, escaped = chr(0x2014), chr(0x2013), BS + "u2014"
    for name in ("vacbrowser.js", "tests/conformance.py",
                 "tests/test_browser_json_depth.py"):
        text = (SUITE / name).read_text().replace(escaped, "")
        assert em not in text, f"{name} carries an em dash"
        assert en not in text, f"{name} carries an en dash"
