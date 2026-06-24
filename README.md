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
- Optionally merges `MESL_SUB_URL` home broadband nodes whose names contain
  `家宽` for AI fallback and manual selection in every group
- Optionally merges a private `LINUXDO_SUB_URL` / `LINUXDO_SUB_TEXT` single
  node, renames it to `美国Linuxdo`, and prefers it for AI traffic with
  `美国家宽10` as the fallback candidate
- Optionally merges a secondary `PINCHE_SUB_URL` subscription as manual-only
  nodes
- Decodes Base64 subscriptions automatically
- Parses both URI subscriptions and Mihomo/Clash YAML proxy lists
- Parses `vless://`, `vmess://`, `trojan://`, and `ss://` links
- Mirrors remote rule files into your own GitHub Pages artifact
- Renders a Mihomo configuration with self-hosted `rule-providers`
- Renders a Shadowrocket configuration and also emits URI subscription fallbacks
- Uses emoji policy groups for easier client-side reading
- Supports split publishing: public rule files on GitHub Pages, full
  node-bearing subscriptions on a private static URL

## Design Principles

For the full current architecture, routing policy, multi-client tradeoffs, and
validation guardrails, see [docs/design.md](docs/design.md).

The project is designed around one primary objective:

> Domestic traffic should be direct and unnoticeable first. On that foundation,
> known foreign services should be explicitly captured, and unknown foreign
> traffic should still have a proxy path.

The resulting failure mode is intentional. A high-confidence Chinese app,
Chinese media service, Chinese mirror, Chinese domain, or Chinese IP should be
routed DIRECT. GitHub, AI, Google, Telegram, developer infrastructure, Microsoft
global services, and streaming should be routed to named proxy groups before
they can be swallowed by broad domestic or download rules. The final group stays
proxy-first on every generated client, but CN IP fallback is allowed to resolve
so unknown Chinese domains can still land on DIRECT before the final group.

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
   group.

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
Shadowrocket does not render Mihomo logical rules, so iOS keeps simpler rule
semantics but uses the same proxy-first static group defaults as Mihomo.

### 3. Proxy Group Defaults

Mihomo and Shadowrocket share the same group names where possible:

- `🚀 代理`: primary proxy selector, first group for easy client operation. It
  defaults to the first node whose name contains `Suehn-Suehn2-260.97`, then
  `Suehn-Suehn2`, and keeps `DIRECT` as an explicit manual escape hatch.
- `💻 GitHub`, `🤖 AI`, `🔎 Google`, `🛠 Developer`, `✈️ Telegram`,
  `📺 流媒体`: explicit foreign service groups. They expose all nodes for manual
  selection but do not include `DIRECT`, which avoids persistent client-side
  selected-state accidentally turning them into long-term direct groups.
- `🍎 Apple`: defaults DIRECT because normal Apple system services, App Store,
  iCloud, push, and updates are commonly domestic-friendly. Apple Intelligence is
  routed to `🤖 AI` instead.
- `🪟 Microsoft`: defaults proxy-first for global Microsoft services, while
  Microsoft CN/CDN rules are direct before the group.
- `⬇️ 下载`: proxy-first on every generated profile. Domestic download
  candidates are handled by earlier domestic mirrors and Mihomo's
  `AND(download,GEOIP,CN)` split, not by making the whole download group DIRECT.
- `🌐 兜底`: defaults proxy-first on Mihomo, Android Mihomo, and Shadowrocket.
- `🤖 AI`: a small health-check fallback group for AI traffic. It prefers
  `美国Linuxdo`, then `美国 10 家宽` / `美国家宽10` naming variants, then the
  remaining nodes and `🚀 代理`. ChatGPT, OpenAI, Codex, Claude, Anthropic,
  Gemini, and Apple Intelligence rules route here.

Optional secondary node sources are explicit:

- `MESL_SUB_URL` is marked `manual_only` but filtered to names containing
  `家宽`. Those nodes are rendered into every static select group for manual
  selection. The AI group uses `美国家宽10` as the fallback candidate after
  `美国Linuxdo`. If the live MESL endpoint rate-limits a build,
  `MESL_SUB_TEXT` can provide a private cached home-node YAML fallback without
  committing node data.
- `LINUXDO_SUB_URL` / `LINUXDO_SUB_TEXT` is an optional private single-node
  source. The node is filtered by `linuxdo` / `美国Linuxdo`, renamed to
  `美国Linuxdo`, and injected through secrets rather than committed to source.
- `PINCHE_SUB_URL` remains manual-only. Those nodes are rendered so they can be
  selected manually from the static select groups, without becoming a separate
  automatic default path.

Traffic quota and expiry metadata are written to `dist/node-sources.json` and
also emitted as comments near the top of generated configs.

Generated private configs also prepend exact DIRECT rules for each proxy
server entry. IP nodes are rendered as single-address `IP-CIDR` / `IP-CIDR6`
rules, and domain nodes are rendered as exact `DOMAIN` rules. The generator
does not derive DIRECT rules from SNI, servername, or WebSocket Host fields, so
camouflage domains and broad CDN suffixes are not accidentally bypassed.

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

`dist/shadowrocket.conf` uses the same static group defaults as the Mihomo
profiles:

- Domestic domains, domestic media, domestic mirrors, and CN IP rules go DIRECT.
- `⬇️ 下载` defaults proxy-first so known foreign software/object-storage downloads
  are not forced to direct.
- `🌐 兜底` defaults proxy-first, matching the desktop profile.
- GitHub, AI, Google, Developer, Telegram, Microsoft, and streaming groups still
  default proxy-first.

iOS does not have the same process/package routing freedom as Mihomo on macOS or
Android. The Shadowrocket renderer therefore reuses the same source rule order
where syntax overlaps, translates Mihomo-only `GEOSITE` / `GEOIP` slots into
mirrored Shadowrocket rule files, and avoids pretending that iOS can exactly
match Android package-level behavior.

If proxy traffic is expensive or the phone is mostly used for domestic apps,
add small explicit DIRECT pins for those domains instead of making the whole iOS
`FINAL` default direct.

`dist/shadowrocket-strict.conf` is still generated as a compatibility profile for
clients that already subscribe to it. Its group defaults now match
`shadowrocket.conf`.

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
- `config/rule-coverage.yaml`: category-level route coverage matrix for
  GitHub, AI, developer ecosystems, domestic mirrors, streaming, and key
  platform services.
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
- Category coverage from `config/rule-coverage.yaml`, which keeps broader
  route coverage explicit without changing current user-facing route behavior.
- Rule-provider audit data from `build/rule-audit.json`, including empty-provider
  checks, non-IP provider IP leakage checks, and strict Mihomo split checks for
  domestic direct domain/IP providers.
- Provider drift baseline from `config/rule-audit-baseline.yaml`, which catches
  empty, unexpectedly tiny, unexpectedly huge, or type-mismatched critical rule
  outputs before publishing.

`python -m pytest` covers renderer behavior, local rule source handling, static
Shadowrocket group defaults, overlay insertion order, and route expectation
simulation.

`python -m subscription_builder.cli smoke-runtime` starts temporary Mihomo
instances on high local ports, waits for providers to load, and requests
representative URLs through the generated mixed-port. This catches runtime
failures that static YAML validation cannot see.

Important: `mihomo-full.yaml`, `mihomo-android.yaml`, `shadowrocket.conf`, and
`shadowrocket-subscription.txt` contain proxy nodes. They should not stay on
public GitHub Pages long term.

The intended secure publishing model is split by sensitivity:

- GitHub Pages publishes public rule files only: `public-dist/rules/`.
- A private static host publishes the full `dist/` directory with node-bearing
  subscriptions.
- Mihomo and Shadowrocket still update by URL. The only change is that clients
  subscribe to the private base URL for full configs, while those configs keep
  loading rule providers from the public Pages base URL.

GitHub Pages cannot make only selected files private. If full configs must stay
on the same public Pages URL, node privacy is impossible. This repository keeps a
legacy fallback in CI: until all private deploy secrets are configured, Actions
continues uploading `dist/` to Pages so existing subscriptions do not break. Once
private deploy is configured, the workflow uploads `public-dist/` to Pages and
deploys full subscriptions to the private host.

## Local Usage

```bash
cd /Users/ziyi/Documents/code/mihomo-subscription-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

export UPSTREAM_SUB_URL="https://example.com/sub/your-token"
export MESL_SUB_URL="https://example.com/mesl/your-token" # optional; imports names containing 家宽
export MESL_SUB_TEXT="$(cat /private/path/mesl-home-only.yaml)" # optional fallback
export LINUXDO_SUB_TEXT="$(cat /private/path/linuxdo-vless.txt)" # optional; exact node text or YAML
export PINCHE_SUB_URL="https://example.com/pcdy/your-token" # optional, manual-only
export PUBLIC_BASE_URL="https://suehn.github.io/mihomo-subscription-builder"
export PRIVATE_BASE_URL="https://private.example.com/mihomo-subscription-builder"

python -m subscription_builder.cli build-all
python -m subscription_builder.cli prepare-public-pages
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
- `dist/node-sources.json`
- `dist/index.html`
- `dist/rules/`

The public-safe GitHub Pages artifact lands in `public-dist/`:

- `public-dist/index.html`
- `public-dist/rules/`

`public-dist/` intentionally excludes all node-bearing full subscription files.

## GitHub Actions Setup

Create the required repository secret:

- `UPSTREAM_SUB_URL`
- `MESL_SUB_URL`: optional MESL subscription. When present, only nodes whose
  names contain `家宽` are imported. They remain manual-only as source metadata,
  but static select groups expose them for manual choice. `🤖 AI` uses
  `美国家宽10` as the fallback candidate after `美国Linuxdo`, then keeps the rest
  of the nodes available.
- `MESL_SUB_TEXT`: optional private cached MESL home-node YAML fallback. Use it
  when the live MESL endpoint rate-limits GitHub Actions; it must stay in
  GitHub Secrets and must not be committed.
- `LINUXDO_SUB_URL` or `LINUXDO_SUB_TEXT`: optional private Linuxdo node source.
  Store the VLESS URI or a one-node YAML subscription in GitHub Secrets. The
  generator renames the matched node to `美国Linuxdo` and makes it the first AI
  fallback candidate.
- `PINCHE_SUB_URL`: optional secondary subscription. When present, its nodes are
  included in Mihomo as manual-only `Pin-Che` nodes and exposed in static select
  groups for manual choice. Its node `server` entries are also covered by exact
  self-DIRECT rules in the private generated configs.

To enable private full-subscription delivery without breaking URL-based updates,
also create these repository secrets:

- `PRIVATE_BASE_URL`: the HTTPS base URL clients will subscribe to, for example
  `https://private.example.com/mihomo-subscription-builder`
- `PRIVATE_SSH_HOST`: private static host
- `PRIVATE_SSH_USER`: SSH user for deployment
- `PRIVATE_SSH_PORT`: optional SSH port, defaults to `22`
- `PRIVATE_SSH_PATH`: remote directory served by `PRIVATE_BASE_URL`
- `PRIVATE_SSH_KEY`: private key with write access to `PRIVATE_SSH_PATH`

When all private deploy secrets are present, the workflow:

1. Builds full artifacts in `dist/`.
2. Deploys `dist/` to the private host with `rsync --delete`.
3. Uploads `public-dist/` to GitHub Pages, so public Pages contains rules only.

When private deploy secrets are incomplete, the workflow keeps legacy behavior
and uploads `dist/` to GitHub Pages. This is intentional to avoid silently
breaking existing client subscription URLs before the private endpoint is ready.

The intended repository remote is:

- `https://github.com/Suehn/mihomo-subscription-builder`

## Notes About Shadowrocket

Shadowrocket imports VLESS/Reality subscriptions reliably from a remote
subscription URL, but local `[Proxy]` serialization varies between app builds.
This project therefore publishes both:

- `shadowrocket.conf` for static proxy-first final routing policy and groups
- `shadowrocket-strict.conf` for clients that already subscribe to the strict URL
- `shadowrocket-subscription.txt` as the canonical node subscription fallback

If a future Shadowrocket build rejects the generated local VLESS line inside
`shadowrocket.conf`, import `shadowrocket-subscription.txt` first, then keep
using `shadowrocket.conf` for rules and groups.

The default route set intentionally does not enable ad blocking. Blocking rules
are mirrored as artifacts, but keeping them out of the default route order
reduces the chance of breaking domestic apps or login flows during always-on use.
