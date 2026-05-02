from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


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


def _payload_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and isinstance(data.get("payload"), list):
            return [str(item).strip() for item in data["payload"] if str(item).strip()]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _rule_matches_domain(rule: str, domain: str) -> bool:
    parts = [part.strip() for part in rule.split(",")]
    if len(parts) == 1:
        if rule.startswith("+."):
            return _domain_matches(rule[2:], domain, suffix=True)
        if rule.startswith("."):
            return _domain_matches(rule[1:], domain, suffix=True)
        return _domain_matches(rule, domain, suffix=False)
    if len(parts) < 2:
        return False
    kind = parts[0]
    value = parts[1]
    if kind == "DOMAIN":
        return _domain_matches(value, domain, suffix=False)
    if kind == "DOMAIN-SUFFIX":
        return _domain_matches(value, domain, suffix=True)
    if kind == "DOMAIN-KEYWORD":
        return value.lower() in domain.lower()
    if kind in {"DOMAIN-REGEX", "PROCESS-NAME", "IP-CIDR", "IP-CIDR6"}:
        return False
    if kind in {"full"}:
        return _domain_matches(value, domain, suffix=False)
    if rule.startswith("+."):
        return _domain_matches(rule[2:], domain, suffix=True)
    if rule.startswith("."):
        return _domain_matches(rule[1:], domain, suffix=True)
    return _domain_matches(rule, domain, suffix=True)


def _provider_matches(path: Path, domain: str) -> bool:
    if not path.exists():
        return False
    return any(_rule_matches_domain(line, domain) for line in _payload_lines(path))


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


def _geosite_matches(category: str, domain: str) -> bool:
    suffixes = {
        "youtube": ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com"],
        "netflix": ["netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net"],
        "disney": ["disneyplus.com", "disney-plus.net", "dssott.com"],
        "spotify": ["spotify.com", "scdn.co", "spotifycdn.com"],
        "tiktok": ["tiktok.com", "tiktokv.com", "byteoversea.com"],
        "microsoft": ["microsoft.com", "windows.com", "office.com", "live.com", "azure.com"],
        "microsoft@cn": ["download.visualstudio.microsoft.com"],
        "apple": ["apple.com", "icloud.com", "mzstatic.com"],
        "apple-cn": ["icloud.com.cn"],
        "cn": ["cn"],
        "geolocation-!cn": [],
        "private": ["local", "lan"],
    }.get(category, [])
    return any(_domain_matches(suffix, domain, suffix=True) for suffix in suffixes)


def _policy_from_rule_parts(parts: list[str]) -> str:
    if parts[0] in {"MATCH", "FINAL"}:
        return parts[1]
    return parts[2]


def route_mihomo_domain(config_path: Path, domain: str) -> MatchResult:
    config = _load_yaml(config_path)
    if not isinstance(config, dict):
        raise TypeError(f"{config_path} must contain a mapping")
    rules = [str(rule) for rule in config.get("rules", [])]
    provider_paths = _mihomo_provider_paths(config, config_path)
    for rule in rules:
        parts = [part.strip() for part in rule.split(",")]
        if not parts:
            continue
        if parts[0] == "RULE-SET" and len(parts) >= 3:
            provider_path = provider_paths.get(parts[1])
            if provider_path and _provider_matches(provider_path, domain):
                return MatchResult(policy=_policy_from_rule_parts(parts), rule=rule)
            continue
        if parts[0] == "GEOSITE":
            if len(parts) >= 3 and _geosite_matches(parts[1], domain):
                return MatchResult(policy=_policy_from_rule_parts(parts), rule=rule)
            continue
        if parts[0] in {"MATCH", "FINAL"} and len(parts) >= 2:
            return MatchResult(policy=parts[1], rule=rule)
        if len(parts) >= 3 and _rule_matches_domain(rule, domain):
            return MatchResult(policy=_policy_from_rule_parts(parts), rule=rule)
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
        parts = [part.strip() for part in rule.split(",")]
        if not parts:
            continue
        if parts[0] == "RULE-SET" and len(parts) >= 3:
            provider_path = _shadowrocket_provider_path(config_path, parts[1])
            if provider_path and _provider_matches(provider_path, domain):
                return MatchResult(policy=parts[2], rule=rule)
            continue
        if parts[0] in {"FINAL", "MATCH"} and len(parts) >= 2:
            return MatchResult(policy=parts[1], rule=rule)
        if len(parts) >= 3 and _rule_matches_domain(rule, domain):
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
    if errors:
        raise ValueError("Route expectation failures:\n" + "\n".join(errors))
