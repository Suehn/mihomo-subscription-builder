from __future__ import annotations

from pathlib import Path

import yaml

from subscription_builder.models import ProxyNode
from subscription_builder.render import render_mihomo, render_shadowrocket
from subscription_builder.route_expectations import route_mihomo_domain, route_shadowrocket_domain, validate_route_expectations
from subscription_builder.rules import BuiltRule
from subscription_builder.validate import validate_mihomo_config, validate_shadowrocket_config


RULE_IDS = [
    "private",
    "lan_non_ip",
    "lan_ip",
    "ads",
    "tencent_direct",
    "alibaba_direct",
    "baidu_direct",
    "weibo_direct",
    "xiaohongshu_direct",
    "xiaomi_direct",
    "huawei_direct",
    "wechat_direct",
    "bilibili_direct",
    "neteasemusic_direct",
    "china_media_direct",
    "apple_cdn",
    "apple_cn",
    "microsoft_cdn",
    "ai",
    "apple_intelligence",
    "apple_services",
    "microsoft",
    "github",
    "google",
    "telegram_non_ip",
    "stream_non_ip",
    "download_domainset",
    "download_non_ip",
    "direct_non_ip",
    "global_non_ip",
    "domestic_non_ip",
    "cn",
    "telegram_ip",
    "stream_ip",
    "geolocation_non_cn",
    "domestic_ip",
    "cn_ip",
]


def _rule(rule_id: str) -> BuiltRule:
    return BuiltRule(
        rule_id=rule_id,
        client="mihomo",
        policy="DIRECT",
        path=f"rules/mihomo/{rule_id}.txt",
        source_url=f"https://example.test/{rule_id}.txt",
        behavior="classical",
        format="text",
    )


def _render_config(tmp_path: Path) -> dict[str, object]:
    render_mihomo(
        project_root=Path.cwd(),
        output_root=tmp_path,
        public_base_url="https://example.test/sub",
        nodes=[
            ProxyNode(
                name="node-a",
                type="vless",
                server="proxy.example.test",
                port=443,
                uuid="00000000-0000-4000-8000-000000000001",
                tls=True,
            )
        ],
        manifest={"mihomo": [_rule(rule_id) for rule_id in RULE_IDS], "shadowrocket": []},
    )
    return yaml.safe_load((tmp_path / "mihomo-full.yaml").read_text(encoding="utf-8"))


def _render_shadowrocket(tmp_path: Path) -> str:
    rules = [_rule(rule_id) for rule_id in RULE_IDS]
    for rule in rules:
        rule.client = "shadowrocket"
        shadowrocket_paths = {
            "private": "private.list",
            "cn": "cn.list",
            "geolocation_non_cn": "geolocation-!cn.list",
            "cn_ip": "cn_ip.list",
            "github": "github.list",
            "google": "google.list",
            "ads": "category-ads-all.list",
            "wechat_direct": "wechat.list",
            "bilibili_direct": "bilibili.list",
            "neteasemusic_direct": "neteasemusic.list",
            "china_media_direct": "china_media.list",
            "tencent_direct": "tencent.list",
            "alibaba_direct": "alibaba.list",
            "baidu_direct": "baidu.list",
            "weibo_direct": "weibo.list",
            "xiaohongshu_direct": "xiaohongshu.list",
            "xiaomi_direct": "xiaomi.list",
            "huawei_direct": "huawei.list",
            "ai": "ai.conf",
            "apple_intelligence": "apple_intelligence.conf",
            "apple_cdn": "apple_cdn.conf",
            "apple_cn": "apple_cn.conf",
            "apple_services": "apple_services.conf",
            "microsoft_cdn": "microsoft_cdn.conf",
            "microsoft": "microsoft.conf",
            "telegram_non_ip": "telegram.conf",
            "telegram_ip": "telegram_ip.conf",
            "stream_non_ip": "stream.conf",
            "stream_ip": "stream_ip.conf",
            "download_domainset": "download_domainset.conf",
            "download_non_ip": "download_non_ip.conf",
            "direct_non_ip": "direct.conf",
            "global_non_ip": "global.conf",
            "lan_non_ip": "lan.conf",
            "lan_ip": "lan_ip.conf",
            "domestic_non_ip": "domestic.conf",
            "domestic_ip": "domestic_ip.conf",
        }
        rule.path = f"rules/shadowrocket/{shadowrocket_paths[rule.rule_id]}"

    render_shadowrocket(
        project_root=Path.cwd(),
        output_root=tmp_path,
        public_base_url="https://example.test/sub",
        nodes=[
            ProxyNode(
                name="node-a",
                type="vless",
                server="proxy.example.test",
                port=443,
                uuid="00000000-0000-4000-8000-000000000001",
                tls=True,
            )
        ],
        manifest={"mihomo": [], "shadowrocket": rules},
    )
    return (tmp_path / "shadowrocket.conf").read_text(encoding="utf-8")


def test_mihomo_disables_ipv6_by_default(tmp_path: Path) -> None:
    config = _render_config(tmp_path)

    assert config["ipv6"] is False
    assert config["dns"]["ipv6"] is False


def test_mihomo_download_and_fallback_groups_prefer_proxy(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    groups = {group["name"]: group["proxies"] for group in config["proxy-groups"]}

    assert groups["🪟 Microsoft"][:3] == ["🚀 代理", "🔁 故障转移", "DIRECT"]
    assert groups["⬇️ 下载"][:3] == ["🔁 故障转移", "🚀 代理", "⚡ 自动选择"]
    assert groups["🌐 兜底"][:3] == ["🚀 代理", "🔁 故障转移", "⚡ 自动选择"]


def test_mihomo_rules_route_specific_foreign_services_before_download_and_cn_ip(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    rules = config["rules"]

    cn_idx = rules.index("GEOSITE,cn,DIRECT")
    github_idx = rules.index("GEOSITE,github,💻 GitHub")
    microsoft_idx = rules.index("RULE-SET,microsoft,🪟 Microsoft")
    google_idx = rules.index("GEOSITE,google,🚀 代理")
    download_idx = rules.index("RULE-SET,download_domainset,⬇️ 下载")
    cn_ip_idx = rules.index("GEOIP,CN,DIRECT,no-resolve")

    assert cn_idx < download_idx
    assert github_idx < download_idx
    assert microsoft_idx < download_idx
    assert google_idx < download_idx
    assert download_idx < cn_ip_idx


def test_mihomo_only_renders_rule_providers_referenced_by_rules(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    providers = config["rule-providers"]

    assert "github" not in providers
    assert "google" not in providers
    assert "cn" not in providers
    assert "cn_ip" not in providers
    assert "geolocation_non_cn" not in providers
    assert "private" not in providers
    assert "download_domainset" in providers
    assert "bilibili_direct" in providers


def test_mihomo_adds_device_overlay_rules_and_rule_update_proxy(tmp_path: Path) -> None:
    config = _render_config(tmp_path)

    assert config["rules"][:4] == [
        "PROCESS-NAME,WeChat,DIRECT",
        "PROCESS-NAME,WeChatAppEx,DIRECT",
        "PROCESS-NAME,QQ,DIRECT",
        "PROCESS-NAME,NetEaseMusic,DIRECT",
    ]
    assert config["rule-providers"]["download_domainset"]["proxy"] == "🔄 规则更新"
    assert config["rule-providers"]["apple_intelligence"]["proxy"] == "🔄 规则更新"
    assert "RULE-SET,apple_intelligence,🤖 AI" in config["rules"]
    assert "RULE-SET,direct_non_ip,DIRECT" in config["rules"]
    assert "RULE-SET,global_non_ip,🚀 代理" in config["rules"]


def test_mihomo_rendered_config_passes_policy_validation(tmp_path: Path) -> None:
    _render_config(tmp_path)

    validate_mihomo_config(Path(tmp_path) / "mihomo-full.yaml", Path.cwd() / "config" / "mihomo" / "validation.yaml")


def test_shadowrocket_routes_specific_foreign_services_before_download_and_cn_ip(tmp_path: Path) -> None:
    lines = _render_shadowrocket(tmp_path).splitlines()

    github_pin_idx = lines.index("DOMAIN-SUFFIX,github.com,💻 GitHub")
    ai_pin_idx = lines.index("DOMAIN-SUFFIX,chatgpt.com,🤖 AI")
    cn_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/cn.list,DIRECT")
    github_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/github.list,💻 GitHub")
    ai_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/ai.conf,🤖 AI")
    microsoft_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/microsoft.conf,🪟 Microsoft")
    google_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/google.list,🚀 代理")
    download_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/download_domainset.conf,⬇️ 下载")
    cn_ip_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/cn_ip.list,DIRECT")

    assert github_pin_idx < download_idx
    assert ai_pin_idx < download_idx
    assert cn_idx < download_idx
    assert github_idx < download_idx
    assert ai_idx < download_idx
    assert microsoft_idx < download_idx
    assert google_idx < download_idx
    assert download_idx < cn_ip_idx


def test_shadowrocket_disables_ipv6_and_uses_safe_group_defaults(tmp_path: Path) -> None:
    text = _render_shadowrocket(tmp_path)
    lines = text.splitlines()

    assert "ipv6 = false" in lines
    assert "🔁 故障转移 = fallback,node-a,url=https://www.gstatic.com/generate_204,interval=300" in lines
    assert "🚀 代理 = select,🔁 故障转移,⚡ 自动选择,🧭 手动选择,DIRECT,node-a" in lines
    assert "🤖 AI = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "⬇️ 下载 = select,🔁 故障转移,🚀 代理,⚡ 自动选择,DIRECT,node-a" in lines
    assert "🌐 兜底 = select,🚀 代理,🔁 故障转移,⚡ 自动选择,DIRECT,node-a" in lines


def test_shadowrocket_includes_new_sukkaw_layers_and_passes_policy_validation(tmp_path: Path) -> None:
    text = _render_shadowrocket(tmp_path)

    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/apple_intelligence.conf,🤖 AI" in text
    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/direct.conf,DIRECT" in text
    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/global.conf,🚀 代理" in text

    validate_shadowrocket_config(Path(tmp_path) / "shadowrocket.conf")


def test_generated_configs_route_representative_domains_as_expected(tmp_path: Path) -> None:
    _render_config(tmp_path)
    _render_shadowrocket(tmp_path)
    rules_root = tmp_path / "rules"
    for client in ("mihomo", "shadowrocket"):
        for rule_id in RULE_IDS:
            suffix = {
                "private": "list",
                "cn": "list",
                "geolocation_non_cn": "list",
                "cn_ip": "list",
                "github": "list",
                "google": "list",
                "ads": "list",
            }.get(rule_id, "conf" if client == "shadowrocket" else "txt")
            path_name = {
                "ads": "category-ads-all",
                "geolocation_non_cn": "geolocation-!cn",
                "direct_non_ip": "direct",
                "global_non_ip": "global",
                "lan_non_ip": "lan",
                "domestic_non_ip": "domestic",
            }.get(rule_id, rule_id)
            provider_path = rules_root / client / f"{path_name}.{suffix}"
            provider_path.parent.mkdir(parents=True, exist_ok=True)
            provider_path.write_text("", encoding="utf-8")

    (rules_root / "mihomo" / "download_domainset.txt").write_text(
        "release-assets.githubusercontent.com\nregistry.npmjs.org\ndownload.jetbrains.com\n", encoding="utf-8"
    )
    (rules_root / "shadowrocket" / "download_domainset.conf").write_text(
        "release-assets.githubusercontent.com\nregistry.npmjs.org\ndownload.jetbrains.com\n", encoding="utf-8"
    )
    (rules_root / "mihomo" / "github.list").write_text("+.github.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "github.list").write_text("DOMAIN-SUFFIX,github.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "ai.txt").write_text("DOMAIN-SUFFIX,chatgpt.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "ai.conf").write_text("DOMAIN-SUFFIX,chatgpt.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "domestic.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "domestic_non_ip.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "bilibili_direct.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "stream_non_ip.txt").write_text("DOMAIN-SUFFIX,youtube.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "domestic.conf").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "bilibili.list").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "stream.conf").write_text("DOMAIN-SUFFIX,youtube.com\n", encoding="utf-8")

    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "mirrors.aliyun.com").policy == "DIRECT"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "mirrors.aliyun.com").policy == "DIRECT"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "release-assets.githubusercontent.com").policy == "💻 GitHub"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "release-assets.githubusercontent.com").policy == "💻 GitHub"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "youtube.com").policy == "📺 流媒体"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "bilibili.com").policy == "DIRECT"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "bilibili.com").policy == "DIRECT"

    expectations = tmp_path / "expectations.yaml"
    expectations.write_text(
        """
domains:
  mirrors.aliyun.com: DIRECT
  release-assets.githubusercontent.com: "💻 GitHub"
  chatgpt.com: "🤖 AI"
  youtube.com: "📺 流媒体"
  bilibili.com: DIRECT
""".strip()
        + "\n",
        encoding="utf-8",
    )
    validate_route_expectations(
        mihomo_paths=[tmp_path / "mihomo-full.yaml"],
        shadowrocket_path=tmp_path / "shadowrocket.conf",
        expectations_path=expectations,
    )
