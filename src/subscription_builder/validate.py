from __future__ import annotations

from pathlib import Path

import yaml

from .rule_grammar import policy_from_rule, referenced_rule_provider_ids
from .routing_contract import (
    BUILTIN_POLICIES,
    GROUP_LABELS,
    SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_FIRST,
    SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_MEMBER,
    SHADOWROCKET_GROUPS_FOLLOW_PROXY,
    SHADOWROCKET_REQUIRED_RULE_FRAGMENTS,
    SHADOWROCKET_RULE_ORDER,
    SHADOWROCKET_SELECT_GROUPS_INCLUDE_ALL_NODES,
)


PUBLIC_PAGES_MARKER = ".generated-public-pages"
PUBLIC_PAGES_ALLOWED_ROOT_ENTRIES = {"index.html", ".nojekyll", PUBLIC_PAGES_MARKER, "rules"}
PRIVATE_ARTIFACT_NAMES = {
    "mihomo-full.yaml",
    "mihomo-android.yaml",
    "mihomo-generic.yaml",
    "shadowrocket.conf",
    "shadowrocket-strict.conf",
    "shadowrocket-subscription.txt",
    "shadowrocket-uris.txt",
    "node-sources.json",
    "nodes.json",
}


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


def _validate_rule_groups(config: dict[str, object]) -> None:
    groups = {str(group["name"]) for group in config.get("proxy-groups", [])}
    missing: set[str] = set()
    for rule in config.get("rules", []):
        policy = policy_from_rule(str(rule))
        if policy and policy not in BUILTIN_POLICIES and policy not in groups:
            missing.add(policy)
    if missing:
        raise ValueError(f"Mihomo rules reference missing proxy groups: {sorted(missing)}")


def _validate_rule_providers(config: dict[str, object]) -> None:
    providers = config.get("rule-providers", {})
    if not isinstance(providers, dict):
        raise TypeError("rule-providers must be a mapping")

    missing_provider_ids = {
        provider_id
        for provider_id in referenced_rule_provider_ids(str(rule) for rule in config.get("rules", []))
        if provider_id not in providers
    }
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

    for key in validation.get("foreign_groups_no_direct_member", []):
        group_name = GROUP_LABELS[str(key)]
        group = groups.get(group_name)
        if not group:
            raise ValueError(f"Missing required proxy group: {group_name}")
        proxies = group.get("proxies", [])
        if not isinstance(proxies, list):
            raise ValueError(f"Proxy group proxies must be a list: {group_name}")
        if "DIRECT" in proxies:
            raise ValueError(f"Proxy group must not include DIRECT: {group_name}")

    proxy_group_name = GROUP_LABELS["PROXY"]
    for key in validation.get("groups_follow_proxy", []):
        group_name = GROUP_LABELS[str(key)]
        group = groups.get(group_name)
        if not group:
            raise ValueError(f"Missing required proxy group: {group_name}")
        proxies = group.get("proxies", [])
        if not isinstance(proxies, list) or not proxies or proxies[0] != proxy_group_name:
            raise ValueError(f"Proxy group must default to {proxy_group_name}: {group_name}")

    node_names = {str(proxy["name"]) for proxy in config["proxies"] if isinstance(proxy, dict) and "name" in proxy}
    for key in validation.get("select_groups_include_all_nodes", []):
        group_name = GROUP_LABELS[str(key)]
        group = groups.get(group_name)
        if not group:
            raise ValueError(f"Missing required proxy group: {group_name}")
        if group.get("type") != "select":
            raise ValueError(f"Proxy group must be a select group: {group_name}")
        proxies = group.get("proxies", [])
        if not isinstance(proxies, list):
            raise ValueError(f"Proxy group proxies must be a list: {group_name}")
        missing_nodes = node_names - {str(item) for item in proxies}
        if missing_nodes:
            raise ValueError(f"Proxy group does not expose every node: {group_name}: {sorted(missing_nodes)}")

    fallback_key = validation.get("fallback_group")
    if fallback_key:
        fallback_name = GROUP_LABELS[str(fallback_key)]
        fallback_group = groups.get(fallback_name)
        if not fallback_group:
            raise ValueError(f"Missing required fallback group: {fallback_name}")
        if fallback_group.get("type") != "fallback":
            raise ValueError(f"Required fallback group must use type fallback: {fallback_name}")
        fallback_members = fallback_group.get("proxies", [])
        if not isinstance(fallback_members, list) or node_names - {str(item) for item in fallback_members}:
            raise ValueError(f"Required fallback group must contain every node: {fallback_name}")

    _validate_rule_groups(config)
    _validate_rule_providers(config)


def _entry_key(entry: dict[str, object]) -> str:
    return f"{entry.get('client', '')}/{entry.get('rule_id', '')}"


def _validate_rule_audit_baseline(entries: list[dict[str, object]], baseline_path: Path) -> list[str]:
    if not baseline_path.exists():
        return []
    payload = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), dict):
        raise TypeError(f"{baseline_path} must contain a rules mapping")

    entries_by_key = {_entry_key(entry): entry for entry in entries}
    errors: list[str] = []
    for key, raw_rule in payload["rules"].items():
        if not isinstance(raw_rule, dict):
            raise TypeError(f"Rule audit baseline entry must be a mapping: {key}")
        entry = entries_by_key.get(str(key))
        if not entry:
            errors.append(f"missing audited provider from baseline: {key}")
            continue

        line_count = int(entry.get("line_count", 0))
        domain_count = int(entry.get("domain_count", 0))
        ip_count = int(entry.get("ip_count", 0))
        process_count = int(entry.get("process_count", 0))
        min_lines = raw_rule.get("min_lines")
        max_lines = raw_rule.get("max_lines")

        if min_lines is not None and line_count < int(min_lines):
            errors.append(f"rule provider below baseline min_lines: {key} has {line_count}, expected >= {min_lines}")
        if max_lines is not None and line_count > int(max_lines):
            errors.append(f"rule provider above baseline max_lines: {key} has {line_count}, expected <= {max_lines}")
        if raw_rule.get("require_domains") and domain_count <= 0:
            errors.append(f"rule provider has no domain rules: {key}")
        if raw_rule.get("forbid_ips") and ip_count:
            errors.append(f"rule provider unexpectedly contains IP rules: {key}")
        if raw_rule.get("forbid_process") and process_count:
            errors.append(f"rule provider unexpectedly contains process rules: {key}")
    return errors


def validate_rule_audit(audit_path: Path, baseline_path: Path | None = None) -> None:
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

    if baseline_path is not None:
        errors.extend(_validate_rule_audit_baseline(entries, baseline_path))

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


def _shadowrocket_proxy_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in _shadowrocket_section(lines, "Proxy"):
        if "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return names


def validate_shadowrocket_config(config_path: Path) -> None:
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

    for key in SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_MEMBER:
        group_name = GROUP_LABELS[key]
        members = groups.get(group_name)
        if not members:
            raise ValueError(f"Missing required Shadowrocket proxy group: {group_name}")
        if "DIRECT" in members:
            raise ValueError(f"Shadowrocket proxy group must not include DIRECT: {group_name}")

    proxy_group_name = GROUP_LABELS["PROXY"]
    for key in SHADOWROCKET_GROUPS_FOLLOW_PROXY:
        group_name = GROUP_LABELS[key]
        members = groups.get(group_name)
        if not members or members[0] != proxy_group_name:
            raise ValueError(f"Shadowrocket proxy group must default to {proxy_group_name}: {group_name}")

    node_names = _shadowrocket_proxy_names(lines)
    for key in SHADOWROCKET_SELECT_GROUPS_INCLUDE_ALL_NODES:
        group_name = GROUP_LABELS[key]
        members = groups.get(group_name)
        if not members:
            raise ValueError(f"Missing required Shadowrocket proxy group: {group_name}")
        missing_nodes = node_names - set(members)
        if missing_nodes:
            raise ValueError(
                f"Shadowrocket proxy group does not expose every node: {group_name}: {sorted(missing_nodes)}"
            )

    fallback_group_name = GROUP_LABELS["Fallback"]
    fallback_members = groups.get(fallback_group_name)
    if not fallback_members:
        raise ValueError(f"Missing required Shadowrocket fallback group: {fallback_group_name}")
    if node_names - set(fallback_members):
        raise ValueError(f"Shadowrocket fallback group must contain every node: {fallback_group_name}")

    final_group_name = GROUP_LABELS["Final"]
    final_members = groups.get(final_group_name)
    if not final_members:
        raise ValueError(f"Missing required Shadowrocket proxy group: {final_group_name}")
    if final_members[0] == "DIRECT":
        raise ValueError(f"Shadowrocket Final group must not default to DIRECT: {final_group_name}")

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


def validate_public_pages_artifact(public_root: Path) -> None:
    if not public_root.exists():
        raise FileNotFoundError(public_root)
    if not public_root.is_dir():
        raise NotADirectoryError(public_root)

    required_paths = [
        public_root / PUBLIC_PAGES_MARKER,
        public_root / ".nojekyll",
        public_root / "index.html",
        public_root / "rules" / "mihomo",
        public_root / "rules" / "shadowrocket",
    ]
    missing = [str(path.relative_to(public_root)) for path in required_paths if not path.exists()]
    if missing:
        raise ValueError(f"Public Pages artifact is missing required paths: {missing}")

    errors: list[str] = []
    for path in public_root.rglob("*"):
        relative = path.relative_to(public_root)
        if path.is_file() and path.name in PRIVATE_ARTIFACT_NAMES:
            errors.append(f"private artifact present in public Pages output: {relative}")
        if len(relative.parts) == 1 and relative.parts[0] not in PUBLIC_PAGES_ALLOWED_ROOT_ENTRIES:
            errors.append(f"unexpected root entry in public Pages output: {relative}")
        if path.name == ".DS_Store":
            errors.append(f"metadata file present in public Pages output: {relative}")

    if errors:
        raise ValueError("Public Pages safety failures:\n" + "\n".join(errors))
