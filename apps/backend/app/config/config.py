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
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")
GOOGLE_CSE_DAILY_QUOTA = int(os.getenv("GOOGLE_CSE_DAILY_QUOTA", "100"))
GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE = int(os.getenv("GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE", "3"))
GOOGLE_CSE_CACHE_TTL_HOURS = int(os.getenv("GOOGLE_CSE_CACHE_TTL_HOURS", "24"))
