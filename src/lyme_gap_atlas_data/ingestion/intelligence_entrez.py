"""Bounded PubMed Entrez capture for the two approved draft searches.

Both searches run together. PMID duplicates collapse to one item. The transport
is Entrez, stored on contract 2.0.0. This module does not register a PROD source,
open Snowflake, or read a secret from the environment on its own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import httpx

from ..intelligence_items import (
    ACQUISITION_VERSION,
    TOKEN,
    canonical_timestamp,
    canonical_url,
    identity_hash,
    item_identities,
    normalize_item,
    permitted_text,
    validate_record,
)
from ..intelligence_metadata import VERSION, NativeMetadataPolicy
from ..intelligence_raw_runtime import FeedRawRetention
from ..settings import PipelineSettings
from .adapters import AcquisitionError
from .intelligence_feed import adapter_for_source
from .types import RunState, RunStatus, Stage, StageCheckpoint, StageStatus, Tier

SOURCE_ORDER = ("pubmed-tick-borne", "pubmed-lyme-borrelia")
QUERY_PINS = {
    "pubmed-tick-borne": (
        "pubmed-tick-borne-v2",
        "f27a4920500a0a9946f93e17ddff5c951906fb8da27a1a9c38f1ca68ea03bb14",
    ),
    "pubmed-lyme-borrelia": (
        "pubmed-lyme-borrelia-v1",
        "d872dae70d05fa55c9a86f086c3c62063db4a886d62a0673d1e89158c1ea5259",
    ),
}
EUTILS_HOST = "eutils.ncbi.nlm.nih.gov"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ENTREZ_TOOL = "one_health_lyme_gap_atlas"
PARSER = "entrez-efetch-v1"
FETCH = "entrez-eutils-v1"
NLM_ATTRIBUTION = "Courtesy of the U.S. National Library of Medicine"
NLM_POLICY_URL = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config" / "intelligence"
SELECTION_PATH = CONFIG_DIR / "feed-selection-v1.json"
RECEIPT_PATH = CONFIG_DIR / "pubmed-policy-receipts.json"
SUPPRESSION_PATH = CONFIG_DIR / "pubmed-abstract-suppressions.json"
MAX_REQUESTS = 5
REFRESH_REQUESTS = 3
MAX_ITEMS = 200
BATCH_SIZE = 67
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MIN_INTERVAL_SECONDS = 0.4
FIRST_WINDOW_DAYS = 30
OVERLAP_DAYS = 2
REFRESH_DAYS = 60
ABSTRACT_LIMIT = 6000
AUTHOR_LIMIT = 20
MESH_LIMIT = 50
KEYWORD_LIMIT = 50
REQUEST_TIMEOUT_SECONDS = 30.0
PMID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
MESH_UI_RE = re.compile(r"^[A-Z][0-9]{6}$")
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
ENTREZ_PERMITTED_PATHS = frozenset(
    {
        "PubmedArticle/MedlineCitation/PMID",
        "PubmedArticle/MedlineCitation/Article/ArticleTitle",
        "PubmedArticle/MedlineCitation/Article/Language",
        "PubmedArticle/MedlineCitation/Article/Journal/Title",
        "PubmedArticle/MedlineCitation/Article/Journal/JournalIssue/PubDate",
        "PubmedArticle/MedlineCitation/Article/Abstract/AbstractText",
        "PubmedArticle/MedlineCitation/Article/Abstract/CopyrightInformation",
        "PubmedArticle/MedlineCitation/Article/AuthorList/Author",
        "PubmedArticle/MedlineCitation/KeywordList/Keyword",
        "PubmedArticle/MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName",
        "PubmedArticle/MedlineCitation/Article/PublicationTypeList/PublicationType",
        "PubmedArticle/PubmedData/ArticleIdList/ArticleId",
        "PubmedArticle/PubmedData/History/PubMedPubDate",
    }
)
PUBLISHED_PATH = "PubmedArticle/MedlineCitation/Article/Journal/JournalIssue/PubDate"
ENTREZ_DAILY_RESOURCE = "pubmed-entrez"
# Publisher suppression matches the journal title from Journal/Title, exactly.
_DROPPED_ELEMENTS = {"script", "style", "iframe", "object"}
_DROPPED_MARKUP = re.compile(
    r"<(script|style|iframe|object)\b[^<>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DROPPED_TO_END = re.compile(
    r"<(script|style|iframe|object)\b[^<>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_REAL_TAG = re.compile(r"</?[A-Za-z][^<>]*>")


class RequestBudget(Protocol):
    requests: int
    request_limit: int

    def reserve(self) -> float: ...

    def remaining(self) -> float: ...


class EntrezSender(Protocol):
    def __call__(self, url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse: ...


@dataclass(frozen=True)
class EntrezResponse:
    status: int
    body: bytes


@dataclass
class EntryDateLedger:
    """Per-source last_entry_date values for the checkpoint detail."""

    dates: dict[str, date]

    def __init__(self, dates: dict[str, date] | None = None) -> None:
        self.dates = dict(dates or {})

    def get(self, source_id: str) -> date | None:
        return self.dates.get(source_id)

    def set(self, source_id: str, day: date) -> None:
        self.dates[source_id] = day


@dataclass
class RevisionLedger:
    """In-memory stand-in for the capture merge: one revision key is inserted once."""

    keys: set[tuple[str, str]]

    def __init__(self) -> None:
        self.keys = set()

    def apply(self, items: list[dict[str, Any]]) -> int:
        added = 0
        for item in items:
            key = (item["item_id"], item["revision_id"])
            if key not in self.keys:
                self.keys.add(key)
                added += 1
        return added


@dataclass
class PubmedOutcome:
    items: list[dict[str, Any]]
    requests: int
    truncated: bool
    remaining: int
    revisions_inserted: int
    watermarks: dict[str, str]
    withheld_abstracts: int
    windows: dict[str, tuple[str, str]]
    response_body: bytes = b""


def withhold_overlong_pubmed_abstract(text: str) -> bool:
    """Whether a sanitized abstract is longer than ABSTRACT_LIMIT.

    The paper is still stored. Its abstract state is withheld and its text is
    null. The characters are not truncated, and the 6000-character cap stays.
    """
    return len(text) > ABSTRACT_LIMIT


def entry_window(last_entry_date: date | None, today: date) -> tuple[date, date]:
    """First capture looks back 30 days. Later captures overlap the watermark by 2 days."""
    if last_entry_date is None:
        return today - timedelta(days=FIRST_WINDOW_DAYS), today
    return last_entry_date - timedelta(days=OVERLAP_DAYS), today


def accepted_pmid(value: object) -> bool:
    """True when value is the API PMID shape: 1 to 10 digits and no leading zero."""
    return isinstance(value, str) and PMID_RE.fullmatch(value) is not None


def ncbi_day(day: date) -> str:
    return day.strftime("%Y/%m/%d")


def encode_entrez_query(params: Mapping[str, str]) -> str:
    """Encode one E-utilities query. A space becomes '+' once; a plus sign is not pre-encoded."""
    return urlencode(list(params.items()))


class _DropRequestUrl(logging.Filter):
    """Hide one request's URL for the duration of that call. The logger level stays as it was."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return False
        return EUTILS_HOST not in message and "api_key" not in message and "email=" not in message


def read_bounded(chunks: Iterable[bytes], limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a response until the byte cap. Further chunks are not pulled after the cap."""
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise AcquisitionError("FEED_TOO_LARGE", code="FEED_TOO_LARGE")
        parts.append(chunk)
    return b"".join(parts)


def live_entrez_get(url: str, params: Mapping[str, str], timeout: float) -> EntrezResponse:
    """One HTTPS GET to E-utilities. Callers supply this; tests use recorded responses."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != EUTILS_HOST or parts.username or parts.password:
        raise AcquisitionError("FEED_HOST_NOT_APPROVED", code="FEED_HOST_NOT_APPROVED")
    logger = logging.getLogger("httpx")
    redaction = _DropRequestUrl()
    logger.addFilter(redaction)
    try:
        with (
            httpx.Client(timeout=timeout, follow_redirects=False) as client,
            client.stream("GET", url, params=dict(params)) as response,
        ):
            body = read_bounded(response.iter_bytes())
            status = response.status_code
    except AcquisitionError:
        raise
    except Exception:
        raise AcquisitionError("FEED_HTTP_FAILED", code="FEED_HTTP_FAILED") from None
    finally:
        logger.removeFilter(redaction)
    return EntrezResponse(status, body)


def mesh_refresh_candidates(items: list[dict[str, Any]], *, today: date) -> list[str]:
    """PMIDs from the last 60 days that still have no MeSH, newest entry date first."""
    cutoff = today - timedelta(days=REFRESH_DAYS)
    pending: list[tuple[date, str]] = []
    for item in items:
        metadata = item["publisher_metadata"]
        if metadata.get("mesh"):
            continue
        raw_date = metadata.get("entry_date")
        pmid = metadata.get("source_item_id")
        if not isinstance(raw_date, str) or not isinstance(pmid, str):
            continue
        try:
            entered = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if entered >= cutoff:
            pending.append((entered, pmid))
    pending.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [pmid for _, pmid in pending[:MAX_ITEMS]]


def load_suppressions(
    path: Path = SUPPRESSION_PATH,
) -> tuple[frozenset[str], frozenset[str]]:
    """PMID set plus publisher set. A publisher value is the journal title, matched exactly."""
    document = json.loads(path.read_text(encoding="utf-8"))
    pmids = document.get("pmids")
    publishers = document.get("publishers")
    if (
        set(document) != {"pmids", "publishers"}
        or not isinstance(pmids, list)
        or not isinstance(publishers, list)
        or any(not accepted_pmid(value) for value in pmids)
        or any(not isinstance(value, str) or not value for value in publishers)
    ):
        raise PermissionError("INTELLIGENCE_PUBMED_SUPPRESSION_INVALID")
    return frozenset(pmids), frozenset(publishers)


def verify_entrez_item(
    item: dict[str, Any], policy: NativeMetadataPolicy, source: dict[str, Any]
) -> None:
    """Writer check for an Entrez item. RSS native verification stays on its own path."""
    policy.validate(source)
    native = item["native_metadata"]
    publisher = item["publisher_metadata"]
    abstract = publisher.get("abstract")
    queries = publisher.get("matched_queries")
    if (
        source["transport"] != "entrez"
        or item["transport"] != "entrez"
        or adapter_for_source(source) != "entrez"
        or item["excerpt"] is not None
        or item["derived_metadata"]
        or item["provenance"]["parser_version"] != PARSER
        or source["family"] != "pubmed"
        or publisher.get("source_family") != "pubmed"
        or publisher.get("publisher") != permitted_text(source["organization"], 1000)
        or native.get("policy_ref") != policy.policy_ref
        or native.get("policy_sha256") != identity_hash(policy.document())
        or native.get("inventory") != sorted(policy.inventory)
        or policy.permitted_paths != ENTREZ_PERMITTED_PATHS
        or policy.published_path != PUBLISHED_PATH
        or not isinstance(abstract, dict)
        or not isinstance(queries, list)
        or not queries
        or queries != [source_id for source_id in SOURCE_ORDER if source_id in queries]
        or item["source_id"] != queries[0]
        or len(publisher.get("authors", [])) > AUTHOR_LIMIT
        or len(publisher.get("categories", [])) > KEYWORD_LIMIT
        or len(publisher.get("mesh", [])) > MESH_LIMIT
        or len(publisher.get("publication_types", [])) > MESH_LIMIT
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")
    if (
        abstract.get("state") in {"suppressed", "not_provided", "withheld"}
        and abstract.get("text") is not None
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
    if abstract.get("text") and item["excerpt"] == abstract["text"]:
        raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
    pmid = publisher.get("source_item_id")
    expected_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if (
        not accepted_pmid(pmid)
        or item.get("canonical_url") != expected_url
        or canonical_url(expected_url) != expected_url
    ):
        raise PermissionError("INTELLIGENCE_NATIVE_MAPPING_INVALID")


def run_pubmed_daily(
    *,
    today: date,
    sender: EntrezSender,
    settings: PipelineSettings,
    budget: RequestBudget,
    fetched_at: str,
    run_id: str,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    checkpoints: EntryDateLedger | None = None,
    revisions: RevisionLedger | None = None,
    suppress_pmids: frozenset[str] | None = None,
    suppress_publishers: frozenset[str] | None = None,
    sources: Mapping[str, dict[str, Any]] | None = None,
    receipt_document: dict[str, Any] | None = None,
    run_ids: Mapping[str, str] | None = None,
    artifact_ids: Mapping[str, str] | None = None,
) -> PubmedOutcome:
    """Run both approved searches once, then efetch the deduped PMID union."""
    loaded = dict(sources) if sources is not None else _load_sources()
    if sources is not None:
        _require_run_sources(loaded)
    queries = _load_queries()
    policies = _load_policies(loaded, receipt_document)
    if suppress_pmids is None or suppress_publishers is None:
        file_pmids, file_publishers = load_suppressions()
        suppress_pmids = file_pmids if suppress_pmids is None else suppress_pmids
        suppress_publishers = (
            file_publishers if suppress_publishers is None else suppress_publishers
        )
    ledger = checkpoints or EntryDateLedger()
    windows = {source_id: entry_window(ledger.get(source_id), today) for source_id in SOURCE_ORDER}
    session = _EntrezSession(
        sender=sender,
        settings=settings,
        budget=budget,
        clock=clock,
        sleep=sleep,
        request_cap=MAX_REQUESTS,
    )
    found: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for source_id in SOURCE_ORDER:
        start, end = windows[source_id]
        pmids, count = session.esearch(queries[source_id], start, end)
        found[source_id] = pmids
        counts[source_id] = count
    ranked = _merge_pmids(found)
    hidden = sum(max(0, counts[source_id] - len(found[source_id])) for source_id in SOURCE_ORDER)
    selected = ranked[:MAX_ITEMS]
    truncated = len(ranked) + hidden > MAX_ITEMS
    remaining = len(ranked) + hidden - len(selected)
    by_query = {pmid: queries_for for pmid, queries_for in selected}
    records: dict[str, _Record] = {}
    withheld = 0
    for batch in _chunks([pmid for pmid, _queries in selected], BATCH_SIZE):
        for record in _parse_efetch(session.efetch(batch)):
            if record.pmid in by_query and record.pmid not in records:
                records[record.pmid] = record
    artifact_sha = hashlib.sha256(b"".join(session.bodies)).hexdigest()
    items: list[dict[str, Any]] = []
    for pmid, matched in selected:
        stored = records.get(pmid)
        if stored is None:
            continue
        owner = matched[0]
        if run_ids is not None and owner not in run_ids:
            continue
        if stored.abstract_withheld:
            withheld += 1
        items.append(
            _build_item(
                stored,
                matched=matched,
                sources=loaded,
                policies=policies,
                fetched_at=fetched_at,
                run_id=run_ids[owner] if run_ids is not None else run_id,
                artifact_sha=artifact_sha,
                artifact_id=(artifact_ids[owner] if artifact_ids is not None else "pubmed-efetch"),
                suppress_pmids=suppress_pmids,
                suppress_publishers=suppress_publishers,
            )
        )
    watermarks = _advance_watermarks(ledger, items, truncated=truncated)
    inserted = revisions.apply(items) if revisions is not None else 0
    return PubmedOutcome(
        items=items,
        requests=budget.requests,
        truncated=truncated,
        remaining=remaining,
        revisions_inserted=inserted,
        watermarks=watermarks,
        withheld_abstracts=withheld,
        windows={
            source_id: (ncbi_day(start), ncbi_day(end))
            for source_id, (start, end) in windows.items()
        },
        response_body=b"".join(session.bodies),
    )


def refresh_pubmed_mesh(
    pmids: list[str],
    *,
    sender: EntrezSender,
    settings: PipelineSettings,
    budget: RequestBudget,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, list[dict[str, str]]]:
    """Weekly MeSH refresh. At most 200 PMIDs and 3 efetch requests, on its own budget."""
    chosen = []
    for pmid in pmids:
        if not accepted_pmid(pmid):
            continue
        if pmid not in chosen:
            chosen.append(pmid)
        if len(chosen) == MAX_ITEMS:
            break
    session = _EntrezSession(
        sender=sender,
        settings=settings,
        budget=budget,
        clock=clock,
        sleep=sleep,
        request_cap=REFRESH_REQUESTS,
    )
    found: dict[str, list[dict[str, str]]] = {}
    for batch in _chunks(chosen, BATCH_SIZE):
        for record in _parse_efetch(session.efetch(batch)):
            found[record.pmid] = record.mesh
    return found


@dataclass
class _Record:
    pmid: str
    title: str
    journal: str | None
    doi: str | None
    language: str | None
    published_at: str | None
    entry_date: date | None
    authors: list[str]
    categories: list[str]
    mesh: list[dict[str, str]]
    publication_types: list[str]
    abstract_text: str | None
    copyright_line: str | None
    abstract_withheld: bool = False


class _EntrezSession:
    def __init__(
        self,
        *,
        sender: EntrezSender,
        settings: PipelineSettings,
        budget: RequestBudget,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
        request_cap: int,
    ) -> None:
        self._sender = sender
        self._settings = settings
        self._budget = budget
        self._clock = clock
        self._sleep = sleep
        self._request_cap = request_cap
        self._last: float | None = None
        self.bodies: list[bytes] = []

    def esearch(self, term: str, start: date, end: date) -> tuple[list[str], int]:
        body = self._get(
            ESEARCH_URL,
            {
                **self._contact(),
                "db": "pubmed",
                "term": term,
                "datetype": "edat",
                "mindate": ncbi_day(start),
                "maxdate": ncbi_day(end),
                "retmax": str(MAX_ITEMS),
                "usehistory": "n",
                "retmode": "json",
                "sort": "most recent",
            },
        )
        return _parse_esearch(body)

    def efetch(self, pmids: list[str]) -> bytes:
        if not pmids or len(pmids) > BATCH_SIZE:
            raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID")
        return self._get(
            EFETCH_URL,
            {**self._contact(), "db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        )

    def _contact(self) -> dict[str, str]:
        email = self._settings.ncbi_email
        if (
            not isinstance(email, str)
            or not email.strip()
            or email != email.strip()
            or len(email) > 320
            or _has_control(email)
        ):
            raise PermissionError("NCBI_CONTACT_REQUIRED")
        return {"tool": ENTREZ_TOOL, "email": email}

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = MIN_INTERVAL_SECONDS - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                if self._clock() - self._last + 1e-9 < MIN_INTERVAL_SECONDS:
                    raise AcquisitionError(
                        "INTELLIGENCE_PUBMED_INTERVAL_REQUIRED",
                        code="INTELLIGENCE_PUBMED_INTERVAL_REQUIRED",
                    )
        self._last = self._clock()

    def _get(self, url: str, params: dict[str, str]) -> bytes:
        self._pace()
        if self._budget.requests >= min(self._budget.request_limit, self._request_cap):
            raise PermissionError("INTELLIGENCE_PILOT_REQUEST_LIMIT")
        remaining = self._budget.reserve()
        try:
            response = self._sender(url, params, min(REQUEST_TIMEOUT_SECONDS, remaining))
        except AcquisitionError:
            raise
        except Exception:
            raise AcquisitionError("FEED_HTTP_FAILED", code="FEED_HTTP_FAILED") from None
        self._budget.remaining()
        if response.status == 403:
            raise AcquisitionError("FEED_HTTP_403", code="FEED_HTTP_403")
        if response.status == 429:
            raise AcquisitionError("FEED_RATE_LIMITED", code="FEED_RATE_LIMITED")
        if response.status != 200:
            raise AcquisitionError("FEED_HTTP_FAILED", code="FEED_HTTP_FAILED")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise AcquisitionError("FEED_TOO_LARGE", code="FEED_TOO_LARGE")
        self.bodies.append(response.body)
        return response.body


def _load_sources() -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for source_id in SOURCE_ORDER:
        path = CONFIG_DIR / f"{source_id}-source-v1.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        validate_record("source", source)
        draft = (
            source["state"] == "candidate"
            and source["approval"]["status"] == "pending"
            and source["trust_review"]["status"] == "pending"
        )
        if (
            source["source_id"] != source_id
            or source["registry_version"] != 1
            or source["state"] not in {"candidate", "active"}
            or (source["state"] == "candidate" and not draft)
            or source["transport"] != "entrez"
            or source["family"] != "pubmed"
            or source["fetch_location"] != ESEARCH_URL
            or source["limits"]["maximum_items"] != MAX_ITEMS
            or source["limits"]["maximum_bytes"] != MAX_RESPONSE_BYTES
            or source["limits"]["timeout_seconds"] != 30
            or source["limits"]["maximum_attempts"] != 1
        ):
            raise PermissionError("INTELLIGENCE_PUBMED_DRAFT_UNREGISTERED")
        sources[source_id] = source
    return sources


def _require_run_sources(sources: Mapping[str, dict[str, Any]]) -> None:
    """Sources supplied by the daily walk. They stay Entrez and inside the same caps."""
    if set(sources) != set(SOURCE_ORDER):
        raise PermissionError("INTELLIGENCE_PUBMED_DRAFT_UNREGISTERED")
    for source_id, source in sources.items():
        if (
            source.get("source_id") != source_id
            or source.get("transport") != "entrez"
            or source.get("family") != "pubmed"
            or source.get("state") not in {"candidate", "active"}
            or source.get("fetch_location") != ESEARCH_URL
            or source.get("limits", {}).get("maximum_items") != MAX_ITEMS
            or source.get("limits", {}).get("maximum_bytes") != MAX_RESPONSE_BYTES
        ):
            raise PermissionError("INTELLIGENCE_PUBMED_DRAFT_UNREGISTERED")


def _load_queries() -> dict[str, str]:
    document = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for entry in document.get("sources", []):
        source_id = entry.get("source_id") if isinstance(entry, dict) else None
        if source_id not in QUERY_PINS:
            continue
        version, digest = QUERY_PINS[source_id]
        if (
            entry.get("decision") != "approved"
            or entry.get("query_version") != version
            or entry.get("query_sha256") != digest
            or not isinstance(entry.get("query"), str)
            or not entry["query"]
        ):
            raise PermissionError("INTELLIGENCE_PUBMED_QUERY_REQUIRED")
        found[source_id] = entry["query"]
    if set(found) != set(SOURCE_ORDER):
        raise PermissionError("INTELLIGENCE_PUBMED_QUERY_REQUIRED")
    return found


def _load_policies(
    sources: Mapping[str, dict[str, Any]], document: dict[str, Any] | None = None
) -> dict[str, NativeMetadataPolicy]:
    if document is None:
        document = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    receipts = document.get("receipts")
    if not isinstance(receipts, list) or len(receipts) != len(SOURCE_ORDER):
        raise PermissionError("INTELLIGENCE_PUBMED_RECEIPT_REQUIRED")
    policies: dict[str, NativeMetadataPolicy] = {}
    for receipt in receipts:
        source_id = receipt.get("source_id")
        source = sources.get(source_id)
        native = receipt.get("native_policy")
        if (
            source is None
            or not isinstance(native, dict)
            or receipt.get("registry_version") != 1
            or receipt.get("source_sha256") != identity_hash(source)
            or native.get("source_sha256") != identity_hash(source)
        ):
            raise PermissionError("INTELLIGENCE_PUBMED_RECEIPT_REQUIRED")
        policy = NativeMetadataPolicy(
            policy_ref=native["policy_ref"],
            source_sha256=native["source_sha256"],
            inventory=frozenset(native["inventory"]),
            permitted_paths=frozenset(native["permitted_paths"]),
            required_paths=frozenset(native["required_paths"]),
            published_path=native["published_path"],
            published_format=native["published_format"],
            updated_path=native.get("updated_path"),
            updated_format=native.get("updated_format", "iso8601"),
        )
        policy.validate(source)
        if (
            policy.permitted_paths != ENTREZ_PERMITTED_PATHS
            or policy.published_path != PUBLISHED_PATH
        ):
            raise PermissionError("INTELLIGENCE_PUBMED_RECEIPT_REQUIRED")
        policies[source_id] = policy
    if set(policies) != set(SOURCE_ORDER):
        raise PermissionError("INTELLIGENCE_PUBMED_RECEIPT_REQUIRED")
    return policies


def _merge_pmids(found: Mapping[str, list[str]]) -> list[tuple[str, tuple[str, ...]]]:
    rank: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for source_id in SOURCE_ORDER:
        for position, pmid in enumerate(found[source_id]):
            matched.setdefault(pmid, [])
            if source_id not in matched[pmid]:
                matched[pmid].append(source_id)
            previous = rank.get(pmid)
            if previous is None or position < previous:
                rank[pmid] = position
    ordered = sorted(
        matched,
        key=lambda pmid: (rank[pmid], SOURCE_ORDER.index(matched[pmid][0]), pmid),
    )
    return [(pmid, tuple(matched[pmid])) for pmid in ordered]


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _parse_esearch(body: bytes) -> tuple[list[str], int]:
    try:
        result = json.loads(body)["esearchresult"]
        if "ERROR" in result:
            raise ValueError
        count = int(result["count"])
        raw_ids = result["idlist"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID") from None
    too_many = not isinstance(raw_ids, list) or len(raw_ids) > MAX_ITEMS or count < len(raw_ids)
    if count < 0 or too_many:
        raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID")
    pmids: list[str] = []
    for pmid in raw_ids:
        if not accepted_pmid(pmid):
            continue
        if pmid not in pmids:
            pmids.append(pmid)
    return pmids, count


def _parse_efetch(body: bytes) -> list[_Record]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID") from None
    records: list[_Record] = []
    for article in root.findall("PubmedArticle"):
        record = _record_from_article(article)
        if record is not None:
            records.append(record)
        if len(records) > BATCH_SIZE:
            raise AcquisitionError("FEED_PAYLOAD_INVALID", code="FEED_PAYLOAD_INVALID")
    return records


def _record_from_article(article: ET.Element) -> _Record | None:
    citation = article.find("MedlineCitation")
    paper = citation.find("Article") if citation is not None else None
    if citation is None or paper is None:
        return None
    pmid = _plain(citation.find("PMID"))
    title = permitted_text(_plain(paper.find("ArticleTitle")), 1000)
    if not accepted_pmid(pmid) or not title:
        return None
    published, _raw = _complete_date(paper.find("Journal/JournalIssue/PubDate"))
    entry, _entry_raw = _entry_date(article)
    abstract_text, copyright, abstract_withheld = _abstract(paper)
    return _Record(
        pmid=pmid,
        title=title,
        journal=permitted_text(_plain(paper.find("Journal/Title")), 1000),
        doi=_doi(article),
        language=permitted_text(_plain(paper.find("Language")), 64),
        published_at=f"{published.isoformat()}T00:00:00Z" if published else None,
        entry_date=entry,
        authors=_authors(paper),
        categories=_keywords(citation),
        mesh=_mesh(citation),
        publication_types=_publication_types(paper),
        abstract_text=abstract_text,
        copyright_line=copyright,
        abstract_withheld=abstract_withheld,
    )


def _abstract(paper: ET.Element) -> tuple[str | None, str | None, bool]:
    parts: list[str] = []
    for node in paper.findall("Abstract/AbstractText"):
        label = node.attrib.get("Label") or ""
        text = _visible_text(node)
        if _has_control(label):
            label = ""
        parts.append(f"{label}: {text}" if label else text)
    raw = "\n".join(parts)
    copyright_node = paper.find("Abstract/CopyrightInformation")
    raw_copyright = "".join(copyright_node.itertext()).strip() if copyright_node is not None else ""
    # Same look-alike mapping as abstracts, so a literal "<" cannot fail the API text check.
    copyright: str | None = sanitize_abstract_text(raw_copyright)
    if not copyright or len(copyright) > 1000:
        copyright = None
    if not raw.strip():
        return None, copyright, False
    sanitized, withheld = _sanitize_abstract(raw)
    return sanitized, copyright, withheld


def sanitize_abstract_text(value: str) -> str:
    """Plain text. Real tags are removed. A bare '<' or '>' is kept as a fullwidth look-alike."""
    text = value
    previous: str | None = None
    while previous != text:
        previous = text
        text = _DROPPED_MARKUP.sub("", text)
    text = _DROPPED_TO_END.sub("", text)
    text = _REAL_TAG.sub("", text)
    text = text.replace("<", "\uff1c").replace(">", "\uff1e")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return " ".join(text.split())


def _sanitize_abstract(value: str) -> tuple[str | None, bool]:
    sanitized = sanitize_abstract_text(value)
    if withhold_overlong_pubmed_abstract(sanitized):
        return None, True
    return (sanitized or None), False


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _visible_text(node: ET.Element) -> str:
    """Element text with script, style, iframe and object subtrees omitted."""
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in list(node):
        if _local_name(child.tag) in _DROPPED_ELEMENTS:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_visible_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _authors(paper: ET.Element) -> list[str]:
    names: list[str] = []
    for author in paper.findall("AuthorList/Author"):
        collective = permitted_text(_plain(author.find("CollectiveName")), 4096)
        fore = permitted_text(_plain(author.find("ForeName")), 4096) or ""
        last = permitted_text(_plain(author.find("LastName")), 4096) or ""
        name = collective or " ".join(part for part in (fore, last) if part)
        if name:
            names.append(name)
    if len(names) > AUTHOR_LIMIT:
        return [*names[: AUTHOR_LIMIT - 1], "et al."]
    return names


def _keywords(citation: ET.Element) -> list[str]:
    values: list[str] = []
    for node in citation.findall("KeywordList/Keyword"):
        keyword = permitted_text(_plain(node), 4096)
        if keyword and keyword not in values:
            values.append(keyword)
        if len(values) == KEYWORD_LIMIT:
            break
    return values


def _mesh(citation: ET.Element) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in citation.findall("MeshHeadingList/MeshHeading/DescriptorName"):
        ui = node.attrib.get("UI", "")
        name = permitted_text(_plain(node), 1000)
        if MESH_UI_RE.fullmatch(ui) is None or not name or ui in seen:
            continue
        seen.add(ui)
        values.append({"name": name, "ui": ui})
        if len(values) == MESH_LIMIT:
            break
    return values


def _publication_types(paper: ET.Element) -> list[str]:
    values: list[str] = []
    for node in paper.findall("PublicationTypeList/PublicationType"):
        label = permitted_text(_plain(node), 256)
        if label and label not in values:
            values.append(label)
        if len(values) == MESH_LIMIT:
            break
    return values


def _doi(article: ET.Element) -> str | None:
    for node in article.findall("PubmedData/ArticleIdList/ArticleId"):
        if node.attrib.get("IdType") == "doi":
            return permitted_text(_plain(node), 4096)
    return None


def _entry_date(article: ET.Element) -> tuple[date | None, str | None]:
    for node in article.findall("PubmedData/History/PubMedPubDate"):
        if node.attrib.get("PubStatus") == "entrez":
            return _complete_date(node)
    return None, None


def _complete_date(node: ET.Element | None) -> tuple[date | None, str | None]:
    if node is None:
        return None, None
    year = _plain(node.find("Year"))
    month = _plain(node.find("Month"))
    day = _plain(node.find("Day"))
    raw = " ".join(part for part in (year, month, day) if part) or None
    if not (len(year) == 4 and year.isdigit() and day.isdigit()):
        return None, raw
    month_number = int(month) if month.isdigit() else MONTHS.get(month.lower()[:3], 0)
    try:
        return date(int(year), month_number, int(day)), raw
    except ValueError:
        return None, raw


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _plain(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _build_item(
    record: _Record,
    *,
    matched: tuple[str, ...],
    sources: Mapping[str, dict[str, Any]],
    policies: Mapping[str, NativeMetadataPolicy],
    fetched_at: str,
    run_id: str,
    artifact_sha: str,
    suppress_pmids: frozenset[str],
    suppress_publishers: frozenset[str],
    artifact_id: str = "pubmed-efetch",
) -> dict[str, Any]:
    source_id = matched[0]
    source = sources[source_id]
    policy = policies[source_id]
    # Publisher suppression matches the journal title exactly, not the publisher organization.
    suppressed = record.pmid in suppress_pmids or (
        record.journal is not None and record.journal in suppress_publishers
    )
    if suppressed:
        abstract: dict[str, Any] = {
            "text": None,
            "state": "suppressed",
            "copyright_line": record.copyright_line,
            "attribution": NLM_ATTRIBUTION,
            "policy_url": NLM_POLICY_URL,
        }
    elif record.abstract_withheld:
        abstract = {
            "text": None,
            "state": "withheld",
            "copyright_line": record.copyright_line,
            "attribution": NLM_ATTRIBUTION,
            "policy_url": NLM_POLICY_URL,
        }
    elif record.abstract_text:
        abstract = {
            "text": record.abstract_text,
            "state": "present",
            "copyright_line": record.copyright_line,
            "attribution": NLM_ATTRIBUTION,
            "policy_url": NLM_POLICY_URL,
        }
    else:
        abstract = {
            "text": None,
            "state": "not_provided",
            "copyright_line": record.copyright_line,
            "attribution": NLM_ATTRIBUTION,
            "policy_url": NLM_POLICY_URL,
        }
    topics = tuple(category for category in record.categories if TOKEN.fullmatch(category))
    item = normalize_item(
        source=source,
        transport="entrez",
        publisher_identity=record.pmid,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{record.pmid}/",
        title=record.title,
        excerpt=None,
        published_at=record.published_at,
        updated_at=None,
        fetched_at=fetched_at,
        provenance={
            "run_id": run_id,
            "artifact_id": artifact_id,
            "artifact_sha256": artifact_sha,
            "parser_version": PARSER,
            "fetch_version": FETCH,
        },
        topics=topics,
    )
    publisher = {
        "publisher": permitted_text(source["organization"], 1000),
        "source_family": source["family"],
        "source_item_id": record.pmid,
        "authors": record.authors,
        "categories": record.categories,
        "language": record.language,
        "media": [],
        "date_states": {
            "published_at": item["field_states"]["published_at"],
            "updated_at": item["field_states"]["updated_at"],
        },
        "matched_queries": list(matched),
        "mesh": record.mesh,
        "publication_types": record.publication_types,
        "journal": record.journal,
        "doi": record.doi,
        "entry_date": record.entry_date.isoformat() if record.entry_date else None,
        "abstract": abstract,
    }
    item.update(
        contract_version="2.0.0",
        publisher_metadata=publisher,
        native_metadata=_native(policy, record),
        derived_metadata={},
    )
    item["provenance"]["normalization_version"] = VERSION
    item_id, content_hash, revision = item_identities(item)
    item.update(
        item_id=item_id,
        deduplication_key=item_id,
        content_sha256=content_hash,
        revision_id=revision,
    )
    validate_record("item", item)
    verify_entrez_item(item, policy, source)
    return item


def _native(policy: NativeMetadataPolicy, record: _Record) -> dict[str, Any]:
    def node(name: str, value: str | None) -> dict[str, Any]:
        present = bool(value)
        return {
            "name": name,
            "value": value if present else None,
            "state": "present" if present else "not_provided",
            "attributes": [],
            "children": [],
            "tail": {"value": None, "state": "not_provided"},
        }

    published = {
        "raw": record.published_at,
        "raw_state": "present" if record.published_at else "not_provided",
        "normalized": record.published_at,
        "state": "present" if record.published_at else "not_provided",
        "parser": "iso8601",
    }
    return {
        "policy_ref": policy.policy_ref,
        "policy_sha256": identity_hash(policy.document()),
        "inventory": sorted(policy.inventory),
        "feed": [],
        "feed_attributes": [],
        "item": [
            node("PMID", record.pmid),
            node("ArticleTitle", record.title),
            node("JournalTitle", record.journal),
            node("Language", record.language),
        ],
        "item_attributes": [],
        "publisher_dates": {
            "published_at": published,
            "updated_at": {
                "raw": None,
                "raw_state": "not_provided",
                "normalized": None,
                "state": "not_provided",
                "parser": "iso8601",
            },
        },
    }


def _advance_watermarks(
    ledger: EntryDateLedger, items: list[dict[str, Any]], *, truncated: bool
) -> dict[str, str]:
    by_source: dict[str, list[date]] = {source_id: [] for source_id in SOURCE_ORDER}
    for item in items:
        metadata = item["publisher_metadata"]
        raw_date = metadata.get("entry_date")
        if not isinstance(raw_date, str):
            continue
        entered = date.fromisoformat(raw_date)
        for source_id in metadata["matched_queries"]:
            by_source[source_id].append(entered)
    saved: dict[str, str] = {}
    for source_id, days in by_source.items():
        if not days:
            continue
        chosen = min(days) if truncated else max(days)
        ledger.set(source_id, chosen)
        saved[source_id] = chosen.isoformat()
    return saved


class ItemWriter(Protocol):
    """IntelligenceStore.write plus the Entrez capture rows that write checks."""

    def capture_session(self) -> Any: ...

    def record_acquisition(
        self,
        *,
        source_id: str,
        registry_version: int,
        resource_key: str,
        run_id: str,
        artifact_id: str,
        context: dict[str, Any],
    ) -> None: ...

    def write(
        self,
        *,
        source_id: str,
        registry_version: int,
        resource_key: str,
        run_id: str,
        items: list[dict[str, Any]],
    ) -> Any: ...


class RunLedger(Protocol):
    """Checkpoint store shape shared by the memory ledger and the Snowflake ledger."""

    def save(self, state: RunState) -> None: ...

    def list_runs(self) -> list[RunState]: ...


def registered_entrez_sources(pinned: Mapping[str, str]) -> list[dict[str, Any]]:
    """Both PubMed sources when each file is active and its hash is pinned.

    Candidate drafts are not walked. One pinned search without the other is not a walk.
    """
    ready: list[dict[str, Any]] = []
    for source_id in SOURCE_ORDER:
        path = CONFIG_DIR / f"{source_id}-source-v1.json"
        if not path.is_file():
            return []
        source = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(source, dict)
            or source.get("source_id") != source_id
            or source.get("transport") != "entrez"
            or source.get("state") != "active"
            or pinned.get(source_id) != identity_hash(source)
        ):
            return []
        ready.append(source)
    return ready


_WATERMARK_RESOURCES = frozenset((ENTREZ_DAILY_RESOURCE, *SOURCE_ORDER))


def _succeeded_watermark_runs(checkpoints: RunLedger) -> list[RunState]:
    return [
        state
        for state in checkpoints.list_runs()
        if state.resource_key in _WATERMARK_RESOURCES and state.status is RunStatus.SUCCEEDED
    ]


def entry_dates_from_ledger(checkpoints: RunLedger) -> EntryDateLedger:
    """Latest per-source last_entry_date on a succeeded PubMed LOAD checkpoint."""
    best = -1
    chosen: dict[str, Any] = {}
    for state in _succeeded_watermark_runs(checkpoints):
        load = state.checkpoint(Stage.LOAD)
        detail = load.detail if load is not None else {}
        raw = detail.get("last_entry_date")
        sequence = detail.get("sequence")
        if not isinstance(raw, dict) or not isinstance(sequence, int) or sequence < best:
            continue
        best = sequence
        chosen = raw
    ledger = EntryDateLedger()
    for source_id in SOURCE_ORDER:
        value = chosen.get(source_id)
        if isinstance(value, str):
            ledger.set(source_id, date.fromisoformat(value))
    return ledger


def entrez_artifact_id(run_id: str) -> str:
    """One artifact id for one ingestion run. Not the shared constant pubmed-efetch."""
    return f"entrez-{run_id}"


def insert_entrez_capture_rows(
    cursor: Any,
    *,
    run_id: str,
    artifact_id: str,
    endpoint: str,
    sha256: str,
    byte_count: int,
    retention_class: str,
    fetched_at: str,
) -> str:
    """Write the request and artifact rows IntelligenceStore.write joins together."""
    request_id = f"{run_id}:ACQUIRE:1"
    cursor.execute(
        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
         endpoint, redacted_request, status_code, response_sha256, retrieved_row_count,
         created_at)
        SELECT %s, %s, 1, 'ENTREZ_ESEARCH', %s, PARSE_JSON(%s), 200, %s, %s, %s""",
        (
            request_id,
            run_id,
            endpoint,
            "{}",
            sha256,
            0,
            fetched_at,
        ),
    )
    cursor.execute(
        """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
        (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri, artifact_type,
         media_type, byte_count, sha256, retention_class, created_at)
        SELECT %s, %s, %s, %s, 'SOURCE_PAYLOAD', 'application/xml', %s, %s, %s, %s""",
        (
            artifact_id,
            run_id,
            request_id,
            f"memory://entrez/{artifact_id}",
            byte_count,
            sha256,
            retention_class,
            fetched_at,
        ),
    )
    return request_id


def prepare_entrez_source_capture(
    *,
    retention: FeedRawRetention,
    source: dict[str, Any],
    run_id: str,
    body: bytes,
    fetched_at: str,
    capture_session: Any,
) -> dict[str, Any]:
    """Bind the Entrez lease, store request and artifact rows, and return the context.

    requested_url is the esearch fetch_location. effective_url is that same endpoint,
    which is the INGESTION_REQUESTS.endpoint value. The lease policy is the source's
    30-day raw retention reference.
    """
    artifact_id = entrez_artifact_id(run_id)
    digest = hashlib.sha256(body).hexdigest()
    requested = canonical_url(source["fetch_location"])
    if not isinstance(requested, str):
        raise PermissionError("INTELLIGENCE_ACQUISITION_URL_INVALID")
    context = {
        "context_version": ACQUISITION_VERSION,
        "attempt_id": hashlib.sha256(run_id.encode()).hexdigest()[:32],
        "source_id": source["source_id"],
        "registry_version": source["registry_version"],
        "registry_sha256": identity_hash(source),
        "requested_url": requested,
        "effective_url": requested,
        "capture_mode": "https",
        "fetch_status": 200,
        "fetched_at": canonical_timestamp(fetched_at),
        "artifact_sha256": digest,
    }
    retention.bind_source(run_id, source, parser_version=PARSER, fetch_version=FETCH)
    lease_sha = retention.capture(source, context)
    locator = f"memory://entrez/{artifact_id}"
    with (
        retention.lease_access(lease_sha, "raw_object", locator, write=True),
        capture_session() as cursor,
    ):
        insert_entrez_capture_rows(
            cursor,
            run_id=run_id,
            artifact_id=artifact_id,
            endpoint=context["effective_url"],
            sha256=digest,
            byte_count=len(body),
            retention_class=source["access_use"]["content_retention_policy_ref"],
            fetched_at=context["fetched_at"],
        )
    return context


def execute_registered_entrez_daily(
    *,
    pinned: Mapping[str, str],
    sender: EntrezSender,
    settings: PipelineSettings,
    budget: RequestBudget,
    checkpoints: RunLedger,
    store: ItemWriter,
    today: date,
    run_id: str,
    fetched_at: str,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    sources: list[dict[str, Any]] | None = None,
    receipt_document: dict[str, Any] | None = None,
    run_ids: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run both searches and write items through store.write when they are registered.

    Unregistered or candidate sources return without a request. store.write is
    IntelligenceStore.write, which MERGEs revisions in bulk_write_items.
    last_entry_date is stored on the LOAD checkpoint of this ledger.
    """
    selected = sources if sources is not None else registered_entrez_sources(pinned)
    skipped: dict[str, Any] = {"walked": False, "requests": 0, "items": [], "windows": {}}
    if not selected:
        return skipped
    by_id = {source["source_id"]: source for source in selected}
    if set(by_id) != set(SOURCE_ORDER):
        return skipped
    for source_id, source in by_id.items():
        if source.get("state") != "active" or pinned.get(source_id) != identity_hash(source):
            return skipped
    ledger = entry_dates_from_ledger(checkpoints)
    retention = getattr(checkpoints, "feed_retention", None)
    planned = run_ids if run_ids is not None else {source_id: run_id for source_id in SOURCE_ORDER}
    artifact_ids = (
        {source_id: entrez_artifact_id(item_run) for source_id, item_run in planned.items()}
        if retention is not None
        else None
    )
    outcome = run_pubmed_daily(
        today=today,
        sender=sender,
        settings=settings,
        budget=budget,
        fetched_at=fetched_at,
        run_id=run_id,
        clock=clock,
        sleep=sleep,
        checkpoints=ledger,
        sources=by_id,
        receipt_document=receipt_document,
        run_ids=run_ids,
        artifact_ids=artifact_ids,
    )
    grouped: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in SOURCE_ORDER}
    for item in outcome.items:
        grouped.setdefault(item["source_id"], []).append(item)
    writers = run_ids if run_ids is not None else {source_id: run_id for source_id in SOURCE_ORDER}
    if retention is not None:
        for source_id, item_run in writers.items():
            if not grouped.get(source_id):
                continue
            context = prepare_entrez_source_capture(
                retention=retention,
                source=by_id[source_id],
                run_id=item_run,
                body=outcome.response_body,
                fetched_at=fetched_at,
                capture_session=store.capture_session,
            )
            store.record_acquisition(
                source_id=source_id,
                registry_version=int(by_id[source_id]["registry_version"]),
                resource_key=source_id,
                run_id=item_run,
                artifact_id=entrez_artifact_id(item_run),
                context=context,
            )
    for source_id in SOURCE_ORDER:
        rows = grouped.get(source_id) or []
        write_run = writers.get(source_id)
        if not rows or write_run is None:
            continue
        store.write(
            source_id=source_id,
            registry_version=int(by_id[source_id]["registry_version"]),
            resource_key=source_id,
            run_id=write_run,
            items=rows,
        )
    previous = -1
    for state in _succeeded_watermark_runs(checkpoints):
        load = state.checkpoint(Stage.LOAD)
        sequence = load.detail.get("sequence") if load is not None else None
        if isinstance(sequence, int):
            previous = max(previous, sequence)
    detail = {"last_entry_date": outcome.watermarks, "sequence": previous + 1}
    saved_runs = (
        [(run_ids[source_id], source_id) for source_id in SOURCE_ORDER if source_id in run_ids]
        if run_ids is not None
        else [(run_id, ENTREZ_DAILY_RESOURCE)]
    )
    for saved_run, resource_key in saved_runs:
        checkpoints.save(
            RunState(
                ingestion_run_id=saved_run,
                resource_key=resource_key,
                source_definition_version=1,
                tier=Tier.C,
                status=RunStatus.SUCCEEDED,
                stages=[
                    StageCheckpoint(
                        stage=Stage.LOAD,
                        status=StageStatus.COMPLETED,
                        detail=detail,
                    )
                ],
            )
        )
    return {
        "walked": True,
        "requests": outcome.requests,
        "items": outcome.items,
        "windows": outcome.windows,
        "watermarks": outcome.watermarks,
    }
