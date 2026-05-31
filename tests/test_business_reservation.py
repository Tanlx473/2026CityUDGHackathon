from __future__ import annotations

from datetime import date, timedelta

import pytest

pytest.importorskip("src.csv_repository", reason="Template business app is not the current generated src/ tree")

from src.csv_repository import CSVRepository
from src.models import ReservationCreate
from src.services import DISABLED_MESSAGE, PAYMENT_SUCCESS_MESSAGE, ReservationService


def make_request(day: date, campus: str = "Weifang", plate_no: str = "鲁A12345") -> ReservationCreate:
    return ReservationCreate(
        name="Alice",
        employee_id="E001",
        mobile="13800000000",
        campus=campus,
        reservation_date=day,
        plate_no=plate_no,
    )


def test_csv_repository_initialization_append_and_update(tmp_path):
    repo = CSVRepository(tmp_path)
    repo.initialize()
    repo.append("internal_vehicle_archive.csv", {"plate_no": "鲁A12345", "owner": "Alice", "remark": "demo"})
    assert repo.read_all("internal_vehicle_archive.csv")[0]["owner"] == "Alice"
    count = repo.update("internal_vehicle_archive.csv", lambda row: row["plate_no"] == "鲁A12345", {"owner": "Bob"})
    assert count == 1
    assert repo.read_all("internal_vehicle_archive.csv")[0]["owner"] == "Bob"


def test_successful_reservation_and_advance_payment(tmp_path):
    service = ReservationService(tmp_path)
    result = service.create_reservation(make_request(date.today() + timedelta(days=1)))
    assert result["success"] is True
    payment = service.advance_payment(result["reservation_id"])
    assert payment["message"] == PAYMENT_SUCCESS_MESSAGE
    assert service.repository.read_all("payment_records.csv")[0]["status"] == "success"


def test_quota_exceeded(tmp_path):
    service = ReservationService(tmp_path)
    day = date.today() + timedelta(days=1)
    service.repository.update("campus_configs.csv", lambda row: row["campus"] == "Weifang", {"weekday_quota": 1, "rest_day_quota": 1})
    assert service.create_reservation(make_request(day, plate_no="鲁A12345"))["success"] is True
    result = service.create_reservation(make_request(day, plate_no="鲁A12346"))
    assert result["success"] is False
    assert "名额已满" in result["message"]


def test_reservation_date_outside_next_seven_days_fails(tmp_path):
    service = ReservationService(tmp_path)
    result = service.create_reservation(make_request(date.today() + timedelta(days=8)))
    assert result["success"] is False
    assert "未来7天内" in result["message"]


def test_same_plate_number_cannot_reserve_twice_same_day(tmp_path):
    service = ReservationService(tmp_path)
    day = date.today() + timedelta(days=1)
    assert service.create_reservation(make_request(day, campus="Weifang", plate_no="鲁A12345"))["success"] is True
    result = service.create_reservation(make_request(day, campus="Qingdao", plate_no="鲁A12345"))
    assert result["success"] is False
    assert "同一车牌" in result["message"]


def test_disabled_campus_fails(tmp_path):
    service = ReservationService(tmp_path)
    service.set_campus_enabled("Weifang", False)
    result = service.create_reservation(make_request(date.today() + timedelta(days=1)))
    assert result["success"] is False
    assert result["message"] == DISABLED_MESSAGE


def test_cancellation_releases_quota(tmp_path):
    service = ReservationService(tmp_path)
    day = date.today() + timedelta(days=1)
    service.repository.update("campus_configs.csv", lambda row: row["campus"] == "Weifang", {"weekday_quota": 1, "rest_day_quota": 1})
    first = service.create_reservation(make_request(day, plate_no="鲁A12345"))
    assert first["success"] is True
    cancel = service.cancel_reservation(first["reservation_id"])
    assert cancel["success"] is True
    second = service.create_reservation(make_request(day, plate_no="鲁A12346"))
    assert second["success"] is True
    ketuo = service.repository.read_all("ketuo_reservation_archive.csv")
    assert ketuo[0]["status"] == "cancelled"
