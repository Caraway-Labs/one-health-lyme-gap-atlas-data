"""Same-named skills from another origin cannot satisfy repository discovery."""

import copy
import runpy
from pathlib import Path

import pytest

HELPER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/verify_atlas_skill_discovery.py")
)


def entry(root):
    skills = []
    for name in sorted(HELPER["SKILLS"]):
        path = root / ".agents/skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public fixture", encoding="utf-8")
        skills.append({"name": name, "enabled": True, "path": str(path)})
    return {"skills": skills, "errors": []}


@pytest.mark.parametrize("kind", ["external", "missing", "duplicate", "disabled", "relative"])
def test_wrong_origin_or_ambiguous_discovery_remains_unknown(tmp_path, kind):
    root = tmp_path / "repo"
    value = entry(root)
    assert HELPER["verify_entry"](value, root)["status"] == "PASS"
    if kind == "external":
        other = tmp_path / "user" / "SKILL.md"
        other.parent.mkdir()
        other.write_text("private origin", encoding="utf-8")
        value["skills"][0]["path"] = str(other)
    elif kind == "missing":
        value["skills"][0].pop("path")
    elif kind == "duplicate":
        value["skills"].append(copy.deepcopy(value["skills"][0]))
    elif kind == "disabled":
        value["skills"][0]["enabled"] = False
    else:
        value["skills"][0]["path"] = ".agents/skills/example/SKILL.md"
    result = HELPER["verify_entry"](value, root)
    assert result["status"] == "UNKNOWN"
    assert result["repository_paths_verified"] is False
    assert str(tmp_path) not in str(result)
