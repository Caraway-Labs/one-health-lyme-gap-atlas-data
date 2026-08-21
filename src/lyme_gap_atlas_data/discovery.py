"""Validated catalog discovery configuration and bounded HTTP adapters."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DiscoveryRequest:
    catalog_id: str
    term: str
    url: str
    headers: dict[str, str]
    pagination: dict[str, Any]


def load_search_configuration(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    if document.get("$schema_version") != "1.0":
        raise ValueError("Unsupported catalog-search configuration schema")
    groups = {group["id"]: group for group in document["term_groups"]}
    for catalog in document["catalogs"]:
        for group_id in catalog["search_term_group_ids"]:
            if group_id not in groups or not groups[group_id]["terms"]:
                raise ValueError(f"Invalid term group {group_id} for {catalog['catalog_id']}")
    return document, hashlib.sha256(raw).hexdigest()


def initial_requests(config: dict[str, Any]) -> list[DiscoveryRequest]:
    groups = {group["id"]: group for group in config["term_groups"]}
    enabled = set(config["initially_enabled_term_group_ids"])
    requests: list[DiscoveryRequest] = []
    for catalog in config["catalogs"]:
        if not catalog["enabled"]:
            continue
        terms = {
            term.casefold(): term
            for group_id in catalog["search_term_group_ids"]
            if group_id in enabled
            for term in groups[group_id]["terms"]
        }
        # These phrases intentionally remain catalog-scoped: they are useful
        # refinements for one catalog, but should not silently affect another.
        terms.update({term.casefold(): term for term in catalog.get("catalog_specific_terms", [])})
        for term in terms.values():
            params = dict(catalog.get("fixed_query_parameters", {}))
            pagination = dict(catalog.get("pagination", {}))
            if pagination.get("strategy") == "CURSOR":
                params[str(pagination["page_size_parameter"])] = pagination["page_size"]
            elif pagination.get("strategy") == "OFFSET_LIMIT":
                request_parameters = pagination["request_parameters"]
                params["limit"] = request_parameters["limit"]
                params["offset"] = 0
            params[catalog["search_parameter"]] = term
            requests.append(
                DiscoveryRequest(
                    catalog["catalog_id"],
                    term,
                    f"{catalog['search_endpoint']}?{urlencode(params)}",
                    {},
                    pagination,
                )
            )
    return requests


def next_page_request(
    request: DiscoveryRequest, payload: dict[str, Any], offset: int
) -> DiscoveryRequest | None:
    """Return the next deterministic catalog page, or ``None`` at completion."""
    pagination = request.pagination
    strategy = pagination.get("strategy")
    separator = "&" if "?" in request.url else "?"
    if strategy == "CURSOR":
        cursor = payload.get(str(pagination.get("response_field", "after")))
        if not cursor:
            return None
        parameter = str(pagination["request_parameter"])
        cursor_parameters = {
            parameter: cursor,
            str(pagination["page_size_parameter"]): pagination["page_size"],
        }
        return DiscoveryRequest(
            request.catalog_id,
            request.term,
            f"{request.url}{separator}{urlencode(cursor_parameters)}",
            request.headers,
            pagination,
        )
    if strategy == "OFFSET_LIMIT":
        results = payload.get("results", [])
        parameters = pagination["request_parameters"]
        limit = int(parameters["limit"])
        if not isinstance(results, list) or len(results) < limit:
            return None
        return DiscoveryRequest(
            request.catalog_id,
            request.term,
            f"{request.url}{separator}{urlencode({'limit': limit, 'offset': offset + limit})}",
            request.headers,
            pagination,
        )
    raise ValueError(f"Unsupported pagination strategy for {request.catalog_id}: {strategy}")


def fetch_json(request: DiscoveryRequest, timeout_seconds: int = 20) -> dict[str, Any]:
    http_request = Request(request.url, headers=request.headers)
    with urlopen(http_request, timeout=timeout_seconds) as response:  # nosec B310: configured HTTPS catalogs
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return payload
