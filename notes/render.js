// The ONE markdown renderer for these notes.
//
// It is a module rather than inline script because there are now two consumers:
// this directory's index page, which renders a post in the browser, and
// tools/build-notes.mjs, which renders the same post to a static file at build
// time. A second implementation for the static path would be a sibling of this
// one, and the first correction to either would silently stop applying to the
// other. Import it; do not reimplement it.
const ABOUT_LABEL = {models: "model", harness: "instrument", infrastructure: "infrastructure"};
const label = (a) => ABOUT_LABEL[a] || a;
const esc = (s) => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// Deliberately a small subset: headings, tables, bold, links, rules, paragraphs.
// That is exactly what the generator emits. A general markdown library would
// render things the drafts never produce and hide a change in what they do.
function md(src) {
  const out = [];
  const lines = src.replace(/\r/g, "").split("\n");
  let i = 0;
  // Code spans are pulled out BEFORE any other inline rule and put back after.
  // Without that, markdown inside a code span gets processed: this post quotes a
  // model that literally answered `**Au**`, and rendering that as bold Au would
  // delete the evidence the post is about.
  const inline = (t) => {
    const code = [];
    let x = esc(t).replace(/`([^`]+)`/g, (m, c) => {
      code.push(c);
      return `\u0000${code.length - 1}\u0000`;
    });
    x = x
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>')
      // The generator emits bare urls (the board link, the repo, the portfolio),
      // so a renderer that only handles [text](url) leaves every one of them as
      // plain text.
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:])/g,
               (m, pre, url) => `${pre}<a href="${url}">${url}</a>`)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|\s)\*([^*]+)\*/g, "$1<em>$2</em>");
    return x.replace(/\u0000(\d+)\u0000/g, (m, n) => `<code>${code[+n]}</code>`);
  };

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("<!--")) {                       // editor guidance, never shown
      while (i < lines.length && !lines[i].includes("-->")) i++;
      i++; continue;
    }
    let m = line.match(/^(#{1,4})\s+(.*)$/);
    if (m) { const n = m[1].length; out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++; continue; }
    if (/^---+$/.test(line.trim())) { out.push("<hr>"); i++; continue; }
    if (line.trim().startsWith(">")) {                   // a quoted prompt or task
      const q = [];
      while (i < lines.length && lines[i].trim().startsWith(">"))
        q.push(lines[i++].trim().replace(/^>\s?/, ""));
      out.push(`<blockquote><p>${inline(q.join(" "))}</p></blockquote>`);
      continue;
    }
    if (line.trim().startsWith("|")) {                   // the evidence table
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(/^[\s|:-]+$/.test(rows[1] || "") ? 2 : 1);
      out.push('<div class="twrap"><table><thead><tr>' + head.map(h => `<th>${inline(h)}</th>`).join("") +
        "</tr></thead><tbody>" +
        body.map(r => "<tr>" + cells(r).map(c => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
        "</tbody></table></div>");
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|---+$|\||>)/.test(lines[i].trim()))
      para.push(lines[i++]);
    const text = para.join(" ");
    out.push(text.startsWith("*") && text.endsWith("*") && !text.startsWith("**")
      ? `<p class="note">${inline(text.slice(1, -1))}</p>`
      : `<p>${inline(text)}</p>`);
  }
  return out.join("\n");
}

function card(p) {
  const about = ["models", "harness", "infrastructure"].includes(p.about) ? p.about : "";
  return `<a class="card" href="./${encodeURIComponent(p.slug)}/">
    <div class="meta"><span class="date">${esc(p.date || "")}</span>
    ${about ? `<span class="tag ${about}">${esc(label(about))}</span>` : ""}
    ${p.kind ? `<span class="tag">${esc(p.kind)}</span>` : ""}</div>
    <h2>${esc(p.title)}</h2><p>${esc(p.summary || "")}</p></a>`;
}

export { ABOUT_LABEL, label, esc, md, card };
