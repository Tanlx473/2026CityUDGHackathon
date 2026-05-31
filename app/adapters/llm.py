from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMAdapter(Protocol):
    def generate_text(self, *, system: str, user: str, metadata: dict[str, str] | None = None) -> str:
        ...

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        metadata: dict[str, str] | None = None,
    ) -> SchemaT:
        ...


class LLMError(RuntimeError):
    """Clear wrapper for model-call failures."""


class MockLLMAdapter:
    """Deterministic adapter for demos and tests without an API key."""

    def generate_text(self, *, system: str, user: str, metadata: dict[str, str] | None = None) -> str:
        node_id = (metadata or {}).get("node_id", "")
        if node_id == "test":
            return (
                "# Test Plan\n\n"
                "- Validate CSV repository initialization, append, query, and update.\n"
                "- Validate reservation success, quota limits, date window, duplicate plate, disabled campus, cancellation, and payment.\n"
                "- Tests use only local temporary CSV files and never call an LLM.\n"
            )
        return (
            "# High-Level Design\n\n"
            "The generated business application is a FastAPI service for employee temporary vehicle reservations. "
            "It uses CSV files as the persistence layer, keeps campus quota configuration in data files, "
            "and exposes reservation, cancellation, payment, and query operations.\n\n"
            "## Modules\n\n"
            "- CSV repository with atomic writes.\n"
            "- Reservation service implementing campus, quota, plate, and date validation.\n"
            "- FastAPI router for business operations.\n"
            "- Pytest suite covering core business rules.\n"
        )

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        metadata: dict[str, str] | None = None,
    ) -> SchemaT:
        payload: dict[str, Any] = {
            "system_name": "Employee Temporary Vehicle Reservation System",
            "modules": ["campus configuration", "reservation application", "cancellation", "advance payment", "ketuo mock"],
            "entities": ["CampusConfig", "Reservation", "KetuoReservationArchive", "PaymentRecord", "InternalVehicleArchive"],
            "business_rules": [
                "Reservations are allowed only within the next 7 days.",
                "A reservation is limited to one day and one campus.",
                "Daily reservations must not exceed campus quota.",
                "The same plate number can reserve only one campus on the same day.",
                "Disabled campuses return 当前园区暂不开放预约.",
                "Cancellation releases occupied quota and invalidates the Ketuo mock record.",
            ],
            "api_endpoints": [
                "GET /health",
                "POST /reservations",
                "POST /reservations/{reservation_id}/cancel",
                "POST /reservations/{reservation_id}/pay",
                "GET /reservations",
                "GET /campuses",
            ],
            "csv_tables": [
                "data/campus_configs.csv",
                "data/reservations.csv",
                "data/ketuo_reservation_archive.csv",
                "data/payment_records.csv",
                "data/internal_vehicle_archive.csv",
            ],
            "validation_rules": ["date_window", "campus_enabled", "daily_quota", "plate_format", "duplicate_plate"],
            "frontend_requirements": [
                "Employee reservation form with name, employee ID, mobile, campus, date, and plate fields.",
                "Reservation list with cancel and advance payment actions.",
                "Admin view for campus quota and enabled status.",
            ],
            "pages": ["Employee reservation page", "My reservations page", "Admin campus configuration page"],
            "acceptance_criteria": [
                "A browser-accessible frontend exists when the specification requires Web/B/S access.",
                "Successful reservation writes local CSV records and Ketuo mock archive data.",
                "Cancellation releases quota and updates the Ketuo mock archive status.",
            ],
        }
        return schema.model_validate(payload)
