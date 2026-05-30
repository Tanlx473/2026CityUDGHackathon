from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Literal

from app.adapters.llm import LLMAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.agents.code_agent import CodeAgent
from app.agents.design_agent import DesignAgent
from app.agents.test_agent import TestAgent
from app.config import get_settings
from app.orchestrator.logger import ExecutionLogger
from app.orchestrator.state import ArtifactRef, BatchState, NodeId, now_iso
from app.storage.file_store import FileStore
from app.validators.artifacts import CodeValidator, DesignArtifactValidator, TestValidator


NODE_ORDER: list[NodeId] = ["design", "code", "test"]


class Orchestrator:
    def __init__(self, *, store: FileStore | None = None, llm: LLMAdapter | None = None, max_retries: int | None = None) -> None:
        self.store = store or FileStore()
        self.llm = llm or OpenAIAdapter()
        self.max_retries = get_settings().max_retries if max_retries is None else max_retries
        self.logger = ExecutionLogger(self.store)

    def create_batch_from_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        mode: Literal["auto", "manual"] = "auto",
    ) -> BatchState:
        batch_id = self._new_batch_id()
        spec_path = self.store.save_uploaded_spec(batch_id=batch_id, filename=filename, content=content)
        state = BatchState.new(batch_id=batch_id, spec_path=self.store.relpath(spec_path), mode=mode)
        self.store.batch_dir(batch_id)
        self.store.save_state(state)
        self.store.init_logs(batch_id)
        self.logger.log(batch_id=batch_id, event="batch_created", message="Batch created", metadata={"mode": mode})
        return state

    def create_batch_from_path(self, spec_path: Path, mode: Literal["auto", "manual"] = "auto") -> BatchState:
        batch_id = self._new_batch_id()
        copied = self.store.copy_spec(batch_id=batch_id, source_path=spec_path)
        state = BatchState.new(batch_id=batch_id, spec_path=self.store.relpath(copied), mode=mode)
        self.store.batch_dir(batch_id)
        self.store.save_state(state)
        self.store.init_logs(batch_id)
        self.logger.log(batch_id=batch_id, event="batch_created", message="Batch created", metadata={"mode": mode})
        return state

    def run_batch(self, batch_id: str) -> BatchState:
        state = self.store.load_state(batch_id)
        state.status = "running"
        self.store.save_state(state)
        self.logger.log(batch_id=batch_id, event="batch_started", message="Automatic pipeline started")
        for node_id in NODE_ORDER:
            state = self._execute_node_with_retries(state, node_id)
            if state.nodes[node_id].status == "failed":
                state.status = "failed"
                state.current_node = node_id
                self.store.save_state(state)
                return state
        state.status = "succeeded"
        state.current_node = None
        self.store.save_state(state)
        self.logger.log(batch_id=batch_id, event="batch_succeeded", message="Pipeline completed successfully")
        return state

    def retry_node(self, batch_id: str, node_id: NodeId) -> BatchState:
        state = self.store.load_state(batch_id)
        if node_id not in NODE_ORDER:
            raise ValueError(f"Unsupported node_id: {node_id}")
        start_index = NODE_ORDER.index(node_id)
        for downstream in NODE_ORDER[start_index:]:
            node = state.nodes[downstream]
            node.status = "queued"
            node.started_at = None
            node.finished_at = None
            node.error_message = None
            if downstream != node_id:
                node.retries = 0
                node.outputs = []
        state.status = "running"
        state.current_node = node_id
        self.store.save_state(state)
        self.logger.log(batch_id=batch_id, node_id=node_id, event="node_retry_requested", message=f"Retry requested for {node_id}")
        for current in NODE_ORDER[start_index:]:
            state = self._execute_node_with_retries(state, current)
            if state.nodes[current].status == "failed":
                state.status = "failed"
                state.current_node = current
                self.store.save_state(state)
                return state
        state.status = "succeeded"
        state.current_node = None
        self.store.save_state(state)
        return state

    def _execute_node_with_retries(self, state: BatchState, node_id: NodeId) -> BatchState:
        while True:
            state = self._execute_node_once(state, node_id)
            node = state.nodes[node_id]
            if node.status == "succeeded":
                return state
            if node.retries >= self.max_retries:
                return state
            node.retries += 1
            node.status = "queued"
            self.store.save_state(state)
            self.logger.log(
                batch_id=state.batch_id,
                node_id=node_id,
                event="node_retry_scheduled",
                message=f"Retrying {node_id}",
                level="WARNING",
                retry_index=node.retries,
            )

    def _execute_node_once(self, state: BatchState, node_id: NodeId) -> BatchState:
        node = state.nodes[node_id]
        node.status = "running"
        node.started_at = now_iso()
        node.finished_at = None
        node.error_message = None
        node.inputs = self._inputs_for(state, node_id)
        state.status = "running"
        state.current_node = node_id
        self.store.save_state(state)
        self.logger.log(
            batch_id=state.batch_id,
            node_id=node_id,
            event="node_started",
            message=f"{node_id} started",
            retry_index=node.retries,
        )
        started = time.perf_counter()
        try:
            outputs = self._agent_for(node_id).run({"batch_id": state.batch_id, "spec_path": state.spec_path})
            node.outputs = [output for output in outputs if isinstance(output, ArtifactRef)]
            self._validator_for(node_id).validate(state.batch_id)
            node.status = "succeeded"
            node.finished_at = now_iso()
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.store.save_state(state)
            self.logger.log(
                batch_id=state.batch_id,
                node_id=node_id,
                event="node_succeeded",
                message=f"{node_id} succeeded",
                duration_ms=duration_ms,
                retry_index=node.retries,
            )
            return state
        except Exception as exc:
            node.status = "failed"
            node.finished_at = now_iso()
            node.error_message = str(exc)
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.store.save_state(state)
            self.logger.log(
                batch_id=state.batch_id,
                node_id=node_id,
                event="node_failed",
                message=str(exc),
                level="ERROR",
                duration_ms=duration_ms,
                retry_index=node.retries,
                error_class=exc.__class__.__name__,
            )
            return state

    def _inputs_for(self, state: BatchState, node_id: NodeId) -> list[ArtifactRef]:
        if node_id == "design":
            spec = self.store.resolve(state.spec_path)
            return [self.store.artifact_for(spec, kind="spec_md")]
        if node_id == "code":
            return state.nodes["design"].outputs
        return state.nodes["design"].outputs + state.nodes["code"].outputs

    def _agent_for(self, node_id: NodeId):
        if node_id == "design":
            return DesignAgent(store=self.store, llm=self.llm)
        if node_id == "code":
            return CodeAgent(store=self.store, llm=self.llm)
        return TestAgent(store=self.store, llm=self.llm)

    def _validator_for(self, node_id: NodeId):
        if node_id == "design":
            return DesignArtifactValidator(self.store)
        if node_id == "code":
            return CodeValidator(self.store)
        return TestValidator(self.store)

    def _new_batch_id(self) -> str:
        return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
