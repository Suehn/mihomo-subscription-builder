from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys

from .config import ProjectConfig, load_project_config
from .models import ProxyNode
from .nodes import (
    NodeSourceResult,
    fetch_and_parse_node_source,
    parse_node_source_text,
    read_nodes_json,
    write_node_source_audit,
    write_nodes_json,
    write_shadowrocket_uri_artifacts,
)
from .render import prepare_public_pages, render_index, render_mihomo, render_shadowrocket
from .route_expectations import validate_route_expectations, validate_rule_coverage
from .runtime_smoke import run_mihomo_runtime_smoke
from .rules import (
    build_rules,
    format_rule_source_summary,
    write_rule_audit,
    write_rule_manifest,
    write_rule_source_status,
)
from .validate import (
    validate_mihomo_config,
    validate_public_pages_artifact,
    validate_rule_audit,
    validate_shadowrocket_config,
)


DEFAULT_MIHOMO_BIN = Path("/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo")


@dataclass(slots=True)
class BuildOptions:
    project_root: Path | None = None
    config_path: Path | None = None
    upstream_url: str | None = None
    public_base_url: str | None = None
    private_base_url: str | None = None
    use_cached_nodes: bool = False


@dataclass(slots=True)
class PublicPagesOptions:
    project_root: Path | None = None
    config_path: Path | None = None
    public_base_url: str | None = None
    output: Path | None = None


@dataclass(slots=True)
class ValidateOptions:
    project_root: Path | None = None
    config_path: Path | None = None
    mihomo_bin: Path | None = None


@dataclass(slots=True)
class RuntimeSmokeOptions:
    project_root: Path | None = None
    config_path: Path | None = None
    mihomo_bin: Path | None = None
    mixed_port: int = 18600
    controller_port: int = 18601
    provider_timeout: float = 30
    urls: list[str] | None = None


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_context(
    *,
    project_root: Path | None,
    config_path: Path | None,
) -> tuple[Path, ProjectConfig, Path, Path]:
    resolved_project_root = project_root.resolve() if project_root else default_project_root()
    resolved_config_path = config_path.resolve() if config_path else resolved_project_root / "sources" / "upstream.yaml"
    output_root = resolved_project_root / "dist"
    build_root = resolved_project_root / "build"
    output_root.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    return resolved_project_root, load_project_config(resolved_config_path), output_root, build_root


def fetch_configured_nodes(
    *,
    config: ProjectConfig,
    upstream_url: str | None = None,
) -> tuple[list[ProxyNode], list[NodeSourceResult]]:
    nodes: list[ProxyNode] = []
    source_results: list[NodeSourceResult] = []
    primary_source_id = config.node_sources[0].source_id
    for source in config.node_sources:
        explicit_url = upstream_url if source.source_id == primary_source_id else None
        source_url = explicit_url or os.environ.get(source.env_var, "")
        source_text = os.environ.get(source.text_env_var, "") if source.text_env_var else ""
        if not source_url and not source_text:
            if source.required:
                raise ValueError(
                    f"Missing upstream subscription URL. Set {source.env_var} or pass --upstream-url."
                )
            continue

        fetch_error: RuntimeError | None = None
        result: NodeSourceResult | None = None
        if source_url:
            try:
                result = fetch_and_parse_node_source(
                    url=source_url,
                    user_agent=config.user_agent,
                    source_id=source.source_id,
                    label=source.label,
                    group_policy=source.group_policy,
                    include_name_contains=source.include_name_contains,
                    include_name_regex=source.include_name_regex,
                    name_override=source.name_override,
                    prefix_label=source.prefix_label,
                    metadata=source.metadata,
                )
            except RuntimeError as exc:
                fetch_error = exc

        if result is None and source_text:
            metadata = {**source.metadata}
            if fetch_error is not None:
                metadata["fetch_error"] = str(fetch_error)
                metadata["fallback"] = source.text_env_var
                print(
                    f"Warning: optional node source {source.source_id!r} URL fetch failed; "
                    f"using {source.text_env_var} fallback: {fetch_error}",
                    file=sys.stderr,
                )
            result = parse_node_source_text(
                raw_text=source_text,
                source_id=source.source_id,
                label=source.label,
                group_policy=source.group_policy,
                include_name_contains=source.include_name_contains,
                include_name_regex=source.include_name_regex,
                name_override=source.name_override,
                prefix_label=source.prefix_label,
                metadata=metadata,
            )

        if result is None and fetch_error is not None:
            if source.required:
                raise fetch_error
            print(f"Warning: optional node source {source.source_id!r} skipped: {fetch_error}", file=sys.stderr)
            source_results.append(
                NodeSourceResult(
                    source_id=source.source_id,
                    label=source.label,
                    group_policy=source.group_policy,
                    nodes=[],
                    userinfo={},
                    metadata={**source.metadata, "fetch_error": str(fetch_error)},
                )
            )
            continue
        if result is None:
            continue
        nodes.extend(result.nodes)
        source_results.append(result)
    return nodes, source_results


def build_all(options: BuildOptions) -> None:
    project_root, config, output_root, build_root = _load_context(
        project_root=options.project_root,
        config_path=options.config_path,
    )
    public_base_url = config.resolve_public_base_url(options.public_base_url)
    private_base_url = config.resolve_private_base_url(options.private_base_url, public_base_url=public_base_url)
    if options.use_cached_nodes:
        nodes = read_nodes_json(build_root / "nodes.json")
        source_results: list[NodeSourceResult] = []
    else:
        nodes, source_results = fetch_configured_nodes(config=config, upstream_url=options.upstream_url)
        write_nodes_json(nodes, build_root / "nodes.json")
    write_shadowrocket_uri_artifacts(nodes, output_root)
    source_audit = write_node_source_audit(
        nodes=nodes,
        source_results=source_results,
        output_path=build_root / "node-sources.json",
    )
    write_node_source_audit(
        nodes=nodes,
        source_results=source_results,
        output_path=output_root / "node-sources.json",
    )
    manifest = build_rules(config, output_root, project_root=project_root)
    write_rule_manifest(manifest, build_root / "rule-manifest.json")
    write_rule_source_status(manifest, build_root / "rule-source-status.json")
    print(format_rule_source_summary(manifest), file=sys.stderr)
    write_rule_audit(manifest, output_root, build_root / "rule-audit.json")
    render_mihomo(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
        node_source_audit=source_audit,
        overlay_name="macos",
        output_name="mihomo-full.yaml",
    )
    render_mihomo(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
        node_source_audit=source_audit,
        overlay_name="android",
        output_name="mihomo-android.yaml",
    )
    render_shadowrocket(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        private_base_url=private_base_url,
        nodes=nodes,
        manifest=manifest,
        node_source_audit=source_audit,
        output_name="shadowrocket.conf",
    )
    render_shadowrocket(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        private_base_url=private_base_url,
        nodes=nodes,
        manifest=manifest,
        node_source_audit=source_audit,
        output_name="shadowrocket-strict.conf",
    )
    render_index(output_root=output_root, public_base_url=public_base_url, private_base_url=private_base_url)


def prepare_public_pages_artifact(options: PublicPagesOptions) -> None:
    project_root, config, output_root, _ = _load_context(
        project_root=options.project_root,
        config_path=options.config_path,
    )
    public_base_url = config.resolve_public_base_url(options.public_base_url)
    pages_root = options.output.resolve() if options.output else project_root / "public-dist"
    prepare_public_pages(source_root=output_root, output_root=pages_root, public_base_url=public_base_url)
    validate_public_pages_artifact(pages_root)


def validate_outputs(options: ValidateOptions) -> None:
    project_root, _, output_root, _ = _load_context(
        project_root=options.project_root,
        config_path=options.config_path,
    )
    mihomo_path = output_root / "mihomo-full.yaml"
    android_mihomo_path = output_root / "mihomo-android.yaml"
    shadowrocket_path = output_root / "shadowrocket.conf"
    shadowrocket_strict_path = output_root / "shadowrocket-strict.conf"
    for required_path in (mihomo_path, android_mihomo_path, shadowrocket_path, shadowrocket_strict_path):
        if not required_path.exists():
            raise FileNotFoundError(required_path)

    validation_path = project_root / "config" / "mihomo" / "validation.yaml"
    validate_mihomo_config(mihomo_path, validation_path)
    validate_mihomo_config(android_mihomo_path, validation_path)
    validate_rule_audit(
        project_root / "build" / "rule-audit.json",
        project_root / "config" / "rule-audit-baseline.yaml",
    )

    validate_shadowrocket_config(shadowrocket_path)
    validate_shadowrocket_config(shadowrocket_strict_path)
    validate_route_expectations(
        mihomo_paths=[mihomo_path, android_mihomo_path],
        shadowrocket_path=shadowrocket_path,
        shadowrocket_strict_path=shadowrocket_strict_path,
        expectations_path=project_root / "config" / "route-expectations.yaml",
    )
    validate_rule_coverage(
        mihomo_paths=[mihomo_path, android_mihomo_path],
        shadowrocket_path=shadowrocket_path,
        shadowrocket_strict_path=shadowrocket_strict_path,
        coverage_path=project_root / "config" / "rule-coverage.yaml",
    )

    mihomo_bin = options.mihomo_bin.resolve() if options.mihomo_bin else DEFAULT_MIHOMO_BIN
    if mihomo_bin.exists():
        subprocess.run([str(mihomo_bin), "-t", "-f", str(mihomo_path)], check=True)
        subprocess.run([str(mihomo_bin), "-t", "-f", str(android_mihomo_path)], check=True)


def smoke_runtime(options: RuntimeSmokeOptions) -> None:
    project_root, _, output_root, _ = _load_context(
        project_root=options.project_root,
        config_path=options.config_path,
    )
    mihomo_bin = options.mihomo_bin.resolve() if options.mihomo_bin else DEFAULT_MIHOMO_BIN
    if not mihomo_bin.exists():
        raise FileNotFoundError(mihomo_bin)

    urls = options.urls or ["https://www.baidu.com/", "https://github.com/"]
    for index, config_name in enumerate(("mihomo-full.yaml", "mihomo-android.yaml")):
        run_mihomo_runtime_smoke(
            mihomo_bin=mihomo_bin,
            config_path=output_root / config_name,
            mixed_port=options.mixed_port + index * 10,
            controller_port=options.controller_port + index * 10,
            urls=urls,
            provider_timeout_seconds=options.provider_timeout,
        )
