"""Transport-independent DATA #131 item identity and permitted-text projection.

No source approval, network acquisition, inference, or warehouse writes occur here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

IDENTITY_VERSION = "intelligence-identity-v1"
TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,199}$")
TIMESTAMP = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.([0-9]+))?(Z|[+]00:00)$"
)
PRIVATE_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "password",
        "secret",
        "signature",
        "authorization",
        "email",
        "recipient",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def identity_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_timestamp(value: str) -> str:
    """Strict UTC RFC3339, preserving arbitrary fractional precision in hashes."""
    match = TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("INVALID_UTC_TIMESTAMP")
    datetime.fromisoformat(match[1]).replace(tzinfo=UTC)  # Validate calendar/time.
    fraction = (match[2] or "").rstrip("0")
    return match[1] + (f".{fraction}" if fraction else "") + "Z"


@lru_cache(maxsize=4)
def _validator(kind: str, version: str = "v1") -> Draft202012Validator:
    if kind not in {"source", "item", "health"}:
        raise ValueError("INVALID_INTELLIGENCE_SCHEMA")
    if version not in {"v1", "v2"} or (version == "v2" and kind != "item"):
        raise ValueError("INVALID_INTELLIGENCE_SCHEMA")
    schema_path = Path(__file__).with_name("intelligence_schemas") / version / f"{kind}.schema.json"
    if not schema_path.exists():
        schema_path = (
            Path(__file__).parents[2]
            / "docs/contracts/intelligence"
            / version
            / f"{kind}.schema.json"
        )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    formats = FormatChecker()

    def utc_datetime(value: object) -> bool:
        if isinstance(value, str):
            canonical_timestamp(value)
        return True

    formats.checks("date-time", raises=ValueError)(utc_datetime)
    return Draft202012Validator(schema, format_checker=formats)


def validate_record(kind: str, value: dict[str, Any]) -> None:
    """Apply accepted schemas without printing source values on validation failure."""
    version = "v2" if kind == "item" and value.get("contract_version") == "2.0.0" else "v1"
    if not _validator(kind, version).is_valid(value):
        raise ValueError("INVALID_INTELLIGENCE_RECORD")


def canonical_url(value: str | None) -> str | None:
    """Never follow links; preserve significant query/path/encoding distinctions."""
    if not value:
        return None
    if re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("INVALID_CANONICAL_URL")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 443}
            or not host
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
            or host.lower() == "localhost"
            or host.lower().endswith((".local", ".internal"))
        ):
            raise ValueError("INVALID_CANONICAL_URL")
        if any(key.lower() in PRIVATE_QUERY_KEYS for key, _ in parse_qsl(parts.query)):
            raise ValueError("PRIVATE_CANONICAL_URL")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("PRIVATE_CANONICAL_URL")
        return urlunsplit(("https", host.lower(), parts.path, parts.query, ""))
    except ValueError as error:
        raise ValueError("INVALID_CANONICAL_URL") from error


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.rsplit(":", 1)[-1] in {"script", "style", "iframe", "object"}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.rsplit(":", 1)[-1] in {"script", "style", "iframe", "object"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def permitted_text(value: str | None, limit: int) -> str | None:
    if not value or limit <= 0:
        return None
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    text = re.sub(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", "".join(parser.parts))
    text = " ".join(text.split())[:limit].strip()
    return text or None


def item_identities(item: dict[str, Any]) -> tuple[str, str, str]:
    """One article identity, content identity and legitimate publisher revision."""
    canonical = canonical_url(item.get("canonical_url"))
    identity = (
        {"canonical_url": canonical}
        if canonical
        else {
            "source_id": item["source_id"],
            "transport_identity_sha256": item["transport_identity_sha256"],
        }
    )
    item_id = identity_hash(identity)
    content = revision_content(item)
    content_hash = identity_hash(content)
    revision_id = identity_hash({"item_id": item_id, "content_sha256": content_hash})
    return item_id, content_hash, revision_id


def revision_content(item: dict[str, Any]) -> dict[str, Any]:
    """One versioned content basis shared by identity and immutable storage."""
    content = {
        field: item[field]
        for field in ("title", "excerpt", "published_at", "updated_at", "event_at")
    }
    for field in ("published_at", "updated_at", "event_at"):
        if content[field] is not None:
            content[field] = canonical_timestamp(content[field])
    if item.get("contract_version") == "2.0.0":
        native = item["native_metadata"]
        content.update(
            contract_version="2.0.0",
            publisher_metadata=item["publisher_metadata"],
            native_metadata={
                "inventory": [path for path in native["inventory"] if path.startswith("item/")],
                "item": native["item"],
                "item_attributes": native["item_attributes"],
                "publisher_dates": native["publisher_dates"],
            },
        )
    return content


def normalize_item(
    *,
    source: dict[str, Any],
    transport: str,
    publisher_identity: str | None,
    url: str | None,
    title: str | None,
    excerpt: str | None,
    published_at: str | None,
    updated_at: str | None,
    fetched_at: str,
    provenance: dict[str, str],
    topics: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Project permitted publisher metadata without inventing dates or relevance."""
    if source["transport"] != transport or transport not in {"rss", "atom", "email", "web"}:
        raise ValueError("TRANSPORT_SOURCE_MISMATCH")
    fields: dict[str, str | None] = {}
    states: dict[str, str] = {}
    limitations = ["Publication-level intelligence; not an epidemiological measurement"]
    try:
        fields["canonical_url"] = canonical_url(url)
        states["canonical_url"] = "present" if fields["canonical_url"] else "not_provided"
    except ValueError:
        fields["canonical_url"] = None
        states["canonical_url"] = "invalid"
    fields["title"] = permitted_text(title, 1000)
    states["title"] = "present" if fields["title"] else ("invalid" if title else "not_provided")
    for key, value in (("published_at", published_at), ("updated_at", updated_at)):
        try:
            fields[key] = canonical_timestamp(value) if value else None
            states[key] = "present" if value else "not_provided"
        except ValueError:
            fields[key] = None
            states[key] = "invalid"
            limitations.append(f"Unsupported publisher chronology: {key}")
    fields["event_at"] = None
    states["event_at"] = "not_provided"
    rights = source["access_use"]
    budget = int(rights["excerpt_max_chars"])
    if not 0 <= budget <= 5000:
        raise ValueError("INVALID_EXCERPT_BUDGET")
    fields["excerpt"] = (
        permitted_text(excerpt, budget) if rights["public_excerpt_permitted"] else None
    )
    states["excerpt"] = (
        "withheld"
        if not rights["public_excerpt_permitted"] or budget == 0
        else "present"
        if fields["excerpt"]
        else "not_provided"
    )
    item: dict[str, Any] = {
        "contract_version": "1.0.0",
        "source_id": source["source_id"],
        "registry_version": source["registry_version"],
        **fields,
        "fetched_at": canonical_timestamp(fetched_at),
        "field_states": states,
        "geographies": [],
        "topics": [],
        "transport": transport,
        "provenance": {**provenance, "normalization_version": IDENTITY_VERSION},
        "limitations": limitations,
        "content_is_untrusted": True,
    }
    unmapped = 0
    for topic in dict.fromkeys(topics):
        if TOKEN.fullmatch(topic):
            item["topics"].append(
                {
                    "value": topic,
                    "origin": "publisher",
                    "method": None,
                    "method_version": None,
                    "confidence": None,
                }
            )
        else:
            unmapped += 1
    if unmapped:
        limitations.append(f"Publisher topics without reviewed taxonomy mapping: {unmapped}")
    if not publisher_identity:
        publisher_identity = identity_hash(fields)
        limitations.append(
            "Content-only transport identity cannot reliably link future corrections"
        )
    item["transport_identity_sha256"] = identity_hash(publisher_identity)
    item_id, content_hash, revision = item_identities(item)
    item.update(
        item_id=item_id,
        deduplication_key=item_id,
        content_sha256=content_hash,
        revision_id=revision,
    )
    validate_record("item", item)
    return item


ACQUISITION_VERSION = "intelligence-acquisition-v1"
ACQUISITION_FIELDS = frozenset(
    {
        "context_version",
        "attempt_id",
        "source_id",
        "registry_version",
        "registry_sha256",
        "requested_url",
        "effective_url",
        "capture_mode",
        "fetch_status",
        "fetched_at",
        "artifact_sha256",
    }
)


def validate_acquisition_context(
    source: dict[str, Any],
    resource_key: str,
    requested_url: str,
    context: Any,
    *,
    allow_fixture: bool = False,
) -> None:
    """Private immutable capture binding; public #131 item schemas stay unchanged."""
    if not isinstance(context, dict) or set(context) != ACQUISITION_FIELDS:
        raise ValueError("INTELLIGENCE_ACQUISITION_CONTEXT_REQUIRED")
    if (
        type(context["registry_version"]) is not int
        or type(context["fetch_status"]) is not int
        or any(
            not isinstance(value, str)
            for key, value in context.items()
            if key not in {"registry_version", "fetch_status"}
        )
    ):
        raise ValueError("INTELLIGENCE_ACQUISITION_CONTEXT_MISMATCH")
    if (
        context["context_version"] != ACQUISITION_VERSION
        or re.fullmatch(r"[a-f0-9]{32}", context["attempt_id"]) is None
        or resource_key != source["source_id"]
        or context["source_id"] != source["source_id"]
        or context["registry_version"] != source["registry_version"]
        or context["registry_sha256"] != identity_hash(source)
        or context["requested_url"] != canonical_url(requested_url)
        or context["fetch_status"] not in {200, 304}
        or context["capture_mode"] not in ({"fixture", "https"} if allow_fixture else {"https"})
        or not isinstance(context["artifact_sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", context["artifact_sha256"]) is None
        or canonical_timestamp(context["fetched_at"]) != context["fetched_at"]
    ):
        raise ValueError("INTELLIGENCE_ACQUISITION_CONTEXT_MISMATCH")
    effective = canonical_url(context["effective_url"])
    if not effective or effective != context["effective_url"]:
        raise ValueError("INTELLIGENCE_ACQUISITION_URL_INVALID")
    if context["capture_mode"] == "https" and (
        source["state"] not in {"active", "manual"}
        or canonical_url(source["fetch_location"]) != context["requested_url"]
        or urlsplit(effective).hostname not in source["approved_hosts"]
    ):
        raise ValueError("INTELLIGENCE_ACQUISITION_SOURCE_NOT_APPROVED")
