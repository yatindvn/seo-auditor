# SEO Auditor - Monorepo Architecture

A modern, high-performance Technical SEO Auditor built with Next.js, Express, WebSocket, and Python BFS Crawling Engine organized as a clean monorepo.

---

## Workspace Layout

- `apps/frontend`: Next.js 14 Dashboard UI application.
- `apps/backend`: Express REST API + WebSocket Server wrapping the `seo_auditor` Python engine.
- `packages/shared`: Shared TypeScript types, schemas, DTO validations, and constants.
- `docs/`: Comprehensive architecture, API, WebSocket, and Environment variable documentation.
- `scripts/`: Monorepo development and build scripts.

---

## Available Scripts

In the root directory, you can run:

### `npm run dev`
Concurrently starts both frontend and backend development servers.

### `npm run dev:frontend`
Starts only the Next.js frontend application.

### `npm run dev:backend`
Starts only the Express + WebSocket backend server.

### `npm run build`
Builds all packages and applications in proper dependency order (`packages/shared` -> `apps/backend` -> `apps/frontend`).

### `npm run lint`
Runs linter checks across all packages.

### `npm run test`
Runs automated unit and integration tests.

---

## Documentation

- [Folder Structure](docs/folder-structure.md)
- [Architecture Overview](docs/architecture.md)
- [REST API Specification](docs/api.md)
- [WebSocket Events Specification](docs/websocket.md)
- [Environment Variables Guide](docs/env.md)
