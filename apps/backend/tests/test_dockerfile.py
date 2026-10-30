"""The image must carry what the app needs at runtime, not just app/.

The database is created by Alembic on first use (app/db/engine.py reads
alembic.ini and alembic/ next to app/). An image without them answers 503 on
every project endpoint, and nothing else in the suite runs from the image.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _copied() -> set:
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    return {src for line in re.findall(r"^COPY\s+(.+)$", text, re.M) for src in line.split()[:-1]}


def _ignored() -> set:
    return {l.strip() for l in (BACKEND / ".dockerignore").read_text(encoding="utf-8").splitlines() if l.strip()}


def test_image_includes_the_migrations():
    copied, ignored = _copied(), _ignored()
    for needed in ("app", "alembic", "alembic.ini"):
        assert needed in copied, f"Dockerfile does not COPY {needed}"
        assert needed not in ignored and f"{needed}/" not in ignored, f".dockerignore excludes {needed}"
