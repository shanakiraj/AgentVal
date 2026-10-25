# AgentVal — Agent Validation & Evaluation Studio

AgentVal is an open-source, developer-first workspace and evaluation engine for benchmarking,
evaluating and stress-testing **multi-step AI agents**, LLM tool use and decision-making workflows.
It pairs an asynchronous evaluation pipeline (Python) with an interactive trace/diff studio (Next.js).

- **Modular scorers**: exact/structural match, JSON-schema / Pydantic validation, LLM-as-judge rubrics, tool-trajectory efficiency, plus your own via a registry.
- **Async runner**: `asyncio.gather` + `Semaphore` concurrency, per-case timeouts, retries with exponential backoff + jitter, per-step latency/token/cost capture.
- **Traces**: OpenTelemetry-style spans for every input, LLM call, tool call, output and error, rendered as a React Flow graph.
- **Compare**: run-vs-run metric deltas and per-test-case regressions.
- **Works offline**: a deterministic mock customer-service agent and mock judge mean the whole demo runs with **no API keys**. Real models go through [LiteLLM](https://github.com/BerriAI/litellm) (OpenAI, Anthropic, Gemini, Ollama, …).

## Quick start

### Option A: Docker (one command)

```bash
cp .env.example .env        # optional; defaults work for local dev
docker compose up --build
```
With `AGENTVAL_SEED=true` (default in compose) the API loads the sample dataset and runs it twice
(baseline vs. improved mock agent) on first start, so the dashboard and compare view have data immediately.

### Option B: Local development

Backend (Python 3.11+):

```bash
cd packages/core-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                   # scorers, runner, API, CLI
agentval seed                               # sample dataset + two demo runs into ./agentval.db
agentval serve --reload                     
```

Frontend (Node 20+):

```bash
cd apps/web
npm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev
```

The database defaults to SQLite (`sqlite:///./agentval.db`). Set `DATABASE_URL` to any Postgres URL
(`postgresql://…`, Neon and Supabase URLs work) to use Postgres; tables are created on startup.

## CLI

```bash
agentval run --dataset <path|dataset-id|sample> --config <config.json|mock-baseline|mock-improved|litellm-openai>
```

```
$ agentval run --dataset sample --config mock-baseline
Running 'v1.0 baseline prompt + mock/cs-agent-v1' on 'Customer Service Agent Evaluation' (5 cases) -> run 4406dbe0-…
Test case                            Status    Score   Latency Tries
--------------------------------------------------------------------
Order status lookup                  PASS      0.965    1151ms     1
Refund for damaged item              PASS      0.900     492ms     1
Password reset                       PASS      0.955     661ms     1
Address change after shipment        FAIL      0.230     724ms     1
Angry customer escalation            PARTIAL   0.800     633ms     1
--------------------------------------------------------------------
  pass rate     60%  (3 pass / 1 partial / 1 fail / 0 error)
  avg score     0.770
  avg latency   732 ms   (p95 1151 ms)
  total cost    $0.000357   tokens 1836
  scorers       exact_match=0.800, llm_judge=0.700, schema_match=1.000, trajectory=0.650
```

Useful flags: `--db <url>`, `--no-persist` (in-memory, no DB), `--output results.json` (full results
incl. traces), `--concurrency N`, `--name`. Other commands: `agentval seed`, `agentval serve`,
`agentval export-demo -o apps/web/src/lib/demo-data.json`.

### Run config (`--config`, or `config` in `POST /api/v1/evals/run`)

```json
{
  "name": "v1.2 improved prompt + mock/cs-agent-v2",
  "agent": { "type": "mock", "variant": "improved", "model": "mock/cs-agent-v2" },
  "scorers": [
    { "type": "exact_match", "params": { "field": "resolution" } },
    { "type": "schema_match" },
    { "type": "llm_judge", "weight": 2, "params": { "model": "mock", "rubric": "…" } },
    { "type": "trajectory" }
  ],
  "concurrency": 4,
  "max_retries": 2,
  "retry_base_delay": 0.5,
  "retry_max_delay": 8,
  "timeout_s": 120,
  "pass_threshold": 0.85,
  "partial_threshold": 0.4
}
```

- `agent.type`: `mock` (no keys), `litellm` (any LiteLLM model id, e.g. `gpt-4o-mini`,
  `anthropic/claude-3-5-sonnet-20240620`, `ollama/llama3`), or `your.module:YourAgent` (subclass of `agentval.agents.Agent`).
- Status per case: **PASS** if weighted score ≥ `pass_threshold`, **PARTIAL** if ≥ `partial_threshold`, **FAIL** otherwise, **ERROR** if the agent failed after all retries.

### Free OpenRouter models

`packages/core-python/agentval/sample_data/configs/openrouter-*.json` run the sample dataset against
free OpenRouter models through LiteLLM (`openrouter/<model-id>:free`), using a store-policy system
prompt and the shared customer-service tool sandbox (the same simulated backend the mock agent uses).
The LLM judge for these runs is `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` for every model
(the two mock runs keep the offline mock judge). The bundled demo data includes real results for
Poolside Laguna S 2.1, Cohere North Mini Code and NVIDIA Nemotron 3.5 Super VL. `max_steps` budgets in the
sample dataset count every LLM turn, including the final answer, so real tool-calling agents are not penalized.

```bash
export OPENROUTER_API_KEY=...   # read by LiteLLM from the environment; never stored by AgentVal
agentval run --dataset sample --config openrouter-nvidia-nemotron-super-vl
```

Free models are rate limited (about 20 requests/min and upstream throttling), so these configs use
`concurrency: 1`. Rate-limit errors are retried per model call with exponential backoff, and then
per test case by the runner. Cost is reported as $0 for `:free` models. If the judge is unavailable
after its retries, `llm_judge` is marked *skipped* for that case instead of scoring 0. Free-model
availability changes often: list the current ones with
`curl -s https://openrouter.ai/api/v1/models | jq -r '.data[] | select(.id | endswith(":free")) | .id'`.

### Dataset format

```json
{
  "name": "Customer Service Agent Evaluation",
  "description": "…",
  "testCases": [
    {
      "name": "Refund for damaged item",
      "input": { "prompt": "My order B2002 arrived damaged…", "context": { "orders": { "…": {} } }, "tools": ["lookup_order", "issue_refund"] },
      "expected": {
        "resolution": "resolved",
        "reply_contains": ["refund", "49.99"],
        "reply_must_not_contain": ["calm down"],
        "tool_calls": [{ "name": "lookup_order", "args": { "order_id": "B2002" } }, { "name": "issue_refund" }],
        "max_steps": 3,
        "schema": { "type": "object", "required": ["reply", "resolution"] }
      },
      "metadata": { "category": "refund", "difficulty": "medium" }
    }
  ]
}
```

## Scorers

| Type | What it measures | Key params |
| --- | --- | --- |
| `exact_match` | Exact, normalized (case/whitespace) or JSON-structural equality of the output or a field | `field`, `expected_field`, `mode` |
| `schema_match` | Output validates against a JSON Schema (inline or `expected.schema`) or a Pydantic model | `schema`, `model`, `field` |
| `llm_judge` | Rubric-based judge via LiteLLM returning `{score, rationale}`; `model: "mock"` uses an offline keyword-coverage judge | `model`, `rubric`, `temperature` |
| `trajectory` | Tool-use quality: recall/precision/order of expected calls, invalid invocations, step budget | `weights`, `available_tools`, `max_steps` |

Custom scorers:

```python
from agentval.scorers import Scorer, register_scorer

@register_scorer("toxicity")
class ToxicityScorer(Scorer):
    def score(self, ctx):            # may also be async
        bad = "idiot" in str(ctx.actual).lower()
        return self.result(0.0 if bad else 1.0, "toxic language" if bad else "clean")
```

Reference it as `{"type": "toxicity"}` once imported, or by path: `{"type": "my_pkg.scorers:ToxicityScorer"}`.

## REST API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/datasets` | List datasets (with test-case and run counts) |
| `POST` | `/api/v1/datasets` | Create a dataset, optionally with `testCases` |
| `GET` / `DELETE` | `/api/v1/datasets/{id}` | Dataset with its test cases / delete |
| `POST` | `/api/v1/datasets/{id}/testcases` | Add one test case (object) or many (array) |
| `DELETE` | `/api/v1/datasets/{id}/testcases/{tcId}` | Delete a test case |
| `POST` | `/api/v1/evals/run` | `{datasetId, name?, config}` — starts a run asynchronously (202) |
| `GET` | `/api/v1/evals/runs` | List runs (`?datasetId=`) |
| `GET` | `/api/v1/evals/runs/{id}` | Progress, metrics and results with traces (`?includeTraces=false`) |
| `GET` | `/api/v1/evals/runs/{id}/stream` | Server-Sent Events progress stream (`progress` … `done`) |
| `GET` | `/api/v1/evals/runs/{id}/results/{resultId}` | One result with full trace |
| `GET` | `/api/v1/evals/compare?runA=&runB=` | Metric, scorer and per-case deltas |
| `GET` | `/api/v1/evals/scorers` | Registered scorer types |

Run metrics: `passRate`, `avgScore`, `avgLatencyMs`, `p50LatencyMs`, `p95LatencyMs`, `totalCostUsd`,
`promptTokens`, `completionTokens`, `tokenCount`, `totalRetries`, `scorerAverages`, `durationMs`, counts.

Traces (`agentval.trace.v1`) store `traceId` and steps with OpenTelemetry-compatible span fields
(`id`, `parentId`, `startTimeUnixNano`, `endTimeUnixNano`, `attributes` such as `gen_ai.request.model`)
plus `type` (`input`/`llm`/`tool_call`/`output`/`error`), `input`, `output`, `status`, `latencyMs`, `tokens`, `costUsd`,
the message history and any retry attempts.

## Studio pages

| Route | What it shows |
| --- | --- |
| `/datasets`, `/datasets/[id]` | Manage datasets and test cases (create/import JSON, add/delete cases), start runs |
| `/runs` | All runs: pass rate, avg score, latency, cost, tokens, plus a per-model comparison |
| `/runs/[id]` | Metric cards, scorer breakdown, per-test-case table with Pass/Partial/Fail badges; live progress while running |
| `/runs/[id]/trace/[resultId]` | React Flow trajectory graph (inputs, LLM calls, tool calls, outputs, errors), step inspector, scores and actual vs expected |
| `/compare` | Multi-run leaderboard + test-case × run matrix (pick any runs with `?runs=`), and an A/B diff (`?a=&b=`) with colored metric deltas and per-case regressions |

## Deploying the web app to Vercel

The studio deploys to Vercel on its own. Until a backend is hosted, it serves the bundled demo data
(sample dataset + two runs) in read-only mode, so every page works.

1. In Vercel, **Add New → Project** and import `shanakiraj/AgentVal`.
2. Set **Root Directory** to `apps/web`. Framework preset: Next.js (auto-detected). Build command `npm run build`, install command `npm install` (defaults).
3. Environment variables (Project Settings → Environment Variables):
   - `NEXT_PUBLIC_API_URL` — public URL of the FastAPI backend, e.g. `https://agentval-api.example.com`. **Leave unset** to run in demo mode.
   - `NEXT_PUBLIC_DEMO_MODE` — optional, `true` forces read-only demo data even when an API URL is set.
   - Do not put model provider keys in the web project; they belong to the API.
4. Deploy. `NEXT_PUBLIC_*` values are inlined at build time, so redeploy after changing them.

When you host the API later (any container host: Fly.io, Render, Railway, Cloud Run…), use
`packages/core-python/Dockerfile`, point `DATABASE_URL` at Postgres (Neon/Supabase work), add the
Vercel domain to `CORS_ORIGINS` (only needed for direct browser access; the studio itself calls the
API server-side), then set `NEXT_PUBLIC_API_URL` in Vercel and redeploy.

Note: run progress in the studio refreshes by polling; the API also exposes an SSE stream for other clients.

## Testing

```bash
cd packages/core-python && pytest -q          # scorers, runner, LiteLLM agent (faked), API (SQLite), CLI
AGENTVAL_TEST_DATABASE_URL=postgresql://… pytest -q   # same suite against Postgres
cd apps/web && npm run typecheck && npm run lint && npm run build
```

## License

MIT
