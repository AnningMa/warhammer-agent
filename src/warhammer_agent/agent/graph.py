"""Sequential LangGraph routing with fresh evidence on every turn."""

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from warhammer_agent.rag.pipeline import prepare_question
from warhammer_agent.rag.refinement import failure_details

from .evidence import pack_evidence


class AgentState(TypedDict, total=False):
    question: str
    messages: list[dict]
    history: list[dict]
    query_plan: dict
    rewrite: dict
    route: dict
    pdf: dict
    sql: dict
    evidence: list[dict]
    omitted: list[str]
    errors: list[dict]
    usage: dict
    timings: dict
    answer: str
    citations: list[dict]
    insufficient_evidence: bool
    status: str


def bounded_history(messages, config):
    history = list(messages[-config["max_history_messages"] :])
    while (
        history
        and sum(len(m["content"]) for m in history) > config["max_history_chars"]
    ):
        history.pop(0)
    return history


def build_graph(services, config, checkpointer):
    def error_update(state, stage, error):
        # Avoid initializing a model merely to report a tool initialization error.
        resource = (
            getattr(services, "_sql_model", None)
            if stage == "sql"
            else getattr(services, "_model", None)
        )
        detail = failure_details(error, resource)
        return {"errors": [*state["errors"], {"stage": stage, **detail}]}

    def initialize(state):
        history = bounded_history(state.get("messages", []), config)
        return {
            "history": history,
            "query_plan": {
                "standalone_question": state["question"],
                "subquestions": [],
                "queries": [state["question"]],
            },
            "rewrite": {},
            "route": {},
            "pdf": {},
            "sql": {},
            "evidence": [],
            "omitted": [],
            "errors": [],
            "usage": {},
            "timings": {},
            "answer": "",
            "citations": [],
            "insufficient_evidence": True,
            "status": "running",
        }

    def rewrite(state):
        start = time.perf_counter()
        try:
            plan, history, metadata = prepare_question(
                state["question"], services.model, services.rag, state["history"]
            )
            return {
                "query_plan": plan,
                "history": history,
                "rewrite": metadata,
                "usage": {**state["usage"], "rewrite": metadata.get("usage")},
                "timings": {**state["timings"], "rewrite": time.perf_counter() - start},
            }
        except Exception as error:  # noqa: BLE001 -- optional planning retains the original question.
            return {
                "rewrite": {
                    "status": "fallback_original",
                    **failure_details(error, getattr(services, "_model", None)),
                }
            }

    def route(state):
        start = time.perf_counter()
        try:
            result, metadata = services.model.route(
                state["question"],
                state["query_plan"],
                state["history"],
                config["routing_max_output_tokens"],
            )
            # Validate even injected/test model adapters before selecting tools.
            from .model import Route

            result = Route.model_validate(result).model_dump()
            if any(
                len(result[key]) > services.rag["max_question_chars"]
                for key in ("pdf_question", "sql_question", "clarification")
            ):
                raise ValueError("Routing output exceeds the question length limit")
            return {
                "route": result,
                "usage": {**state["usage"], "route": metadata.get("usage")},
                "timings": {**state["timings"], "route": time.perf_counter() - start},
            }
        except Exception as error:  # noqa: BLE001 -- routing failure must not select a tool by guessing.
            return error_update(state, "route", error)

    def next_tool(state):
        route = state["route"]
        if not route or route["clarification"].strip():
            return "synthesize"
        return "sql" if route["intent"] == "database" else "pdf"

    def pdf(state):
        start = time.perf_counter()
        # Keep the original question in retrieval while adding the router's
        # focused PDF question, and reuse the single pre-routing query plan.
        plan = dict(state["query_plan"])
        focused = state["route"]["pdf_question"]
        plan["queries"] = list(
            dict.fromkeys([state["question"], *plan["queries"], focused])
        )
        try:
            result = services.retrieve_pdf(
                state["question"], plan, state["history"], state["rewrite"]
            )
            return {
                "pdf": result,
                "usage": {
                    **state["usage"],
                    "rerank": result.get("rerank", {}).get("usage"),
                },
                "timings": {**state["timings"], "pdf": time.perf_counter() - start},
            }
        except Exception as error:  # noqa: BLE001 -- hybrid may still return independently supported SQL facts.
            return error_update(state, "pdf", error)

    def after_pdf(state):
        return "sql" if state["route"]["intent"] == "hybrid" else "synthesize"

    def sql(state):
        start = time.perf_counter()
        try:
            result = services.retrieve_sql(state["route"]["sql_question"])
            return {
                "sql": result,
                "usage": {
                    **state["usage"],
                    "sql_plan": result.get("planning_usage"),
                    "sql": result.get("usage"),
                },
                "timings": {**state["timings"], "sql": time.perf_counter() - start},
            }
        except Exception as error:  # noqa: BLE001 -- report failure; never silently repair or weaken SQL safety.
            return error_update(state, "sql", error)

    def synthesize(state):
        route = state["route"]
        if not route:
            return {
                "status": "failed",
                "answer": "Unable to determine which information is needed. Please retry or clarify the question.",
            }
        if route["clarification"].strip():
            return {"status": "clarification", "answer": route["clarification"]}
        evidence, omitted = pack_evidence(
            state["pdf"].get("evidence", []), state["sql"], config
        )
        base = {"evidence": evidence, "omitted": omitted}
        if state["sql"].get("status") == "clarification" and not evidence:
            return {
                **base,
                "status": "clarification",
                "answer": state["sql"]["clarification"],
            }
        if not evidence:
            failed = any(e["stage"] in {"pdf", "sql"} for e in state["errors"])
            return {
                **base,
                "status": "failed" if failed else "insufficient_evidence",
                "answer": "No usable evidence is available to answer this question.",
            }
        required = (
            {"pdf"}
            if route["intent"] == "rules"
            else {"sql"}
            if route["intent"] == "database"
            else {"pdf", "sql"}
        )
        missing = required - {item["kind"] for item in evidence}
        limitations = [
            f"The {kind.upper()} path did not provide usable evidence."
            for kind in sorted(missing)
        ]
        if state["sql"].get("status") == "clarification":
            limitations.append(
                "Database clarification needed: " + state["sql"]["clarification"]
            )
        start = time.perf_counter()
        try:
            result = services.model.synthesize(
                state["question"],
                {**state["query_plan"], "tool_questions": route},
                evidence,
                limitations,
            )
            # Revalidate at the graph boundary: adapters cannot bypass citations.
            from .evidence import validate_answer

            ids = [
                c["citation_id"] if isinstance(c, dict) else c
                for c in result["citations"]
            ]
            validated = validate_answer(
                {
                    "answer": result["answer"],
                    "citations": ids,
                    "insufficient_evidence": result["insufficient_evidence"],
                },
                evidence,
            )
            result = {**result, **validated}
            partial = bool(missing) and bool(result["citations"])
            status = (
                "partial_answer"
                if partial
                else "insufficient_evidence"
                if result["insufficient_evidence"]
                else "answered"
            )
            if missing:
                result["answer"] += "\n\nUnavailable information: " + " ".join(
                    limitations
                )
                result["insufficient_evidence"] = True
            if any(e["kind"] == "sql" and e["truncated"] for e in evidence):
                result["answer"] += (
                    "\n\nDatabase results are incomplete due to query or context limits."
                )
            return {
                **base,
                **result,
                "status": status,
                "usage": {**state["usage"], "synthesis": result.get("usage")},
                "timings": {
                    **state["timings"],
                    "synthesis": time.perf_counter() - start,
                },
            }
        except Exception as error:  # noqa: BLE001 -- do not publish an unvalidated or unsupported answer.
            return {
                **base,
                **error_update(state, "synthesize", error),
                "status": "failed",
                "answer": "Unable to generate a validated answer from the retrieved evidence.",
            }

    def finish(state):
        messages = list(state.get("messages", []))
        if state["status"] != "failed":
            messages.extend(
                [
                    {"role": "user", "content": state["question"]},
                    {"role": "assistant", "content": state["answer"]},
                ]
            )
        return {"messages": bounded_history(messages, config)}

    graph = StateGraph(AgentState)
    for name, node in [
        ("initialize", initialize),
        ("rewrite", rewrite),
        ("route", route),
        ("pdf", pdf),
        ("sql", sql),
        ("synthesize", synthesize),
        ("finish", finish),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "rewrite")
    graph.add_edge("rewrite", "route")
    graph.add_conditional_edges(
        "route", next_tool, {name: name for name in ["pdf", "sql", "synthesize"]}
    )
    graph.add_conditional_edges(
        "pdf", after_pdf, {"sql": "sql", "synthesize": "synthesize"}
    )
    graph.add_edge("sql", "synthesize")
    graph.add_edge("synthesize", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
