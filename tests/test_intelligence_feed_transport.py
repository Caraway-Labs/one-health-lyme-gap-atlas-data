"""Pinned connection, bounded response and cache policy independent tests."""

from __future__ import annotations

import errno
import hashlib
import http.client
import ssl
import traceback
from dataclasses import replace
from typing import Any

import pytest
from test_intelligence_feed import FIXTURES, approved, definition, fetch_adapter

from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError
from lyme_gap_atlas_data.ingestion.intelligence_feed import (
    FeedCache,
    FeedResponse,
    _PinnedHTTPS,
    _request,
    _resolve,
    acquisition_context,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash


@pytest.mark.parametrize(
    "addresses",
    [
        ["93.184.216.34", "2606:4700:4700::1111", "8.8.8.8", "93.184.216.34"],
        ["2606:4700:4700::1111", "93.184.216.34", "2606:4700:4700::1111"],
        ["8.8.8.8", "93.184.216.34", "8.8.8.8"],
    ],
)
def test_dns_preserves_platform_address_order_and_deduplicates_once(
    monkeypatch: Any, addresses: list[str]
) -> None:
    calls = []

    def resolve(host: str, port: int) -> list[Any]:
        calls.append((host, port))
        return [(0, 0, 0, "", (address, port)) for address in addresses]

    monkeypatch.setattr("socket.getaddrinfo", resolve)
    assert _resolve("example.org", 2) == tuple(dict.fromkeys(addresses))
    assert calls == [("example.org", 443)]


def test_live_selection_uses_first_platform_candidate_without_alternative_retry(
    monkeypatch: Any,
) -> None:
    addresses = ["93.184.216.34", "2606:4700:4700::1111", "8.8.8.8"]
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port: [(0, 0, 0, "", (address, port)) for address in addresses],
    )
    record = approved()
    adapter, calls = fetch_adapter(record, [])
    adapter.resolve = _resolve

    def unreachable(*args: Any) -> FeedResponse:
        calls.append(args)
        raise AcquisitionError("FEED_NETWORK_UNREACHABLE", code="FEED_NETWORK_UNREACHABLE")

    adapter.request = unreachable
    with pytest.raises(AcquisitionError, match="FEED_NETWORK_UNREACHABLE"):
        adapter.acquire(definition(record))
    assert len(calls) == 1
    assert calls[0][1] == addresses[0]


@pytest.mark.parametrize("phase", ["connect", "request", "getresponse", "read"])
@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError("private transport value"), "FEED_TIMEOUT"),
        (ssl.SSLCertVerificationError("private transport value"), "FEED_TLS_VERIFICATION_FAILED"),
        (ssl.SSLError("private transport value"), "FEED_TLS_FAILED"),
        (ConnectionRefusedError("private transport value"), "FEED_CONNECTION_REFUSED"),
        (ConnectionResetError("private transport value"), "FEED_CONNECTION_RESET"),
        (BrokenPipeError("private transport value"), "FEED_CONNECTION_RESET"),
        (http.client.RemoteDisconnected("private transport value"), "FEED_HTTP_PROTOCOL_FAILED"),
        (http.client.IncompleteRead(b"private transport value", 100), "FEED_HTTP_PROTOCOL_FAILED"),
        (OSError(errno.ENETUNREACH, "private transport value"), "FEED_NETWORK_UNREACHABLE"),
        (OSError(errno.EHOSTUNREACH, "private transport value"), "FEED_NETWORK_UNREACHABLE"),
        (OSError(errno.EAFNOSUPPORT, "private transport value"), "FEED_NETWORK_UNREACHABLE"),
        (OSError("private transport value"), "FEED_NETWORK_FAILED"),
    ],
)
def test_transport_failure_codes_are_safe_and_never_retry(
    monkeypatch: Any, phase: str, error: Exception, code: str
) -> None:
    calls: list[str] = []

    class Connection:
        sock = None
        status = 200

        def __init__(self, host: str, ip: str, timeout: float) -> None:
            assert (host, ip, timeout) == ("example.org", "93.184.216.34", 2)
            calls.append("init")

        def fail_at(self, step: str) -> None:
            calls.append(step)
            if step == phase:
                raise error

        def connect(self) -> None:
            self.fail_at("connect")

        def request(self, method: str, path: str, headers: Any) -> None:
            self.fail_at("request")

        def getresponse(self) -> Connection:
            self.fail_at("getresponse")
            return self

        def getheaders(self) -> list[Any]:
            return []

        def read(self, budget: int) -> bytes:
            self.fail_at("read")
            return b""

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr("lyme_gap_atlas_data.ingestion.intelligence_feed._PinnedHTTPS", Connection)
    with pytest.raises(AcquisitionError) as caught:
        _request("https://example.org/feed.xml", "93.184.216.34", {}, 100, 2)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert "private transport value" not in "".join(traceback.format_exception(caught.value))
    assert calls.count("init") == calls.count("connect") == calls.count("close") == 1
    assert calls.count("request") <= 1


def test_https_socket_connects_to_verified_ip_with_original_tls_hostname(monkeypatch: Any) -> None:
    calls: list[Any] = []

    class Socket:
        def settimeout(self, timeout: float) -> None:
            assert 0 < timeout <= 2

        def close(self) -> None:
            pass

    raw = Socket()

    def connect(address: Any, timeout: Any) -> Socket:
        calls.append((address, timeout))
        return raw

    class Context:
        def wrap_socket(self, socket: Any, *, server_hostname: str) -> Socket:
            assert socket is raw and server_hostname == "example.org"
            return raw

    monkeypatch.setattr("socket.create_connection", connect)
    connection = _PinnedHTTPS("example.org", "93.184.216.34", 2.0)
    connection.tls_context = Context()
    connection.connect()
    assert calls == [(("93.184.216.34", 443), 2.0)]


@pytest.mark.parametrize(
    "headers,body,code",
    [
        ({"content-encoding": "gzip"}, b"compressed", "ENCODING_UNSUPPORTED"),
        ({"content-length": "101"}, b"", "TOO_LARGE"),
        ({}, b"x" * 101, "TOO_LARGE"),
    ],
)
def test_network_response_size_and_compression_are_bounded(
    monkeypatch: Any, headers: dict[str, str], body: bytes, code: str
) -> None:
    class Response:
        status = 200

        def getheaders(self) -> list[Any]:
            return list(headers.items())

        def read(self, budget: int) -> bytes:
            assert budget == 101
            return body

    class Connection:
        sock = None

        def __init__(self, host: str, ip: str, timeout: float) -> None:
            pass

        def connect(self) -> None:
            pass

        def request(self, method: str, path: str, headers: Any) -> None:
            assert method == "GET" and path == "/feed.xml?query=publisher"

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr("lyme_gap_atlas_data.ingestion.intelligence_feed._PinnedHTTPS", Connection)
    with pytest.raises(AcquisitionError, match=code):
        _request("https://example.org/feed.xml?query=publisher", "93.184.216.34", {}, 100, 2)


def test_cache_requires_retained_evidence_and_headers_cannot_inject_requests() -> None:
    record = approved()
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    cache = FeedCache(
        identity_hash(record), raw, "retained-artifact", "value\r\nAuthorization: secret"
    )
    cache = replace(
        cache,
        source_context=acquisition_context(
            definition(record),
            record,
            effective_url=record["fetch_location"],
            fetched_at="2026-09-30T15:00:00Z",
            artifact_sha256=hashlib.sha256(raw).hexdigest(),
            capture_mode="https",
        ),
    )
    adapter, calls = fetch_adapter(record, [], cache=cache)
    with pytest.raises(AcquisitionError, match="RETAINED_CACHE_REQUIRED"):
        adapter.acquire(definition(record))
    assert calls == []
    adapter.cache_allowed = lambda saved: True
    with pytest.raises(AcquisitionError, match="CACHE_HEADER_INVALID"):
        adapter.acquire(definition(record))
    assert calls == []


def test_validators_stay_private_and_redirected_validators_are_not_reused() -> None:
    record = approved()
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, _ = fetch_adapter(record, [FeedResponse(200, {"etag": '"version-1"'}, raw)])
    acquired = adapter.acquire(definition(record))
    assert acquired.payload["etag"] == '"version-1"'
    record["limits"]["maximum_redirects"] = 1
    adapter, _ = fetch_adapter(
        record,
        [
            FeedResponse(302, {"location": "/new.xml"}, b""),
            FeedResponse(200, {"etag": '"other-endpoint"'}, raw),
        ],
    )
    assert "etag" not in adapter.acquire(definition(record)).payload


def test_generic_scientific_writer_rejects_publication_items_before_connection() -> None:
    from lyme_gap_atlas_data.ingestion.runtime import SnowflakeStageEffects

    effects = SnowflakeStageEffects(connection_factory=lambda: pytest.fail("must not connect"))
    with pytest.raises(PermissionError, match="INTELLIGENCE_STORAGE_EFFECTS_REQUIRED"):
        effects.materialize_normalized(definition(approved()), None, [])
    with pytest.raises(PermissionError, match="INTELLIGENCE_STORAGE_EFFECTS_REQUIRED"):
        effects.register_artifact(definition(approved()), None, None)


def test_injected_response_cannot_ignore_total_fetch_deadline(monkeypatch: Any) -> None:
    record = approved()
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, _ = fetch_adapter(record, [FeedResponse(200, {}, raw)])
    clock = iter([0.0, 0.0, 0.0, 121.0])
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.intelligence_feed.time.monotonic", lambda: next(clock)
    )
    with pytest.raises(AcquisitionError, match="FEED_TIMEOUT"):
        adapter.acquire(definition(record))
