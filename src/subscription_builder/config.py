from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

import yaml


@dataclass(slots=True)
class NodeSourceSpec:
    source_id: str
    label: str
    env_var: str
    text_env_var: str | None = None
    required: bool = True
    group_policy: str = "default"
    include_name_contains: list[str] = field(default_factory=list)
    include_name_regex: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


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
    node_sources: list[NodeSourceSpec]
    public_base_url_env: str
    private_base_url_env: str
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

    def resolve_private_base_url(self, explicit_url: str | None = None, *, public_base_url: str | None = None) -> str:
        value = explicit_url or os.environ.get(self.private_base_url_env, "")
        value = value or public_base_url or self.resolve_public_base_url()
        return value.rstrip("/")


def load_project_config(config_path: Path) -> ProjectConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    subscription = raw["subscription"]

    def _string_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError(f"Expected string or list of strings, got: {type(value).__name__}")

    primary_source = NodeSourceSpec(
        source_id=str(subscription.get("id", "primary")),
        label=str(subscription.get("label", "Primary")),
        env_var=subscription["env_var"],
        text_env_var=str(subscription["text_env_var"]) if subscription.get("text_env_var") else None,
        required=True,
        group_policy=str(subscription.get("group_policy", "default")),
        include_name_contains=_string_list(subscription.get("include_name_contains")),
        include_name_regex=str(subscription["include_name_regex"]) if subscription.get("include_name_regex") else None,
        metadata=dict(subscription.get("metadata", {})),
    )
    node_sources = [primary_source]
    for item in subscription.get("extra_sources", []):
        node_sources.append(
            NodeSourceSpec(
                source_id=str(item["id"]),
                label=str(item.get("label", item["id"])),
                env_var=str(item["env_var"]),
                text_env_var=str(item["text_env_var"]) if item.get("text_env_var") else None,
                required=bool(item.get("required", False)),
                group_policy=str(item.get("group_policy", "manual_only")),
                include_name_contains=_string_list(item.get("include_name_contains")),
                include_name_regex=str(item["include_name_regex"]) if item.get("include_name_regex") else None,
                metadata=dict(item.get("metadata", {})),
            )
        )

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
        subscription_env_var=subscription["env_var"],
        node_sources=node_sources,
        public_base_url_env=raw["artifacts"]["public_base_url_env"],
        private_base_url_env=raw["artifacts"].get("private_base_url_env", "PRIVATE_BASE_URL"),
        default_public_base_url=raw["artifacts"]["default_public_base_url"],
        user_agent=raw["network"]["user_agent"],
        rules=rules,
    )
