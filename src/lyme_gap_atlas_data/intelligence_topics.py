"""Deterministic intelligence topic assignment for vocabulary v1.

`map_topics` is a pure function: the same inputs and vocabulary produce the same
matches on every run. It does not read files, call a model, or write storage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

VOCABULARY_ROOT = Path(__file__).resolve().parents[2] / "config" / "intelligence"
FALLBACK_TOPIC_ID = "other-public-health"
# The daily topic hook is opt-in. Any other value, including unset, leaves it off.
TOPICS_FLAG = "ATLAS_INTELLIGENCE_TOPICS"
VOCABULARY_VERSION_V1 = "v1"
MAX_TOPICS = 10
MAX_FIELD_CHARS = 4096
# PubMed stores a present abstract up to this cap and withholds anything longer.
MAX_ABSTRACT_CHARS = 6000
logger = logging.getLogger(__name__)
_VERSION = re.compile(r"^v[0-9]+$")
_TOPIC_IDS = frozenset(
    {
        "lyme-disease",
        "babesiosis",
        "anaplasmosis",
        "ehrlichiosis",
        "powassan",
        "alpha-gal",
        "spotted-fever-rickettsioses",
        "tick-borne-encephalitis",
        "cchf-sfts",
        "ticks-and-vectors",
        "zoonoses-one-health",
        "arboviruses",
        "foodborne-enteric",
        "respiratory",
        "vaccines",
        "antimicrobial-resistance",
        "surveillance-data",
        "diagnostics",
        FALLBACK_TOPIC_ID,
    }
)
_PAGE_SIZE = 200
_MAX_PAGES = 100
_MERGE_CHUNK = 400


class TopicMatch(TypedDict):
    topic_id: str
    matched_field: str
    matched_term: str | None


class TopicRow(TypedDict):
    item_id: str
    revision_id: str
    topic_id: str
    vocabulary_version: str
    matched_field: str
    matched_term: str | None


_TABLE_EXISTS = """
SELECT COUNT(*)
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'CONFORMED'
  AND TABLE_NAME = 'INTELLIGENCE_ITEM_TOPICS'
"""
_REVISION_PAGE = f"""
SELECT item_id, revision_id, TO_JSON(content_document)
FROM CONFORMED.INTELLIGENCE_ITEM_REVISIONS
WHERE item_id > %s OR (item_id = %s AND revision_id > %s)
ORDER BY item_id, revision_id
LIMIT {_PAGE_SIZE}
"""
_MERGE = """
MERGE INTO CONFORMED.INTELLIGENCE_ITEM_TOPICS AS target
USING (
  SELECT
    value:item_id::VARCHAR AS item_id,
    value:revision_id::VARCHAR AS revision_id,
    value:topic_id::VARCHAR AS topic_id,
    value:vocabulary_version::VARCHAR AS vocabulary_version,
    value:matched_field::VARCHAR AS matched_field,
    CASE
      WHEN value:matched_term IS NULL OR IS_NULL_VALUE(value:matched_term) THEN NULL
      ELSE value:matched_term::VARCHAR
    END AS matched_term
  FROM TABLE(FLATTEN(INPUT => PARSE_JSON(%s)))
) AS source
ON target.item_id = source.item_id
 AND target.revision_id = source.revision_id
 AND target.topic_id = source.topic_id
 AND target.vocabulary_version = source.vocabulary_version
WHEN MATCHED AND (
    target.matched_field IS DISTINCT FROM source.matched_field
    OR target.matched_term IS DISTINCT FROM source.matched_term
) THEN UPDATE SET
    matched_field = source.matched_field,
    matched_term = source.matched_term,
    computed_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    item_id, revision_id, topic_id, vocabulary_version, matched_field, matched_term
) VALUES (
    source.item_id, source.revision_id, source.topic_id, source.vocabulary_version,
    source.matched_field, source.matched_term
)
"""


def vocabulary_path(version: str) -> Path:
    """Return the versioned vocabulary file. Older versions stay beside newer ones."""
    if _VERSION.fullmatch(version) is None:
        raise ValueError("TOPIC_VOCABULARY_VERSION")
    return VOCABULARY_ROOT / f"topic-vocabulary-{version}.json"


def load_vocabulary(version: str = VOCABULARY_VERSION_V1) -> dict[str, Any]:
    """Load and validate one vocabulary file. Missing versions fail closed."""
    path = vocabulary_path(version)
    schema_path = path.with_suffix(".schema.json")
    if not path.is_file() or not schema_path.is_file():
        raise ValueError("TOPIC_VOCABULARY_VERSION")
    vocabulary = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(vocabulary, dict) or not isinstance(schema, dict):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    validator = Draft202012Validator(schema)
    if not validator.is_valid(vocabulary):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    if vocabulary.get("vocabulary_version") != version:
        raise ValueError("TOPIC_VOCABULARY_VERSION")
    topics = vocabulary.get("topics")
    if not isinstance(topics, list):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    ids = [topic["id"] for topic in topics if isinstance(topic, dict)]
    if len(ids) != len(set(ids)) or set(ids) != _TOPIC_IDS:
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    fallback = next(topic for topic in topics if topic["id"] == FALLBACK_TOPIC_ID)
    if fallback["synonyms"] or fallback["mesh_ui"] or fallback["publisher_categories"]:
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    for topic in topics:
        if topic["id"] != FALLBACK_TOPIC_ID and not topic["synonyms"]:
            raise ValueError("TOPIC_VOCABULARY_INVALID")
    return vocabulary


def map_topics(
    title: str | None,
    description: str | None,
    categories: Sequence[str] | None,
    mesh: Sequence[str | Mapping[str, Any]] | None,
    keywords: Sequence[str] | None,
    vocab: Mapping[str, Any],
    *,
    abstract: str | None = None,
) -> list[TopicMatch]:
    """Return explainable topic matches in vocabulary order, at most ten.

    A topic with no synonym, MeSH UI, or publisher-category match is omitted.
    When nothing matches, the only row is the fallback topic and its matched
    term is null. MeSH entries may be bare strings or ``{"name", "ui"}``
    objects. ``abstract`` is a separate field with the PubMed 6000-character cap.
    """
    mesh_values = _mesh_values(mesh)
    fields = {
        "title": _text(title, "title"),
        "description": _text(description, "description"),
        "abstract": _text(abstract, "abstract", limit=MAX_ABSTRACT_CHARS),
        "categories": _texts(categories, "categories"),
        "mesh": tuple(entry.text for entry in mesh_values),
        "keywords": _texts(keywords, "keywords"),
    }
    topics = vocab.get("topics")
    version = vocab.get("vocabulary_version")
    if not isinstance(topics, list) or not isinstance(version, str):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    matches: list[TopicMatch] = []
    for topic in topics:
        if not isinstance(topic, dict) or topic.get("id") == FALLBACK_TOPIC_ID:
            continue
        found = _match_topic(topic, fields, mesh_values)
        if found is None:
            continue
        matched_field, matched_term = found
        matches.append(
            {
                "topic_id": str(topic["id"]),
                "matched_field": matched_field,
                "matched_term": matched_term,
            }
        )
        if len(matches) == MAX_TOPICS:
            break
    if not matches:
        matches.append(
            {
                "topic_id": FALLBACK_TOPIC_ID,
                "matched_field": "fallback",
                "matched_term": None,
            }
        )
    return matches


def topics_hook_enabled(enabled: bool | None = None) -> bool:
    """Return whether the topic hook may run.

    The daily job does not pass ``enabled``. The hook runs only when
    ``ATLAS_INTELLIGENCE_TOPICS`` is exactly ``on``.
    """
    if enabled is not None:
        return enabled
    return os.environ.get(TOPICS_FLAG) == "on"


def topics_table_exists(cursor: Any) -> bool:
    """Return whether the conformed topic table is present in the current database."""
    cursor.execute(_TABLE_EXISTS)
    row = cursor.fetchone()
    return row is not None and int(row[0]) > 0


def topic_rows_for_items(
    items: Sequence[Mapping[str, Any]], vocabulary: Mapping[str, Any]
) -> list[TopicRow]:
    """Map stored item or revision documents without changing those documents."""
    version = str(vocabulary["vocabulary_version"])
    rows: list[TopicRow] = []
    for item in items:
        title, description, categories, mesh, keywords, abstract = inputs_from_document(item)
        for match in map_topics(
            title,
            description,
            categories,
            mesh,
            keywords,
            vocabulary,
            abstract=abstract,
        ):
            rows.append(
                {
                    "item_id": str(item["item_id"]),
                    "revision_id": str(item["revision_id"]),
                    "topic_id": match["topic_id"],
                    "vocabulary_version": version,
                    "matched_field": match["matched_field"],
                    "matched_term": match["matched_term"],
                }
            )
    return rows


def inputs_from_document(
    document: Mapping[str, Any],
) -> tuple[str | None, str | None, tuple[str, ...], Any, tuple[str, ...], str | None]:
    """Read publisher fields. A badly typed or oversized field raises."""
    if not isinstance(document, Mapping):
        raise ValueError("TOPIC_FIELD_TYPE")
    publisher = document.get("publisher_metadata")
    if publisher is None:
        publisher_map: Mapping[str, Any] = {}
    elif isinstance(publisher, Mapping):
        publisher_map = publisher
    else:
        raise ValueError("TOPIC_FIELD_TYPE")
    description_value = publisher_map.get("description")
    if isinstance(description_value, Mapping):
        description = description_value.get("text")
    else:
        description = description_value
    mesh = document.get("mesh")
    if mesh is None:
        mesh = publisher_map.get("mesh")
    return (
        _text(document.get("title"), "title"),
        _text(description, "description"),
        _texts(publisher_map.get("categories"), "categories"),
        mesh,
        _texts(document.get("keywords") or publisher_map.get("keywords"), "keywords"),
        _present_abstract(publisher_map.get("abstract")),
    )


def merge_topic_rows(cursor: Any, rows: Sequence[TopicRow]) -> int:
    """Idempotent MERGE on item, revision, topic, and vocabulary version."""
    affected = 0
    pending = list(rows)
    while pending:
        chunk = pending[:_MERGE_CHUNK]
        pending = pending[_MERGE_CHUNK:]
        payload = json.dumps(chunk, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        cursor.execute(_MERGE, (payload,))
        affected += int(cursor.rowcount or 0)
    return affected


def backfill_topics(
    cursor: Any, *, vocabulary_version: str = VOCABULARY_VERSION_V1
) -> dict[str, int]:
    """Page stored revisions and merge their topic rows.

    A badly typed item is counted, skipped, and reported in ``warnings``. The
    page continues. Repeating the call after a clean run merges the same keys.
    """
    vocabulary = load_vocabulary(vocabulary_version)
    last_item = ""
    last_revision = ""
    items = 0
    topic_rows = 0
    warnings = 0
    for _page in range(_MAX_PAGES):
        cursor.execute(_REVISION_PAGE, (last_item, last_item, last_revision))
        fetched = cursor.fetchall()
        if not fetched:
            break
        for item_id, revision_id, document_json in fetched:
            items += 1
            last_item = str(item_id)
            last_revision = str(revision_id)
            try:
                document = json.loads(document_json)
                if not isinstance(document, dict):
                    raise ValueError("TOPIC_REVISION_DOCUMENT")
                document["item_id"] = item_id
                document["revision_id"] = revision_id
                rows = topic_rows_for_items([document], vocabulary)
            except Exception:
                warnings += 1
                continue
            topic_rows += merge_topic_rows(cursor, rows)
        if len(fetched) < _PAGE_SIZE:
            break
    else:
        raise ValueError("TOPIC_BACKFILL_PAGE_LIMIT")
    if warnings:
        logger.warning("intelligence_topics step=backfill_item_skipped warnings=%s", warnings)
    return {"items": items, "topic_rows": topic_rows, "warnings": warnings}


class _MeshValue(NamedTuple):
    ui: str | None
    text: str


def _match_topic(
    topic: Mapping[str, Any],
    fields: Mapping[str, str | None | tuple[str, ...]],
    mesh_values: tuple[_MeshValue, ...],
) -> tuple[str, str] | None:
    topic_id = topic.get("id")
    if not isinstance(topic_id, str):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    patterns = tuple(_pattern(synonym) for synonym in _synonyms(topic))
    categories = _field_texts(fields, "categories")
    for category in categories:
        if category.casefold() in _folded(topic.get("publisher_categories")):
            return "categories", category
    mesh_ids = _folded(topic.get("mesh_ui"))
    for entry in mesh_values:
        candidate = entry.ui if entry.ui is not None else entry.text
        if candidate.casefold() in mesh_ids:
            return "mesh", candidate
    for field in ("title", "description", "abstract", "categories", "mesh", "keywords"):
        for text in _field_texts(fields, field):
            for pattern in patterns:
                found = pattern.search(text)
                if found is not None:
                    return field, found.group(0)
    return None


def _field_texts(fields: Mapping[str, str | None | tuple[str, ...]], field: str) -> tuple[str, ...]:
    value = fields[field]
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return value


def _synonyms(topic: Mapping[str, Any]) -> tuple[str, ...]:
    synonyms = topic.get("synonyms")
    if not isinstance(synonyms, list) or not all(isinstance(item, str) for item in synonyms):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    return tuple(synonyms)


def _folded(values: Any) -> frozenset[str]:
    if values is None:
        return frozenset()
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError("TOPIC_VOCABULARY_INVALID")
    return frozenset(item.casefold() for item in values)


def _pattern(synonym: str) -> re.Pattern[str]:
    body = re.escape(synonym.strip()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def _present_abstract(value: Any) -> str | None:
    """Return abstract text only when the publisher state is ``present``."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("TOPIC_FIELD_TYPE")
    state = value.get("state")
    if state != "present":
        if state is not None and not isinstance(state, str):
            raise ValueError("TOPIC_FIELD_TYPE")
        return None
    text = value.get("text")
    if text is not None and not isinstance(text, str):
        raise ValueError("TOPIC_FIELD_TYPE")
    return text


def _mesh_values(values: Any) -> tuple[_MeshValue, ...]:
    """Accept bare MeSH strings and PubMed ``{"name", "ui"}`` objects."""
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ValueError("TOPIC_FIELD_TYPE")
    checked: list[_MeshValue] = []
    for value in values:
        if isinstance(value, str):
            _bounded(value, "mesh", MAX_FIELD_CHARS)
            checked.append(_MeshValue(ui=None, text=value))
            continue
        if isinstance(value, Mapping) and set(value) == {"name", "ui"}:
            name = value["name"]
            ui = value["ui"]
            if not isinstance(name, str) or not isinstance(ui, str):
                raise ValueError("TOPIC_FIELD_TYPE")
            _bounded(name, "mesh", MAX_FIELD_CHARS)
            _bounded(ui, "mesh", MAX_FIELD_CHARS)
            checked.append(_MeshValue(ui=ui, text=name))
            continue
        raise ValueError("TOPIC_FIELD_TYPE")
    return tuple(checked)


def _bounded(value: str, field: str, limit: int) -> None:
    if len(value) > limit:
        raise ValueError(f"TOPIC_FIELD_LIMIT:{field}")


def _text(value: Any, field: str, *, limit: int = MAX_FIELD_CHARS) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("TOPIC_FIELD_TYPE")
    _bounded(value, field, limit)
    return value


def _texts(values: Any, field: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ValueError("TOPIC_FIELD_TYPE")
    checked: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("TOPIC_FIELD_TYPE")
        if len(value) > MAX_FIELD_CHARS:
            raise ValueError(f"TOPIC_FIELD_LIMIT:{field}")
        checked.append(value)
    return tuple(checked)
