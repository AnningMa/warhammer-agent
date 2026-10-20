"""Disk checkpoints and one-at-a-time execution within each session."""

import fcntl
import hashlib
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from .graph import build_graph


@contextmanager
def session_graph(root: Path, config: dict, services, session_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
        raise ValueError(
            "session-id must contain 1–100 ASCII letters, digits, underscores or hyphens"
        )
    path = (root / config["checkpoints"]).resolve()
    business = (
        (root / services.sql["database_path"]).resolve()
        if hasattr(services, "sql")
        else None
    )
    if business == path:
        raise ValueError("Session checkpoints must not use the business database")
    path.parent.mkdir(parents=True, exist_ok=True)
    locks = path.parent / "locks"
    locks.mkdir(exist_ok=True)
    lock_path = locks / (hashlib.sha256(session_id.encode()).hexdigest() + ".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "This session is already running; submit turns sequentially"
            ) from error
        try:
            with closing(
                sqlite3.connect(str(path), check_same_thread=False)
            ) as connection:
                saver = SqliteSaver(
                    connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[])
                )
                yield build_graph(services, config, saver)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run_turn(root, config, services, question, session_id=None, progress=None):
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > services.rag["max_question_chars"]
    ):
        raise ValueError("The question must be nonempty and within max_question_chars")
    session_id = session_id or uuid4().hex
    started = time.perf_counter()
    with session_graph(root, config, services, session_id) as graph:
        run_config = {"configurable": {"thread_id": session_id}}
        for update in graph.stream(
            {"question": question.strip()}, run_config, stream_mode="updates"
        ):
            if progress:
                for name in update:
                    progress(name)
        state = dict(graph.get_state(run_config).values)
    return {
        **state,
        "models": {
            "routing_and_synthesis": services.rag.get("generation", {}).get("model"),
            "sql": services.sql.get("generation", {}).get("model")
            if hasattr(services, "sql")
            else None,
        },
        "session_id": session_id,
        "elapsed_seconds": time.perf_counter() - started,
    }
