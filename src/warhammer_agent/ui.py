"""Small local Streamlit interface for the unified agent."""

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


def _load_services(root: Path, model: str) -> tuple[dict, AgentServices]:
    config = json.loads((root / "config/agent.json").read_text())
    validate_agent(config)
    services = AgentServices(root, config)
    services.rag["generation"]["model"] = model
    services.sql["generation"]["model"] = model
    validate_rag(services.rag)
    validate_sql(services.sql)
    return config, services


def _render_assistant(st, message: dict) -> None:
    st.markdown(message["content"])
    errors = message.get("errors", [])
    if errors:
        st.error("Request failure: " + "; ".join(error_label(e) for e in errors))
    citations = message.get("citations", [])
    if citations:
        st.markdown("**Sources**")
        for citation in citations:
            st.markdown(f"- {citation_label(citation)}")
    with st.expander("Run details"):
        st.write(f"Status: `{message['status']}`")
        st.write(f"Route: `{message.get('route') or 'unavailable'}`")
        if message.get("report_path"):
            st.caption(f"Run report: {message['report_path']}")


def main() -> None:
    """Run the Streamlit application."""
    import streamlit as st

    root = Path.cwd()
    st.set_page_config(page_title="Warhammer 40K Assistant", page_icon="⚔️")
    st.title("Warhammer 40K Assistant")
    st.caption("Ask about the Core Rules, unit datasheets, or both sources.")

    if "session_id" not in st.session_state:
        st.session_state.session_id = _new_session()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar:
        st.header("Session")
        model = st.text_input("Gemini model", value="gemini-3-flash-preview").strip()
        st.code(st.session_state.session_id, language=None)
        if st.button("New conversation", use_container_width=True):
            st.session_state.session_id = _new_session()
            st.session_state.messages = []
            st.rerun()
        st.caption("The API key is read from GEMINI_API_KEY in .env.")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                _render_assistant(st, message)
            else:
                st.markdown(message["content"])

    question = st.chat_input("Ask a Warhammer 40K question")
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            if not model:
                raise ValueError("Gemini model cannot be empty")
            active_model = st.session_state.get("active_model")
            if "services" not in st.session_state or active_model != model:
                old = st.session_state.get("services")
                if old is not None:
                    old.close()
                config, services = _load_services(root, model)
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
            _render_assistant(st, message)
        except Exception as error:  # noqa: BLE001 -- UI boundary shows safe diagnostics.
            details = failure_details(
                error,
                getattr(st.session_state.get("services"), "_model", None),
            )
            code = (details.get("api_error") or {}).get("code")
            suffix = f" (API {code})" if code is not None else ""
            st.error(f"The request failed: {details['error_type']}{suffix}")
