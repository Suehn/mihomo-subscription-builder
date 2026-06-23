from __future__ import annotations

from subscription_builder.publish import PRIVATE_DEPLOY_REQUIRED_ENV, select_publish_mode, write_github_env_lines


def _private_env() -> dict[str, str]:
    return {
        "PRIVATE_BASE_URL": "https://private.example.test/sub",
        "PRIVATE_SSH_HOST": "private.example.test",
        "PRIVATE_SSH_USER": "deploy",
        "PRIVATE_SSH_PATH": "/var/www/sub",
        "PRIVATE_SSH_KEY": "secret-key",
    }


def test_select_publish_mode_uses_split_private_when_all_private_secrets_exist() -> None:
    mode = select_publish_mode(_private_env())

    assert mode.name == "split-private"
    assert mode.private_deploy_enabled is True
    assert mode.pages_artifact_path == "public-dist"
    assert mode.effective_private_base_url == "https://private.example.test/sub"
    assert mode.github_env_lines() == [
        "PRIVATE_DEPLOY_ENABLED=true",
        "PAGES_ARTIFACT_PATH=public-dist",
        "EFFECTIVE_PRIVATE_BASE_URL=https://private.example.test/sub",
    ]


def test_select_publish_mode_falls_back_to_legacy_when_any_private_secret_is_missing() -> None:
    for key in PRIVATE_DEPLOY_REQUIRED_ENV:
        env = _private_env()
        env[key] = ""

        mode = select_publish_mode(env)

        assert mode.name == "legacy"
        assert mode.private_deploy_enabled is False
        assert mode.pages_artifact_path == "dist"
        assert mode.effective_private_base_url == ""


def test_write_github_env_lines_appends_selected_mode(tmp_path) -> None:
    output_path = tmp_path / "github-env"

    write_github_env_lines(select_publish_mode(_private_env()), output_path)

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "PRIVATE_DEPLOY_ENABLED=true",
        "PAGES_ARTIFACT_PATH=public-dist",
        "EFFECTIVE_PRIVATE_BASE_URL=https://private.example.test/sub",
    ]
