"""Bounded January action using an already configured approved service/owner.

No credential discovery or fallback. Inspect is the default. Mutating modes need
independent review and the appropriate existing identity; no workflow is dispatched.
"""

import argparse
import json
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_source_review import reconcile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=["inspect", "register-pending", "record-steward"], default="inspect"
    )
    parser.add_argument("--decision", type=Path)
    args = parser.parse_args()
    decision = json.loads(args.decision.read_text()) if args.decision else None
    with connect(SnowflakeSettings()) as connection:
        result = reconcile(connection, phase=args.phase, decision=decision)
    if args.phase == "inspect":
        report = [
            {
                "resource_key": r["resource_key"],
                "registry_matches": len(r["resources"]),
                "version_matches": len(r["versions"]),
            }
            for r in result
        ]
    else:
        report = {
            "phase": args.phase,
            "source_version_ids": result,
            "source_activation": False,
            "grants_changed": False,
            "release_publication": False,
        }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
