from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader
import yaml

from .models import ProxyNode
from .rules import BuiltRule


def _provider_url(base_url: str, relative_path: str) -> str:
    return f"{base_url}/{relative_path.lstrip('/')}"


def _rule_lookup(items: Iterable[BuiltRule]) -> dict[str, BuiltRule]:
    return {item.rule_id: item for item in items}


def _build_proxy_group(group_name: str, preferred: list[str], node_names: list[str]) -> dict[str, object]:
    seen: list[str] = []
    for item in preferred + node_names:
        if item not in seen:
            seen.append(item)
    return {
        "name": group_name,
        "type": "select",
        "proxies": seen,
    }


def render_mihomo(
    *,
    project_root: Path,
    output_root: Path,
    public_base_url: str,
    nodes: list[ProxyNode],
    manifest: dict[str, list[BuiltRule]],
) -> None:
    env = Environment(loader=FileSystemLoader(str(project_root / "templates")), autoescape=False)
    template = env.get_template("mihomo.yaml.j2")

    mihomo_rules = manifest["mihomo"]
    lookup = _rule_lookup(mihomo_rules)
    node_names = [node.name for node in nodes]
    providers: dict[str, dict[str, object]] = {}
    for item in mihomo_rules:
        path = Path(item.path)
        provider: dict[str, object] = {
            "type": "http",
            "behavior": item.behavior,
            "interval": 21600,
            "path": f"./providers/{path.name}",
            "url": _provider_url(public_base_url, item.path),
        }
        if item.format == "text":
            provider["format"] = "text"
        providers[item.rule_id] = provider

    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": True,
        "unified-delay": True,
        "profile": {"store-selected": True},
        "dns": {
            "enable": True,
            "ipv6": True,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query",
            ],
            "proxy-server-nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query",
            ],
            "nameserver-policy": {
                "geosite:cn,private,apple-cn,microsoft@cn": [
                    "https://dns.alidns.com/dns-query",
                    "https://doh.pub/dns-query",
                ],
                "geosite:geolocation-!cn": [
                    "https://1.1.1.1/dns-query",
                    "https://dns.google/dns-query",
                ],
            },
            "fake-ip-filter": [
                "*.local",
                "localhost",
                "*.lan",
                "captive.apple.com",
                "time.apple.com",
                "mesu.apple.com",
                "swscan.apple.com",
            ],
        },
        "proxies": [node.to_mihomo_proxy() for node in nodes],
        "proxy-groups": [
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "proxies": node_names,
            },
            _build_proxy_group("PROXY", ["AUTO", "DIRECT"], node_names),
            _build_proxy_group("AI", ["PROXY", "AUTO", "DIRECT"], node_names),
            _build_proxy_group("GitHub", ["PROXY", "AUTO", "DIRECT"], node_names),
            _build_proxy_group("Apple", ["DIRECT", "PROXY", "AUTO"], node_names),
            _build_proxy_group("Microsoft", ["DIRECT", "PROXY", "AUTO"], node_names),
            _build_proxy_group("Telegram", ["PROXY", "AUTO", "DIRECT"], node_names),
            _build_proxy_group("Streaming", ["PROXY", "AUTO", "DIRECT"], node_names),
            _build_proxy_group("Download", ["DIRECT", "PROXY", "AUTO"], node_names),
            _build_proxy_group("Final", ["PROXY", "DIRECT", "AUTO"], node_names),
        ],
        "rule-providers": providers,
        "rules": [
            "RULE-SET,private,DIRECT",
            "RULE-SET,lan_non_ip,DIRECT",
            "RULE-SET,lan_ip,DIRECT",
            "RULE-SET,ads,REJECT",
            "RULE-SET,apple_cdn,DIRECT",
            "RULE-SET,apple_cn,DIRECT",
            "RULE-SET,microsoft_cdn,DIRECT",
            "RULE-SET,download_domainset,Download",
            "RULE-SET,download_non_ip,Download",
            "RULE-SET,domestic_non_ip,DIRECT",
            "RULE-SET,domestic_ip,DIRECT",
            "RULE-SET,cn,DIRECT",
            "RULE-SET,cn_ip,DIRECT",
            "RULE-SET,ai,AI",
            "RULE-SET,apple_services,Apple",
            "RULE-SET,microsoft,Microsoft",
            "RULE-SET,github,GitHub",
            "RULE-SET,google,PROXY",
            "RULE-SET,telegram_non_ip,Telegram",
            "RULE-SET,telegram_ip,Telegram",
            "RULE-SET,stream_non_ip,Streaming",
            "RULE-SET,stream_ip,Streaming",
            "RULE-SET,geolocation_non_cn,PROXY",
            "MATCH,Final",
        ],
    }
    body_yaml = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=120)
    rendered = template.render(body_yaml=body_yaml)
    (output_root / "mihomo-full.yaml").write_text(rendered, encoding="utf-8")


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
        "groups": [
            {"name": "PROXY", "type": "select", "members": ["AUTO", "DIRECT", *proxy_names]},
            {
                "name": "AUTO",
                "type": "url-test",
                "members": proxy_names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            },
            {"name": "AI", "type": "select", "members": ["PROXY", "AUTO", "DIRECT", *proxy_names]},
            {"name": "GitHub", "type": "select", "members": ["PROXY", "AUTO", "DIRECT", *proxy_names]},
            {"name": "Apple", "type": "select", "members": ["DIRECT", "PROXY", "AUTO", *proxy_names]},
            {"name": "Microsoft", "type": "select", "members": ["DIRECT", "PROXY", "AUTO", *proxy_names]},
            {"name": "Telegram", "type": "select", "members": ["PROXY", "AUTO", "DIRECT", *proxy_names]},
            {"name": "Streaming", "type": "select", "members": ["PROXY", "AUTO", "DIRECT", *proxy_names]},
            {"name": "Download", "type": "select", "members": ["DIRECT", "PROXY", "AUTO", *proxy_names]},
            {"name": "Final", "type": "select", "members": ["PROXY", "DIRECT", "AUTO", *proxy_names]},
        ],
        "rules": [
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['private'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['lan_non_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['lan_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['ads'].path)},REJECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_cdn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_cn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['microsoft_cdn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['download_domainset'].path)},Download",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['download_non_ip'].path)},Download",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['domestic_non_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['domestic_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['cn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['cn_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['ai'].path)},AI",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_services'].path)},Apple",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['microsoft'].path)},Microsoft",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['github'].path)},GitHub",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['google'].path)},PROXY",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['telegram_non_ip'].path)},Telegram",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['telegram_ip'].path)},Telegram",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['stream_non_ip'].path)},Streaming",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['stream_ip'].path)},Streaming",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['geolocation_non_cn'].path)},PROXY",
            "FINAL,Final",
        ],
    }
    rendered = template.render(**context)
    (output_root / "shadowrocket.conf").write_text(rendered + "\n", encoding="utf-8")
