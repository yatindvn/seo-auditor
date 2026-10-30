# Phase 7.1: AI Visibility — Design

**Date:** 2026-10-30
**Status:** Approved, pending implementation plan
**Branch:** `feat/ai-visibility`
**Brief:** `BUILD_PROMPT.md` Phase 7: "AI Visibility: user-defined prompts
sent to Claude/OpenAI/Gemini APIs; record whether the brand is mentioned,
position, and cited sources; track over time." (7.2 Content Explorer is a
separate sub-project.)

## Problem

People increasingly ask AI assistants instead of searching. The platform
can't tell whether a brand shows up in those answers, where it ranks against
competitors, or whether its site is cited. `ai_visibility_runs` exists
(Phase 1) but is unused.

## Decisions taken

- **Web search on:** each model answers with its own web-search tool, so
  answers resemble AI search, with real citations. Each call costs about
  $0.02–0.05.
- **Text matching** for detection: deterministic, free and testable.
- **Weekly runs are opt-in per project** (off by default), plus "Run now".
  There's a hard daily cap and a dry run without keys, and the owner OKs
  the first real call to each provider. No AI keys are configured today.

## Design

### 1. Providers: `app/ai_visibility/providers.py`

```python
@dataclass
class Answer:
    text: str = ""
    citations: List[Dict[str, str]] = field(default_factory=list)   # {url, title}
    model: str = ""
    error: Optional[str] = None

class AiProvider(Protocol):
    name: str            # "claude" | "openai" | "gemini" | "dry_run"
    model: str
    dry_run: bool
    def ask(self, prompt: str) -> Answer
```

| Provider | Request (`requests`, 60 s timeout) | Text / citations |
| --- | --- | --- |
| `ClaudeProvider(key, model)` | `POST https://api.anthropic.com/v1/messages`, headers `x-api-key`, `anthropic-version: 2023-06-01`; body `{model, max_tokens: 1024, messages: [{role: user, content: prompt}], tools: [{type: ANTHROPIC_WEB_SEARCH_TOOL, name: "web_search", max_uses: 3}]}` | text = joined `content[].text` of `type == "text"` blocks; citations = each text block's `citations[]` `{url, title}`, plus `web_search_tool_result` `content[].url/title`, deduplicated by URL |
| `OpenAIProvider(key, model)` | `POST https://api.openai.com/v1/responses`, `Authorization: Bearer`; body `{model, input: prompt, tools: [{type: OPENAI_WEB_SEARCH_TOOL}]}` | text = `output[]` of type `message` → `content[]` of type `output_text` `.text`; citations = their `annotations[]` of type `url_citation` `{url, title}` |
| `GeminiProvider(key, model)` | `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, header `x-goog-api-key`; body `{contents: [{parts: [{text: prompt}]}], tools: [{google_search: {}}]}` | text = `candidates[0].content.parts[].text`; citations = `candidates[0].groundingMetadata.groundingChunks[].web` `{uri → url, title}` (grounding URIs are redirects, and the title carries the domain) |

- **Config:**
  - keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
  - models: `ANTHROPIC_MODEL` (default `claude-sonnet-5`), `OPENAI_MODEL` and `GEMINI_MODEL` (no default: a provider without its model set is skipped and the UI says so)
  - tool names: `ANTHROPIC_WEB_SEARCH_TOOL` (default `web_search_20250305`), `OPENAI_WEB_SEARCH_TOOL` (default `web_search`)
  - `AI_VISIBILITY_DRY_RUN`, `AI_VISIBILITY_DAILY_CAP` (default 30)
- **Errors:** a non-2xx response gives `Answer(error="{provider} HTTP {status}: {message}")`. A network failure gives the error type only. Keys never appear in errors or logs.
- **The cap:** each `ask` first calls `spend.reserve("ai_visibility", AI_VISIBILITY_DAILY_CAP)`. A cap hit gives `Answer(error=...)` without a call.
- **`DryRunAI(name)`:** deterministic answers (seeded by prompt + name) that name some of the given brands in varying order, with 2–4 citations, some on the project's domain. `dry_run=True`. The run passes it the brand list through `brands_hint`.
- **`configured_providers(cfg)`:**
  - `AI_VISIBILITY_DRY_RUN` or no key at all → `[DryRunAI("claude"), DryRunAI("openai"), DryRunAI("gemini")]`
  - otherwise, the providers whose key (and model) are set

### 2. Detection: `app/ai_visibility/detect.py` (pure)

```python
@dataclass(frozen=True)
class Brand:  owner: str (the project domain or a competitor domain); is_self: bool; terms: Tuple[str, ...]; domain: str

first_index(text, brand) -> Optional[int]     # earliest match of any term (whole word, case-insensitive) or domain/www.domain
analyze(text, citations, brands) -> {mentioned, position, brands_mentioned: [owner…], cited, cited_domains: [domain…]}
```

- **Terms** are matched with `re.escape` inside `(?<![\w-])…(?![\w-])`,
  case-insensitive. Empty terms are ignored. The domain counts as a term.
- **Order and position:**
  - `brands_mentioned` = brands with a match, ordered by first index
  - `position` = the 1-based index of the self brand in that list, or `None`
- **Citations:**
  - A citation's domain is `hostname` without `www.`.
  - **Grounding redirects:** when the host is `vertexaisearch.cloud.google.com`
    (or any `*.googleusercontent.com` / `grounding-api-redirect` path), the
    domain is taken from the citation `title` when it looks like a domain.
  - `cited` is true when any citation domain equals the self domain or is a
    subdomain of it.
  - `cited_domains` lists the unique domains in order.
- **Share of voice** for a run: the fraction of answers (without errors)
  that mention each brand.

### 3. Storage (migration `0010_ai_visibility`)

- **`ai_prompts`:** `id, project_id (FK cascade, indexed), text (Text ≤ 300), enabled (bool, default true), created_at`.
- **`ai_brand_terms`:** `id, project_id (FK cascade, indexed), owner (string 255: the project domain or a competitor domain), term (string 100)`, unique on `(project_id, owner, term)`.
- **`ai_runs`:** `id, project_id (FK cascade, indexed), started_at, finished_at, trigger (manual|scheduled), dry_run, calls, errors`.
- **`ai_visibility_runs` gains:** `run_id (FK ai_runs cascade, indexed, nullable)`, `prompt_id (nullable)`, `model (string 64)`, `answer (Text, ≤ 8000 chars)`, `mentioned (bool)`, `position (int, nullable)`, `brands_json (JSON list)`, `cited (bool)`, `citations_json (JSON list)`, `error (Text, nullable)`, `dry_run (bool)`. The existing `ran_at`, `provider`, `prompt` and `result_json` stay.
- **`projects` gains:** `ai_schedule (string 16, nullable)` and `last_ai_run_at`.

### 4. Running: `app/ai_visibility/run.py`

`run_project(project_id, providers=None, trigger="manual") -> dict`:

- It loads the enabled prompts. With no prompts it returns
  `{status: "no_prompts"}`.
- **Brands:** the self brand comes from the project's domain plus its
  `ai_brand_terms` owned by the project domain (and the project `name`). A
  competitor brand comes from each `Competitor` domain plus its terms.
- **Calls:** an `ai_runs` row is created, then `ask` runs for every
  prompt × provider in a 3-thread pool. `DryRunAI` gets the brand names for
  realistic text.
- **Each answer:** `analyze`, then one row is stored per answer (the answer
  trimmed to 8,000 chars).
- **The run row** gets `finished_at`, `calls`, `errors` and `dry_run` (true
  if any provider is dry run), and `last_ai_run_at` is set.
- **Returns** `{status: "ran", run_id, calls, errors, dry_run, mention_rate}`.
- Never raises for per-call failures. A provider's error is that row's
  `error`.
- **Scheduler:** `run_due_ai_visibility(now)`, every 6 h, for projects with
  `ai_schedule == "weekly"` and a last run older than 7 days, using
  `claim()`. **It skips when every configured provider is a dry run.**

### 5. API: `app/api/ai_visibility.py`

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/projects/{id}/ai-visibility` | `{providers: [{name, model, dry_run}], dry_run, schedule, last_run_at, latest, previous, trend, share_of_voice, top_cited}` |
| GET / POST | `/api/projects/{id}/ai-visibility/prompts` | list / add `{text}` (1–300 chars; 409 beyond 25) |
| PATCH / DELETE | `/api/ai-prompts/{id}` | `{enabled?, text?}` / 204 |
| GET / PUT | `/api/projects/{id}/ai-visibility/brands` | `{self: {domain, terms}, competitors: [{domain, terms}]}`. PUT replaces the terms for the owners given (each term 1–100 chars, at most 10 per owner) |
| POST | `/api/projects/{id}/ai-visibility/run` | the run result |
| GET | `/api/projects/{id}/ai-visibility/answers?run_id&provider&prompt_id&limit&offset` | answers with highlights (default: latest run) |

- **`latest` / `previous`** (per run): `{run_id, started_at, dry_run,
  calls, errors, mention_rate, avg_position, cited_rate, by_provider:
  {name: {mention_rate, avg_position, cited_rate}}}`. Rates exclude error
  rows.
- **`trend`:** the last 20 runs, oldest first,
  `[{run_id, started_at, mention_rate, by_provider: {name: mention_rate}}]`.
- **`share_of_voice`** (latest run): `[{owner, is_self, rate}]`, sorted.
- **`top_cited`** (latest run): `[{domain, count, is_self}]`, top 10.
- **Answer items:** `{id, prompt, provider, model, mentioned, position,
  brands, cited, citations, error, answer, highlights: [{start, end,
  owner}]}`. Highlights are computed server-side with `detect`.
- `PATCH /api/projects/{id}` accepts `ai_schedule: "weekly" | null`.

### 6. UI: the "AI Visibility" tab (`/projects/[id]/ai-visibility`)

- **Setup:**
  - brand terms: your domain plus aliases (chips with add and remove), and
    each competitor with aliases
  - prompts: list with enable, delete and add (25 max)
- **Run controls:**
  - Run now, with the estimate "≈ $X: N prompts × M models × ~$0.03"
  - Weekly switch
  - the configured models, each with a dry-run badge, and "Not configured"
    hints for missing keys or models
- **KPI tiles:** mention rate, average position (lower is better) and cited
  rate, each with the change vs the previous run.
- **Charts:**
  - **Trend:** mention rate per run, one series per model, with a legend
    and a table view, never a dual axis.
  - **Share of voice:** horizontal bars (you first, in the series colour,
    competitors after), with a table view.
- **Top cited domains:** your domain is marked.
- **Answers table:** prompt × model, with a mentioned pill (icon + text),
  position "2nd of 4", and a cited pill.
  - **Expanding a row** shows the answer with highlights. The answer is
    split into text segments at the server's highlight ranges and rendered
    as text nodes inside `<mark>` elements, never as HTML.
  - Citations are shown as links (http/https only, `target=_blank
    rel="noopener noreferrer"`).
- A dry-run banner shows whenever the run or the providers are dry run.

## Error handling

| Case | Result |
| --- | --- |
| No keys | dry-run providers, banner, the weekly job never runs |
| A key but no model (OpenAI/Gemini) | provider skipped, UI hint "set OPENAI_MODEL" |
| Provider HTTP error or timeout | that answer's `error`, the run continues, the error count rises |
| Cap reached | remaining calls get `error="daily cap of N ai_visibility calls reached"`, no call made |
| No prompts | run returns `no_prompts`, UI asks for prompts |
| 26th prompt / 11th term | 409 / 422 |

## Testing

- **Providers:** with HTTP mocked: each request (URL, headers with the key,
  body with the tool) and each response parsed from recorded samples
  (text + citations). A non-2xx response or timeout becomes `error`. The
  cap means no call, the key never appears in errors, the dry run is
  deterministic, and `configured_providers` covers its modes.
- **Detection:**
  - whole-word matching (no "Bookstore" inside "Bookstores"; hyphens)
  - aliases, case, domain and www
  - ordering and position
  - absent brands
  - citation domains (www stripping, subdomains, Gemini redirect + title)
- **Run:** every prompt × provider, the stored rows, a failure isolated,
  `no_prompts`, the cap, the answer trimmed, the run counts.
- **Scheduler:** weekly opt-in, older than 7 days, all-dry-run skipped.
- **API:** prompts CRUD and caps, brands GET/PUT and validation, run, the
  latest/previous/trend/share/top_cited math, answers with highlights and
  filters, and the PATCH schedule.
- **Frontend:**
  - setup (terms, prompts)
  - run and its estimate
  - KPIs with changes (position lower is better)
  - chart table views
  - an answer expanded with `<mark>` highlights and safe links
  - states (empty, dry run, not configured)
- **Live check:** dry run end to end, UI at 1440 and 390 px. Real calls to
  each provider only after the owner adds a key and says go.

## Done when

A project's prompts are asked of Claude, OpenAI and Gemini (or dry run). Each
answer records the mention, position, citations and cited status. The tab
shows KPIs, trends, share of voice, top cited domains and every answer.
Runs are manual or weekly by opt-in, capped, with keys kept safe. Docs, env
and tests are updated.

## Out of scope

- Sentiment, AI-judged ranking, other models (Perplexity, Copilot),
  per-country prompts, and alerting on visibility drops.
