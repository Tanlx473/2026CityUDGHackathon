from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import (
    AdminLoginRequest,
    AdminReservationsResponse,
    CancelResponse,
    KetuoSyncStatusResponse,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MyReservationsResponse,
    ParkResponse,
    ParkUpdateRequest,
    PrepayRequest,
    PrepayResponse,
    QuotaRemainResponse,
    QuotaRuleResponse,
    QuotaRuleUpdateRequest,
    RealtimeStatusResponse,
    ReservationCreateRequest,
    ReservationResponse,
)
from .services import AdminService, AuthService, ParkService, PaymentService, QuotaService, ReservationService

app = FastAPI(title="员工临时车辆预约管理系统", version="1.0.0")
bearer_scheme = HTTPBearer()


@app.get("/")
def root() -> MessageResponse:
    return MessageResponse(message="员工临时车辆预约管理系统运行中")


@app.post("/api/auth/login", response_model=LoginResponse)
def employee_login(req: LoginRequest) -> LoginResponse:
    return AuthService.employee_login(req)


@app.post("/api/admin/login", response_model=LoginResponse)
def admin_login(req: AdminLoginRequest) -> LoginResponse:
    return AuthService.admin_login(req)


def get_employee_identity(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    return AuthService.get_identity(credentials.credentials, expected_user_type="employee")


def get_admin_identity(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    return AuthService.get_identity(credentials.credentials, expected_user_type="admin")


@app.get("/api/campuses", response_model=list[ParkResponse])
def list_campuses() -> list[ParkResponse]:
    return ParkService.list_parks()


@app.get("/api/campuses/{campus_id}/config", response_model=ParkResponse)
def get_campus_config(campus_id: str) -> ParkResponse:
    park = ParkService.get_park(campus_id)
    return ParkResponse(
        park_id=park.park_id,
        park_name=park.park_name,
        reservation_enabled=park.reservation_enabled,
        description=park.description,
    )


@app.put("/api/admin/campuses/{campus_id}/config", response_model=ParkResponse)
def update_campus_config(campus_id: str, req: ParkUpdateRequest, identity: dict = Depends(get_admin_identity)) -> ParkResponse:
    return ParkService.update_park(campus_id, req, identity["user_id"])


@app.get("/api/reservations/quota", response_model=QuotaRemainResponse)
def get_quota_remain(campusId: str, date_value: date) -> QuotaRemainResponse:
    return QuotaService.get_remain(campusId, date_value)


@app.post("/api/reservations", response_model=ReservationResponse)
def create_reservation(req: ReservationCreateRequest, identity: dict = Depends(get_employee_identity)) -> ReservationResponse:
    return ReservationService.create(identity["user_id"], req)


@app.get("/api/reservations/my", response_model=MyReservationsResponse)
def my_reservations(identity: dict = Depends(get_employee_identity)) -> MyReservationsResponse:
    return MyReservationsResponse(items=ReservationService.my_reservations(identity["user_id"]))


@app.post("/api/reservations/{reservation_id}/cancel", response_model=CancelResponse)
def cancel_reservation(reservation_id: str, identity: dict = Depends(get_employee_identity)) -> CancelResponse:
    return ReservationService.cancel(identity["user_id"], reservation_id)


@app.post("/api/payments/prepay", response_model=PrepayResponse)
def prepay(req: PrepayRequest, identity: dict = Depends(get_employee_identity)) -> PrepayResponse:
    return PaymentService.prepay(identity["user_id"], req)


@app.get("/api/admin/reservations", response_model=AdminReservationsResponse)
def admin_reservations(
    park_id: Optional[str] = None,
    reservation_date: Optional[date] = None,
    plate_no: Optional[str] = None,
    identity: dict = Depends(get_admin_identity),
) -> AdminReservationsResponse:
    return ReservationService.admin_list(park_id, reservation_date, plate_no)


@app.get("/api/admin/realtime-status", response_model=RealtimeStatusResponse)
def admin_realtime_status(date_value: Optional[date] = None, identity: dict = Depends(get_admin_identity)) -> RealtimeStatusResponse:
    return AdminService.realtime_status(date_value)


@app.get("/api/admin/ketuo-sync-status", response_model=KetuoSyncStatusResponse)
def admin_ketuo_sync_status(identity: dict = Depends(get_admin_identity)) -> KetuoSyncStatusResponse:
    return AdminService.ketuo_sync_status()


@app.get("/api/admin/quota-rules", response_model=list[QuotaRuleResponse])
def list_quota_rules(identity: dict = Depends(get_admin_identity)) -> list[QuotaRuleResponse]:
    return QuotaService.list_rules()


@app.put("/api/admin/quota-rules/{rule_id}", response_model=QuotaRuleResponse)
def update_quota_rule(rule_id: str, req: QuotaRuleUpdateRequest, identity: dict = Depends(get_admin_identity)) -> QuotaRuleResponse:
    return QuotaService.update_rule(rule_id, req, identity["user_id"])
