from __future__ import annotations

import base64

import pytest

from subscription_builder.models import ProxyNode
from subscription_builder.nodes import (
    FetchedSubscription,
    NodeSourceResult,
    decode_subscription_payload,
    fetch_and_parse_node_source,
    parse_nodes_text,
    split_links,
    write_node_source_audit,
)


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


def test_fetch_subscription_error_redacts_secret_url(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib_error.HTTPError(
            url="https://example.test/sub?token=secret-token",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=None,
        )

    from urllib import error as urllib_error

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        fetch_and_parse_node_source(
            url="https://example.test/sub?token=secret-token",
            user_agent="test",
            source_id="test",
            label="Test",
            group_policy="default",
        )

    message = str(exc_info.value)
    assert "example.test" in message
    assert "secret-token" not in message
    assert "token=" not in message


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


def test_parse_mihomo_subscription_filters_metadata_and_keeps_supported_nodes() -> None:
    payload = """
proxies:
  - { name: "剩余流量：5000 GB", type: ss, server: 127.0.0.1, port: 127, cipher: aes-256-gcm, password: meta }
  - { name: "Pin US CDN", type: vless, server: 104.18.82.177, port: 443, uuid: 00000000-0000-4000-8000-000000000001, tls: true, network: ws, servername: edge.example.test, ws-opts: { path: /pinche, headers: { Host: edge.example.test } } }
  - { name: "Pin US Hysteria2", type: hysteria2, server: 23.94.37.72, port: 49394, password: secret, sni: zhuijumi.tv, skip-cert-verify: true, up: 100, down: 100 }
""".strip()

    nodes = parse_nodes_text(payload)

    assert [node.name for node in nodes] == ["Pin US CDN", "Pin US Hysteria2"]
    assert [node.type for node in nodes] == ["vless", "hysteria2"]
    assert nodes[0].to_mihomo_proxy()["ws-opts"] == {
        "path": "/pinche",
        "headers": {"Host": "edge.example.test"},
    }
    assert nodes[1].to_mihomo_proxy()["sni"] == "zhuijumi.tv"
    assert nodes[1].to_mihomo_proxy()["up"] == 100


def test_node_source_can_import_only_home_broadband_nodes(monkeypatch) -> None:
    payload = """
proxies:
  - { name: "台湾 09 家宽", type: vless, server: tw09.example.test, port: 443, uuid: 00000000-0000-4000-8000-000000000009, tls: true }
  - { name: "台湾 10 普通", type: vless, server: tw10.example.test, port: 443, uuid: 00000000-0000-4000-8000-000000000010, tls: true }
  - { name: "日本 01 家宽", type: vless, server: jp01.example.test, port: 443, uuid: 00000000-0000-4000-8000-000000000011, tls: true }
""".strip()

    def fake_fetch_subscription(url: str, user_agent: str) -> FetchedSubscription:
        return FetchedSubscription(text=payload, userinfo={})

    monkeypatch.setattr("subscription_builder.nodes.fetch_subscription", fake_fetch_subscription)

    result = fetch_and_parse_node_source(
        url="https://example.test/mesl",
        user_agent="test",
        source_id="mesl",
        label="MESL",
        group_policy="manual_only",
        include_name_contains=["家宽"],
    )

    assert [node.name for node in result.nodes] == ["MESL · 台湾 09 家宽", "MESL · 日本 01 家宽"]
    assert all(node.source_group_policy == "manual_only" for node in result.nodes)


def test_write_node_source_audit_records_traffic_metadata(tmp_path) -> None:
    node = ProxyNode(name="pin", type="vless", server="proxy.example.test", port=443, uuid="id").apply_source(
        source_id="pinche",
        source_label="Pin-Che",
        group_policy="manual_only",
    )
    result = NodeSourceResult(
        source_id="pinche",
        label="Pin-Che",
        group_policy="manual_only",
        nodes=[node],
        userinfo={"upload": 10, "download": 20, "total": 100, "expire": 1815696000},
        metadata={"traffic_observed": "0.00B / 4.88TB", "expires_on": "2027-05-16"},
    )

    audit = write_node_source_audit(nodes=[node], source_results=[result], output_path=tmp_path / "node-sources.json")

    source = audit["sources"][0]
    assert source["label"] == "Pin-Che"
    assert source["group_policy"] == "manual_only"
    assert source["node_count"] == 1
    assert source["subscription_userinfo"]["total"] == 100
