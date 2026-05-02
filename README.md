# mihomo-subscription-builder

Build a self-hosted remote subscription from a raw upstream node feed. The
project targets two outputs:

- `mihomo-full.yaml` for Mihomo-compatible clients
- `shadowrocket.conf` plus `shadowrocket-subscription.txt` for Shadowrocket

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

## Rule Strategy

This project is intentionally a thin Mihomo subscription assembler, not a full
hand-maintained routing rulebase. The long-term shape is:

- `MetaCubeX/meta-rules-dat` for the Mihomo geosite/geoip backbone
- `SukkaW/Surge` mirror rule sets for AI, Apple, Microsoft, Telegram, streaming,
  download, LAN, domestic, direct, and global supplemental rules
- a very small local overlay for macOS and Android process/package DIRECT rules
- policy validation that blocks unsafe rule ordering and proxy-group defaults

For Mihomo clients, the generated config uses `GEOSITE` / `GEOIP` for large
MetaCubeX categories such as `cn`, `geolocation-!cn`, `github`, `google`, and
`CN` IPs. That keeps those large rulebases in Mihomo's geodata loader instead of
loading them as normal `rule-providers` at startup.

The update model is therefore simple: upstream supplemental rule sets are
mirrored into `dist/rules/`, `dist/mihomo-full.yaml` references only the
providers that are actually used by its route order, and Mihomo can also refresh
providers through the `🔄 规则更新` policy group. Shadowrocket cannot consume
Mihomo `GEOSITE` / `GEOIP` syntax directly, so its renderer translates the same
route slots back into the mirrored Shadowrocket rule files.

The rules are kept in reviewable YAML templates under `config/mihomo/`:

- `base.yaml` controls DNS, IPv6, geodata, and sniffer behavior
- `groups.yaml` controls proxy-group defaults
- `rules.yaml` controls the stable route order
- `overlays/macos.yaml` and `overlays/android.yaml` keep device-specific direct rules
- `validation.yaml` defines CI policy checks
- `../route-expectations.yaml` defines representative domain routing expectations

The default profile is an always-on profile: domestic domains, domestic IPs, and
known Chinese apps/video services go DIRECT, specific foreign services are
pinned before broad download rules, `Download`/`Final` do not default to
DIRECT, and IPv6 is disabled by default for networks where domestic AAAA routes
are not reliable.

Shadowrocket uses the same group and rule templates where the syntax overlaps.
Mihomo-only `GEOSITE` rules are translated into explicit rule-provider or pinned
domain rules for Shadowrocket instead of maintaining a separate hand-written
iOS rule order.

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

## Validation Coverage

`python -m subscription_builder.cli validate` checks:

- Mihomo syntax with `verge-mihomo -t` when Clash Verge Rev is installed
- Mihomo and Shadowrocket group defaults, final rule placement, and rule order
- representative domain routing from `config/route-expectations.yaml`, including
  GitHub assets, AI domains, Telegram, YouTube/Netflix, common Chinese video
  sites, domestic mirrors, Microsoft CDN, JetBrains downloads, and npm registry

`python -m subscription_builder.cli smoke-runtime` starts temporary Mihomo
instances on high local ports, waits for rule providers to finish loading, and
requests representative domestic/foreign URLs through the generated mixed-port.
This catches runtime failures that `-t` cannot see. During a fresh start, large
providers may report `ruleCount: 0` briefly; the smoke waits for readiness before
testing traffic.

The default route set intentionally does not enable ad blocking. Blocking rules
are mirrored as artifacts, but keeping them out of the default route order
reduces the chance of breaking domestic apps or login flows during always-on use.
