from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import time
from typing import Iterable
import urllib.error
import urllib.request

import yaml

from .config import ProjectConfig, RuleOutput, RuleSpec


@dataclass(slots=True)
class BuiltRule:
    rule_id: str
    client: str
    policy: str
    path: str
    source_url: str
    behavior: str | None
    format: str | None


def _fetch_text(url: str, user_agent: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch rule source after retries: {url}") from last_error


def _load_source_text(output: RuleOutput, user_agent: str, project_root: Path) -> str:
    if output.source_file:
        return (project_root / output.source_file).read_text(encoding="utf-8")
    if output.source_url:
        return _fetch_text(output.source_url, user_agent)
    raise ValueError(f"Rule output must define source_url or source_file: {output.path}")


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


def _payload_lines_from_content(content: str) -> list[str]:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("payload"), list):
        return [str(item).strip() for item in data["payload"] if str(item).strip()]
    return [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]


IP_RULE_KINDS = {"IP-CIDR", "IP-CIDR6", "IP-ASN", "GEOIP"}
PROCESS_RULE_KINDS = {"PROCESS-NAME", "PROCESS-PATH", "PROCESS-NAME-REGEX"}
DOMAIN_RULE_KINDS = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-REGEX",
    "GEOSITE",
    "HOST",
    "HOST-SUFFIX",
    "HOST-KEYWORD",
    "URL-REGEX",
}


def _rule_kind(line: str) -> str:
    if "," in line:
        return line.split(",", 1)[0].strip()
    try:
        ipaddress.ip_network(line, strict=False)
        return "IP-CIDR6" if ":" in line else "IP-CIDR"
    except ValueError:
        pass
    if line.startswith(("+.", ".")) or any(ch.isalpha() for ch in line):
        return "DOMAIN-LIKE"
    return "UNKNOWN"


def _is_ip_rule(line: str) -> bool:
    return _rule_kind(line) in IP_RULE_KINDS


def _is_process_rule(line: str) -> bool:
    return _rule_kind(line) in PROCESS_RULE_KINDS


def _is_domain_rule(line: str) -> bool:
    return _rule_kind(line) in DOMAIN_RULE_KINDS or _rule_kind(line) == "DOMAIN-LIKE"


def _convert_clash_classical_non_ip(content: str) -> str:
    lines = [line for line in _payload_lines_from_content(content) if not _is_ip_rule(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def _convert_clash_classical_domain(content: str) -> str:
    lines = [line for line in _payload_lines_from_content(content) if _is_domain_rule(line)]
    return "\n".join(lines) + ("\n" if lines else "")


def _convert_clash_classical_ip(content: str) -> str:
    lines = [line for line in _payload_lines_from_content(content) if _is_ip_rule(line)]
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
            content = _load_source_text(output, config.user_agent, source_root)
            rendered = _transform_content(content, output)
            destination = output_root / output.path
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
                )
            )
    return manifest


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
            }
            for item in items
        ]
        for client, items in manifest.items()
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _audit_rule_file(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    lines = _payload_lines_from_content(content)
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "line_count": len(lines),
        "domain_count": sum(1 for line in lines if _is_domain_rule(line)),
        "ip_count": sum(1 for line in lines if _is_ip_rule(line)),
        "process_count": sum(1 for line in lines if _is_process_rule(line)),
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
                    **audit,
                }
            )
    payload = {"rules": entries}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
