from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import yaml

from .config import ProjectConfig, load_project_config
from .nodes import fetch_and_parse_nodes, write_nodes_json, write_shadowrocket_uri_artifacts
from .render import render_index, render_mihomo, render_shadowrocket
from .rules import build_rules, write_rule_manifest


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
    upstream_url = config.resolve_upstream_url(args.upstream_url)
    public_base_url = config.resolve_public_base_url(args.public_base_url)
    nodes = fetch_and_parse_nodes(upstream_url, config.user_agent)
    write_nodes_json(nodes, build_root / "nodes.json")
    write_shadowrocket_uri_artifacts(nodes, output_root)
    manifest = build_rules(config, output_root)
    write_rule_manifest(manifest, build_root / "rule-manifest.json")
    render_mihomo(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
    )
    render_shadowrocket(
        project_root=project_root,
        output_root=output_root,
        public_base_url=public_base_url,
        nodes=nodes,
        manifest=manifest,
    )
    render_index(output_root=output_root, public_base_url=public_base_url)
    return 0


def _validate(args: argparse.Namespace) -> int:
    project_root, _, output_root, _ = _load_context(args)
    mihomo_path = output_root / "mihomo-full.yaml"
    shadowrocket_path = output_root / "shadowrocket.conf"
    if not mihomo_path.exists():
        raise FileNotFoundError(mihomo_path)
    if not shadowrocket_path.exists():
        raise FileNotFoundError(shadowrocket_path)

    mihomo_data = yaml.safe_load(mihomo_path.read_text(encoding="utf-8"))
    required_keys = {"proxies", "proxy-groups", "rule-providers", "rules"}
    missing = required_keys - set(mihomo_data.keys())
    if missing:
        raise ValueError(f"Mihomo config is missing required keys: {sorted(missing)}")

    shadowrocket_text = shadowrocket_path.read_text(encoding="utf-8")
    for section in ("[General]", "[Proxy]", "[Proxy Group]", "[Rule]"):
        if section not in shadowrocket_text:
            raise ValueError(f"Shadowrocket config is missing section: {section}")

    mihomo_bin = Path(args.mihomo_bin).resolve() if args.mihomo_bin else DEFAULT_MIhOMO_BIN
    if mihomo_bin.exists():
        subprocess.run([str(mihomo_bin), "-t", "-f", str(mihomo_path)], check=True)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build remote subscriptions for Mihomo and Shadowrocket.")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--upstream-url", default=None)
    parser.add_argument("--public-base-url", default=None)
    parser.add_argument("--mihomo-bin", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("build-all")
    subparsers.add_parser("validate")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build-all":
        return _build_all(args)
    if args.command == "validate":
        return _validate(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
