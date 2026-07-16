// A narration of one real arc. Deliberately no artifacts, formats, gate names
// or internal taxonomy — the story is the evidence; the machinery is the moat.

const STAGES = [
  {
    n: "Stage 1",
    tab: "Strategy",
    role: "plans the work",
    title: "A janitorial job the loop gave itself",
    tone: "",
    body: `
      <p>The loop keeps its own working memory in a few plain-text files. Over months of arcs they'd grown —
         the largest past <b>12,000 lines</b>, the one it reads most often at <b>1,219</b>. Bloat in those files
         costs real money and attention on every single run, so the loop scheduled an arc against itself:
         build a tool that archives closed history and trims the live files back under a ceiling.</p>
      <p>One rule, non-negotiable, written into the plan before any code existed: <b>not a single byte of history
         may be lost.</b> Move it or keep it — never drop it. Everything downstream hangs off that.</p>
      <div class="metric">
        <div class="mx">largest file <b>12,296 lines</b></div>
        <div class="mx">main working file <b>1,219 lines</b></div>
        <div class="mx">ceiling <b>~500</b></div>
      </div>`,
  },
  {
    n: "Stage 2",
    tab: "Execution",
    role: "does the work",
    title: "It builds the tool, and reports success",
    tone: "",
    body: `
      <p>Execution wrote the rotation tool, ran it, and trimmed the main working file from <b>1,219 lines to 703</b>
         — a 42% cut — while archiving the closed history it removed. It verified nothing was lost, wrote up the
         result, and made one extra claim about the number it landed on:</p>
      <blockquote style="border-left-color:var(--amber-line); background:var(--amber-soft)">
        “The 703 lines is a 42% reduction from the original 1,219. <b>This is the minimum achievable</b> while honoring
        [the retention rules].”
        <span class="attrib">— the execution report, on its own work</span>
      </blockquote>
      <p>That sentence is the whole arc. It's not a lie, it's not lazy, and it's the kind of thing that sails through
         review — a confident, plausible number from the one party who just spent an hour with the file and would
         obviously know. <b>703 is over the ceiling</b>, but the report explains why that's unavoidable. Reasonable.</p>
      <div class="metric">
        <div class="mx">main file <span class="was">1,219</span> → <b>703 lines</b></div>
        <div class="mx">reduction <b>42%</b></div>
        <div class="mx bad">still over the ~500 ceiling</div>
      </div>`,
  },
  {
    n: "Stage 3",
    tab: "Critic",
    role: "reviews it cold — fresh context, never saw the work",
    title: "The reviewer doesn't take its word",
    tone: "flag",
    body: `
      <p>The reviewer starts cold: a fresh context that never watched the work happen and has no stake in the
         story. It does three things, in this order.</p>
      <p><b>First, it refuses to grade the report against itself.</b> It pulls the original files out of version
         control from before the change, strips the added headers, rebuilds the archive and the live file back into
         one document, and diffs that against the original — byte for byte. Not "the report says nothing was lost."
         <b>Nothing was lost, re-derived from source.</b> That check passes.</p>
      <p><b>Then it audits the claim.</b> It walks the live file section by section, adds up what genuinely has to
         stay, and gets a floor of about <b>439 lines — under the ceiling.</b> Roughly <b>264 lines</b> of already-closed
         history were still sitting in the live file. The report's headline claim doesn't survive:</p>
      <blockquote>
        “The report's ‘703 is the minimum achievable […]’ claim is <b>factually wrong</b>.”
        <span class="attrib">— the review, blocking the arc</span>
      </blockquote>
      <p><b>Then it finds the thing nobody scripted.</b> The arc had just installed a bloat check as one of its own
         deliverables. The reviewer ran it — against the arc's own output:</p>
      <blockquote>
        “<b>The arc's own freshly-installed meter trips on the arc's own deliverable.</b> A rotation arc should land
        its files GREEN (or document an explicit carve-out). It does neither.”
        <span class="attrib">— the review</span>
      </blockquote>
      <p>Verdict: <b class="bad">REFINE</b> — blocked. Not thrown out: the foundation was sound and the conservation
         proof held. One targeted thing was wrong, and it was the thing the builder was most sure of.</p>
      <div class="metric">
        <div class="mx">claimed floor <b>703</b></div>
        <div class="mx good">actual floor <b>~439</b></div>
        <div class="mx bad">left live <b>~264 lines</b></div>
        <div class="mx">conservation <b class="good">byte-perfect</b></div>
      </div>`,
  },
  {
    n: "Stage 4",
    tab: "Execution v2",
    role: "fixes what the review found",
    title: "703 → 439",
    tone: "ok",
    body: `
      <p>Execution took the finding, moved the remaining closed history into the archive, and re-landed the file at
         <b>439 lines</b>. The reviewer went again — and re-proved conservation on the additional 264 lines, from
         source, rather than accepting that the second attempt had been more careful than the first.</p>
      <p>Green. <b class="good">APPROVE</b>. The file it reads on every run is now under the ceiling it set for itself,
         and the number is one that survived being checked.</p>
      <div class="metric">
        <div class="mx">main file <span class="was">703</span> → <b class="now">439 lines</b></div>
        <div class="mx good">under the ceiling</div>
        <div class="mx">conservation re-proved <b class="good">byte-perfect</b></div>
        <div class="mx">total cut from <b>1,219 → 439</b></div>
      </div>`,
  },
  {
    n: "Stage 5",
    tab: "Ops",
    role: "records it — and asks a human",
    title: "Then it stops and waits for me",
    tone: "ok",
    body: `
      <p>Ops recorded the outcome and prepared the commit. And then the loop — which had just planned, built,
         reviewed, blocked, fixed and re-reviewed its own work without me — <b>stopped, and waited for a human to
         approve the commit.</b></p>
      <p>That's the part I care about most. The loop is trusted to <em>do</em> the work and to <em>catch</em> its own
         mistakes. It is not trusted to decide that something irreversible is fine. Every gate on the path to
         something you can't undo — a commit, a deploy — still has a person on it, on purpose.</p>
      <p><b>Reliability earns the loop more automation. It never earns it fewer gates.</b></p>
      <div class="metric">
        <div class="mx">arc <b class="good">closed</b></div>
        <div class="mx">commit <b>human-approved</b></div>
        <div class="mx">stages that ran unattended <b>4 of 5</b></div>
      </div>`,
  },
];

let i = 0;
const $ = (id) => document.getElementById(id);

function render() {
  $("steps").innerHTML = STAGES.map((s, k) =>
    `<button class="stab ${k === i ? "on" : ""} ${s.tone === "flag" ? "flag" : ""}" data-i="${k}">
       <span class="sn">${s.n}</span><span class="st">${s.tab}</span></button>`
  ).join("");
  const s = STAGES[i];
  $("stage").innerHTML =
    `<div class="stage ${s.tone}">
       <span class="role">${s.tab} — ${s.role}</span>
       <h2>${s.title}</h2>
       ${s.body}
     </div>`;
  $("prev").disabled = i === 0;
  $("next").disabled = i === STAGES.length - 1;
  $("next").textContent = i === STAGES.length - 2 ? "how it ends →" : "next stage →";
  document.querySelectorAll(".stab").forEach((b) =>
    b.addEventListener("click", () => { i = +b.dataset.i; render(); })
  );
}

$("prev").addEventListener("click", () => { if (i > 0) { i--; render(); } });
$("next").addEventListener("click", () => { if (i < STAGES.length - 1) { i++; render(); } });
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight" && i < STAGES.length - 1) { i++; render(); }
  if (e.key === "ArrowLeft" && i > 0) { i--; render(); }
});
render();
