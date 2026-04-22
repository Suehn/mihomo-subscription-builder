from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse


def _clean_name(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed or "proxy"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in (part.strip() for part in value.split(",")) if item]


@dataclass(slots=True)
class ProxyNode:
    name: str
    type: str
    server: str
    port: int
    network: str = "tcp"
    tls: bool = False
    servername: str | None = None
    client_fingerprint: str | None = None
    skip_cert_verify: bool = False
    udp: bool = True
    fast_open: bool = False
    uuid: str | None = None
    password: str | None = None
    flow: str | None = None
    reality_public_key: str | None = None
    reality_short_id: str | None = None
    reality_spider_x: str | None = None
    ws_path: str | None = None
    ws_host: str | None = None
    service_name: str | None = None
    http_path: str | None = None
    http_host: str | None = None
    alpn: list[str] = field(default_factory=list)
    raw_uri: str | None = None

    @classmethod
    def from_uri(cls, uri: str) -> "ProxyNode":
        if uri.startswith("vless://"):
            return cls._from_vless_uri(uri)
        if uri.startswith("trojan://"):
            return cls._from_trojan_uri(uri)
        if uri.startswith("vmess://"):
            return cls._from_vmess_uri(uri)
        if uri.startswith("ss://"):
            return cls._from_ss_uri(uri)
        raise ValueError(f"Unsupported proxy URI: {uri[:32]}...")

    @classmethod
    def _from_vless_uri(cls, uri: str) -> "ProxyNode":
        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
        security = query.get("security", ["none"])[0]
        network = query.get("type", ["tcp"])[0] or "tcp"
        host = parsed.hostname or ""
        ws_host = query.get("host", [None])[0]
        ws_path = query.get("path", [None])[0]
        service_name = query.get("serviceName", [None])[0]
        http_path = query.get("path", [None])[0] if network == "http" else None
        http_host = query.get("host", [None])[0] if network == "http" else None
        return cls(
            name=_clean_name(unquote(parsed.fragment or "vless")),
            type="vless",
            server=host,
            port=parsed.port or 443,
            uuid=unquote(parsed.username or ""),
            network=network,
            tls=security in {"tls", "reality"},
            servername=query.get("sni", [query.get("peer", [None])[0]])[0],
            client_fingerprint=query.get("fp", [None])[0],
            skip_cert_verify=query.get("allowInsecure", ["0"])[0] in {"1", "true"},
            flow=query.get("flow", [None])[0],
            reality_public_key=query.get("pbk", [None])[0],
            reality_short_id=query.get("sid", [None])[0],
            reality_spider_x=query.get("spx", [None])[0],
            ws_path=ws_path,
            ws_host=ws_host,
            service_name=service_name,
            http_path=http_path,
            http_host=http_host,
            alpn=_split_csv(query.get("alpn", [None])[0]),
            raw_uri=uri,
        )

    @classmethod
    def _from_trojan_uri(cls, uri: str) -> "ProxyNode":
        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
        security = query.get("security", ["tls"])[0]
        return cls(
            name=_clean_name(unquote(parsed.fragment or "trojan")),
            type="trojan",
            server=parsed.hostname or "",
            port=parsed.port or 443,
            password=unquote(parsed.username or ""),
            network=query.get("type", ["tcp"])[0] or "tcp",
            tls=security in {"tls", "reality"},
            servername=query.get("sni", [None])[0],
            client_fingerprint=query.get("fp", [None])[0],
            skip_cert_verify=query.get("allowInsecure", ["0"])[0] in {"1", "true"},
            reality_public_key=query.get("pbk", [None])[0],
            reality_short_id=query.get("sid", [None])[0],
            reality_spider_x=query.get("spx", [None])[0],
            ws_path=query.get("path", [None])[0],
            ws_host=query.get("host", [None])[0],
            service_name=query.get("serviceName", [None])[0],
            alpn=_split_csv(query.get("alpn", [None])[0]),
            raw_uri=uri,
        )

    @classmethod
    def _from_vmess_uri(cls, uri: str) -> "ProxyNode":
        payload = uri.removeprefix("vmess://")
        decoded = base64.b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
        data = json.loads(decoded)
        tls_value = data.get("tls", "")
        network = data.get("net", "tcp") or "tcp"
        return cls(
            name=_clean_name(data.get("ps", "vmess")),
            type="vmess",
            server=data["add"],
            port=int(data["port"]),
            uuid=data["id"],
            network=network,
            tls=tls_value in {"tls", "1", True},
            servername=data.get("sni") or data.get("host"),
            client_fingerprint=data.get("fp"),
            ws_path=data.get("path"),
            ws_host=data.get("host"),
            service_name=data.get("path") if network == "grpc" else None,
            raw_uri=uri,
        )

    @classmethod
    def _from_ss_uri(cls, uri: str) -> "ProxyNode":
        parsed = urlparse(uri)
        tag = _clean_name(unquote(parsed.fragment or "ss"))
        if parsed.username:
            userinfo = unquote(parsed.username)
        else:
            userinfo = base64.b64decode(parsed.netloc.split("@", 1)[0] + "=" * 4).decode("utf-8")
        method, password = userinfo.split(":", 1)
        return cls(
            name=tag,
            type="ss",
            server=parsed.hostname or "",
            port=parsed.port or 8388,
            password=password,
            network="tcp",
            raw_uri=uri,
        )

    def to_mihomo_proxy(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "type": self.type,
            "server": self.server,
            "port": self.port,
            "udp": self.udp,
        }
        if self.type in {"vless", "vmess"} and self.uuid:
            data["uuid"] = self.uuid
        if self.type in {"trojan", "ss"} and self.password:
            data["password"] = self.password
        if self.type == "ss":
            data["cipher"] = "auto"
        if self.tls:
            data["tls"] = True
        if self.servername:
            data["servername"] = self.servername
        if self.client_fingerprint:
            data["client-fingerprint"] = self.client_fingerprint
        if self.skip_cert_verify:
            data["skip-cert-verify"] = True
        if self.flow:
            data["flow"] = self.flow
        if self.network:
            data["network"] = self.network
        if self.fast_open:
            data["tfo"] = True
        if self.alpn:
            data["alpn"] = self.alpn
        if self.reality_public_key:
            data["reality-opts"] = {"public-key": self.reality_public_key}
            if self.reality_short_id:
                data["reality-opts"]["short-id"] = self.reality_short_id
        if self.network == "ws":
            ws_opts: dict[str, object] = {"path": self.ws_path or "/"}
            if self.ws_host:
                ws_opts["headers"] = {"Host": self.ws_host}
            data["ws-opts"] = ws_opts
        if self.network == "grpc" and self.service_name:
            data["grpc-opts"] = {"grpc-service-name": self.service_name}
        if self.network == "http":
            http_opts: dict[str, object] = {}
            if self.http_path:
                http_opts["path"] = [self.http_path]
            if self.http_host:
                http_opts["headers"] = {"Host": [self.http_host]}
            if http_opts:
                data["http-opts"] = http_opts
        return data

    def to_uri(self) -> str:
        if self.raw_uri:
            return self.raw_uri
        raise ValueError(f"Raw URI is unavailable for {self.name}")

    def to_shadowrocket_proxy_line(self) -> str:
        if self.type == "vless":
            parts = [
                f"{self.name}=vless,{self.server},{self.port}",
                f"password={self.uuid}",
                f"udp={1 if self.udp else 0}",
                f"tfo={1 if self.fast_open else 0}",
            ]
            if self.tls:
                parts.append("tls=true")
            if self.servername:
                parts.append(f"peer={self.servername}")
            if self.flow == "xtls-rprx-vision":
                parts.append("xtls=2")
            if self.client_fingerprint:
                parts.append(f"client-fingerprint={self.client_fingerprint}")
            if self.reality_public_key:
                parts.append(f"publicKey={self.reality_public_key}")
            if self.reality_short_id:
                parts.append(f"shortId={self.reality_short_id}")
            if self.network == "ws":
                parts.append("obfs=websocket")
                if self.ws_host:
                    parts.append(f"obfs-host={self.ws_host}")
                if self.ws_path:
                    parts.append(f"path={self.ws_path}")
            elif self.network == "grpc":
                parts.append("obfs=grpc")
                if self.service_name:
                    parts.append(f"path={self.service_name}")
            else:
                parts.append("obfs=none")
            return ",".join(parts)
        if self.type == "trojan":
            parts = [
                f"{self.name}=trojan,{self.server},{self.port}",
                f"password={self.password}",
                f"udp={1 if self.udp else 0}",
            ]
            if self.servername:
                parts.append(f"peer={self.servername}")
            if self.skip_cert_verify:
                parts.append("allowInsecure=1")
            return ",".join(parts)
        if self.type == "ss":
            return f"{self.name}=ss,{self.server},{self.port},password={self.password},method=aes-256-gcm"
        if self.type == "vmess":
            parts = [
                f"{self.name}=vmess,{self.server},{self.port}",
                f"password={self.uuid}",
                "method=auto",
                "udp=1",
                f"tfo={1 if self.fast_open else 0}",
            ]
            if self.tls:
                parts.append("tls=true")
            if self.servername:
                parts.append(f"peer={self.servername}")
            if self.network == "ws":
                parts.append("obfs=websocket")
                if self.ws_host:
                    parts.append(f"obfs-host={self.ws_host}")
                if self.ws_path:
                    parts.append(f"path={self.ws_path}")
            else:
                parts.append("obfs=none")
            return ",".join(parts)
        raise ValueError(f"Shadowrocket local line is unsupported for proxy type: {self.type}")

