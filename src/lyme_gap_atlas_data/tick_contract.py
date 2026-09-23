"""Stable identities for the canonical tick-surveillance contract.

This module intentionally does not normalize taxa, pathogens, methods, or
units.  Those governed mappings belong to Story #386.  It only makes the
identity dimensions needed by the site/event contract explicit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def validate_canonical_observation(observation: Mapping[str, Any]) -> None:
    """Fail closed on reviewed cross-field canonical invariants.

    Structural requirements remain in the JSON Schema. This boundary holds only
    reviewed behavioral rules which standard JSON Schema cannot express.
    """
    if observation.get("observation_type") != "PATHOGEN_TESTING":
        return

    ticks_tested = observation.get("ticks_tested")
    ticks_positive = observation.get("ticks_positive")
    prevalence = observation.get("prevalence")
    if (
        isinstance(prevalence, (int, float))
        and not isinstance(prevalence, bool)
        and (
            not isinstance(ticks_tested, int) or isinstance(ticks_tested, bool) or ticks_tested <= 0
        )
    ):
        raise ValueError("canonical PATHOGEN_TESTING prevalence requires a positive ticks_tested")
    if (
        isinstance(ticks_tested, int)
        and not isinstance(ticks_tested, bool)
        and isinstance(ticks_positive, int)
        and not isinstance(ticks_positive, bool)
        and ticks_positive > ticks_tested
    ):
        raise ValueError("canonical PATHOGEN_TESTING ticks_positive cannot exceed ticks_tested")


def canonical_observation_id(
    *,
    source_dataset_id: str,
    data_source_version_id: str,
    source_record_id: str,
    observation_type: str,
    sampling_site_id: str | None = None,
    sampling_event_id: str | None = None,
    sample_id: str | None = None,
    subsample_id: str | None = None,
    testing_id: str | None = None,
    replicate_id: str | None = None,
    strata: Mapping[str, Any] | None = None,
) -> str:
    """Return a deterministic ID without deriving a key from county geography.

    ``source_record_id`` is the immutable publisher/artifact-row anchor.  The
    supplied site, event, sample, replicate, test, and applicable stratum
    values prevent a single source record from collapsing distinct canonical
    observations.  Callers must preserve the source identifiers separately;
    the digest is not a replacement for their lineage.
    """
    required = {
        "source_dataset_id": source_dataset_id,
        "data_source_version_id": data_source_version_id,
        "source_record_id": source_record_id,
        "observation_type": observation_type,
    }
    if any(not value for value in required.values()):
        raise ValueError(
            "canonical observation identity requires source lineage and observation type"
        )

    identity: dict[str, Any] = {"contract_version": "tick-surveillance-v1.1", **required}
    for name, value in {
        "sampling_site_id": sampling_site_id,
        "sampling_event_id": sampling_event_id,
        "sample_id": sample_id,
        "subsample_id": subsample_id,
        "testing_id": testing_id,
        "replicate_id": replicate_id,
    }.items():
        if value is not None:
            identity[name] = value
    if strata:
        identity["strata"] = dict(strata)
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return "tickobs:v1.1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
