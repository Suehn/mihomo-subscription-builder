from __future__ import annotations

from pathlib import Path

import pytest

from subscription_builder.config import load_project_config


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "upstream.yaml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def _base_config(*, rule_suffix: str = "") -> str:
    return f"""
subscription:
  env_var: UPSTREAM_SUB_URL
artifacts:
  public_base_url_env: PUBLIC_BASE_URL
  private_base_url_env: PRIVATE_BASE_URL
  default_public_base_url: https://example.test/sub
network:
  user_agent: test-agent/1.0
rules:
- id: developer_global
  policy: Developer
  outputs:
    mihomo:
      source_file: rules/custom/developer_global.txt
      path: rules/mihomo/developer_global.txt
      behavior: classical
      format: text
    shadowrocket:
      source_file: rules/custom/developer_global.txt
      path: rules/shadowrocket/developer_global.conf
{rule_suffix}
"""


def test_load_project_config_accepts_valid_source_config(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path, _base_config()))

    assert config.subscription_env_var == "UPSTREAM_SUB_URL"
    assert config.default_public_base_url == "https://example.test/sub"
    assert [rule.rule_id for rule in config.rules] == ["developer_global"]
    assert set(config.rules[0].outputs) == {"mihomo", "shadowrocket"}


def test_load_project_config_rejects_duplicate_rule_ids(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        _base_config(
            rule_suffix="""
- id: developer_global
  policy: Developer
  outputs:
    mihomo:
      source_url: https://example.test/other.txt
      path: rules/mihomo/other.txt
      behavior: classical
"""
        ),
    )

    with pytest.raises(ValueError, match="Duplicate rule id: developer_global"):
        load_project_config(path)


def test_load_project_config_rejects_unsupported_transform(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        _base_config().replace(
            "path: rules/shadowrocket/developer_global.conf",
            "path: rules/shadowrocket/developer_global.conf\n      transform: unknown_transform",
        ),
    )

    with pytest.raises(ValueError, match="unsupported transform: unknown_transform"):
        load_project_config(path)


def test_load_project_config_rejects_unsafe_output_path(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        _base_config().replace("path: rules/mihomo/developer_global.txt", "path: ../developer_global.txt"),
    )

    with pytest.raises(ValueError, match="safe relative path"):
        load_project_config(path)


def test_load_project_config_requires_one_rule_source_per_output(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        _base_config().replace(
            "source_file: rules/custom/developer_global.txt\n      path: rules/mihomo/developer_global.txt",
            "source_url: https://example.test/developer_global.txt\n      source_file: rules/custom/developer_global.txt\n      path: rules/mihomo/developer_global.txt",
            1,
        ),
    )

    with pytest.raises(ValueError, match="exactly one of source_url or source_file"):
        load_project_config(path)


def test_load_project_config_rejects_invalid_node_source_regex(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        _base_config().replace(
            "env_var: UPSTREAM_SUB_URL",
            "env_var: UPSTREAM_SUB_URL\n  include_name_regex: '['",
        ),
    )

    with pytest.raises(ValueError, match="valid regular expression"):
        load_project_config(path)
