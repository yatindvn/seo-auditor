import importlib
from pathlib import Path

import dotenv
import pytest


@pytest.fixture(autouse=True)
def _restore_real_config_module_after_test():
    """Both tests below `importlib.reload()` the shared `app.config.config`
    module object while `dotenv.load_dotenv`/`os.environ` are monkeypatched,
    which leaves that *module object* mutated (e.g. GOOGLE_CSE_API_KEY set to
    a fake value) even after `monkeypatch` restores `os.environ` — reload
    mutates module attributes in place, and monkeypatch never re-reloads the
    module for us. Left uncleaned, the next test that imports the real config
    module would see it report itself "configured" and could attempt a live
    CSE request.

    Autouse fixtures are set up (and therefore finalized) before explicitly
    requested fixtures of the same scope, so this fixture's `yield` returns
    — running the reload below — only after the test's own `monkeypatch`
    fixture has already undone its changes. Reloading at that point re-reads
    the real environment and the real apps/backend/.env, restoring the
    module to the state a fresh import would produce.
    """
    yield
    from app.config import config as config_module
    importlib.reload(config_module)


def test_config_reads_values_from_backend_dotenv(monkeypatch):
    """config.py must load its .env from apps/backend, not just os.environ.

    The real apps/backend/.env is gitignored and untracked, so asserting its
    existence would fail on any fresh clone or CI runner and proves nothing
    about the code under test anyway (dotenv.load_dotenv is monkeypatched
    below, so the real file's contents are never read). Use the tracked
    .env.example instead purely to pin down *which directory* config.py's
    load_dotenv call must target — a check that has no dependency on the
    untracked file being present.
    """
    backend_dir = Path(__file__).resolve().parents[1]
    assert (backend_dir / ".env.example").exists(), "apps/backend/.env.example must exist"

    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    captured_path = {}

    def fake_load_dotenv(path, **kwargs):
        captured_path["path"] = Path(path)
        monkeypatch.setenv("GOOGLE_CSE_API_KEY", "from-dotenv")

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_API_KEY == "from-dotenv"
    # Proves config.py's load_dotenv call targets apps/backend/.env specifically,
    # without requiring that (gitignored) file to exist.
    assert captured_path["path"].parent == backend_dir
    assert captured_path["path"].name == ".env"


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
