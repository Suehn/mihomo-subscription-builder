from __future__ import annotations

from copy import deepcopy
from pathlib import Path
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
    "GitHub": "💻 GitHub",
    "Apple": "🍎 Apple",
    "Microsoft": "🪟 Microsoft",
    "Telegram": "✈️ Telegram",
    "Streaming": "📺 流媒体",
    "Download": "⬇️ 下载",
    "Final": "🌐 兜底",
}


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


def _apply_overlay(config: dict[str, object], overlay: dict[str, object]) -> list[str]:
    prepend_rules = [str(item) for item in overlay.get("prepend-rules", [])]
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
        parts = str(rule).split(",")
        if len(parts) >= 2 and parts[0] == "RULE-SET":
            provider_ids.add(parts[1])
    return provider_ids


def _build_mihomo_groups(project_root: Path, node_names: list[str]) -> list[dict[str, object]]:
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
        if raw_group.get("include_nodes"):
            members.extend(node_names)
        if group["type"] in {"select", "fallback", "url-test"}:
            group["proxies"] = _dedupe(members)
        for field in ("url", "interval", "tolerance", "timeout", "lazy"):
            if field in raw_group:
                group[field] = raw_group[field]
        groups.append(group)
    return groups


def _build_shadowrocket_groups(project_root: Path, node_names: list[str]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for group in _build_mihomo_groups(project_root, node_names):
        if group["name"] == _g("RuleUpdate"):
            continue
        members = [str(item) for item in group.get("proxies", [])]
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


def _build_mihomo_rules(project_root: Path, config: dict[str, object], overlay_name: str) -> list[str]:
    payload = _load_mihomo_template(project_root, "rules.yaml")
    if not isinstance(payload, dict):
        raise TypeError("config/mihomo/rules.yaml must contain a mapping")

    rules = [str(item) for item in payload.get("rules", [])]
    overlay_path = project_root / "config" / "mihomo" / "overlays" / f"{overlay_name}.yaml"
    if overlay_path.exists():
        overlay = _load_yaml(overlay_path)
        if not isinstance(overlay, dict):
            raise TypeError(f"config/mihomo/overlays/{overlay_name}.yaml must contain a mapping")
        rules = [*_apply_overlay(config, overlay), *rules]
    return [_resolve_rule(rule) for rule in rules]


def _build_shadowrocket_rules(project_root: Path, public_base_url: str, shadow_rules: dict[str, BuiltRule]) -> list[str]:
    payload = _load_mihomo_template(project_root, "rules.yaml")
    if not isinstance(payload, dict):
        raise TypeError("config/mihomo/rules.yaml must contain a mapping")

    rendered: list[str] = []
    for raw_rule in payload.get("rules", []):
        rule = str(raw_rule)
        parts = rule.split(",")
        rule_type = parts[0]
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
                "private": "private",
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
    overlay_name: str = "macos",
    output_name: str = "mihomo-full.yaml",
) -> None:
    env = Environment(loader=FileSystemLoader(str(project_root / "templates")), autoescape=False)
    template = env.get_template("mihomo.yaml.j2")

    mihomo_rules = manifest["mihomo"]
    node_names = [node.name for node in nodes]
    base_config = _load_mihomo_template(project_root, "base.yaml")
    if not isinstance(base_config, dict):
        raise TypeError("config/mihomo/base.yaml must contain a mapping")
    config = deepcopy(base_config)
    config["proxies"] = [node.to_mihomo_proxy() for node in nodes]
    config["proxy-groups"] = _build_mihomo_groups(project_root, node_names)
    config["rules"] = _build_mihomo_rules(project_root, config, overlay_name)
    all_providers = _build_rule_providers(mihomo_rules, public_base_url)
    referenced_provider_ids = _referenced_rule_provider_ids(config["rules"])
    config["rule-providers"] = {
        provider_id: provider
        for provider_id, provider in all_providers.items()
        if provider_id in referenced_provider_ids
    }
    body_yaml = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=120)
    rendered = template.render(body_yaml=body_yaml)
    (output_root / output_name).write_text(rendered, encoding="utf-8")


def render_shadowrocket(
    *,
    project_root: Path,
    output_root: Path,
    public_base_url: str,
    nodes: list[ProxyNode],
    manifest: dict[str, list[BuiltRule]],
) -> None:
    env = Environment(loader=FileSystemLoader(str(project_root / "templates")), autoescape=False, trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("shadowrocket.conf.j2")

    shadow_rules = _rule_lookup(manifest["shadowrocket"])
    proxy_names = [node.name for node in nodes]
    context = {
        "generated_comment": "Generated by mihomo-subscription-builder. Edit templates instead of this file.",
        "fallback_subscription_url": _provider_url(public_base_url, "shadowrocket-subscription.txt"),
        "proxy_lines": [node.to_shadowrocket_proxy_line() for node in nodes],
        "groups": _build_shadowrocket_groups(project_root, proxy_names),
        "rules": _build_shadowrocket_rules(project_root, public_base_url, shadow_rules),
    }
    rendered = template.render(**context)
    (output_root / "shadowrocket.conf").write_text(rendered + "\n", encoding="utf-8")


def render_index(*, output_root: Path, public_base_url: str) -> None:
    links = [
        ("Mihomo subscription", f"{public_base_url}/mihomo-full.yaml"),
        ("Mihomo Android subscription", f"{public_base_url}/mihomo-android.yaml"),
        ("Shadowrocket config", f"{public_base_url}/shadowrocket.conf"),
        ("Shadowrocket node subscription", f"{public_base_url}/shadowrocket-subscription.txt"),
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
  <p>Base URL: <code>{public_base_url}</code></p>
</body>
</html>
"""
    (output_root / "index.html").write_text(html + "\n", encoding="utf-8")
