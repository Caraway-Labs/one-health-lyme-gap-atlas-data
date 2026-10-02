"""Print a nonexecuting, metadata-only DATA376 proof plan. Never connect."""

import argparse
import json
import subprocess
from pathlib import Path

from lyme_gap_atlas_data.failure_engine_proof import make_plan, plan_hash


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("proof plan rejected")


def main() -> int:
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--code-commit")
        args = parser.parse_args()
        root = Path(__file__).resolve().parents[1]
        commit = args.code_commit
        if commit is None:
            commit = subprocess.run(
                ["git", "-c", f"safe.directory={root}", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ).stdout.strip()
        plan = make_plan(commit)
        print(json.dumps({"plan_sha256": plan_hash(plan), "plan": plan}, sort_keys=True))
        return 0
    except Exception:
        print('{"state":"PLAN_UNAVAILABLE"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
