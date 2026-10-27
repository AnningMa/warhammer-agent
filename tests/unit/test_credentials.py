"""Session credentials must never overwrite shared process configuration."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from warhammer_agent.credentials import resolve_api_key
from warhammer_agent.rag.generation import GeminiGenerator
from warhammer_agent.rag.refinement import failure_details
from warhammer_agent.sql.generator import GeminiSQLGenerator


def test_explicit_key_and_blank_key_never_use_env_file(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Explicit session credentials must not load .env")

    monkeypatch.setattr("dotenv.load_dotenv", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    settings = {"api_key_env": "GEMINI_API_KEY"}
    assert resolve_api_key(tmp_path, settings, " session-key ") == "session-key"
    with pytest.raises(ValueError, match="Provide a Google API key"):
        resolve_api_key(tmp_path, settings, " ")
    assert resolve_api_key(Path.cwd(), settings, "another-session") == "another-session"
    # The shared environment remains untouched.
    import os

    assert os.environ["GEMINI_API_KEY"] == "server-key"


def test_cli_still_supports_env_and_dotenv(tmp_path, monkeypatch):
    settings = {"api_key_env": "GEMINI_API_KEY"}
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=file-key\n")
    assert resolve_api_key(tmp_path, settings) == "file-key"
    monkeypatch.setenv("GEMINI_API_KEY", "environment-key")
    assert resolve_api_key(tmp_path, settings) == "environment-key"


@pytest.mark.parametrize("model_class", [GeminiGenerator, GeminiSQLGenerator])
def test_clients_use_separate_session_keys_without_changing_settings(
    tmp_path, monkeypatch, model_class
):
    from google import genai

    keys = []

    def client(**kwargs):
        keys.append(kwargs["api_key"])
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    settings = {
        "model": "offline-stub",
        "api_key_env": "GEMINI_API_KEY",
        "timeout_ms": 1000,
        "attempts": 1,
        "max_output_tokens": 1000,
        "temperature": 0.2,
    }
    original = json.dumps(settings, sort_keys=True)
    first = model_class(tmp_path, settings, api_key="session-one")
    second = model_class(tmp_path, settings, api_key="session-two")
    assert keys == ["session-one", "session-two"]
    assert first._api_key != second._api_key
    assert json.dumps(settings, sort_keys=True) == original
    first.close()
    second.close()


def test_error_details_redact_runtime_key_including_client_init_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "server-key")
    error = SimpleNamespace(code=429, message="session-one session-two server-key")
    generator = SimpleNamespace(
        _api_key="session-one", settings={"api_key_env": "GEMINI_API_KEY"}
    )
    details = failure_details(error, generator, api_key="session-two")
    assert details["api_error"]["message"] == "[REDACTED] [REDACTED] [REDACTED]"
    error.message = "session-two"
    assert (
        failure_details(error, None, api_key="session-two")["api_error"]["message"]
        == "[REDACTED]"
    )


def test_services_pass_each_sessions_key_to_both_clients(monkeypatch):
    from warhammer_agent.agent import services as module

    initialized = []

    class Model:
        def __init__(self, root, settings, *, api_key):
            self._api_key = api_key
            initialized.append(api_key)

        def close(self):
            pass

    monkeypatch.setattr(module, "AgentModel", Model)
    monkeypatch.setattr(module, "GeminiSQLGenerator", Model)
    monkeypatch.setattr(module.SchemaCatalog, "from_sqlite", lambda path: object())
    monkeypatch.setattr(module, "ReadOnlyDatabase", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        module,
        "SQLRetriever",
        lambda *args, **kwargs: SimpleNamespace(
            retrieve=lambda question: SimpleNamespace(
                to_dict=lambda: {"status": "executed"}
            )
        ),
    )
    root = Path.cwd()
    config = json.loads((root / "config/agent.json").read_text())
    first = module.AgentServices(root, config, api_key="session-one")
    second = module.AgentServices(root, config, api_key="session-two")
    assert first.model._api_key == "session-one"
    assert second.model._api_key == "session-two"
    first.retrieve_sql("Question")
    second.retrieve_sql("Question")
    assert initialized == ["session-one", "session-two", "session-one", "session-two"]
    for instance in (first, second):
        serialized = json.dumps([instance.config, instance.rag, instance.sql])
        assert "session-one" not in serialized and "session-two" not in serialized
        instance.close()
