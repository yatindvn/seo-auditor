# Folder Structure Documentation

```text
SiteCrawler/
│
├── apps/
│   ├── frontend/
│   │   ├── app/                # Next.js App Router (Landing, Dashboard, API proxy)
│   │   ├── components/         # UI components (Health Gauge, Tables, Issue Charts)
│   │   ├── lib/                # React Context and shared helper utilities
│   │   ├── services/           # ApiService abstraction layer (HTTP + WebSocket)
│   │   ├── public/             # Static assets
│   │   ├── package.json        # Frontend manifest
│   │   └── next.config.mjs     # Next.js build configuration
│   │
│   └── backend/
│       ├── src/
│       │   ├── crawler/        # CrawlEngine bridge runner
│       │   ├── websocket/      # WebSocket Server implementation
│       │   ├── routes/         # Express REST routes (/api/audit, /api/health)
│       │   ├── controllers/    # Controller request handlers
│       │   ├── services/       # AuditService, AiService
│       │   ├── middleware/     # Error handler and request loggers
│       │   ├── models/         # SessionModel storage
│       │   ├── utils/          # Python process runner
│       │   ├── ai/             # AI suggestions bridge
│       │   └── server.ts       # Express + HTTP + WS entry point
│       ├── app/                # Core Python BFS crawler & SEO analysis engine (also `python -m app.cli`)
│       ├── package.json        # Backend manifest
│       └── tsconfig.json       # Backend TypeScript config
│
├── packages/
│   └── shared/
│       ├── src/
│       │   ├── types/          # CrawlResult, PageItem, ExecutiveSummary, HealthScore
│       │   ├── constants/      # Status codes, default configs, event names
│       │   ├── schemas/        # Request payload validation DTOs
│       │   ├── interfaces/     # Service interfaces (ICrawlService, IAiService)
│       │   └── validation/     # URL sanitization and checks
│       ├── package.json        # Shared package manifest
│       └── tsconfig.json       # Shared package TS config
│
├── docs/                       # Architecture, API, WebSocket & Env documentation
├── scripts/                    # Dev & build scripts
├── package.json                # Root monorepo workspace configuration
└── pnpm-workspace.yaml         # Monorepo workspace definition
```
