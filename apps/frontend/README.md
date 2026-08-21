# SEO Auditor — Next.js Frontend

The Next.js (App Router, TypeScript, Tailwind CSS) dashboard for the SEO Auditor.

## Architecture

- **Frontend** — this package. `app/`, `components/`, `lib/`, `services/`.
- **Backend** — a separate FastAPI service in `apps/backend`, run as a persistent
  process. It is *not* serverless and cannot be: a crawl runs for minutes, live
  progress is streamed over a WebSocket, and session state, the crawler registry
  and the rank cache all live in process memory.
- **Shared types** — `packages/shared`, describing the JSON the backend emits.

The dashboard talks to the backend directly over REST and a WebSocket
(`services/api.ts`). The two routes under `app/api/` are thin extras, not the
backend: `/api/health` answers a liveness probe, and `/api/audit` proxies to the
backend when `NEXT_PUBLIC_API_URL` is set.

## Local development

From the **repository root**, which starts the frontend and the Python backend
together:

```bash
npm install
python -m pip install -r apps/backend/requirements.txt
npm run dev
```

- Frontend: http://localhost:3000
- Backend: http://localhost:5000

Running `npm run dev` inside this directory starts only the frontend; audits then
fail, because nothing is serving the API on port 5000.

## Environment variables

Not needed locally — the defaults in `services/api.ts` point at
`http://127.0.0.1:5000` and `ws://localhost:5000/ws`. Required for any deployment
where the backend is on another host:

| Variable | Example | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://api.example.com` | Backend base URL |
| `NEXT_PUBLIC_WS_URL` | `wss://api.example.com/ws` | **`wss://`, not `ws://`** |

An HTTPS page cannot open a plaintext WebSocket — the browser blocks it as mixed
content, and live crawl progress silently never arrives while the rest of the
dashboard keeps working. That failure gives no console error users would notice.

## Deployment

The frontend deploys to Vercel from the repository root; the root `vercel.json`
pins the framework and build settings, and `.vercelignore` keeps the Python
sources out of the upload. Set the two variables above in the Vercel project, or
every audit fails against the visitor's own machine.

The backend needs a host that supports long-running processes — see
`docs/deployment-oracle.md`.

## Tech stack

- Next.js 14 App Router
- TypeScript
- Tailwind CSS
- shadcn/ui primitives (hand-coded)
- Recharts
- Lucide icons
- Vitest + React Testing Library
