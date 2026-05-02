from __future__ import annotations

from dataclasses import dataclass
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


def _transform_content(content: str, output: RuleOutput) -> str:
    if output.transform == "metacubex_domain_to_shadowrocket":
        return _convert_metacubex_domain_yaml_to_shadowrocket(content)
    if output.transform == "metacubex_ipcidr_to_shadowrocket":
        return _convert_metacubex_ip_yaml_to_shadowrocket(content)
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
