from __future__ import annotations

from pathlib import Path

import yaml

from subscription_builder.models import ProxyNode
from subscription_builder.render import prepare_public_pages, render_mihomo, render_shadowrocket
from subscription_builder.route_expectations import route_mihomo_domain, route_shadowrocket_domain, validate_route_expectations
from subscription_builder.rules import BuiltRule
from subscription_builder.validate import validate_mihomo_config, validate_rule_audit, validate_shadowrocket_config


RULE_IDS = [
    "private",
    "lan_non_ip",
    "lan_ip",
    "ads",
    "tencent_direct_ip",
    "alibaba_direct_ip",
    "baidu_direct_domain",
    "weibo_direct_domain",
    "xiaohongshu_direct_domain",
    "xiaomi_direct_domain",
    "xiaomi_direct_ip",
    "huawei_direct_domain",
    "wechat_direct_domain",
    "wechat_direct_ip",
    "bilibili_direct_domain",
    "bilibili_direct_ip",
    "neteasemusic_direct_domain",
    "neteasemusic_direct_ip",
    "china_media_direct_domain",
    "china_media_direct_ip",
    "apple_cdn",
    "apple_cn",
    "microsoft_cdn",
    "ai",
    "apple_intelligence",
    "apple_services",
    "microsoft",
    "github",
    "google",
    "developer_global",
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
        path=f"rules/mihomo/{_rule_path_name(rule_id)}.txt",
        source_url=f"https://example.test/{rule_id}.txt",
        behavior="classical",
        format="text",
    )


def _rule_path_name(rule_id: str) -> str:
    return {
        "ads": "category-ads-all",
        "direct_non_ip": "direct",
        "global_non_ip": "global",
        "lan_non_ip": "lan",
        "domestic_non_ip": "domestic",
    }.get(rule_id, rule_id)


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


def _render_shadowrocket(tmp_path: Path, *, output_name: str = "shadowrocket.conf", traffic_saver: bool = True) -> str:
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
            "developer_global": "developer_global.conf",
            "ads": "category-ads-all.list",
            "wechat_direct_domain": "wechat.list",
            "bilibili_direct_domain": "bilibili.list",
            "neteasemusic_direct_domain": "neteasemusic.list",
            "china_media_direct_domain": "china_media.list",
            "baidu_direct_domain": "baidu.list",
            "weibo_direct_domain": "weibo.list",
            "xiaohongshu_direct_domain": "xiaohongshu.list",
            "xiaomi_direct_domain": "xiaomi.list",
            "huawei_direct_domain": "huawei.list",
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
        if rule.rule_id not in shadowrocket_paths:
            continue
        rule.path = f"rules/shadowrocket/{shadowrocket_paths[rule.rule_id]}"

    shadowrocket_rule_ids = set(shadowrocket_paths)
    render_shadowrocket(
        project_root=Path.cwd(),
        output_root=tmp_path,
        public_base_url="https://example.test/sub",
        private_base_url="https://private.example.test/sub",
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
        manifest={"mihomo": [], "shadowrocket": [rule for rule in rules if rule.rule_id in shadowrocket_rule_ids]},
        output_name=output_name,
        traffic_saver=traffic_saver,
    )
    return (tmp_path / output_name).read_text(encoding="utf-8")


def test_mihomo_disables_ipv6_by_default(tmp_path: Path) -> None:
    config = _render_config(tmp_path)

    assert config["ipv6"] is False
    assert config["dns"]["ipv6"] is False


def test_mihomo_uses_domestic_doh_and_filters_local_wpad(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    dns = config["dns"]

    assert "https://1.1.1.1/dns-query" not in str(dns)
    assert "https://8.8.8.8/dns-query" not in str(dns)
    assert "wpad" in dns["fake-ip-filter"]
    assert config["rules"][0] == "DOMAIN,wpad,REJECT"


def test_mihomo_download_and_fallback_groups_prefer_proxy(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    groups = {group["name"]: group["proxies"] for group in config["proxy-groups"]}

    assert config["proxy-groups"][0]["name"] == "🚀 代理"
    assert groups["🪟 Microsoft"][:3] == ["🚀 代理", "🔁 故障转移", "DIRECT"]
    assert groups["🔎 Google"][:3] == ["🚀 代理", "🔁 故障转移", "⚡ 自动选择"]
    assert groups["💻 GitHub"][:4] == ["🚀 代理", "🔁 故障转移", "⚡ 自动选择", "🧭 手动选择"]
    assert groups["🛠 Developer"][:4] == ["🚀 代理", "🔁 故障转移", "⚡ 自动选择", "🧭 手动选择"]
    assert groups["⬇️ 下载"][:3] == ["🔁 故障转移", "🚀 代理", "⚡ 自动选择"]
    assert groups["🌐 兜底"][:3] == ["🚀 代理", "🔁 故障转移", "⚡ 自动选择"]
    for group_name in ["💻 GitHub", "🛠 Developer", "📺 流媒体", "⬇️ 下载"]:
        assert "DIRECT" not in groups[group_name]


def test_mihomo_rules_route_specific_foreign_services_before_download_and_cn_ip(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    rules = config["rules"]

    cn_idx = rules.index("GEOSITE,cn,DIRECT")
    github_idx = rules.index("GEOSITE,github,💻 GitHub")
    github_release_idx = rules.index("DOMAIN-SUFFIX,release-assets.githubusercontent.com,💻 GitHub")
    github_releases_idx = rules.index("DOMAIN-SUFFIX,github-releases.githubusercontent.com,💻 GitHub")
    microsoft_idx = rules.index("RULE-SET,microsoft,🪟 Microsoft")
    google_idx = rules.index("GEOSITE,google,🔎 Google")
    developer_idx = rules.index("RULE-SET,developer_global,🛠 Developer")
    download_cn_idx = rules.index("AND,((RULE-SET,download_domainset),(GEOIP,CN)),DIRECT")
    download_idx = rules.index("RULE-SET,download_domainset,⬇️ 下载")
    cn_ip_idx = rules.index("GEOIP,CN,DIRECT")

    assert cn_idx < download_idx
    assert github_idx < download_idx
    assert github_release_idx < download_idx
    assert github_releases_idx < download_idx
    assert microsoft_idx < download_idx
    assert google_idx < download_idx
    assert developer_idx < download_idx
    assert rules.index("DOMAIN-SUFFIX,npmmirror.com,DIRECT") < developer_idx
    assert rules.index("DOMAIN-SUFFIX,goproxy.cn,DIRECT") < developer_idx
    assert rules.index("DOMAIN-SUFFIX,go.dev,🛠 Developer") < google_idx
    assert rules.index("DOMAIN,marketplace.visualstudio.com,🛠 Developer") < microsoft_idx
    assert rules.index("DOMAIN-SUFFIX,huggingface.co,🛠 Developer") < download_idx
    assert developer_idx < download_cn_idx
    assert download_cn_idx < download_idx
    assert download_idx < cn_ip_idx
    assert "GEOIP,CN,DIRECT,no-resolve" not in rules


def test_mihomo_splits_domestic_direct_domain_and_ip_rules(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    rules = config["rules"]
    providers = config["rule-providers"]
    github_idx = rules.index("DOMAIN-SUFFIX,github.com,💻 GitHub")
    cn_ip_idx = rules.index("GEOIP,CN,DIRECT")

    assert "bilibili_direct_domain" in providers
    assert "bilibili_direct_ip" in providers
    assert "tencent_direct_ip" in providers
    assert "tencent_direct_domain" not in providers
    assert rules.index("RULE-SET,bilibili_direct_domain,DIRECT") < github_idx
    assert rules.index("RULE-SET,bilibili_direct_ip,DIRECT,no-resolve") < cn_ip_idx
    assert rules.index("RULE-SET,bilibili_direct_domain,DIRECT") < rules.index(
        "RULE-SET,bilibili_direct_ip,DIRECT,no-resolve"
    )


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
    assert "developer_global" in providers
    assert "bilibili_direct_domain" in providers
    assert "bilibili_direct_ip" in providers


def test_mihomo_adds_device_overlay_rules_and_rule_update_proxy(tmp_path: Path) -> None:
    config = _render_config(tmp_path)
    rules = config["rules"]

    assert config["rules"][:5] == [
        "DOMAIN,wpad,REJECT",
        "PROCESS-NAME,NetEaseMusic,DIRECT",
        "PROCESS-NAME,UURemote,DIRECT",
        "PROCESS-NAME,UURemoteServer,DIRECT",
        "GEOSITE,private,DIRECT",
    ]
    assert rules.index("DOMAIN-SUFFIX,github.com,💻 GitHub") < rules.index("PROCESS-NAME,WeChat,DIRECT")
    assert rules.index("DOMAIN-SUFFIX,chatgpt.com,🤖 AI") < rules.index("PROCESS-NAME,WeChat,DIRECT")
    assert rules.index("GEOSITE,google,🔎 Google") < rules.index("PROCESS-NAME,WeChat,DIRECT")
    assert rules.index("RULE-SET,telegram_non_ip,✈️ Telegram") < rules.index("PROCESS-NAME,WeChat,DIRECT")
    assert config["rule-providers"]["download_domainset"]["proxy"] == "🔄 规则更新"
    assert config["rule-providers"]["apple_intelligence"]["proxy"] == "🔄 规则更新"
    assert config["rule-providers"]["developer_global"]["proxy"] == "🔄 规则更新"
    assert "RULE-SET,apple_intelligence,🤖 AI" in config["rules"]
    assert "RULE-SET,direct_non_ip,DIRECT" in config["rules"]
    assert "RULE-SET,global_non_ip,🚀 代理" in config["rules"]
    assert "RULE-SET,developer_global,🛠 Developer" in config["rules"]


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
    google_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/google.list,🔎 Google")
    developer_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/developer_global.conf,🛠 Developer")
    download_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/download_domainset.conf,⬇️ 下载")
    cn_ip_idx = lines.index("RULE-SET,https://example.test/sub/rules/shadowrocket/cn_ip.list,DIRECT")

    assert github_pin_idx < download_idx
    assert ai_pin_idx < download_idx
    assert cn_idx < download_idx
    assert github_idx < download_idx
    assert ai_idx < download_idx
    assert microsoft_idx < download_idx
    assert google_idx < download_idx
    assert developer_idx < download_idx
    assert download_idx < cn_ip_idx
    assert not any(line.startswith("AND,") for line in lines)


def test_shadowrocket_disables_ipv6_and_uses_safe_group_defaults(tmp_path: Path) -> None:
    text = _render_shadowrocket(tmp_path)
    lines = text.splitlines()
    group_lines = []
    in_group_section = False
    for line in lines:
        if line == "[Proxy Group]":
            in_group_section = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_group_section = False
        elif in_group_section and line:
            group_lines.append(line)

    assert "ipv6 = false" in lines
    assert "dns-server = https://doh.pub/dns-query,https://dns.alidns.com/dns-query" in lines
    assert "https://private.example.test/sub/shadowrocket-subscription.txt" in lines[2]
    assert "https://example.test/sub/shadowrocket-subscription.txt" not in text
    assert "1.1.1.1" not in text
    assert "8.8.8.8" not in text
    assert group_lines[0] == "🚀 代理 = select,🔁 故障转移,⚡ 自动选择,🧭 手动选择,DIRECT,node-a"
    assert next(line for line in lines if line.startswith("🚀 代理 = ")) == "🚀 代理 = select,🔁 故障转移,⚡ 自动选择,🧭 手动选择,DIRECT,node-a"
    assert "🔁 故障转移 = fallback,node-a,url=https://www.gstatic.com/generate_204,interval=300" in lines
    assert "🤖 AI = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "🔎 Google = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "💻 GitHub = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "🛠 Developer = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "📺 流媒体 = select,🚀 代理,🔁 故障转移,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "⬇️ 下载 = select,🔁 故障转移,🚀 代理,⚡ 自动选择,🧭 手动选择,node-a" in lines
    assert "🌐 兜底 = select,DIRECT,🚀 代理,🔁 故障转移,⚡ 自动选择,node-a" in lines

    strict_text = _render_shadowrocket(tmp_path, output_name="shadowrocket-strict.conf", traffic_saver=False)
    strict_lines = strict_text.splitlines()
    assert "⬇️ 下载 = select,🔁 故障转移,🚀 代理,⚡ 自动选择,🧭 手动选择,node-a" in strict_lines
    assert "🌐 兜底 = select,🚀 代理,🔁 故障转移,⚡ 自动选择,DIRECT,node-a" in strict_lines


def test_shadowrocket_includes_new_sukkaw_layers_and_passes_policy_validation(tmp_path: Path) -> None:
    text = _render_shadowrocket(tmp_path)

    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/apple_intelligence.conf,🤖 AI" in text
    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/developer_global.conf,🛠 Developer" in text
    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/direct.conf,DIRECT" in text
    assert "RULE-SET,https://example.test/sub/rules/shadowrocket/global.conf,🚀 代理" in text

    validate_shadowrocket_config(Path(tmp_path) / "shadowrocket.conf", traffic_saver=True)
    _render_shadowrocket(tmp_path, output_name="shadowrocket-strict.conf", traffic_saver=False)
    validate_shadowrocket_config(Path(tmp_path) / "shadowrocket-strict.conf", traffic_saver=False)


def test_generated_configs_route_representative_domains_as_expected(tmp_path: Path) -> None:
    _render_config(tmp_path)
    _render_shadowrocket(tmp_path)
    _render_shadowrocket(tmp_path, output_name="shadowrocket-strict.conf", traffic_saver=False)
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
                "developer_global": "conf",
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
        "release-assets.githubusercontent.com\nregistry.npmjs.org\ndownload.jetbrains.com\nrepo.anaconda.com\n",
        encoding="utf-8",
    )
    (rules_root / "shadowrocket" / "download_domainset.conf").write_text(
        "release-assets.githubusercontent.com\nregistry.npmjs.org\ndownload.jetbrains.com\nrepo.anaconda.com\n",
        encoding="utf-8",
    )
    (rules_root / "mihomo" / "github.list").write_text("+.github.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "github.list").write_text("DOMAIN-SUFFIX,github.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "ai.txt").write_text("DOMAIN-SUFFIX,chatgpt.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "ai.conf").write_text("DOMAIN-SUFFIX,chatgpt.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "domestic.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "domestic_non_ip.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "bilibili_direct_domain.txt").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "mihomo" / "microsoft.txt").write_text(
        "DOMAIN-SUFFIX,office.com\nDOMAIN-SUFFIX,live.com\nDOMAIN-SUFFIX,sharepoint.com\n", encoding="utf-8"
    )
    (rules_root / "mihomo" / "apple_services.txt").write_text(
        "DOMAIN-SUFFIX,icloud.com\nDOMAIN-SUFFIX,apple.com\n", encoding="utf-8"
    )
    (rules_root / "mihomo" / "telegram_non_ip.txt").write_text("DOMAIN-SUFFIX,telegram.org\n", encoding="utf-8")
    (rules_root / "mihomo" / "stream_non_ip.txt").write_text(
        "DOMAIN-SUFFIX,youtube.com\nDOMAIN-SUFFIX,spotify.com\nDOMAIN-SUFFIX,tiktok.com\n", encoding="utf-8"
    )
    (rules_root / "mihomo" / "developer_global.txt").write_text(
        "DOMAIN-SUFFIX,pypi.org\nDOMAIN-SUFFIX,repo.anaconda.com\nDOMAIN-SUFFIX,download.pytorch.org\n"
        "DOMAIN-SUFFIX,developer.hashicorp.com\n",
        encoding="utf-8",
    )
    (rules_root / "shadowrocket" / "domestic.conf").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "bilibili.list").write_text("DOMAIN-SUFFIX,bilibili.com\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "microsoft.conf").write_text(
        "DOMAIN-SUFFIX,office.com\nDOMAIN-SUFFIX,live.com\nDOMAIN-SUFFIX,sharepoint.com\n", encoding="utf-8"
    )
    (rules_root / "shadowrocket" / "apple_services.conf").write_text(
        "DOMAIN-SUFFIX,icloud.com\nDOMAIN-SUFFIX,apple.com\n", encoding="utf-8"
    )
    (rules_root / "shadowrocket" / "telegram.conf").write_text("DOMAIN-SUFFIX,telegram.org\n", encoding="utf-8")
    (rules_root / "shadowrocket" / "stream.conf").write_text(
        "DOMAIN-SUFFIX,youtube.com\nDOMAIN-SUFFIX,spotify.com\nDOMAIN-SUFFIX,tiktok.com\n", encoding="utf-8"
    )
    (rules_root / "shadowrocket" / "developer_global.conf").write_text(
        "DOMAIN-SUFFIX,pypi.org\nDOMAIN-SUFFIX,repo.anaconda.com\nDOMAIN-SUFFIX,download.pytorch.org\n"
        "DOMAIN-SUFFIX,developer.hashicorp.com\n",
        encoding="utf-8",
    )

    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "mirrors.aliyun.com").policy == "DIRECT"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "mirrors.aliyun.com").policy == "DIRECT"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "release-assets.githubusercontent.com").policy == "💻 GitHub"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "release-assets.githubusercontent.com").policy == "💻 GitHub"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "github-releases.githubusercontent.com").policy == "💻 GitHub"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "youtube.com").policy == "📺 流媒体"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "pypi.org").policy == "🛠 Developer"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "repo.anaconda.com").policy == "🛠 Developer"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "download.pytorch.org").policy == "🛠 Developer"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket-strict.conf", "developer.hashicorp.com").policy == "🛠 Developer"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "office.com").policy == "🪟 Microsoft"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "icloud.com").policy == "🍎 Apple"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "spotify.com").policy == "📺 流媒体"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "telegram.org").policy == "✈️ Telegram"
    assert route_mihomo_domain(tmp_path / "mihomo-full.yaml", "bilibili.com").policy == "DIRECT"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "bilibili.com").policy == "DIRECT"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket.conf", "pypi.org").policy == "🛠 Developer"
    assert route_shadowrocket_domain(tmp_path / "shadowrocket-strict.conf", "pypi.org").policy == "🛠 Developer"

    expectations = tmp_path / "expectations.yaml"
    expectations.write_text(
        """
domains:
  mirrors.aliyun.com: DIRECT
  release-assets.githubusercontent.com: "💻 GitHub"
  github-releases.githubusercontent.com: "💻 GitHub"
  chatgpt.com: "🤖 AI"
  youtube.com: "📺 流媒体"
  spotify.com: "📺 流媒体"
  pypi.org: "🛠 Developer"
  repo.anaconda.com: "🛠 Developer"
  download.pytorch.org: "🛠 Developer"
  developer.hashicorp.com: "🛠 Developer"
  office.com: "🪟 Microsoft"
  icloud.com: "🍎 Apple"
  telegram.org: "✈️ Telegram"
  bilibili.com: DIRECT
""".strip()
        + "\n",
        encoding="utf-8",
    )
    validate_route_expectations(
        mihomo_paths=[tmp_path / "mihomo-full.yaml"],
        shadowrocket_path=tmp_path / "shadowrocket.conf",
        shadowrocket_strict_path=tmp_path / "shadowrocket-strict.conf",
        expectations_path=expectations,
    )


def test_rule_audit_baseline_validation(tmp_path: Path) -> None:
    audit_path = tmp_path / "rule-audit.json"
    baseline_path = tmp_path / "rule-audit-baseline.yaml"
    audit_path.write_text(
        """
rules:
  - client: mihomo
    rule_id: developer_global
    line_count: 80
    domain_count: 80
    ip_count: 0
    process_count: 0
    sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
""".lstrip(),
        encoding="utf-8",
    )
    baseline_path.write_text(
        """
rules:
  mihomo/developer_global:
    min_lines: 50
    max_lines: 300
    require_domains: true
    forbid_ips: true
""".lstrip(),
        encoding="utf-8",
    )

    validate_rule_audit(audit_path, baseline_path)


def test_prepare_public_pages_excludes_private_subscription_artifacts(tmp_path: Path) -> None:
    source_root = tmp_path / "dist"
    public_root = tmp_path / "public-dist"
    (source_root / "rules" / "mihomo").mkdir(parents=True)
    (source_root / "rules" / "shadowrocket").mkdir(parents=True)
    (source_root / "rules" / "mihomo" / "developer_global.txt").write_text("DOMAIN-SUFFIX,pypi.org\n", encoding="utf-8")
    (source_root / "rules" / "shadowrocket" / "developer_global.conf").write_text(
        "DOMAIN-SUFFIX,pypi.org\n",
        encoding="utf-8",
    )
    for private_name in [
        "mihomo-full.yaml",
        "mihomo-android.yaml",
        "shadowrocket.conf",
        "shadowrocket-strict.conf",
        "shadowrocket-subscription.txt",
        "shadowrocket-uris.txt",
    ]:
        (source_root / private_name).write_text("node-secret\n", encoding="utf-8")

    prepare_public_pages(
        source_root=source_root,
        output_root=public_root,
        public_base_url="https://example.test/sub",
    )

    assert (public_root / "rules" / "mihomo" / "developer_global.txt").exists()
    assert (public_root / "rules" / "shadowrocket" / "developer_global.conf").exists()
    assert (public_root / ".nojekyll").exists()
    assert (public_root / ".generated-public-pages").exists()
    assert "node-secret" not in (public_root / "index.html").read_text(encoding="utf-8")
    for private_name in [
        "mihomo-full.yaml",
        "mihomo-android.yaml",
        "shadowrocket.conf",
        "shadowrocket-strict.conf",
        "shadowrocket-subscription.txt",
        "shadowrocket-uris.txt",
    ]:
        assert not (public_root / private_name).exists()
