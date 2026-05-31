from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent


class DesignManifest(BaseModel):
    system_name: str
    modules: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    csv_tables: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    frontend_requirements: list[str] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class DesignAgent(BaseAgent):
    agent_name = "DesignAgent"
    prompt_file = "design_agent.md"

    def run(self, input_context: dict[str, str]) -> list[object]:
        batch_id = input_context["batch_id"]
        spec_path = input_context["spec_path"]
        spec_text = self.read_text(spec_path)
        prompt = self.load_prompt()
        metadata = {"batch_id": batch_id, "node_id": "design"}

        overview = self.llm.generate_text(system=prompt, user=spec_text, metadata=metadata)
        manifest = self.llm.generate_json(system=prompt, user=spec_text, schema=DesignManifest, metadata=metadata)

        output_dir = self.batch_artifact_dir(batch_id, "概要设计")
        overview_ref = self.store.write_text(output_dir / "overview_design.md", overview)
        manifest_ref = self.store.write_json(output_dir / "design_manifest.json", manifest.model_dump(mode="json"))
        return [overview_ref, manifest_ref]
