from __future__ import annotations

from subscription_builder.rule_grammar import (
    is_domain_rule,
    is_ip_rule,
    is_process_rule,
    payload_lines_from_content,
    policy_from_rule,
    referenced_rule_provider_ids,
    rule_matches_domain,
    with_resolved_policy,
)


def test_payload_lines_from_content_accepts_yaml_payload_and_plain_text() -> None:
    assert payload_lines_from_content(
        """
payload:
  - DOMAIN-SUFFIX,example.com
  - +.openai.com
""".strip()
    ) == ["DOMAIN-SUFFIX,example.com", "+.openai.com"]

    assert payload_lines_from_content(
        """
# comment
DOMAIN,api.example.com

IP-CIDR,192.0.2.0/24
""".strip()
    ) == ["DOMAIN,api.example.com", "IP-CIDR,192.0.2.0/24"]


def test_rule_kind_helpers_classify_rule_lines() -> None:
    assert is_domain_rule("DOMAIN-SUFFIX,example.com")
    assert is_domain_rule("+.example.com")
    assert is_ip_rule("192.0.2.0/24")
    assert is_ip_rule("IP-CIDR6,2001:db8::/32")
    assert is_process_rule("PROCESS-NAME,apsd")


def test_policy_from_rule_handles_final_standard_and_logic_rules() -> None:
    assert policy_from_rule("FINAL,🚀 代理") == "🚀 代理"
    assert policy_from_rule("RULE-SET,github,💻 GitHub") == "💻 GitHub"
    assert policy_from_rule("AND,((RULE-SET,download),(GEOIP,CN)),DIRECT") == "DIRECT"
    assert policy_from_rule("DOMAIN-SUFFIX,example.com") is None


def test_referenced_rule_provider_ids_finds_nested_logic_refs() -> None:
    assert referenced_rule_provider_ids(
        [
            "RULE-SET,github,💻 GitHub",
            "AND,((RULE-SET,download_domainset),(GEOIP,CN)),DIRECT",
        ]
    ) == {"github", "download_domainset"}


def test_with_resolved_policy_rewrites_only_policy_position() -> None:
    resolver = {"Proxy": "🚀 代理", "Direct": "DIRECT"}.__getitem__

    assert with_resolved_policy("FINAL,Proxy", resolver) == "FINAL,🚀 代理"
    assert with_resolved_policy("RULE-SET,github,Proxy", resolver) == "RULE-SET,github,🚀 代理"
    assert with_resolved_policy("AND,((RULE-SET,download),(GEOIP,CN)),Direct", resolver) == (
        "AND,((RULE-SET,download),(GEOIP,CN)),DIRECT"
    )


def test_rule_matches_domain_supports_common_domain_rule_forms() -> None:
    assert rule_matches_domain("DOMAIN,api.example.com", "api.example.com")
    assert not rule_matches_domain("DOMAIN,api.example.com", "www.example.com")
    assert rule_matches_domain("DOMAIN-SUFFIX,example.com", "www.example.com")
    assert rule_matches_domain("DOMAIN-KEYWORD,example", "cdn.example.net")
    assert rule_matches_domain("+.example.org", "www.example.org")
    assert not rule_matches_domain("IP-CIDR,192.0.2.0/24", "example.com")
