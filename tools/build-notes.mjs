// Generate a real page per note at notes/<slug>/index.html.
//
// Why these exist at all: the index rendered every post inline and addressed
// them with a hash fragment. A fragment is invisible to search engines and to
// link-preview crawlers, so every post's canonical_url on dev.to pointed at
// https://erikhill.dev/notes/<slug>/ , a path that had never existed and
// returned 404. A canonical pointing at a dead page is worse than none: it
// tells a crawler the real version is somewhere that is not there.
//
// The URL shape here is chosen to match what those canonicals already claimed,
// so publishing makes the existing claim true rather than requiring every post
// to be rewritten.
//
// The markdown renderer is imported, never reimplemented. See notes/render.js.
import { md, esc, label } from "../notes/render.js";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const RAW = "https://raw.githubusercontent.com/egnaro9/model-drift/main/posts/";
const SITE = "https://erikhill.dev";
const OUT = new URL("../notes/", import.meta.url).pathname;

const argOf = (f, d) => {
  const i = process.argv.indexOf(f);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : d;
};
const LOCAL = argOf("--from", `${process.env.HOME}/model-drift/posts`);

async function load(name) {
  if (existsSync(path.join(LOCAL, name))) return readFile(path.join(LOCAL, name), "utf8");
  const r = await fetch(RAW + name, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status} from ${RAW}`);
  return r.text();
}

const page = (p, bodyHtml) => {
  const about = ["models", "harness", "infrastructure"].includes(p.about) ? p.about : "";
  const url = `${SITE}/notes/${p.slug}/`;
  const desc = (p.summary || "").slice(0, 300);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(p.title)} | Erik Hill</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${url}">
<meta property="og:type" content="article">
<meta property="og:title" content="${esc(p.title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${url}">
<meta property="og:site_name" content="Drift Notes">
<meta name="author" content="Erik Hill">
<meta property="article:author" content="https://erikhill.dev">
<meta property="article:published_time" content="${esc(p.date || "")}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(p.title)}">
<meta name="twitter:description" content="${esc(desc)}">
<link rel="stylesheet" href="/notes/notes.css">
</head>
<body>
<a href="${SITE}" aria-label="Back to portfolio" style="position:fixed;top:12px;left:14px;z-index:9999;font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;font-weight:600;color:#f2a53c;background:rgba(14,19,22,.86);border:1px solid rgba(242,165,60,.45);border-radius:4px;padding:6px 11px;text-decoration:none;backdrop-filter:blur(4px)">&#8592; Portfolio</a>

<div class="col">
  <article id="post" class="on">
    <header style="padding-top:76px">
      <a class="back" href="/notes/">&#8592; All notes</a>
      <div class="meta"><span class="date">${esc(p.date || "")}</span>${
        about ? `<span class="tag ${about}">${esc(label(about))}</span>` : ""}${
        p.kind ? `<span class="tag">${esc(p.kind)}</span>` : ""}</div>
      <div>${bodyHtml}</div>
    </header>
  </article>

  <div class="sub" style="margin-top:40px">
    <strong>Subscribe</strong>
    <p>Every note is archived at <a href="/notes/">Drift Notes</a>. To get them as
    they go out, <a href="https://www.linkedin.com/newsletters/7508403524037148672/"
    target="erikhill-out" rel="noopener">subscribe on LinkedIn</a>. Weekly when
    there is something to say, and silent when there is not.</p>
  </div>

  <footer>
    Generated from <a href="https://github.com/egnaro9/model-drift">model-drift</a>,
    which drafts these automatically from the run that produced them. The numbers are
    generated; the decision to publish is not.
    <br>Live board: <a href="https://egnaro9.github.io/model-drift/">the drift chart</a>.
  </footer>
</div>
</body>
</html>
`;
};

// A length check catches a page that rendered nothing. It does not catch a page
// that rendered MOST of a post, which is the failure a generator actually has:
// one unhandled construct and a section goes missing with everything around it
// intact. So compare word sequences, source against output, and refuse on any
// gap. Punctuation, tags and urls are normalised away because they legitimately
// differ between markdown and html; the prose may not.
function assertNothingDropped(slug, rawMd, html) {
  const strip = t => t.replace(/https?:\/\/\S+/g, " ");
  const words = t => strip(t.replace(/<[^>]+>/g, " ")
      .replace(/&[a-z]+;|&#\d+;/g, " "))
      .toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  const src = words(rawMd.replace(/^---\n[\s\S]*?\n---\n/, ""));
  const out = words(html).join(" ");
  const gaps = [];
  for (let i = 0; i + 8 < src.length; i += 4) {
    const w = src.slice(i, i + 8).join(" ");
    if (!out.includes(w)) gaps.push(w);
  }
  if (gaps.length) throw new Error(
    `${slug}: ${gaps.length} passage(s) from the source did not survive rendering.\n` +
    gaps.slice(0, 3).map(g => `    ${g}`).join("\n") +
    `\n  The page would have looked fine. Check render.js for an unhandled construct.`);
}

const index = JSON.parse(await load("index.json"));
if (!Array.isArray(index) || !index.length) {
  console.error("index.json is empty or not a list; refusing to wipe the notes directory");
  process.exit(1);
}

const written = [];
for (const p of index) {
  const raw = await load(p.file);
  const body = md(raw.replace(/^---\n[\s\S]*?\n---\n/, ""));
  if (body.trim().length < 200) throw new Error(`${p.slug}: rendered body is suspiciously short`);
  assertNothingDropped(p.slug, raw, body);
  const dir = path.join(OUT, p.slug);
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, "index.html"), page(p, body));
  written.push(p.slug);
  console.log(`  ${String(body.length).padStart(6)} bytes  /notes/${p.slug}/`);
}

// A page left behind for a post that was unpublished or renamed keeps serving a
// canonical nobody links to any more. Name them; do not delete silently.
const onDisk = (await readdir(OUT, { withFileTypes: true }))
  .filter(d => d.isDirectory()).map(d => d.name);
const orphans = onDisk.filter(d => !written.includes(d));
if (orphans.length) console.log(`\n  STALE, no longer in index.json: ${orphans.join(", ")}`);
console.log(`\n${written.length} page(s) generated.`);
