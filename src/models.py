from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


ReservationStatus = Literal["pending_effective", "cancelled", "completed"]
PaymentStatus = Literal["unpaid", "paid"]
DayType = Literal["workday", "restday"]


class Employee(BaseModel):
    employee_id: str
    name: str
    job_no: str
    mobile: str
    login_account: str
    password_hash: str
    status: str = "active"


class Admin(BaseModel):
    admin_id: str
    username: str
    password_hash: str
    status: str = "active"


class Park(BaseModel):
    park_id: str
    park_name: str
    reservation_enabled: bool = True
    description: str
    status: str = "active"


class QuotaRule(BaseModel):
    rule_id: str
    park_id: str
    day_type: DayType
    daily_limit: int = Field(ge=0)
    updated_at: datetime
    updated_by: str


class Reservation(BaseModel):
    reservation_id: str
    employee_id: str
    name: str
    job_no: str
    mobile: str
    park_id: str
    park_name: str
    plate_no: str
    reservation_date: date
    status: ReservationStatus = "pending_effective"
    payment_status: PaymentStatus = "unpaid"
    created_at: datetime
    updated_at: datetime


class KetuoInternalVehicle(BaseModel):
    id: str
    plate_no: str
    owner_type: str
    status: str


class KetuoReservedVehicle(BaseModel):
    id: str
    plate_no: str
    park_name: str
    reservation_date: date
    status: str
    remark: str
    synced_at: datetime


class KetuoPayment(BaseModel):
    payment_id: str
    plate_no: str
    park_name: str
    pay_time: datetime
    amount: float
    status: str


class OperationLog(BaseModel):
    log_id: str
    operator_type: str
    operator_id: str
    action: str
    target_id: str
    detail: str
    created_at: datetime


class LoginRequest(BaseModel):
    login_account: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_type: Literal["employee", "admin"]
    user_id: str
    name: str


class ParkResponse(BaseModel):
    park_id: str
    park_name: str
    reservation_enabled: bool
    description: str


class ParkUpdateRequest(BaseModel):
    reservation_enabled: bool
    description: str


class QuotaRuleResponse(BaseModel):
    rule_id: str
    park_id: str
    day_type: DayType
    daily_limit: int
    updated_at: datetime
    updated_by: str


class QuotaRuleUpdateRequest(BaseModel):
    daily_limit: int = Field(ge=0)


class QuotaRemainResponse(BaseModel):
    park_id: str
    park_name: str
    date: date
    day_type: DayType
    daily_limit: int
    used_count: int
    remain_count: int
    reservation_enabled: bool
    description: str


class ReservationCreateRequest(BaseModel):
    name: str
    job_no: str
    mobile: str
    park_id: str
    reservation_date: date
    plate_no: str


class ReservationResponse(BaseModel):
    reservation_id: str
    employee_id: str
    name: str
    job_no: str
    mobile: str
    park_id: str
    park_name: str
    plate_no: str
    reservation_date: date
    status: ReservationStatus
    payment_status: PaymentStatus
    created_at: datetime
    updated_at: datetime


class MyReservationsResponse(BaseModel):
    items: List[ReservationResponse]


class CancelResponse(BaseModel):
    message: str
    reservation: ReservationResponse


class PrepayRequest(BaseModel):
    reservation_id: str


class PrepayResponse(BaseModel):
    message: str
    reservation_id: str
    plate_no: str
    park_name: str
    amount: float
    pay_time: datetime


class RealtimeStatusItem(BaseModel):
    park_id: str
    park_name: str
    date: date
    day_type: DayType
    daily_limit: int
    used_count: int
    remain_count: int
    reservation_enabled: bool


class RealtimeStatusResponse(BaseModel):
    items: List[RealtimeStatusItem]


class KetuoSyncStatusResponse(BaseModel):
    reserved_vehicle_count: int
    payment_count: int
    internal_vehicle_count: int


class MessageResponse(BaseModel):
    message: str


class AdminReservationsResponse(BaseModel):
    items: List[ReservationResponse]
    total: int
