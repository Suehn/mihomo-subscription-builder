from __future__ import annotations


GROUP_LABELS = {
    "PROXY": "🚀 代理",
    "Fallback": "🔁 故障转移",
    "RuleUpdate": "🔄 规则更新",
    "AI": "🤖 AI",
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

BUILTIN_POLICIES = {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
CONFIG_RULE_POLICIES = {*(BUILTIN_POLICIES - {"PASS"}), *GROUP_LABELS}
LOGIC_RULE_TYPES = {"AND", "OR", "NOT"}
SHADOWROCKET_UNSUPPORTED_RULE_TYPES = {*LOGIC_RULE_TYPES, "SUB-RULE"}

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
SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_MEMBER = [
    "GitHub",
    "AI",
    "Google",
    "Developer",
    "Microsoft",
    "Telegram",
    "Streaming",
    "Download",
]
SHADOWROCKET_GROUPS_FOLLOW_PROXY = [
    "GitHub",
    "AI",
    "Google",
    "Developer",
    "Apple",
    "Microsoft",
    "Telegram",
    "Streaming",
    "Download",
    "Final",
]
SHADOWROCKET_SELECT_GROUPS_INCLUDE_ALL_NODES = [
    "PROXY",
    "GitHub",
    "AI",
    "Google",
    "Developer",
    "Apple",
    "Microsoft",
    "Telegram",
    "Streaming",
    "Download",
    "Final",
]
SHADOWROCKET_REQUIRED_RULE_FRAGMENTS = [
    "DOMAIN-SUFFIX,github.com",
    "DOMAIN-SUFFIX,objects.githubusercontent.com",
    "DOMAIN-SUFFIX,chatgpt.com",
    "DOMAIN-SUFFIX,claude.ai",
    "/bundles/03-ai.conf",
    "/developer_global.conf",
    "/bundles/05-direct.conf",
    "/bundles/07-proxy.conf",
    "FINAL,",
]
SHADOWROCKET_RULE_ORDER = [
    ("DOMAIN-SUFFIX,github.com", "/bundles/06-download.conf"),
    ("/github.", "/bundles/06-download.conf"),
    ("/bundles/03-ai.conf", "/bundles/06-download.conf"),
    ("/microsoft.conf", "/bundles/06-download.conf"),
    ("/microsoft_cdn.conf", "/bundles/06-download.conf"),
    ("/bundles/04-direct.conf", "/bundles/06-download.conf"),
    ("/bundles/05-direct.conf", "/bundles/06-download.conf"),
    ("/developer_global.conf", "/bundles/06-download.conf"),
    ("/bundles/06-download.conf", "/bundles/08-direct.conf"),
    ("/bundles/07-proxy.conf", "/bundles/08-direct.conf"),
]

SHADOWROCKET_GEOSITE_RULE_IDS = {
    "private": "private",
    "github": "github",
    "google": "google",
    "cn": "cn",
    "geolocation-!cn": "geolocation_non_cn",
}
SHADOWROCKET_GEOIP_RULE_IDS = {
    "private": "lan_ip",
    "CN": "cn_ip",
}

MIHOMO_GEOSITE_PROVIDER_FILES = {
    "private": "private.yaml",
    "github": "github.yaml",
    "google": "google.yaml",
    "cn": "cn.yaml",
    "geolocation-!cn": "geolocation-!cn.yaml",
}

GEOSITE_FALLBACK_SUFFIXES = {
    "youtube": ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com"],
    "netflix": ["netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net"],
    "disney": ["disneyplus.com", "disney-plus.net", "dssott.com"],
    "spotify": ["spotify.com", "scdn.co", "spotifycdn.com"],
    "tiktok": ["tiktok.com", "tiktokv.com", "byteoversea.com"],
    "google": ["google.com", "googleapis.com", "gstatic.com", "googleusercontent.com", "google.dev"],
    "microsoft": ["microsoft.com", "windows.com", "office.com", "live.com", "azure.com"],
    "microsoft@cn": ["download.visualstudio.microsoft.com"],
    "apple": ["apple.com", "icloud.com", "mzstatic.com"],
    "apple-cn": ["icloud.com.cn"],
    "cn": ["cn"],
    "geolocation-!cn": [],
    "private": ["local", "lan"],
}


def group_label(key: str) -> str:
    return GROUP_LABELS[key]


def resolve_policy(value: str) -> str:
    if value.startswith("@"):
        return group_label(value[1:])
    return value
