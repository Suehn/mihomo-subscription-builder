from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re

import yaml

from .routing_contract import CONFIG_RULE_POLICIES


SUPPORTED_RULE_CLIENTS = {"mihomo", "shadowrocket"}
SUPPORTED_RULE_BEHAVIORS = {"classical", "domain", "ipcidr"}
SUPPORTED_RULE_FORMATS = {"text"}
SUPPORTED_RULE_TRANSFORMS = {
    "clash_classical_domain",
    "clash_classical_ip",
    "clash_classical_non_ip",
    "metacubex_domain_to_shadowrocket",
    "metacubex_ipcidr_to_shadowrocket",
}


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
    _validate_raw_config(raw, config_path)
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
    for item in subscription.get("extra_sources") or []:
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


def _expect_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a mapping")
    return value


def _expect_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    return value


def _expect_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")
    return value


def _validate_relative_path(value: object, label: str) -> None:
    raw_path = _expect_non_empty_string(value, label)
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a safe relative path: {raw_path}")


def _validate_string_list(value: object, label: str) -> None:
    if value is None or isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return
    raise TypeError(f"{label} must be a string or list of strings")


def _validate_regex(value: object, label: str) -> None:
    if value is None:
        return
    pattern = _expect_non_empty_string(value, label)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{label} must be a valid regular expression: {exc}") from exc


def _validate_node_source(raw_source: dict[str, object], label: str, *, required_env: bool) -> str:
    source_id = str(raw_source.get("id", "primary" if label == "subscription" else "")).strip()
    if not source_id:
        raise TypeError(f"{label}.id must be a non-empty string")
    if required_env:
        _expect_non_empty_string(raw_source.get("env_var"), f"{label}.env_var")
    elif raw_source.get("env_var") is not None:
        _expect_non_empty_string(raw_source.get("env_var"), f"{label}.env_var")
    if raw_source.get("text_env_var") is not None:
        _expect_non_empty_string(raw_source.get("text_env_var"), f"{label}.text_env_var")
    _validate_string_list(raw_source.get("include_name_contains"), f"{label}.include_name_contains")
    _validate_regex(raw_source.get("include_name_regex"), f"{label}.include_name_regex")
    if raw_source.get("metadata") is not None:
        _expect_mapping(raw_source.get("metadata"), f"{label}.metadata")
    return source_id


def _validate_rule_output(rule_id: str, client_name: object, payload: object) -> None:
    client = _expect_non_empty_string(client_name, f"rule {rule_id} output client")
    if client not in SUPPORTED_RULE_CLIENTS:
        raise ValueError(f"Rule {rule_id} has unsupported output client: {client}")
    output = _expect_mapping(payload, f"rule {rule_id} output {client}")
    _validate_relative_path(output.get("path"), f"rule {rule_id} output {client}.path")

    has_source_url = bool(output.get("source_url"))
    has_source_file = bool(output.get("source_file"))
    if has_source_url == has_source_file:
        raise ValueError(f"Rule {rule_id} output {client} must define exactly one of source_url or source_file")
    if has_source_url:
        _expect_non_empty_string(output.get("source_url"), f"rule {rule_id} output {client}.source_url")
    if has_source_file:
        _validate_relative_path(output.get("source_file"), f"rule {rule_id} output {client}.source_file")

    behavior = output.get("behavior")
    if client == "mihomo" and not behavior:
        raise ValueError(f"Rule {rule_id} output {client} must define behavior")
    if behavior is not None and behavior not in SUPPORTED_RULE_BEHAVIORS:
        raise ValueError(f"Rule {rule_id} output {client} has unsupported behavior: {behavior}")

    output_format = output.get("format")
    if output_format is not None and output_format not in SUPPORTED_RULE_FORMATS:
        raise ValueError(f"Rule {rule_id} output {client} has unsupported format: {output_format}")

    transform = output.get("transform")
    if transform is not None and transform not in SUPPORTED_RULE_TRANSFORMS:
        raise ValueError(f"Rule {rule_id} output {client} has unsupported transform: {transform}")


def _validate_raw_config(raw: object, config_path: Path) -> None:
    config = _expect_mapping(raw, str(config_path))
    subscription = _expect_mapping(config.get("subscription"), "subscription")
    artifacts = _expect_mapping(config.get("artifacts"), "artifacts")
    network = _expect_mapping(config.get("network"), "network")
    rules = _expect_list(config.get("rules"), "rules")
    if not rules:
        raise ValueError("rules must not be empty")

    source_ids = {_validate_node_source(subscription, "subscription", required_env=True)}
    extra_sources = subscription.get("extra_sources", [])
    if extra_sources is None:
        extra_sources = []
    _expect_list(extra_sources, "subscription.extra_sources")
    for index, item in enumerate(extra_sources):
        raw_source = _expect_mapping(item, f"subscription.extra_sources[{index}]")
        source_id = _validate_node_source(raw_source, f"subscription.extra_sources[{index}]", required_env=True)
        if source_id in source_ids:
            raise ValueError(f"Duplicate node source id: {source_id}")
        source_ids.add(source_id)

    _expect_non_empty_string(artifacts.get("public_base_url_env"), "artifacts.public_base_url_env")
    _expect_non_empty_string(artifacts.get("default_public_base_url"), "artifacts.default_public_base_url")
    if artifacts.get("private_base_url_env") is not None:
        _expect_non_empty_string(artifacts.get("private_base_url_env"), "artifacts.private_base_url_env")
    _expect_non_empty_string(network.get("user_agent"), "network.user_agent")

    rule_ids: set[str] = set()
    output_paths: set[str] = set()
    for index, item in enumerate(rules):
        raw_rule = _expect_mapping(item, f"rules[{index}]")
        rule_id = _expect_non_empty_string(raw_rule.get("id"), f"rules[{index}].id")
        if rule_id in rule_ids:
            raise ValueError(f"Duplicate rule id: {rule_id}")
        rule_ids.add(rule_id)

        policy = _expect_non_empty_string(raw_rule.get("policy"), f"rule {rule_id}.policy")
        if policy not in CONFIG_RULE_POLICIES:
            raise ValueError(f"Rule {rule_id} has unsupported policy: {policy}")

        outputs = _expect_mapping(raw_rule.get("outputs"), f"rule {rule_id}.outputs")
        if not outputs:
            raise ValueError(f"Rule {rule_id} must define at least one output")
        for client_name, output in outputs.items():
            _validate_rule_output(rule_id, client_name, output)
            output_path = str(_expect_mapping(output, f"rule {rule_id} output {client_name}")["path"])
            if output_path in output_paths:
                raise ValueError(f"Duplicate rule output path: {output_path}")
            output_paths.add(output_path)
