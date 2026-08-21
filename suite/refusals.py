"""Extract the verifier's REFUSAL VOCABULARY from vac/verify.py, once, for both sides.

THE DEFECT THIS FILE EXISTS TO REFUSE. A browser verifier that hand-types
"sha256-mismatch" into a .js file is not sharing a vocabulary with the reference
implementation, it is imitating one. The two drift silently: verify.py renames a
refusal, the page keeps printing the old name, and the page still looks green
because nothing compares them. So the names are never typed by hand on the
browser side. They are read out of verify.py's own emission sites by parsing it,
written to ONE generated artifact (refusals.json), and mirrored into ONE
generated JS constant table (refusals.gen.js) that the hand-written verifier
addresses by IDENTIFIER. A refusal that verify.py stops emitting removes the key,
and the generated table's guard throws on first use instead of printing a name
the reference implementation no longer knows.

Extraction is AST-driven, not regex over source text: a refusal is the leading
dashed token of a string literal that reaches a failure list (`.append(...)`), a
wholesale-refusal `return [...]`, or the `FAIL ...` line main() prints for an
unsafe archive. Anything else that merely looks like a dashed name (profile ids
in PROFILES, op names in _ROW_OPS) never reaches one of those sites and so is
never mistaken for a refusal.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re

VERIFY = pathlib.Path.home() / "vac-protocol" / "vac" / "verify.py"

# Spec constants the browser port must agree with byte for byte. Typed here as
# NAMES to look up, never as VALUES to copy: if verify.py drops one, extraction
# raises and the build stops instead of shipping a stale table.
_WANT_CONSTS = ("VAC_VERSION", "PROFILES", "_ROW_OPS", "_CRASHKIT_WEIGHTS",
                "_CRASHKIT_ACC_ALIASES", "_EVALMUT_HOLES", "_TODO_PREFIX",
                "_CHECK_REFS", "_CHECK_OPT_REFS")
# Regexes the port must apply to the same artifacts. Each is plain enough to be
# the same pattern in JS; a construct that is not would be caught by the
# fixture comparison, which runs both implementations over the same bytes.
_WANT_PATTERNS = ("_CERTLAB_RENDER", "_EVALMUT_RENDER", "_NUMERIC_STR")
HERE = pathlib.Path(__file__).resolve().parent
JSON_OUT = HERE / "refusals.json"
JS_OUT = HERE / "refusals.gen.js"

# a refusal name is lowercase dashed, at least two segments, and is followed by
# ": " (the reason) or ends the string (a bare name such as empty-limitations)
_NAME = re.compile(r"^([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?::|$)")


class ExtractionError(RuntimeError):
    """The vocabulary could not be derived. Never fall back to a typed list."""


def _leading_name(node: ast.AST) -> str | None:
    """The refusal name a failure-string literal starts with, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        head = node.value
    elif isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return None
        head = first.value
    else:
        return None
    m = _NAME.match(head)
    return m.group(1) if m else None


def _emission_sites(tree: ast.AST):
    """Yield (name, lineno, kind) for every literal that reaches a refusal."""
    for node in ast.walk(tree):
        # f.append("name: reason") / failures.append(...)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and len(node.args) == 1):
            name = _leading_name(node.args[0])
            if name:
                yield name, node.lineno, "append"
        # return ["name: reason"]: a wholesale refusal, nothing else runs
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                name = _leading_name(elt)
                if name:
                    yield name, node.lineno, "return"
        # print(f"FAIL name: reason"), the archive path, outside verify_bundle
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "print" and len(node.args) == 1):
            arg = node.args[0]
            head = None
            if isinstance(arg, ast.JoinedStr) and arg.values:
                first = arg.values[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    head = first.value
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                head = arg.value
            if head and head.startswith("FAIL "):
                m = _NAME.match(head[5:])
                if m:
                    yield m.group(1), node.lineno, "print"


def _constants(tree: ast.AST) -> dict:
    """Module-level spec constants, literal-evaluated. Missing one is fatal."""
    out: dict = {}
    pats: dict = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id in _WANT_CONSTS:
            try:
                out[tgt.id] = ast.literal_eval(node.value)
            except ValueError as e:
                raise ExtractionError(f"{tgt.id} is not a literal: {e}") from e
        elif tgt.id in _WANT_PATTERNS:
            v = node.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "compile" and v.args):
                try:
                    pats[tgt.id] = ast.literal_eval(v.args[0])
                except ValueError as e:
                    raise ExtractionError(
                        f"{tgt.id} pattern is not a literal: {e}") from e
    missing = [n for n in _WANT_CONSTS if n not in out]
    missing += [n for n in _WANT_PATTERNS if n not in pats]
    if missing:
        raise ExtractionError(
            "verify.py no longer defines " + ", ".join(missing)
            + ". The browser port cannot agree with a constant it cannot read.")
    out["_PATTERNS"] = pats
    return out


def _report_lines(tree: ast.AST) -> list[str]:
    """The fixed lines _report() prints: the CLI's own words for its scope."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_report":
            out = []
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "print" and len(sub.args) == 1
                        and isinstance(sub.args[0], ast.Constant)
                        and isinstance(sub.args[0].value, str)):
                    out.append(sub.args[0].value)
            if not out:
                raise ExtractionError("_report prints no fixed lines")
            return out
    raise ExtractionError("verify.py has no _report function")


def extract(verify_py: pathlib.Path = VERIFY) -> dict:
    """The vocabulary, with the bytes it was derived from named."""
    try:
        text = verify_py.read_text(encoding="utf-8")
    except OSError as e:
        raise ExtractionError(f"cannot read {verify_py}: {e}") from e
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise ExtractionError(f"cannot parse {verify_py}: {e}") from e

    sites: dict[str, list[int]] = {}
    kinds: dict[str, set] = {}
    for name, lineno, kind in _emission_sites(tree):
        sites.setdefault(name, []).append(lineno)
        kinds.setdefault(name, set()).add(kind)
    if not sites:
        raise ExtractionError(f"no refusal names found in {verify_py}")

    names = sorted(sites)
    consts = _constants(tree)
    return {
        "derived_from": {
            "path": "vac/verify.py",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            # splitlines(), not count("\n") + 1. The latter counts the empty string after a trailing
            # newline, so it published 1624 for a 1623-line file, one line off from wc -l,
            # next to an exact sha256 that made it easy to trust.
            "lines": len(text.splitlines()),
        },
        "refusals": [
            {
                "name": n,
                "const": n.upper().replace("-", "_"),
                "sites": len(sites[n]),
                "first_line": min(sites[n]),
                # a refusal reached only by print() is main()'s archive path,
                # which never runs over an already-unpacked bundle
                "archive_only": kinds[n] == {"print"},
            }
            for n in names
        ],
        "constants": consts,
        "report_lines": _report_lines(tree),
    }


def as_js(vocab: dict) -> str:
    """The generated constant table. The ONLY .js file allowed to spell a name."""
    d = vocab["derived_from"]
    c = vocab["constants"]
    spec = {
        "VAC_VERSION": c["VAC_VERSION"],
        "PROFILES": list(c["PROFILES"]),
        "ROW_OPS": list(c["_ROW_OPS"]),
        "CRASHKIT_WEIGHTS": c["_CRASHKIT_WEIGHTS"],
        "CRASHKIT_ACC_ALIASES": list(c["_CRASHKIT_ACC_ALIASES"]),
        "EVALMUT_HOLES": [list(h) for h in c["_EVALMUT_HOLES"]],
        "TODO_PREFIX": c["_TODO_PREFIX"],
        "CHECK_REFS": {k: list(v) for k, v in c["_CHECK_REFS"].items()},
        "CHECK_OPT_REFS": {k: list(v) for k, v in c["_CHECK_OPT_REFS"].items()},
        "PATTERNS": c["_PATTERNS"],
        "REPORT_LINES": vocab["report_lines"],
    }
    rows = "".join(
        f'  {r["const"]}: {json.dumps(r["name"])},\n' for r in vocab["refusals"])
    return f"""// GENERATED by suite/refusals.py from {d["path"]} (sha256 {d["sha256"][:16]}).
// Do not edit. Do not copy a name out of here into hand-written JS: address the
// table by identifier so a renamed refusal throws instead of printing a stale
// name. Regenerate with: python3 refusals.py
globalThis.VAC_REFUSALS = (function () {{
  const NAMES = Object.freeze({{
{rows}  }});
  const SOURCE = Object.freeze({json.dumps(d, sort_keys=True)});
  // NOT key-sorted: CRASHKIT_WEIGHTS is joined in insertion order by one
  // refusal message, so sorting it here would change the reference text.
  globalThis.VAC_SPEC = Object.freeze({json.dumps(spec)});
  const R = new Proxy(NAMES, {{
    get(t, k) {{
      if (k === "__source") return SOURCE;
      if (k === "__names") return Object.freeze(Object.values(NAMES).slice());
      if (typeof k === "symbol" || k in t) return t[k];
      throw new Error(
        "no such refusal in the vocabulary derived from " + SOURCE.path + ": " +
        String(k) + ". The reference verifier does not emit it.");
    }},
  }});
  return R;
}})();
if (typeof module !== "undefined" && module.exports) module.exports = globalThis.VAC_REFUSALS;
"""


def generate(verify_py: pathlib.Path = VERIFY) -> dict:
    """Re-derive and rewrite both generated artifacts. Returns the vocabulary."""
    vocab = extract(verify_py)
    JSON_OUT.write_text(json.dumps(vocab, indent=1) + "\n", encoding="utf-8")
    JS_OUT.write_text(as_js(vocab), encoding="utf-8")
    return vocab


def load(verify_py: pathlib.Path = VERIFY) -> tuple[dict, str]:
    """(vocabulary, provenance sentence) for the build.

    verify.py present: re-derive now, rewrite the generated pair if it moved, and
    say so. verify.py absent: use the committed snapshot and say THAT, naming the
    verify.py bytes it was derived from. A build that cannot see the reference
    implementation must not claim it just read it.
    """
    try:
        vocab = extract(verify_py)
    except ExtractionError as e:
        try:
            snap = json.loads(JSON_OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e2:
            raise ExtractionError(
                f"{e}; and the committed snapshot {JSON_OUT.name} is unusable: {e2}") from e2
        d = snap["derived_from"]
        return snap, (
            f"read from the committed snapshot suite/{JSON_OUT.name}, derived from "
            f"{d['path']} sha256 {d['sha256'][:12]}. The reference implementation was "
            f"not readable at build time ({e}), so this vocabulary was NOT re-derived now.")
    if JSON_OUT.exists():
        try:
            old = json.loads(JSON_OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
        if old != vocab:
            generate(verify_py)
    else:
        generate(verify_py)
    d = vocab["derived_from"]
    return vocab, (
        f"derived at build time by parsing {d['path']} "
        f"(sha256 {d['sha256'][:12]}, {d['lines']} lines) for every site that "
        "appends a named refusal")


if __name__ == "__main__":
    v = generate()
    print(f"wrote {JSON_OUT} and {JS_OUT}: {len(v['refusals'])} refusals "
          f"from {v['derived_from']['path']} sha256 {v['derived_from']['sha256'][:12]}")
    print(f"  spec constants: {', '.join(sorted(v['constants']))}")
    print(f"  report lines: {len(v['report_lines'])}")
    for r in v["refusals"]:
        flag = "  (archive path only)" if r["archive_only"] else ""
        print(f"  {r['name']:<26} {r['sites']} site(s), first at line {r['first_line']}{flag}")
