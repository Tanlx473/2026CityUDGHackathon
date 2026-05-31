import threading
from datetime import datetime
from typing import Dict, List

from .models import Admin, Employee, KetuoInternalVehicle, KetuoPayment, KetuoReservedVehicle, OperationLog, Park, QuotaRule, Reservation
from .utils import hash_password, now


class InMemoryDB:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.employees: Dict[str, Employee] = {}
        self.admins: Dict[str, Admin] = {}
        self.parks: Dict[str, Park] = {}
        self.quota_rules: Dict[str, QuotaRule] = {}
        self.reservations: Dict[str, Reservation] = {}
        self.ketuo_internal_vehicles: Dict[str, KetuoInternalVehicle] = {}
        self.ketuo_reserved_vehicles: Dict[str, KetuoReservedVehicle] = {}
        self.ketuo_payments: Dict[str, KetuoPayment] = {}
        self.operation_logs: Dict[str, OperationLog] = {}
        self.tokens: Dict[str, Dict[str, str]] = {}
        self._seed()

    def _seed(self) -> None:
        seeded_at = now()

        employee = Employee(
            employee_id="emp_001",
            name="张三",
            job_no="E1001",
            mobile="13800138000",
            login_account="zhangsan",
            password_hash=hash_password("123456"),
            status="active",
        )
        employee2 = Employee(
            employee_id="emp_002",
            name="李四",
            job_no="E1002",
            mobile="13900139000",
            login_account="lisi",
            password_hash=hash_password("123456"),
            status="active",
        )
        self.employees[employee.employee_id] = employee
        self.employees[employee2.employee_id] = employee2

        admin = Admin(
            admin_id="admin_001",
            username="admin",
            password_hash=hash_password("admin123"),
            status="active",
        )
        self.admins[admin.admin_id] = admin

        parks = [
            Park(park_id="park_weifang", park_name="潍坊", reservation_enabled=True, description="潍坊园区临时车辆预约说明：请按预约日期入厂。", status="active"),
            Park(park_id="park_qingdao", park_name="青岛", reservation_enabled=True, description="青岛园区临时车辆预约说明：高峰期请提前预约。", status="active"),
            Park(park_id="park_rongcheng", park_name="荣成", reservation_enabled=True, description="荣成园区临时车辆预约说明：请保持手机号可联系。", status="active"),
            Park(park_id="park_dongguan", park_name="东莞", reservation_enabled=True, description="东莞园区临时车辆预约说明：离场前可提前缴费。", status="active"),
        ]
        for park in parks:
            self.parks[park.park_id] = park

        rule_index = 1
        for park in parks:
            for day_type, limit in (("workday", 10), ("restday", 4)):
                rule = QuotaRule(
                    rule_id=f"rule_{rule_index:03d}",
                    park_id=park.park_id,
                    day_type=day_type,
                    daily_limit=limit,
                    updated_at=seeded_at,
                    updated_by="system",
                )
                self.quota_rules[rule.rule_id] = rule
                rule_index += 1

        internal_vehicle = KetuoInternalVehicle(
            id="iv_001",
            plate_no="鲁G88888",
            owner_type="internal",
            status="active",
        )
        self.ketuo_internal_vehicles[internal_vehicle.id] = internal_vehicle


db = InMemoryDB()


def list_values(mapping: Dict[str, object]) -> List[object]:
    return list(mapping.values())
