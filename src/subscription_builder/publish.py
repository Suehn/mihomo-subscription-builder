from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PRIVATE_DEPLOY_REQUIRED_ENV = [
    "PRIVATE_BASE_URL",
    "PRIVATE_SSH_HOST",
    "PRIVATE_SSH_USER",
    "PRIVATE_SSH_PATH",
    "PRIVATE_SSH_KEY",
]


@dataclass(frozen=True, slots=True)
class PublishMode:
    private_deploy_enabled: bool
    pages_artifact_path: str
    effective_private_base_url: str

    @property
    def name(self) -> str:
        return "split-private" if self.private_deploy_enabled else "legacy"

    def github_env_lines(self) -> list[str]:
        return [
            f"PRIVATE_DEPLOY_ENABLED={str(self.private_deploy_enabled).lower()}",
            f"PAGES_ARTIFACT_PATH={self.pages_artifact_path}",
            f"EFFECTIVE_PRIVATE_BASE_URL={self.effective_private_base_url}",
        ]


def _has_value(env: Mapping[str, str], key: str) -> bool:
    return bool(env.get(key, "").strip())


def select_publish_mode(env: Mapping[str, str]) -> PublishMode:
    private_enabled = all(_has_value(env, key) for key in PRIVATE_DEPLOY_REQUIRED_ENV)
    if private_enabled:
        return PublishMode(
            private_deploy_enabled=True,
            pages_artifact_path="public-dist",
            effective_private_base_url=env["PRIVATE_BASE_URL"].strip(),
        )
    return PublishMode(
        private_deploy_enabled=False,
        pages_artifact_path="dist",
        effective_private_base_url="",
    )


def write_github_env_lines(mode: PublishMode, github_env_path: Path) -> None:
    with github_env_path.open("a", encoding="utf-8") as handle:
        for line in mode.github_env_lines():
            handle.write(line + "\n")
