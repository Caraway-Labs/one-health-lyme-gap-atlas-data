"""Rights-bound native metadata mapping; no source activation or enrichment."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .intelligence_items import (
    TOKEN,
    canonical_json,
    canonical_timestamp,
    canonical_url,
    identity_hash,
    item_identities,
    normalize_item,
    permitted_text,
    validate_record,
)

VERSION = "intelligence-identity-v2"
PARSER = "rss-atom-native-v2"
ATOM = "{http://www.w3.org/2005/Atom}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
MEDIA = "{http://search.yahoo.com/mrss/}"
ENTRY_TAGS = frozenset({"item", ATOM + "entry"})


@dataclass(frozen=True)
class NativeMetadataPolicy:
    """An injected reviewed source/version receipt, never inferred from XML.

    Paths use expanded namespace names and explicit feed/item scopes. Inventory
    describes observed structures, not a blanket right to retain their values.
    Permitted paths authorize sanitized metadata only, not transport XML,
    full article content, or raw HTML. The trusted lookup must resolve rights.
    """

    policy_ref: str
    source_sha256: str
    inventory: frozenset[str]
    permitted_paths: frozenset[str]
    published_path: str
    published_format: str
    updated_path: str | None = None
    updated_format: str = "iso8601"
    required_paths: frozenset[str] = frozenset()

    def document(self) -> dict[str, Any]:
        return {
            "policy_ref": self.policy_ref,
            "source_sha256": self.source_sha256,
            "inventory": sorted(self.inventory),
            "permitted_paths": sorted(self.permitted_paths),
            "published_path": self.published_path,
            "published_format": self.published_format,
            "updated_path": self.updated_path,
            "updated_format": self.updated_format,
            "required_paths": sorted(self.required_paths),
        }

    def validate(self, source: dict[str, Any]) -> None:
        if (
            not self.policy_ref
            or len(self.policy_ref) > 200
            or self.source_sha256 != identity_hash(source)
            or not self.inventory
            or not self.permitted_paths <= self.inventory
            or not self.required_paths <= self.inventory
            or self.published_format not in {"rfc822", "iso8601"}
            or self.updated_format not in {"rfc822", "iso8601"}
            or self.published_path not in self.inventory
            or (self.updated_path is not None and self.updated_path not in self.inventory)
        ):
            raise ValueError("INTELLIGENCE_NATIVE_POLICY_INVALID")


def _stream_parent(
    raw: bytes,
    source: dict[str, Any],
    base_url: str | None,
    on_entry: Any,
) -> ET.Element:
    """Walk the feed once. ``on_entry`` sees one detached item, then it is cleared."""
    # Local import: intelligence_feed already imports this module.
    from .ingestion.intelligence_feed import feed_parent, walk_feed

    root = walk_feed(raw, source, on_entry, base_url=base_url)
    return feed_parent(root, source)


def _walk(node: ET.Element, path: str, output: dict[str, list[str | None]]) -> None:
    output.setdefault(path, []).append(node.text)
    if node.tail and node.tail.strip():
        output.setdefault(path + "/#tail", []).append(node.tail)
    for name, value in sorted(node.attrib.items()):
        output.setdefault(path + "/@" + name, []).append(value)
    for child in node:
        _walk(child, path + "/" + child.tag, output)


def _fields(parent: ET.Element, entries: list[ET.Element]) -> dict[str, list[str | None]]:
    fields: dict[str, list[str | None]] = {}
    for name, value in sorted(parent.attrib.items()):
        fields.setdefault("feed/@" + name, []).append(value)
    for child in parent:
        if child.tag not in ENTRY_TAGS:
            _walk(child, "feed/" + child.tag, fields)
    for entry in entries:
        for name, value in sorted(entry.attrib.items()):
            fields.setdefault("item/@" + name, []).append(value)
        for child in entry:
            _walk(child, "item/" + child.tag, fields)
    return fields


def inventory_feed(
    raw: bytes, source: dict[str, Any], *, base_url: str | None = None
) -> dict[str, int]:
    """Value-free observed inventory; safe evidence for denied-text fields too."""
    item_counts: dict[str, int] = {}

    def on_entry(entry: ET.Element, _inherited: str) -> None:
        for path, values in _fields(ET.Element("feed"), [entry]).items():
            item_counts[path] = item_counts.get(path, 0) + len(values)

    parent = _stream_parent(raw, source, base_url, on_entry)
    counts = {path: len(values) for path, values in _fields(parent, []).items()}
    for path, count in item_counts.items():
        counts[path] = counts.get(path, 0) + count
    return dict(sorted(counts.items()))


def _value(value: str | None, path: str, policy: NativeMetadataPolicy) -> dict[str, Any]:
    if value is None or not value.strip():
        return {"value": None, "state": "not_provided"}
    if path not in policy.permitted_paths:
        return {"value": None, "state": "withheld"}
    # Refuse oversized reviewed metadata rather than silently truncating it.
    if len(value) > 4096:
        raise ValueError("INTELLIGENCE_NATIVE_FIELD_LIMIT")
    sanitized = permitted_text(value, 4096)
    return {
        "value": sanitized,
        "state": "present" if sanitized else "invalid",
    }


def _node(node: ET.Element, path: str, policy: NativeMetadataPolicy) -> dict[str, Any]:
    return {
        "name": node.tag,
        **_value(node.text, path, policy),
        "tail": _value(node.tail, path + "/#tail", policy),
        "attributes": [
            {"name": name, **_value(value, path + "/@" + name, policy)}
            for name, value in sorted(node.attrib.items())
        ],
        "children": [_node(child, path + "/" + child.tag, policy) for child in node],
    }


def _scalar(fields: dict[str, list[str | None]], path: str | None) -> str | None:
    if path is None:
        return None
    values = fields.get(path, [])
    if len(values) > 1:
        raise ValueError("INTELLIGENCE_NATIVE_MAPPING_AMBIGUOUS")
    return values[0] if values else None


def _date(
    raw: str | None, dialect: str, path: str | None, policy: NativeMetadataPolicy
) -> dict[str, Any]:
    from .ingestion.intelligence_feed import _publisher_date

    normalized = None
    state = "not_provided"
    if raw is not None and raw.strip():
        candidate = _publisher_date(raw.strip(), rss=dialect == "rfc822")
        try:
            normalized = canonical_timestamp(candidate) if candidate else None
            state = "present" if normalized else "invalid"
        except ValueError:
            state = "invalid"
    # Exact publisher string is private metadata only when reviewed and bounded.
    if raw is not None and len(raw) > 512:
        raise ValueError("INTELLIGENCE_NATIVE_DATE_LIMIT")
    permitted = path in policy.permitted_paths
    if raw and not permitted:
        normalized, state = None, "withheld"
    return {
        "raw": raw if permitted else None,
        "raw_state": "present" if permitted and raw else "not_provided" if not raw else "withheld",
        "normalized": normalized,
        "state": state,
        "parser": dialect,
    }


def parse_native_feed(
    raw: bytes,
    source: dict[str, Any],
    policy: NativeMetadataPolicy,
    *,
    base_url: str | None = None,
) -> list[dict[str, Any]]:
    """Map reviewed metadata without discarding namespaces or repeated fields.

    Items are mapped one at a time. The feed header is kept; item elements are
    released before the next item is parsed.
    """
    from .ingestion.intelligence_feed import entry_record

    policy.validate(source)
    item_paths: set[str] = set()
    saw_entry = False

    def collect(entry: ET.Element, _inherited: str) -> None:
        nonlocal saw_entry
        saw_entry = True
        item_paths.update(_fields(ET.Element("feed"), [entry]))

    parent = _stream_parent(raw, source, base_url, collect)
    inventory = set(_fields(parent, [])) | item_paths
    required = (
        policy.required_paths
        if saw_entry
        else frozenset(path for path in policy.required_paths if path.startswith("feed/"))
    )
    if not inventory <= policy.inventory or not required <= inventory:
        raise ValueError("INTELLIGENCE_NATIVE_SCHEMA_DRIFT")
    # Legacy field errors are raised before native mapping, matching the
    # previous parse-then-map order, without retaining item elements.
    legacy: list[dict[str, Any]] = []

    def collect_legacy(entry: ET.Element, inherited: str) -> None:
        legacy.append(entry_record(entry, source, inherited))

    _stream_parent(raw, source, base_url, collect_legacy)
    mapped: list[dict[str, Any]] = []
    cursor = 0

    def on_entry(entry: ET.Element, _inherited: str) -> None:
        nonlocal cursor
        base = legacy[cursor]
        cursor += 1
        mapped.append(_map_native_entry(parent, entry, base, source, policy))

    _stream_parent(raw, source, base_url, on_entry)
    return mapped


def _map_native_entry(
    parent: ET.Element,
    entry: ET.Element,
    base: dict[str, Any],
    source: dict[str, Any],
    policy: NativeMetadataPolicy,
) -> dict[str, Any]:
    fields = _fields(parent, [entry])
    if not policy.required_paths <= set(fields):
        raise ValueError("INTELLIGENCE_NATIVE_SCHEMA_DRIFT")
    native: dict[str, Any] = {
        "policy_ref": policy.policy_ref,
        "policy_sha256": identity_hash(policy.document()),
        "inventory": sorted(path for path in fields if path in policy.inventory),
        "feed": [
            _node(child, "feed/" + child.tag, policy)
            for child in parent
            if child.tag not in ENTRY_TAGS
        ],
        "feed_attributes": [
            {"name": name, **_value(value, "feed/@" + name, policy)}
            for name, value in sorted(parent.attrib.items())
        ],
        "item": [_node(child, "item/" + child.tag, policy) for child in entry],
        "item_attributes": [
            {"name": name, **_value(value, "item/@" + name, policy)}
            for name, value in sorted(entry.attrib.items())
        ],
        "publisher_dates": {
            "published_at": _date(
                _scalar(fields, policy.published_path),
                policy.published_format,
                policy.published_path,
                policy,
            ),
            "updated_at": _date(
                _scalar(fields, policy.updated_path),
                policy.updated_format,
                policy.updated_path,
                policy,
            ),
        },
    }
    if len(canonical_json(native).encode()) > 65536:
        raise ValueError("INTELLIGENCE_NATIVE_METADATA_LIMIT")
    canonical = _publisher_metadata(fields, source, policy, native)
    # Legacy public fields must obey the same receipt as the private tree.
    rss = source["transport"] == "rss"
    for key, name in (("title", "title"), ("excerpt", "description" if rss else "summary")):
        path = "item/" + (name if rss else ATOM + name)
        if any(
            p == path or p.startswith(path + "/") for p in fields if p not in policy.permitted_paths
        ):
            base[key] = None
    if not _url_paths_permitted(fields, policy, rss):
        base["url"] = None
    base["topics"] = tuple(canonical["categories"])
    for key in ("published_at", "updated_at"):
        date = native["publisher_dates"][key]
        base[key] = date["normalized"]
    return {**base, "publisher_metadata": canonical, "native_metadata": native}


def _url_paths_permitted(
    fields: dict[str, list[str | None]], policy: NativeMetadataPolicy, rss: bool
) -> bool:
    prefix = "item/link" if rss else "item/" + ATOM + "link"
    relevant = {path for path in fields if path == prefix or path.startswith(prefix + "/")}
    if not rss:
        relevant |= {
            path for path in fields if path.endswith("/@{http://www.w3.org/XML/1998/namespace}base")
        }
    return relevant <= policy.permitted_paths


def _complete_plain_text(value: str | None) -> str:
    """Sanitized publisher text. Oversized results fail; they are never shortened."""
    if value is None:
        return ""
    plain = permitted_text(value, 4096) or ""
    complete = permitted_text(value, max(len(value), 4096) + 1) or ""
    if complete != plain or len(plain) > 4096:
        raise ValueError("INTELLIGENCE_NATIVE_FIELD_LIMIT")
    return plain


def _publisher_metadata(
    fields: dict[str, list[str | None]],
    source: dict[str, Any],
    policy: NativeMetadataPolicy,
    native: dict[str, Any],
    *,
    sanitized_fields: bool = False,
) -> dict[str, Any]:
    canonical: dict[str, Any] = {
        "publisher": permitted_text(source["organization"], 1000),
        "source_family": source["family"],
        "source_item_id": None,
        "authors": [],
        "categories": [],
        "language": None,
        "media": [],
        "date_states": {key: value["state"] for key, value in native["publisher_dates"].items()},
    }
    rss = source["transport"] == "rss"
    identity_path = "item/guid" if rss else "item/" + ATOM + "id"
    canonical["source_item_id"] = _value(_scalar(fields, identity_path), identity_path, policy)[
        "value"
    ]
    author_paths = (
        ["item/author", "item/{http://purl.org/dc/elements/1.1/}creator"]
        if rss
        else [
            "item/" + ATOM + "author/" + ATOM + "name",
            "feed/" + ATOM + "author/" + ATOM + "name",
        ]
    )
    for path in author_paths:
        for value in fields.get(path, []):
            author = _value(value, path, policy)["value"]
            if author and "@" not in author and author not in canonical["authors"]:
                canonical["authors"].append(author)
    category_path = "item/category" if rss else "item/" + ATOM + "category/@term"
    categories: list[str] = []
    for raw_value in fields.get(category_path, []):
        if sanitized_fields:
            category = raw_value if category_path in policy.permitted_paths else None
        else:
            category = _value(raw_value, category_path, policy)["value"]
        if category and category not in categories:
            categories.append(category)
    canonical["categories"] = categories
    # Optional. Older receipts omit the path, so immutable records stay valid
    # and the description is withheld until a reviewed receipt permits it.
    description = _publisher_description(fields, rss, policy, sanitized_fields=sanitized_fields)
    if description is not None:
        canonical["description"] = description
    language_paths = [
        "item/{http://purl.org/dc/elements/1.1/}language",
        "feed/language",
        "item/@" + XML_LANG,
        "feed/@" + XML_LANG,
    ]
    for path in language_paths:
        language = _value(_scalar(fields, path), path, policy)["value"]
        if language:
            if len(language) > 64:
                raise ValueError("INTELLIGENCE_NATIVE_LANGUAGE_LIMIT")
            canonical["language"] = language
            break
    # Optional media is a reference only; no download, image copying or HTML.
    for path, values in fields.items():
        if (
            not path.startswith("item/")
            or not any(
                path.endswith(name + "/@url")
                for name in ("enclosure", MEDIA + "content", MEDIA + "thumbnail")
            )
            or path not in policy.permitted_paths
        ):
            continue
        for value in values:
            try:
                url = canonical_url(value)
            except ValueError:
                continue
            if url and {"url": url, "origin": "publisher"} not in canonical["media"]:
                canonical["media"].append({"url": url, "origin": "publisher"})
    for key in ("authors", "categories", "media"):
        if len(canonical[key]) > 100:
            raise ValueError("INTELLIGENCE_NATIVE_COLLECTION_LIMIT")
    return canonical


def _publisher_description(
    fields: dict[str, list[str | None]],
    rss: bool,
    policy: NativeMetadataPolicy,
    *,
    sanitized_fields: bool,
) -> dict[str, Any] | None:
    """Complete plain text from the publisher description. Never a truncated excerpt."""
    description_path = "item/description" if rss else "item/" + ATOM + "summary"
    if description_path not in policy.permitted_paths:
        return None
    if any(path.startswith(description_path + "/") for path in fields):
        raise ValueError("INTELLIGENCE_DESCRIPTION_NESTED_MARKUP")
    values = fields.get(description_path, [])
    if len(values) > 1:
        raise ValueError("INTELLIGENCE_NATIVE_MAPPING_AMBIGUOUS")
    raw_description = values[0] if values else None
    if raw_description is not None and len(raw_description) > 4096:
        raise ValueError("INTELLIGENCE_NATIVE_FIELD_LIMIT")
    # Writer verification rebuilds fields from the sanitized native tree.
    # Running the HTML parser again would decode literal entity text twice.
    text = (raw_description or "") if sanitized_fields else _complete_plain_text(raw_description)
    return {
        "text": text if values else None,
        "state": ("present" if text else "empty") if values else "not_provided",
        "format": "plain_text",
        "origin": "publisher",
    }


def normalize_native_item(**kwargs: Any) -> dict[str, Any]:
    """V2 identity includes eligible publisher metadata, never fetch or enrichment."""
    publisher = kwargs.pop("publisher_metadata")
    native = kwargs.pop("native_metadata")
    item = normalize_item(**kwargs)
    item.update(
        contract_version="2.0.0",
        publisher_metadata=publisher,
        native_metadata=native,
        derived_metadata={},
    )
    item["provenance"]["normalization_version"] = VERSION
    # Normalized invalid dates are null but their invalid state is retained.
    for key, state in publisher["date_states"].items():
        item["field_states"][key] = state
    item_id, content_hash, revision = item_identities(item)
    item.update(
        item_id=item_id,
        deduplication_key=item_id,
        content_sha256=content_hash,
        revision_id=revision,
    )
    validate_record("item", item)
    return item


def verify_native_item(
    item: dict[str, Any], policy: NativeMetadataPolicy, source: dict[str, Any]
) -> None:
    """Writer independently resolves authority; adapter metadata cannot self-approve."""
    policy.validate(source)
    native = item["native_metadata"]
    if native["policy_ref"] != policy.policy_ref or native["policy_sha256"] != identity_hash(
        policy.document()
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
    if (
        item["derived_metadata"]
        or item["provenance"]["parser_version"] != PARSER
        or item["publisher_metadata"]["publisher"] != permitted_text(source["organization"], 1000)
        or item["publisher_metadata"]["source_family"] != source["family"]
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    # Strict schema plus source-bound policy and native value-path checks; no raw XML.
    fields: dict[str, list[str | None]] = {}

    def value_at(value: dict[str, Any], path: str) -> None:
        retained = value["value"]
        publisher_text = path in {
            "item/description",
            "item/category",
            "item/" + ATOM + "summary",
        }
        plain_text_valid = (
            isinstance(retained, str)
            and len(retained) <= 4096
            and re.search(r"[<>\x00-\x1f\x7f]", retained) is None
            and retained == " ".join(retained.split())
        )
        if path not in policy.inventory or (
            retained is not None
            and (
                path not in policy.permitted_paths
                or (
                    not plain_text_valid
                    if publisher_text
                    else permitted_text(retained, 4096) != retained
                )
            )
        ):
            raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
        fields.setdefault(path, []).append(retained)

    def check(nodes: list[dict[str, Any]], prefix: str) -> None:
        for node in nodes:
            path = prefix + "/" + node["name"]
            value_at(node, path)
            if node["tail"]["value"] is not None or node["tail"]["state"] != "not_provided":
                value_at(node["tail"], path + "/#tail")
            for attribute in node["attributes"]:
                attr_path = path + "/@" + attribute["name"]
                value_at(attribute, attr_path)
            check(node["children"], path)

    check(native["feed"], "feed")
    check(native["item"], "item")
    for scope in ("feed", "item"):
        for attribute in native[scope + "_attributes"]:
            value_at(attribute, scope + "/@" + attribute["name"])
    if native["inventory"] != sorted(fields):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    if not policy.required_paths <= set(fields):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    rss = source["transport"] == "rss"
    for key, name in (("title", "title"), ("excerpt", "description" if rss else "summary")):
        path = "item/" + (name if rss else ATOM + name)
        if item[key] is not None and any(
            p == path or p.startswith(path + "/") for p in fields if p not in policy.permitted_paths
        ):
            raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
    if item["canonical_url"] is not None and not _url_paths_permitted(fields, policy, rss):
        raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
    for key, date_path, dialect in (
        ("published_at", policy.published_path, policy.published_format),
        ("updated_at", policy.updated_path, policy.updated_format),
    ):
        date = native["publisher_dates"][key]
        retained = _scalar(fields, date_path)
        if date["raw"] is None and (
            date["normalized"] is not None or date["state"] not in {"not_provided", "withheld"}
        ):
            raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
        if date_path in policy.permitted_paths and retained is not None and date["raw"] is None:
            raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
        if date["raw"] is not None and permitted_text(date["raw"], 4096) != retained:
            raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
        if date["raw"] is not None and date != _date(date["raw"], dialect, date_path, policy):
            raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
        if date["raw"] is not None and date_path not in policy.permitted_paths:
            raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
        if (
            date["normalized"] != item[key]
            or date["state"] != item["field_states"][key]
            or date["parser"] != dialect
        ):
            raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    if item["publisher_metadata"] != _publisher_metadata(
        fields, source, policy, native, sanitized_fields=True
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    expected_topics = [
        {
            "value": category,
            "origin": "publisher",
            "method": None,
            "method_version": None,
            "confidence": None,
        }
        for category in item["publisher_metadata"]["categories"]
        if TOKEN.fullmatch(category)
    ]
    if item["topics"] != expected_topics or item["geographies"]:
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    if len(canonical_json(native).encode()) > 65536:
        raise ValueError("INTELLIGENCE_NATIVE_METADATA_LIMIT")
