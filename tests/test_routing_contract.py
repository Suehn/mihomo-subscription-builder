from __future__ import annotations

from subscription_builder.routing_contract import (
    CONFIG_RULE_POLICIES,
    GROUP_LABELS,
    MIHOMO_GEOSITE_PROVIDER_FILES,
    SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_FIRST,
    SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_MEMBER,
    SHADOWROCKET_GEOSITE_RULE_IDS,
)


def test_config_rule_policies_cover_all_group_keys_and_builtin_outputs() -> None:
    assert set(GROUP_LABELS).issubset(CONFIG_RULE_POLICIES)
    assert {"DIRECT", "REJECT", "REJECT-DROP"}.issubset(CONFIG_RULE_POLICIES)
    assert "PASS" not in CONFIG_RULE_POLICIES


def test_shadowrocket_validation_group_keys_are_known_groups() -> None:
    assert set(SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_FIRST).issubset(GROUP_LABELS)
    assert set(SHADOWROCKET_FOREIGN_GROUPS_NO_DIRECT_MEMBER).issubset(GROUP_LABELS)


def test_shadowrocket_geosite_mappings_have_mihomo_provider_files() -> None:
    assert set(SHADOWROCKET_GEOSITE_RULE_IDS).issubset(MIHOMO_GEOSITE_PROVIDER_FILES)
