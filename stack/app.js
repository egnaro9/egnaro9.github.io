// One button, four projects, one loop.
//
// Nothing here reimplements any of them. This page installs each project's own
// published wheel — the exact artifact its CI built — and calls them. The
// arrows on the diagram are function calls.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const WHEELS = {
  "rag-eval-lab": "https://egnaro9.github.io/rag-eval-lab/ragevallab-0.1.0-py3-none-any.whl",
  "llm-gateway": "https://egnaro9.github.io/llm-gateway/llmgateway-0.1.0-py3-none-any.whl",
  "agent-graph": "https://egnaro9.github.io/agent-graph/agentgraph-0.1.0-py3-none-any.whl",
};

let py = null;
const setStatus = (t, s) => { $("statusText").textContent = t; $("status").className = "status" + (s ? " " + s : ""); };
const lit = (id, on = true) => $(id)?.classList.toggle("lit", on);

function step(n, title, body, cls = "") {
  const el = document.createElement("div");
  el.className = "hop " + cls;
  el.innerHTML = `<div class="hopnum">${n}</div><div class="hopbody"><div class="hoptitle">${title}</div>${body}</div>`;
  $("flow").appendChild(el);
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return el;
}

async function boot() {
  try {
    setStatus("Booting Python (WebAssembly)…");
    py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/" });
    await py.loadPackage("micropip");
    const micropip = py.pyimport("micropip");

    setStatus("Installing LangGraph…");
    for (const p of ["langgraph", "langgraph-checkpoint", "langgraph-sdk", "langgraph-prebuilt"]) {
      await micropip.install.callKwargs(p, { deps: false });
    }
    await micropip.install(["langchain-core", "pydantic", "xxhash", "fastapi"]);

    for (const [name, url] of Object.entries(WHEELS)) {
      setStatus(`Installing ${name}'s published wheel…`);
      await micropip.install.callKwargs(url, { deps: false });
      lit(`chip-${name}`);
    }

    setStatus("Wiring the four together…");
    await py.runPythonAsync(`
import sys, types, json

class _Shim(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if name.startswith("OPT_"):
            return 1
        if name.endswith(("Error", "Exception", "OK", "Closed")) or name.startswith("Connection"):
            cls = type(name, (Exception,), {}); setattr(self, name, cls); return cls
        def _unavailable(*a, **k):
            raise NotImplementedError(f"{self.__name__}.{name} is not available in WebAssembly")
        return _unavailable

def _register(name, is_pkg=False):
    m = _Shim(name)
    if is_pkg: m.__path__ = []
    sys.modules.setdefault(name, m)

_register("ormsgpack")
for mod, pkg in [("websockets", True), ("websockets.sync", True), ("websockets.sync.client", False),
                 ("websockets.asyncio", True), ("websockets.asyncio.client", False),
                 ("websockets.exceptions", False), ("websockets.client", False), ("websockets.typing", False)]:
    _register(mod, pkg)

import anyio.to_thread
async def _inline(func, *a, **k): return func(*a)
anyio.to_thread.run_sync = _inline          # WASM has no threads

# ── the four projects, each from its own published wheel ──────────────────────
from ragevallab.data import SAMPLE_DOCS                 # rag-eval-lab
from ragevallab.evals import faithfulness, FAITHFULNESS_THRESHOLD, precision_at_k, recall_at_k
from llmgateway.app import Config as GwConfig, create_app as create_gateway   # llm-gateway
from agentgraph.graph import run as agent_run           # agent-graph
from agentgraph.rag import rag_policy, rag_tools
from agentgraph.gateway import GatewayPolicy

GATEWAY = create_gateway(GwConfig(api_keys=frozenset({"dev-key"}), rate_capacity=60))
TOOLS = rag_tools()                 # agent-graph's search IS rag-eval-lab's retriever
PLANNER = rag_policy()
GW = GatewayPolicy(transport=None, model="mock-1")

async def _asgi(method, path, body=None):
    payload = json.dumps(body).encode() if body else b""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "",
             "headers": [(b"content-type", b"application/json"), (b"authorization", b"Bearer dev-key")],
             "client": ("127.0.0.1", 0), "server": ("localhost", 80)}
    sent = False
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}
    msgs = []
    async def send(m): msgs.append(m)
    await GATEWAY(scope, receive, send)
    raw = b"".join(m.get("body", b"") for m in msgs if m["type"] == "http.response.body")
    return json.loads(raw)

CASES = [
    {"q": "Which planet is the hottest in the Solar System?", "gold": ["venus#0"]},
    {"q": "What is the tallest volcano in the Solar System?", "gold": ["mars#0"]},
    {"q": "Which planet is famous for its ring system?", "gold": ["saturn#0"]},
    {"q": "Who wrote Hamlet?", "gold": []},   # NOT in the corpus — retrieval must fail honestly
]

def corpus_json():
    return json.dumps(SAMPLE_DOCS)

async def run_case(i):
    """One question through all four projects."""
    case = CASES[i]
    q = case["q"]

    # 1+2. agent-graph runs, retrieving through rag-eval-lab's pipeline.
    state = agent_run(q, policy=PLANNER, tools_registry=TOOLS)
    search = TOOLS["search"]
    contexts, retrieved = list(search.last_contexts), list(search.last_retrieved)
    tools_used = [s["tool"] for s in state["steps"] if s["type"] == "action"]

    # 3. the agent's LLM call, through llm-gateway.
    obs = state.get("observations", [])
    gw = {}
    answer = state["answer"]
    if obs:
        gw = await _asgi("POST", "/v1/chat/completions", GW.build_request(q, obs))
        if "choices" in gw:
            answer = gw["choices"][0]["message"]["content"]

    # 4. rag-eval-lab grades the answer against what was actually retrieved.
    #    Score the agent's OWN words, not the mock's echo of the prompt.
    graded = state["answer"]
    f = faithfulness(graded, contexts) if contexts else 0.0
    p = precision_at_k(retrieved, case["gold"], 3) if case["gold"] else 0.0
    r = recall_at_k(retrieved, case["gold"], 3) if case["gold"] else 0.0

    return json.dumps({
        "q": q, "tools": tools_used, "retrieved": retrieved, "contexts": contexts,
        "agent_answer": graded, "gateway_answer": answer,
        "cached": bool(gw.get("cached")), "cost": float(gw.get("cost_usd", 0.0)),
        "faithfulness": round(f, 3), "precision": round(p, 3), "recall": round(r, 3),
        "flagged": f < FAITHFULNESS_THRESHOLD, "threshold": FAITHFULNESS_THRESHOLD,
        "in_corpus": bool(case["gold"]),
    })

async def gateway_metrics():
    return json.dumps(await _asgi("GET", "/metrics"))

def build_eval_run(cases_json):
    """The scored cases, in rag-eval-lab's eval_run.json schema."""
    cases = json.loads(cases_json)
    out = []
    for c in cases:
        out.append({
            "q": c["q"], "answer": c["agent_answer"],
            "retrieved": c["retrieved"], "citations": c["retrieved"][:1],
            "scores": {"precision@k": c["precision"], "recall@k": c["recall"],
                       "citation": 1.0 if c["retrieved"] else 0.0,
                       "faithfulness": c["faithfulness"]},
            "flagged": c["flagged"],
            "note": "" if c["in_corpus"] else "Not in the corpus — the retriever returned its closest chunk anyway.",
        })
    n = len(out)
    mean = lambda k: round(sum(x["scores"][k] for x in out) / n, 3) if n else 0.0
    return json.dumps({
        "run": "agent-graph via rag-eval-lab",
        "metrics": {"precision@k": mean("precision@k"), "recall@k": mean("recall@k"),
                    "citation_rate": mean("citation"), "faithfulness": mean("faithfulness"),
                    "flagged_cases": float(sum(1 for x in out if x["flagged"])), "n_cases": float(n)},
        "cases": out,
    })
`);

    setStatus("Ready — all four projects installed and wired in this tab", "ready");
    $("run").disabled = false;
    const docs = JSON.parse(await py.runPythonAsync("corpus_json()"));
    $("corpus").innerHTML =
      "<b>The corpus the agent retrieves from:</b><br>" +
      Object.entries(docs).map(([k, v]) => `<span class="cid">${esc(k)}#0</span> ${esc(v)}`).join("<br>");
  } catch (err) {
    setStatus("Failed to boot: " + err, "err");
    console.error(err);
  }
}

const tone = (v) => (v >= 0.9 ? "good" : v >= 0.6 ? "warn" : "bad");
const pct = (v) => (v * 100).toFixed(0) + "%";

async function runStack() {
  const btn = $("run");
  btn.disabled = true;
  btn.textContent = "running…";
  $("flow").innerHTML = "";
  $("finale").innerHTML = "";
  const results = [];

  for (let i = 0; i < 4; i++) {
    const c = JSON.parse(await py.runPythonAsync(`await run_case(${i})`));
    results.push(c);

    step(1, `<span class="proj a">agent-graph</span> gets a question`,
      `<div class="q">“${esc(c.q)}”</div>`, "a");
    await sleep(320);

    step(2, `<span class="proj a">agent-graph</span> → <span class="proj r">rag-eval-lab</span> · retrieve`,
      `<div class="mono">tools: ${c.tools.join(" → ") || "none"}</div>
       <div class="mono ids">${c.retrieved.join(", ") || "—"}</div>
       <div class="ctx">${esc((c.contexts[0] || "").slice(0, 110))}${(c.contexts[0] || "").length > 110 ? "…" : ""}</div>
       ${!c.in_corpus ? `<div class="warnline">Not in the corpus — a real retriever returns its closest chunk anyway rather than admitting defeat. Watch step 4.</div>` : ""}`, "r");
    await sleep(320);

    step(3, `<span class="proj a">agent-graph</span> → <span class="proj g">llm-gateway</span> · compose`,
      `<div class="mono">cached=<b class="${c.cached ? "good" : ""}">${c.cached}</b> · cost $${c.cost}
       ${c.cached ? `<span class="good">← served from cache, provider untouched</span>` : ""}</div>`, "g");
    await sleep(320);

    // Grounded-but-wrong: faithful to a chunk that shouldn't have been retrieved.
    const groundedButWrong = !c.in_corpus && c.faithfulness >= c.threshold;
    step(4, `<span class="proj r">rag-eval-lab</span> grades the answer`,
      `<div class="mono">faithfulness <b class="${tone(c.faithfulness)}">${pct(c.faithfulness)}</b>
        · precision@k <b class="${c.in_corpus ? "" : "bad"}">${pct(c.precision)}</b> · threshold ${c.threshold}</div>
       <div class="verdictline ${groundedButWrong ? "warn" : c.flagged ? "bad" : "good"}">${
        groundedButWrong
          ? "⚠ perfectly faithful — and completely wrong"
          : c.flagged
          ? "🚩 flagged — the answer isn't grounded in what was retrieved"
          : "✓ grounded in the retrieved context"}</div>
       ${groundedButWrong ? `<div class="warnline">This is the honest lesson. <b>Faithfulness measures grounding, not correctness.</b> The agent answered from the chunk it was handed, so it's 100% faithful — to a document about Mercury. <b>precision@k = 0%</b> is what exposes it. One metric alone would have called this a pass; that's why you measure retrieval and grounding separately.</div>` : ""}`,
      groundedButWrong ? "bad" : c.flagged ? "bad" : "r");
    await sleep(420);
  }

  // 5. produce the artifact + hand it to the dashboard.
  const evalRun = JSON.parse(await py.runPythonAsync(`build_eval_run(${JSON.stringify(JSON.stringify(results))})`));
  const m = await py.runPythonAsync("await gateway_metrics()").then(JSON.parse);
  localStorage.setItem("ragevallab:eval_run", JSON.stringify(evalRun));

  step(5, `<span class="proj r">rag-eval-lab</span> → <span class="proj d">eval-dashboard</span> · the artifact`,
    `<div class="mono">wrote <b>eval_run.json</b> — ${evalRun.metrics.n_cases} cases ·
      ${evalRun.metrics.flagged_cases} flagged · mean faithfulness ${pct(evalRun.metrics.faithfulness)}</div>`, "d");

  $("finale").innerHTML = `
    <div class="cards">
      <div class="card"><div class="k">Cases run</div><div class="v">${evalRun.metrics.n_cases}</div></div>
      <div class="card"><div class="k">Flagged</div><div class="v ${evalRun.metrics.flagged_cases ? "bad" : "good"}">${evalRun.metrics.flagged_cases}</div></div>
      <div class="card"><div class="k">Faithfulness</div><div class="v ${tone(evalRun.metrics.faithfulness)}">${pct(evalRun.metrics.faithfulness)}</div></div>
      <div class="card"><div class="k">Gateway calls</div><div class="v">${m.requests}</div></div>
      <div class="card"><div class="k">Cache hits</div><div class="v good">${m.cache_hits}</div></div>
      <div class="card"><div class="k">Spend</div><div class="v">$${m.total_cost_usd}</div></div>
    </div>
    <a class="handoff-btn" href="https://egnaro9.github.io/eval-dashboard/?from=rag-eval-lab" target="_blank" rel="noopener">
      Open this run in eval-dashboard →</a>
    <div class="handoff-note">That button hands the <b>eval_run.json you just produced</b> to the fourth project. Four repos, one loop — and every arrow above was a function call, not a diagram.
      ${m.cache_hits > 0 ? `<br><br>Note the <b>${m.cache_hits} cache hits</b>: you ran it twice, so the gateway served the agent's LLM calls without touching the provider.` : `<br><br>Run it again — the gateway will serve every one of those LLM calls from cache the second time.`}</div>`;
  $("finale").scrollIntoView({ block: "nearest", behavior: "smooth" });

  btn.disabled = false;
  btn.textContent = "▶ Run it again";
}

$("run").addEventListener("click", runStack);
boot();
