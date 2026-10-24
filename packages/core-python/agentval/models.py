"""Database tables (mirrors the Prisma schema in the product spec, plus run bookkeeping)."""
# NOTE: no "from __future__ import annotations" here: SQLModel relationships need real annotations.



import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, Relationship, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STATUSES = {RunStatus.COMPLETED.value, RunStatus.FAILED.value}


class Dataset(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    test_cases: List["TestCase"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    eval_runs: List["EvalRun"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class TestCase(SQLModel, table=True):
    __test__ = False  # keep pytest from collecting this class

    id: str = Field(default_factory=_uuid, primary_key=True)
    dataset_id: str = Field(foreign_key="dataset.id", index=True, ondelete="CASCADE")
    name: Optional[str] = None
    position: int = Field(default=0, index=True)
    input: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    expected: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    # "metadata" is reserved by SQLAlchemy declarative; keep the column name, rename attribute.
    meta: Optional[dict[str, Any]] = Field(default=None, sa_column=Column("metadata", JSON))
    created_at: datetime = Field(default_factory=utcnow)

    dataset: Optional[Dataset] = Relationship(back_populates="test_cases")
    eval_results: List["EvalResult"] = Relationship(
        back_populates="test_case",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class EvalRun(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    dataset_id: str = Field(foreign_key="dataset.id", index=True, ondelete="CASCADE")
    name: str
    status: str = Field(default=RunStatus.PENDING.value, index=True)
    model: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    metrics: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    total_cases: int = 0
    completed_cases: int = 0
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    dataset: Optional[Dataset] = Relationship(back_populates="eval_runs")
    results: List["EvalResult"] = Relationship(
        back_populates="eval_run",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class EvalResult(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    eval_run_id: str = Field(foreign_key="evalrun.id", index=True, ondelete="CASCADE")
    test_case_id: str = Field(foreign_key="testcase.id", index=True, ondelete="CASCADE")
    actual: Any = Field(default=None, sa_column=Column(JSON))
    trace: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    score: float = 0.0
    passed: bool = False
    status: str = "FAIL"  # PASS | PARTIAL | FAIL | ERROR
    scores: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    latency_ms: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 1
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)

    eval_run: Optional[EvalRun] = Relationship(back_populates="results")
    test_case: Optional[TestCase] = Relationship(back_populates="eval_results")
