"""Modular scorer registry. Importing this package registers the built-in scorers."""

from agentval.scorers.base import (
    Scorer,
    ScoreResult,
    ScoringContext,
    available_scorers,
    build_scorer,
    get_scorer_class,
    register_scorer,
)
from agentval.scorers.exact_match import ExactMatchScorer
from agentval.scorers.llm_judge import LLMJudgeScorer
from agentval.scorers.schema_match import SchemaMatchScorer
from agentval.scorers.trajectory import TrajectoryScorer

__all__ = [
    "Scorer",
    "ScoreResult",
    "ScoringContext",
    "available_scorers",
    "build_scorer",
    "get_scorer_class",
    "register_scorer",
    "ExactMatchScorer",
    "SchemaMatchScorer",
    "LLMJudgeScorer",
    "TrajectoryScorer",
]
