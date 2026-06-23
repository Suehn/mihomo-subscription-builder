from __future__ import annotations

from pathlib import Path

import pytest

from subscription_builder.config import ProjectConfig, RuleOutput, RuleSpec
from subscription_builder.rules import (
    BuiltRule,
    _convert_clash_classical_domain,
    _convert_clash_classical_ip,
    _convert_clash_classical_non_ip,
    _convert_metacubex_domain_yaml_to_shadowrocket,
    _convert_metacubex_ip_yaml_to_shadowrocket,
    _fetch_text,
    build_rules,
    format_rule_source_summary,
    rule_source_status_report,
    write_rule_source_status,
)


def _project_config(rule_output: RuleOutput) -> ProjectConfig:
    return ProjectConfig(
        subscription_env_var="UPSTREAM_SUB_URL",
        node_sources=[],
        public_base_url_env="PUBLIC_BASE_URL",
        private_base_url_env="PRIVATE_BASE_URL",
        default_public_base_url="https://example.test/sub",
        user_agent="test-agent/1.0",
        rules=[
            RuleSpec(
                rule_id="remote_rule",
                policy="DIRECT",
                outputs={"mihomo": rule_output},
            )
        ],
    )


def test_convert_metacubex_domain_yaml_to_shadowrocket() -> None:
    content = """
payload:
  - full:example.com
  - keyword:github
  - regexp:^api[.]example[.]com$
  - domain:openai.com
  - +.google.com
  - .claude.ai
  - telegram.org
""".strip()
    rendered = _convert_metacubex_domain_yaml_to_shadowrocket(content)
    assert rendered.splitlines() == [
        "DOMAIN,example.com",
        "DOMAIN-KEYWORD,github",
        "DOMAIN-REGEX,^api[.]example[.]com$",
        "DOMAIN-SUFFIX,openai.com",
        "DOMAIN-SUFFIX,google.com",
        "DOMAIN-SUFFIX,claude.ai",
        "DOMAIN-SUFFIX,telegram.org",
    ]


def test_convert_metacubex_ip_yaml_to_shadowrocket() -> None:
    content = """
payload:
  - 1.1.1.0/24
  - 2606:4700::/32
""".strip()
    rendered = _convert_metacubex_ip_yaml_to_shadowrocket(content)
    assert rendered.splitlines() == [
        "IP-CIDR,1.1.1.0/24",
        "IP-CIDR6,2606:4700::/32",
    ]


def test_split_clash_classical_domain_and_ip_rules() -> None:
    content = """
payload:
  - DOMAIN-SUFFIX,bilibili.com
  - DOMAIN,api.bilibili.com
  - DOMAIN-KEYWORD,bilibili
  - PROCESS-NAME,tv.danmaku.bili
  - IP-CIDR,203.107.1.0/24
  - IP-CIDR6,2400:3200::/32
  - IP-ASN,132203
""".strip()

    assert _convert_clash_classical_domain(content).splitlines() == [
        "DOMAIN-SUFFIX,bilibili.com",
        "DOMAIN,api.bilibili.com",
        "DOMAIN-KEYWORD,bilibili",
    ]
    assert _convert_clash_classical_ip(content).splitlines() == [
        "IP-CIDR,203.107.1.0/24",
        "IP-CIDR6,2400:3200::/32",
        "IP-ASN,132203",
    ]


def test_convert_clash_classical_non_ip_filters_ip_rules() -> None:
    content = """
payload:
  - DOMAIN-SUFFIX,apple.com
  - PROCESS-NAME,apsd
  - IP-CIDR,17.0.0.0/8,no-resolve
""".strip()

    assert _convert_clash_classical_non_ip(content).splitlines() == [
        "DOMAIN-SUFFIX,apple.com",
        "PROCESS-NAME,apsd",
    ]


def test_fetch_text_with_curl_timeout_fails_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    calls = 0

    def timeout_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(cmd="curl", timeout=35)

    monkeypatch.setattr("subscription_builder.rules.shutil.which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr("subscription_builder.rules.subprocess.run", timeout_run)
    monkeypatch.setattr("subscription_builder.rules.time.sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="Failed to fetch rule source after retries"):
        _fetch_text("https://example.test/slow.txt", "test-agent/1.0")
    assert calls == 3


def test_build_rules_records_successful_remote_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_fetch_text(url: str, user_agent: str) -> str:
        assert url == "https://example.test/rules.txt"
        assert user_agent == "test-agent/1.0"
        return "DOMAIN-SUFFIX,example.com\n"

    monkeypatch.setattr("subscription_builder.rules._fetch_text", fake_fetch_text)
    output = RuleOutput(
        client="mihomo",
        source_url="https://example.test/rules.txt",
        path="rules/mihomo/remote_rule.txt",
        behavior="classical",
        format="text",
    )

    manifest = build_rules(_project_config(output), tmp_path, project_root=Path.cwd())

    assert (tmp_path / "rules" / "mihomo" / "remote_rule.txt").read_text(encoding="utf-8") == (
        "DOMAIN-SUFFIX,example.com\n"
    )
    built_rule = manifest["mihomo"][0]
    assert built_rule.source_status == "fetched"
    assert built_rule.source_error is None


def test_build_rules_uses_cached_rendered_rule_on_remote_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_fetch_text(url: str, user_agent: str) -> str:
        raise RuntimeError("Failed to fetch rule source after retries: https://example.test/meta.yaml")

    monkeypatch.setattr("subscription_builder.rules._fetch_text", fail_fetch_text)
    cached_path = tmp_path / "rules" / "mihomo" / "remote_rule.txt"
    cached_path.parent.mkdir(parents=True)
    cached_path.write_text("DOMAIN-SUFFIX,cached.example\n", encoding="utf-8")
    output = RuleOutput(
        client="mihomo",
        source_url="https://example.test/meta.yaml",
        path="rules/mihomo/remote_rule.txt",
        behavior="domain",
        transform="metacubex_domain_to_shadowrocket",
    )

    manifest = build_rules(_project_config(output), tmp_path, project_root=Path.cwd())

    assert cached_path.read_text(encoding="utf-8") == "DOMAIN-SUFFIX,cached.example\n"
    built_rule = manifest["mihomo"][0]
    assert built_rule.source_status == "cached_fallback"
    assert "Failed to fetch rule source" in str(built_rule.source_error)
    assert "using cached" in capsys.readouterr().err


def test_build_rules_remote_failure_without_cache_still_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_fetch_text(url: str, user_agent: str) -> str:
        raise RuntimeError("Failed to fetch rule source after retries: https://example.test/rules.txt")

    monkeypatch.setattr("subscription_builder.rules._fetch_text", fail_fetch_text)
    output = RuleOutput(
        client="mihomo",
        source_url="https://example.test/rules.txt",
        path="rules/mihomo/missing.txt",
        behavior="classical",
    )

    with pytest.raises(RuntimeError, match="Failed to fetch rule source"):
        build_rules(_project_config(output), tmp_path, project_root=Path.cwd())


def test_rule_source_status_report_summarizes_fetch_modes(tmp_path: Path) -> None:
    manifest = {
        "mihomo": [
            BuiltRule(
                rule_id="remote",
                client="mihomo",
                policy="DIRECT",
                path="rules/mihomo/remote.txt",
                source_url="https://example.test/remote.txt",
                behavior="classical",
                format="text",
                source_status="fetched",
            ),
            BuiltRule(
                rule_id="cached",
                client="mihomo",
                policy="DIRECT",
                path="rules/mihomo/cached.txt",
                source_url="https://example.test/cached.txt",
                behavior="classical",
                format="text",
                source_status="cached_fallback",
                source_error="Failed to fetch rule source after retries: https://example.test/cached.txt",
            ),
        ],
        "shadowrocket": [
            BuiltRule(
                rule_id="local",
                client="shadowrocket",
                policy="DIRECT",
                path="rules/shadowrocket/local.conf",
                source_url="rules/custom/local.txt",
                behavior=None,
                format=None,
                source_status="local",
            )
        ],
    }

    report = rule_source_status_report(manifest)
    assert report["total"] == 3
    assert report["counts"] == {"cached_fallback": 1, "fetched": 1, "local": 1}
    assert report["cached_fallbacks"] == [
        {
            "client": "mihomo",
            "rule_id": "cached",
            "path": "rules/mihomo/cached.txt",
            "source_url": "https://example.test/cached.txt",
            "source_status": "cached_fallback",
            "source_error": "Failed to fetch rule source after retries: https://example.test/cached.txt",
        }
    ]
    assert format_rule_source_summary(manifest) == "Rule sources: cached_fallback=1, fetched=1, local=1"

    output_path = tmp_path / "rule-source-status.json"
    write_rule_source_status(manifest, output_path)
    assert '"cached_fallbacks"' in output_path.read_text(encoding="utf-8")
