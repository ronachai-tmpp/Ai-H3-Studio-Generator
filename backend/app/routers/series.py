"""REST ของหน้าเว็บสำหรับดู/ควบคุม Series (การสร้างเนื้อหาทำผ่าน MCP)"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.series_models import SeriesError
from app.services.series_runtime import series_service
from app.services.series_service import SeriesService

router = APIRouter()

NOT_FOUND_PREFIX = "ไม่พบซีรีส์"


def get_service() -> SeriesService:
    return series_service


class ControlBody(BaseModel):
    action: Literal["pause", "resume", "cancel"]


def _call(fn, *args):
    try:
        return fn(*args)
    except SeriesError as exc:
        # store.get ยก SeriesError "ไม่พบซีรีส์ ..." เมื่อไม่มี id นั้น
        status = 404 if str(exc).startswith(NOT_FOUND_PREFIX) else 400
        raise HTTPException(status_code=status, detail=str(exc))


@router.get("/")
def list_series(service: SeriesService = Depends(get_service)):
    return service.overview()


@router.get("/{series_id}")
def series_detail(series_id: str, service: SeriesService = Depends(get_service)):
    return _call(service.detail, series_id)


@router.post("/{series_id}/control")
def control_series(series_id: str, body: ControlBody, service: SeriesService = Depends(get_service)):
    _call(service.control, series_id, body.action)
    return _call(service.detail, series_id)
