from __future__ import annotations

import shutil
from textwrap import dedent
from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent


BUSINESS_TEST = r'''
from __future__ import annotations

from datetime import date, timedelta

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
'''


class GeneratedTestFile(BaseModel):
    path: str = Field(pattern=r"^tests/generated/test_.+\.py$", description="Project-relative pytest file under tests/generated/")
    content: str = Field(min_length=1, description="Complete pytest file contents")


class TestGenerationResult(BaseModel):
    files: list[GeneratedTestFile] = Field(min_length=1)
    test_plan_markdown: str = Field(min_length=1)


class TestAgent(BaseAgent):
    agent_name = "TestAgent"
    prompt_file = "test_agent.md"

    def run(self, input_context: dict[str, str]) -> list[object]:
        batch_id = input_context["batch_id"]
        spec_path = input_context["spec_path"]
        result = self._generate_tests(batch_id=batch_id, spec_path=spec_path)
        generated_dir = self.store.root_dir / "tests" / "generated"
        if generated_dir.exists():
            shutil.rmtree(generated_dir)
        generated_dir.mkdir(parents=True, exist_ok=True)
        init_ref = self.store.write_text(generated_dir / "__init__.py", "")
        test_refs = [init_ref]
        for generated_file in result.files:
            target = self._safe_test_path(generated_file.path)
            test_refs.append(self.store.write_text(target, generated_file.content))

        output_dir = self.batch_artifact_dir(batch_id, "单元测试")
        plan_ref = self.store.write_text(output_dir / "test_plan.md", result.test_plan_markdown)

        snapshot_dir = output_dir / "tests_snapshot"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        shutil.copytree(generated_dir, snapshot_dir)
        snapshot_refs = [
            self.store.artifact_for(path, kind="tests_snapshot")
            for path in sorted(snapshot_dir.rglob("*.py"))
            if path.is_file()
        ]
        return [*test_refs, plan_ref, *snapshot_refs]

    def _generate_tests(self, *, batch_id: str, spec_path: str) -> TestGenerationResult:
        prompt = self.load_prompt()
        spec_text = self.read_text(spec_path)
        overview = self._optional_batch_text(batch_id, "概要设计", "overview_design.md")
        design_manifest = self._optional_batch_text(batch_id, "概要设计", "design_manifest.json")
        code_manifest = self._optional_batch_text(batch_id, "代码生成", "code_manifest.json")
        source_files = self._source_context()
        user = (
            "Generate deterministic pytest tests for the generated FastAPI application.\n"
            "Return JSON only. Every test file path must be under tests/generated/.\n"
            "Generate a complete replacement test suite for the current generated src/ tree; do not assume any previous tests exist.\n"
            "Tests must use only local temporary files and FastAPI TestClient where useful.\n"
            "Do not call external APIs, shell commands, or network services.\n\n"
            f"# Product specification\n{spec_text}\n\n"
            f"# Design overview\n{overview}\n\n"
            f"# Design manifest\n{design_manifest}\n\n"
            f"# Code manifest\n{code_manifest}\n\n"
            f"# Generated source files\n{source_files}\n"
        )
        metadata = {"batch_id": batch_id, "node_id": "test"}
        try:
            return self.llm.generate_json(system=prompt, user=user, schema=TestGenerationResult, metadata=metadata)
        except Exception:
            if self._strict_mode():
                raise
            return self._template_generation_result()

    def _strict_mode(self) -> bool:
        adapter_settings = getattr(self.llm, "settings", None)
        return bool(adapter_settings is not None and getattr(adapter_settings, "llm_strict", False))

    def _optional_batch_text(self, batch_id: str, dirname: str, filename: str) -> str:
        path = self.store.batch_dir(batch_id) / dirname / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _source_context(self) -> str:
        src_dir = self.store.root_dir / "src"
        chunks = []
        for path in sorted(src_dir.rglob("*.py")):
            relative = path.relative_to(self.store.root_dir).as_posix()
            chunks.append(f"## {relative}\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(chunks)

    def _safe_test_path(self, generated_path: str) -> Path:
        candidate = Path(generated_path)
        if candidate.is_absolute():
            raise ValueError(f"Generated path must be relative: {generated_path}")
        if any(part in {"..", "", ".git"} for part in candidate.parts):
            raise ValueError(f"Unsafe generated path: {generated_path}")
        if len(candidate.parts) < 3 or candidate.parts[:2] != ("tests", "generated"):
            raise ValueError(f"Generated test path must be under tests/generated/: {generated_path}")
        target = (self.store.root_dir / candidate).resolve()
        test_root = (self.store.root_dir / "tests" / "generated").resolve()
        if target != test_root and test_root not in target.parents:
            raise ValueError(f"Generated test path escapes tests/generated/: {generated_path}")
        if target.suffix != ".py" or not target.name.startswith("test_"):
            raise ValueError(f"Generated test file must be a test_*.py file: {generated_path}")
        return target

    def _template_generation_result(self) -> TestGenerationResult:
        return TestGenerationResult(
            files=[
                GeneratedTestFile(
                    path="tests/generated/test_business_reservation.py",
                    content=dedent(BUSINESS_TEST).lstrip("\n"),
                )
            ],
            test_plan_markdown=(
                "# Test Plan\n\n"
                "- Validate CSV repository initialization, append, query, and update.\n"
                "- Validate reservation success, quota limits, date window, duplicate plate, disabled campus, cancellation, and payment.\n"
                "- Tests use only local temporary CSV files and never call an LLM.\n"
            ),
        )
