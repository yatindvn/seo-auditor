import importlib
from pathlib import Path


def test_config_reads_values_from_backend_dotenv(tmp_path, monkeypatch):
    """config.py must load apps/backend/.env, not just os.environ."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    assert env_file.exists(), "apps/backend/.env must exist (empty values are fine)"

    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *a, **k: __import__("os").environ.setdefault("GOOGLE_CSE_API_KEY", "from-dotenv"),
    )

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_API_KEY == "from-dotenv"


def test_dotenv_does_not_override_real_environment(monkeypatch):
    """An explicitly exported env var must win over the .env file."""
    monkeypatch.setenv("GOOGLE_CSE_CX", "from-real-env")

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_CX == "from-real-env"
