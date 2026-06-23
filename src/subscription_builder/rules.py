from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import time
import urllib.error
import urllib.request

import yaml

from .config import ProjectConfig, RuleOutput, RuleSpec
from .rule_grammar import (
    is_domain_rule,
    is_ip_rule,
    is_process_rule,
    payload_lines_from_content,
)


RULE_FETCH_CONNECT_TIMEOUT_SECONDS = 10
RULE_FETCH_MAX_TIME_SECONDS = 30
RULE_FETCH_SUBPROCESS_TIMEOUT_SECONDS = RULE_FETCH_MAX_TIME_SECONDS + 5


@dataclass(slots=True)
class BuiltRule:
    rule_id: str
    client: str
    policy: str
    path: str
    source_url: str
    behavior: str | None
    format: str | None
    source_status: str = "unknown"
    source_error: str | None = None


@dataclass(slots=True)
class RuleSourceContent:
    text: str
    status: str
    error: str | None = None
    already_rendered: bool = False


def _fetch_text_with_curl(url: str, user_agent: str) -> str | None:
    curl = shutil.which("curl")
    if not curl:
        return None
    result = subprocess.run(
        [
            curl,
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--compressed",
            "--connect-timeout",
            str(RULE_FETCH_CONNECT_TIMEOUT_SECONDS),
            "--max-time",
            str(RULE_FETCH_MAX_TIME_SECONDS),
            "--user-agent",
            user_agent,
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=RULE_FETCH_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or f"curl exited with status {result.returncode}"
        raise RuntimeError(f"Failed to fetch rule source: {url} ({stderr})")
    return result.stdout


def _fetch_text(url: str, user_agent: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            curl_result = _fetch_text_with_curl(url, user_agent)
            if curl_result is not None:
                return curl_result
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except (RuntimeError, subprocess.TimeoutExpired, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch rule source after retries: {url}") from last_error


def _load_rule_source(
    output: RuleOutput,
    *,
    user_agent: str,
    project_root: Path,
    destination: Path,
) -> RuleSourceContent:
    if output.source_file:
        return RuleSourceContent(
            text=(project_root / output.source_file).read_text(encoding="utf-8"),
            status="local",
        )
    if not output.source_url:
        raise ValueError(f"Rule output must define source_url or source_file: {output.path}")
    try:
        return RuleSourceContent(text=_fetch_text(output.source_url, user_agent), status="fetched")
    except RuntimeError as exc:
        if destination.exists():
            cached = destination.read_text(encoding="utf-8")
            if cached.strip():
                return RuleSourceContent(
                    text=cached if cached.endswith("\n") else cached + "\n",
                    status="cached_fallback",
                    error=str(exc),
                    already_rendered=True,
                )
        raise


def _convert_metacubex_domain_yaml_to_shadowrocket(content: str) -> str:
    data = yaml.safe_load(content)
    payload = data.get("payload", [])
    lines: list[str] = []
    for raw in payload:
        item = str(raw).strip()
        if not item:
            continue
        if item.startswith("full:"):
            lines.append(f"DOMAIN,{item.removeprefix('full:')}")
        elif item.startswith("keyword:"):
            lines.append(f"DOMAIN-KEYWORD,{item.removeprefix('keyword:')}")
        elif item.startswith("regexp:"):
            lines.append(f"DOMAIN-REGEX,{item.removeprefix('regexp:')}")
        elif item.startswith("domain:"):
            lines.append(f"DOMAIN-SUFFIX,{item.removeprefix('domain:')}")
        elif item.startswith("+."):
            lines.append(f"DOMAIN-SUFFIX,{item.removeprefix('+.')}")
        elif item.startswith("."):
            lines.append(f"DOMAIN-SUFFIX,{item.removeprefix('.')}")
        else:
            lines.append(f"DOMAIN-SUFFIX,{item}")
    return "\n".join(lines) + "\n"


def _convert_metacubex_ip_yaml_to_shadowrocket(content: str) -> str:
    data = yaml.safe_load(content)
    payload = data.get("payload", [])
    lines: list[str] = []
    for raw in payload:
        item = str(raw).strip()
        if not item:
            continue
        prefix = "IP-CIDR6" if ":" in item else "IP-CIDR"
        lines.append(f"{prefix},{item}")
    return "\n".join(lines) + "\n"


def _convert_clash_classical_non_ip(content: str) -> str:
    lines = [line for line in payload_lines_from_content(content) if not is_ip_rule(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def _convert_clash_classical_domain(content: str) -> str:
    lines = [line for line in payload_lines_from_content(content) if is_domain_rule(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def _convert_clash_classical_ip(content: str) -> str:
    lines = [line for line in payload_lines_from_content(content) if is_ip_rule(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def _transform_content(content: str, output: RuleOutput) -> str:
    if output.transform == "metacubex_domain_to_shadowrocket":
        return _convert_metacubex_domain_yaml_to_shadowrocket(content)
    if output.transform == "metacubex_ipcidr_to_shadowrocket":
        return _convert_metacubex_ip_yaml_to_shadowrocket(content)
    if output.transform == "clash_classical_non_ip":
        return _convert_clash_classical_non_ip(content)
    if output.transform == "clash_classical_domain":
        return _convert_clash_classical_domain(content)
    if output.transform == "clash_classical_ip":
        return _convert_clash_classical_ip(content)
    return content if content.endswith("\n") else content + "\n"


def build_rules(config: ProjectConfig, output_root: Path, project_root: Path | None = None) -> dict[str, list[BuiltRule]]:
    source_root = project_root or Path.cwd()
    manifest: dict[str, list[BuiltRule]] = {"mihomo": [], "shadowrocket": []}
    for rule in config.rules:
        for client_name, output in rule.outputs.items():
            destination = output_root / output.path
            source = _load_rule_source(
                output,
                user_agent=config.user_agent,
                project_root=source_root,
                destination=destination,
            )
            rendered = source.text if source.already_rendered else _transform_content(source.text, output)
            if source.status == "cached_fallback":
                print(
                    f"Warning: rule source {rule.rule_id}/{client_name} fetch failed; "
                    f"using cached {destination}: {source.error}",
                    file=sys.stderr,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
            manifest[client_name].append(
                BuiltRule(
                    rule_id=rule.rule_id,
                    client=client_name,
                    policy=rule.policy,
                    path=output.path,
                    source_url=output.source_url or output.source_file or "",
                    behavior=output.behavior,
                    format=output.format,
                    source_status=source.status,
                    source_error=source.error,
                )
            )
    return manifest


def rule_source_status_report(manifest: dict[str, list[BuiltRule]]) -> dict[str, object]:
    counts: dict[str, int] = {}
    entries: list[dict[str, object]] = []
    cached_fallbacks: list[dict[str, object]] = []
    for client, items in manifest.items():
        for item in items:
            counts[item.source_status] = counts.get(item.source_status, 0) + 1
            entry = {
                "client": client,
                "rule_id": item.rule_id,
                "path": item.path,
                "source_url": item.source_url,
                "source_status": item.source_status,
                **({"source_error": item.source_error} if item.source_error else {}),
            }
            entries.append(entry)
            if item.source_status == "cached_fallback":
                cached_fallbacks.append(entry)
    return {
        "total": sum(counts.values()),
        "counts": dict(sorted(counts.items())),
        "cached_fallbacks": cached_fallbacks,
        "entries": entries,
    }


def format_rule_source_summary(manifest: dict[str, list[BuiltRule]]) -> str:
    report = rule_source_status_report(manifest)
    counts = report["counts"]
    if not isinstance(counts, dict):
        return "Rule sources: unavailable"
    parts = [f"{status}={count}" for status, count in counts.items()]
    return "Rule sources: " + ", ".join(parts)


def write_rule_source_status(manifest: dict[str, list[BuiltRule]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(rule_source_status_report(manifest), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_rule_manifest(manifest: dict[str, list[BuiltRule]], output_path: Path) -> None:
    payload = {
        client: [
            {
                "rule_id": item.rule_id,
                "client": item.client,
                "policy": item.policy,
                "path": item.path,
                "source_url": item.source_url,
                "behavior": item.behavior,
                "format": item.format,
                "source_status": item.source_status,
                **({"source_error": item.source_error} if item.source_error else {}),
            }
            for item in items
        ]
        for client, items in manifest.items()
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _audit_rule_file(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    lines = payload_lines_from_content(content)
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "line_count": len(lines),
        "domain_count": sum(1 for line in lines if is_domain_rule(line)),
        "ip_count": sum(1 for line in lines if is_ip_rule(line)),
        "process_count": sum(1 for line in lines if is_process_rule(line)),
        "sha256": sha256,
    }


def write_rule_audit(manifest: dict[str, list[BuiltRule]], output_root: Path, output_path: Path) -> None:
    entries: list[dict[str, object]] = []
    for client, items in manifest.items():
        for item in items:
            path = output_root / item.path
            audit = _audit_rule_file(path)
            entries.append(
                {
                    "rule_id": item.rule_id,
                    "client": client,
                    "path": item.path,
                    "behavior": item.behavior,
                    "format": item.format,
                    "source_status": item.source_status,
                    **({"source_error": item.source_error} if item.source_error else {}),
                    **audit,
                }
            )
    payload = {"rules": entries}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
