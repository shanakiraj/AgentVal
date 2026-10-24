from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from agentval import schemas, service
from agentval.db import get_session
from agentval.models import Dataset, TestCase

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


def _get(session: Session, dataset_id: str) -> Dataset:
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    return ds


@router.get("", response_model=list[schemas.DatasetRead])
def list_datasets(session: Session = Depends(get_session)):
    rows = session.exec(select(Dataset).order_by(Dataset.created_at.desc())).all()
    return [service.dataset_view(session, d) for d in rows]


@router.post("", response_model=schemas.DatasetDetail, status_code=status.HTTP_201_CREATED)
def create_dataset(body: schemas.DatasetCreate, session: Session = Depends(get_session)):
    ds = service.create_dataset(session, body)
    return service.dataset_view(session, ds, detail=True)


@router.get("/{dataset_id}", response_model=schemas.DatasetDetail)
def get_dataset(dataset_id: str, session: Session = Depends(get_session)):
    return service.dataset_view(session, _get(session, dataset_id), detail=True)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, session: Session = Depends(get_session)):
    session.delete(_get(session, dataset_id))
    session.commit()


@router.post("/{dataset_id}/testcases", response_model=list[schemas.TestCaseRead],
             status_code=status.HTTP_201_CREATED)
def add_test_cases(dataset_id: str,
                   body: Union[schemas.TestCaseCreate, list[schemas.TestCaseCreate]],
                   session: Session = Depends(get_session)):
    """Add one test case (object body) or many (array body)."""
    ds = _get(session, dataset_id)
    items = body if isinstance(body, list) else [body]
    return [service.test_case_view(tc) for tc in service.add_test_cases(session, ds, items)]


@router.delete("/{dataset_id}/testcases/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(dataset_id: str, test_case_id: str, session: Session = Depends(get_session)):
    tc = session.get(TestCase, test_case_id)
    if tc is None or tc.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test case not found")
    session.delete(tc)
    session.commit()
