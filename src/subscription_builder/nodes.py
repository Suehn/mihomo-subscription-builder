from __future__ import annotations

import base64
from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable
import urllib.request

from .models import ProxyNode


def fetch_url_text(url: str, user_agent: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def decode_subscription_payload(raw_text: str) -> str:
    candidate = raw_text.strip()
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


def fetch_and_parse_nodes(url: str, user_agent: str) -> list[ProxyNode]:
    raw_text = fetch_url_text(url, user_agent)
    payload = decode_subscription_payload(raw_text)
    links = split_links(payload)
    nodes: list[ProxyNode] = []
    for link in links:
        try:
            nodes.append(ProxyNode.from_uri(link))
        except ValueError:
            continue
    if not nodes:
        raise ValueError("No supported proxy nodes were parsed from the upstream subscription.")
    return nodes


def write_nodes_json(nodes: Iterable[ProxyNode], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(node) for node in nodes]
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_shadowrocket_uri_artifacts(nodes: Iterable[ProxyNode], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    uri_text = "\n".join(node.to_uri() for node in nodes) + "\n"
    (output_dir / "shadowrocket-uris.txt").write_text(uri_text, encoding="utf-8")
    encoded = base64.b64encode(uri_text.encode("utf-8")).decode("ascii")
    (output_dir / "shadowrocket-subscription.txt").write_text(encoded + "\n", encoding="utf-8")

