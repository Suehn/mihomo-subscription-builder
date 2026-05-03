from __future__ import annotations

from pathlib import Path
import re

import yaml

from .render import GROUP_LABELS


BUILTIN_POLICIES = {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
LOGIC_RULE_TYPES = {"AND", "OR", "NOT"}
RULE_SET_REF_RE = re.compile(r"RULE-SET,([A-Za-z0-9_.!@-]+)")
SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_FIRST = [
    "PROXY",
    "GitHub",
    "AI",
    "Google",
    "Developer",
    "Microsoft",
    "Telegram",
    "Streaming",
]
SHADOWROCKET_REQUIRED_RULE_FRAGMENTS = [
    "DOMAIN-SUFFIX,github.com",
    "DOMAIN-SUFFIX,objects.githubusercontent.com",
    "DOMAIN-SUFFIX,chatgpt.com",
    "DOMAIN-SUFFIX,claude.ai",
    "/apple_intelligence.conf",
    "/developer_global.conf",
    "/direct.conf",
    "/global.conf",
    "FINAL,",
]
SHADOWROCKET_RULE_ORDER = [
    ("DOMAIN-SUFFIX,github.com", "/download_domainset.conf"),
    ("/github.", "/download_domainset.conf"),
    ("/ai.conf", "/download_domainset.conf"),
    ("/apple_intelligence.conf", "/download_domainset.conf"),
    ("/microsoft.conf", "/download_domainset.conf"),
    ("/microsoft_cdn.conf", "/download_domainset.conf"),
    ("/apple_cdn.conf", "/download_domainset.conf"),
    ("/cn.", "/download_domainset.conf"),
    ("/developer_global.conf", "/download_domainset.conf"),
    ("/download_domainset.conf", "/cn_ip."),
    ("/geolocation-!cn.", "/cn_ip."),
]


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _first_index(rules: list[str], prefix: str) -> int:
    for index, rule in enumerate(rules):
        if rule.startswith(prefix):
            return index
    raise ValueError(f"Missing rule with prefix: {prefix}")


def _first_index_contains(rules: list[str], needle: str) -> int:
    for index, rule in enumerate(rules):
        if needle in rule:
            return index
    raise ValueError(f"Missing rule containing: {needle}")


def _policy_from_rule(rule: str) -> str | None:
    if not rule:
        return None

    rule_type = rule.split(",", 1)[0]
    if rule_type in LOGIC_RULE_TYPES:
        return rule.rsplit(",", 1)[-1]

    parts = rule.split(",")
    if parts[0] in {"MATCH", "FINAL"}:
        return parts[1] if len(parts) >= 2 else None
    return parts[2] if len(parts) >= 3 else None


def _validate_rule_groups(config: dict[str, object]) -> None:
    groups = {str(group["name"]) for group in config.get("proxy-groups", [])}
    missing: set[str] = set()
    for rule in config.get("rules", []):
        policy = _policy_from_rule(str(rule))
        if policy and policy not in BUILTIN_POLICIES and policy not in groups:
            missing.add(policy)
    if missing:
        raise ValueError(f"Mihomo rules reference missing proxy groups: {sorted(missing)}")


def _validate_rule_providers(config: dict[str, object]) -> None:
    providers = config.get("rule-providers", {})
    if not isinstance(providers, dict):
        raise TypeError("rule-providers must be a mapping")

    missing_provider_ids: set[str] = set()
    for rule in config.get("rules", []):
        rule_text = str(rule)
        for match in RULE_SET_REF_RE.finditer(rule_text):
            provider_id = match.group(1)
            if provider_id not in providers:
                missing_provider_ids.add(provider_id)
    if missing_provider_ids:
        raise ValueError(f"Mihomo rules reference missing rule-providers: {sorted(missing_provider_ids)}")

    groups = {str(group["name"]) for group in config.get("proxy-groups", [])}
    missing_proxy_groups: set[str] = set()
    for provider_id, provider in providers.items():
        if not isinstance(provider, dict):
            raise TypeError(f"rule-provider must be a mapping: {provider_id}")
        proxy_name = provider.get("proxy")
        if proxy_name and proxy_name not in groups and proxy_name not in BUILTIN_POLICIES:
            missing_proxy_groups.add(str(proxy_name))
    if missing_proxy_groups:
        raise ValueError(f"rule-providers reference missing proxy groups: {sorted(missing_proxy_groups)}")


def validate_mihomo_config(config_path: Path, validation_path: Path) -> None:
    config = _load_yaml(config_path)
    validation = _load_yaml(validation_path)
    if not isinstance(config, dict):
        raise TypeError(f"{config_path} must contain a mapping")
    if not isinstance(validation, dict):
        raise TypeError(f"{validation_path} must contain a mapping")

    required_keys = {"proxies", "proxy-groups", "rule-providers", "rules"}
    missing_keys = required_keys - set(config)
    if missing_keys:
        raise ValueError(f"Mihomo config is missing required keys: {sorted(missing_keys)}")

    rules = [str(rule) for rule in config["rules"]]
    if not rules:
        raise ValueError("Mihomo config has no rules")

    last_rule_prefix = str(validation.get("last_rule_prefix", "MATCH,"))
    if not rules[-1].startswith(last_rule_prefix):
        raise ValueError(f"Last Mihomo rule must start with {last_rule_prefix!r}: {rules[-1]}")

    if validation.get("ipv6_disabled"):
        if config.get("ipv6") is not False:
            raise ValueError("Top-level ipv6 must be false")
        dns = config.get("dns", {})
        if not isinstance(dns, dict) or dns.get("ipv6") is not False:
            raise ValueError("dns.ipv6 must be false")

    providers = config.get("rule-providers", {})
    if not isinstance(providers, dict):
        raise TypeError("rule-providers must be a mapping")
    for required in validation.get("required_providers", []):
        if required not in providers:
            raise ValueError(f"Missing required rule-provider: {required}")

    for required in validation.get("required_rules", []):
        _first_index(rules, str(required))

    for item in validation.get("rule_order", []):
        before = str(item["before"])
        after = str(item["after"])
        before_index = _first_index(rules, before)
        after_index = _first_index(rules, after)
        if before_index >= after_index:
            raise ValueError(f"Rule order violation: {before!r} must be before {after!r}")

    groups = {str(group["name"]): group for group in config["proxy-groups"]}
    for key in validation.get("foreign_groups_no_direct_first", []):
        group_name = GROUP_LABELS[str(key)]
        group = groups.get(group_name)
        if not group:
            raise ValueError(f"Missing required proxy group: {group_name}")
        proxies = group.get("proxies", [])
        if not isinstance(proxies, list) or not proxies:
            raise ValueError(f"Proxy group has no proxies: {group_name}")
        if proxies[0] == "DIRECT":
            raise ValueError(f"Proxy group defaults to DIRECT: {group_name}")

    _validate_rule_groups(config)
    _validate_rule_providers(config)


def validate_rule_audit(audit_path: Path) -> None:
    payload = yaml.safe_load(audit_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise TypeError(f"{audit_path} must contain a rules list")

    entries = payload["rules"]
    if not entries:
        raise ValueError("Rule audit has no entries")

    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise TypeError("Rule audit entries must be mappings")
        rule_id = str(raw_entry.get("rule_id", ""))
        client = str(raw_entry.get("client", ""))
        key = (client, rule_id)
        if key in seen:
            errors.append(f"duplicate audit entry: {client}/{rule_id}")
        seen.add(key)

        line_count = int(raw_entry.get("line_count", 0))
        domain_count = int(raw_entry.get("domain_count", 0))
        ip_count = int(raw_entry.get("ip_count", 0))
        process_count = int(raw_entry.get("process_count", 0))
        sha256 = str(raw_entry.get("sha256", ""))

        if line_count <= 0:
            errors.append(f"empty rule provider: {client}/{rule_id}")
        if len(sha256) != 64:
            errors.append(f"invalid sha256 for rule provider: {client}/{rule_id}")
        if rule_id.endswith("_non_ip") and ip_count:
            errors.append(f"non_ip provider contains IP rules: {client}/{rule_id}")
        if client == "mihomo" and rule_id.endswith("_direct_domain") and ip_count:
            errors.append(f"direct domain provider contains IP rules: {client}/{rule_id}")
        if client == "mihomo" and rule_id.endswith("_direct_domain") and process_count:
            errors.append(f"direct domain provider contains process rules: {client}/{rule_id}")
        if client == "mihomo" and rule_id.endswith("_direct_ip") and domain_count:
            errors.append(f"direct IP provider contains domain rules: {client}/{rule_id}")
        if client == "mihomo" and rule_id.endswith("_direct_ip") and process_count:
            errors.append(f"direct IP provider contains process rules: {client}/{rule_id}")

    if errors:
        raise ValueError("Rule audit failures:\n" + "\n".join(errors))


def _shadowrocket_section(lines: list[str], name: str) -> list[str]:
    start_marker = f"[{name}]"
    try:
        start = lines.index(start_marker) + 1
    except ValueError as exc:
        raise ValueError(f"Shadowrocket config is missing section: {start_marker}") from exc
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("[") and lines[index].endswith("]"):
            end = index
            break
    return [line for line in lines[start:end] if line.strip() and not line.startswith("#")]


def _shadowrocket_groups(lines: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for line in _shadowrocket_section(lines, "Proxy Group"):
        if "=" not in line:
            continue
        name, payload = line.split("=", 1)
        parts = [part.strip() for part in payload.split(",") if part.strip()]
        if len(parts) >= 2:
            groups[name.strip()] = parts[1:]
    return groups


def validate_shadowrocket_config(config_path: Path, *, traffic_saver: bool = True) -> None:
    lines = config_path.read_text(encoding="utf-8").splitlines()
    for section in ("[General]", "[Proxy]", "[Proxy Group]", "[Rule]"):
        if section not in lines:
            raise ValueError(f"Shadowrocket config is missing section: {section}")

    if "ipv6 = false" not in lines:
        raise ValueError("Shadowrocket config must set ipv6 = false")

    groups = _shadowrocket_groups(lines)
    for key in SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_FIRST:
        group_name = GROUP_LABELS[key]
        members = groups.get(group_name)
        if not members:
            raise ValueError(f"Missing required Shadowrocket proxy group: {group_name}")
        if members[0] == "DIRECT":
            raise ValueError(f"Shadowrocket proxy group defaults to DIRECT: {group_name}")

    final_group_name = GROUP_LABELS["Final"]
    final_members = groups.get(final_group_name)
    if not final_members:
        raise ValueError(f"Missing required Shadowrocket proxy group: {final_group_name}")
    if traffic_saver and final_members[0] != "DIRECT":
        raise ValueError(f"Traffic-Saver Shadowrocket Final group must default to DIRECT: {final_group_name}")
    if not traffic_saver and final_members[0] == "DIRECT":
        raise ValueError(f"Strict Shadowrocket Final group must not default to DIRECT: {final_group_name}")

    download_group_name = GROUP_LABELS["Download"]
    download_members = groups.get(download_group_name)
    if not download_members:
        raise ValueError(f"Missing required Shadowrocket proxy group: {download_group_name}")
    if download_members[0] == "DIRECT":
        raise ValueError(f"Shadowrocket Download group must not default to DIRECT: {download_group_name}")

    rules = _shadowrocket_section(lines, "Rule")
    if not rules:
        raise ValueError("Shadowrocket config has no rules")
    if not rules[-1].startswith("FINAL,"):
        raise ValueError(f"Last Shadowrocket rule must be FINAL: {rules[-1]}")

    for fragment in SHADOWROCKET_REQUIRED_RULE_FRAGMENTS:
        _first_index_contains(rules, fragment)

    for before, after in SHADOWROCKET_RULE_ORDER:
        before_index = _first_index_contains(rules, before)
        after_index = _first_index_contains(rules, after)
        if before_index >= after_index:
            raise ValueError(f"Shadowrocket rule order violation: {before!r} must be before {after!r}")
