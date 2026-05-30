from __future__ import annotations

import importlib
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.storage.file_store import FileStore


class ValidationError(RuntimeError):
    pass


class DesignArtifactValidator:
    REQUIRED_FIELDS = {
        "system_name",
        "modules",
        "entities",
        "business_rules",
        "api_endpoints",
        "csv_tables",
        "validation_rules",
    }

    def __init__(self, store: FileStore) -> None:
        self.store = store

    def validate(self, batch_id: str) -> dict[str, Any]:
        base = self.store.batch_dir(batch_id) / "概要设计"
        overview = base / "overview_design.md"
        manifest = base / "design_manifest.json"
        if not overview.exists() or not overview.read_text(encoding="utf-8").strip():
            raise ValidationError("overview_design.md is missing or empty")
        if not manifest.exists():
            raise ValidationError("design_manifest.json is missing")
        data = self.store.read_json(manifest)
        missing = self.REQUIRED_FIELDS - set(data)
        if missing:
            raise ValidationError(f"design_manifest.json missing fields: {sorted(missing)}")
        return {"validator": "design", "ok": True}


class CodeValidator:
    CORE_MODULES = ["src.csv_repository", "src.models", "src.services", "src.api"]

    def __init__(self, store: FileStore) -> None:
        self.store = store

    def validate(self, batch_id: str) -> dict[str, Any]:
        src_dir = self.store.root_dir / "src"
        if not src_dir.exists():
            raise ValidationError("src/ does not exist")
        python_files = sorted(src_dir.glob("*.py"))
        names = {path.name for path in python_files}
        required = {"__init__.py", "csv_repository.py", "models.py", "services.py", "api.py"}
        missing = required - names
        if missing:
            raise ValidationError(f"src/ missing required files: {sorted(missing)}")
        for path in python_files:
            py_compile.compile(str(path), doraise=True)
        for module in self.CORE_MODULES:
            importlib.invalidate_caches()
            importlib.import_module(module)
        return {"validator": "code", "ok": True, "files": [path.name for path in python_files]}


class TestValidator:
    def __init__(self, store: FileStore) -> None:
        self.store = store

    def validate(self, batch_id: str) -> dict[str, Any]:
        tests_dir = self.store.root_dir / "tests"
        if not tests_dir.exists():
            raise ValidationError("tests/ does not exist")
        target = tests_dir / "test_business_reservation.py"
        if not target.exists():
            raise ValidationError("generated business test file is missing")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_business_reservation.py",
            "--cov=src",
            "--cov-branch",
            "--cov-report=term-missing",
        ]
        completed = subprocess.run(command, cwd=self.store.root_dir, text=True, capture_output=True, timeout=60)
        if completed.returncode != 0:
            raise ValidationError((completed.stdout + "\n" + completed.stderr).strip())
        return {"validator": "test", "ok": True, "summary": completed.stdout[-2000:]}


def validate_batch_smoke(store: FileStore, batch_id: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    results["design"] = DesignArtifactValidator(store).validate(batch_id)
    results["code"] = CodeValidator(store).validate(batch_id)
    test_plan = store.batch_dir(batch_id) / "单元测试" / "test_plan.md"
    results["test_plan_exists"] = test_plan.exists() and bool(test_plan.read_text(encoding="utf-8").strip())
    return results
