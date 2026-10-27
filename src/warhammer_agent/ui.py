"""Handbook-inspired local Streamlit interface for the unified agent."""

import json
from pathlib import Path
from uuid import uuid4

from warhammer_agent.agent.cli import validate_config as validate_agent
from warhammer_agent.agent.services import AgentServices
from warhammer_agent.agent.session import run_turn
from warhammer_agent.rag.cli import save_report
from warhammer_agent.rag.cli import validate_config as validate_rag
from warhammer_agent.rag.refinement import failure_details
from warhammer_agent.sql.cli import _validate_config as validate_sql

EXAMPLE_QUESTIONS = (
    ("Core Rules", "How does Deep Strike work?"),
    ("Datasheets", "What is the Toughness of an Intercessor Squad model?"),
    (
        "Rules + datasheets",
        (
            "What is the Toughness of a Heavy Intercessor Squad model, "
            "and what roll does a Strength 6 attack need to wound it?"
        ),
    ),
)


def citation_label(citation: dict) -> str:
    """Return one concise, user-facing source label."""
    identity = citation["citation_id"]
    if citation["kind"] == "pdf":
        pages = ", ".join(str(page) for page in citation["page_numbers"])
        return (
            f"[{identity}] {citation['source']} · {citation['section_title']} "
            f"· PDF physical pages {pages}"
        )
    tables = ", ".join(citation["schema_tables"])
    return f"[{identity}] {citation['database_path']} · tables {tables}"


def error_label(error: dict) -> str:
    """Return a safe stage, type and API-code summary."""
    stage = error.get("stage", "request")
    kind = error.get("error_type", "Error")
    code = (error.get("api_error") or {}).get("code")
    suffix = f" (API {code})" if code is not None else ""
    return f"{stage}: {kind}{suffix}"


def _new_session() -> str:
    return f"web_{uuid4().hex}"


def _load_services(root: Path, model: str, api_key: str) -> tuple[dict, AgentServices]:
    config = json.loads((root / "config/agent.json").read_text())
    validate_agent(config)
    services = AgentServices(root, config, api_key=api_key)
    services.rag["generation"]["model"] = model
    services.sql["generation"]["model"] = model
    validate_rag(services.rag)
    validate_sql(services.sql)
    return config, services


def _render_assistant(st, message: dict, index: int) -> None:
    if message["status"] == "answered":
        st.caption(":green[Answered]")
    with st.container(key=f"answer-{index}"):
        st.markdown(message["content"])
    errors = message.get("errors", [])
    if errors:
        st.error("Request failure: " + "; ".join(error_label(e) for e in errors))
    citations = message.get("citations", [])
    if citations:
        with st.expander(f"Sources · {len(citations)}", expanded=False):
            for source_index, citation in enumerate(citations):
                with st.container(key=f"source-{index}-{source_index}"):
                    st.caption(
                        ":green[PDF rules]"
                        if citation["kind"] == "pdf"
                        else ":green[Database]"
                    )
                    st.markdown(citation_label(citation))
    with st.expander("Run details", expanded=False):
        st.write(f"Status: `{message['status']}`")
        st.write(f"Route: `{message.get('route') or 'unavailable'}`")
        if message.get("report_path"):
            st.caption(f"Run report: {message['report_path']}")


def _choose_example(question: str) -> None:
    import streamlit as st

    st.session_state.pending_question = question


def _clear_api_key() -> None:
    import streamlit as st

    st.session_state.google_api_key = ""


def main() -> None:
    """Run the Streamlit application with the existing Agent entry point."""
    import streamlit as st

    root = Path.cwd()
    st.set_page_config(
        page_title="Warhammer 40K Assistant",
        page_icon=":material/menu_book:",
        layout="centered",
    )
    st.html(f"<style>{Path(__file__).with_suffix('.css').read_text()}</style>")
    with st.container(key="manual-page"):
        _render_page(st, root)


def _render_page(st, root: Path) -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = _new_session()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar, st.container(key="manual-sidebar"):
        st.header("Core Rules")
        st.caption("Rules, datasheets & battlefield questions.")
        if st.button(
            "New conversation", key="new-conversation", type="primary", width="stretch"
        ):
            st.session_state.session_id = _new_session()
            st.session_state.messages = []
            st.session_state.pop("pending_question", None)
            st.rerun()
        st.subheader("Google API key")
        api_key = st.text_input(
            "Google API key",
            type="password",
            key="google_api_key",
            placeholder="Enter your Gemini API key",
            label_visibility="collapsed",
        ).strip()
        st.caption(
            "Kept in this session's memory; not saved to configuration or run reports."
        )
        st.markdown(
            "[Get a key in Google AI Studio](https://aistudio.google.com/apikey)"
        )
        if api_key:
            st.button("Clear API key", key="clear-api-key", on_click=_clear_api_key)
        st.subheader("Current session")
        st.code(st.session_state.session_id, language=None)
        with st.expander("Settings", expanded=False):
            # A separate value survives Streamlit's cleanup of hidden widgets.
            model = st.text_input(
                "Gemini model",
                value=st.session_state.get("selected_model", "gemini-3-flash-preview"),
                key="model_input",
            ).strip()
            st.session_state.selected_model = model
            st.caption(
                "This model is used for routing, PDF refinement, SQL and answers."
            )
        st.divider()
        st.caption("Answers refer to the project's local rules and datasheets.")

    # Close clients as soon as their session credentials/model change, even when idle.
    old = st.session_state.get("services")
    if old is not None and (
        st.session_state.get("active_model") != model
        or getattr(old, "_api_key", None) != api_key
    ):
        old.close()
        for name in ("services", "config", "active_model"):
            st.session_state.pop(name, None)

    with st.container(key="manual-title"):
        st.title("Warhammer 40K Assistant")
        st.markdown(
            "Consult the Core Rules. Check a datasheet. Resolve a battlefield question."
        )
        st.caption("Answers include references to the local PDF or database.")

    if not api_key:
        st.info("Enter your Google API key in the sidebar to start a conversation.")

    if not st.session_state.messages:
        with st.container(key="manual-examples"):
            st.subheader("Begin with a question")
            for index, (label, example) in enumerate(EXAMPLE_QUESTIONS):
                st.caption(label)
                st.button(
                    example,
                    key=f"example-{index}",
                    width="stretch",
                    disabled=not api_key,
                    on_click=_choose_example,
                    args=(example,),
                )

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(
            message["role"],
            avatar=":material/menu_book:"
            if message["role"] == "assistant"
            else ":material/person:",
        ):
            if message["role"] == "assistant":
                _render_assistant(st, message, index)
            else:
                st.markdown(message["content"])

    typed_question = st.chat_input(
        "Ask a Warhammer 40K question", key="question", disabled=not api_key
    )
    question = st.session_state.pop("pending_question", None) or typed_question
    if not question or not api_key:
        return
    question = question.strip()
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)

    with st.chat_message("assistant", avatar=":material/menu_book:"):
        try:
            if not model:
                raise ValueError("Gemini model cannot be empty")
            active_model = st.session_state.get("active_model")
            if "services" not in st.session_state or active_model != model:
                old = st.session_state.get("services")
                if old is not None:
                    old.close()
                config, services = _load_services(root, model, api_key)
                st.session_state.config = config
                st.session_state.services = services
                st.session_state.active_model = model
            with st.spinner("Searching the project sources..."):
                record = run_turn(
                    root,
                    st.session_state.config,
                    st.session_state.services,
                    question,
                    session_id=st.session_state.session_id,
                )
            report_path = save_report(root, st.session_state.config, record)
            message = {
                "role": "assistant",
                "content": record["answer"],
                "citations": record.get("citations", []),
                "status": record["status"],
                "route": (record.get("route") or {}).get("intent"),
                "errors": record.get("errors", []),
                "report_path": str(report_path),
            }
            st.session_state.messages.append(message)
        except Exception as error:  # noqa: BLE001 -- UI boundary shows safe diagnostics.
            details = failure_details(
                error,
                getattr(st.session_state.get("services"), "_model", None),
                api_key=api_key,
            )
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "This question could not be answered. "
                    "Please try again when the service is available.",
                    "status": "failed",
                    "errors": [{"stage": "request", **details}],
                }
            )
    # Redraw history once: remove empty-state examples and keep errors on reruns.
    st.rerun()
