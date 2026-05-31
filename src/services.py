from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from src.csv_repository import CSVRepository
from src.models import ReservationCreate


CAMPUSES = ["Weifang", "Qingdao", "Rongcheng", "Dongguan"]
DISABLED_MESSAGE = "当前园区暂不开放预约"
PAYMENT_SUCCESS_MESSAGE = "缴费成功，离厂时无需支付"


class ReservationService:
    def __init__(self, data_dir: Path | str = "data") -> None:
        self.repository = CSVRepository(data_dir)
        self.repository.initialize()
        self.ensure_default_campus_configs()

    def ensure_default_campus_configs(self) -> None:
        if self.repository.read_all("campus_configs.csv"):
            return
        for campus in CAMPUSES:
            self.repository.append(
                "campus_configs.csv",
                {
                    "campus": campus,
                    "weekday_quota": 2,
                    "rest_day_quota": 1,
                    "enabled": "true",
                    "instruction": f"{campus} campus temporary reservation",
                },
            )

    def list_campuses(self) -> list[dict[str, str]]:
        return self.repository.read_all("campus_configs.csv")

    def list_reservations(self) -> list[dict[str, str]]:
        return self.repository.read_all("reservations.csv")

    def create_reservation(self, request: ReservationCreate) -> dict[str, object]:
        config = self._campus_config(request.campus)
        if not config or config.get("enabled", "").lower() != "true":
            return {"success": False, "message": DISABLED_MESSAGE, "reservation_id": None}
        if not self._valid_plate(request.plate_no):
            return {"success": False, "message": "车牌号格式不正确", "reservation_id": None}
        if not self._within_next_seven_days(request.reservation_date):
            return {"success": False, "message": "预约日期必须在未来7天内", "reservation_id": None}
        if self._duplicate_plate(request.plate_no, request.reservation_date):
            return {"success": False, "message": "同一车牌同一天只能预约一个园区", "reservation_id": None}
        if self._active_count(request.campus, request.reservation_date) >= self._quota(config, request.reservation_date):
            return {"success": False, "message": "当日预约名额已满", "reservation_id": None}

        reservation_id = uuid.uuid4().hex[:12]
        row = {
            "reservation_id": reservation_id,
            "name": request.name,
            "employee_id": request.employee_id,
            "mobile": request.mobile,
            "campus": request.campus,
            "reservation_date": request.reservation_date.isoformat(),
            "plate_no": request.plate_no.upper(),
            "status": "success",
        }
        self.repository.append("reservations.csv", row)
        self.repository.append(
            "ketuo_reservation_archive.csv",
            {
                "reservation_id": reservation_id,
                "plate_no": request.plate_no.upper(),
                "campus": request.campus,
                "reserve_date": request.reservation_date.isoformat(),
                "status": "success",
                "remark": f"{request.name}/{request.employee_id}/{request.mobile}",
            },
        )
        return {"success": True, "message": "预约成功", "reservation_id": reservation_id}

    def cancel_reservation(self, reservation_id: str) -> dict[str, object]:
        matches = self.repository.query(
            "reservations.csv",
            lambda row: row["reservation_id"] == reservation_id and row["status"] == "success",
        )
        if not matches:
            return {"success": False, "message": "未找到可取消的预约", "reservation_id": reservation_id}
        self.repository.update(
            "reservations.csv",
            lambda row: row["reservation_id"] == reservation_id,
            {"status": "cancelled"},
        )
        self.repository.update(
            "ketuo_reservation_archive.csv",
            lambda row: row["reservation_id"] == reservation_id,
            {"status": "cancelled"},
        )
        return {"success": True, "message": "取消成功", "reservation_id": reservation_id}

    def advance_payment(self, reservation_id: str) -> dict[str, object]:
        matches = self.repository.query(
            "reservations.csv",
            lambda row: row["reservation_id"] == reservation_id and row["status"] == "success",
        )
        if not matches:
            return {"success": False, "message": "未找到可缴费的预约", "reservation_id": reservation_id}
        reservation = matches[0]
        payment_id = uuid.uuid4().hex[:12]
        self.repository.append(
            "payment_records.csv",
            {
                "payment_id": payment_id,
                "reservation_id": reservation_id,
                "plate_no": reservation["plate_no"],
                "amount": "20.00",
                "status": "success",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        return {
            "success": True,
            "message": PAYMENT_SUCCESS_MESSAGE,
            "reservation_id": reservation_id,
            "payment_id": payment_id,
        }

    def set_campus_enabled(self, campus: str, enabled: bool) -> None:
        self.repository.update("campus_configs.csv", lambda row: row["campus"] == campus, {"enabled": str(enabled).lower()})

    def _campus_config(self, campus: str) -> dict[str, str] | None:
        matches = self.repository.query("campus_configs.csv", lambda row: row["campus"] == campus)
        return matches[0] if matches else None

    def _quota(self, config: dict[str, str], reservation_date: date) -> int:
        key = "weekday_quota" if reservation_date.weekday() < 5 else "rest_day_quota"
        return int(config[key])

    def _active_count(self, campus: str, reservation_date: date) -> int:
        day = reservation_date.isoformat()
        return len(
            self.repository.query(
                "reservations.csv",
                lambda row: row["campus"] == campus and row["reservation_date"] == day and row["status"] == "success",
            )
        )

    def _duplicate_plate(self, plate_no: str, reservation_date: date) -> bool:
        day = reservation_date.isoformat()
        plate = plate_no.upper()
        return bool(
            self.repository.query(
                "reservations.csv",
                lambda row: row["plate_no"].upper() == plate and row["reservation_date"] == day and row["status"] == "success",
            )
        )

    def _within_next_seven_days(self, reservation_date: date) -> bool:
        today = date.today()
        return today <= reservation_date <= today + timedelta(days=7)

    def _valid_plate(self, plate_no: str) -> bool:
        value = plate_no.strip().upper()
        if len(value) not in {7, 8}:
            return False
        return bool(re.match(r"^[\u4e00-\u9fa5][A-Z][A-Z0-9]{5,6}$", value))
