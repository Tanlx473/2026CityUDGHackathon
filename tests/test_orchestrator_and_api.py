from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.llm import MockLLMAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.api import main as api_main
from app.orchestrator.engine import Orchestrator
from app.storage.file_store import FileStore
from src import api as business_api
from src.services import ReservationService


def test_mock_llm_adapter_runs_without_api_key() -> None:
    adapter = MockLLMAdapter()
    text = adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})

    assert "High-Level Design" in text


def test_openai_adapter_falls_back_without_key() -> None:
    adapter = OpenAIAdapter(fallback=MockLLMAdapter())

    assert adapter.available is False
    assert "High-Level Design" in adapter.generate_text(system="x", user="y", metadata={"node_id": "design"})


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


def test_business_api_endpoints(tmp_path: Path, monkeypatch) -> None:
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
