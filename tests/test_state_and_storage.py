from __future__ import annotations

import pytest

from app.orchestrator.state import ArtifactRef, BatchState, NodeState
from app.storage.file_store import FileStore


def test_batch_state_serialization_round_trip() -> None:
    state = BatchState.new(batch_id="batch-1", spec_path="docs/待生成/spec.md")
    state.nodes["design"].outputs.append(ArtifactRef(kind="design_md", path="x.md", sha256="abc"))

    restored = BatchState.model_validate(state.model_dump(mode="json"))

    assert restored.batch_id == "batch-1"
    assert restored.nodes["design"].outputs[0].kind == "design_md"
    assert isinstance(restored.nodes["code"], NodeState)


def test_file_store_write_and_read(tmp_path) -> None:
    store = FileStore(tmp_path)
    path = tmp_path / "docs" / "已生成" / "b1" / "artifact.json"

    ref = store.write_json(path, {"hello": "world"})

    assert ref.path == "docs/已生成/b1/artifact.json"
    assert store.read_json(path) == {"hello": "world"}
    assert len(ref.sha256) == 64


def test_business_storage_persists_seed_and_updates_to_csv(tmp_path) -> None:
    storage = pytest.importorskip("src.storage", reason="Current generated src/ tree does not expose src.storage")
    if not hasattr(storage, "InMemoryDB"):
        pytest.skip("Current generated src.storage does not expose InMemoryDB")
    InMemoryDB = storage.InMemoryDB
    db = InMemoryDB(tmp_path)

    assert (tmp_path / "employees.csv").exists()
    assert (tmp_path / "parks.csv").exists()

    park = db.parks["park_weifang"]
    park.reservation_enabled = False
    park.description = "CSV persisted description"
    db.parks[park.park_id] = park

    restored = InMemoryDB(tmp_path)

    assert restored.parks["park_weifang"].reservation_enabled is False
    assert restored.parks["park_weifang"].description == "CSV persisted description"
