from pathlib import Path

from warhammer_agent.ui import citation_label, error_label


def test_citation_labels_cover_pdf_and_sql_sources():
    pdf = citation_label(
        {
            "citation_id": "S1",
            "kind": "pdf",
            "source": "Core Rules.pdf",
            "section_title": "GRENADE",
            "page_numbers": [42],
        }
    )
    sql = citation_label(
        {
            "citation_id": "S2",
            "kind": "sql",
            "database_path": "data/wahadb.sqlite",
            "schema_tables": ["datasheets", "datasheets_models"],
        }
    )

    assert pdf == "[S1] Core Rules.pdf · GRENADE · PDF physical pages 42"
    assert sql == ("[S2] data/wahadb.sqlite · tables datasheets, datasheets_models")


def test_error_label_keeps_safe_diagnostic_fields():
    error = {
        "stage": "route",
        "error_type": "ClientError",
        "api_error": {"code": 429, "message": "provider detail"},
    }

    assert error_label(error) == "route: ClientError (API 429)"


# UI tests use Streamlit's real state/rerun engine and a fake Agent: no API calls.
import pytest

from warhammer_agent import ui

streamlit_testing = pytest.importorskip("streamlit.testing.v1")


@pytest.fixture
def chat_app(monkeypatch, tmp_path):
    calls = []
    closed = []

    class Services:
        def __init__(self, api_key):
            self._api_key = api_key

        def close(self):
            closed.append(True)

    def load_services(root, model, api_key):
        return {}, Services(api_key)

    def turn(root, config, services, question, *, session_id):
        calls.append((question, session_id))
        return {
            "answer": "A model has Toughness 4 [S1]. Compare Strength and Toughness [S2].",
            "status": "answered",
            "route": {"intent": "hybrid"},
            "citations": [
                {
                    "citation_id": "S1",
                    "kind": "sql",
                    "database_path": "data/wahadb.sqlite",
                    "schema_tables": ["datasheets", "datasheets_models"],
                },
                {
                    "citation_id": "S2",
                    "kind": "pdf",
                    "source": "Core Rules.pdf",
                    "section_title": "2. WOUND ROLL",
                    "page_numbers": [21, 22],
                },
            ],
        }

    monkeypatch.setattr(ui, "_load_services", load_services)
    monkeypatch.setattr(ui, "run_turn", turn)
    monkeypatch.setattr(ui, "save_report", lambda *args: tmp_path / "run.json")
    app = streamlit_testing.AppTest.from_file(Path.cwd() / "scripts/chat_app.py").run()
    assert not app.exception
    app.text_input(key="google_api_key").set_value("offline-session-key").run()
    return app, calls, closed


def test_empty_state_does_not_initialize_agent(chat_app):
    app, calls, _ = chat_app
    assert not calls
    assert len(app.chat_input) == 1
    assert [
        button.label
        for button in app.button
        if button.key and button.key.startswith("example-")
    ] == [example for _, example in ui.EXAMPLE_QUESTIONS]
    assert app.expander[0].label == "Settings"
    assert not app.expander[0].proto.expanded


@pytest.mark.parametrize("example_index", range(3))
def test_examples_use_same_agent_path_and_do_not_repeat(chat_app, example_index):
    app, calls, _ = chat_app
    session = app.session_state.session_id
    app.button(key=f"example-{example_index}").click().run()
    assert not app.exception
    assert calls == [(ui.EXAMPLE_QUESTIONS[example_index][1], session)]
    assert len(app.chat_message) == 2
    assert not any(button.key == "example-0" for button in app.button)
    assert any(expander.label == "Sources · 2" for expander in app.expander)
    assert all(not expander.proto.expanded for expander in app.expander)
    texts = " ".join(item.value for item in app.markdown)
    assert "PDF physical pages 21, 22" in texts
    assert "tables datasheets, datasheets_models" in texts
    app.run()
    assert len(calls) == 1


def test_typed_followup_and_new_session_preserve_model(chat_app):
    app, calls, _ = chat_app
    app.text_input(key="model_input").set_value("test-model").run()
    app.chat_input[0].set_value("First question").run()
    app.chat_input[0].set_value("What about cover?").run()
    assert not app.exception
    assert len(app.chat_message) == 4
    assert calls[0][1] == calls[1][1]
    app.sidebar.button[0].click().run()
    assert app.session_state.session_id != calls[0][1]
    assert not app.chat_message
    assert app.text_input(key="model_input").value == "test-model"
    app.chat_input[0].set_value("A new question").run()
    assert calls[2][1] != calls[0][1]


def test_failed_request_keeps_safe_error_on_rerun(chat_app, monkeypatch):
    app, _calls, _ = chat_app

    def fail(*args, **kwargs):
        raise ConnectionError("private provider detail")

    monkeypatch.setattr(ui, "run_turn", fail)
    app.chat_input[0].set_value("A question").run()
    assert not app.exception
    assert len(app.error) == 1
    assert "ConnectionError" in app.error[0].value
    assert "private provider detail" not in app.error[0].value
    app.run()
    assert len(app.error) == 1
    assert len(app.chat_message) == 2


def test_model_change_closes_previous_services(chat_app):
    app, calls, closed = chat_app
    app.chat_input[0].set_value("A question").run()
    app.text_input(key="model_input").set_value("another-model").run()
    app.chat_input[0].set_value("Another question").run()
    assert not app.exception
    assert closed == [True]
    assert len(calls) == 2


def test_missing_key_blocks_chat_and_examples_even_with_server_key(
    chat_app, monkeypatch
):
    app, calls, _ = chat_app
    monkeypatch.setenv("GEMINI_API_KEY", "server-key-must-not-be-used")
    app.button(key="clear-api-key").click().run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert all(
        button.disabled
        for button in app.button
        if (button.key or "").startswith("example-")
    )
    assert not calls
    assert "Enter your Google API key" in app.info[0].value
    assert (
        app.text_input(key="google_api_key").proto.type
        == app.text_input(key="google_api_key").proto.PASSWORD
    )


def test_key_rotation_and_clear_close_clients_without_losing_history(chat_app):
    app, calls, closed = chat_app
    app.chat_input[0].set_value("First question").run()
    app.text_input(key="google_api_key").set_value("replacement-session-key").run()
    assert closed == [True]
    assert len(app.chat_message) == 2
    app.chat_input[0].set_value("Second question").run()
    assert app.session_state.services._api_key == "replacement-session-key"
    assert calls[0][1] == calls[1][1]
    app.button(key="clear-api-key").click().run()
    assert closed == [True, True]
    assert app.chat_input[0].disabled
    assert app.text_input(key="google_api_key").value == ""
    assert "services" not in app.session_state
    assert len(app.chat_message) == 4


def test_new_conversation_keeps_session_key(chat_app):
    app, calls, _ = chat_app
    app.chat_input[0].set_value("Question").run()
    app.button(key="new-conversation").click().run()
    assert app.text_input(key="google_api_key").value == "offline-session-key"
    assert not app.chat_message
    assert len(calls) == 1
