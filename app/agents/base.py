from __future__ import annotations

from pathlib import Path
from typing import Any

from app.adapters.llm import LLMAdapter
from app.storage.file_store import FileStore


class BaseAgent:
    agent_name = "base"
    prompt_file = ""

    def __init__(self, *, store: FileStore, llm: LLMAdapter) -> None:
        self.store = store
        self.llm = llm

    def load_prompt(self) -> str:
        path = self.store.root_dir / "prompts" / self.prompt_file
        if not path.exists():
            return f"You are {self.agent_name}."
        return path.read_text(encoding="utf-8")

    def run(self, input_context: dict[str, Any]) -> list[Any]:
        raise NotImplementedError

    def read_text(self, relative_path: str) -> str:
        return self.store.resolve(relative_path).read_text(encoding="utf-8")

    def batch_artifact_dir(self, batch_id: str, name: str) -> Path:
        path = self.store.batch_dir(batch_id) / name
        path.mkdir(parents=True, exist_ok=True)
        return path
