from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
import re
import shutil
from typing import Iterable

from jinja2 import Environment, FileSystemLoader
import yaml

from .models import ProxyNode
from .rules import BuiltRule


GROUP_LABELS = {
    "AUTO": "⚡ 自动选择",
    "FALLBACK": "🔁 故障转移",
    "MANUAL": "🧭 手动选择",
    "PROXY": "🚀 代理",
    "RuleUpdate": "🔄 规则更新",
    "AI": "🤖 AI",
    "AI_AUTO": "🤖 AI 自动选择",
    "AI_FALLBACK": "🤖 AI 故障转移",
    "GitHub": "💻 GitHub",
    "Google": "🔎 Google",
    "Developer": "🛠 Developer",
    "Apple": "🍎 Apple",
    "Microsoft": "🪟 Microsoft",
    "Telegram": "✈️ Telegram",
    "Streaming": "📺 流媒体",
    "Download": "⬇️ 下载",
    "Final": "🌐 兜底",
}

LOGIC_RULE_TYPES = {"AND", "OR", "NOT"}
SHADOWROCKET_UNSUPPORTED_RULE_TYPES = {*LOGIC_RULE_TYPES, "SUB-RULE"}
RULE_SET_REF_RE = re.compile(r"RULE-SET,([A-Za-z0-9_.!@-]+)")
HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
PUBLIC_PAGES_MARKER = ".generated-public-pages"


def _g(name: str) -> str:
    return GROUP_LABELS[name]


def _provider_url(base_url: str, relative_path: str) -> str:
    return f"{base_url}/{relative_path.lstrip('/')}"


def _rule_lookup(items: Iterable[BuiltRule]) -> dict[str, BuiltRule]:
    return {item.rule_id: item for item in items}


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_mihomo_template(project_root: Path, name: str) -> object:
    return _load_yaml(project_root / "config" / "mihomo" / name)


def _resolve_policy(value: str) -> str:
    if value.startswith("@"):
        return _g(value[1:])
    return value


def _resolve_rule(line: str) -> str:
    rule_type = line.split(",", 1)[0]
    if rule_type in LOGIC_RULE_TYPES:
        head, policy = line.rsplit(",", 1)
        return f"{head},{_resolve_policy(policy)}"

    parts = line.split(",")
    if parts[0] in {"MATCH", "FINAL"} and len(parts) >= 2:
        parts[1] = _resolve_policy(parts[1])
        return ",".join(parts)
    if len(parts) >= 3:
        parts[2] = _resolve_policy(parts[2])
    return ",".join(parts)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _is_exact_hostname(value: str) -> bool:
    if len(value) > 253:
        return False
    return all(HOST_LABEL_RE.fullmatch(label) for label in value.split("."))


def _proxy_server_direct_rules(nodes: Iterable[ProxyNode]) -> list[str]:
    rules: list[str] = []
    for node in nodes:
        host = node.server.strip().removeprefix("[").removesuffix("]").rstrip(".").lower()
        if not host:
            continue
        try:
            address = ip_address(host)
        except ValueError:
            if not _is_exact_hostname(host):
                continue
            rules.append(f"DOMAIN,{host},DIRECT")
            continue
        if address.version == 4:
            rules.append(f"IP-CIDR,{address}/32,DIRECT,no-resolve")
        else:
            rules.append(f"IP-CIDR6,{address}/128,DIRECT,no-resolve")
    return _dedupe(rules)


def _insert_proxy_server_direct_rules(rules: list[str], nodes: Iterable[ProxyNode]) -> list[str]:
    rendered = [*rules]
    _insert_after_rules(rendered, "RULE-SET,lan_non_ip,DIRECT", _proxy_server_direct_rules(nodes))
    return rendered


def _node_names_for_group(nodes: list[ProxyNode], include_nodes: object) -> list[str]:
    if isinstance(include_nodes, dict):
        selected = _node_names_for_group_spec(nodes, include_nodes)
        if not selected and "fallback_include_nodes" in include_nodes:
            return _node_names_for_group(nodes, include_nodes["fallback_include_nodes"])
        return selected
    if not include_nodes:
        return []
    if include_nodes is True or include_nodes == "default":
        return [node.name for node in nodes if node.source_group_policy != "manual_only"]
    if include_nodes == "manual_only":
        return [node.name for node in nodes if node.source_group_policy == "manual_only"]
    if include_nodes == "all":
        return [node.name for node in nodes]
    raise ValueError(f"Unsupported include_nodes policy: {include_nodes}")


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise TypeError(f"Expected string or list of strings, got: {type(value).__name__}")


def _node_names_for_group_spec(nodes: list[ProxyNode], spec: dict[str, object]) -> list[str]:
    source_ids = set(_string_list(spec.get("source_ids")))
    group_policies = set(_string_list(spec.get("group_policies")))
    name_contains = _string_list(spec.get("name_contains"))
    name_regex = str(spec["name_regex"]) if spec.get("name_regex") else ""
    name_pattern = re.compile(name_regex) if name_regex else None
    preferred_name_contains = _string_list(spec.get("preferred_name_contains"))

    selected: list[tuple[int, ProxyNode]] = []
    for index, node in enumerate(nodes):
        if source_ids and node.source_id not in source_ids:
            continue
        if group_policies and node.source_group_policy not in group_policies:
            continue
        if name_contains and not any(token in node.name for token in name_contains):
            continue
        if name_pattern and not name_pattern.search(node.name):
            continue
        selected.append((index, node))

    def sort_key(item: tuple[int, ProxyNode]) -> tuple[int, int]:
        index, node = item
        for rank, token in enumerate(preferred_name_contains):
            if token in node.name:
                return rank, index
        return len(preferred_name_contains), index

    return [node.name for _, node in sorted(selected, key=sort_key)]


def _format_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)}{units[unit_index]}"
    return f"{size:.2f}{units[unit_index]}"


def _format_expire(value: object) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp <= 0:
        return str(value)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def _format_node_source_comments(node_source_audit: dict[str, object] | None) -> list[str]:
    if not node_source_audit:
        return []
    comments = ["Node source summary:"]
    for source in node_source_audit.get("sources", []):
        if not isinstance(source, dict):
            continue
        label = source.get("label", source.get("id", "source"))
        policy = source.get("group_policy", "default")
        node_count = source.get("node_count", 0)
        suffix = ""
        userinfo = source.get("subscription_userinfo", {})
        if isinstance(userinfo, dict) and userinfo:
            upload = int(userinfo.get("upload", 0))
            download = int(userinfo.get("download", 0))
            total = userinfo.get("total")
            used = upload + download
            traffic = f"{_format_bytes(used)}"
            if total is not None:
                traffic = f"{traffic} / {_format_bytes(total)}"
            expire = userinfo.get("expire")
            suffix = f", traffic={traffic}"
            if expire is not None:
                suffix += f", expires={_format_expire(expire)}"
        else:
            metadata = source.get("metadata", {})
            if isinstance(metadata, dict):
                traffic = metadata.get("traffic_observed")
                expires = metadata.get("expires_on")
                if traffic:
                    suffix += f", traffic={traffic}"
                if expires:
                    suffix += f", expires={expires}"
        comments.append(f"- {label}: nodes={node_count}, policy={policy}{suffix}")
    return comments


def _append_unique_list(target: dict[str, object], path: list[str], values: list[str]) -> None:
    current: object = target
    for key in path[:-1]:
        if not isinstance(current, dict):
            raise TypeError(f"Cannot merge overlay path: {'.'.join(path)}")
        current = current.setdefault(key, {})
    if not isinstance(current, dict):
        raise TypeError(f"Cannot merge overlay path: {'.'.join(path)}")
    key = path[-1]
    existing = current.setdefault(key, [])
    if not isinstance(existing, list):
        raise TypeError(f"Overlay target is not a list: {'.'.join(path)}")
    existing[:] = _dedupe([*existing, *values])


def _insert_after_rules(rules: list[str], anchor: str, insertions: list[str]) -> None:
    if not insertions:
        return
    for index, rule in enumerate(rules):
        if rule.startswith(anchor):
            rules[index + 1:index + 1] = insertions
            return
    raise ValueError(f"Overlay anchor not found: {anchor}")


def _apply_overlay(config: dict[str, object], rules: list[str], overlay: dict[str, object]) -> list[str]:
    prepend_rules = [str(item) for item in overlay.get("prepend-rules", [])]
    for item in overlay.get("insert-after", []):
        if not isinstance(item, dict):
            raise TypeError("overlay insert-after entries must be mappings")
        anchor = str(item["anchor"])
        insertions = [str(rule) for rule in item.get("rules", [])]
        _insert_after_rules(rules, anchor, insertions)
    dns_overlay = overlay.get("dns", {})
    if isinstance(dns_overlay, dict):
        fake_ip_filter = dns_overlay.get("fake-ip-filter", {})
        if isinstance(fake_ip_filter, dict):
            append_values = fake_ip_filter.get("append", [])
            if isinstance(append_values, list):
                _append_unique_list(config, ["dns", "fake-ip-filter"], [str(item) for item in append_values])
    return prepend_rules


def _build_rule_providers(mihomo_rules: Iterable[BuiltRule], public_base_url: str) -> dict[str, dict[str, object]]:
    providers: dict[str, dict[str, object]] = {}
    for item in mihomo_rules:
        path = Path(item.path)
        provider: dict[str, object] = {
            "type": "http",
            "behavior": item.behavior,
            "interval": 43200,
            "path": f"./providers/{path.name}",
            "url": _provider_url(public_base_url, item.path),
            "proxy": _g("RuleUpdate"),
        }
        if item.format == "text":
            provider["format"] = "text"
        providers[item.rule_id] = provider
    return providers


def _referenced_rule_provider_ids(rules: Iterable[str]) -> set[str]:
    provider_ids: set[str] = set()
    for rule in rules:
        rule_text = str(rule)
        parts = rule_text.split(",")
        if len(parts) >= 2 and parts[0] == "RULE-SET":
            provider_ids.add(parts[1])
        for match in RULE_SET_REF_RE.finditer(rule_text):
            provider_ids.add(match.group(1))
    return provider_ids


def _build_mihomo_groups(project_root: Path, nodes: list[ProxyNode]) -> list[dict[str, object]]:
    payload = _load_mihomo_template(project_root, "groups.yaml")
    if not isinstance(payload, dict):
        raise TypeError("config/mihomo/groups.yaml must contain a mapping")

    groups: list[dict[str, object]] = []
    for raw_group in payload.get("groups", []):
        key = str(raw_group["key"])
        group: dict[str, object] = {
            "name": _g(key),
            "type": raw_group["type"],
        }
        members = [_resolve_policy(str(item)) for item in raw_group.get("members", [])]
        group_node_names = _node_names_for_group(nodes, raw_group.get("include_nodes"))
        if raw_group.get("nodes_first"):
            members = [*group_node_names, *members]
        else:
            members.extend(group_node_names)
        if group["type"] in {"select", "fallback", "url-test"}:
            group["proxies"] = _dedupe(members)
        for field in ("url", "interval", "tolerance", "timeout", "lazy"):
            if field in raw_group:
                group[field] = raw_group[field]
        groups.append(group)
    return groups


SHADOWROCKET_TRAFFIC_SAVER_FIRST_MEMBERS = {
    "Final": ["DIRECT"],
}


def _shadowrocket_traffic_saver_members(group_name: str, members: list[str]) -> list[str]:
    first_members = SHADOWROCKET_TRAFFIC_SAVER_FIRST_MEMBERS.get(group_name)
    if not first_members:
        return members
    remaining = [member for member in members if member not in first_members]
    return [*first_members, *remaining]


def _build_shadowrocket_groups(project_root: Path, nodes: list[ProxyNode], *, traffic_saver: bool) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for group in _build_mihomo_groups(project_root, nodes):
        if group["name"] == _g("RuleUpdate"):
            continue
        group_key = next((key for key, label in GROUP_LABELS.items() if label == group["name"]), "")
        members = [str(item) for item in group.get("proxies", [])]
        if traffic_saver:
            members = _shadowrocket_traffic_saver_members(group_key, members)
        shadow_group: dict[str, object] = {
            "name": group["name"],
            "type": group["type"],
            "members": members,
            "options": [],
        }
        options: list[str] = []
        if group["type"] in {"fallback", "url-test"}:
            if "url" in group:
                options.append(f"url={group['url']}")
            if "interval" in group:
                options.append(f"interval={group['interval']}")
            if group["type"] == "url-test" and "tolerance" in group:
                options.append(f"tolerance={group['tolerance']}")
        shadow_group["options"] = options
        shadow_group["line"] = ",".join(
            [f"{shadow_group['name']} = {shadow_group['type']}", *members, *options]
        )
        groups.append(shadow_group)
    return groups


def _build_mihomo_rules(project_root: Path, config: dict[str, object], overlay_name: str, nodes: list[ProxyNode]) -> list[str]:
    payload = _load_mihomo_template(project_root, "rules.yaml")
    if not isinstance(payload, dict):
        raise TypeError("config/mihomo/rules.yaml must contain a mapping")

    rules = [str(item) for item in payload.get("rules", [])]
    overlay_path = project_root / "config" / "mihomo" / "overlays" / f"{overlay_name}.yaml"
    if overlay_path.exists():
        overlay = _load_yaml(overlay_path)
        if not isinstance(overlay, dict):
            raise TypeError(f"config/mihomo/overlays/{overlay_name}.yaml must contain a mapping")
        rules = [*_apply_overlay(config, rules, overlay), *rules]
    rules = _insert_proxy_server_direct_rules(rules, nodes)
    return [_resolve_rule(rule) for rule in rules]


def _build_shadowrocket_rules(
    project_root: Path,
    public_base_url: str,
    shadow_rules: dict[str, BuiltRule],
    nodes: list[ProxyNode],
) -> list[str]:
    payload = _load_mihomo_template(project_root, "rules.yaml")
    if not isinstance(payload, dict):
        raise TypeError("config/mihomo/rules.yaml must contain a mapping")

    rendered: list[str] = []
    for raw_rule in _insert_proxy_server_direct_rules([str(item) for item in payload.get("rules", [])], nodes):
        rule = str(raw_rule)
        parts = rule.split(",")
        rule_type = parts[0]
        if rule_type in SHADOWROCKET_UNSUPPORTED_RULE_TYPES:
            continue
        if rule_type in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6"}:
            if len(parts) < 3:
                raise ValueError(f"Invalid Shadowrocket-compatible rule: {rule}")
            parts[2] = _resolve_policy(parts[2])
            rendered.append(",".join(parts[:3]))
            continue
        if rule_type == "RULE-SET":
            if len(parts) < 3:
                raise ValueError(f"Invalid RULE-SET rule: {rule}")
            rule_id = parts[1]
            if rule_id not in shadow_rules:
                if rule_id.endswith("_direct_ip"):
                    continue
                raise ValueError(f"Missing Shadowrocket rule artifact for rule-set: {rule_id}")
            policy = _resolve_policy(parts[2])
            rendered.append(f"RULE-SET,{_provider_url(public_base_url, shadow_rules[rule_id].path)},{policy}")
            continue
        if rule_type in {"MATCH", "FINAL"}:
            if len(parts) < 2:
                raise ValueError(f"Invalid final rule: {rule}")
            rendered.append(f"FINAL,{_resolve_policy(parts[1])}")
            continue
        if rule_type == "GEOSITE":
            geosite_rule_ids = {
                "private": "private",
                "github": "github",
                "google": "google",
                "cn": "cn",
                "geolocation-!cn": "geolocation_non_cn",
            }
            if len(parts) >= 3 and parts[1] in geosite_rule_ids:
                rule_id = geosite_rule_ids[parts[1]]
                if rule_id not in shadow_rules:
                    raise ValueError(f"Missing Shadowrocket rule artifact for geosite: {parts[1]}")
                policy = _resolve_policy(parts[2])
                rendered.append(f"RULE-SET,{_provider_url(public_base_url, shadow_rules[rule_id].path)},{policy}")
                continue
            continue
        if rule_type == "GEOIP":
            geoip_rule_ids = {
                "private": "lan_ip",
                "CN": "cn_ip",
            }
            if len(parts) >= 3 and parts[1] in geoip_rule_ids:
                rule_id = geoip_rule_ids[parts[1]]
                if rule_id not in shadow_rules:
                    raise ValueError(f"Missing Shadowrocket rule artifact for geoip: {parts[1]}")
                policy = _resolve_policy(parts[2])
                rendered.append(f"RULE-SET,{_provider_url(public_base_url, shadow_rules[rule_id].path)},{policy}")
                continue
            continue
        raise ValueError(f"Unsupported rule type for Shadowrocket: {rule}")
    return _dedupe(rendered)


def render_mihomo(
    *,
    project_root: Path,
    output_root: Path,
    public_base_url: str,
    nodes: list[ProxyNode],
    manifest: dict[str, list[BuiltRule]],
    node_source_audit: dict[str, object] | None = None,
    overlay_name: str = "macos",
    output_name: str = "mihomo-full.yaml",
) -> None:
    env = Environment(loader=FileSystemLoader(str(project_root / "templates")), autoescape=False)
    template = env.get_template("mihomo.yaml.j2")

    mihomo_rules = manifest["mihomo"]
    base_config = _load_mihomo_template(project_root, "base.yaml")
    if not isinstance(base_config, dict):
        raise TypeError("config/mihomo/base.yaml must contain a mapping")
    config = deepcopy(base_config)
    config["proxies"] = [node.to_mihomo_proxy() for node in nodes]
    config["proxy-groups"] = _build_mihomo_groups(project_root, nodes)
    config["rules"] = _build_mihomo_rules(project_root, config, overlay_name, nodes)
    all_providers = _build_rule_providers(mihomo_rules, public_base_url)
    referenced_provider_ids = _referenced_rule_provider_ids(config["rules"])
    config["rule-providers"] = {
        provider_id: provider
        for provider_id, provider in all_providers.items()
        if provider_id in referenced_provider_ids
    }
    body_yaml = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=120)
    rendered = template.render(body_yaml=body_yaml, node_source_comments=_format_node_source_comments(node_source_audit))
    (output_root / output_name).write_text(rendered, encoding="utf-8")


def render_shadowrocket(
    *,
    project_root: Path,
    output_root: Path,
    public_base_url: str,
    private_base_url: str | None = None,
    nodes: list[ProxyNode],
    manifest: dict[str, list[BuiltRule]],
    node_source_audit: dict[str, object] | None = None,
    output_name: str = "shadowrocket.conf",
    traffic_saver: bool = True,
) -> None:
    env = Environment(loader=FileSystemLoader(str(project_root / "templates")), autoescape=False, trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("shadowrocket.conf.j2")

    shadow_rules = _rule_lookup(manifest["shadowrocket"])
    shadow_nodes = [node for node in nodes if node.supports_shadowrocket_config()]
    private_base_url = private_base_url or public_base_url
    context = {
        "generated_comment": "Generated by mihomo-subscription-builder. Edit templates instead of this file.",
        "node_source_comments": _format_node_source_comments(node_source_audit),
        "fallback_subscription_url": _provider_url(private_base_url, "shadowrocket-subscription.txt"),
        "proxy_lines": [node.to_shadowrocket_proxy_line() for node in shadow_nodes],
        "groups": _build_shadowrocket_groups(project_root, shadow_nodes, traffic_saver=traffic_saver),
        "rules": _build_shadowrocket_rules(project_root, public_base_url, shadow_rules, shadow_nodes),
    }
    rendered = template.render(**context)
    (output_root / output_name).write_text(rendered + "\n", encoding="utf-8")


def render_index(*, output_root: Path, public_base_url: str, private_base_url: str | None = None) -> None:
    private_base_url = private_base_url or public_base_url
    links = [
        ("Mihomo subscription", f"{private_base_url}/mihomo-full.yaml"),
        ("Mihomo Android subscription", f"{private_base_url}/mihomo-android.yaml"),
        ("Shadowrocket config", f"{private_base_url}/shadowrocket.conf"),
        ("Shadowrocket strict config", f"{private_base_url}/shadowrocket-strict.conf"),
        ("Shadowrocket node subscription", f"{private_base_url}/shadowrocket-subscription.txt"),
        ("Public rules", f"{public_base_url}/rules/"),
    ]
    items = "\n".join(f'<li><a href="{url}">{label}</a></li>' for label, url in links)
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>mihomo-subscription-builder</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 760px; margin: 48px auto; padding: 0 20px; line-height: 1.6; color: #111827; }}
    h1 {{ margin-bottom: 8px; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }}
    a {{ color: #0f62fe; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>mihomo-subscription-builder</h1>
  <p>Remote subscription artifacts for Mihomo and Shadowrocket.</p>
  <ul>
    {items}
  </ul>
  <p>Private subscription base URL: <code>{private_base_url}</code></p>
  <p>Public rules base URL: <code>{public_base_url}</code></p>
</body>
</html>
"""
    (output_root / "index.html").write_text(html + "\n", encoding="utf-8")


def prepare_public_pages(*, source_root: Path, output_root: Path, public_base_url: str) -> None:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root == source_root:
        raise ValueError("Public Pages output must not be the same directory as the private artifact source.")
    if output_root.exists():
        marker = output_root / PUBLIC_PAGES_MARKER
        if any(output_root.iterdir()) and not marker.exists():
            raise ValueError(f"Refusing to overwrite non-generated public Pages directory: {output_root}")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    rules_source = source_root / "rules"
    if not rules_source.exists():
        raise FileNotFoundError(rules_source)
    shutil.copytree(rules_source, output_root / "rules")
    (output_root / ".nojekyll").write_text("", encoding="utf-8")
    (output_root / PUBLIC_PAGES_MARKER).write_text(
        "Generated by mihomo-subscription-builder prepare-public-pages. Safe to replace.\n",
        encoding="utf-8",
    )

    links = [
        ("Mihomo rule providers", f"{public_base_url}/rules/mihomo/"),
        ("Shadowrocket rule sets", f"{public_base_url}/rules/shadowrocket/"),
    ]
    items = "\n".join(f'<li><a href="{url}">{label}</a></li>' for label, url in links)
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>mihomo-subscription-builder public rules</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 760px; margin: 48px auto; padding: 0 20px; line-height: 1.6; color: #111827; }}
    h1 {{ margin-bottom: 8px; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }}
    a {{ color: #0f62fe; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>mihomo-subscription-builder public rules</h1>
  <p>This public artifact intentionally contains rule files only. Full Mihomo and Shadowrocket subscriptions contain proxy nodes and must be delivered from a private URL.</p>
  <ul>
    {items}
  </ul>
  <p>Public rules base URL: <code>{public_base_url}</code></p>
</body>
</html>
"""
    (output_root / "index.html").write_text(html + "\n", encoding="utf-8")
