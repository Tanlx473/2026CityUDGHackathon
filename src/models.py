from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class ReservationCreate(BaseModel):
    name: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    mobile: str = Field(min_length=5)
    campus: str
    reservation_date: date
    plate_no: str


class ReservationCancel(BaseModel):
    reservation_id: str


class ReservationResponse(BaseModel):
    success: bool
    message: str
    reservation_id: str | None = None
