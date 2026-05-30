from __future__ import annotations

from typing import Any

from app.orchestrator.state import ExecutionLogEntry, NodeId
from app.storage.file_store import FileStore


class ExecutionLogger:
    def __init__(self, store: FileStore) -> None:
        self.store = store

    def log(
        self,
        *,
        batch_id: str,
        event: str,
        message: str,
        node_id: NodeId | None = None,
        level: str = "INFO",
        duration_ms: int | None = None,
        retry_index: int = 0,
        error_class: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_metadata = {k: v for k, v in (metadata or {}).items() if "key" not in k.lower() and "token" not in k.lower()}
        entry = ExecutionLogEntry(
            batch_id=batch_id,
            node_id=node_id,
            event=event,
            level=level,  # type: ignore[arg-type]
            message=message,
            duration_ms=duration_ms,
            retry_index=retry_index,
            error_class=error_class,
            metadata=safe_metadata,
        )
        self.store.append_log(entry)
