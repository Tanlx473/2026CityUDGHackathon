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
        return {
            "validator": "design",
            "passed": True,
            "score": 100,
            "checks": {
                "overview_design_non_empty": True,
                "manifest_exists": True,
                "required_fields_present": True,
            },
        }


class CodeValidator:
    REQUIRED_FILES = {"__init__.py", "api.py"}

    def __init__(self, store: FileStore) -> None:
        self.store = store

    def validate(self, batch_id: str) -> dict[str, Any]:
        src_dir = self.store.root_dir / "src"
        if not src_dir.exists():
            raise ValidationError("src/ does not exist")
        python_files = sorted(src_dir.rglob("*.py"))
        names = {path.name for path in src_dir.glob("*.py")}
        missing = self.REQUIRED_FILES - names
        if missing:
            raise ValidationError(f"src/ missing required files: {sorted(missing)}")
        for path in python_files:
            py_compile.compile(str(path), doraise=True)
        root = str(self.store.root_dir)
        inserted = False
        if root not in sys.path:
            sys.path.insert(0, root)
            inserted = True
        previous_modules = {name: module for name, module in sys.modules.items() if name == "src" or name.startswith("src.")}
        for name in previous_modules:
            sys.modules.pop(name, None)
        try:
            importlib.invalidate_caches()
            module = importlib.import_module("src.api")
            if not hasattr(module, "app"):
                raise ValidationError("src.api must expose a FastAPI app variable named app")
        finally:
            for name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
                sys.modules.pop(name, None)
            sys.modules.update(previous_modules)
            if inserted:
                try:
                    sys.path.remove(root)
                except ValueError:
                    pass
        return {
            "validator": "code",
            "passed": True,
            "score": 100,
            "checks": {
                "src_exists": True,
                "required_files_present": True,
                "py_compile_passed": True,
                "fastapi_app_importable": True,
            },
            "files": [path.name for path in python_files],
        }


class TestValidator:
    def __init__(self, store: FileStore) -> None:
        self.store = store

    def validate(self, batch_id: str) -> dict[str, Any]:
        generated_dir = self.store.root_dir / "tests" / "generated"
        if not generated_dir.exists():
            raise ValidationError("tests/generated/ does not exist")
        targets = sorted(path for path in generated_dir.rglob("test_*.py") if path.is_file())
        if not targets:
            raise ValidationError("generated pytest files are missing")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/generated",
            "--cov=src",
            "--cov-branch",
            "--cov-fail-under=80",
            "--cov-report=term-missing",
        ]
        completed = subprocess.run(command, cwd=self.store.root_dir, text=True, capture_output=True, timeout=60)
        if completed.returncode != 0:
            raise ValidationError((completed.stdout + "\n" + completed.stderr).strip())
        return {
            "validator": "test",
            "passed": True,
            "score": 100,
            "coverage_threshold": 80,
            "checks": {
                "generated_tests_exist": True,
                "pytest_passed": True,
                "coverage_threshold_passed": True,
            },
            "summary": completed.stdout[-2000:],
        }


def validate_batch_smoke(store: FileStore, batch_id: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    results["design"] = DesignArtifactValidator(store).validate(batch_id)
    results["code"] = CodeValidator(store).validate(batch_id)
    test_plan = store.batch_dir(batch_id) / "单元测试" / "test_plan.md"
    results["test_plan_exists"] = test_plan.exists() and bool(test_plan.read_text(encoding="utf-8").strip())
    return results
