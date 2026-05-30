from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

from app.agents.base import BaseAgent


BUSINESS_FILES: dict[str, str] = {
    "__init__.py": '"""Generated employee vehicle reservation business system."""\n',
    "models.py": r'''
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
''',
    "csv_repository.py": r'''
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Callable


DEFAULT_SCHEMAS: dict[str, list[str]] = {
    "campus_configs.csv": ["campus", "weekday_quota", "rest_day_quota", "enabled", "instruction"],
    "reservations.csv": [
        "reservation_id", "name", "employee_id", "mobile", "campus", "reservation_date", "plate_no", "status"
    ],
    "ketuo_reservation_archive.csv": ["reservation_id", "plate_no", "campus", "reserve_date", "status", "remark"],
    "payment_records.csv": ["payment_id", "reservation_id", "plate_no", "amount", "status", "created_at"],
    "internal_vehicle_archive.csv": ["plate_no", "owner", "remark"],
}


class CSVRepository:
    def __init__(self, base_dir: Path | str = "data", schemas: dict[str, list[str]] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.schemas = schemas or DEFAULT_SCHEMAS
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        for table, headers in self.schemas.items():
            path = self.path_for(table)
            if not path.exists():
                self._atomic_write(path, [], headers)

    def path_for(self, table: str) -> Path:
        if table not in self.schemas:
            raise ValueError(f"Unknown CSV table: {table}")
        return self.base_dir / table

    def read_all(self, table: str) -> list[dict[str, str]]:
        path = self.path_for(table)
        if not path.exists():
            self._atomic_write(path, [], self.schemas[table])
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def query(self, table: str, predicate: Callable[[dict[str, str]], bool]) -> list[dict[str, str]]:
        return [row for row in self.read_all(table) if predicate(row)]

    def append(self, table: str, row: dict[str, object]) -> dict[str, str]:
        rows = self.read_all(table)
        normalized = self._normalize(table, row)
        rows.append(normalized)
        self._atomic_write(self.path_for(table), rows, self.schemas[table])
        return normalized

    def update(
        self,
        table: str,
        predicate: Callable[[dict[str, str]], bool],
        changes: dict[str, object],
    ) -> int:
        rows = self.read_all(table)
        count = 0
        for row in rows:
            if predicate(row):
                for key, value in changes.items():
                    if key not in self.schemas[table]:
                        raise ValueError(f"Unknown field {key} for table {table}")
                    row[key] = str(value)
                count += 1
        if count:
            self._atomic_write(self.path_for(table), rows, self.schemas[table])
        return count

    def _normalize(self, table: str, row: dict[str, object]) -> dict[str, str]:
        headers = self.schemas[table]
        return {header: str(row.get(header, "")) for header in headers}

    def _atomic_write(self, path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})
        os.replace(temp_path, path)
''',
    "services.py": r'''
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
''',
    "api.py": r'''
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
''',
}


class CodeAgent(BaseAgent):
    agent_name = "CodeAgent"
    prompt_file = "code_agent.md"

    def run(self, input_context: dict[str, str]) -> list[object]:
        batch_id = input_context["batch_id"]
        src_dir = self.store.root_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, content in BUSINESS_FILES.items():
            self.store.write_text(src_dir / relative_path, dedent(content).lstrip("\n"))

        code_manifest = {
            "system_name": "Employee Temporary Vehicle Reservation System",
            "strategy": "template-first",
            "source_root": "src",
            "modules": sorted(BUSINESS_FILES.keys()),
            "entrypoint": "uvicorn src.api:app --reload",
            "business_functions": ["campus configuration", "reservation", "cancellation", "advance payment", "query"],
            "csv_tables": [
                "campus_configs.csv",
                "reservations.csv",
                "ketuo_reservation_archive.csv",
                "payment_records.csv",
                "internal_vehicle_archive.csv",
            ],
        }
        output_dir = self.batch_artifact_dir(batch_id, "代码生成")
        manifest_ref = self.store.write_json(output_dir / "code_manifest.json", code_manifest)

        snapshot_dir = output_dir / "src_snapshot"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        shutil.copytree(src_dir, snapshot_dir)
        snapshot_ref = self.store.artifact_for(snapshot_dir / "__init__.py", kind="src_snapshot")
        return [manifest_ref, snapshot_ref]
