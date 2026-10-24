"""End-to-end evaluation for the unified Warhammer agent."""

from .dataset import EvaluationCase, load_cases
from .metrics import evaluate_case, summarize

__all__ = ["EvaluationCase", "evaluate_case", "load_cases", "summarize"]
