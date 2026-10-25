"""API request/response models (Pydantic v2, camelCase on the wire)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class TestCaseCreate(ApiModel):
    __test__ = False
    name: Optional[str] = None
    input: dict[str, Any]
    expected: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class TestCaseRead(TestCaseCreate):
    id: str
    dataset_id: str
    created_at: datetime


class DatasetCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    test_cases: list[TestCaseCreate] = Field(default_factory=list)


class DatasetRead(ApiModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    test_case_count: int = 0
    run_count: int = 0


class DatasetDetail(DatasetRead):
    test_cases: list[TestCaseRead] = Field(default_factory=list)


class RunCreate(ApiModel):
    dataset_id: str
    name: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class ResultRead(ApiModel):
    id: str
    eval_run_id: str
    test_case_id: str
    test_case_name: Optional[str] = None
    input: Optional[dict[str, Any]] = None
    expected: Optional[dict[str, Any]] = None
    actual: Any = None
    trace: Optional[dict[str, Any]] = None
    score: float
    passed: bool
    status: str
    scores: dict[str, Any]
    latency_ms: int
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    attempts: int
    trial: int = 0
    error: Optional[str] = None


class RunRead(ApiModel):
    id: str
    dataset_id: str
    dataset_name: Optional[str] = None
    name: str
    status: str
    model: Optional[str] = None
    config: dict[str, Any]
    metrics: Optional[dict[str, Any]] = None
    total_cases: int
    completed_cases: int
    progress: float
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RunDetail(RunRead):
    results: list[ResultRead] = Field(default_factory=list)


class MetricDelta(ApiModel):
    metric: str
    a: Optional[float] = None
    b: Optional[float] = None
    delta: Optional[float] = None
    better: Optional[str] = None  # "a" | "b" | "same"


class CaseComparison(ApiModel):
    test_case_id: str
    test_case_name: Optional[str] = None
    status_a: Optional[str] = None
    status_b: Optional[str] = None
    score_a: Optional[float] = None
    score_b: Optional[float] = None
    delta: Optional[float] = None
    change: str  # improved | regressed | unchanged | missing


class CompareResponse(ApiModel):
    run_a: RunRead
    run_b: RunRead
    metrics: list[MetricDelta]
    scorers: list[MetricDelta]
    cases: list[CaseComparison]
    # Statistical regression analysis: summary (paired bootstrap CI, p-values, verdict) + CI gate.
    regression: Optional[dict[str, Any]] = None
