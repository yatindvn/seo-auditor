# Deploying the backend to Oracle Cloud Always Free

The Next.js frontend goes on Vercel. This document covers the Python backend,
which cannot run on Vercel: it crawls for minutes per audit, serves a WebSocket
for live progress, and keeps all state in process memory. It needs a persistent
process on a real VM.

## Why a VM, and why exactly one instance

Every piece of audit state lives in memory:

| State | Location |
| --- | --- |
| `active_sessions` | `apps/backend/app/api/routes.py:16` |
| `active_crawlers` | `apps/backend/app/services/audit_service.py:17` |
| Audit history (in-memory list, capped at 50) | `apps/backend/app/models/session_model.py:7` |
| Rank cache + daily CSE quota counter | `apps/backend/app/seo/rank_checker.py:69` |
| Live WebSocket connections | `apps/backend/app/websocket/ws_manager.py:9` |

Two consequences:

- **Run one instance only.** With two, a `POST /api/audit` creates a session on
  one process while the browser's WebSocket connects to the other and receives
  nothing, and `GET /api/audit/latest` returns 404. The Dockerfile pins
  `--workers 1` and compose pins `replicas: 1` for this reason. Do not raise them.
- **Restarting loses all audit history.** Nothing is written to disk. Redeploying
  discards every stored session.

## 1. Create the instance

### Pick an Always Free eligible shape, or lose the VM in 30 days

A new Oracle account starts as a **Free Trial**: 30 days of credits *on top of*
the Always Free allowance. The console will happily create an instance on a shape
paid for out of those credits, and nothing warns you at the time. When the trial
ends, that instance is stopped and reclaimed — the deployment simply disappears.

The shape picker shows a green **"Always Free eligible"** badge. Confirm it before
creating. The default selection is frequently *not* eligible.

OCI Console → Compute → Instances → Create instance.

- **Shape:** `VM.Standard.A1.Flex`, 2 OCPU / 12 GB is ample (Always Free allows up
  to 4 OCPU / 24 GB across all A1 instances). This shape is **ARM64** — the
  Dockerfile pins Python 3.12 because `lxml` and `reportlab` publish prebuilt
  aarch64 wheels for it; other versions may try to compile from source and fail.
- **Image:** Ubuntu 22.04 or 24.04.
- **SSH key:** upload your public key. Save the private key somewhere safe.

If A1 capacity is unavailable in your region — common — either retry later or use
`VM.Standard.E2.1.Micro` (x86, 1 GB RAM). 1 GB is tight; see Memory below.

## 2. Open the firewalls — both of them

**This is the step that most often goes wrong.** OCI has two independent layers,
and opening only one leaves the service unreachable while looking perfectly
healthy from inside the VM.

**a. VCN Security List** (cloud-side): Networking → Virtual Cloud Networks → your
VCN → Security Lists → Default Security List → Add Ingress Rules. Add two, both
with Source `0.0.0.0/0`, protocol TCP, destination ports `80` and `443`.

**b. Host firewall** (inside the VM): Oracle's images drop everything except SSH.
`deploy/oracle/setup.sh` handles this for both `firewalld` and `iptables`, and
persists the rules so they survive a reboot.

## 3. Bootstrap the VM

```bash
ssh ubuntu@<your-public-ip>
git clone https://github.com/yatindvn/seo-auditor.git
cd seo-auditor
./deploy/oracle/setup.sh          # installs Docker, opens the host firewall
exec newgrp docker                 # pick up docker group membership without re-login
```

## 4. Configure

```bash
cp deploy/oracle/.env.example deploy/oracle/.env
nano deploy/oracle/.env
```

- `BACKEND_DOMAIN` — a real DNS name. **Let's Encrypt will not issue a
  certificate for a bare IP.** With no domain, use nip.io, which resolves
  `<ip>.nip.io` to that IP and passes HTTP-01 validation:
  `BACKEND_DOMAIN=203.0.113.10.nip.io`
- `ALLOWED_ORIGINS` — your frontend's exact origin(s), comma-separated. Without
  it the browser blocks every API call.

  CORS matches the `Origin` header **exactly**, and a Vercel project answers on
  several hostnames at once: a project alias (`seo-auditor-navy.vercel.app`), an
  owner alias (`seo-auditor-<owner>.vercel.app`), and a per-deployment URL
  (`seo-auditor-<hash>-<owner>.vercel.app`). List every alias you actually browse
  to. The per-deployment URL changes on every push, so preview deployments will
  not be covered — that is usually fine, but it is why a preview can fail with
  "blocked by CORS policy" while production works.

  Changing this needs the backend restarted to take effect:

  ```bash
  docker compose -f deploy/oracle/docker-compose.yml --env-file deploy/oracle/.env up -d
  ```
- `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_CX` — optional. Left blank, rank checks
  return `status: "skipped"` and the UI reports that honestly rather than
  implying the keywords rank badly.

`deploy/oracle/.env` is gitignored. Never commit it.

## 5. Start it

```bash
docker compose -f deploy/oracle/docker-compose.yml --env-file deploy/oracle/.env up -d --build
```

Caddy obtains a certificate on first request, so the initial load may take a few
seconds. Verify:

```bash
curl https://$BACKEND_DOMAIN/api/health
# {"status":"ok","service":"seo-auditor-native-python-backend","timestamp":"..."}
```

## 6. Point the frontend at it

In Vercel → Project → Settings → Environment Variables:

```
NEXT_PUBLIC_API_URL=https://<your-backend-domain>
NEXT_PUBLIC_WS_URL=wss://<your-backend-domain>/ws
```

**`wss://`, not `ws://`.** The default is `ws://localhost:5000/ws`
(`apps/frontend/services/api.ts:4`), and an HTTPS page may not open a plaintext
WebSocket — the browser blocks it as mixed content and live crawl progress
silently never arrives, with the rest of the dashboard looking fine.

Redeploy the frontend for the variables to take effect.

## Operating it

**Memory.** `PageResult` retains each page's full HTML
(`apps/backend/app/crawler/crawler.py:61`) for the whole crawl, and `max_pages`
is capped at 1000 (MAX_PAGES_LIMIT). On a 1 GB E2.1.Micro, keep crawls to a few
hundred pages. On
a 12 GB A1 there is far more headroom, but the ceiling is still real.

**Crawling from a cloud IP.** Some sites rate-limit or block datacenter ranges.
If crawls start failing against a specific target, this is a likely cause.

**Updating:**

```bash
git pull
docker compose -f deploy/oracle/docker-compose.yml --env-file deploy/oracle/.env up -d --build
```

This restarts the backend and therefore clears all audit history.

**Logs:**

```bash
docker compose -f deploy/oracle/docker-compose.yml logs -f backend
```

## If you later want history to survive restarts

`SessionStore` (`apps/backend/app/models/session_model.py`) is a plain in-memory
list. Persisting it to SQLite or Postgres is a self-contained change and the
natural next step if this becomes more than a demo.

<!-- Deployment note: NEXT_PUBLIC_API_URL and NEXT_PUBLIC_WS_URL are inlined at
build time, so changing them in the Vercel dashboard has no effect until a new
production build runs. Pushing a commit is the reliable way to force one. -->
