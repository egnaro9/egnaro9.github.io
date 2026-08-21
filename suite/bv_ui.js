// The Break This Claim panel: the only part of the browser verifier that
// touches the DOM. It owns no checks. It decodes the embedded bundle, hands the
// bytes to VACBROWSER, and prints what came back, including the case where
// nothing could run at all.
//
// Two rules this file exists to keep. The served bytes are read once into SOURCE
// and never written to, so every run re-derives its own copy and a mutation can
// never reach the next run or the page. And nothing here decides a verdict: the
// verdict, the named refusals and the scope lines are all rendered from the
// verifier's return value, so the panel cannot show green over a check that did
// not happen.
'use strict';
(function () {
  const root = document.getElementById('bv');
  if (!root) return;
  const el = id => document.getElementById(id);
  const out = el('bv-out'), ctl = el('bv-ctl'), verdictEl = el('bv-verdict');
  const scopeEl = el('bv-scope'), blurbEl = el('bv-blurb');
  const data = JSON.parse(el('bv-bundle').textContent);

  const SOURCE = new Map(data.files.map(f =>
    [f.path, Uint8Array.from(atob(f.b64), c => c.charCodeAt(0))]));
  const PINNED = new Map(data.files.map(f => [f.path, f.sha256]));

  function line(text, cls) {
    const span = document.createElement('span');
    if (cls) span.className = cls;
    span.textContent = text + '\n';
    out.appendChild(span);
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function setVerdict(text, cls) {
    verdictEl.textContent = text;
    verdictEl.className = 'big ' + (cls || '');
  }

  // What the mutation actually changed, in bytes, against the served copy.
  function diffSummary(files) {
    const notes = [];
    for (const [path, bytes] of files) {
      const before = SOURCE.get(path);
      if (!before) { notes.push(`+ ${path} added (${bytes.length} bytes)`); continue; }
      if (before.length !== bytes.length) {
        notes.push(`~ ${path} rewritten (${before.length} bytes to ${bytes.length})`);
        continue;
      }
      let n = 0;
      for (let i = 0; i < bytes.length; i++) if (bytes[i] !== before[i]) n++;
      if (n) notes.push(`~ ${path} ${n} byte${n === 1 ? '' : 's'} changed`);
    }
    for (const path of SOURCE.keys()) {
      if (!files.has(path)) notes.push(`- ${path} removed`);
    }
    return notes.length ? notes : ['nothing changed'];
  }

  async function digestTable(files) {
    const rows = [];
    for (const [path, bytes] of files) {
      const digest = await VACBROWSER.sha256Hex(bytes);
      const pinned = PINNED.get(path);
      const note = path === 'vac.json' ? 'the manifest does not pin itself'
        : pinned === undefined ? 'not part of the served bundle'
          : digest === pinned ? 'matches the served bytes'
            : 'DIFFERS from the served bytes';
      rows.push(`  sha256(${path}) = ${digest}  (${note})`);
    }
    return rows;
  }

  function renderScope(scope) {
    clear(scopeEl);
    const add = (label, items, cls) => {
      const h = document.createElement('p');
      h.className = 'bvlabel';
      h.textContent = label;
      scopeEl.appendChild(h);
      const ul = document.createElement('ul');
      ul.className = 'bvlist ' + (cls || '');
      for (const item of items) {
        const li = document.createElement('li');
        li.textContent = item;
        ul.appendChild(li);
      }
      scopeEl.appendChild(ul);
    };
    add('ran: computed in this browser over the bytes above', scope.ran, 'ok');
    add('not run: nothing below was checked here', scope.notRun, 'no');
  }

  // The replay recipe, printed the way the command-line tool prints it. It is
  // the procedure that would re-earn these verdicts, and printing it beside a
  // PASS is what keeps the PASS from being mistaken for one.
  function renderReplay(scope) {
    if (!scope.replayCommands.length && !scope.replayExpected) return;
    line('semantic replay: NOT run by this page. To re-earn the verdicts, run the', 'warn');
    line("bundle's own replay block at the pinned issuer_commit:", 'warn');
    for (const cmd of scope.replayCommands) line('    $ ' + cmd, 'cmd');
    if (scope.replayExpected) line('    expected: ' + scope.replayExpected, 'cmd');
  }

  async function show(title, blurb, files, result, verdict) {
    clear(out);
    blurbEl.textContent = blurb || '';
    line('$ verify ' + data.root + '   [in this browser, over the bytes on this page]', 'cmd');
    for (const note of diffSummary(files)) line('  ' + note, 'warn');
    for (const row of await digestTable(files)) line(row, 'cmd');
    for (const f of result.failures) line('FAIL ' + f, 'fail');
    for (const p of result.unported) {
      line('NOT RUN  the ' + p + ' recomputation is not implemented in this browser port', 'warn');
    }
    const n = result.failures.length;
    if (verdict === 'PASS') {
      line('structural verification: PASS (' + data.root + ')', 'pass');
    } else if (verdict === 'REFUSED') {
      line('structural verification: FAIL, ' + n + ' named reason(s) (' + data.root + ')', 'fail');
    } else {
      line('structural verification: INCOMPLETE, ' + n + ' named reason(s) and at least one '
        + 'check that did not run (' + data.root + ')', 'warn');
    }
    setVerdict(verdict === 'PASS' ? 'PASS' : verdict === 'REFUSED'
      ? n + ' refused' : 'INCOMPLETE',
      verdict === 'PASS' ? 'ok' : verdict === 'REFUSED' ? 'bad' : 'warn');
    const scope = VACBROWSER.scopeOf(result);
    renderReplay(scope);
    renderScope(scope);
  }

  function button(label, cls, fn) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    b.onclick = () => {
      for (const other of ctl.querySelectorAll('button')) other.classList.remove('sel');
      b.classList.add('sel');
      fn().catch(e => {
        clear(out);
        line('the panel could not complete a run: ' + e.message, 'fail');
        setVerdict('INCOMPLETE', 'warn');
      });
    };
    ctl.appendChild(b);
    return b;
  }

  async function runClean() {
    const r = await VACBROWSER.runClean(SOURCE);
    await show('unmodified', 'The bundle exactly as it is served, with nothing altered.',
      r.bundle.files, r.result, r.verdict);
  }

  function build() {
    button('Verify the bundle as served', '', runClean);
    for (const m of VACBROWSER.MUTATIONS) {
      button(m.title, 'ghost', async () => {
        const r = await VACBROWSER.runMutation(SOURCE, m.id);
        await show(m.title, m.blurb, r.files, r.result, r.verdict);
      });
    }
  }

  if (!globalThis.crypto || !crypto.subtle) {
    // No SubtleCrypto means no sha256, which means artifact integrity cannot be
    // checked here at all. That is INCOMPLETE, and it is never a pass.
    setVerdict('INCOMPLETE', 'warn');
    line('crypto.subtle is unavailable in this context, so no sha256 can be computed here.',
      'warn');
    line('Nothing was verified. Run the command-line verifier instead.', 'warn');
    return;
  }
  build();
  runClean().catch(e => {
    clear(out);
    line('the panel could not complete its first run: ' + e.message, 'fail');
    setVerdict('INCOMPLETE', 'warn');
  });
})();
