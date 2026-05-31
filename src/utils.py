import hashlib
import re
import uuid
from datetime import date, datetime


PLATE_PATTERN = re.compile(
    r"^[\u4e00-\u9fa5][A-Z][A-Z0-9]{5}([A-Z0-9])?$"
)
MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def today() -> date:
    return date.today()


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_password(raw: str, hashed: str) -> bool:
    return hash_password(raw) == hashed


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_plate(plate_no: str) -> str:
    return plate_no.strip().upper()


def is_valid_plate(plate_no: str) -> bool:
    return bool(PLATE_PATTERN.match(normalize_plate(plate_no)))


def is_valid_mobile(mobile: str) -> bool:
    return bool(MOBILE_PATTERN.match(mobile.strip()))


def detect_day_type(target_date: date) -> str:
    return "restday" if target_date.weekday() >= 5 else "workday"
