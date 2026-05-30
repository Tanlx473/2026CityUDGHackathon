from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.adapters.llm import LLMError, MockLLMAdapter, SchemaT
from app.config import Settings, get_settings


class OpenAIAdapter:
    """OpenAI SDK adapter with a deterministic fallback when unavailable."""

    def __init__(self, settings: Settings | None = None, fallback: MockLLMAdapter | None = None) -> None:
        self.settings = settings or get_settings()
        self.fallback = fallback or MockLLMAdapter()
        self._client: Any | None = None
        if self.settings.has_openai_key:
            try:
                from openai import OpenAI

                kwargs: dict[str, str] = {"api_key": self.settings.openai_api_key or ""}
                if self.settings.openai_base_url:
                    kwargs["base_url"] = self.settings.openai_base_url
                self._client = OpenAI(**kwargs)
            except Exception:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def _model_for(self, metadata: dict[str, str] | None) -> str | None:
        node_id = (metadata or {}).get("node_id")
        if node_id == "design":
            return self.settings.design_model
        if node_id == "code":
            return self.settings.code_model
        if node_id == "test":
            return self.settings.test_model
        return self.settings.design_model or self.settings.code_model or self.settings.test_model

    def generate_text(self, *, system: str, user: str, metadata: dict[str, str] | None = None) -> str:
        model = self._model_for(metadata)
        if not self.available or not model:
            return self.fallback.generate_text(system=system, user=user, metadata=metadata)
        try:
            response = self._client.responses.create(
                model=model,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                metadata={k: v for k, v in (metadata or {}).items() if "key" not in k.lower()},
            )
            return response.output_text
        except Exception as exc:
            try:
                return self.fallback.generate_text(system=system, user=user, metadata=metadata)
            except Exception as fallback_exc:
                raise LLMError(
                    f"OpenAI text generation failed and fallback failed: {exc.__class__.__name__}: {fallback_exc}"
                ) from fallback_exc

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        metadata: dict[str, str] | None = None,
    ) -> SchemaT:
        model = self._model_for(metadata)
        if not self.available or not model:
            return self.fallback.generate_json(system=system, user=user, schema=schema, metadata=metadata)
        try:
            response = self._client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": f"{system}\nReturn JSON matching this schema: {schema.model_json_schema()}"},
                    {"role": "user", "content": user},
                ],
                text={"format": {"type": "json_object"}},
                metadata={k: v for k, v in (metadata or {}).items() if "key" not in k.lower()},
            )
            return schema.model_validate(json.loads(response.output_text))
        except Exception as exc:
            try:
                return self.fallback.generate_json(system=system, user=user, schema=schema, metadata=metadata)
            except Exception as fallback_exc:
                raise LLMError(
                    f"OpenAI JSON generation failed and fallback failed: {exc.__class__.__name__}: {fallback_exc}"
                ) from fallback_exc
