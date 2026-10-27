"""Bounded RSS/Atom acquisition through the shared ingestion state machine.

The default adapter permits offline fixtures only. Live callers must supply an
authoritative registry lookup and retention-policy check; source YAML cannot
approve itself. No schedule, approved source, subscription or crawler is created.
"""

from __future__ import annotations

import base64
import errno
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
from contextlib import nullcontext, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from xml.parsers import expat

from ..intelligence_daily_telemetry import http_observation, spawn_observed, spawn_observed_timer
from ..intelligence_items import (
    ACQUISITION_VERSION,
    canonical_timestamp,
    canonical_url,
    identity_hash,
    normalize_item,
    validate_acquisition_context,
    validate_record,
)
from ..intelligence_metadata import NativeMetadataPolicy, normalize_native_item, parse_native_feed
from ..intelligence_raw_runtime import FeedRawRetention, buffer_namespace
from .adapters import AcquireResult, AcquisitionArtifact, AcquisitionError, NormalizeResult
from .types import AdapterKind, FailureCategory, SourceDefinition, ValidationIssue, ValidationResult

PARSER_VERSION = "rss-atom-v1"
FETCH_VERSION = "pinned-https-v1"
ATOM = "{http://www.w3.org/2005/Atom}"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


def _failure(code: str) -> AcquisitionError:
    return AcquisitionError(code, code=code)


def adapter_for_source(source: dict[str, Any]) -> str:
    """Dispatch RSS/Atom parsing and the Entrez adapter. Entrez is not an RSS feed."""
    transport = source.get("transport")
    if transport == "entrez":
        return "entrez"
    if transport in {"rss", "atom"}:
        return "rss_atom"
    raise _failure("INTELLIGENCE_SOURCE_MISMATCH")


class _ElementBuilder:
    """One-element stack. Completed entries can be dropped instead of kept."""

    def __init__(self) -> None:
        self._data: list[str] = []
        self._tail = False
        self._last: ET.Element | None = None
        self.stack: list[ET.Element] = []
        self.root: ET.Element | None = None

    def _flush(self) -> None:
        if self._data and self._last is not None:
            text = "".join(self._data)
            if self._tail:
                self._last.tail = text
            else:
                self._last.text = text
        self._data = []

    def data(self, data: str) -> None:
        self._data.append(data)

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        self._flush()
        elem = ET.Element(tag, attrs)
        if self.stack:
            self.stack[-1].append(elem)
        elif self.root is None:
            self.root = elem
        self.stack.append(elem)
        self._last = elem
        self._tail = False
        return elem

    def end(self, tag: str) -> ET.Element:
        self._flush()
        elem = self.stack.pop()
        self._last = elem
        self._tail = True
        return elem

    def close(self) -> ET.Element | None:
        self._flush()
        return self.root


def _clark(name: str) -> str:
    """Expat ``uri}local`` names use ElementTree's ``{uri}local`` form."""
    if name.startswith("{") or "}" not in name:
        return name
    uri, local = name.rsplit("}", 1)
    if not uri:
        return local
    return "{" + uri + "}" + local


def _attribute_map(attrs: Any) -> dict[str, str]:
    raw_pairs: list[tuple[Any, Any]]
    if isinstance(attrs, dict):
        raw_pairs = list(attrs.items())
    elif isinstance(attrs, list):
        raw_pairs = [(attrs[index], attrs[index + 1]) for index in range(0, len(attrs), 2)]
    else:
        return {}
    return {_clark(str(key)): str(value) for key, value in raw_pairs}


def _is_feed_entry(transport: str, parent: ET.Element, elem: ET.Element) -> bool:
    if transport == "rss":
        return parent.tag == "channel" and elem.tag == "item"
    if transport == "atom":
        return parent.tag == ATOM + "feed" and elem.tag == ATOM + "entry"
    return False


def walk_feed(
    raw: bytes,
    source: dict[str, Any],
    on_entry: Callable[[ET.Element, str], None],
    *,
    base_url: str | None = None,
) -> ET.Element:
    """Parse one feed, invoking ``on_entry`` per item and then dropping that item.

    The returned element is the channel or feed with entry children removed.
    Security limits match the previous full-tree parse: no DTD, depth 32,
    100_000 nodes, and the reviewed item cap.
    """
    limits = source["limits"]
    if len(raw) > limits["maximum_bytes"]:
        raise _failure("FEED_TOO_LARGE")
    transport = source["transport"]
    if transport not in {"rss", "atom"}:
        raise _failure("INTELLIGENCE_SOURCE_MISMATCH")
    maximum_items = limits["maximum_items"]
    feed_base = base_url or source.get("fetch_location") or ""
    builder = _ElementBuilder()
    depth = 0
    nodes = 0
    kept = 0
    pending: tuple[ET.Element, ET.Element] | None = None

    def deliver() -> None:
        nonlocal pending, kept
        if pending is None:
            return
        parent, elem = pending
        pending = None
        inherited = feed_base
        if transport == "atom" and builder.root is not None:
            inherited = _xml_base(builder.root, feed_base)
        try:
            if kept < maximum_items:
                on_entry(elem, inherited)
        finally:
            kept += 1
            parent.remove(elem)
            elem.clear()

    def start(name: str, attrs: Any) -> None:
        nonlocal depth, nodes
        depth += 1
        nodes += 1
        if depth > 32 or nodes > 100_000:
            raise _failure("XML_COMPLEXITY_LIMIT")
        builder.start(_clark(name), _attribute_map(attrs))
        deliver()

    def end(name: str) -> None:
        nonlocal depth, pending
        elem = builder.end(_clark(name))
        depth -= 1
        parent = builder.stack[-1] if builder.stack else None
        if parent is not None and _is_feed_entry(transport, parent, elem):
            pending = (parent, elem)

    def characters(data: str) -> None:
        builder.data(data)

    def doctype(*_args: Any) -> None:
        raise _failure("XML_DTD_FORBIDDEN")

    parser = expat.ParserCreate(None, "}")
    parser.ordered_attributes = True
    parser.buffer_text = True
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = doctype
    parser.ExternalEntityRefHandler = lambda *_args: 0
    try:
        parser.Parse(raw, True)
        builder.close()
        deliver()
    except AcquisitionError:
        raise
    except (expat.ExpatError, AssertionError, ET.ParseError, IndexError) as error:
        raise _failure("MALFORMED_FEED") from error
    root = builder.root
    if root is None:
        raise _failure("MALFORMED_FEED")
    _require_feed_envelope(root, transport)
    return root


def _require_feed_envelope(root: ET.Element, transport: str) -> ET.Element:
    if transport == "rss" and root.tag == "rss" and root.get("version") == "2.0":
        channels = [child for child in list(root) if child.tag == "channel"]
        if len(channels) != 1:
            raise _failure("UNSUPPORTED_FEED_ENVELOPE")
        return channels[0]
    if transport == "atom" and root.tag == ATOM + "feed":
        return root
    raise _failure("UNSUPPORTED_FEED_ENVELOPE")


def feed_parent(root: ET.Element, source: dict[str, Any]) -> ET.Element:
    """Channel or feed element after entries have been released."""
    return _require_feed_envelope(root, source["transport"])


def entry_record(entry: ET.Element, source: dict[str, Any], inherited_base: str) -> dict[str, Any]:
    """One item's public fields. The caller can drop ``entry`` after this returns."""
    transport = source["transport"]
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
        feed_base = inherited_base
    else:
        entry_base = _xml_base(entry, inherited_base)
        links = [
            None
            if node.get("href") in {None, ""}
            else urljoin(_xml_base(node, entry_base), node.attrib["href"])
            for node in entry.findall(ATOM + "link")
            if node.get("rel", "alternate") == "alternate"
            and node.get("type", "text/html") in {"text/html", "application/xhtml+xml"}
        ]
        # Atom requires href. An empty RFC3986 reference identifies the
        # feed document, not an evidenced publication; abstain in both cases.
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
        feed_base = inherited_base
    if item["url"] and feed_base:
        item["url"] = urljoin(feed_base, item["url"])
    if len(item["topics"]) > 100:
        raise _failure("FEED_TOPIC_LIMIT")
    return item


def parse_feed(
    raw: bytes, source: dict[str, Any], *, base_url: str | None = None
) -> list[dict[str, Any]]:
    """Reject DTD/entities, excessive depth/nodes/items and unsupported envelopes."""
    result: list[dict[str, Any]] = []

    def on_entry(entry: ET.Element, inherited: str) -> None:
        result.append(entry_record(entry, source, inherited))

    walk_feed(raw, source, on_entry, base_url=base_url)
    return result


def count_feed_entries(raw: bytes, source: dict[str, Any], *, base_url: str | None = None) -> int:
    """Validate entries one at a time and return how many were kept.

    The item dict is discarded before the next item is built.
    """
    count = 0

    def on_entry(entry: ET.Element, inherited: str) -> None:
        nonlocal count
        entry_record(entry, source, inherited)
        count += 1

    walk_feed(raw, source, on_entry, base_url=base_url)
    return count


def _xml_base(node: ET.Element, inherited: str) -> str:
    declared = node.get(XML_BASE)
    if declared is None:
        return inherited
    resolved = urljoin(inherited, declared)
    try:
        canonical = canonical_url(resolved)
    except ValueError as error:
        raise _failure("XML_BASE_INVALID") from error
    if not canonical:
        raise _failure("XML_BASE_INVALID")
    return canonical


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
        if match[3] != "Z" and (int(match[3][1:3]) > 23 or int(match[3][4:6]) > 59):
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
    effective_url: str | None = None


@dataclass(frozen=True)
class FeedCache:
    """Private, validated prior capture; not an unvalidated caller byte cache."""

    source_sha256: str
    body: bytes
    artifact_id: str
    etag: str | None = None
    last_modified: str | None = None
    source_context: dict[str, Any] | None = None
    raw_lease_sha256: str | None = None
    cache_id: str = field(default_factory=lambda: buffer_namespace("cache").split("://", 1)[1])

    @property
    def retention_locator(self) -> str:
        return f"cache://{self.cache_id}/{self.raw_lease_sha256}/{self.artifact_id}"

    def discard_raw(self) -> bool:
        existed = bool(self.body)
        object.__setattr__(self, "body", b"")
        return existed


def acquisition_context(
    definition: SourceDefinition,
    source: dict[str, Any],
    *,
    effective_url: str,
    fetched_at: str,
    artifact_sha256: str,
    capture_mode: str,
    fetch_status: int = 200,
) -> dict[str, Any]:
    context = {
        "context_version": ACQUISITION_VERSION,
        "attempt_id": uuid4().hex,
        "source_id": source["source_id"],
        "registry_version": source["registry_version"],
        "registry_sha256": identity_hash(source),
        "requested_url": canonical_url(definition.endpoint_template),
        "effective_url": canonical_url(effective_url),
        "capture_mode": capture_mode,
        "fetch_status": fetch_status,
        "fetched_at": canonical_timestamp(fetched_at),
        "artifact_sha256": artifact_sha256,
    }
    validate_acquisition_context(
        source,
        definition.resource_key,
        definition.endpoint_template,
        context,
        allow_fixture=capture_mode == "fixture",
    )
    return context


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
            # getaddrinfo orders candidates using the platform's address policy.
            # A set loses that preference before our single pinned connection.
            replies.put(
                tuple(dict.fromkeys(str(row[4][0]) for row in socket.getaddrinfo(host, 443)))
            )
        except Exception as error:
            replies.put(error)

    # A platform resolver may block beyond socket timeouts. Only one bounded
    # lookup per request is started; daemon threads never prevent worker exit.
    spawn_observed(lookup, name="intelligence-feed-dns")
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

    with http_observation(url) as observed:
        return _request_observed(
            url, parts, connection, headers, deadline, timer, interrupt, budget, observed
        )


def _request_observed(
    url: str,
    parts: Any,
    connection: _PinnedHTTPS,
    headers: dict[str, str],
    deadline: float,
    timer: threading.Timer | None,
    interrupt: Callable[[], None],
    budget: int,
    observed: dict[str, Any],
) -> FeedResponse:
    try:
        connection.connect()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _failure("FEED_TIMEOUT")
        timer = spawn_observed_timer(remaining, interrupt)
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
        observed["status"] = response.status
        observed["bytes"] = len(body)
        return FeedResponse(response.status, metadata, body)
    except TimeoutError:
        raise _failure("FEED_TIMEOUT") from None
    except ssl.SSLCertVerificationError:
        raise _failure("FEED_TLS_VERIFICATION_FAILED") from None
    except ssl.SSLError:
        raise _failure("FEED_TLS_FAILED") from None
    except http.client.HTTPException:
        raise _failure("FEED_HTTP_PROTOCOL_FAILED") from None
    except ConnectionRefusedError:
        raise _failure("FEED_CONNECTION_REFUSED") from None
    except (ConnectionResetError, BrokenPipeError):
        raise _failure("FEED_CONNECTION_RESET") from None
    except OSError as error:
        # Only closed constant codes leave the transport. Provider exception
        # messages may contain private request values and must not be logged.
        code = (
            "FEED_NETWORK_UNREACHABLE"
            if error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EAFNOSUPPORT}
            else "FEED_NETWORK_FAILED"
        )
        raise _failure(code) from None
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
        native_policy_lookup: Callable[[str, int], NativeMetadataPolicy] | None = None,
        feed_retention: FeedRawRetention | None = None,
    ) -> None:
        self.lookup = registry_lookup
        self.retention_allowed = retention_allowed
        self.request = request
        self.resolve = resolve
        self.sleep = sleep
        self.cache = cache
        self.cache_allowed = cache_allowed
        self.native_policy_lookup = native_policy_lookup
        self.feed_retention = feed_retention

    @staticmethod
    def _source(definition: SourceDefinition) -> dict[str, Any]:
        source = definition.extra.get("intelligence_registry")
        if not isinstance(source, dict):
            raise _failure("INTELLIGENCE_REGISTRY_REQUIRED")
        validate_record("source", source)
        if definition.resource_key != source["source_id"]:
            raise _failure("INTELLIGENCE_RESOURCE_SOURCE_MISMATCH")
        if source["source_id"] != definition.source_id or source["transport"] not in {
            "rss",
            "atom",
        }:
            raise _failure("INTELLIGENCE_SOURCE_MISMATCH")
        return source

    def bind_run_source(self, definition: SourceDefinition, run_id: str) -> None:
        if self.feed_retention is None:
            raise PermissionError("INTELLIGENCE_RAW_RETENTION_REQUIRED")
        self.feed_retention.bind_source(
            run_id,
            self._source(definition),
            parser_version="rss-atom-native-v2" if self.native_policy_lookup else PARSER_VERSION,
            fetch_version=FETCH_VERSION,
        )

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        with self.feed_retention.ledger.guard() if self.feed_retention else nullcontext():
            return self._acquire(definition, fixture_dir=fixture_dir)

    def _acquire(
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
            response = self._fetch(definition, source)
            raw = response.body
        fetched_at = (
            self.feed_retention.clock()
            if self.feed_retention
            else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        effective_url = response.effective_url or definition.endpoint_template
        row_count = count_feed_entries(raw, source, base_url=effective_url)
        digest = hashlib.sha256(raw).hexdigest()
        payload: dict[str, Any] = {
            "xml_base64": base64.b64encode(raw).decode("ascii"),
            "artifact_sha256": digest,
            "fetched_at": canonical_timestamp(fetched_at),
            "source_context": acquisition_context(
                definition,
                source,
                effective_url=effective_url,
                fetched_at=fetched_at,
                artifact_sha256=digest,
                capture_mode="fixture" if fixture_dir is not None else "https",
                fetch_status=response.status,
            ),
        }
        if self.feed_retention is not None:
            payload["raw_lease_sha256"] = self.feed_retention.capture(
                source,
                payload["source_context"],
                previous=self.cache.raw_lease_sha256
                if response.status == 304 and self.cache
                else None,
            )
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
            artifacts=(
                AcquisitionArtifact(
                    name="feed.xml",
                    payload=raw,
                    media_type="application/xml",
                    source_uri=effective_url,
                    row_count=row_count,
                ),
            ),
            row_count=row_count,
            detail={
                "fetch_status": response.status,
                "outcome": "quiet" if row_count == 0 else "fetched",
                "parser_version": PARSER_VERSION,
            },
        )

    def _fetch(self, definition: SourceDefinition, source: dict[str, Any]) -> FeedResponse:
        if self.feed_retention is None and self.request is _request:
            raise _failure("INTELLIGENCE_RAW_RETENTION_REQUIRED")
        limits = source["limits"]
        deadline = time.monotonic() + limits["timeout_seconds"]
        url = source["fetch_location"]
        headers = {
            "Accept": "application/atom+xml, application/rss+xml, application/xml",
            "Accept-Encoding": "identity",
            "User-Agent": "AtlasIntelligence/1",
        }
        cache = self.cache
        if cache is not None and self.feed_retention is not None:
            try:
                with self.feed_retention.lease_access(
                    cache.raw_lease_sha256 or "", "conditional_cache", cache.retention_locator
                ):
                    pass
            except PermissionError as error:
                if str(error) != "INTELLIGENCE_RAW_EXPIRED":
                    raise _failure("FEED_RETAINED_CACHE_REQUIRED") from None
                # Never send validators or accept 304 for expired bytes.
                cache.discard_raw()
                self.cache = cache = None
        if cache is not None:
            if self.cache_allowed is None or not self.cache_allowed(cache):
                raise _failure("FEED_RETAINED_CACHE_REQUIRED")
            if cache.source_sha256 != identity_hash(source) or not cache.artifact_id:
                raise _failure("FEED_CACHE_SOURCE_MISMATCH")
            try:
                validate_acquisition_context(
                    source,
                    definition.resource_key,
                    definition.endpoint_template,
                    cache.source_context,
                )
            except (ValueError, TypeError) as error:
                raise _failure("FEED_CACHE_SOURCE_MISMATCH") from error
            if (
                cache.source_context is None
                or cache.source_context["artifact_sha256"] != hashlib.sha256(cache.body).hexdigest()
                or cache.source_context["effective_url"] != source["fetch_location"]
            ):
                raise _failure("FEED_CACHE_SOURCE_MISMATCH")
            count_feed_entries(cache.body, source, base_url=cache.source_context["effective_url"])
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
                if self.feed_retention is not None:
                    try:
                        with self.feed_retention.lease_access(
                            cache.raw_lease_sha256 or "",
                            "conditional_cache",
                            cache.retention_locator,
                        ):
                            body = cache.body
                    except PermissionError:
                        cache.discard_raw()
                        self.cache = None
                        raise
                    return FeedResponse(304, response.headers, body, url)
                return FeedResponse(304, response.headers, cache.body, url)
            if response.status == 200:
                if redirects:
                    return FeedResponse(200, {}, response.body, url)
                return FeedResponse(200, response.headers, response.body, url)
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
        with self.feed_retention.ledger.guard() if self.feed_retention else nullcontext():
            return self._retained_entries(definition, payload)

    def _retained_entries(self, definition: SourceDefinition, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise _failure("FEED_CAPTURE_REQUIRED")
        if self.feed_retention is not None:
            self.feed_retention.verify_payload(payload)
        raw = base64.b64decode(payload["xml_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != payload["artifact_sha256"]:
            raise _failure("FEED_CAPTURE_HASH_MISMATCH")
        canonical_timestamp(payload["fetched_at"])
        source = self._source(definition)
        try:
            validate_acquisition_context(
                source,
                definition.resource_key,
                definition.endpoint_template,
                payload.get("source_context"),
                allow_fixture=True,
            )
        except (ValueError, TypeError) as error:
            raise _failure("FEED_SOURCE_CONTEXT_MISMATCH") from error
        context = payload["source_context"]
        if (
            context["artifact_sha256"] != payload["artifact_sha256"]
            or context["fetched_at"] != payload["fetched_at"]
        ):
            raise _failure("FEED_SOURCE_CONTEXT_MISMATCH")
        if self.native_policy_lookup is not None:
            policy = self.native_policy_lookup(source["source_id"], source["registry_version"])
            entries = parse_native_feed(raw, source, policy, base_url=context["effective_url"])
        else:
            entries = parse_feed(raw, source, base_url=context["effective_url"])
        del raw
        return entries

    def retained_cache(self, payload: dict[str, Any], artifact_id: str) -> FeedCache:
        if self.feed_retention is None:
            raise PermissionError("INTELLIGENCE_RAW_RETENTION_REQUIRED")
        self.feed_retention.verify_payload(payload)
        source = payload["source_context"]
        cache = FeedCache(
            source["registry_sha256"],
            b"",
            artifact_id,
            payload.get("etag"),
            payload.get("last-modified"),
            source,
            payload["raw_lease_sha256"],
        )
        self.feed_retention.register_buffer(cache.retention_locator, cache.discard_raw)
        with self.feed_retention.lease_access(
            cache.raw_lease_sha256 or "", "conditional_cache", cache.retention_locator, write=True
        ):
            raw = base64.b64decode(payload["xml_base64"], validate=True)
            if hashlib.sha256(raw).hexdigest() != source["artifact_sha256"]:
                raise _failure("FEED_CAPTURE_HASH_MISMATCH")
            retained = FeedCache(
                cache.source_sha256,
                raw,
                artifact_id,
                cache.etag,
                cache.last_modified,
                source,
                cache.raw_lease_sha256,
                cache.cache_id,
            )
            self.feed_retention.register_buffer(retained.retention_locator, retained.discard_raw)
            return retained

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        entries = self._entries(definition, payload)
        lineage = payload.get("_acquisition_lineage", {})
        if not lineage.get("ingestion_run_id") or not lineage.get("artifact_id"):
            raise _failure("FEED_ACQUISITION_LINEAGE_REQUIRED")
        records: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in entries:
            native = self.native_policy_lookup is not None
            normalizer = normalize_native_item if native else normalize_item
            item = normalizer(
                source=self._source(definition),
                transport=self._source(definition)["transport"],
                fetched_at=payload["fetched_at"],
                provenance={
                    "run_id": lineage["ingestion_run_id"],
                    "artifact_id": lineage["artifact_id"],
                    "artifact_sha256": payload["artifact_sha256"],
                    "parser_version": "rss-atom-native-v2" if native else PARSER_VERSION,
                    "fetch_version": FETCH_VERSION,
                },
                **entry,
            )
            records.setdefault((item["item_id"], item["revision_id"]), item)
        return NormalizeResult(
            records=list(records.values()),
            transformation_version="rss-atom-native-v2"
            if self.native_policy_lookup
            else PARSER_VERSION,
            detail={
                "duplicate_items": len(entries) - len(records),
                "outcome": "quiet" if not records else "normalized",
            },
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        # XML alone has no run/artifact/fetch metadata. Never fabricate replay chronology.
        raise _failure("FEED_REPLAY_MANIFEST_REQUIRED")
