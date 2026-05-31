import csv
import threading
from pathlib import Path
from typing import Callable, Dict, List, Type

from pydantic import BaseModel

from .models import Admin, Employee, KetuoInternalVehicle, KetuoPayment, KetuoReservedVehicle, OperationLog, Park, QuotaRule, Reservation
from .utils import hash_password, now


class PersistedDict(Dict[str, BaseModel]):
    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_change = on_change

    def __setitem__(self, key: str, value: BaseModel) -> None:
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._changed()

    def clear(self) -> None:
        super().clear()
        self._changed()

    def pop(self, key: str, default=None):
        value = super().pop(key, default)
        self._changed()
        return value

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        self._changed()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


class InMemoryDB:
    TABLES: dict[str, tuple[Type[BaseModel], str]] = {
        "employees": (Employee, "employee_id"),
        "admins": (Admin, "admin_id"),
        "parks": (Park, "park_id"),
        "quota_rules": (QuotaRule, "rule_id"),
        "reservations": (Reservation, "reservation_id"),
        "ketuo_internal_vehicles": (KetuoInternalVehicle, "id"),
        "ketuo_reserved_vehicles": (KetuoReservedVehicle, "id"),
        "ketuo_payments": (KetuoPayment, "payment_id"),
        "operation_logs": (OperationLog, "log_id"),
    }

    def __init__(self, csv_dir: str | Path | None = None) -> None:
        self.lock = threading.RLock()
        self.csv_dir = Path(csv_dir) if csv_dir is not None else None
        self._loading = True
        self.employees: Dict[str, Employee] = self._new_table("employees")  # type: ignore[assignment]
        self.admins: Dict[str, Admin] = self._new_table("admins")  # type: ignore[assignment]
        self.parks: Dict[str, Park] = self._new_table("parks")  # type: ignore[assignment]
        self.quota_rules: Dict[str, QuotaRule] = self._new_table("quota_rules")  # type: ignore[assignment]
        self.reservations: Dict[str, Reservation] = self._new_table("reservations")  # type: ignore[assignment]
        self.ketuo_internal_vehicles: Dict[str, KetuoInternalVehicle] = self._new_table("ketuo_internal_vehicles")  # type: ignore[assignment]
        self.ketuo_reserved_vehicles: Dict[str, KetuoReservedVehicle] = self._new_table("ketuo_reserved_vehicles")  # type: ignore[assignment]
        self.ketuo_payments: Dict[str, KetuoPayment] = self._new_table("ketuo_payments")  # type: ignore[assignment]
        self.operation_logs: Dict[str, OperationLog] = self._new_table("operation_logs")  # type: ignore[assignment]
        self.tokens: Dict[str, Dict[str, str]] = {}

        if self.csv_dir is None:
            self._seed_defaults()
            self._loading = False
            return

        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()
        self._seed_defaults()
        self._loading = False
        self.save_all()

    def _new_table(self, name: str) -> PersistedDict:
        return PersistedDict(lambda table=name: self._save_table(table))

    def _seed_defaults(self) -> None:
        seeded_at = now()

        default_employees = [
            Employee(
                employee_id="emp_001",
                name="张三",
                job_no="E1001",
                mobile="13800138000",
                login_account="zhangsan",
                password_hash=hash_password("123456"),
                status="active",
            ),
            Employee(
                employee_id="emp_002",
                name="李四",
                job_no="E1002",
                mobile="13900139000",
                login_account="lisi",
                password_hash=hash_password("123456"),
                status="active",
            ),
        ]
        for employee in default_employees:
            self.employees.setdefault(employee.employee_id, employee)

        admin = Admin(
            admin_id="admin_001",
            username="admin",
            password_hash=hash_password("admin123"),
            status="active",
        )
        self.admins.setdefault(admin.admin_id, admin)

        parks = [
            Park(park_id="park_weifang", park_name="潍坊", reservation_enabled=True, description="潍坊园区临时车辆预约说明：请按预约日期入厂。", status="active"),
            Park(park_id="park_qingdao", park_name="青岛", reservation_enabled=True, description="青岛园区临时车辆预约说明：高峰期请提前预约。", status="active"),
            Park(park_id="park_rongcheng", park_name="荣成", reservation_enabled=True, description="荣成园区临时车辆预约说明：请保持手机号可联系。", status="active"),
            Park(park_id="park_dongguan", park_name="东莞", reservation_enabled=True, description="东莞园区临时车辆预约说明：离场前可提前缴费。", status="active"),
        ]
        for park in parks:
            self.parks.setdefault(park.park_id, park)

        rule_index = 1
        for park in parks:
            for day_type, limit in (("workday", 10), ("restday", 4)):
                rule_id = f"rule_{rule_index:03d}"
                rule = QuotaRule(
                    rule_id=rule_id,
                    park_id=park.park_id,
                    day_type=day_type,
                    daily_limit=limit,
                    updated_at=seeded_at,
                    updated_by="system",
                )
                self.quota_rules.setdefault(rule.rule_id, rule)
                rule_index += 1

        internal_vehicle = KetuoInternalVehicle(
            id="iv_001",
            plate_no="鲁G88888",
            owner_type="internal",
            status="active",
        )
        self.ketuo_internal_vehicles.setdefault(internal_vehicle.id, internal_vehicle)

    def _load_all(self) -> None:
        for table_name in self.TABLES:
            self._load_table(table_name)

    def _load_table(self, table_name: str) -> None:
        if self.csv_dir is None:
            return
        path = self._table_path(table_name)
        if not path.exists():
            return
        model_class, key_field = self.TABLES[table_name]
        table = getattr(self, table_name)
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not any(row.values()):
                    continue
                record = model_class.model_validate(row)
                table[getattr(record, key_field)] = record

    def save_all(self) -> None:
        if self.csv_dir is None:
            return
        for table_name in self.TABLES:
            self._save_table(table_name)

    def _save_table(self, table_name: str) -> None:
        if self.csv_dir is None or self._loading:
            return
        model_class, _ = self.TABLES[table_name]
        path = self._table_path(table_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".csv.tmp")
        fieldnames = list(model_class.model_fields)
        table = getattr(self, table_name)
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in table.values():
                writer.writerow(record.model_dump(mode="json"))
        temp_path.replace(path)

    def _table_path(self, table_name: str) -> Path:
        if self.csv_dir is None:
            raise RuntimeError("CSV directory is not configured")
        return self.csv_dir / f"{table_name}.csv"


db = InMemoryDB(Path("data") / "generated_business_system")


def list_values(mapping: Dict[str, object]) -> List[object]:
    return list(mapping.values())
