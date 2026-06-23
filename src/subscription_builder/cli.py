from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .pipeline import (
    BuildOptions,
    PublicPagesOptions,
    RuntimeSmokeOptions,
    ValidateOptions,
    build_all,
    prepare_public_pages_artifact,
    smoke_runtime,
    validate_outputs,
)
from .publish import select_publish_mode, write_github_env_lines


def _build_all(args: argparse.Namespace) -> int:
    build_all(
        BuildOptions(
            project_root=Path(args.project_root).resolve() if args.project_root else None,
            config_path=Path(args.config).resolve() if args.config else None,
            upstream_url=args.upstream_url,
            public_base_url=args.public_base_url,
            private_base_url=args.private_base_url,
            use_cached_nodes=args.use_cached_nodes,
        )
    )
    return 0


def _prepare_public_pages(args: argparse.Namespace) -> int:
    prepare_public_pages_artifact(
        PublicPagesOptions(
            project_root=Path(args.project_root).resolve() if args.project_root else None,
            config_path=Path(args.config).resolve() if args.config else None,
            public_base_url=args.public_base_url,
            output=Path(args.output).resolve() if args.output else None,
        )
    )
    return 0


def _validate(args: argparse.Namespace) -> int:
    validate_outputs(
        ValidateOptions(
            project_root=Path(args.project_root).resolve() if args.project_root else None,
            config_path=Path(args.config).resolve() if args.config else None,
            mihomo_bin=Path(args.mihomo_bin).resolve() if args.mihomo_bin else None,
        )
    )
    return 0


def _smoke_runtime(args: argparse.Namespace) -> int:
    smoke_runtime(
        RuntimeSmokeOptions(
            project_root=Path(args.project_root).resolve() if args.project_root else None,
            config_path=Path(args.config).resolve() if args.config else None,
            mihomo_bin=Path(args.mihomo_bin).resolve() if args.mihomo_bin else None,
            mixed_port=args.mixed_port,
            controller_port=args.controller_port,
            provider_timeout=args.provider_timeout,
            urls=list(args.url),
        )
    )
    return 0


def _select_publish_mode(args: argparse.Namespace) -> int:
    mode = select_publish_mode(os.environ)
    if args.github_env:
        write_github_env_lines(mode, Path(args.github_env).resolve())
    else:
        for line in mode.github_env_lines():
            print(line)
    print(f"Publish mode: {mode.name}", file=sys.stderr)
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
    publish_parser = subparsers.add_parser("select-publish-mode")
    publish_parser.add_argument(
        "--github-env",
        default=None,
        help="Append selected publish mode variables to this GitHub Actions env file. Prints to stdout when omitted.",
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
    if args.command == "select-publish-mode":
        return _select_publish_mode(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
