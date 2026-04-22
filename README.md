# mihomo-subscription-builder

Build a self-hosted remote subscription from a raw upstream node feed. The
project targets two outputs:

- `mihomo-full.yaml` for Mihomo-compatible clients
- `shadowrocket.conf` plus `shadowrocket-subscription.txt` for Shadowrocket

The upstream node source is expected to be a raw subscription endpoint like the
current `vms.217777.xyz` feed behind the local lightweight `美西` profile.

## Repository Identity

- GitHub owner: `Suehn`
- Repository name: `mihomo-subscription-builder`
- GitHub Pages base URL: `https://suehn.github.io/mihomo-subscription-builder`

## What It Does

- Pulls the upstream subscription from `UPSTREAM_SUB_URL`
- Decodes Base64 subscriptions automatically
- Parses `vless://`, `vmess://`, `trojan://`, and `ss://` links
- Mirrors remote rule files into your own GitHub Pages artifact
- Renders a Mihomo configuration with self-hosted `rule-providers`
- Renders a Shadowrocket configuration and also emits URI subscription fallbacks
- Uses emoji policy groups for easier client-side reading

## Rule Strategy

This project intentionally borrows and composes multiple GitHub-maintained rule sources instead of hand-maintaining a giant local ruleset:

- `MetaCubeX/meta-rules-dat` for the Mihomo geosite/geoip backbone
- `SukkaW/Surge` for Apple, Microsoft, download, LAN, domestic, Telegram, AI, and streaming rule sets
- `blackmatrix7/ios_rule_script` for selective high-value domestic service supplements such as WeChat, BiliBili, NetEaseMusic, and China media
- `blackmatrix7/ios_rule_script` for selective high-value domestic service supplements such as Tencent, Alibaba, Baidu, Weibo, XiaoHongShu, XiaoMi, Huawei, WeChat, BiliBili, NetEaseMusic, and China media

For Mihomo clients, the generated config also enables `geodata` auto-update against MetaCubeX GEO artifacts. This is treated as a lower-level GEO data base for DNS and future GEO rules, not as a replacement for the self-hosted rule-provider layer.

The update model is therefore simple: this repo republishes upstream rules on every workflow run, while keeping your own stable subscription URLs.

## Local Usage

```bash
cd /Users/ziyi/Documents/code/mihomo-subscription-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export UPSTREAM_SUB_URL="https://vms.217777.xyz:6942/sub/your-token"
export PUBLIC_BASE_URL="https://suehn.github.io/mihomo-subscription-builder"

python -m subscription_builder.cli build-all
python -m subscription_builder.cli validate
python -m pytest
```

Generated files land in `dist/`:

- `dist/mihomo-full.yaml`
- `dist/shadowrocket.conf`
- `dist/shadowrocket-subscription.txt`
- `dist/shadowrocket-uris.txt`
- `dist/index.html`
- `dist/rules/`

## GitHub Actions Setup

Create the repository secret:

- `UPSTREAM_SUB_URL`

The workflow publishes `dist/` to GitHub Pages. The intended remote is:

- `https://github.com/Suehn/mihomo-subscription-builder`

## Notes About Shadowrocket

Shadowrocket imports VLESS/Reality subscriptions reliably from a remote
subscription URL, but local `[Proxy]` serialization varies between app builds.
This project therefore publishes both:

- `shadowrocket.conf` for routing policy and groups
- `shadowrocket-subscription.txt` as the canonical node subscription fallback

If a future Shadowrocket build rejects the generated local VLESS line inside
`shadowrocket.conf`, import `shadowrocket-subscription.txt` first, then keep
using `shadowrocket.conf` for rules and groups.
