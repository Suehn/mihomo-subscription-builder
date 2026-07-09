from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from .rule_grammar import (
    payload_lines_from_file,
    policy_from_rule_parts,
    rule_matches_domain,
    split_rule_parts,
)
from .routing_contract import GEOSITE_FALLBACK_SUFFIXES, LOGIC_RULE_TYPES, MIHOMO_GEOSITE_PROVIDER_FILES


@dataclass(slots=True)
class MatchResult:
    policy: str
    rule: str


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _domain_matches(rule_domain: str, domain: str, suffix: bool) -> bool:
    rule_domain = rule_domain.lower().lstrip(".")
    domain = domain.lower().rstrip(".")
    if suffix:
        return domain == rule_domain or domain.endswith(f".{rule_domain}")
    return domain == rule_domain


@lru_cache(maxsize=None)
def _provider_payload_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(payload_lines_from_file(path))


@lru_cache(maxsize=None)
def _provider_matches(path: Path, domain: str) -> bool:
    return any(rule_matches_domain(line, domain) for line in _provider_payload_lines(path))


def _mihomo_provider_paths(config: dict[str, object], config_path: Path) -> dict[str, Path]:
    providers = config.get("rule-providers", {})
    if not isinstance(providers, dict):
        raise TypeError("rule-providers must be a mapping")
    paths: dict[str, Path] = {}
    for provider_id, raw_provider in providers.items():
        if not isinstance(raw_provider, dict):
            continue
        provider_path = _mihomo_provider_path(config_path, raw_provider)
        if provider_path:
            paths[str(provider_id)] = provider_path
    return paths


def _mihomo_provider_path(config_path: Path, provider: dict[str, object]) -> Path | None:
    provider_url = str(provider.get("url", ""))
    marker = "/rules/"
    if marker in provider_url:
        relative = provider_url.split(marker, 1)[1]
        return (config_path.parent / "rules" / relative).resolve()
    provider_path = str(provider.get("path", ""))
    if provider_path:
        return (config_path.parent / provider_path).resolve()
    return None


def _geosite_rule_path(config_path: Path, category: str) -> Path | None:
    file_name = MIHOMO_GEOSITE_PROVIDER_FILES.get(category)
    if not file_name:
        return None
    return (config_path.parent / "rules" / "mihomo" / file_name).resolve()


def _geosite_matches(category: str, domain: str, *, config_path: Path | None = None) -> bool:
    if config_path is not None:
        provider_path = _geosite_rule_path(config_path, category)
        if provider_path and _provider_matches(provider_path, domain):
            return True

    suffixes = GEOSITE_FALLBACK_SUFFIXES.get(category, [])
    return any(_domain_matches(suffix, domain, suffix=True) for suffix in suffixes)


def route_mihomo_domain(config_path: Path, domain: str) -> MatchResult:
    config = _load_yaml(config_path)
    if not isinstance(config, dict):
        raise TypeError(f"{config_path} must contain a mapping")
    rules = [str(rule) for rule in config.get("rules", [])]
    provider_paths = _mihomo_provider_paths(config, config_path)
    for rule in rules:
        parts = split_rule_parts(rule)
        if not parts:
            continue
        if parts[0] in LOGIC_RULE_TYPES:
            # Domain-only simulator cannot decide GEOIP clauses, so logical
            # rules are intentionally skipped. Concrete follow-up rules are
            # still evaluated and covered by route expectations.
            continue
        if parts[0] == "RULE-SET" and len(parts) >= 3:
            provider_path = provider_paths.get(parts[1])
            if provider_path and _provider_matches(provider_path, domain):
                return MatchResult(policy=policy_from_rule_parts(parts), rule=rule)
            continue
        if parts[0] == "GEOSITE":
            if len(parts) >= 3 and _geosite_matches(parts[1], domain, config_path=config_path):
                return MatchResult(policy=policy_from_rule_parts(parts), rule=rule)
            continue
        if parts[0] in {"MATCH", "FINAL"} and len(parts) >= 2:
            return MatchResult(policy=parts[1], rule=rule)
        if len(parts) >= 3 and rule_matches_domain(rule, domain):
            return MatchResult(policy=policy_from_rule_parts(parts), rule=rule)
    raise ValueError(f"No Mihomo rule matched domain: {domain}")


def _shadowrocket_section(lines: list[str], name: str) -> list[str]:
    marker = f"[{name}]"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise ValueError(f"Shadowrocket config is missing section: {marker}") from exc
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("[") and lines[index].endswith("]"):
            end = index
            break
    return [line for line in lines[start:end] if line.strip() and not line.startswith("#")]


def route_shadowrocket_domain(config_path: Path, domain: str) -> MatchResult:
    lines = config_path.read_text(encoding="utf-8").splitlines()
    for rule in _shadowrocket_section(lines, "Rule"):
        parts = split_rule_parts(rule)
        if not parts:
            continue
        if parts[0] == "RULE-SET" and len(parts) >= 3:
            provider_path = _shadowrocket_provider_path(config_path, parts[1])
            if provider_path and _provider_matches(provider_path, domain):
                return MatchResult(policy=parts[2], rule=rule)
            continue
        if parts[0] in {"FINAL", "MATCH"} and len(parts) >= 2:
            return MatchResult(policy=parts[1], rule=rule)
        if len(parts) >= 3 and rule_matches_domain(rule, domain):
            return MatchResult(policy=parts[2], rule=rule)
    raise ValueError(f"No Shadowrocket rule matched domain: {domain}")


def _shadowrocket_provider_path(config_path: Path, url_or_path: str) -> Path | None:
    marker = "/rules/"
    if marker not in url_or_path:
        return None
    relative = url_or_path.split(marker, 1)[1]
    return (config_path.parent / "rules" / relative).resolve()


def validate_route_expectations(
    *,
    mihomo_paths: Iterable[Path],
    shadowrocket_path: Path,
    shadowrocket_strict_path: Path | None = None,
    expectations_path: Path,
) -> None:
    payload = _load_yaml(expectations_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("domains"), dict):
        raise TypeError(f"{expectations_path} must contain a domains mapping")
    domains = {str(domain): str(policy) for domain, policy in payload["domains"].items()}
    errors: list[str] = []
    for domain, expected_policy in domains.items():
        for config_path in mihomo_paths:
            result = route_mihomo_domain(config_path, domain)
            if result.policy != expected_policy:
                errors.append(f"{config_path.name}: {domain} => {result.policy} via {result.rule}; expected {expected_policy}")
        shadow_result = route_shadowrocket_domain(shadowrocket_path, domain)
        if shadow_result.policy != expected_policy:
            errors.append(
                f"{shadowrocket_path.name}: {domain} => {shadow_result.policy} via {shadow_result.rule}; expected {expected_policy}"
            )
        if shadowrocket_strict_path is not None:
            strict_result = route_shadowrocket_domain(shadowrocket_strict_path, domain)
            if strict_result.policy != expected_policy:
                errors.append(
                    f"{shadowrocket_strict_path.name}: {domain} => {strict_result.policy} via {strict_result.rule}; expected {expected_policy}"
                )
    if errors:
        raise ValueError("Route expectation failures:\n" + "\n".join(errors))


def _coverage_category_expectations(raw_category: object) -> dict[str, str]:
    if not isinstance(raw_category, dict):
        raise TypeError("Rule coverage categories must be mappings")
    name = str(raw_category.get("name", "")).strip()
    if not name:
        raise ValueError("Rule coverage category is missing name")

    raw_expectations = raw_category.get("expectations")
    if raw_expectations is not None:
        if not isinstance(raw_expectations, dict):
            raise TypeError(f"Rule coverage category {name} expectations must be a mapping")
        return {str(domain): str(policy) for domain, policy in raw_expectations.items()}

    policy = raw_category.get("policy")
    domains = raw_category.get("domains")
    if policy is None or not isinstance(domains, list):
        raise TypeError(f"Rule coverage category {name} must define policy plus domains or expectations")
    return {str(domain): str(policy) for domain in domains}


def validate_rule_coverage(
    *,
    mihomo_paths: Iterable[Path],
    shadowrocket_path: Path,
    shadowrocket_strict_path: Path | None = None,
    coverage_path: Path,
) -> None:
    payload = _load_yaml(coverage_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("categories"), list):
        raise TypeError(f"{coverage_path} must contain a categories list")

    errors: list[str] = []
    for raw_category in payload["categories"]:
        if not isinstance(raw_category, dict):
            raise TypeError("Rule coverage categories must be mappings")
        category_name = str(raw_category.get("name", "")).strip()
        expectations = _coverage_category_expectations(raw_category)
        if not expectations:
            errors.append(f"{category_name}: no coverage domains")
            continue
        for domain, expected_policy in expectations.items():
            for config_path in mihomo_paths:
                result = route_mihomo_domain(config_path, domain)
                if result.policy != expected_policy:
                    errors.append(
                        f"{category_name}/{config_path.name}: {domain} => {result.policy} "
                        f"via {result.rule}; expected {expected_policy}"
                    )
            shadow_result = route_shadowrocket_domain(shadowrocket_path, domain)
            if shadow_result.policy != expected_policy:
                errors.append(
                    f"{category_name}/{shadowrocket_path.name}: {domain} => {shadow_result.policy} "
                    f"via {shadow_result.rule}; expected {expected_policy}"
                )
            if shadowrocket_strict_path is not None:
                strict_result = route_shadowrocket_domain(shadowrocket_strict_path, domain)
                if strict_result.policy != expected_policy:
                    errors.append(
                        f"{category_name}/{shadowrocket_strict_path.name}: {domain} => {strict_result.policy} "
                        f"via {strict_result.rule}; expected {expected_policy}"
                    )

    if errors:
        raise ValueError("Rule coverage failures:\n" + "\n".join(errors))
