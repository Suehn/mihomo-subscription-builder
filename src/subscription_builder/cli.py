from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .config import ProjectConfig, load_project_config
from .nodes import fetch_and_parse_nodes, read_nodes_json, write_nodes_json, write_shadowrocket_uri_artifacts
from .render import prepare_public_pages, render_index, render_mihomo, render_shadowrocket
from .route_expectations import validate_route_expectations
from .runtime_smoke import run_mihomo_runtime_smoke
from .rules import build_rules, write_rule_audit, write_rule_manifest
from .validate import validate_mihomo_config, validate_rule_audit, validate_shadowrocket_config


DEFAULT_MIhOMO_BIN = Path("/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_context(args: argparse.Namespace) -> tuple[Path, ProjectConfig, Path, Path]:
    project_root = Path(args.project_root).resolve() if args.project_root else _project_root()
    config_path = Path(args.config).resolve() if args.config else project_root / "sources" / "upstream.yaml"
    output_root = project_root / "dist"
    build_root = project_root / "build"
    output_root.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)
    return project_root, load_project_config(config_path), output_root, build_root


def _build_all(args: argparse.Namespace) -> int:
    project_root, config, output_root, build_root = _load_context(args)
    public_base_url = config.resolve_public_base_url(args.public_base_url)
    private_base_url = config.resolve_private_base_url(args.private_base_url, public_base_url=public_base_url)
    if args.use_cached_nodes:
        nodes = read_nodes_json(build_root / "nodes.json")
    else:
        upstream_url = config.resolve_upstream_url(args.upstream_url)
        nodes = fetch_and_parse_nodes(upstream_url, config.user_agent)
        write_nodes_json(nodes, build_root / "nodes.json")
    write_shadowrocket_uri_artifacts(nodes, output_root)
    manifest = build_rules(config, output_root, project_root=project_root)
    write_rule_manifest(manifest, build_root / "rule-manifest.json")
    write_rule_audit(manifest, output_root, build_root / "rule-audit.json")
    render_mihomo(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
        overlay_name="macos",
        output_name="mihomo-full.yaml",
    )
    render_mihomo(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
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
        output_name="shadowrocket.conf",
        traffic_saver=True,
    )
    render_shadowrocket(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        private_base_url=private_base_url,
        nodes=nodes,
        manifest=manifest,
        output_name="shadowrocket-strict.conf",
        traffic_saver=False,
    )
    render_index(output_root=output_root, public_base_url=public_base_url, private_base_url=private_base_url)
    return 0


def _prepare_public_pages(args: argparse.Namespace) -> int:
    project_root, config, output_root, _ = _load_context(args)
    public_base_url = config.resolve_public_base_url(args.public_base_url)
    pages_root = Path(args.output).resolve() if args.output else project_root / "public-dist"
    prepare_public_pages(source_root=output_root, output_root=pages_root, public_base_url=public_base_url)
    return 0


def _validate(args: argparse.Namespace) -> int:
    project_root, _, output_root, _ = _load_context(args)
    mihomo_path = output_root / "mihomo-full.yaml"
    android_mihomo_path = output_root / "mihomo-android.yaml"
    shadowrocket_path = output_root / "shadowrocket.conf"
    shadowrocket_strict_path = output_root / "shadowrocket-strict.conf"
    if not mihomo_path.exists():
        raise FileNotFoundError(mihomo_path)
    if not android_mihomo_path.exists():
        raise FileNotFoundError(android_mihomo_path)
    if not shadowrocket_path.exists():
        raise FileNotFoundError(shadowrocket_path)
    if not shadowrocket_strict_path.exists():
        raise FileNotFoundError(shadowrocket_strict_path)

    validation_path = project_root / "config" / "mihomo" / "validation.yaml"
    validate_mihomo_config(mihomo_path, validation_path)
    validate_mihomo_config(android_mihomo_path, validation_path)
    validate_rule_audit(
        project_root / "build" / "rule-audit.json",
        project_root / "config" / "rule-audit-baseline.yaml",
    )

    validate_shadowrocket_config(shadowrocket_path, traffic_saver=True)
    validate_shadowrocket_config(shadowrocket_strict_path, traffic_saver=False)
    validate_route_expectations(
        mihomo_paths=[mihomo_path, android_mihomo_path],
        shadowrocket_path=shadowrocket_path,
        shadowrocket_strict_path=shadowrocket_strict_path,
        expectations_path=project_root / "config" / "route-expectations.yaml",
    )

    mihomo_bin = Path(args.mihomo_bin).resolve() if args.mihomo_bin else DEFAULT_MIhOMO_BIN
    if mihomo_bin.exists():
        subprocess.run([str(mihomo_bin), "-t", "-f", str(mihomo_path)], check=True)
        subprocess.run([str(mihomo_bin), "-t", "-f", str(android_mihomo_path)], check=True)
    return 0


def _smoke_runtime(args: argparse.Namespace) -> int:
    project_root, _, output_root, _ = _load_context(args)
    mihomo_bin = Path(args.mihomo_bin).resolve() if args.mihomo_bin else DEFAULT_MIhOMO_BIN
    if not mihomo_bin.exists():
        raise FileNotFoundError(mihomo_bin)

    urls = list(args.url)
    for index, config_name in enumerate(("mihomo-full.yaml", "mihomo-android.yaml")):
        run_mihomo_runtime_smoke(
            mihomo_bin=mihomo_bin,
            config_path=output_root / config_name,
            mixed_port=args.mixed_port + index * 10,
            controller_port=args.controller_port + index * 10,
            urls=urls,
            provider_timeout_seconds=args.provider_timeout,
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build remote subscriptions for Mihomo and Shadowrocket.")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--upstream-url", default=None)
    parser.add_argument("--public-base-url", default=None)
    parser.add_argument("--private-base-url", default=None)
    parser.add_argument("--mihomo-bin", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build-all")
    build_parser.add_argument(
        "--use-cached-nodes",
        action="store_true",
        help="Use build/nodes.json instead of fetching the upstream subscription.",
    )
    public_pages_parser = subparsers.add_parser("prepare-public-pages")
    public_pages_parser.add_argument(
        "--output",
        default=None,
        help="Output directory for the public rules-only GitHub Pages artifact. Defaults to public-dist.",
    )
    subparsers.add_parser("validate")
    smoke_parser = subparsers.add_parser("smoke-runtime")
    smoke_parser.add_argument("--mixed-port", type=int, default=18600)
    smoke_parser.add_argument("--controller-port", type=int, default=18601)
    smoke_parser.add_argument("--provider-timeout", type=float, default=30)
    smoke_parser.add_argument(
        "--url",
        action="append",
        default=["https://www.baidu.com/", "https://github.com/"],
        help="URL to request through the temporary mixed-port. Can be passed more than once.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build-all":
        return _build_all(args)
    if args.command == "prepare-public-pages":
        return _prepare_public_pages(args)
    if args.command == "validate":
        return _validate(args)
    if args.command == "smoke-runtime":
        return _smoke_runtime(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
