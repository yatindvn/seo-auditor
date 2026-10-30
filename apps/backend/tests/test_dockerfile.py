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


def test_optional_compose_services_do_not_require_their_variables():
    """Compose interpolates every service, profiles or not, so a `${VAR:?}`
    in an optional service stops the default deploy when VAR is unset."""
    import yaml

    compose = BACKEND.parents[1] / "deploy" / "oracle" / "docker-compose.yml"
    services = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        if service.get("profiles"):
            text = yaml.safe_dump(service)
            assert ":?" not in text, f"optional service {name} requires a variable"
