from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import yaml


@dataclass(slots=True)
class RuleOutput:
    client: str
    path: str
    source_url: str | None = None
    source_file: str | None = None
    behavior: str | None = None
    format: str | None = None
    transform: str | None = None


@dataclass(slots=True)
class RuleSpec:
    rule_id: str
    policy: str
    outputs: dict[str, RuleOutput]


@dataclass(slots=True)
class ProjectConfig:
    subscription_env_var: str
    public_base_url_env: str
    default_public_base_url: str
    user_agent: str
    rules: list[RuleSpec]

    def resolve_upstream_url(self, explicit_url: str | None = None) -> str:
        value = explicit_url or os.environ.get(self.subscription_env_var, "")
        if not value:
            raise ValueError(
                f"Missing upstream subscription URL. Set {self.subscription_env_var} or pass --upstream-url."
            )
        return value

    def resolve_public_base_url(self, explicit_url: str | None = None) -> str:
        value = explicit_url or os.environ.get(self.public_base_url_env, "")
        value = value or self.default_public_base_url
        return value.rstrip("/")


def load_project_config(config_path: Path) -> ProjectConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    rules: list[RuleSpec] = []
    for item in raw["rules"]:
        outputs: dict[str, RuleOutput] = {}
        for client_name, client_payload in item["outputs"].items():
            outputs[client_name] = RuleOutput(
                client=client_name,
                path=client_payload["path"],
                source_url=client_payload.get("source_url"),
                source_file=client_payload.get("source_file"),
                behavior=client_payload.get("behavior"),
                format=client_payload.get("format"),
                transform=client_payload.get("transform"),
            )
        rules.append(
            RuleSpec(
                rule_id=item["id"],
                policy=item["policy"],
                outputs=outputs,
            )
        )
    return ProjectConfig(
        subscription_env_var=raw["subscription"]["env_var"],
        public_base_url_env=raw["artifacts"]["public_base_url_env"],
        default_public_base_url=raw["artifacts"]["default_public_base_url"],
        user_agent=raw["network"]["user_agent"],
        rules=rules,
    )
