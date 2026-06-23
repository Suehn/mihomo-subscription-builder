from __future__ import annotations

import ipaddress
from pathlib import Path
import re
from typing import Callable, Iterable

import yaml

from .routing_contract import LOGIC_RULE_TYPES


RULE_SET_REF_RE = re.compile(r"RULE-SET,([A-Za-z0-9_.!@-]+)")

IP_RULE_KINDS = {"IP-CIDR", "IP-CIDR6", "IP-ASN", "GEOIP"}
PROCESS_RULE_KINDS = {"PROCESS-NAME", "PROCESS-PATH", "PROCESS-NAME-REGEX"}
DOMAIN_RULE_KINDS = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-REGEX",
    "GEOSITE",
    "HOST",
    "HOST-SUFFIX",
    "HOST-KEYWORD",
    "URL-REGEX",
}


def split_rule_parts(rule: str) -> list[str]:
    return [part.strip() for part in rule.split(",")]


def payload_lines_from_content(content: str) -> list[str]:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("payload"), list):
        return [str(item).strip() for item in data["payload"] if str(item).strip()]
    return [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def payload_lines_from_file(path: Path) -> list[str]:
    return payload_lines_from_content(path.read_text(encoding="utf-8"))


def rule_kind(line: str) -> str:
    if "," in line:
        return line.split(",", 1)[0].strip()
    try:
        ipaddress.ip_network(line, strict=False)
        return "IP-CIDR6" if ":" in line else "IP-CIDR"
    except ValueError:
        pass
    if line.startswith(("+.", ".")) or any(ch.isalpha() for ch in line):
        return "DOMAIN-LIKE"
    return "UNKNOWN"


def is_ip_rule(line: str) -> bool:
    return rule_kind(line) in IP_RULE_KINDS


def is_process_rule(line: str) -> bool:
    return rule_kind(line) in PROCESS_RULE_KINDS


def is_domain_rule(line: str) -> bool:
    return rule_kind(line) in DOMAIN_RULE_KINDS or rule_kind(line) == "DOMAIN-LIKE"


def policy_from_rule(rule: str) -> str | None:
    if not rule:
        return None

    kind = rule_kind(rule)
    if kind in LOGIC_RULE_TYPES:
        return rule.rsplit(",", 1)[-1].strip()

    parts = split_rule_parts(rule)
    if parts[0] in {"MATCH", "FINAL"}:
        return parts[1] if len(parts) >= 2 else None
    return parts[2] if len(parts) >= 3 else None


def policy_from_rule_parts(parts: list[str]) -> str:
    if parts[0] in {"MATCH", "FINAL"}:
        return parts[1]
    return parts[2]


def with_resolved_policy(rule: str, resolver: Callable[[str], str]) -> str:
    kind = rule_kind(rule)
    if kind in LOGIC_RULE_TYPES:
        head, policy = rule.rsplit(",", 1)
        return f"{head},{resolver(policy.strip())}"

    parts = split_rule_parts(rule)
    if parts[0] in {"MATCH", "FINAL"} and len(parts) >= 2:
        parts[1] = resolver(parts[1])
        return ",".join(parts)
    if len(parts) >= 3:
        parts[2] = resolver(parts[2])
    return ",".join(parts)


def referenced_rule_provider_ids(rules: Iterable[str]) -> set[str]:
    provider_ids: set[str] = set()
    for rule in rules:
        rule_text = str(rule)
        parts = split_rule_parts(rule_text)
        if len(parts) >= 2 and parts[0] == "RULE-SET":
            provider_ids.add(parts[1])
        for match in RULE_SET_REF_RE.finditer(rule_text):
            provider_ids.add(match.group(1))
    return provider_ids


def _domain_matches(rule_domain: str, domain: str, *, suffix: bool) -> bool:
    rule_domain = rule_domain.lower().lstrip(".")
    domain = domain.lower().rstrip(".")
    if suffix:
        return domain == rule_domain or domain.endswith(f".{rule_domain}")
    return domain == rule_domain


def rule_matches_domain(rule: str, domain: str) -> bool:
    parts = split_rule_parts(rule)
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
    if kind == "full":
        return _domain_matches(value, domain, suffix=False)
    if rule.startswith("+."):
        return _domain_matches(rule[2:], domain, suffix=True)
    if rule.startswith("."):
        return _domain_matches(rule[1:], domain, suffix=True)
    return _domain_matches(rule, domain, suffix=True)
