from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm import LLMError, MockLLMAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.agents.design_agent import DesignManifest
from app.api import main as api_main
from app.config import Settings, get_settings
from app.orchestrator.engine import Orchestrator
from app.storage.file_store import FileStore


def test_mock_llm_adapter_runs_without_api_key() -> None:
    adapter = MockLLMAdapter()
    text = adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})

    assert "High-Level Design" in text


def test_openai_adapter_falls_back_without_key() -> None:
    adapter = OpenAIAdapter(settings=Settings(), fallback=MockLLMAdapter())

    assert adapter.available is False
    assert "High-Level Design" in adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})


def test_openai_adapter_strict_mode_fails_without_model_or_key() -> None:
    adapter = OpenAIAdapter(settings=Settings(llm_strict=True), fallback=MockLLMAdapter())

    with pytest.raises(LLMError):
        adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})


def test_settings_default_to_strict_when_api_key_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("LLM_STRICT", raising=False)
    get_settings.cache_clear()

    try:
        assert get_settings().llm_strict is True
    finally:
        get_settings.cache_clear()


class FakeChatCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        message = type("Message", (), {"content": '{"system_name": "Demo", "modules": [], "entities": [], "business_rules": [], "api_endpoints": [], "csv_tables": [], "validation_rules": []}'})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeChatCompletions()


class FakeOpenAICompatibleClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


class FailingChatCompletions:
    def create(self, **kwargs):
        raise RuntimeError("api unavailable")


class FailingChat:
    def __init__(self) -> None:
        self.completions = FailingChatCompletions()


class FailingOpenAICompatibleClient:
    def __init__(self) -> None:
        self.chat = FailingChat()


def test_openai_compatible_base_url_uses_chat_completions() -> None:
    adapter = OpenAIAdapter(
        settings=Settings(
            openai_api_key="test-key",
            openai_base_url="https://api.deepseek.com",
            design_model="deepseek-v4-flash",
            llm_strict=True,
        ),
        fallback=MockLLMAdapter(),
    )
    adapter._client = FakeOpenAICompatibleClient()

    result = adapter.generate_json(
        system="x",
        user="y",
        schema=DesignManifest,
        metadata={"node_id": "design"},
    )

    assert result.system_name == "Demo"
    assert adapter.provider_name == "openai-compatible"
    assert adapter._client.chat.completions.calls == 1


def test_openai_adapter_strict_mode_does_not_hide_api_errors() -> None:
    adapter = OpenAIAdapter(
        settings=Settings(
            openai_api_key="test-key",
            openai_base_url="https://api.deepseek.com",
            design_model="deepseek-v4-flash",
            llm_strict=True,
        ),
        fallback=MockLLMAdapter(),
    )
    adapter._client = FailingOpenAICompatibleClient()

    with pytest.raises(LLMError, match="OpenAI JSON generation failed"):
        adapter.generate_json(system="x", user="y", schema=DesignManifest, metadata={"node_id": "design"})


def test_openai_adapter_records_fallback_when_non_strict_api_call_fails() -> None:
    adapter = OpenAIAdapter(
        settings=Settings(
            openai_api_key="test-key",
            openai_base_url="https://api.deepseek.com",
            design_model="deepseek-v4-flash",
            llm_strict=False,
        ),
        fallback=MockLLMAdapter(),
    )
    adapter._client = FailingOpenAICompatibleClient()

    text = adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})

    assert "High-Level Design" in text
    assert adapter.last_call_metadata["llm_provider"] == "mock"
    assert adapter.last_call_metadata["llm_fallback_used"] is True
    assert "api unavailable" in adapter.last_call_metadata["llm_fallback_reason"]


def test_fastapi_health_works() -> None:
    client = TestClient(api_main.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_platform_api_create_run_status_logs_artifacts_and_validate(tmp_path: Path, monkeypatch) -> None:
    store = FileStore(tmp_path)
    orchestrator = Orchestrator(store=store, llm=MockLLMAdapter(), max_retries=0)
    monkeypatch.setattr(api_main, "store", store)
    monkeypatch.setattr(api_main, "orchestrator", orchestrator)
    client = TestClient(api_main.app)

    create_response = client.post(
        "/api/v1/batches",
        files={"file": ("spec.md", b"# Employee Temporary Vehicle Reservation System", "text/markdown")},
        data={"mode": "auto"},
    )
    assert create_response.status_code == 200
    batch_id = create_response.json()["batch_id"]

    run_response = client.post(f"/api/v1/batches/{batch_id}/run")
    assert run_response.status_code == 202
    state_response = client.get(f"/api/v1/batches/{batch_id}")
    assert state_response.json()["status"] == "succeeded"
    assert client.get(f"/api/v1/batches/{batch_id}/logs").json()
    artifacts = client.get(f"/api/v1/batches/{batch_id}/artifacts").json()
    assert any(item["path"].endswith("overview_design.md") for item in artifacts)
    validate_response = client.post("/api/v1/validate", json={"batch_id": batch_id})
    assert validate_response.status_code == 200
    retry_response = client.post(f"/api/v1/batches/{batch_id}/retry/design")
    assert retry_response.status_code == 202
    assert retry_response.json() == {"batch_id": batch_id, "node_id": "design", "status": "accepted"}


def test_business_api_endpoints(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("src.csv_repository", reason="Template business app is not the current generated src/ tree")
    from src import api as business_api
    from src.services import ReservationService

    monkeypatch.setattr(business_api, "service", ReservationService(tmp_path))
    client = TestClient(business_api.app)

    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/campuses").json()) == 4
    assert client.get("/reservations").json() == []


def test_orchestrator_state_transitions(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    orchestrator = Orchestrator(store=store, llm=MockLLMAdapter(), max_retries=1)
    state = orchestrator.create_batch_from_bytes(filename="spec.md", content=b"# Vehicle reservation", mode="auto")

    finished = orchestrator.run_batch(state.batch_id)

    assert finished.status == "succeeded"
    assert finished.nodes["design"].status == "succeeded"
    assert finished.nodes["code"].status == "succeeded"
    assert finished.nodes["test"].status == "succeeded"
    assert store.status_path(state.batch_id).exists()
    assert store.log_path(state.batch_id).exists()


class DynamicGenerationLLM(MockLLMAdapter):
    def generate_json(self, *, system: str, user: str, schema, metadata: dict[str, str] | None = None):
        node_id = (metadata or {}).get("node_id")
        if node_id == "code":
            return schema.model_validate(
                {
                    "files": [
                        {"path": "src/__init__.py", "content": '"""Generated app."""\n'},
                        {
                            "path": "src/api.py",
                            "content": (
                                "from fastapi import FastAPI\n\n"
                                "app = FastAPI(title='Dynamic Demo')\n\n"
                                "@app.get('/health')\n"
                                "def health():\n"
                                "    return {'status': 'ok', 'source': 'dynamic'}\n"
                            ),
                        },
                    ],
                    "manifest": {"system_name": "Dynamic Demo", "strategy": "test-dynamic"},
                }
            )
        if node_id == "test":
            return schema.model_validate(
                {
                    "files": [
                        {
                            "path": "tests/generated/test_dynamic_api.py",
                            "content": (
                                "from fastapi.testclient import TestClient\n"
                                "from src.api import app\n\n"
                                "def test_health():\n"
                                "    assert TestClient(app).get('/health').json()['source'] == 'dynamic'\n"
                            ),
                        }
                    ],
                    "test_plan_markdown": "# Test Plan\n\n- Validate dynamic health endpoint.\n",
                }
            )
        return super().generate_json(system=system, user=user, schema=schema, metadata=metadata)


def test_orchestrator_uses_structured_llm_for_code_and_tests(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    orchestrator = Orchestrator(store=store, llm=DynamicGenerationLLM(), max_retries=0)
    state = orchestrator.create_batch_from_bytes(filename="spec.md", content=b"# Dynamic Demo", mode="auto")

    finished = orchestrator.run_batch(state.batch_id)

    assert finished.status == "succeeded"
    assert "source': 'dynamic'" in (tmp_path / "src" / "api.py").read_text(encoding="utf-8")
    assert (tmp_path / "tests" / "generated" / "test_dynamic_api.py").exists()


class FlakyDesignLLM(MockLLMAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, system: str, user: str, metadata: dict[str, str] | None = None) -> str:
        if (metadata or {}).get("node_id") == "design":
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary design failure")
        return super().generate_text(system=system, user=user, metadata=metadata)


def test_failed_node_retry_logic(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    llm = FlakyDesignLLM()
    orchestrator = Orchestrator(store=store, llm=llm, max_retries=1)
    state = orchestrator.create_batch_from_bytes(filename="spec.md", content=b"# Vehicle reservation", mode="auto")

    finished = orchestrator.run_batch(state.batch_id)

    assert finished.status == "succeeded"
    assert finished.nodes["design"].retries == 1
    logs = store.read_json(store.log_path(state.batch_id))
    assert any(entry["event"] == "node_failed" for entry in logs)
    assert any(entry["event"] == "node_retry_scheduled" for entry in logs)
