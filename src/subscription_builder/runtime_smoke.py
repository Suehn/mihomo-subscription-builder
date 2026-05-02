from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

import yaml

DEFAULT_CLASH_VERGE_DATA_DIR = Path.home() / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a mapping")
    return data


def _copy_cached_rule_providers(config: dict[str, object], config_path: Path, data_dir: Path) -> None:
    providers = config.get("rule-providers", {})
    if not isinstance(providers, dict):
        return
    providers_dir = data_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        provider_path = str(provider.get("path", ""))
        if not provider_path:
            continue
        target = data_dir / provider_path
        target.parent.mkdir(parents=True, exist_ok=True)
        source = _local_rule_provider_source(config_path, provider)
        if source and source.exists():
            shutil.copy2(source, target)


def _copy_cached_geodata(data_dir: Path) -> None:
    for source_name, target_name in {
        "geosite.dat": "geosite.dat",
        "geoip.dat": "geoip.dat",
        "Country.mmdb": "Country.mmdb",
        "ASN.mmdb": "ASN.mmdb",
    }.items():
        source = DEFAULT_CLASH_VERGE_DATA_DIR / source_name
        if source.exists():
            shutil.copy2(source, data_dir / target_name)


def _local_rule_provider_source(config_path: Path, provider: dict[str, object]) -> Path | None:
    url = str(provider.get("url", ""))
    marker = "/rules/"
    if marker in url:
        relative = url.split(marker, 1)[1]
        return (config_path.parent / "rules" / relative).resolve()
    provider_path = str(provider.get("path", ""))
    if provider_path:
        return (config_path.parent / provider_path).resolve()
    return None


def _api_json(controller_port: int, path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://127.0.0.1:{controller_port}{path}", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_controller(controller_port: int, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            _api_json(controller_port, "/version")
            return
        except Exception as exc:  # pragma: no cover - exercised by CLI smoke only
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Mihomo controller did not become ready: {last_error}")


def _wait_rule_providers(controller_port: int, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    waiting: list[str] = []
    while time.time() < deadline:
        providers = _api_json(controller_port, "/providers/rules").get("providers", {})
        if not isinstance(providers, dict):
            return
        waiting = []
        for provider_id, payload in providers.items():
            if isinstance(payload, dict) and int(payload.get("ruleCount", 0)) == 0:
                waiting.append(str(provider_id))
        if not waiting:
            return
        time.sleep(0.5)
    raise RuntimeError(f"Rule providers did not finish loading: {waiting}")


def _curl_via_proxy(port: int, url: str) -> tuple[int, str]:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-L",
            "--connect-timeout",
            "4",
            "--max-time",
            "12",
            "-o",
            "/dev/null",
            "-w",
            "code=%{http_code} exit=%{exitcode} err=%{errormsg}",
            "-x",
            f"http://127.0.0.1:{port}",
            url,
        ],
        text=True,
        capture_output=True,
        timeout=16,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def run_mihomo_runtime_smoke(
    *,
    mihomo_bin: Path,
    config_path: Path,
    mixed_port: int,
    controller_port: int,
    urls: list[str],
    provider_timeout_seconds: float = 30,
) -> None:
    config = _load_yaml(config_path)
    with tempfile.TemporaryDirectory(prefix=f"mihomo-runtime-{config_path.stem}-") as tmp:
        data_dir = Path(tmp)
        config["mixed-port"] = mixed_port
        config["external-controller"] = f"127.0.0.1:{controller_port}"
        config["allow-lan"] = False
        config["log-level"] = "debug"
        tun = config.get("tun")
        if isinstance(tun, dict):
            # The smoke verifies explicit mixed-port routing. Starting a second
            # TUN stack can conflict with the live Clash Verge core on macOS.
            tun["enable"] = False
        _copy_cached_geodata(data_dir)
        _copy_cached_rule_providers(config, config_path, data_dir)
        temporary_config_path = data_dir / "config.yaml"
        temporary_config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        log_path = data_dir / "mihomo.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [str(mihomo_bin), "-d", str(data_dir), "-f", str(temporary_config_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=data_dir,
                text=True,
            )
            try:
                _wait_controller(controller_port, timeout_seconds=10)
                _wait_rule_providers(controller_port, timeout_seconds=provider_timeout_seconds)
                failures: list[str] = []
                for url in urls:
                    returncode, output = _curl_via_proxy(mixed_port, url)
                    if returncode != 0 or "code=200" not in output:
                        failures.append(f"{url}: returncode={returncode} {output}")
                if failures:
                    log_tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
                    raise RuntimeError("Runtime smoke failed:\n" + "\n".join(failures) + "\n" + log_tail)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
                        process.kill()
                        process.wait(timeout=2)
