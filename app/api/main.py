from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.orchestrator.engine import Orchestrator
from app.orchestrator.state import NodeId
from app.storage.file_store import FileStore
from app.validators.artifacts import validate_batch_smoke


app = FastAPI(title="AI Agent Development Pipeline API")
store = FileStore()
orchestrator = Orchestrator(store=store)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-agent-development-pipeline"}


@app.post("/api/v1/batches")
async def create_batch(file: UploadFile = File(...), mode: str = Form("auto")) -> dict[str, object]:
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail={"message": "Please upload a Markdown .md file"})
    if mode not in {"auto", "manual"}:
        raise HTTPException(status_code=400, detail={"message": "mode must be auto or manual"})
    content = await file.read()
    if not content.strip():
        raise HTTPException(status_code=400, detail={"message": "Uploaded specification is empty"})
    state = orchestrator.create_batch_from_bytes(filename=file.filename, content=content, mode=mode)  # type: ignore[arg-type]
    return {"batch_id": state.batch_id, "state": state.model_dump(mode="json")}


@app.post("/api/v1/batches/{batch_id}/run", status_code=202)
def run_batch(batch_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    _load_state_or_404(batch_id)
    background_tasks.add_task(orchestrator.run_batch, batch_id)
    return {"batch_id": batch_id, "status": "accepted"}


@app.get("/api/v1/batches/{batch_id}")
def get_batch(batch_id: str) -> dict[str, object]:
    state = _load_state_or_404(batch_id)
    return state.model_dump(mode="json")


@app.get("/api/v1/batches/{batch_id}/logs")
def get_logs(batch_id: str) -> list[dict[str, object]]:
    _load_state_or_404(batch_id)
    path = store.log_path(batch_id)
    if not path.exists():
        return []
    return store.read_json(path)


@app.get("/api/v1/batches/{batch_id}/artifacts")
def get_artifacts(batch_id: str) -> list[dict[str, str]]:
    _load_state_or_404(batch_id)
    return store.list_artifacts(batch_id)


@app.get("/api/v1/batches/{batch_id}/download")
def download_artifact(batch_id: str, path: str) -> FileResponse:
    _load_state_or_404(batch_id)
    target = store.resolve(path)
    batch_root = store.batch_dir(batch_id).resolve()
    if batch_root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail={"message": "Artifact not found"})
    return FileResponse(target, filename=target.name)


@app.post("/api/v1/batches/{batch_id}/advance", status_code=202)
def advance_batch(batch_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    state = _load_state_or_404(batch_id)
    if state.mode != "manual":
        raise HTTPException(status_code=400, detail={"message": "advance is only available for manual mode batches"})
    if state.status != "paused":
        raise HTTPException(status_code=400, detail={"message": f"Batch is not paused (status: {state.status})"})
    background_tasks.add_task(orchestrator.advance_node, batch_id)
    return {"batch_id": batch_id, "node_id": state.current_node, "status": "accepted"}


@app.post("/api/v1/batches/{batch_id}/retry/{node_id}", status_code=202)
def retry_node(batch_id: str, node_id: NodeId, background_tasks: BackgroundTasks) -> dict[str, str]:
    _load_state_or_404(batch_id)
    background_tasks.add_task(orchestrator.retry_node, batch_id, node_id)
    return {"batch_id": batch_id, "node_id": node_id, "status": "accepted"}


@app.post("/api/v1/validate")
def validate(payload: dict[str, str]) -> dict[str, object]:
    batch_id = payload.get("batch_id")
    if not batch_id:
        raise HTTPException(status_code=400, detail={"message": "batch_id is required"})
    _load_state_or_404(batch_id)
    try:
        return {"batch_id": batch_id, "validation": validate_batch_smoke(store, batch_id)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_class": exc.__class__.__name__}) from exc


def _load_state_or_404(batch_id: str):
    try:
        return store.load_state(batch_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail={"message": "Batch not found"}) from exc
