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
        for term in terms.values():
            params = dict(catalog.get("fixed_query_parameters", {}))
            params[catalog["search_parameter"]] = term
            requests.append(
                DiscoveryRequest(
                    catalog["catalog_id"],
                    term,
                    f"{catalog['search_endpoint']}?{urlencode(params)}",
                    {},
                )
            )
    return requests


def fetch_json(request: DiscoveryRequest, timeout_seconds: int = 20) -> dict[str, Any]:
    http_request = Request(request.url, headers=request.headers)
    with urlopen(http_request, timeout=timeout_seconds) as response:  # nosec B310: configured HTTPS catalogs
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return payload
