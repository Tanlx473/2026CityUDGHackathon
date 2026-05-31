from datetime import date
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from .models import (
    Admin,
    AdminLoginRequest,
    AdminReservationsResponse,
    CancelResponse,
    Employee,
    KetuoPayment,
    KetuoReservedVehicle,
    KetuoSyncStatusResponse,
    LoginRequest,
    LoginResponse,
    Park,
    ParkResponse,
    ParkUpdateRequest,
    PrepayRequest,
    PrepayResponse,
    QuotaRemainResponse,
    QuotaRule,
    QuotaRuleResponse,
    QuotaRuleUpdateRequest,
    RealtimeStatusItem,
    RealtimeStatusResponse,
    Reservation,
    ReservationCreateRequest,
    ReservationResponse,
)
from .storage import db
from .utils import detect_day_type, is_valid_mobile, is_valid_plate, new_id, normalize_plate, now, today, verify_password


PREPAY_AMOUNT = 20.0


class AuthService:
    @staticmethod
    def employee_login(req: LoginRequest) -> LoginResponse:
        with db.lock:
            employee = next((e for e in db.employees.values() if e.login_account == req.login_account and e.status == "active"), None)
            if not employee or not verify_password(req.password, employee.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
            token = new_id("emp_token")
            db.tokens[token] = {"user_type": "employee", "user_id": employee.employee_id}
            return LoginResponse(token=token, user_type="employee", user_id=employee.employee_id, name=employee.name)

    @staticmethod
    def admin_login(req: AdminLoginRequest) -> LoginResponse:
        with db.lock:
            admin = next((a for a in db.admins.values() if a.username == req.username and a.status == "active"), None)
            if not admin or not verify_password(req.password, admin.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
            token = new_id("admin_token")
            db.tokens[token] = {"user_type": "admin", "user_id": admin.admin_id}
            return LoginResponse(token=token, user_type="admin", user_id=admin.admin_id, name=admin.username)

    @staticmethod
    def get_identity(token: str, expected_user_type: Optional[str] = None) -> Dict[str, str]:
        with db.lock:
            identity = db.tokens.get(token)
            if not identity:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌无效")
            if expected_user_type and identity["user_type"] != expected_user_type:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
            return identity


class ParkService:
    @staticmethod
    def list_parks() -> List[ParkResponse]:
        with db.lock:
            return [
                ParkResponse(
                    park_id=p.park_id,
                    park_name=p.park_name,
                    reservation_enabled=p.reservation_enabled,
                    description=p.description,
                )
                for p in db.parks.values()
                if p.status == "active"
            ]

    @staticmethod
    def get_park(park_id: str) -> Park:
        park = db.parks.get(park_id)
        if not park or park.status != "active":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="园区不存在")
        return park

    @staticmethod
    def update_park(park_id: str, req: ParkUpdateRequest, admin_id: str) -> ParkResponse:
        with db.lock:
            park = ParkService.get_park(park_id)
            park.reservation_enabled = req.reservation_enabled
            park.description = req.description
            db.parks[park_id] = park
            LoggingService.log("admin", admin_id, "update_park", park_id, f"enabled={req.reservation_enabled}")
            return ParkResponse(
                park_id=park.park_id,
                park_name=park.park_name,
                reservation_enabled=park.reservation_enabled,
                description=park.description,
            )


class QuotaService:
    @staticmethod
    def get_rule(park_id: str, target_date: date) -> QuotaRule:
        day_type = detect_day_type(target_date)
        for rule in db.quota_rules.values():
            if rule.park_id == park_id and rule.day_type == day_type:
                return rule
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配额规则不存在")

    @staticmethod
    def used_count(park_id: str, target_date: date) -> int:
        return sum(
            1
            for r in db.reservations.values()
            if r.park_id == park_id and r.reservation_date == target_date and r.status == "pending_effective"
        )

    @staticmethod
    def get_remain(park_id: str, target_date: date) -> QuotaRemainResponse:
        with db.lock:
            park = ParkService.get_park(park_id)
            rule = QuotaService.get_rule(park_id, target_date)
            used = QuotaService.used_count(park_id, target_date)
            remain = max(rule.daily_limit - used, 0)
            return QuotaRemainResponse(
                park_id=park.park_id,
                park_name=park.park_name,
                date=target_date,
                day_type=rule.day_type,
                daily_limit=rule.daily_limit,
                used_count=used,
                remain_count=remain,
                reservation_enabled=park.reservation_enabled,
                description=park.description,
            )

    @staticmethod
    def list_rules() -> List[QuotaRuleResponse]:
        with db.lock:
            return [
                QuotaRuleResponse(
                    rule_id=r.rule_id,
                    park_id=r.park_id,
                    day_type=r.day_type,
                    daily_limit=r.daily_limit,
                    updated_at=r.updated_at,
                    updated_by=r.updated_by,
                )
                for r in db.quota_rules.values()
            ]

    @staticmethod
    def update_rule(rule_id: str, req: QuotaRuleUpdateRequest, admin_id: str) -> QuotaRuleResponse:
        with db.lock:
            rule = db.quota_rules.get(rule_id)
            if not rule:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配额规则不存在")
            rule.daily_limit = req.daily_limit
            rule.updated_at = now()
            rule.updated_by = admin_id
            db.quota_rules[rule_id] = rule
            LoggingService.log("admin", admin_id, "update_quota_rule", rule_id, f"daily_limit={req.daily_limit}")
            return QuotaRuleResponse(
                rule_id=rule.rule_id,
                park_id=rule.park_id,
                day_type=rule.day_type,
                daily_limit=rule.daily_limit,
                updated_at=rule.updated_at,
                updated_by=rule.updated_by,
            )


class ReservationService:
    @staticmethod
    def _validate_date(target_date: date) -> None:
        current = today()
        if target_date < current:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预约日期不得早于当前日期")
        if (target_date - current).days > 7:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持预约未来7天内日期")

    @staticmethod
    def _validate_employee_match(employee: Employee, req: ReservationCreateRequest) -> None:
        if employee.name != req.name or employee.job_no != req.job_no:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="姓名或工号与登录员工不匹配")
        if employee.mobile != req.mobile:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号与登录员工不匹配")

    @staticmethod
    def _check_plate_conflicts(plate_no: str, target_date: date) -> None:
        normalized = normalize_plate(plate_no)
        for vehicle in db.ketuo_internal_vehicles.values():
            if normalize_plate(vehicle.plate_no) == normalized and vehicle.status == "active":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该车辆已存在内部车辆档案，不能重复预约")
        for reservation in db.reservations.values():
            if normalize_plate(reservation.plate_no) == normalized and reservation.reservation_date == target_date and reservation.status == "pending_effective":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="同一车牌同一天只能预约一个园区")

    @staticmethod
    def create(employee_id: str, req: ReservationCreateRequest) -> ReservationResponse:
        with db.lock:
            employee = db.employees.get(employee_id)
            if not employee or employee.status != "active":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="员工不存在或已停用")
            ReservationService._validate_employee_match(employee, req)
            if not is_valid_mobile(req.mobile):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号格式不正确")
            if not is_valid_plate(req.plate_no):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="车牌号格式不正确")
            ReservationService._validate_date(req.reservation_date)
            park = ParkService.get_park(req.park_id)
            if not park.reservation_enabled:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前园区暂不开放预约")
            rule = QuotaService.get_rule(req.park_id, req.reservation_date)
            if rule.daily_limit == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前园区暂不开放预约")
            ReservationService._check_plate_conflicts(req.plate_no, req.reservation_date)
            used = QuotaService.used_count(req.park_id, req.reservation_date)
            if used >= rule.daily_limit:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当日预约车位已满")

            ts = now()
            reservation = Reservation(
                reservation_id=new_id("res"),
                employee_id=employee.employee_id,
                name=req.name,
                job_no=req.job_no,
                mobile=req.mobile,
                park_id=park.park_id,
                park_name=park.park_name,
                plate_no=normalize_plate(req.plate_no),
                reservation_date=req.reservation_date,
                status="pending_effective",
                payment_status="unpaid",
                created_at=ts,
                updated_at=ts,
            )
            ketuo_record = KetuoReservedVehicle(
                id=new_id("kres"),
                plate_no=reservation.plate_no,
                park_name=park.park_name,
                reservation_date=reservation.reservation_date,
                status="pending_effective",
                remark=f"{reservation.name}/{reservation.job_no}/{reservation.mobile}",
                synced_at=ts,
            )
            db.reservations[reservation.reservation_id] = reservation
            db.ketuo_reserved_vehicles[ketuo_record.id] = ketuo_record
            LoggingService.log("employee", employee.employee_id, "create_reservation", reservation.reservation_id, reservation.plate_no)
            return ReservationService._to_response(reservation)

    @staticmethod
    def my_reservations(employee_id: str) -> List[ReservationResponse]:
        with db.lock:
            items = [r for r in db.reservations.values() if r.employee_id == employee_id]
            items.sort(key=lambda x: (x.reservation_date, x.created_at), reverse=True)
            return [ReservationService._to_response(i) for i in items]

    @staticmethod
    def cancel(employee_id: str, reservation_id: str) -> CancelResponse:
        with db.lock:
            reservation = db.reservations.get(reservation_id)
            if not reservation:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约记录不存在")
            if reservation.employee_id != employee_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅允许取消本人预约")
            if reservation.status == "cancelled":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预约已取消")
            if reservation.status != "pending_effective":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前状态不可取消")
            reservation.status = "cancelled"
            reservation.updated_at = now()
            db.reservations[reservation_id] = reservation
            for record in db.ketuo_reserved_vehicles.values():
                if normalize_plate(record.plate_no) == normalize_plate(reservation.plate_no) and record.park_name == reservation.park_name and record.reservation_date == reservation.reservation_date and record.status == "pending_effective":
                    record.status = "cancelled"
                    record.synced_at = now()
            LoggingService.log("employee", employee_id, "cancel_reservation", reservation_id, reservation.plate_no)
            return CancelResponse(message="预约已取消，车位已释放", reservation=ReservationService._to_response(reservation))

    @staticmethod
    def admin_list(park_id: Optional[str], reservation_date: Optional[date], plate_no: Optional[str]) -> AdminReservationsResponse:
        with db.lock:
            items = list(db.reservations.values())
            if park_id:
                items = [r for r in items if r.park_id == park_id]
            if reservation_date:
                items = [r for r in items if r.reservation_date == reservation_date]
            if plate_no:
                normalized = normalize_plate(plate_no)
                items = [r for r in items if normalize_plate(r.plate_no) == normalized]
            items.sort(key=lambda x: (x.reservation_date, x.created_at), reverse=True)
            responses = [ReservationService._to_response(i) for i in items]
            return AdminReservationsResponse(items=responses, total=len(responses))

    @staticmethod
    def _to_response(reservation: Reservation) -> ReservationResponse:
        return ReservationResponse(
            reservation_id=reservation.reservation_id,
            employee_id=reservation.employee_id,
            name=reservation.name,
            job_no=reservation.job_no,
            mobile=reservation.mobile,
            park_id=reservation.park_id,
            park_name=reservation.park_name,
            plate_no=reservation.plate_no,
            reservation_date=reservation.reservation_date,
            status=reservation.status,
            payment_status=reservation.payment_status,
            created_at=reservation.created_at,
            updated_at=reservation.updated_at,
        )


class PaymentService:
    @staticmethod
    def prepay(employee_id: str, req: PrepayRequest) -> PrepayResponse:
        with db.lock:
            reservation = db.reservations.get(req.reservation_id)
            if not reservation:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约记录不存在")
            if reservation.employee_id != employee_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅允许操作本人预约")
            if reservation.status != "pending_effective":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅有效预约可提前缴费")
            if reservation.payment_status == "paid":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该预约已完成提前缴费")
            pay_time = now()
            payment = KetuoPayment(
                payment_id=new_id("pay"),
                plate_no=reservation.plate_no,
                park_name=reservation.park_name,
                pay_time=pay_time,
                amount=PREPAY_AMOUNT,
                status="success",
            )
            db.ketuo_payments[payment.payment_id] = payment
            reservation.payment_status = "paid"
            reservation.updated_at = pay_time
            db.reservations[reservation.reservation_id] = reservation
            LoggingService.log("employee", employee_id, "prepay", reservation.reservation_id, reservation.plate_no)
            return PrepayResponse(
                message="缴费成功，离厂时无需支付",
                reservation_id=reservation.reservation_id,
                plate_no=reservation.plate_no,
                park_name=reservation.park_name,
                amount=payment.amount,
                pay_time=payment.pay_time,
            )


class AdminService:
    @staticmethod
    def realtime_status(target_date: Optional[date]) -> RealtimeStatusResponse:
        with db.lock:
            check_date = target_date or today()
            items: List[RealtimeStatusItem] = []
            for park in db.parks.values():
                if park.status != "active":
                    continue
                rule = QuotaService.get_rule(park.park_id, check_date)
                used = QuotaService.used_count(park.park_id, check_date)
                items.append(
                    RealtimeStatusItem(
                        park_id=park.park_id,
                        park_name=park.park_name,
                        date=check_date,
                        day_type=rule.day_type,
                        daily_limit=rule.daily_limit,
                        used_count=used,
                        remain_count=max(rule.daily_limit - used, 0),
                        reservation_enabled=park.reservation_enabled,
                    )
                )
            return RealtimeStatusResponse(items=items)

    @staticmethod
    def ketuo_sync_status() -> KetuoSyncStatusResponse:
        with db.lock:
            return KetuoSyncStatusResponse(
                reserved_vehicle_count=len(db.ketuo_reserved_vehicles),
                payment_count=len(db.ketuo_payments),
                internal_vehicle_count=len(db.ketuo_internal_vehicles),
            )


class LoggingService:
    @staticmethod
    def log(operator_type: str, operator_id: str, action: str, target_id: str, detail: str) -> None:
        from .models import OperationLog

        log = OperationLog(
            log_id=new_id("log"),
            operator_type=operator_type,
            operator_id=operator_id,
            action=action,
            target_id=target_id,
            detail=detail,
            created_at=now(),
        )
        db.operation_logs[log.log_id] = log
