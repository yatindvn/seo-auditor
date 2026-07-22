# SEO Auditor — Next.js Frontend + Python Serverless Backend

The Next.js (App Router, TypeScript, Tailwind CSS) frontend for the SEO Auditor,
plus a Vercel Python serverless function that runs the crawl.

## Architecture

- **Frontend** — Next.js app (`app/`, `components/`, `lib/`). The audit form POSTs to `/api/audit`.
- **Backend** — `api/audit.py`, a **Vercel Python serverless function**. It imports the
  `seo_auditor` package (in `seo_auditor/seo_auditor/`), runs the crawl + analysis
  in-memory via `collect_audit_data()`, and returns the full JSON report. No files are
  written to disk (serverless filesystems are read-only outside `/tmp`).
- The classic CLI (`python -m seo_auditor.cli ...`) still works and shares the exact same
  audit logic.

`/api/audit` is served by the Python function on Vercel — there is intentionally **no**
Next.js `app/api/audit` route (that would conflict, and the old version shell-executed
Python, which cannot run on Vercel's Node runtime).

## Local development

Because the backend is a Python serverless function, use the Vercel CLI locally so both
the Next.js frontend and the Python function run together:

```bash
npm install
pip install -r requirements.txt          # crawl deps for the Python function
npm i -g vercel                           # one-time
vercel dev                                # runs frontend + /api/audit together
```

Open the printed URL (usually http://localhost:3000).

> `npm run dev` alone runs only the Next.js frontend — the `/api/audit` Python function
> will not be available, so audits will fail. Use `vercel dev` to exercise the full stack.

## Deploying to Vercel

1. **Push this repo to GitHub** (already at `github.com/yatindvn/seo-auditor`).
2. In [vercel.com](https://vercel.com) → **Add New… → Project** → import the repo.
3. Vercel auto-detects **Next.js** and builds `api/audit.py` with the **Python** runtime
   (driven by `vercel.json` + the root `requirements.txt`). Leave the defaults.
4. Click **Deploy**. The frontend serves at your domain; audits hit `/api/audit`.

No environment variables are required. `SEO_AUDITOR_API_URL` is optional (see below).

### `vercel.json`

Configures the Python function:

```json
{
  "functions": {
    "api/audit.py": { "memory": 1024, "maxDuration": 60, "includeFiles": "seo_auditor/seo_auditor/**" }
  }
}
```

- `maxDuration: 60` — crawls of many pages are slow; 60s is the Hobby-plan ceiling.
  On the **Pro** plan you can raise this up to 300s for larger crawls.
- `includeFiles` — bundles the `seo_auditor` package source into the function.
- Crawls are capped at **15 pages / depth 2** to stay within the timeout.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SEO_AUDITOR_API_URL` | No | — | Optional external audit API URL. Not needed for the built-in Python function. |

## Tech Stack

- Next.js 14 App Router
- TypeScript
- Tailwind CSS (Apple design tokens)
- shadcn/ui primitives (hand-coded, no CLI needed)
- Recharts
- Lucide Icons
