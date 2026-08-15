import importlib
from pathlib import Path

import dotenv


def test_config_reads_values_from_backend_dotenv(monkeypatch):
    """config.py must load apps/backend/.env, not just os.environ."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    assert env_file.exists(), "apps/backend/.env must exist (empty values are fine)"

    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *a, **k: monkeypatch.setenv("GOOGLE_CSE_API_KEY", "from-dotenv"),
    )

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_API_KEY == "from-dotenv"


def test_dotenv_does_not_override_real_environment(tmp_path, monkeypatch):
    """An explicitly exported env var must win over the .env file (override=False).

    Self-contained: writes its own temp .env with a known non-empty value and
    redirects config.py's load_dotenv call to read that file instead of the
    real apps/backend/.env, so this test does not depend on the real fixture
    file's undeclared contents (e.g. GOOGLE_CSE_CX happening to be empty
    there). If config.py's override=False were flipped to override=True, the
    temp file's value would win and the assertion below would fail.
    """
    fake_env_file = tmp_path / ".env"
    fake_env_file.write_text("GOOGLE_CSE_CX=from-dotenv-file\n")

    real_load_dotenv = dotenv.load_dotenv

    def redirect_to_fake_env_file(_path, **kwargs):
        return real_load_dotenv(fake_env_file, **kwargs)

    monkeypatch.setattr("dotenv.load_dotenv", redirect_to_fake_env_file)
    monkeypatch.setenv("GOOGLE_CSE_CX", "from-real-env")

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_CX == "from-real-env"
