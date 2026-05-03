# mihomo-subscription-builder

Build a self-hosted remote subscription from a raw upstream node feed. The
project targets two outputs:

- `mihomo-full.yaml` for Mihomo-compatible clients
- `shadowrocket.conf`, `shadowrocket-strict.conf`, and
  `shadowrocket-subscription.txt` for Shadowrocket

The upstream node source is expected to be a raw subscription endpoint provided
through the private `UPSTREAM_SUB_URL` secret.

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

## Design Principles

For the full current architecture, routing policy, multi-client tradeoffs, and
validation guardrails, see [docs/design.md](docs/design.md).

The project is designed around one primary objective:

> Domestic traffic should be direct and unnoticeable first. On that foundation,
> known foreign services should be explicitly captured, and unknown foreign
> traffic should still have a proxy fallback.

The resulting failure mode is intentional. A high-confidence Chinese app,
Chinese media service, Chinese mirror, Chinese domain, or Chinese IP should be
routed DIRECT. GitHub, AI, Google, Telegram, developer infrastructure, Microsoft
global services, and streaming should be routed to named proxy groups before
they can be swallowed by broad domestic or download rules. Final fallback stays
proxy-first on Mihomo, but CN IP fallback is allowed to resolve so unknown
Chinese domains can still land on DIRECT.

This project is intentionally a thin subscription assembler, not a
hand-maintained full rulebase. It follows mature rule sources and only keeps a
small local layer for stable developer domains and device-specific app/process
rules.

## Routing Architecture

The generated route order is built in layers. Each layer exists to prevent a
specific class of misrouting.

### 1. Mature Rule Backbone

`MetaCubeX/meta-rules-dat` supplies the large geosite/geoip backbone. Mihomo uses
native `GEOSITE` / `GEOIP` rules for large categories such as `cn`,
`geolocation-!cn`, `github`, `google`, and `CN` IPs. This keeps large data in
Mihomo's geodata loader instead of normal runtime `rule-providers`.

`SukkaW/Surge` mirror rules supply focused supplemental layers for AI, Apple,
Microsoft, Telegram, streaming, download, LAN, domestic, direct, and global
traffic. These are mirrored into `dist/rules/` and referenced through
self-hosted rule-provider URLs.

The local rule layer is deliberately small. `rules/custom/developer_global.txt`
contains stable developer ecosystem domains such as PyPI, npm, Go, Rust, Docker,
Maven, JetBrains, Homebrew, Linux package repositories, and Hugging Face. Broad
CDN domains are not included there because they would capture too much unrelated
traffic.

### 2. Domestic-First Mihomo Order

The Mihomo profile follows this high-level order:

1. Local noise and private networks: `wpad`, private geosite/geoip, LAN rules.
2. High-confidence domestic services: Tencent, Alibaba, Baidu, Weibo,
   Xiaohongshu, Xiaomi, Huawei, WeChat rule sets, Bilibili, NetEase Music, and
   China media.
3. Foreign hard pins: GitHub, OpenAI/AI, Claude, Gemini, and YouTube domain pins.
4. Domestic developer mirrors: TUNA, USTC, BFSU, NJU, SJTU, Aliyun, Tencent,
   Huawei Cloud, `npmmirror.com`, `goproxy.cn`, Maven/registry mirrors.
5. Foreign service groups: AI, Apple Intelligence, GitHub, Google, Telegram.
6. Apple and Microsoft split rules: China/CDN paths direct, global services in
   named groups.
7. Streaming, domestic non-IP, `GEOSITE,cn,DIRECT`, developer-global, dynamic
   download split, global, `geolocation-!cn`, IP rules, `GEOIP,CN,DIRECT`, final
   fallback.

The key tail rule is:

```yaml
- GEOIP,CN,DIRECT
- MATCH,🌐 兜底
```

`GEOIP,CN,DIRECT` intentionally does not use `no-resolve`. This lets unknown
domains that were not caught by domestic domain rules resolve to a CN IP and go
DIRECT. `MATCH` still points to the `🌐 兜底` group, whose Mihomo default is
proxy-first, so unknown non-CN traffic does not silently fall back to DIRECT.

Download is split before the broad download group:

```yaml
- AND,((RULE-SET,download_domainset),(GEOIP,CN)),DIRECT
- AND,((RULE-SET,download_non_ip),(GEOIP,CN)),DIRECT
- RULE-SET,download_domainset,⬇️ 下载
- RULE-SET,download_non_ip,⬇️ 下载
```

This means domestic download candidates can still go DIRECT after CN IP
resolution, while non-CN download candidates use the proxy-first download group.
Shadowrocket does not render Mihomo logical rules, so iOS keeps simpler
Traffic-Saver semantics and relies on explicit pins plus DIRECT final fallback.

### 3. Proxy Group Defaults

Mihomo and Shadowrocket share the same group names where possible:

- `🚀 代理`: primary proxy selector, first group for easy client operation.
- `💻 GitHub`, `🤖 AI`, `🔎 Google`, `🛠 Developer`, `✈️ Telegram`,
  `📺 流媒体`: explicit foreign service groups. GitHub, Developer, Streaming,
  and Download intentionally do not include `DIRECT`, which avoids persistent
  client-side selected-state accidentally turning them into long-term direct
  groups.
- `🍎 Apple`: defaults DIRECT because normal Apple system services, App Store,
  iCloud, push, and updates are commonly domestic-friendly. Apple Intelligence is
  routed to `🤖 AI` instead.
- `🪟 Microsoft`: defaults proxy-first for global Microsoft services, while
  Microsoft CN/CDN rules are direct before the group.
- `⬇️ 下载`: proxy/fallback first on every generated profile. Domestic download
  candidates are handled by earlier domestic mirrors and Mihomo's
  `AND(download,GEOIP,CN)` split, not by making the whole download group DIRECT.
- `🌐 兜底`: Mihomo defaults proxy-first; iOS defaults DIRECT first.

This split is deliberate. Desktop should protect unknown foreign traffic more
aggressively. iOS should protect domestic traffic and cellular data more
aggressively, while still proxying explicitly known foreign services.

## Multi-Client Behavior

### macOS Mihomo

`dist/mihomo-full.yaml` is the main desktop profile for Clash Verge Rev. It is
the strict always-on profile:

- IPv6 is disabled by default because the target environment has shown unstable
  domestic IPv6 direct routes.
- DNS uses domestic DoH servers and filters local `wpad` noise.
- Domestic services and CN domains/IPs are direct.
- GitHub, AI, Google, Telegram, Developer, Microsoft global, and streaming are
  explicit proxy groups.
- `🌐 兜底` is proxy-first.

The macOS overlay keeps pure domestic processes such as NetEase Music and
UURemote early DIRECT. Mixed container apps such as WeChat and QQ are inserted
after GitHub/AI/Google/Telegram pins, so ordinary chat traffic remains DIRECT
while explicit foreign links are not hidden behind a process-level DIRECT rule.

### Android Mihomo

`dist/mihomo-android.yaml` uses the same base strategy but has a more aggressive
domestic app overlay. Domestic video, short-video, music, shopping, payment,
maps, and local-life package names are placed early DIRECT to protect domestic
experience and avoid wasting proxy traffic.

WeChat and QQ package rules are not placed at the very top. They are inserted
after foreign hard pins for the same reason as macOS: they are mixed containers
that can open third-party foreign links.

### iOS Shadowrocket

`dist/shadowrocket.conf` is intentionally Traffic-Saver first:

- Domestic domains, domestic media, domestic mirrors, and CN IP rules go DIRECT.
- `⬇️ 下载` defaults proxy-first so known foreign software/object-storage downloads
  are not forced to direct.
- `🌐 兜底` defaults DIRECT first.
- GitHub, AI, Google, Developer, Telegram, Microsoft, and streaming groups still
  default proxy-first.

iOS does not have the same process/package routing freedom as Mihomo on macOS or
Android. The Shadowrocket renderer therefore reuses the same source rule order
where syntax overlaps, translates Mihomo-only `GEOSITE` / `GEOIP` slots into
mirrored Shadowrocket rule files, and avoids pretending that iOS can exactly
match Android package-level behavior.

If proxy traffic is expensive or the phone is mostly used for domestic apps,
Shadowrocket should keep the generated Traffic-Saver behavior. If a specific
foreign unknown site fails on iOS, add a small explicit pin instead of changing
the whole iOS `FINAL` back to proxy-first.

`dist/shadowrocket-strict.conf` is generated as a fallback profile. It keeps the
same rules and proxy-first download group, but makes `🌐 兜底` proxy-first. Use it
only when iOS needs desktop-like foreign recall; the default phone profile remains
Traffic-Saver.

## Update And Maintenance Model

The rule source of truth is kept in reviewable templates:

- `sources/upstream.yaml`: upstream node secret, public artifact base URL, and
  all mirrored rule sources.
- `config/mihomo/base.yaml`: DNS, IPv6, geodata, sniffer, and general Mihomo
  runtime settings.
- `config/mihomo/groups.yaml`: shared group definitions and defaults.
- `config/mihomo/rules.yaml`: canonical route order.
- `config/mihomo/overlays/macos.yaml`: macOS process overlay.
- `config/mihomo/overlays/android.yaml`: Android package/process overlay.
- `config/mihomo/validation.yaml`: policy checks for Mihomo route order and
  group defaults.
- `config/route-expectations.yaml`: representative domain routing tests.
- `rules/custom/developer_global.txt`: small local developer ecosystem list.
- `config/rule-audit-baseline.yaml`: line-count and type baseline for critical
  mirrored rule providers.
- `build/rule-audit.json`: generated provider manifest with line counts,
  domain/IP/process counts, and sha256 hashes for drift checks.

Generated files land in `dist/` and should not be edited manually. For local
Clash Verge changes, update the source templates, regenerate, validate, commit,
push, then update the client profile from the published URL.

## Validation Strategy

`python -m subscription_builder.cli validate` checks:

- Mihomo syntax with `verge-mihomo -t` when Clash Verge Rev is installed.
- Mihomo group existence, rule-provider references, final rule placement, IPv6
  policy, and route ordering.
- Shadowrocket sections, IPv6 policy, key foreign groups, final rule placement,
  and rule ordering.
- Representative domain routing from `config/route-expectations.yaml`, including
  GitHub assets, AI domains, Telegram, Google, YouTube/Netflix, common Chinese
  video sites, domestic mirrors, Microsoft CDN, JetBrains downloads, npm/PyPI,
  Hugging Face, and CN direct behavior.
- Rule-provider audit data from `build/rule-audit.json`, including empty-provider
  checks, non-IP provider IP leakage checks, and strict Mihomo split checks for
  domestic direct domain/IP providers.
- Provider drift baseline from `config/rule-audit-baseline.yaml`, which catches
  empty, unexpectedly tiny, unexpectedly huge, or type-mismatched critical rule
  outputs before publishing.

`python -m pytest` covers renderer behavior, local rule source handling,
Traffic-Saver Shadowrocket group defaults, overlay insertion order, and route
expectation simulation.

`python -m subscription_builder.cli smoke-runtime` starts temporary Mihomo
instances on high local ports, waits for providers to load, and requests
representative URLs through the generated mixed-port. This catches runtime
failures that static YAML validation cannot see.

Important: `mihomo-full.yaml` contains proxy nodes. Publishing `dist/` to
public GitHub Pages exposes those nodes to anyone with the URL. For private use,
prefer a local Clash Verge profile, a private static host, or a self-hosted
subscription service with access control.

## Local Usage

```bash
cd /Users/ziyi/Documents/code/mihomo-subscription-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export UPSTREAM_SUB_URL="https://example.com/sub/your-token"
export PUBLIC_BASE_URL="https://suehn.github.io/mihomo-subscription-builder"

python -m subscription_builder.cli build-all
python -m subscription_builder.cli validate
python -m subscription_builder.cli smoke-runtime
python -m pytest
```

Generated files land in `dist/`:

- `dist/mihomo-full.yaml`
- `dist/mihomo-android.yaml`
- `dist/shadowrocket.conf`
- `dist/shadowrocket-strict.conf`
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

- `shadowrocket.conf` for Traffic-Saver routing policy and groups
- `shadowrocket-strict.conf` for a proxy-first iOS final fallback variant
- `shadowrocket-subscription.txt` as the canonical node subscription fallback

If a future Shadowrocket build rejects the generated local VLESS line inside
`shadowrocket.conf`, import `shadowrocket-subscription.txt` first, then keep
using `shadowrocket.conf` for rules and groups.

The default route set intentionally does not enable ad blocking. Blocking rules
are mirrored as artifacts, but keeping them out of the default route order
reduces the chance of breaking domestic apps or login flows during always-on use.
