"""Bounded RSS/Atom acquisition through the shared ingestion state machine.

The default adapter permits offline fixtures only. Live callers must supply an
authoritative registry lookup and retention-policy check; source YAML cannot
approve itself. No schedule, approved source, subscription or crawler is created.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.parsers import expat

from ..intelligence_items import canonical_timestamp, canonical_url, normalize_item, validate_record
from .adapters import AcquireResult, AcquisitionError, NormalizeResult
from .types import AdapterKind, FailureCategory, SourceDefinition, ValidationIssue, ValidationResult

PARSER_VERSION = "rss-atom-v1"
FETCH_VERSION = "pinned-https-v1"
ATOM = "{http://www.w3.org/2005/Atom}"


def _failure(code: str) -> AcquisitionError:
    return AcquisitionError(code, code=code)


def parse_feed(raw: bytes, source: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject DTD/entities, excessive depth/nodes/items and unsupported envelopes."""
    limits = source["limits"]
    if len(raw) > limits["maximum_bytes"]:
        raise _failure("FEED_TOO_LARGE")
    guard = expat.ParserCreate()
    depth = nodes = 0

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, nodes
        depth += 1
        nodes += 1
        if depth > 32 or nodes > 100_000:
            raise _failure("XML_COMPLEXITY_LIMIT")

    def end(name: str) -> None:
        nonlocal depth
        depth -= 1

    def doctype(*args: Any) -> None:
        raise _failure("XML_DTD_FORBIDDEN")

    guard.StartElementHandler = start
    guard.EndElementHandler = end
    guard.StartDoctypeDeclHandler = doctype
    guard.ExternalEntityRefHandler = lambda *args: 0
    try:
        guard.Parse(raw, True)
        root = ET.fromstring(raw)
    except (expat.ExpatError, ET.ParseError) as error:
        raise _failure("MALFORMED_FEED") from error
    transport = source["transport"]
    if transport == "rss" and root.tag == "rss" and root.get("version") == "2.0":
        channels = root.findall("channel")
        if len(channels) != 1:
            raise _failure("UNSUPPORTED_FEED_ENVELOPE")
        entries = channels[0].findall("item")
    elif transport == "atom" and root.tag == ATOM + "feed":
        entries = root.findall(ATOM + "entry")
    else:
        raise _failure("UNSUPPORTED_FEED_ENVELOPE")
    if len(entries) > limits["maximum_items"]:
        raise _failure("FEED_ITEM_LIMIT")
    result: list[dict[str, Any]] = []
    for entry in entries:
        if transport == "rss":
            item: dict[str, Any] = {
                "publisher_identity": _text(entry, "guid"),
                "url": _text(entry, "link"),
                "title": _text(entry, "title"),
                "excerpt": _text(entry, "description"),
                "published_at": _publisher_date(_text(entry, "pubDate"), rss=True),
                "updated_at": None,
                "topics": tuple(_element_text(node) for node in entry.findall("category")),
            }
        else:
            links = [
                node.get("href")
                for node in entry.findall(ATOM + "link")
                if node.get("rel", "alternate") == "alternate"
                and node.get("type", "text/html") in {"text/html", "application/xhtml+xml"}
            ]
            # Ambiguous alternatives stay unknown rather than choosing a publisher URL.
            item = {
                "publisher_identity": _text(entry, ATOM + "id"),
                "url": links[0] if len(links) == 1 else None,
                "title": _text(entry, ATOM + "title"),
                "excerpt": _text(entry, ATOM + "summary"),
                "published_at": _publisher_date(_text(entry, ATOM + "published")),
                "updated_at": _publisher_date(_text(entry, ATOM + "updated")),
                "topics": tuple(node.get("term", "") for node in entry.findall(ATOM + "category")),
            }
        if item["url"] and source["fetch_location"]:
            item["url"] = urljoin(source["fetch_location"], item["url"])
        if len(item["topics"]) > 100:
            raise _failure("FEED_TOPIC_LIMIT")
        result.append(item)
    return result


def _element_text(node: ET.Element) -> str:
    # Preserve child markup for the permitted-text sanitizer (including XHTML).
    return (node.text or "") + "".join(ET.tostring(child, encoding="unicode") for child in node)


def _text(node: ET.Element, name: str) -> str | None:
    children = node.findall(name)
    if len(children) > 1:
        raise _failure("AMBIGUOUS_FEED_FIELD")
    return _element_text(children[0]).strip() if children else None


def _publisher_date(value: str | None, *, rss: bool = False) -> str | None:
    if not value:
        return None
    try:
        if rss:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return value  # Missing zone remains invalid, never assumed UTC.
            return date.astimezone(UTC).isoformat().replace("+00:00", "Z")
        match = re.fullmatch(
            r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
            r"(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})",
            value,
        )
        if match is None:
            return value
        date = datetime.fromisoformat(match[1] + match[3].replace("Z", "+00:00"))
        seconds = date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        return canonical_timestamp(seconds + ("." + match[2] if match[2] else "") + "Z")
    except (ValueError, TypeError, OverflowError):
        return value  # Normalizer records invalid chronology explicitly.


@dataclass(frozen=True)
class FeedResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class FeedCache:
    """Private, validated prior capture; not an unvalidated caller byte cache."""

    source_sha256: str
    body: bytes
    artifact_id: str
    etag: str | None = None
    last_modified: str | None = None


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self.tls_context)
        self.address = address
        self.request_timeout = timeout

    def connect(self) -> None:
        # No second hostname lookup, proxy environment or unverified TLS/SNI.
        deadline = time.monotonic() + self.request_timeout
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _failure("FEED_TIMEOUT")
            raw.settimeout(remaining)
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _resolve(host: str, timeout: float) -> tuple[str, ...]:
    replies: queue.Queue[tuple[str, ...] | Exception] = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            replies.put(tuple({str(row[4][0]) for row in socket.getaddrinfo(host, 443)}))
        except Exception as error:
            replies.put(error)

    # A platform resolver may block beyond socket timeouts. Only one bounded
    # lookup per request is started; daemon threads never prevent worker exit.
    threading.Thread(target=lookup, daemon=True).start()
    try:
        reply = replies.get(timeout=timeout)
    except queue.Empty as error:
        raise _failure("FEED_DNS_TIMEOUT") from error
    if isinstance(reply, Exception):
        raise _failure("FEED_DNS_FAILED") from reply
    return reply


def _request(
    url: str, address: str, headers: dict[str, str], budget: int, timeout: float
) -> FeedResponse:
    parts = urlsplit(url)
    connection = _PinnedHTTPS(parts.hostname or "", address, timeout)
    deadline = time.monotonic() + timeout
    timer: threading.Timer | None = None

    def interrupt() -> None:
        if connection.sock is not None:
            with suppress(OSError):
                connection.sock.shutdown(socket.SHUT_RDWR)

    try:
        connection.connect()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _failure("FEED_TIMEOUT")
        timer = threading.Timer(remaining, interrupt)
        timer.daemon = True
        timer.start()
        connection.request(
            "GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""), headers=headers
        )
        response = connection.getresponse()
        metadata = {key.lower(): value for key, value in response.getheaders()}
        if metadata.get("content-encoding", "identity").lower() != "identity":
            raise _failure("FEED_ENCODING_UNSUPPORTED")
        length = metadata.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > budget):
            raise _failure("FEED_TOO_LARGE")
        body = response.read(budget + 1)
        if len(body) > budget:
            raise _failure("FEED_TOO_LARGE")
        if time.monotonic() >= deadline:
            raise _failure("FEED_TIMEOUT")
        return FeedResponse(response.status, metadata, body)
    except (OSError, http.client.HTTPException) as error:
        raise _failure("FEED_NETWORK_FAILED") from error
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


class IntelligenceFeedAdapter:
    kind = AdapterKind.RSS_ATOM

    def __init__(
        self,
        *,
        registry_lookup: Callable[[str, int], dict[str, Any]] | None = None,
        retention_allowed: Callable[[str], bool] | None = None,
        request: Callable[[str, str, dict[str, str], int, float], FeedResponse] = _request,
        resolve: Callable[[str, float], tuple[str, ...]] = _resolve,
        sleep: Callable[[float], None] = time.sleep,
        cache: FeedCache | None = None,
        cache_allowed: Callable[[FeedCache], bool] | None = None,
    ) -> None:
        self.lookup = registry_lookup
        self.retention_allowed = retention_allowed
        self.request = request
        self.resolve = resolve
        self.sleep = sleep
        self.cache = cache
        self.cache_allowed = cache_allowed

    @staticmethod
    def _source(definition: SourceDefinition) -> dict[str, Any]:
        source = definition.extra.get("intelligence_registry")
        if not isinstance(source, dict):
            raise _failure("INTELLIGENCE_REGISTRY_REQUIRED")
        validate_record("source", source)
        if source["source_id"] != definition.source_id or source["transport"] not in {
            "rss",
            "atom",
        }:
            raise _failure("INTELLIGENCE_SOURCE_MISMATCH")
        return source

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        source = self._source(definition)
        response = FeedResponse(200, {}, b"")
        if fixture_dir is not None:
            with (fixture_dir / "sample.xml").open("rb") as stream:
                raw = stream.read(source["limits"]["maximum_bytes"] + 1)
        else:
            if self.lookup is None or self.retention_allowed is None:
                raise PermissionError("INTELLIGENCE_LIVE_APPROVAL_REQUIRED")
            approved = self.lookup(source["source_id"], source["registry_version"])
            if approved != source or source["state"] not in {"active", "manual"}:
                raise PermissionError("INTELLIGENCE_SOURCE_NOT_APPROVED")
            if not self.retention_allowed(source["access_use"]["content_retention_policy_ref"]):
                raise PermissionError("INTELLIGENCE_RETENTION_NOT_APPROVED")
            if canonical_url(definition.endpoint_template) != canonical_url(
                source["fetch_location"]
            ):
                raise PermissionError("INTELLIGENCE_ENDPOINT_MISMATCH")
            response = self._fetch(source)
            raw = response.body
        entries = parse_feed(raw, source)
        payload = {
            "xml_base64": base64.b64encode(raw).decode("ascii"),
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        # Private replay manifest only; never part of an intelligence item or log.
        for key in ("etag", "last-modified"):
            value = response.headers.get(key)
            if (
                value is not None
                and len(value) <= 512
                and all(32 <= ord(char) < 127 for char in value)
            ):
                payload[key] = value
        return AcquireResult(
            payload=payload,
            raw_payload=raw,
            artifact_sha256=payload["artifact_sha256"],
            media_type="application/xml",
            row_count=len(entries),
            detail={
                "fetch_status": response.status,
                "outcome": "quiet" if not entries else "fetched",
                "parser_version": PARSER_VERSION,
            },
        )

    def _fetch(self, source: dict[str, Any]) -> FeedResponse:
        from ..intelligence_items import identity_hash

        limits = source["limits"]
        deadline = time.monotonic() + limits["timeout_seconds"]
        url = source["fetch_location"]
        headers = {
            "Accept": "application/atom+xml, application/rss+xml, application/xml",
            "Accept-Encoding": "identity",
            "User-Agent": "AtlasIntelligence/1",
        }
        cache = self.cache
        if cache is not None:
            if self.cache_allowed is None or not self.cache_allowed(cache):
                raise _failure("FEED_RETAINED_CACHE_REQUIRED")
            if cache.source_sha256 != identity_hash(source) or not cache.artifact_id:
                raise _failure("FEED_CACHE_SOURCE_MISMATCH")
            parse_feed(cache.body, source)
            for name, value in (
                ("If-None-Match", cache.etag),
                ("If-Modified-Since", cache.last_modified),
            ):
                if value is not None:
                    if len(value) > 512 or any(
                        ord(char) < 32 or ord(char) == 127 for char in value
                    ):
                        raise _failure("FEED_CACHE_HEADER_INVALID")
                    headers[name] = value
        redirects = attempts = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _failure("FEED_TIMEOUT")
            safe_url = canonical_url(url)
            host = urlsplit(safe_url or "").hostname or ""
            if host not in source["approved_hosts"]:
                raise _failure("FEED_HOST_NOT_APPROVED")
            addresses = self.resolve(host, remaining)
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise _failure("FEED_PRIVATE_ADDRESS")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _failure("FEED_TIMEOUT")
            response = self.request(
                safe_url or "", addresses[0], headers, limits["maximum_bytes"], remaining
            )
            if time.monotonic() >= deadline:
                raise _failure("FEED_TIMEOUT")
            if len(response.body) > limits["maximum_bytes"]:
                raise _failure("FEED_TOO_LARGE")
            if response.status in {301, 302, 303, 307, 308}:
                redirects += 1
                if redirects > limits["maximum_redirects"] or not response.headers.get("location"):
                    raise _failure("FEED_REDIRECT_BLOCKED")
                url = urljoin(url, response.headers["location"])
                # Validators belong to the exact endpoint, never forwarded to redirects.
                headers.pop("If-None-Match", None)
                headers.pop("If-Modified-Since", None)
                continue
            attempts += 1
            if response.status == 304:
                if cache is None or url != source["fetch_location"]:
                    raise _failure("FEED_304_WITHOUT_CAPTURE")
                return FeedResponse(304, response.headers, cache.body)
            if response.status == 200:
                if redirects:
                    return FeedResponse(200, {}, response.body)
                return response
            if response.status == 429 or 500 <= response.status <= 599:
                if attempts >= limits["maximum_attempts"]:
                    raise _failure(
                        "FEED_RATE_LIMITED" if response.status == 429 else "FEED_UPSTREAM_FAILED"
                    )
                wait = 2 ** (attempts - 1)
                retry = response.headers.get("retry-after")
                if retry:
                    if not retry.isdigit() or int(retry) > 2:
                        raise _failure("FEED_RETRY_DEFERRED")
                    wait = max(wait, int(retry))
                if wait >= deadline - time.monotonic():
                    raise _failure("FEED_RETRY_DEFERRED")
                self.sleep(float(wait))
                continue
            raise _failure(
                "FEED_ACCESS_FAILED" if response.status in {401, 403} else "FEED_HTTP_FAILED"
            )

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        try:
            self._entries(definition, payload)
        except (ValueError, AcquisitionError, KeyError, TypeError):
            return ValidationResult(
                ok=False,
                issues=[
                    ValidationIssue(
                        code="FEED_PAYLOAD_INVALID",
                        message="Feed payload failed bounded validation",
                        category=FailureCategory.SCHEMA,
                    )
                ],
            )
        return ValidationResult(ok=True, issues=[])

    def _entries(self, definition: SourceDefinition, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise _failure("FEED_CAPTURE_REQUIRED")
        raw = base64.b64decode(payload["xml_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != payload["artifact_sha256"]:
            raise _failure("FEED_CAPTURE_HASH_MISMATCH")
        canonical_timestamp(payload["fetched_at"])
        return parse_feed(raw, self._source(definition))

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        entries = self._entries(definition, payload)
        lineage = payload.get("_acquisition_lineage", {})
        if not lineage.get("ingestion_run_id") or not lineage.get("artifact_id"):
            raise _failure("FEED_ACQUISITION_LINEAGE_REQUIRED")
        records: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in entries:
            item = normalize_item(
                source=self._source(definition),
                transport=self._source(definition)["transport"],
                fetched_at=payload["fetched_at"],
                provenance={
                    "run_id": lineage["ingestion_run_id"],
                    "artifact_id": lineage["artifact_id"],
                    "artifact_sha256": payload["artifact_sha256"],
                    "parser_version": PARSER_VERSION,
                    "fetch_version": FETCH_VERSION,
                },
                **entry,
            )
            records.setdefault((item["item_id"], item["revision_id"]), item)
        return NormalizeResult(
            records=list(records.values()),
            transformation_version=PARSER_VERSION,
            detail={
                "duplicate_items": len(entries) - len(records),
                "outcome": "quiet" if not records else "normalized",
            },
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        # XML alone has no run/artifact/fetch metadata. Never fabricate replay chronology.
        raise _failure("FEED_REPLAY_MANIFEST_REQUIRED")
