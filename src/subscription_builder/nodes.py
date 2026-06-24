from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time
from typing import Iterable
import urllib.error
from urllib.parse import urlparse
import urllib.request

import yaml

from .models import ProxyNode


@dataclass(slots=True)
class FetchedSubscription:
    text: str
    userinfo: dict[str, int]


@dataclass(slots=True)
class NodeSourceResult:
    source_id: str
    label: str
    group_policy: str
    nodes: list[ProxyNode]
    userinfo: dict[str, int]
    metadata: dict[str, object]


def _parse_subscription_userinfo(value: str | None) -> dict[str, int]:
    if not value:
        return {}
    parsed: dict[str, int] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key in {"upload", "download", "total", "expire"}:
            try:
                parsed[key] = int(raw_value)
            except ValueError:
                continue
    return parsed


def fetch_url_text(url: str, user_agent: str) -> str:
    return fetch_subscription(url, user_agent).text


def _safe_url_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or parsed.scheme or "subscription"


def _fetch_error_summary(error: Exception | None) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code}"
    if isinstance(error, urllib.error.URLError):
        return str(error.reason)
    if error is None:
        return "unknown error"
    return error.__class__.__name__


def fetch_subscription(url: str, user_agent: str) -> FetchedSubscription:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return FetchedSubscription(
                    text=response.read().decode("utf-8", errors="replace"),
                    userinfo=_parse_subscription_userinfo(response.headers.get("subscription-userinfo")),
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(
        f"Failed to fetch upstream subscription after retries: {_safe_url_label(url)} ({_fetch_error_summary(last_error)})"
    ) from None


def decode_subscription_payload(raw_text: str) -> str:
    candidate = raw_text.strip()
    if candidate.startswith("proxies:") or "\nproxies:" in candidate:
        return candidate
    if "://" in candidate:
        return candidate
    try:
        decoded = base64.b64decode(candidate + "=" * (-len(candidate) % 4)).decode("utf-8")
    except Exception:
        return raw_text
    return decoded.strip() or raw_text


def split_links(payload: str) -> list[str]:
    lines = [line.strip() for line in payload.replace("\r", "\n").split("\n")]
    return [line for line in lines if line and "://" in line]


def _is_loopback_metadata_proxy(payload: dict[str, object]) -> bool:
    server = str(payload.get("server", ""))
    return server in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _parse_nodes_payload(payload: str) -> list[ProxyNode]:
    try:
        decoded = yaml.safe_load(payload)
    except yaml.YAMLError:
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("proxies"), list):
        nodes = []
        for item in decoded["proxies"]:
            if not isinstance(item, dict) or _is_loopback_metadata_proxy(item):
                continue
            try:
                nodes.append(ProxyNode.from_mihomo_proxy(item))
            except (KeyError, TypeError, ValueError):
                continue
        return nodes

    links = split_links(payload)
    if links:
        nodes: list[ProxyNode] = []
        for link in links:
            try:
                nodes.append(ProxyNode.from_uri(link))
            except ValueError:
                continue
        return nodes

    return []


def parse_nodes_text(raw_text: str) -> list[ProxyNode]:
    payload = decode_subscription_payload(raw_text)
    nodes = _parse_nodes_payload(payload)
    if not nodes:
        raise ValueError("No supported proxy nodes were parsed from the upstream subscription.")
    return nodes


def fetch_and_parse_nodes(url: str, user_agent: str) -> list[ProxyNode]:
    fetched = fetch_subscription(url, user_agent)
    return parse_nodes_text(fetched.text)


def filter_nodes_by_name(
    nodes: Iterable[ProxyNode],
    *,
    include_name_contains: Iterable[str] | None = None,
    include_name_regex: str | None = None,
) -> list[ProxyNode]:
    contains = [item for item in (include_name_contains or []) if item]
    pattern = re.compile(include_name_regex) if include_name_regex else None
    selected: list[ProxyNode] = []
    for node in nodes:
        if contains and not any(token in node.name for token in contains):
            continue
        if pattern and not pattern.search(node.name):
            continue
        selected.append(node)
    return selected


def parse_node_source_text(
    *,
    raw_text: str,
    source_id: str,
    label: str,
    group_policy: str,
    include_name_contains: Iterable[str] | None = None,
    include_name_regex: str | None = None,
    name_override: str | None = None,
    prefix_label: bool = True,
    userinfo: dict[str, int] | None = None,
    metadata: dict[str, object] | None = None,
) -> NodeSourceResult:
    parsed_nodes = filter_nodes_by_name(
        parse_nodes_text(raw_text),
        include_name_contains=include_name_contains,
        include_name_regex=include_name_regex,
    )
    nodes = []
    for node in parsed_nodes:
        if name_override:
            node.name = name_override.strip()
            node.raw_uri = None
        nodes.append(
            node.apply_source(
                source_id=source_id,
                source_label=label,
                group_policy=group_policy,
                prefix_label=prefix_label,
            )
        )
    return NodeSourceResult(
        source_id=source_id,
        label=label,
        group_policy=group_policy,
        nodes=nodes,
        userinfo=dict(userinfo or {}),
        metadata=dict(metadata or {}),
    )


def fetch_and_parse_node_source(
    *,
    url: str,
    user_agent: str,
    source_id: str,
    label: str,
    group_policy: str,
    include_name_contains: Iterable[str] | None = None,
    include_name_regex: str | None = None,
    name_override: str | None = None,
    prefix_label: bool = True,
    metadata: dict[str, object] | None = None,
) -> NodeSourceResult:
    fetched = fetch_subscription(url, user_agent)
    return parse_node_source_text(
        raw_text=fetched.text,
        source_id=source_id,
        label=label,
        group_policy=group_policy,
        include_name_contains=include_name_contains,
        include_name_regex=include_name_regex,
        name_override=name_override,
        prefix_label=prefix_label,
        userinfo=fetched.userinfo,
        metadata=metadata,
    )


def read_nodes_json(input_path: Path) -> list[ProxyNode]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(f"Cached nodes file must contain a list: {input_path}")
    nodes: list[ProxyNode] = []
    for item in data:
        if not isinstance(item, dict):
            raise TypeError(f"Cached node entries must be mappings: {input_path}")
        nodes.append(ProxyNode(**item))
    if not nodes:
        raise ValueError(f"Cached nodes file has no nodes: {input_path}")
    return nodes


def write_nodes_json(nodes: Iterable[ProxyNode], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(node) for node in nodes]
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_shadowrocket_uri_artifacts(nodes: Iterable[ProxyNode], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    supported_nodes = [node for node in nodes if node.supports_shadowrocket_config()]
    uri_text = "\n".join(node.to_uri() for node in supported_nodes) + "\n"
    (output_dir / "shadowrocket-uris.txt").write_text(uri_text, encoding="utf-8")
    encoded = base64.b64encode(uri_text.encode("utf-8")).decode("ascii")
    (output_dir / "shadowrocket-subscription.txt").write_text(encoded + "\n", encoding="utf-8")


def _node_sources_from_nodes(nodes: Iterable[ProxyNode]) -> dict[str, dict[str, object]]:
    sources: dict[str, dict[str, object]] = {}
    for node in nodes:
        source = sources.setdefault(
            node.source_id,
            {
                "id": node.source_id,
                "label": node.source_label,
                "group_policy": node.source_group_policy,
                "node_count": 0,
                "mihomo_node_count": 0,
                "shadowrocket_node_count": 0,
            },
        )
        source["node_count"] = int(source["node_count"]) + 1
        source["mihomo_node_count"] = int(source["mihomo_node_count"]) + 1
        if node.supports_shadowrocket_config():
            source["shadowrocket_node_count"] = int(source["shadowrocket_node_count"]) + 1
    return sources


def write_node_source_audit(
    *,
    nodes: Iterable[ProxyNode],
    source_results: Iterable[NodeSourceResult],
    output_path: Path,
) -> dict[str, object]:
    sources = _node_sources_from_nodes(nodes)
    for result in source_results:
        source = sources.setdefault(
            result.source_id,
            {
                "id": result.source_id,
                "label": result.label,
                "group_policy": result.group_policy,
                "node_count": 0,
                "mihomo_node_count": 0,
                "shadowrocket_node_count": 0,
            },
        )
        source["label"] = result.label
        source["group_policy"] = result.group_policy
        if result.userinfo:
            source["subscription_userinfo"] = result.userinfo
        if result.metadata:
            source["metadata"] = result.metadata

    payload = {"sources": list(sources.values())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload
