// A STRUCTURAL VERIFIER FOR VAC EVIDENCE BUNDLES, RUN IN THE BROWSER.
//
// WHAT THIS IS. A port of the checks vac/verify.py performs that a browser can
// genuinely compute over the bundle's own bytes: manifest schema, artifact
// presence and sha256 (crypto.subtle, real SHA-256, not a stand-in), bundle
// closure, stated limitations, stamp agreement, and the declared numbers
// recomputed from the artifacts under the evidence profiles it implements.
//
// WHAT THIS IS NOT. Semantic replay. A structural PASS here means exactly what
// it means at the command line: the bundle is internally honest, not that the
// issuer's grader would emit these verdicts. Only re-running the issuer's code
// at the pinned commit re-earns that, and this file never claims otherwise.
//
// THE RULE THIS FILE OBEYS. Not one refusal name is typed here. Every name is
// addressed through R.<IDENTIFIER> on the table refusals.gen.js generates by
// parsing verify.py, so a refusal the reference implementation renames or drops
// throws on first use instead of quietly printing a name that no longer exists.
// Same for the spec constants: profiles, op sets, weight tables and the render
// patterns all arrive in VAC_SPEC from the same generated artifact.
//
// FAIL CLOSED. A profile this port does not implement is never a pass. It is
// reported as UNPORTED, the run's verdict becomes INCOMPLETE, and the page says
// which check did not run. A verifier that skips silently is the defect the
// whole protocol exists to refuse, and it would be worse here than anywhere.
'use strict';
globalThis.VACBROWSER = (function () {
  const R = globalThis.VAC_REFUSALS;
  const SPEC = globalThis.VAC_SPEC;
  if (!R || !SPEC) {
    throw new Error('refusals.gen.js must be loaded before vacbrowser.js: ' +
      'the vocabulary is generated from verify.py, never typed here');
  }

  // ---------------------------------------------------------------- numbers
  // Python's round() rounds the EXACT binary value of the double to the nearest
  // multiple of 10^-n, ties to even, then converts the decimal back. toFixed()
  // breaks ties the other way, so 0.125 at 2 places would disagree with the
  // reference verifier on a value a bundle can really carry. Done exactly with
  // BigInt: |x| = m * 2^e, scale by 10^p, divide, compare 2r to den.
  function pyRound(x, places) {
    if (!Number.isFinite(x) || x === 0) return x;
    const neg = x < 0 || Object.is(x, -0);
    const buf = new DataView(new ArrayBuffer(8));
    buf.setFloat64(0, Math.abs(x));
    const hi = BigInt(buf.getUint32(0)), lo = BigInt(buf.getUint32(4));
    const bits = (hi << 32n) | lo;
    const expBits = Number((bits >> 52n) & 0x7ffn);
    const frac = bits & 0xfffffffffffffn;
    let m, e;
    if (expBits === 0) { m = frac; e = -1074n; }
    else { m = frac | 0x10000000000000n; e = BigInt(expBits - 1075); }
    const p = BigInt(places);
    let num = m, den = 1n;
    if (e >= 0n) num <<= e; else den <<= -e;
    if (p >= 0n) num *= 10n ** p; else den *= 10n ** -p;
    let q = num / den;
    const r = num % den, twice = r * 2n;
    if (twice > den || (twice === den && (q & 1n) === 1n)) q += 1n;
    // Build the decimal string and let Number() do the (correctly rounded)
    // conversion back, which is what CPython's round does via strtod.
    let s;
    if (places >= 0) {
      let d = q.toString().padStart(places + 1, '0');
      s = places === 0 ? d : d.slice(0, d.length - places) + '.' + d.slice(d.length - places);
    } else {
      s = q.toString() + '0'.repeat(-places);
    }
    const out = Number(s);
    return neg ? -out : out;
  }

  // Python repr for a float: shortest round-tripping digits, '.0' forced on a
  // whole value, and scientific notation on the same thresholds CPython uses
  // (decpt <= -4 or decpt > 16), which are NOT the thresholds String() uses.
  function pyFloatRepr(x) {
    if (Number.isNaN(x)) return 'nan';
    if (x === Infinity) return 'inf';
    if (x === -Infinity) return '-inf';
    if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
    const neg = x < 0;
    const ex = Math.abs(x).toExponential();           // shortest digits
    const [mant, expPart] = ex.split('e');
    const digits = mant.replace('.', '');
    const decpt = parseInt(expPart, 10) + 1;
    let body;
    if (decpt <= -4 || decpt > 16) {
      const e2 = decpt - 1;
      // CPython adds the trailing '.0' only in FIXED notation: repr(1e-05)
      // is '1e-05', not '1.0e-05'.
      const head = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
      body = head + 'e' + (e2 < 0 ? '-' : '+') + String(Math.abs(e2)).padStart(2, '0');
    } else if (decpt <= 0) {
      body = '0.' + '0'.repeat(-decpt) + digits;
    } else if (decpt >= digits.length) {
      body = digits + '0'.repeat(decpt - digits.length) + '.0';
    } else {
      body = digits.slice(0, decpt) + '.' + digits.slice(decpt);
    }
    return neg ? '-' + body : body;
  }

  // JSON collapses 5 and 5.0 into one JS number, so float-ness is carried in a
  // side table keyed by the CONTAINER the value sits in. Without it every
  // reference message that prints a float would read "4" where the CLI reads
  // "4.0", and the two transcripts would stop being comparable.
  const FLOATS = new WeakMap();
  function markFloat(parent, key) {
    let s = FLOATS.get(parent);
    if (!s) { s = new Set(); FLOATS.set(parent, s); }
    s.add(String(key));
  }
  function isFloatAt(parent, key) {
    const s = parent && typeof parent === 'object' ? FLOATS.get(parent) : null;
    return !!(s && s.has(String(key)));
  }

  function pyStrRepr(s) {
    const q = (s.includes("'") && !s.includes('"')) ? '"' : "'";
    let out = '';
    for (const ch of s) {
      const c = ch.codePointAt(0);
      if (ch === '\\') out += '\\\\';
      else if (ch === q) out += '\\' + q;
      else if (ch === '\n') out += '\\n';
      else if (ch === '\r') out += '\\r';
      else if (ch === '\t') out += '\\t';
      else if (c < 0x20 || c === 0x7f) out += '\\x' + c.toString(16).padStart(2, '0');
      else out += ch;
    }
    return q + out + q;
  }

  // repr(v) as Python would print it. `parent`/`key` locate the float table.
  function pyRepr(v, parent, key) {
    if (v === null || v === undefined) return 'None';
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (typeof v === 'number') return numRepr(v, isFloatAt(parent, key));
    if (typeof v === 'string') return pyStrRepr(v);
    if (Array.isArray(v)) return '[' + v.map((x, i) => pyRepr(x, v, i)).join(', ') + ']';
    if (typeof v === 'object') {
      return '{' + Object.keys(v).map(k => pyStrRepr(k) + ': ' + pyRepr(v[k], v, k)).join(', ') + '}';
    }
    return String(v);
  }
  function numRepr(v, isFloat) {
    if (typeof v !== 'number') return String(v);
    if (isFloat || !Number.isInteger(v)) return pyFloatRepr(v);
    return String(v);
  }
  // str() of a number, which is what an f-string interpolation without !r does.
  function numStr(v, parent, key) {
    if (typeof v !== 'number') return v === null || v === undefined ? 'None'
      : typeof v === 'boolean' ? (v ? 'True' : 'False') : String(v);
    return numRepr(v, isFloatAt(parent, key));
  }
  // A number produced by this port's own recomputation, where float-ness is
  // known from the arithmetic rather than from a JSON literal.
  function F(v) { return { v: v, f: true }; }
  function I(v) { return { v: v, f: false }; }
  function unwrap(t) { return t && typeof t === 'object' && 'v' in t ? t.v : t; }
  function tagStr(t) { return numRepr(unwrap(t), t && typeof t === 'object' ? t.f : false); }

  // CPython's sum() has not been a naive left-to-right add since 3.12: it runs
  // Neumaier compensated summation over floats. A plain reduce here disagreed
  // with the reference verifier in the 4th-from-last digit of an unrounded mean,
  // which is the kind of difference that turns an agreeing pair of verifiers
  // into a page printing a number the command line does not print.
  function pySum(vals) {
    let f = 0.0, c = 0.0;
    for (const x of vals) {
      const t = f + x;
      if (Math.abs(f) >= Math.abs(x)) c += (f - t) + x;
      else c += (x - t) + f;
      f = t;
    }
    return f + c;
  }

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function sortedKeys(o) { return Object.keys(o).sort(cmp); }

  // ------------------------------------------------------------------- JSON
  // A hand-written parser, for two reasons JSON.parse cannot serve: it records
  // which literals were floats (above), and it reproduces CPython's decoder
  // messages, so the manifest-parse refusal on the page carries the same
  // `Expecting value: line 1 column 1 (char 0)` tail the command line prints.
  class PyJSONError extends Error {}
  const NUMBER_RE = /(-?(?:0|[1-9]\d*))(\.\d+)?([eE][-+]?\d+)?/y;

  function jsonParse(text) {
    let i = 0;
    const err = (msg, pos) => {
      const nl = text.lastIndexOf('\n', pos - 1);
      const lineno = (text.slice(0, pos).match(/\n/g) || []).length + 1;
      const colno = pos - nl;
      throw new PyJSONError(`${msg}: line ${lineno} column ${colno} (char ${pos})`);
    };
    const WS = ' \t\n\r';
    const ws = () => { while (i < text.length && WS.includes(text[i])) i++; };

    function parseString() {
      const begin = i - 1;                       // the opening quote
      let out = '';
      for (;;) {
        if (i >= text.length) err('Unterminated string starting at', begin);
        const ch = text[i];
        if (ch === '"') { i++; return out; }
        if (ch === '\\') {
          const esc = i;                       // the backslash itself
          i++;
          if (i >= text.length) err('Unterminated string starting at', begin);
          const e = text[i++];
          const simple = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
          if (e in simple) { out += simple[e]; continue; }
          if (e !== 'u') err('Invalid \\escape', esc);
          const hex = text.slice(i, i + 4);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) err('Invalid \\uXXXX escape', esc + 1);
          out += String.fromCharCode(parseInt(hex, 16));
          i += 4;
          continue;
        }
        if (ch.charCodeAt(0) < 0x20) err('Invalid control character at', i);
        out += ch;
        i++;
      }
    }

    function parseValue(path) {
      ws();
      if (i >= text.length) err('Expecting value', i);
      const ch = text[i];
      if (ch === '"') { i++; return parseString(); }
      if (ch === '{') {
        i++;
        const obj = {};
        ws();
        if (text[i] === '}') { i++; return obj; }
        for (;;) {
          ws();
          if (text[i] !== '"') err('Expecting property name enclosed in double quotes', i);
          i++;
          const key = parseString();
          ws();
          if (text[i] !== ':') err("Expecting ':' delimiter", i);
          i++;
          const sub = path ? `${path}.${key}` : key;
          const start = (ws(), i);
          const val = parseValue(sub);
          spans.set(sub, [start, i]);
          if (typeof val === 'number' && lastWasFloat) markFloat(obj, key);
          obj[key] = val;
          ws();
          if (text[i] === '}') { i++; return obj; }
          if (text[i] !== ',') err("Expecting ',' delimiter", i);
          const comma = i;
          i++;
          ws();
          if (text[i] === '}') err('Illegal trailing comma before end of object', comma);
        }
      }
      if (ch === '[') {
        i++;
        const arr = [];
        ws();
        if (text[i] === ']') { i++; return arr; }
        for (;;) {
          const sub = `${path}[${arr.length}]`;
          ws();
          const start = i;
          const val = parseValue(sub);
          spans.set(sub, [start, i]);
          if (typeof val === 'number' && lastWasFloat) markFloat(arr, arr.length);
          arr.push(val);
          ws();
          if (text[i] === ']') { i++; return arr; }
          if (text[i] !== ',') err("Expecting ',' delimiter", i);
          const comma = i;
          i++;
          ws();
          if (text[i] === ']') err('Illegal trailing comma before end of array', comma);
        }
      }
      if (text.startsWith('true', i)) { i += 4; lastWasFloat = false; return true; }
      if (text.startsWith('false', i)) { i += 5; lastWasFloat = false; return false; }
      if (text.startsWith('null', i)) { i += 4; lastWasFloat = false; return null; }
      if (text.startsWith('NaN', i)) { i += 3; lastWasFloat = true; return NaN; }
      if (text.startsWith('Infinity', i)) { i += 8; lastWasFloat = true; return Infinity; }
      if (text.startsWith('-Infinity', i)) { i += 9; lastWasFloat = true; return -Infinity; }
      NUMBER_RE.lastIndex = i;
      const m = NUMBER_RE.exec(text);
      if (m && m.index === i) {
        i += m[0].length;
        lastWasFloat = !!(m[2] || m[3]);
        return Number(m[0]);
      }
      err('Expecting value', i);
    }

    const spans = new Map();
    let lastWasFloat = false;
    const value = parseValue('');
    spans.set('', [0, i]);
    ws();
    if (i < text.length) err('Extra data', i);
    return { value, spans };
  }

  function canonical(v) {                       // json.dumps(x, sort_keys=True)
    if (v === null) return 'null';
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    if (typeof v === 'object') {
      return '{' + sortedKeys(v).map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
    }
    return JSON.stringify(v);
  }

  // ------------------------------------------------------------------ bytes
  async function sha256Hex(bytes) {
    const buf = await crypto.subtle.digest('SHA-256',
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
  }
  // ignoreBOM:true means DO NOT strip it. The default, false, silently removes a leading
  // U+FEFF, so a BOM'd bundle parsed clean here while Python's read_text() refused it as
  // unparseable. Same bytes, opposite verdicts, and no corpus fixture carried a BOM so the
  // conformance suite was green throughout. Keep the BOM in the string and let JSON.parse
  // reject it, which is what CPython does.
  const DEC = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  class DecodeError extends Error {}
  function decodeText(bytes) {
    try { return DEC.decode(bytes); }
    catch (e) { throw new DecodeError("'utf-8' codec can't decode the file's bytes"); }
  }

  // ------------------------------------------------------------- predicates
  function isHex64(v) {
    return typeof v === 'string' && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
  }
  function nonemptyStr(v) { return typeof v === 'string' && v.trim() !== ''; }
  function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
  function nonemptyObj(v) { return isObj(v) && Object.keys(v).length > 0; }

  // pathlib resolves `bundle / "./results.json"` to results.json, so a manifest
  // may list a path that is not the literal key of any file. The path stays RAW
  // everywhere it is compared (listed, trusted, closure), because that is what
  // the reference verifier compares; only the lookup normalises.
  function fsPath(p) {
    return typeof p === 'string' ? p.split('/').filter(s => s !== '' && s !== '.').join('/') : p;
  }
  function fileBytes(bundle, rel) { return bundle.files.get(fsPath(rel)); }

  function safeRelpath(p) {
    if (!nonemptyStr(p) || p === 'vac.json' || p.includes('\\')) return false;
    for (const ch of p) {
      const c = ch.codePointAt(0);
      if (c < 0x20 || c === 0x7f) return false;
    }
    if (/^[A-Za-z]:/.test(p) || p.startsWith('//')) return false;   // windows drive / UNC
    if (p.startsWith('/')) return false;
    const parts = p.split('/').filter(s => s !== '' && s !== '.');
    if (parts.length === 0) return false;
    return !parts.includes('..');
  }

  // Python str() of an interpolated value, as an f-string without !r renders it.
  function pyStr(v, parent, key) {
    if (v === null || v === undefined) return 'None';
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (typeof v === 'number') return numRepr(v, isFloatAt(parent, key));
    if (typeof v === 'string') return v;
    return pyRepr(v, parent, key);
  }

  // ------------------------------------------------------- drafts (SPEC 2.7)
  function todoFailures(m) {
    const f = [];
    (function walk(node, path) {
      if (isObj(node)) {
        for (const k of sortedKeys(node)) walk(node[k], path ? `${path}.${k}` : k);
      } else if (Array.isArray(node)) {
        node.forEach((v, i) => walk(v, `${path}[${i}]`));
      } else if (typeof node === 'string' && node.startsWith(SPEC.TODO_PREFIX)) {
        f.push(`${R.DRAFT_INCOMPLETE}: ${path} is an unauthored TODO`);
      }
    })(m, '');
    return f;
  }

  // -------------------------------------------------------- schema (SPEC 2)
  function validateManifest(m) {
    const f = [];
    const need = (obj, path, pred, what) => {
      const leaf = path.split('.').pop();
      const v = isObj(obj) ? obj[leaf] : undefined;
      if (!pred(v)) { f.push(`${R.SCHEMA_VIOLATION}: ${path}: ${what}`); return null; }
      return v;
    };
    if (m.vac_version !== SPEC.VAC_VERSION) {
      f.push(`${R.SCHEMA_VIOLATION}: vac_version: must be ${pyRepr(SPEC.VAC_VERSION)}, ` +
        `got ${pyRepr(m.vac_version, m, 'vac_version')}`);
    }
    const claim = need(m, 'claim', isObj, 'object required') || {};
    need(claim, 'claim.capability', nonemptyStr, 'non-empty string required');
    need(claim, 'claim.scope', nonemptyStr, 'non-empty string required');
    const lims = claim.limitations;
    if (!(Array.isArray(lims) && lims.length && lims.every(nonemptyStr))) {
      f.push(R.EMPTY_LIMITATIONS);
    }
    const subject = need(m, 'subject', isObj, 'object required') || {};
    if (subject.kind !== 'agent' && subject.kind !== 'suite-archetype') {
      f.push(`${R.SCHEMA_VIOLATION}: subject.kind: must be 'agent' or 'suite-archetype'`);
    }
    need(subject, 'subject.id', nonemptyStr, 'non-empty string required');
    if (!nonemptyObj(subject.version)) {
      // verify.py punctuates this one message with a long dash. It is written
      // here as an escape, never as a literal, so the port stays byte-faithful
      // to the reference text without that character entering this source file.
      f.push(`${R.SCHEMA_VIOLATION}: subject.version: at least one pinned identifier ` +
        'required \u2014 an unpinned subject is unverifiable');
    }
    const proto = need(m, 'protocol', isObj, 'object required') || {};
    for (const k of ['issuer', 'issuer_commit', 'task', 'grading', 'control_policy']) {
      need(proto, `protocol.${k}`, nonemptyStr, 'non-empty string required');
    }
    const hashes = proto.hashes;
    if (!(nonemptyObj(hashes) && Object.values(hashes).every(nonemptyStr))) {
      f.push(`${R.SCHEMA_VIOLATION}: protocol.hashes: at least one named content hash required`);
    }
    const ev = m.evidence;
    if (!(Array.isArray(ev) && ev.length)) {
      f.push(`${R.SCHEMA_VIOLATION}: evidence: non-empty array required`);
    } else {
      const seen = new Set();
      ev.forEach((e, i) => {
        if (!isObj(e) || !safeRelpath(e.path)) {
          f.push(`${R.SCHEMA_VIOLATION}: evidence[${i}].path: safe relative path required`);
          return;
        }
        if (!isHex64(e.sha256)) {
          f.push(`${R.SCHEMA_VIOLATION}: evidence[${i}].sha256: 64 lowercase hex chars required`);
        }
        if (seen.has(e.path)) f.push(`${R.DUPLICATE_ARTIFACT}: ${e.path}`);
        seen.add(e.path);
      });
    }
    const results = need(m, 'results', isObj, 'object required') || {};
    if (!isObj(results.summary)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.summary: object required`);
    }
    const checks = results.checks;
    if (!(Array.isArray(checks) && checks.length)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks: at least one profile check required`);
    } else {
      checks.forEach((c, i) => {
        if (!isObj(c)) {
          f.push(`${R.SCHEMA_VIOLATION}: results.checks[${i}]: object required`);
          return;
        }
        if (!SPEC.PROFILES.includes(c.profile)) {
          f.push(`${R.UNKNOWN_PROFILE}: results.checks[${i}]: ${pyRepr(c.profile, c, 'profile')}`);
        }
      });
    }
    const replay = need(m, 'replay', isObj, 'object required') || {};
    const rc = replay.issuer_commit;
    if (!nonemptyStr(rc)) f.push(R.MISSING_ISSUER_COMMIT);
    else if (nonemptyStr(proto.issuer_commit) && rc !== proto.issuer_commit) {
      f.push(`${R.ISSUER_COMMIT_MISMATCH}: replay ${rc} != protocol ${proto.issuer_commit}`);
    }
    const cmds = replay.commands;
    if (!(Array.isArray(cmds) && cmds.length && cmds.every(nonemptyStr))) {
      f.push(`${R.SCHEMA_VIOLATION}: replay.commands: non-empty list of commands required`);
    }
    if (!nonemptyStr(replay.expected)) {
      f.push(`${R.SCHEMA_VIOLATION}: replay.expected: expected outcome required`);
    }
    return f;
  }

  // ------------------------------------- artifacts: presence, sha256, closure
  function verifyArtifacts(bundle, m) {
    const f = [];
    const entries = (Array.isArray(m.evidence) ? m.evidence : [])
      .filter(e => isObj(e) && safeRelpath(e.path));
    const listed = new Set(entries.map(e => e.path));
    const trusted = new Set();
    for (const e of entries) {
      if (!bundle.files.has(fsPath(e.path))) {
        f.push(`${R.MISSING_ARTIFACT}: ${e.path}`);
        continue;
      }
      if (!isHex64(e.sha256)) continue;          // already named as a schema violation
      const actual = bundle.digests.get(fsPath(e.path));
      if (actual !== e.sha256) {
        f.push(`${R.SHA256_MISMATCH}: ${e.path}: manifest ${e.sha256}, file ${actual}`);
      } else {
        trusted.add(e.path);
      }
    }
    for (const rel of Array.from(bundle.files.keys()).sort(cmp)) {
      if (rel !== 'vac.json' && !listed.has(rel)) f.push(`${R.UNLISTED_FILE}: ${rel}`);
    }
    return { failures: f, trusted };
  }

  // --------------------------------------------- evidence profiles (SPEC 3)
  function loadJson(bundle, rel, f, want) {
    want = want || ['object'];
    let data;
    try {
      const parsed = jsonParse(decodeText(fileBytes(bundle, rel)));
      data = parsed.value;
    } catch (e) {
      if (e instanceof PyJSONError || e instanceof DecodeError) {
        f.push(`${R.ARTIFACT_UNPARSABLE}: ${rel}: ${e.message}`);
        return null;
      }
      throw e;
    }
    const okObj = want.includes('object') && isObj(data);
    const okArr = want.includes('array') && Array.isArray(data);
    if (!okObj && !okArr) {
      const name = want.map(w => w === 'object' ? 'an object' : 'an array').join(' or ');
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${rel}: top level must be ${name}`);
      return null;
    }
    return data;
  }

  // WHAT ACTUALLY RAN. The scope statement is not a paragraph about what this
  // port is capable of, it is a record of the phases THIS run reached. A bundle
  // refused for a missing manifest never reaches the schema or the hashes, and a
  // profile with no stamp binding compares no stamps: saying otherwise would be
  // the same overclaim the page exists to refuse, one level up.
  let WORK = new Set();
  function noteWork(kind) { WORK.add(kind); }


  function poolOf(rec) {                     // {k: tagged} -> {k: [tagged]}
    const out = {};
    for (const k of Object.keys(rec)) out[k] = [rec[k]];
    return out;
  }

  // ---- certlab-bundle-v1
  function checkCertlab(bundle, check, proto, f) {
    const art = check.artifact;
    const data = loadJson(bundle, art, f);
    if (data === null) return null;
    const verdicts = data.verdicts;
    if (!Array.isArray(verdicts)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no verdicts[] array`);
      return null;
    }
    const count = k => verdicts.filter(v => isObj(v) && v[k] === true).length;
    const recomputed = {
      verdicts: I(verdicts.length), fixed: I(count('fixed')),
      policy_ok: I(count('policy_ok')), tests_ok: I(count('tests_ok')),
    };
    const expect = check.expect;
    if (!nonemptyObj(expect)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[certlab-bundle-v1].expect: ` +
        'declared counts required');
    } else {
      for (const k of sortedKeys(expect)) {
        if (!(k in recomputed)) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: not recomputable under certlab-bundle-v1`);
        } else if (expect[k] !== unwrap(recomputed[k])) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: declared ${pyStr(expect[k], expect, k)}, ` +
            `recomputed ${tagStr(recomputed[k])}`);
        }
      }
    }
    const hashes = isObj(proto.hashes) ? proto.hashes : {};
    for (const k of ['taskset_hash', 'prompt_hash']) {
      if (!(k in hashes)) continue;
      noteWork('stamp');
      if (!(k in data)) {
        f.push(`${R.STAMP_MISMATCH}: ${k}: named by protocol.hashes but absent from ${art}`);
      } else if (hashes[k] !== data[k]) {
        f.push(`${R.STAMP_MISMATCH}: ${k}: protocol ${pyStr(hashes[k], hashes, k)}, ` +
          `artifact ${pyStr(data[k], data, k)}`);
      }
    }
    const ic = proto.issuer_commit;
    if (nonemptyStr(ic)) {
      noteWork('stamp');
      if (!('harness_commit' in data)) {
        f.push(`${R.STAMP_MISMATCH}: harness_commit: protocol declares issuer_commit ` +
          `but ${art} carries no harness_commit`);
      } else if (data.harness_commit !== ic) {
        f.push(`${R.STAMP_MISMATCH}: harness_commit: protocol ${ic}, ` +
          `artifact ${pyStr(data.harness_commit, data, 'harness_commit')}`);
      }
    }
    const pool = poolOf(recomputed);
    const modes = new Map();
    for (const v of verdicts) {
      if (isObj(v) && nonemptyStr(v.failure_mode)) {
        modes.set(v.failure_mode, (modes.get(v.failure_mode) || 0) + 1);
      }
    }
    for (const [mode, cnt] of modes) {
      if (!(mode in recomputed)) {
        if (!(mode in pool)) pool[mode] = [];
        pool[mode].push(I(cnt));
      }
    }
    const renderRel = check.render;
    if (nonemptyStr(renderRel)) {
      let text = null;
      try { text = decodeText(fileBytes(bundle, renderRel)); }
      catch (e) { f.push(`${R.ARTIFACT_UNPARSABLE}: ${renderRel}: ${e.message}`); }
      if (text !== null) checkCertlabRender(renderRel, text, recomputed, f);
    }
    return pool;
  }

  function checkCertlabRender(art, text, want, f) {
    const m = new RegExp(SPEC.PATTERNS._CERTLAB_RENDER).exec(text);
    if (!m) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no 'N/M seeded defects fixed' headline ` +
        'to compare against the verdicts');
      return;
    }
    for (const [k, got] of [['fixed', parseInt(m[1], 10)], ['verdicts', parseInt(m[2], 10)]]) {
      if (!(k in want)) {
        f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: contract names ${k}, which this profile ` +
          'does not recompute');
        return;
      }
      if (got !== unwrap(want[k])) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: contract shows ${k} ${got}, ` +
          `verdicts recompute ${tagStr(want[k])}`);
      }
    }
  }

  // ---- fleet-board-v1
  function fleetRates(lines) {
    const n = lines.length;
    const det = lines.filter(l => isObj(l) && l.detected === true).length;
    const fa = lines.filter(l => !(isObj(l) && l.clean_passed === true)).length;
    return [['n', I(n)], ['detected', I(det)], ['false_alarms', I(fa)],
      ['detection_rate', F(pyRound(det / n, 3))],
      ['false_alarm_rate', F(pyRound(fa / n, 3))]];
  }

  function checkFleet(bundle, check, proto, f) {
    const agg = loadJson(bundle, check.aggregate, f);
    const rawRel = check.raw;
    let raw;
    try {
      // str.splitlines() breaks on more than \n. Matching it matters because a
      // JSONL artifact written on another platform must parse into the same
      // number of rows here as it does at the command line.
      raw = decodeText(fileBytes(bundle, rawRel))
        .split(/\r\n|[\n\r\u000b\u000c\u001c\u001d\u001e\u0085\u2028\u2029]/)
        .filter(ln => ln.trim() !== '').map(ln => jsonParse(ln).value);
    } catch (e) {
      if (e instanceof PyJSONError || e instanceof DecodeError) {
        f.push(`${R.ARTIFACT_UNPARSABLE}: ${rawRel}: ${e.message}`);
        return null;
      }
      throw e;
    }
    if (agg === null) return null;
    const rows = agg.rows;
    if (!Array.isArray(rows)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${check.aggregate}: no rows[] array`);
      return null;
    }
    const groups = new Map();                 // canonical key -> {suite, member, lines}
    raw.forEach((ln, idx) => {
      const o = isObj(ln) ? ln : {};
      const suite = 'suite' in o ? o.suite : null;
      const member = 'member' in o ? o.member : null;
      const paired = o.defective_failed === true && o.clean_passed === true;
      const got = 'detected' in o ? o.detected : null;
      if (got !== paired) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${pyStr(suite, o, 'suite')}/` +
          `${pyStr(member, o, 'member')}: raw line ${idx + 1} detected flag ` +
          'contradicts its own pair');
      }
      const key = canonical([suite, member]);
      if (!groups.has(key)) groups.set(key, { suite, member, lines: [] });
      groups.get(key).lines.push(ln);
    });
    const expect = check.expect;
    if (isObj(expect)) {
      for (const k of sortedKeys(expect)) {
        if (k !== 'rows') {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: not recomputable under fleet-board-v1`);
        } else if (expect[k] !== rows.length) {
          f.push(`${R.SUMMARY_MISMATCH}: rows: declared ${pyStr(expect[k], expect, k)}, ` +
            `recomputed ${rows.length}`);
        }
      }
    }
    const seen = new Set();
    for (const row of rows) {
      const o = isObj(row) ? row : {};
      const suite = 'suite' in o ? o.suite : null;
      const member = 'member' in o ? o.member : null;
      const where = `${pyStr(suite, o, 'suite')}/${pyStr(member, o, 'member')}`;
      const key = canonical([suite, member]);
      if (seen.has(key)) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${where}: duplicate aggregate row`);
        continue;
      }
      seen.add(key);
      const grp = groups.get(key);
      if (!grp || !grp.lines.length) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${where}: aggregate row has no raw lines`);
        continue;
      }
      for (const [k, v] of fleetRates(grp.lines)) {
        const declared = k in o ? o[k] : null;
        if (declared !== unwrap(v)) {
          f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${where}: ${k} declared ` +
            `${pyStr(declared, o, k)}, recomputed ${tagStr(v)}`);
        }
      }
    }
    for (const [key, grp] of groups) {
      if (!seen.has(key)) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${pyStr(grp.suite, grp, 'suite')}/` +
          `${pyStr(grp.member, grp, 'member')}: raw lines with no aggregate row`);
      }
    }
    const ic = proto.issuer_commit;
    if (nonemptyStr(ic)) {
      noteWork('stamp');
      if (!('fleet_commit' in agg)) {
        f.push(`${R.STAMP_MISMATCH}: fleet_commit: protocol declares issuer_commit but ` +
          'the aggregate row carries no fleet_commit');
      } else if (agg.fleet_commit !== ic) {
        f.push(`${R.STAMP_MISMATCH}: fleet_commit: protocol ${ic}, ` +
          `artifact ${pyStr(agg.fleet_commit, agg, 'fleet_commit')}`);
      }
    }
    const hashes = isObj(proto.hashes) ? proto.hashes : {};
    if ('fleet_commit' in hashes) {
      noteWork('stamp');
      if (!('fleet_commit' in agg)) {
        f.push(`${R.STAMP_MISMATCH}: hashes.fleet_commit: named by protocol.hashes but ` +
          'absent from the aggregate row');
      } else if (hashes.fleet_commit !== agg.fleet_commit) {
        f.push(`${R.STAMP_MISMATCH}: hashes.fleet_commit: protocol ` +
          `${pyStr(hashes.fleet_commit, hashes, 'fleet_commit')}, artifact ` +
          `${pyStr(agg.fleet_commit, agg, 'fleet_commit')}`);
      }
    }
    const suites = new Set();
    for (const g of groups.values()) suites.add(canonical(g.suite));
    const pool = { rows: [I(groups.size)], suites: [I(suites.size)] };
    const add = (k, v) => { if (!(k in pool)) pool[k] = []; pool[k].push(v); };
    const bySuite = new Map();
    for (const g of groups.values()) {
      const sk = canonical(g.suite);
      if (!bySuite.has(sk)) bySuite.set(sk, []);
      bySuite.get(sk).push(...g.lines);
      for (const [k, v] of fleetRates(g.lines)) add(k, v);
    }
    for (const lines of bySuite.values()) {
      const stats = fleetRates(lines);
      stats.push(['members', I(new Set(lines.map(l => canonical(isObj(l) ? l.member : null))).size)]);
      for (const [k, v] of stats) add(k, v);
    }
    if (raw.length) for (const [k, v] of fleetRates(raw)) add(k, v);
    return pool;
  }

  // ---- evalmut-run-v1
  function checkEvalmut(bundle, check, proto, f) {
    const art = check.artifact;
    const data = loadJson(bundle, art, f);
    if (data === null) return null;
    const rows = data.results;
    if (!Array.isArray(rows) || !rows.every(isObj)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no results[] array ` +
        '(evalmut-run-v1 requires the --json --all payload)');
      return null;
    }
    const tally = data.tally;
    if (!isObj(tally)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no tally object`);
      return null;
    }
    const holes = data.holes;
    if (!isObj(holes)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no holes object`);
      return null;
    }
    rows.forEach((r, idx) => {
      if ((r.outcome === 'missed' && r.polarity !== 'defect')
        || (r.outcome === 'flagged' && r.polarity !== 'equivalent')) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: row ${idx + 1} outcome ` +
          `${pyRepr(r.outcome, r, 'outcome')} contradicts its polarity ` +
          `${pyRepr(r.polarity, r, 'polarity')}`);
      }
    });
    const counts = {};
    for (const k of ['caught', 'missed', 'flagged', 'error', 'na']) {
      counts[k] = rows.filter(r => r.outcome === k).length;
    }
    for (const k of ['caught', 'missed', 'flagged', 'error', 'na']) {
      const declared = k in tally ? tally[k] : null;
      if (declared !== counts[k]) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: tally.${k} declared ` +
          `${pyStr(declared, tally, k)}, recomputed ${counts[k]}`);
      }
    }
    const applied = counts.caught + counts.missed + counts.flagged;
    const score = applied === 0 ? 1.0 : counts.caught / applied;
    if (('score' in data ? data.score : null) !== score) {
      f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: score declared ` +
        `${pyStr('score' in data ? data.score : null, data, 'score')}, ` +
        `recomputed ${pyFloatRepr(score)}`);
    }
    const holeCounts = {};
    for (const [cls, outcome, opType] of SPEC.EVALMUT_HOLES) {
      const want = rows.filter(r => r.outcome === outcome
        && (opType === null || r.op_type === opType));
      holeCounts[cls] = want.length;
      const rawHoles = holes[cls];
      const got = Array.isArray(rawHoles) ? rawHoles.filter(isObj) : [];
      const a = got.map(canonical).sort(cmp), b = want.map(canonical).sort(cmp);
      if (canonical(a) !== canonical(b)) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: holes.${cls} does not recompute ` +
          `from the rows (declared ${got.length}, recomputed ${want.length})`);
      }
    }
    const recomputed = {
      caught: I(counts.caught), missed: I(counts.missed), flagged: I(counts.flagged),
      error: I(counts.error), na: I(counts.na),
      applied: I(applied), results: I(rows.length), score_3: F(pyRound(score, 3)),
      vacuous: I(holeCounts.vacuous), blind: I(holeCounts.blind),
      brittle: I(holeCounts.brittle), coverage_gap: I(holeCounts.coverage_gap),
      operators_exercised: I(new Set(rows.map(r => canonical(r.operator_id))).size),
    };
    const catRel = check.catalog;
    if (nonemptyStr(catRel)) {
      const cat = loadJson(bundle, catRel, f, ['array']);
      if (cat !== null) {
        let ok = true;
        if (!cat.every(isObj)) {
          f.push(`${R.ARTIFACT_UNPARSABLE}: ${catRel}: no operator array`);
        } else {
          cat.forEach((o, idx) => {
            if (!(nonemptyStr(o.id) && nonemptyStr(o.real_origin))) {
              // verify.py's own long dash, written as an escape, never typed
              f.push(`${R.ARTIFACT_UNPARSABLE}: ${catRel}: catalog entry ${idx + 1} lacks a ` +
                'non-empty id/real_origin \\u2014 the battery must be mined, not asserted');
              ok = false;
            }
          });
          const byId = new Map();
          for (const o of cat) if (nonemptyStr(o.id)) byId.set(o.id, o);
          if (ok && byId.size !== cat.length) {
            f.push(`${R.ARTIFACT_UNPARSABLE}: ${catRel}: duplicate operator ids`);
            ok = false;
          }
          if (ok) {
            rows.forEach((r, idx) => {
              const op = byId.get(r.operator_id);
              if (op === undefined) {
                f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: row ${idx + 1} operator ` +
                  `${pyRepr(r.operator_id, r, 'operator_id')} is not in the catalog`);
                return;
              }
              for (const k of ['family', 'polarity', 'op_type']) {
                const a = k in r ? r[k] : null, b = k in op ? op[k] : null;
                if (a !== b) {
                  f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: row ${idx + 1} ${k} ` +
                    `${pyRepr(a, r, k)} contradicts the catalog's ${pyRepr(b, op, k)}`);
                }
              }
            });
            recomputed.operators = I(cat.length);
          }
        }
      }
    }
    const renderRel = check.render;
    if (nonemptyStr(renderRel)) {
      let text = null;
      try { text = decodeText(fileBytes(bundle, renderRel)); }
      catch (e) { f.push(`${R.ARTIFACT_UNPARSABLE}: ${renderRel}: ${e.message}`); }
      if (text !== null) checkEvalmutRender(renderRel, text, recomputed, f);
    }
    const expect = check.expect;
    if (!nonemptyObj(expect)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[evalmut-run-v1].expect: ` +
        'declared counts required');
    } else {
      for (const k of sortedKeys(expect)) {
        if (!(k in recomputed)) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: not recomputable under evalmut-run-v1`);
        } else if (expect[k] !== unwrap(recomputed[k])) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: declared ${pyStr(expect[k], expect, k)}, ` +
            `recomputed ${tagStr(recomputed[k])}`);
        }
      }
    }
    const pool = poolOf(recomputed);
    pool.score = [F(score)];
    return pool;
  }

  function checkEvalmutRender(art, text, want, f) {
    const m = new RegExp(SPEC.PATTERNS._EVALMUT_RENDER).exec(text);
    if (!m) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no 'mutation score' headline ` +
        'to compare against the payload');
      return;
    }
    const got = {
      caught: I(parseInt(m[2], 10)), applied: I(parseInt(m[3], 10)),
      na: I(parseInt(m[4], 10)), score_3: F(pyRound(parseFloat(m[1]) / 100, 3)),
    };
    const missing = sortedKeys(got).filter(k => !(k in want));
    if (missing.length) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: render headline names ` +
        `${missing.join(', ')}, which this profile does not recompute`);
      return;
    }
    for (const k of sortedKeys(got)) {
      if (unwrap(got[k]) !== unwrap(want[k])) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: render shows ${k} ${tagStr(got[k])}, ` +
          `payload recomputes ${tagStr(want[k])}`);
      }
    }
  }

  // ---- crashkit-battery-v1
  function checkCrashkit(bundle, check, proto, f) {
    const art = check.artifact;
    const data = loadJson(bundle, art, f);
    if (data === null) return null;
    const cases = data.cases;
    if (!Array.isArray(cases) || !cases.every(isObj)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no cases[] array`);
      return null;
    }
    const metrics = data.metrics;
    if (!isObj(metrics)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no metrics object`);
      return null;
    }
    const perKind = data.per_kind;
    if (!isObj(perKind)) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no per_kind object`);
      return null;
    }
    for (let n = 0; n < cases.length; n++) {
      const c = cases[n];
      if (!(typeof c.passed === 'boolean' && typeof c.truncated === 'boolean'
        && typeof c.flagged === 'boolean' && nonemptyStr(c.kind))) {
        f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: case ${n + 1} lacks the explicit ` +
          'passed/truncated/flagged booleans + kind ' +
          '(crashkit-battery-v1 refuses note-parsing)');
        return null;
      }
    }
    cases.forEach((c, idx) => {
      if (c.flagged !== (!c.passed && !c.truncated)) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: case ${idx + 1} flagged flag ` +
          'contradicts its own passed/truncated pair');
      }
    });
    const W = SPEC.CRASHKIT_WEIGHTS;
    const graded = cases.filter(c => !c.truncated);
    const nCases = cases.length;
    const truncs = cases.filter(c => c.truncated).length;
    const errors = cases.filter(c => c.grader === 'error').length;
    const accuracy = graded.length
      ? pyRound(graded.filter(c => c.passed).length / graded.length, 4) : 0.0;
    // sorted({...}, key=lambda v: (v is None, str(v))): None last, then str order
    const seenSev = new Map();
    for (const c of graded) {
      const sev = 'severity' in c ? c.severity : null;
      const known = typeof sev === 'string' && Object.prototype.hasOwnProperty.call(W, sev);
      if (!known) seenSev.set(canonical(sev), sev);
    }
    const unknown = Array.from(seenSev.values()).sort((a, b) => {
      const ka = [a === null || a === undefined ? 1 : 0, pyStr(a)];
      const kb = [b === null || b === undefined ? 1 : 0, pyStr(b)];
      return ka[0] - kb[0] || cmp(ka[1], kb[1]);
    });
    if (unknown.length) {
      const labels = unknown.slice(0, 4).map(u => pyRepr(u)).join(', ');
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: severity ${labels} outside the ` +
        `profile's frozen table (${Object.keys(W).join('/')})`);
      return null;
    }
    const totalW = graded.reduce((s, c) => s + W[c.severity], 0);
    const failedW = graded.filter(c => !c.passed).reduce((s, c) => s + W[c.severity], 0);
    const recomputed = {
      accuracy: F(accuracy),
      vulnerability_score: F(totalW ? pyRound(failedW / totalW, 4) : 0.0),
      flagged_cases: F(cases.filter(c => c.flagged).length),
      n_cases: F(nCases),
      truncations: F(truncs),
      reliability: F(nCases ? pyRound((nCases - errors - truncs) / nCases, 4) : 0.0),
      cases: I(nCases), graded: I(graded.length), errors: I(errors),
    };
    for (const k of SPEC.CRASHKIT_ACC_ALIASES) {
      const declared = k in metrics ? metrics[k] : null;
      if (declared !== accuracy) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: metrics.${k} declared ` +
          `${pyStr(declared, metrics, k)}, recomputed ${pyFloatRepr(accuracy)}`);
      }
    }
    for (const k of ['vulnerability_score', 'flagged_cases', 'n_cases',
      'truncations', 'reliability']) {
      const declared = k in metrics ? metrics[k] : null;
      if (declared !== unwrap(recomputed[k])) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: metrics.${k} declared ` +
          `${pyStr(declared, metrics, k)}, recomputed ${tagStr(recomputed[k])}`);
      }
    }
    const kinds = new Map();
    for (const c of graded) {
      if (!kinds.has(c.kind)) kinds.set(c.kind, []);
      kinds.get(c.kind).push(c.passed ? 1 : 0);
    }
    const want = new Map();
    for (const [k, v] of kinds) {
      want.set(k, pyRound(v.reduce((a, b) => a + b, 0) / v.length, 4));
    }
    const allKinds = Array.from(new Set([...Object.keys(perKind), ...kinds.keys()])).sort(cmp);
    for (const k of allKinds) {
      const declared = k in perKind ? perKind[k] : null;
      const w = want.has(k) ? want.get(k) : null;
      if (declared !== w) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: per_kind[${pyRepr(k)}] declared ` +
          `${pyStr(declared, perKind, k)}, recomputed ${w === null ? 'None' : pyFloatRepr(w)}`);
      }
    }
    const key = check.battery_hash_key;
    const hashes = isObj(proto.hashes) ? proto.hashes : {};
    if (!nonemptyStr(key)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[crashkit-battery-v1].battery_hash_key: ` +
        "name of the protocol.hashes entry pinning this artifact's battery required");
    } else if ((noteWork('stamp'), !(key in hashes))) {
      f.push(`${R.STAMP_MISMATCH}: ${key}: named by the check but absent from protocol.hashes`);
    } else if (hashes[key] !== ('git_sha' in data ? data.git_sha : null)) {
      f.push(`${R.STAMP_MISMATCH}: ${key}: protocol ${pyStr(hashes[key], hashes, key)}, ` +
        `artifact ${pyStr('git_sha' in data ? data.git_sha : null, data, 'git_sha')}`);
    }
    const expect = check.expect;
    if (!nonemptyObj(expect)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[crashkit-battery-v1].expect: ` +
        'declared numbers required');
    } else {
      for (const k of sortedKeys(expect)) {
        if (!(k in recomputed)) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: not recomputable under crashkit-battery-v1`);
        } else if (expect[k] !== unwrap(recomputed[k])) {
          f.push(`${R.SUMMARY_MISMATCH}: ${k}: declared ${pyStr(expect[k], expect, k)}, ` +
            `recomputed ${tagStr(recomputed[k])}`);
        }
      }
    }
    return poolOf(recomputed);
  }

  // ---- rows-aggregate-v1
  function rowsAggregate(rows, op, field, places) {
    if (op === 'count') return rows.length * 1.0;
    const vals = rows.map(r => (field in r ? r[field] : null));
    const round = v => (places === null || places === undefined) ? v : pyRound(v, places);
    if (op === 'rate_true') {
      if (!vals.every(v => typeof v === 'boolean')) return null;
      return round(vals.filter(v => v).length / rows.length);
    }
    if (!vals.every(v => typeof v === 'number')) return null;
    if (op === 'sum') return round(pySum(vals));
    if (op === 'mean') return round(pySum(vals) / rows.length);
    if (op === 'min') return round(vals.reduce((a, b) => (b < a ? b : a)));
    if (op === 'max') return round(vals.reduce((a, b) => (b > a ? b : a)));
    return null;
  }

  function checkRowsAggregate(bundle, check, proto, f) {
    const art = check.artifact;
    const data = loadJson(bundle, art, f, ['object', 'array']);
    if (data === null) return null;
    const rowsKey = check.rows_key;
    const rows = Array.isArray(data) ? data
      : (nonemptyStr(rowsKey) ? (rowsKey in data ? data[rowsKey] : null) : null);
    if (!Array.isArray(rows) || !rows.every(isObj)) {
      const where = nonemptyStr(rowsKey) ? pyRepr(rowsKey) : 'the document';
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: no array of row objects at ${where}`);
      return null;
    }
    if (!rows.length) {
      f.push(`${R.ARTIFACT_UNPARSABLE}: ${art}: rows[] is empty; no aggregate ` +
        'can be recomputed from nothing');
      return null;
    }
    const recipe = check.recompute;
    if (!nonemptyObj(recipe)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[rows-aggregate-v1].recompute: ` +
        'a recipe naming how each declared number is recomputed from the rows is required');
      return null;
    }
    const recomputed = {};
    for (const name of sortedKeys(recipe)) {
      const spec = recipe[name];
      if (!isObj(spec)) {
        f.push(`${R.SCHEMA_VIOLATION}: recompute.${name}: object required`);
        return null;
      }
      const op = spec.op;
      if (!SPEC.ROW_OPS.includes(op)) {
        f.push(`${R.SCHEMA_VIOLATION}: recompute.${name}.op: ${pyRepr(op, spec, 'op')} ` +
          `is not one of ${SPEC.ROW_OPS.join('/')}`);
        return null;
      }
      const field = spec.field;
      if (op !== 'count' && !nonemptyStr(field)) {
        f.push(`${R.SCHEMA_VIOLATION}: recompute.${name}.field: required ` +
          `for op ${pyRepr(op, spec, 'op')}`);
        return null;
      }
      const places = 'round' in spec ? spec.round : null;
      // isinstance(places, int) is False for a JSON float literal such as 4.0.
      // The parser records which literals carried a fraction, so the port can
      // make the same distinction JS numbers would otherwise erase.
      if (places !== null && !(typeof places === 'number' && Number.isInteger(places)
        && !isFloatAt(spec, 'round'))) {
        f.push(`${R.SCHEMA_VIOLATION}: recompute.${name}.round: integer required`);
        return null;
      }
      if (op !== 'count') {
        const missing = rows.findIndex(r => !(field in r));
        if (missing >= 0) {
          f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: recompute.${name} reads ` +
            `${pyRepr(field, spec, 'field')}, absent from row ${missing}`);
          return null;
        }
      }
      const got = rowsAggregate(rows, op, field, places);
      if (got === null) {
        f.push(`${R.RAW_AGGREGATE_MISMATCH}: ${art}: recompute.${name}: ` +
          `${pyRepr(field, spec, 'field')} is not the type op ${pyRepr(op, spec, 'op')} ` +
          'requires across every row');
        return null;
      }
      recomputed[name] = F(got);
    }
    const expect = check.expect;
    if (!nonemptyObj(expect)) {
      f.push(`${R.SCHEMA_VIOLATION}: results.checks[rows-aggregate-v1].expect: ` +
        'declared numbers required');
      return null;
    }
    for (const k of sortedKeys(expect)) {
      if (!(k in recomputed)) {
        f.push(`${R.SUMMARY_MISMATCH}: ${k}: declared but the recipe does not recompute it`);
      } else if (expect[k] !== unwrap(recomputed[k])) {
        f.push(`${R.SUMMARY_MISMATCH}: ${k}: declared ${pyStr(expect[k], expect, k)}, ` +
          `recomputed ${tagStr(recomputed[k])}`);
      }
    }
    return poolOf(recomputed);
  }

  // Profiles this port implements. A profile that is NOT here is not a pass and
  // not a refusal: it is UNPORTED, the run is INCOMPLETE, and the page says
  // which check did not run. Skipping it silently would be the exact defect.
  const CHECK_FNS = {
    'certlab-bundle-v1': checkCertlab,
    'fleet-board-v1': checkFleet,
    'evalmut-run-v1': checkEvalmut,
    'crashkit-battery-v1': checkCrashkit,
    'rows-aggregate-v1': checkRowsAggregate,
  };
  const PORTED = Object.keys(CHECK_FNS);
  const NOT_PORTED = SPEC.PROFILES.filter(p => !(p in CHECK_FNS));

  // ------------------------------------------------------------- coherence
  function summaryOutruns(summary, pools) {
    const byField = new Map();
    for (const pool of pools) {
      for (const k of Object.keys(pool)) {
        if (!byField.has(k)) byField.set(k, new Map());
        for (const t of pool[k]) byField.get(k).set(unwrap(t), t.f);
      }
    }
    const allVals = new Map();
    for (const mp of byField.values()) {
      for (const [v, isF] of mp) if (!allVals.has(v)) allVals.set(v, isF);
    }
    const f = [];
    const numericStr = new RegExp('^(?:' + SPEC.PATTERNS._NUMERIC_STR + ')$');
    (function walk(node, path, key, parent, pkey) {
      if (isObj(node)) {
        for (const k of sortedKeys(node)) walk(node[k], `${path}.${k}`, k, node, k);
        return;
      }
      if (Array.isArray(node)) {
        node.forEach((v, i) => walk(v, `${path}[${i}]`, key, node, i));
        return;
      }
      if (typeof node === 'boolean') return;
      if (typeof node === 'string') {
        if (numericStr.test(node.trim())) {
          f.push(`${R.SUMMARY_OUTRUNS_CHECKS}: ${path}: declares ${pyRepr(node)} as a ` +
            'string; a numeric headline must be a JSON number so it can be recomputed');
        }
        return;
      }
      if (typeof node !== 'number') return;
      const mp = byField.get(key);
      if (mp) {
        if (!mp.has(node)) {
          const got = Array.from(mp.keys()).sort((a, b) => a - b);
          const shown = got.length === 1
            ? numRepr(got[0], mp.get(got[0]))
            : 'one of [' + got.map(v => numRepr(v, mp.get(v))).join(', ') + ']';
          f.push(`${R.SUMMARY_OUTRUNS_CHECKS}: ${path}: declares ` +
            `${pyStr(node, parent, pkey)}, recomputation gives ${shown}`);
        }
      } else if (!allVals.has(node)) {
        f.push(`${R.SUMMARY_OUTRUNS_CHECKS}: ${path}: declares ` +
          `${pyStr(node, parent, pkey)}, no check recomputes it`);
      }
    })(summary, 'summary', 'summary', null, null);
    return f;
  }

  function coherence(bundle, m, trusted) {
    const f = [];
    const results = isObj(m.results) ? m.results : {};
    const proto = isObj(m.protocol) ? m.protocol : {};
    const listed = new Set((Array.isArray(m.evidence) ? m.evidence : [])
      .filter(e => isObj(e) && safeRelpath(e.path)).map(e => e.path));
    const pools = [];
    const checks = Array.isArray(results.checks) ? results.checks : [];
    const covered = new Set();
    for (const c of checks) {
      if (!isObj(c)) continue;
      for (const v of Object.values(c)) if (typeof v === 'string' && listed.has(v)) covered.add(v);
    }
    let complete = true;
    const unported = [], ran = [];
    for (const c of checks) {
      if (!isObj(c) || !SPEC.PROFILES.includes(c.profile)) { complete = false; continue; }
      let usable = true;
      const refs = Array.from(SPEC.CHECK_REFS[c.profile]);
      for (const k of (SPEC.CHECK_OPT_REFS[c.profile] || [])) if (k in c) refs.push(k);
      for (const refKey of refs) {
        const r = c[refKey];
        if (!nonemptyStr(r) || !listed.has(r)) {
          f.push(`${R.CHECK_ARTIFACT_NOT_LISTED}: ${pyRepr(r, c, refKey)}`);
          usable = false;
        } else if (!trusted.has(r)) {
          usable = false;                      // missing or hash-failed: already named
        }
      }
      if (!usable) { complete = false; continue; }
      const fn = CHECK_FNS[c.profile];
      if (!fn) { complete = false; unported.push(c.profile); continue; }
      const before = f.length;
      const pool = fn(bundle, c, proto, f);
      if (pool === null) {
        complete = false;
        if (f.length === before) {                // fail closed, never skip silently
          f.push(`${R.ARTIFACT_UNPARSABLE}: ${c.profile}: check contributed no recomputation`);
        }
      } else {
        pools.push(pool);
        ran.push(c.profile);
      }
    }
    const uncovered = Array.from(listed).filter(p => !covered.has(p)).sort(cmp);
    if (uncovered.length) {
      const shown = uncovered.slice(0, 4).join(', ');
      const more = uncovered.length > 4 ? ` (+${uncovered.length - 4} more)` : '';
      f.push(`${R.EVIDENCE_UNCHECKED}: ${shown}${more}: listed in evidence ` +
        'but read by no check');
    }
    const summary = results.summary;
    if (complete && pools.length && isObj(summary)) {
      for (const line of summaryOutruns(summary, pools)) f.push(line);
    }
    return { failures: f, unported, ran };
  }

  // -------------------------------------------------------------- the entry
  async function loadBundle(files) {
    const digests = new Map();
    for (const [rel, bytes] of files) digests.set(rel, await sha256Hex(bytes));
    return { files, digests };
  }

  function verifyBundle(bundle) {
    WORK = new Set();
    const out = { failures: [], unported: [], ran: [], manifest: null, work: WORK };
    if (!bundle.files.has('vac.json')) {
      out.failures.push(`${R.MISSING_MANIFEST}: no vac.json in bundle`);
      return out;
    }
    let m;
    try {
      m = jsonParse(decodeText(bundle.files.get('vac.json'))).value;
    } catch (e) {
      if (e instanceof PyJSONError || e instanceof DecodeError) {
        out.failures.push(`${R.INVALID_JSON}: vac.json: ${e.message}`);
        return out;
      }
      throw e;
    }
    if (!isObj(m)) {
      out.failures.push(`${R.INVALID_JSON}: vac.json: top level must be an object`);
      return out;
    }
    out.manifest = m;
    noteWork('manifest');
    const todo = todoFailures(m);
    noteWork('draft');
    if (todo.length) {                     // a draft is refused wholesale (SPEC 2.7)
      out.failures = todo;
      return out;
    }
    noteWork('artifacts');
    const art = verifyArtifacts(bundle, m);
    const coh = coherence(bundle, m, art.trusted);
    noteWork('schema');
    out.failures = validateManifest(m).concat(art.failures, coh.failures);
    out.unported = coh.unported;
    out.ran = coh.ran;
    return out;
  }

  // What this run actually did, and what it did not. The page prints verify.py's
  // own scope sentences beside these, taken from VAC_SPEC.REPORT_LINES, so the
  // browser cannot quietly claim a wider scope than the command line claims.
  // Each phase names what it proves when it runs and why it did not when it did
  // not. Nothing is listed as having run unless this run recorded it.
  const PHASES = [
    ['manifest', 'the manifest was found in the bundle and parsed as JSON',
      'the manifest was missing or unparsable, so every check below it was ' +
      'never reached'],
    ['draft', 'draft markers (SPEC 2.7): the manifest carries no unauthored TODO',
      'the draft scan never ran, because the manifest could not be read'],
    ['schema', 'manifest schema (SPEC 2), including stated limitations and ' +
      'issuer_commit agreement between the protocol and replay blocks',
      'the schema was not checked: the run stopped at a missing manifest, an ' +
      'unparsable manifest, or a draft refused wholesale'],
    ['artifacts', "artifact presence and sha256 over the bundle's own bytes, " +
      'computed with crypto.subtle SHA-256, plus bundle closure: every file ' +
      'present is a file the manifest lists',
      'no artifact was hashed and closure was not checked: the run stopped ' +
      'before it'],
    ['stamp', 'stamp agreement: a value named by protocol.hashes was compared ' +
      'against the artifact that carries it',
      'no stamp was compared: no check this bundle declares binds a ' +
      'protocol.hashes value to an artifact field'],
  ];

  function scopeOf(result) {
    const work = result.work || new Set();
    const ran = [], notRun = [];
    for (const [key, did, didNot] of PHASES) (work.has(key) ? ran : notRun)
      .push(work.has(key) ? did : didNot);
    for (const p of result.ran) {
      ran.push(`declared results recomputed from the artifacts under ${p}`);
    }
    notRun.push(
      'semantic replay: the issuer is not cloned and its grader is not re-run, ' +
        'so no verdict here is re-earned',
      'that the pinned issuer_commit exists in any repository, or that the ' +
        'replay commands run: both are compared as text only',
      'the archive path: a .tar.gz is unpacked and vetted by the command-line ' +
        'tool, never here');
    for (const p of result.unported) {
      notRun.push(`the ${p} recomputation, which this browser port does not ` +
        'implement: the bundle declares that check and it did not run here');
    }
    if (NOT_PORTED.length) {
      notRun.push('profiles this port does not implement at all: ' +
        NOT_PORTED.join(', ') + '. A bundle using one cannot pass here');
    }
    // The replay recipe, echoed exactly as the command line echoes it: the one
    // procedure that WOULD re-earn these verdicts, and the reason a structural
    // pass here is not that.
    const m = result.manifest;
    const replay = (m && isObj(m.replay)) ? m.replay : {};
    return {
      ran, notRun,
      replayCommands: Array.isArray(replay.commands)
        ? replay.commands.filter(c => typeof c === 'string') : [],
      replayExpected: typeof replay.expected === 'string' ? replay.expected : '',
    };
  }

  function verdictOf(result) {
    if (result.unported.length) return 'INCOMPLETE';
    return result.failures.length ? 'REFUSED' : 'PASS';
  }

  // ------------------------------------------------------------- mutations
  // Every mutation copies the bundle first and edits the COPY. The served bytes
  // are never touched, and each run re-derives its copy from them, so no
  // mutation can leak into the next one or into what the page ships.
  const ENC = new TextEncoder();

  function copyFiles(files) {
    const out = new Map();
    for (const [k, v] of files) out.set(k, v.slice());
    return out;
  }
  function textOf(files, rel) { return decodeText(files.get(rel)); }
  function setText(files, rel, text) { files.set(rel, ENC.encode(text)); return files; }

  // Byte-precise surgery: replace exactly the span one JSON value occupies and
  // leave every other byte of the document alone. A tamper that rewrote the
  // whole file would be a different, easier thing to catch.
  function spliceValue(files, rel, path, literal) {
    const text = textOf(files, rel);
    const { spans } = jsonParse(text);
    const span = spans.get(path);
    if (!span) throw new Error(`no value at ${path} in ${rel}`);
    return setText(files, rel, text.slice(0, span[0]) + literal + text.slice(span[1]));
  }
  function valueText(files, rel, path) {
    const text = textOf(files, rel);
    const span = jsonParse(text).spans.get(path);
    return span ? text.slice(span[0], span[1]) : null;
  }
  async function rehash(files, rel, evidenceIndex) {
    const digest = await sha256Hex(files.get(rel));
    return spliceValue(files, 'vac.json', `evidence[${evidenceIndex}].sha256`,
      JSON.stringify(digest));
  }

  // `expect` names the refusals a mutation is BUILT to trigger, addressed
  // through the generated table. The page never renders it: the page renders
  // what the verifier actually returned. It exists so the test harness can
  // fail when a mutation stops exercising the path it was written for.
  const MUTATIONS = [
    {
      id: 'sha256-flip',
      title: 'Flip one character of a listed sha256',
      blurb: 'One hex digit of the manifest entry for results.json, and nothing else. ' +
        'The artifact is untouched: only the number the manifest pins it to moves.',
      expect: [R.SHA256_MISMATCH],
      async apply(files) {
        const raw = valueText(files, 'vac.json', 'evidence[0].sha256');
        const digest = JSON.parse(raw);
        const flipped = (digest[0] === '0' ? '1' : '0') + digest.slice(1);
        return spliceValue(files, 'vac.json', 'evidence[0].sha256',
          JSON.stringify(flipped));
      },
    },
    {
      id: 'drop-artifact',
      title: 'Delete a listed artifact',
      blurb: 'results.json is removed from the bundle while the manifest keeps ' +
        'pinning it. The evidence for every declared number is simply gone.',
      expect: [R.MISSING_ARTIFACT],
      async apply(files) { files.delete('results.json'); return files; },
    },
    {
      id: 'blank-the-limitations',
      title: 'Empty the limitations field',
      blurb: 'The three stated non-claims are replaced with an empty list. ' +
        'A claim that admits nothing is an advertisement, so the bundle stops verifying.',
      expect: [R.EMPTY_LIMITATIONS],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'claim.limitations', '[]');
      },
    },
    {
      id: 'retouch-and-rehash',
      title: 'Improve the failing case, then re-hash so the manifest agrees',
      blurb: 'The one failing case scores 0.42. Raise it to 0.92 and recompute the ' +
        'sha256 so presence and integrity both still pass. Every refusal below is ' +
        'earned by recomputation, not by the hash.',
      expect: [R.SUMMARY_MISMATCH, R.SUMMARY_OUTRUNS_CHECKS],
      async apply(files) {
        spliceValue(files, 'results.json', 'cases[2].score', '0.92');
        return rehash(files, 'results.json', 0);
      },
    },
    {
      id: 'stray-file',
      title: 'Smuggle in an unlisted file',
      blurb: 'A file rides along in the bundle that the manifest never lists. ' +
        'Closure is what stops a bundle carrying content nobody pinned.',
      expect: [R.UNLISTED_FILE],
      async apply(files) {
        files.set('notes.txt', ENC.encode('shipped alongside, pinned by nothing\n'));
        return files;
      },
    },
    {
      id: 'delete-the-check',
      title: 'Delete the check that reads the artifact',
      blurb: 'Breaking a check is refused, so try deleting it instead. The artifact ' +
        'stays pinned and hash-clean, and nothing reads it.',
      expect: [R.SCHEMA_VIOLATION, R.EVIDENCE_UNCHECKED],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.checks', '[]');
      },
    },
    {
      id: 'bogus-profile',
      title: 'Declare a profile the spec does not define',
      blurb: 'A check whose profile is not in the frozen set names no rules, so ' +
        'nothing about it can be recomputed.',
      expect: [R.UNKNOWN_PROFILE],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.checks[0].profile',
          '"rows-aggregate-v9"');
      },
    },
    {
      id: 'check-elsewhere',
      title: 'Point the check at an artifact the manifest does not list',
      blurb: 'The check claims to read rows.json, which no evidence entry pins. ' +
        'Both halves are named: the dangling reference, and the artifact now read by nobody.',
      expect: [R.CHECK_ARTIFACT_NOT_LISTED, R.EVIDENCE_UNCHECKED],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.checks[0].artifact', '"rows.json"');
      },
    },
    {
      id: 'duplicate-evidence',
      title: 'List the same artifact twice',
      blurb: 'The evidence array pins results.json twice. One path, one entry: a ' +
        'second entry is a second answer to the same question.',
      expect: [R.DUPLICATE_ARTIFACT],
      async apply(files) {
        const one = valueText(files, 'vac.json', 'evidence[0]');
        return spliceValue(files, 'vac.json', 'evidence[0]', one + ',\n  ' + one);
      },
    },
    {
      id: 'commit-drift',
      title: 'Let the replay commit drift from the protocol commit',
      blurb: 'The replay block points at a different commit from the one the ' +
        'protocol pins, so the recipe would not re-run what was graded.',
      expect: [R.ISSUER_COMMIT_MISMATCH],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'replay.issuer_commit', '"deadbee"');
      },
    },
    {
      id: 'summary-inflate',
      title: 'Inflate a headline number',
      blurb: 'The published accuracy becomes 0.95 while the rows still recompute ' +
        '0.8. The headline is held to what the artifact supports.',
      expect: [R.SUMMARY_OUTRUNS_CHECKS],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.summary.accuracy', '0.95');
      },
    },
    {
      id: 'summary-as-string',
      title: 'Retype a headline number as a string',
      blurb: 'Quotes around 0.95 used to be enough to walk a number past a ' +
        'comparator that only looked at numbers. A numeral wearing quotes does not skip the check.',
      expect: [R.SUMMARY_OUTRUNS_CHECKS],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.summary.accuracy', '"0.95"');
      },
    },
    {
      id: 'expect-inflate',
      title: 'Inflate the number the check declares',
      blurb: 'The check itself declares accuracy 0.95. The recipe is still run over ' +
        'the rows, and the rows still say 0.8.',
      expect: [R.SUMMARY_MISMATCH],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'results.checks[0].expect.accuracy', '0.95');
      },
    },
    {
      id: 'draft-marker',
      title: 'Leave one unauthored TODO in the manifest',
      blurb: "A manifest still carrying vac.draft's marker is a workpiece, not a " +
        'claim, and is refused wholesale before anything else is checked.',
      expect: [R.DRAFT_INCOMPLETE],
      async apply(files) {
        return spliceValue(files, 'vac.json', 'claim.scope',
          '"TODO(scope): say what this run does and does not cover"');
      },
    },
    {
      id: 'break-json',
      title: 'Corrupt the manifest itself',
      blurb: 'One key loses its quotes. The manifest stops being JSON, and the ' +
        'refusal names the line and column.',
      expect: [R.INVALID_JSON],
      async apply(files) {
        const text = textOf(files, 'vac.json').replace(/"claim"(\s*):/, 'claim$1:');
        return setText(files, 'vac.json', text);
      },
    },
    {
      id: 'no-manifest',
      title: 'Ship the artifacts without a manifest',
      blurb: 'The evidence is all still there. Nothing states what it is evidence FOR, ' +
        'so there is no claim to verify.',
      expect: [R.MISSING_MANIFEST],
      async apply(files) { files.delete('vac.json'); return files; },
    },
  ];

  async function runMutation(sourceFiles, id) {
    const mut = MUTATIONS.find(m => m.id === id);
    if (!mut) throw new Error('no such mutation: ' + id);
    const files = await mut.apply(copyFiles(sourceFiles));
    const bundle = await loadBundle(files);
    const result = verifyBundle(bundle);
    return { mutation: mut, files, result, verdict: verdictOf(result) };
  }

  async function runClean(sourceFiles) {
    const bundle = await loadBundle(copyFiles(sourceFiles));
    const result = verifyBundle(bundle);
    return { bundle, result, verdict: verdictOf(result) };
  }

  return {
    loadBundle, verifyBundle, verdictOf, scopeOf,
    runClean, runMutation, MUTATIONS, PORTED, NOT_PORTED,
    sha256Hex, pyRound, pyFloatRepr, pyRepr, jsonParse,
    refusals: R, spec: SPEC,
  };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = globalThis.VACBROWSER;
