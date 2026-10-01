"""Pinned connection, bounded response and cache policy independent tests."""

from __future__ import annotations

import hashlib
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
    acquisition_context,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash


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
