import os
from pathlib import Path

from dotenv import load_dotenv

# The live backend is the Python app; apps/backend/src/server.ts (which called
# dotenv.config()) is the retired Express server. Without this, GOOGLE_CSE_*
# values pasted into apps/backend/.env are never read and every rank check
# reports "not configured".
# override=False so a real exported environment variable still wins.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

PORT = int(os.getenv("PORT", "5000"))
HOST = os.getenv("HOST", "0.0.0.0")
MAX_PAGES_CAP = int(os.getenv("MAX_PAGES", "15"))
MAX_DEPTH_CAP = int(os.getenv("MAX_DEPTH", "2"))
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "10"))
# Fetch workers. The work is network-bound, so this far exceeds the core
# count of the deployed 2 OCPU shape. It is also the politeness dial: it
# sets how many connections a crawl opens against someone else's site at
# once, which is why it is configurable rather than a constant.
CRAWL_CONCURRENCY = int(os.getenv("CRAWL_CONCURRENCY", "32"))
# Where per-session SQLite files live, one per audit. A named Docker volume
# maps here in deploy/oracle/docker-compose.yml so audit history outlives a
# container rebuild -- it used to be an in-memory list, lost on every deploy.
SESSION_DIR = Path(os.getenv("SESSION_DIR", "./sessions"))
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")
GOOGLE_CSE_DAILY_QUOTA = int(os.getenv("GOOGLE_CSE_DAILY_QUOTA", "100"))
GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE = int(os.getenv("GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE", "3"))
GOOGLE_CSE_CACHE_TTL_HOURS = int(os.getenv("GOOGLE_CSE_CACHE_TTL_HOURS", "24"))

# Comma-separated browser origins permitted to call this API, e.g.
# "https://seo-auditor.vercel.app,https://www.example.com". Empty (the local
# default) means no origin is configured; see app/main.py, which then falls back
# to a wildcard *without* credentials rather than the invalid wildcard+credentials
# pair. Set this in any deployment where the frontend is on another domain.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
