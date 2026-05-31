from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from src.models import ReservationCreate
from src.services import ReservationService


app = FastAPI(title="Employee Temporary Vehicle Reservation System")
service = ReservationService(Path("data"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "employee-vehicle-reservation"}


@app.get("/campuses")
def campuses() -> list[dict[str, str]]:
    return service.list_campuses()


@app.get("/reservations")
def reservations() -> list[dict[str, str]]:
    return service.list_reservations()


@app.post("/reservations")
def create_reservation(request: ReservationCreate) -> dict[str, object]:
    return service.create_reservation(request)


@app.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: str) -> dict[str, object]:
    return service.cancel_reservation(reservation_id)


@app.post("/reservations/{reservation_id}/pay")
def advance_payment(reservation_id: str) -> dict[str, object]:
    return service.advance_payment(reservation_id)
