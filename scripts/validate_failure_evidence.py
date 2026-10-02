"""Validate reviewed packets without printing rejected data or exception details."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lyme_gap_atlas_data.failure_evidence import validate_packet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        for path in args.packet:
            validate_packet(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        print("Failure evidence validation: REJECTED")
        return 1
    print("Failure evidence validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
