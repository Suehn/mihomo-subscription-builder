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
        "vless://abcfaa41-a869-473d-a6fa-f792c0f23b61@vms.217777.xyz:26767"
        "?security=reality&type=tcp&sni=aws.amazon.com&fp=chrome&pbk=Mfb2huSHHeLHeaaAapwJx_gLqaiLRUzMuvvSPVJpbkM"
        "&sid=b4f871#Suehn-Suehn-293.31GB%F0%9F%93%8A"
    )
    node = ProxyNode.from_uri(uri)
    assert node.type == "vless"
    assert node.server == "vms.217777.xyz"
    assert node.port == 26767
    assert node.uuid == "abcfaa41-a869-473d-a6fa-f792c0f23b61"
    assert node.tls is True
    assert node.servername == "aws.amazon.com"
    assert node.client_fingerprint == "chrome"
    assert node.reality_public_key == "Mfb2huSHHeLHeaaAapwJx_gLqaiLRUzMuvvSPVJpbkM"
    assert node.reality_short_id == "b4f871"


def test_vless_node_renders_for_mihomo() -> None:
    uri = (
        "vless://abcfaa41-a869-473d-a6fa-f792c0f23b61@vms.217777.xyz:26767"
        "?security=reality&type=tcp&sni=aws.amazon.com&fp=chrome&pbk=Mfb2huSHHeLHeaaAapwJx_gLqaiLRUzMuvvSPVJpbkM"
        "&sid=b4f871#Suehn"
    )
    node = ProxyNode.from_uri(uri)
    rendered = node.to_mihomo_proxy()
    assert rendered["type"] == "vless"
    assert rendered["server"] == "vms.217777.xyz"
    assert rendered["uuid"] == "abcfaa41-a869-473d-a6fa-f792c0f23b61"
    assert rendered["tls"] is True
    assert rendered["reality-opts"] == {
        "public-key": "Mfb2huSHHeLHeaaAapwJx_gLqaiLRUzMuvvSPVJpbkM",
        "short-id": "b4f871",
    }
