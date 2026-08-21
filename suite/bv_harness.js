// Node driver for the browser verifier, so its output can be diffed against
// the reference implementation over the same bytes.
//
// The point of this file is that nothing in it re-implements a check. It loads
// a bundle off disk into the same Map<path, Uint8Array> the page builds from
// embedded bytes, calls the same verifier and the same mutation functions the
// page calls, and prints what came back. A harness that computed anything of
// its own would be comparing two of my implementations instead of comparing
// mine against the reference.
//
//   node bv_harness.js verify <bundle-dir>
//   node bv_harness.js mutate <bundle-dir> <mutation-id> <out-dir>
//   node bv_harness.js list
'use strict';
const fs = require('fs');
const path = require('path');

require(path.join(__dirname, 'refusals.gen.js'));
const V = require(path.join(__dirname, 'vacbrowser.js'));

function loadDir(dir) {
  const files = new Map();
  (function walk(rel) {
    const abs = rel ? path.join(dir, rel) : dir;
    for (const name of fs.readdirSync(abs).sort()) {
      const sub = rel ? rel + '/' + name : name;
      const st = fs.statSync(path.join(dir, sub));
      if (st.isDirectory()) walk(sub);
      else if (st.isFile()) files.set(sub, new Uint8Array(fs.readFileSync(path.join(dir, sub))));
    }
  })('');
  return files;
}

function writeDir(files, out) {
  fs.rmSync(out, { recursive: true, force: true });
  for (const [rel, bytes] of files) {
    const dest = path.join(out, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, Buffer.from(bytes));
  }
  if (!files.size) fs.mkdirSync(out, { recursive: true });
}

function report(result, verdict) {
  return {
    verdict: verdict,
    failures: result.failures,
    names: result.failures.map(l => l.split(':')[0]),
    unported: result.unported,
    ran: result.ran,
    scope: V.scopeOf(result),
  };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === 'list') {
    console.log(JSON.stringify(V.MUTATIONS.map(m => ({
      id: m.id, title: m.title, blurb: m.blurb, expect: m.expect,
    })), null, 1));
    return;
  }
  if (cmd === 'verify') {
    const out = await V.runClean(loadDir(rest[0]));
    console.log(JSON.stringify(report(out.result, out.verdict), null, 1));
    return;
  }
  if (cmd === 'mutate') {
    const [dir, id, outDir] = rest;
    const out = await V.runMutation(loadDir(dir), id);
    if (outDir) writeDir(out.files, outDir);
    console.log(JSON.stringify(Object.assign(report(out.result, out.verdict), {
      mutation: id, expect: out.mutation.expect,
    }), null, 1));
    return;
  }
  console.error('usage: node bv_harness.js verify|mutate|list ...');
  process.exit(2);
}

main().catch(e => { console.error(e); process.exit(1); });
