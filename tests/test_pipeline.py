from __future__ import annotations

from pathlib import Path

from subscription_builder.config import ProjectConfig
from subscription_builder.models import ProxyNode
from subscription_builder.pipeline import (
    BuildOptions,
    PublicPagesOptions,
    ValidateOptions,
    build_all,
    prepare_public_pages_artifact,
    validate_outputs,
)


def _config() -> ProjectConfig:
    return ProjectConfig(
        subscription_env_var="UPSTREAM_SUB_URL",
        node_sources=[],
        public_base_url_env="PUBLIC_BASE_URL",
        private_base_url_env="PRIVATE_BASE_URL",
        default_public_base_url="https://public.example.test/sub",
        user_agent="test-agent/1.0",
        rules=[],
    )


def test_build_all_uses_cached_nodes_and_writes_expected_artifacts(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    events: list[tuple[str, object]] = []
    node = ProxyNode(
        name="node-a",
        type="vless",
        server="proxy.example.test",
        port=443,
        uuid="00000000-0000-4000-8000-000000000001",
        tls=True,
    )
    manifest = {"mihomo": [], "shadowrocket": []}

    monkeypatch.setattr("subscription_builder.pipeline.load_project_config", lambda path: _config())
    monkeypatch.setattr("subscription_builder.pipeline.read_nodes_json", lambda path: [node])
    monkeypatch.setattr(
        "subscription_builder.pipeline.fetch_configured_nodes",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should use cached nodes")),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.write_shadowrocket_uri_artifacts",
        lambda nodes, output_root: events.append(("shadowrocket-uri", output_root)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.write_node_source_audit",
        lambda nodes, source_results, output_path: events.append(("node-audit", output_path)) or {"sources": []},
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.build_rules",
        lambda config, output_root, project_root: events.append(("build-rules", output_root)) or manifest,
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.write_rule_manifest",
        lambda manifest, output_path: events.append(("rule-manifest", output_path)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.write_rule_source_status",
        lambda manifest, output_path: events.append(("rule-source-status", output_path)),
    )
    monkeypatch.setattr("subscription_builder.pipeline.format_rule_source_summary", lambda manifest: "Rule sources: test=1")
    monkeypatch.setattr(
        "subscription_builder.pipeline.write_rule_audit",
        lambda manifest, output_root, output_path: events.append(("rule-audit", output_path)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.render_mihomo",
        lambda **kwargs: events.append(("mihomo", kwargs["output_name"])),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.render_shadowrocket",
        lambda **kwargs: events.append(("shadowrocket", kwargs["output_name"])),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.render_index",
        lambda **kwargs: events.append(("index", kwargs["output_root"])),
    )

    build_all(BuildOptions(project_root=tmp_path, use_cached_nodes=True))

    assert (tmp_path / "dist").is_dir()
    assert (tmp_path / "build").is_dir()
    assert ("rule-source-status", tmp_path / "build" / "rule-source-status.json") in events
    assert ("rule-audit", tmp_path / "build" / "rule-audit.json") in events
    assert ("mihomo", "mihomo-full.yaml") in events
    assert ("mihomo", "mihomo-android.yaml") in events
    assert ("mihomo", "mihomo-generic.yaml") in events
    assert ("shadowrocket", "shadowrocket.conf") in events
    assert ("shadowrocket", "shadowrocket-strict.conf") in events
    assert "Rule sources: test=1" in capsys.readouterr().err


def test_prepare_public_pages_artifact_validates_generated_output(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr("subscription_builder.pipeline.load_project_config", lambda path: _config())
    monkeypatch.setattr(
        "subscription_builder.pipeline.prepare_public_pages",
        lambda source_root, output_root, public_base_url: calls.append(("prepare", output_root)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_public_pages_artifact",
        lambda public_root: calls.append(("validate-public", public_root)),
    )

    prepare_public_pages_artifact(PublicPagesOptions(project_root=tmp_path))

    assert calls == [
        ("prepare", tmp_path / "public-dist"),
        ("validate-public", tmp_path / "public-dist"),
    ]


def test_validate_outputs_uses_expected_generated_files(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []
    for relative_path in (
        "dist/mihomo-full.yaml",
        "dist/mihomo-android.yaml",
        "dist/mihomo-generic.yaml",
        "dist/shadowrocket.conf",
        "dist/shadowrocket-strict.conf",
        "build/rule-audit.json",
        "config/mihomo/validation.yaml",
        "config/rule-audit-baseline.yaml",
        "config/route-expectations.yaml",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr("subscription_builder.pipeline.load_project_config", lambda path: _config())
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_mihomo_config",
        lambda config_path, validation_path: calls.append(("mihomo", config_path.name)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_rule_audit",
        lambda audit_path, baseline_path: calls.append(("rule-audit", audit_path.name)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_shadowrocket_config",
        lambda config_path: calls.append(("shadowrocket", config_path.name)),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_route_expectations",
        lambda **kwargs: calls.append(("routes", [path.name for path in kwargs["mihomo_paths"]])),
    )
    monkeypatch.setattr(
        "subscription_builder.pipeline.validate_rule_coverage",
        lambda **kwargs: calls.append(("coverage", kwargs["coverage_path"].name)),
    )

    validate_outputs(ValidateOptions(project_root=tmp_path, mihomo_bin=tmp_path / "missing-mihomo"))

    assert calls == [
        ("mihomo", "mihomo-full.yaml"),
        ("mihomo", "mihomo-android.yaml"),
        ("mihomo", "mihomo-generic.yaml"),
        ("rule-audit", "rule-audit.json"),
        ("shadowrocket", "shadowrocket.conf"),
        ("shadowrocket", "shadowrocket-strict.conf"),
        ("routes", ["mihomo-full.yaml", "mihomo-android.yaml", "mihomo-generic.yaml"]),
        ("coverage", "rule-coverage.yaml"),
    ]
