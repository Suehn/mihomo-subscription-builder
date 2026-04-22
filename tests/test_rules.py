from __future__ import annotations

from subscription_builder.rules import (
    _convert_metacubex_domain_yaml_to_shadowrocket,
    _convert_metacubex_ip_yaml_to_shadowrocket,
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
