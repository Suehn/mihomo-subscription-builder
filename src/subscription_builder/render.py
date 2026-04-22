from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader
import yaml

from .models import ProxyNode
from .rules import BuiltRule


GROUP_LABELS = {
    "AUTO": "⚡ 自动选择",
    "PROXY": "🚀 代理",
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
        "geodata-mode": True,
        "geodata-loader": "memconservative",
        "geo-auto-update": True,
        "geo-update-interval": 24,
        "geox-url": {
            "geoip": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.dat",
            "geosite": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat",
            "mmdb": "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/country.mmdb",
            "asn": "https://github.com/xishang0128/geoip/releases/download/latest/GeoLite2-ASN.mmdb",
        },
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
                "name": _g("AUTO"),
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "proxies": node_names,
            },
            _build_proxy_group(_g("PROXY"), [_g("AUTO"), "DIRECT"], node_names),
            _build_proxy_group(_g("AI"), [_g("PROXY"), _g("AUTO"), "DIRECT"], node_names),
            _build_proxy_group(_g("GitHub"), [_g("PROXY"), _g("AUTO"), "DIRECT"], node_names),
            _build_proxy_group(_g("Apple"), ["DIRECT", _g("PROXY"), _g("AUTO")], node_names),
            _build_proxy_group(_g("Microsoft"), ["DIRECT", _g("PROXY"), _g("AUTO")], node_names),
            _build_proxy_group(_g("Telegram"), [_g("PROXY"), _g("AUTO"), "DIRECT"], node_names),
            _build_proxy_group(_g("Streaming"), [_g("PROXY"), _g("AUTO"), "DIRECT"], node_names),
            _build_proxy_group(_g("Download"), ["DIRECT", _g("PROXY"), _g("AUTO")], node_names),
            _build_proxy_group(_g("Final"), [_g("PROXY"), "DIRECT", _g("AUTO")], node_names),
        ],
        "rule-providers": providers,
        "rules": [
            "RULE-SET,private,DIRECT",
            "RULE-SET,lan_non_ip,DIRECT",
            "RULE-SET,lan_ip,DIRECT",
            "RULE-SET,ads,REJECT",
            "RULE-SET,tencent_direct,DIRECT",
            "RULE-SET,alibaba_direct,DIRECT",
            "RULE-SET,baidu_direct,DIRECT",
            "RULE-SET,weibo_direct,DIRECT",
            "RULE-SET,xiaohongshu_direct,DIRECT",
            "RULE-SET,xiaomi_direct,DIRECT",
            "RULE-SET,huawei_direct,DIRECT",
            "RULE-SET,wechat_direct,DIRECT",
            "RULE-SET,bilibili_direct,DIRECT",
            "RULE-SET,neteasemusic_direct,DIRECT",
            "RULE-SET,china_media_direct,DIRECT",
            "RULE-SET,apple_cdn,DIRECT",
            "RULE-SET,apple_cn,DIRECT",
            "RULE-SET,microsoft_cdn,DIRECT",
            f"RULE-SET,download_domainset,{_g('Download')}",
            f"RULE-SET,download_non_ip,{_g('Download')}",
            "RULE-SET,domestic_non_ip,DIRECT",
            "RULE-SET,domestic_ip,DIRECT",
            "RULE-SET,cn,DIRECT",
            "RULE-SET,cn_ip,DIRECT",
            f"RULE-SET,ai,{_g('AI')}",
            f"RULE-SET,apple_services,{_g('Apple')}",
            f"RULE-SET,microsoft,{_g('Microsoft')}",
            f"RULE-SET,github,{_g('GitHub')}",
            f"RULE-SET,google,{_g('PROXY')}",
            f"RULE-SET,telegram_non_ip,{_g('Telegram')}",
            f"RULE-SET,telegram_ip,{_g('Telegram')}",
            f"RULE-SET,stream_non_ip,{_g('Streaming')}",
            f"RULE-SET,stream_ip,{_g('Streaming')}",
            f"RULE-SET,geolocation_non_cn,{_g('PROXY')}",
            f"MATCH,{_g('Final')}",
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
            {"name": _g("PROXY"), "type": "select", "members": [_g("AUTO"), "DIRECT", *proxy_names]},
            {
                "name": _g("AUTO"),
                "type": "url-test",
                "members": proxy_names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            },
            {"name": _g("AI"), "type": "select", "members": [_g("PROXY"), _g("AUTO"), "DIRECT", *proxy_names]},
            {"name": _g("GitHub"), "type": "select", "members": [_g("PROXY"), _g("AUTO"), "DIRECT", *proxy_names]},
            {"name": _g("Apple"), "type": "select", "members": ["DIRECT", _g("PROXY"), _g("AUTO"), *proxy_names]},
            {"name": _g("Microsoft"), "type": "select", "members": ["DIRECT", _g("PROXY"), _g("AUTO"), *proxy_names]},
            {"name": _g("Telegram"), "type": "select", "members": [_g("PROXY"), _g("AUTO"), "DIRECT", *proxy_names]},
            {"name": _g("Streaming"), "type": "select", "members": [_g("PROXY"), _g("AUTO"), "DIRECT", *proxy_names]},
            {"name": _g("Download"), "type": "select", "members": ["DIRECT", _g("PROXY"), _g("AUTO"), *proxy_names]},
            {"name": _g("Final"), "type": "select", "members": [_g("PROXY"), "DIRECT", _g("AUTO"), *proxy_names]},
        ],
        "rules": [
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['private'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['lan_non_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['lan_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['ads'].path)},REJECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['tencent_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['alibaba_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['baidu_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['weibo_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['xiaohongshu_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['xiaomi_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['huawei_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['wechat_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['bilibili_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['neteasemusic_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['china_media_direct'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_cdn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_cn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['microsoft_cdn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['download_domainset'].path)},{_g('Download')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['download_non_ip'].path)},{_g('Download')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['domestic_non_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['domestic_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['cn'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['cn_ip'].path)},DIRECT",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['ai'].path)},{_g('AI')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['apple_services'].path)},{_g('Apple')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['microsoft'].path)},{_g('Microsoft')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['github'].path)},{_g('GitHub')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['google'].path)},{_g('PROXY')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['telegram_non_ip'].path)},{_g('Telegram')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['telegram_ip'].path)},{_g('Telegram')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['stream_non_ip'].path)},{_g('Streaming')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['stream_ip'].path)},{_g('Streaming')}",
            f"RULE-SET,{_provider_url(public_base_url, shadow_rules['geolocation_non_cn'].path)},{_g('PROXY')}",
            f"FINAL,{_g('Final')}",
        ],
    }
    rendered = template.render(**context)
    (output_root / "shadowrocket.conf").write_text(rendered + "\n", encoding="utf-8")


def render_index(*, output_root: Path, public_base_url: str) -> None:
    links = [
        ("Mihomo subscription", f"{public_base_url}/mihomo-full.yaml"),
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
