// Every published note must have a page here, and every page's canonical must
// match where it actually sits.
//
// The HTTP link checker cannot do the first job. Each generated note carries its
// own URL as its canonical, so checking that over HTTP asks whether the deploy
// currently running has already finished. On 2026-09-23 the link check ran at
// 23:13:52Z and Pages went live at 23:14:23Z: CI went red on two correct pages,
// and a re-run would have gone green without fixing anything.
//
// The first version of this file replaced that with a scan for
// https://erikhill.dev/notes/<slug>/ references and a check that each had a page.
// That check could not fail. The only thing carrying such a reference IS the page
// itself, so deleting a page deleted its own reference: the count dropped from 4
// to 2 and it exited 0. A self-reference is satisfied by definition.
//
// So the authority is posts/index.json in model-drift, which is where "published"
// is decided and which no page can edit.
const INDEX = "https://raw.githubusercontent.com/egnaro9/model-drift/main/posts/index.json";

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const NOTES = new URL("../notes/", import.meta.url).pathname;
const fail = (m) => { console.error(m); process.exitCode = 1; };

const r = await fetch(INDEX, { cache: "no-cache" });
if (!r.ok) { console.error(`cannot read ${INDEX}: HTTP ${r.status}`); process.exit(1); }
const index = await r.json();
if (!Array.isArray(index) || !index.length) {
  console.error("index.json is empty or not a list; refusing to pass vacuously");
  process.exit(1);
}

// 1. every published note has a page
for (const p of index) {
  try { await readFile(path.join(NOTES, p.slug, "index.html"), "utf8"); }
  catch { fail(`published but has no page: notes/${p.slug}/index.html`); }
}

// 2. every page's canonical matches where it sits, so a page cannot claim to be
//    a different note than the directory it was written into
const dirs = (await readdir(NOTES, { withFileTypes: true }))
  .filter(d => d.isDirectory()).map(d => d.name);
for (const d of dirs) {
  const html = await readFile(path.join(NOTES, d, "index.html"), "utf8");
  const m = html.match(/<link rel="canonical" href="https:\/\/erikhill\.dev\/notes\/([^"\/]+)\/">/);
  if (!m) fail(`notes/${d}/index.html has no canonical link`);
  else if (m[1] !== d) fail(`notes/${d}/ claims canonical /notes/${m[1]}/`);
}

// 3. a page for something no longer published is not an error, but say so
const extra = dirs.filter(d => !index.some(p => p.slug === d));
if (extra.length) console.log(`  note: page(s) present but not in index.json: ${extra.join(", ")}`);

if (!process.exitCode)
  console.log(`${index.length} published note(s), ${dirs.length} page(s), all canonicals match.`);
