from __future__ import annotations

import base64

from subscription_builder.models import ProxyNode
from subscription_builder.nodes import decode_subscription_payload, split_links


def test_decode_subscription_payload_accepts_base64_text() -> None:
    raw = "vless://foo.example:443#A\nvless://bar.example:443#B\n"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    assert decode_subscription_payload(encoded) == raw.strip()


def test_decode_subscription_payload_preserves_raw_links() -> None:
    payload = "vless://foo.example:443#A"
    assert decode_subscription_payload(payload) == payload


def test_split_links_filters_blank_lines() -> None:
    payload = "vless://foo.example:443#A\r\n\r\nvmess://abc\nnot-a-link\n"
    assert split_links(payload) == ["vless://foo.example:443#A", "vmess://abc"]


def test_parse_vless_reality_node() -> None:
    uri = (
        "vless://00000000-0000-4000-8000-000000000001@proxy.example.test:443"
        "?security=reality&type=tcp&sni=example.com&fp=chrome&pbk=0123456789abcdefghijklmnopqrstuvwxyzABCDE"
        "&sid=123456#example-node"
    )
    node = ProxyNode.from_uri(uri)
    assert node.type == "vless"
    assert node.server == "proxy.example.test"
    assert node.port == 443
    assert node.uuid == "00000000-0000-4000-8000-000000000001"
    assert node.tls is True
    assert node.servername == "example.com"
    assert node.client_fingerprint == "chrome"
    assert node.reality_public_key == "0123456789abcdefghijklmnopqrstuvwxyzABCDE"
    assert node.reality_short_id == "123456"


def test_vless_node_renders_for_mihomo() -> None:
    uri = (
        "vless://00000000-0000-4000-8000-000000000001@proxy.example.test:443"
        "?security=reality&type=tcp&sni=example.com&fp=chrome&pbk=0123456789abcdefghijklmnopqrstuvwxyzABCDE"
        "&sid=123456#example-node"
    )
    node = ProxyNode.from_uri(uri)
    rendered = node.to_mihomo_proxy()
    assert rendered["type"] == "vless"
    assert rendered["server"] == "proxy.example.test"
    assert rendered["uuid"] == "00000000-0000-4000-8000-000000000001"
    assert rendered["tls"] is True
    assert rendered["reality-opts"] == {
        "public-key": "0123456789abcdefghijklmnopqrstuvwxyzABCDE",
        "short-id": "123456",
    }
