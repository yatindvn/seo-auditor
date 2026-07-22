# SEO Auditor — Next.js Frontend

This directory contains the Next.js (App Router, TypeScript, Tailwind CSS) frontend for the SEO Auditor tool.

## Development

```bash
# Install dependencies
npm install

# Start dev server (frontend + API route to Python backend)
npm run dev
```

Open http://localhost:3000 in your browser.

## Architecture

The frontend calls its own Next.js API route (`/api/audit`) which:
1. First tries to proxy to an external FastAPI backend (if `SEO_AUDITOR_API_URL` is set)
2. Falls back to running `python -m seo_auditor.cli` directly

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SEO_AUDITOR_API_URL` | `http://127.0.0.1:8000/api/audit` | External FastAPI URL to proxy audit requests to |

## Tech Stack

- Next.js 14 App Router
- TypeScript
- Tailwind CSS (Apple design tokens)
- shadcn/ui primitives (hand-coded, no CLI needed)
- Recharts
- Lucide Icons
