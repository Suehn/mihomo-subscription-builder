# 订阅生成与分流设计

本文档是当前 `mihomo-subscription-builder` 的设计说明，用来说明为什么这样分流、各端如何取舍、以后更新时应该守住哪些边界。

## 1. 总体目标

当前方案不是单纯追求国外召回，也不是单纯省代理流量，而是按下面的优先级设计：

```text
P0 国内高置信流量强 DIRECT，国内体验优先无感
P0 国内下载、视频、音乐、生活类 App 尽量不浪费代理
P0 国外关键服务显式代理，不依赖宽泛兜底碰运气
P0 下载流量按国内外拆分，国外下载不要被 DIRECT 抢走
P1 多端共享同一套原则，但按客户端能力做差异化
P1 用测试、校验、发布检查保护规则顺序
P2 节点发布安全：规则公开，完整订阅走私有 URL
```

关键判断是：Mihomo 端不使用 `MATCH,DIRECT`。更稳的尾部结构是：

```yaml
- GEOIP,CN,DIRECT
- MATCH,🌐 兜底
```

`GEOIP,CN,DIRECT` 不加 `no-resolve`，用于兜住未知国内域名。`MATCH` 仍进入代理优先的兜底组，用来减少未知国外流量漏直连。

## 2. 架构分层

仓库定位是 thin generator，不是手写完整规则库。它只负责把节点、成熟规则源、小型覆盖层和多端模板组合成可发布订阅。

### 2.1 节点层

`UPSTREAM_SUB_URL` 由本地环境或 GitHub Actions secret 提供。生成器解析 `vless://`、`vmess://`、`trojan://`、`ss://` 节点，并输出 Mihomo 和 Shadowrocket 可用的订阅文件。

### 2.2 规则源层

大规则主干依赖成熟规则源：

- MetaCubeX geodata 提供 `GEOSITE` / `GEOIP` 主干，例如 `cn`、`geolocation-!cn`、`github`、`google`、`CN`。
- SukkaW 规则补充 AI、Apple、Microsoft、Telegram、Streaming、Download、LAN、Domestic、Direct、Global 等精细分类。
- 本仓库只维护小型 `rules/custom/developer_global.txt`，覆盖稳定开发生态域名，例如 PyPI、npm、Go、Docker、JetBrains、VS Code Marketplace、Hugging Face。

本地规则不应该扩成第二套大型域名库，尤其不要把 Cloudflare、Fastly、Akamai、CloudFront 这类宽泛 CDN 域名塞进 Developer。

### 2.3 模板层

核心 source of truth：

- `config/mihomo/base.yaml`：DNS、IPv6、geodata、sniffer、通用运行参数。
- `config/mihomo/groups.yaml`：策略组和默认顺序。
- `config/mihomo/rules.yaml`：Mihomo 主规则顺序。
- `config/mihomo/overlays/macos.yaml`：macOS 进程覆盖层。
- `config/mihomo/overlays/android.yaml`：Android 包名 / 进程覆盖层。
- `sources/upstream.yaml`：规则源镜像和转换声明。
- `config/route-expectations.yaml`：代表性域名路由期望。
- `config/rule-audit-baseline.yaml`：关键 provider 的行数和类型漂移基线。

生成后的 `dist/` 文件只作为包含节点的完整私有产物，不应手工编辑。`public-dist/` 是从 `dist/rules/` 派生出的公开 GitHub Pages 产物，只包含规则文件和公开索引，不包含节点。

## 3. Mihomo 规则顺序

规则顺序是整个方案的核心。当前顺序从高置信、低风险开始，到宽泛兜底结束。

### 3.1 本地和私有网络

最前面处理本机、局域网和系统噪声：

```yaml
- GEOSITE,private,DIRECT
- GEOIP,private,DIRECT,no-resolve
- RULE-SET,lan_non_ip,DIRECT
```

macOS overlay 额外把 `DOMAIN,wpad,REJECT` 放在最前，减少 WPAD 解析噪声。

### 3.2 国内高置信 DIRECT

国内大厂、国内 App、国内媒体和国内服务放在前部 DIRECT。为了避免早期 IP 规则触发解析，部分 blackmatrix7 classical provider 被拆成：

```text
*_direct_domain -> 前部 DIRECT
*_direct_ip     -> 后部 DIRECT,no-resolve
```

这样国内域名可以很早命中 DIRECT，IP 类内容则后移并加 `no-resolve`，避免和国外关键服务抢优先级。

### 3.3 国外关键服务 hard pins

GitHub、AI、YouTube 等国外关键服务用少量硬钉规则放在宽泛规则前面，防止被 download、CDN、国内规则或 Final 抢走。

代表性 hard pins：

- GitHub：`github.com`、`githubusercontent.com`、`githubassets.com`、`objects.githubusercontent.com`、`release-assets.githubusercontent.com`、`github-releases.githubusercontent.com`、`ghcr.io`。
- AI：`openai.com`、`chatgpt.com`、`oaistatic.com`、`anthropic.com`、`claude.ai`。
- YouTube：`youtube.com`、`youtu.be`、`googlevideo.com`、`ytimg.com`。

### 3.4 国内开发镜像 DIRECT

国内镜像明确 DIRECT，放在 Developer global 和 Download 前面：

```text
TUNA / USTC / BFSU / NJU / SJTU
Aliyun / Tencent Cloud / Huawei Cloud mirrors
npmmirror.com
goproxy.cn
Maven 国内源
国内容器镜像源
```

这保证国内开发下载不浪费代理。

### 3.5 Developer hard pins

国外开发基础设施被显式分到 `🛠 Developer`，并放在 Google、Microsoft、Download 之前：

```text
PyPI / pythonhosted
npm / registry.npmjs.org
Go / proxy.golang.org / sum.golang.org
Rust / crates.io
Docker / registry-1.docker.io / auth.docker.io
JetBrains
VS Code Marketplace
Hugging Face
Anaconda / PyTorch
HashiCorp / Terraform
```

这样 Go 不会只靠 Google 组兜，VS Code Marketplace 也不会只靠 Microsoft 组兜，语义更干净。

### 3.6 Apple 和 Microsoft 拆分

Apple 不是全代理，也不是全直连：

```text
Apple CN / Apple CDN -> DIRECT
Apple Intelligence   -> 🤖 AI
Apple Services       -> 🍎 Apple
🍎 Apple 默认 DIRECT
```

Microsoft 也拆成国内 CDN 和全球服务：

```text
Microsoft CN / Microsoft CDN -> DIRECT
Microsoft global services    -> 🪟 Microsoft
🪟 Microsoft 默认代理优先
```

### 3.7 Download 国内外动态拆分

Mihomo 端现在用逻辑规则拆 Download：

```yaml
- AND,((RULE-SET,download_domainset),(GEOIP,CN)),DIRECT
- AND,((RULE-SET,download_non_ip),(GEOIP,CN)),DIRECT
- RULE-SET,download_domainset,⬇️ 下载
- RULE-SET,download_non_ip,⬇️ 下载
```

效果是：

```text
命中 Download 且解析到 CN IP -> DIRECT
命中 Download 且不是 CN IP  -> ⬇️ 下载
```

`⬇️ 下载` 组保持代理优先。国内镜像和 CN IP 下载会在更早规则或动态拆分里 DIRECT，国外对象存储和软件大文件下载不会被无脑直连。

### 3.8 尾部兜底

尾部顺序是：

```yaml
- RULE-SET,global_non_ip,🚀 代理
- GEOSITE,geolocation-!cn,🚀 代理
- RULE-SET,..._ip,DIRECT,no-resolve
- RULE-SET,domestic_ip,DIRECT,no-resolve
- GEOIP,CN,DIRECT
- MATCH,🌐 兜底
```

这里的核心是让未知国内站有 CN IP DIRECT 机会，同时让未知国外站进入代理优先兜底。

## 4. 策略组默认值

Mihomo 端：

```text
🌐 兜底：代理优先
⬇️ 下载：代理优先
GitHub / AI / Google / Developer / Telegram / Streaming：代理优先
🍎 Apple：DIRECT 优先
🪟 Microsoft：代理优先，CN/CDN 在前置规则直连
```

这个默认值的失败模式是可控的：少量未知国内域名可能先经历 CN IP 判断，国外未知流量不会直接落到 DIRECT。

`GitHub`、`Developer`、`Streaming`、`Download` 这些关键国外组不包含 `DIRECT` 成员。这是为了避免客户端 `store-selected` 把一次临时手动选择持久化成长期 DIRECT，导致 GitHub、开发下载或国外大文件下载重新绕开代理。需要全局应急直连时，仍可以从 `🚀 代理` 或 `🌐 兜底` 这类更上层组操作。

## 5. 多端策略

### 5.1 macOS Clash Verge Rev

`mihomo-full.yaml` 是桌面主配置，属于 strict always-on：

- IPv6 关闭。
- 国内域名、国内服务、CN IP 直连。
- GitHub、AI、Google、Telegram、Developer、Microsoft global、Streaming 显式代理。
- `🌐 兜底` 代理优先。
- 不按浏览器、VS Code、终端、包管理器进程 DIRECT。

macOS overlay 只把 NetEase Music、UURemote 这类纯国内进程提前 DIRECT。WeChat / QQ 是混合容器，放在国外硬钉之后，避免微信内打开 GitHub、OpenAI、Google 等链接时被进程规则抢走。

### 5.2 Android Mihomo

`mihomo-android.yaml` 共用主规则，并增加更强的国内 App overlay：

```text
国内视频、短视频、音乐、电商、支付、地图、本地生活 App -> 早期 DIRECT
```

WeChat / QQ 包名同样不放在所有规则最前，而是放在国外硬钉之后。暂不使用 `tun.exclude-package`，因为它会让流量完全绕过 Mihomo，日志不可见，后续排障成本更高。

### 5.3 iOS Shadowrocket Traffic-Saver

`shadowrocket.conf` 是 iOS 默认配置，目标是 Traffic-Saver：

```text
🌐 兜底：DIRECT 优先
⬇️ 下载：代理优先
已知国外服务：代理优先
国内域名 / 国内媒体 / CN IP：DIRECT
```

Shadowrocket 不强行复刻 Mihomo 的 `AND/OR/NOT/SUB-RULE`。渲染器会跳过这些 Mihomo 专用逻辑规则，只复用语法兼容的规则顺序和规则集。

这版关键变化是 iOS 的 Download 不再 DIRECT first。这样手机仍然省流量，但国外已知下载不会被默认直连拖慢或失败。

### 5.4 iOS Shadowrocket Strict

`shadowrocket-strict.conf` 是备用配置，规则和 Download 顺序与默认 iOS 配置一致，但 `🌐 兜底` 改为代理优先。它适合 iOS 需要更强国外召回时使用，不是默认手机策略。

## 6. DNS 和 IPv6

IPv6 保持关闭：

```yaml
ipv6: false
dns:
  ipv6: false
```

原因是本机环境曾出现国内 IPv6 地址命中 CN DIRECT 后 `no route to host` 或 `i/o timeout`。在接入网络、路由器、TUN 栈和运营商 IPv6 都稳定前，开启 IPv6 会损害国内直连体验。

DNS 以稳定国内 DoH 为主，不默认使用 `1.1.1.1` 或 `8.8.8.8` 这类本地曾刷 timeout 的国外 DoH。

## 7. 验证护栏

当前验证分四层：

1. `python -m subscription_builder.cli validate`：检查 Mihomo/Shadowrocket 语法、策略组、provider 引用、规则顺序、IPv6 策略、路由期望、provider audit 和 provider drift baseline。
2. `python -m pytest`：检查渲染器、逻辑规则解析、Shadowrocket Traffic-Saver/Strict、provider 拆分和路由模拟。
3. `verge-mihomo -t`：对 `mihomo-full.yaml` 和 `mihomo-android.yaml` 做真实 Mihomo 配置检查。
4. GitHub Actions：push 后重新生成并发布远端订阅。

关键测试目标：

- `GEOIP,CN,DIRECT` 不能变回 `no-resolve`。
- Mihomo 必须包含 Download/CN 动态拆分。
- Shadowrocket 不能包含 Mihomo 逻辑规则。
- iOS Traffic-Saver 的 `🌐 兜底` 必须 DIRECT first。
- 所有 profile 的 `⬇️ 下载` 必须代理优先。
- `GitHub`、`Developer`、`Streaming`、`Download` 不得包含 `DIRECT` 成员。
- Developer hard pins 必须早于 Google / Microsoft / Download 的宽泛规则。
- split provider 不得出现 domain/IP 类型泄漏。
- 关键 provider 必须落在 `config/rule-audit-baseline.yaml` 定义的行数范围内，并满足 domain/IP 类型约束。

## 8. 更新流程

日常更新流程：

```bash
python -m subscription_builder.cli build-all
python -m subscription_builder.cli prepare-public-pages
python -m subscription_builder.cli validate
python -m pytest
git commit
git push
```

发布后需要按发布模式确认远端文件，而不是只相信本地 `dist/`。

legacy 模式下，私有发布密钥未配置完整，GitHub Pages 仍上传 `dist/`，用于避免旧订阅 URL 立即失效。至少检查：

- `mihomo-full.yaml` 规则数、provider 数、策略组数。
- `mihomo-android.yaml` 规则数、provider 数、策略组数。
- `shadowrocket.conf` 是否 Traffic-Saver。
- `shadowrocket-strict.conf` 是否 Strict。
- Download 组是否代理优先。
- GitHub / Developer / Streaming / Download 是否不含 DIRECT。
- Mihomo 是否含 `AND(download,GEOIP,CN)`。

split-private 模式下，私有发布密钥配置完整，GitHub Pages 改为上传 `public-dist/`，完整订阅上传到 `PRIVATE_BASE_URL` 对应的私有静态目录。至少检查：

- GitHub Pages 上不存在 `mihomo-full.yaml`、`mihomo-android.yaml`、`shadowrocket.conf`、`shadowrocket-subscription.txt`。
- GitHub Pages 上 `rules/mihomo/` 和 `rules/shadowrocket/` 可访问。
- `PRIVATE_BASE_URL/mihomo-full.yaml` 和 `PRIVATE_BASE_URL/shadowrocket.conf` 可通过客户端订阅更新。
- 私有 Shadowrocket 配置里的 fallback subscription 指向 `PRIVATE_BASE_URL/shadowrocket-subscription.txt`。

## 9. 当前成功标准

当前版本达标的判断标准：

```text
macOS: Final 代理优先，Download 代理优先，CN IP 可解析 DIRECT
Android: 国内 App 强 DIRECT，WeChat / QQ 不抢国外硬钉
iOS Traffic-Saver: Final DIRECT 优先，Download 代理优先
iOS Strict: Final 代理优先，Download 代理优先
Developer: Go / npm / PyPI / Docker / Hugging Face / VS Code / Anaconda / PyTorch / HashiCorp 等显式 Developer
关键国外组: GitHub / Developer / Streaming / Download 不含 DIRECT
Download: 国内候选 DIRECT，国外候选 Download 代理组
IPv6: 关闭
发布: GitHub Actions 成功；legacy 模式下旧订阅 URL 不断，split-private 模式下公开 Pages 只含规则、私有 URL 可拉取完整订阅
```

## 10. P2 安全发布架构

GitHub Pages 不能给单个文件加访问控制。只要完整 `mihomo-full.yaml` 或 `shadowrocket.conf` 继续放在公开 Pages，同 URL 的任何人都可以拿到节点。因此当前安全发布架构把规则和节点分开：

```text
GitHub Pages:
  public-dist/index.html
  public-dist/rules/

私有静态服务:
  dist/mihomo-full.yaml
  dist/mihomo-android.yaml
  dist/shadowrocket.conf
  dist/shadowrocket-strict.conf
  dist/shadowrocket-subscription.txt
```

`PUBLIC_BASE_URL` 只承担规则分发，例如 `https://suehn.github.io/mihomo-subscription-builder/rules/...`。`PRIVATE_BASE_URL` 承担完整订阅分发，Clash Verge Rev、Android Mihomo 和 Shadowrocket 都应订阅私有 URL。

为了不打断现有链接，CI 有一个明确迁移门：

- 私有发布密钥不完整时，继续把 `dist/` 上传到 GitHub Pages，保持旧链接可更新，但这仍是 legacy 暴露模式。
- `PRIVATE_BASE_URL`、`PRIVATE_SSH_HOST`、`PRIVATE_SSH_USER`、`PRIVATE_SSH_PATH`、`PRIVATE_SSH_KEY` 配置完整后，CI 先用 `rsync --delete` 把 `dist/` 发到私有主机，再把 GitHub Pages 切成 `public-dist/`。
- 切换后需要把各端订阅 URL 从公开 Pages 改到 `PRIVATE_BASE_URL`；后续仍然是链接订阅更新，不需要手工拷贝配置。

这个迁移门避免“为了安全直接删除公开 full YAML，导致当前客户端 404”。真正完成节点私有化的判据是：公开 Pages 上 full YAML 和 Shadowrocket full config 不存在，私有 URL 能拉到完整订阅。
