# Environment Variables Reference

## Frontend Environment Variables (`apps/frontend/.env`)

| Variable | Description | Default |
| --- | --- | --- |
| `VITE_API_URL` | Base URL for REST API backend | `http://localhost:5000` |
| `VITE_WS_URL` | Base URL for WebSocket server | `ws://localhost:5000` |
| `NEXT_PUBLIC_API_URL` | Next.js public REST API backend | `http://localhost:5000` |
| `NEXT_PUBLIC_WS_URL` | Next.js public WebSocket backend | `ws://localhost:5000` |

## Backend Environment Variables (`apps/backend/.env`)

| Variable | Description | Default |
| --- | --- | --- |
| `PORT` | Backend HTTP & WebSocket port | `5000` |
| `NODE_ENV` | Environment mode (`development` / `production`) | `development` |
| `CRAWL_TIMEOUT` | Python HTTP request timeout (seconds) | `10` |
| `MAX_DEPTH` | Maximum BFS crawl depth cap | `2` |
| `HF_TOKEN` | HuggingFace Token for AI suggestions | `""` |
