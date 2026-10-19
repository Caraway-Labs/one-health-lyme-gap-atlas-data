"""Verify retained fixed-parser mappings without inventing a missing custom map."""

import ast
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parents[1]
# Successful original publication, October candidate build and October publication.
REFS = (
    "a96bee6217ac1c57982e65f6b4b6cfb769bb293f",
    "56b75e6d0ee8861d9624ee93307229377cfe14a6",
    "e6516fa2452500594884178d073cd64f2bc5efe6",
)
FIXED = {
    "human": ("2", "c00584e1a940f31369ad130f6e67c8bdc2526794f86a81289e106dba67e0b68e"),
    "context_svi": ("1", "dc042342a2e5abc108af67b439ec04c86da8b61f9bdd1cf1b1e5ee0462dea7b2"),
    "context_rucc": ("1", "ec455ee2a8bc5fc8e070575ea5bee7dce46fc6037f8c3449cbf56e8b45331fa7"),
}


def selectors(node):
    return sorted(
        {
            ast.unparse(n)
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and (
                isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in ("row", "record", "payload")
                and n.func.attr == "get"
                or isinstance(n.func, ast.Name)
                and n.func.id == "_first"
            )
        }
    )


def mapping_descriptor(text, source):
    functions = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    if source == "human":
        # The complete human parser and its scalar helpers are identical.
        names = ("_human_values", "_record", "_first", "_number", "_text_or", "_state_code")
        return {name: ast.dump(functions[name], include_attributes=False) for name in names}
    loop = next(
        n
        for n in ast.walk(functions["_assemble_counties"])
        if isinstance(n, ast.For) and ast.unparse(n.iter) == f"source_rows['{source}']"
    )
    # Preserve output-column -> ordered raw-field selectors. Numeric sentinel
    # handling is not asserted equal by this descriptor; actual feature values
    # and all observation identities/hashes are separately required to match.
    outputs = {}
    assignments = {}
    for n in ast.walk(loop):
        if isinstance(n, ast.Assign):
            if isinstance(n.value, ast.Dict):
                for key, value in zip(n.value.keys, n.value.values, strict=True):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        outputs[key.value] = selectors(value)
            elif selectors(n.value):
                assignments[";".join(ast.unparse(t) for t in n.targets)] = selectors(n.value)
    return {"selectors": selectors(loop), "outputs": outputs, "assignments": assignments}


@lru_cache
def code_evidence(source):
    descriptors, blobs = [], {}
    for ref in REFS:
        text = subprocess.check_output(
            ["git", "show", f"{ref}:src/lyme_gap_atlas_data/semantic_release.py"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
        descriptors.append(mapping_descriptor(text, source))
        blobs[ref] = hashlib.sha256(text.encode()).hexdigest()
    if not all(d == descriptors[0] for d in descriptors[1:]):
        raise ValueError("Retained fixed field mappings differ; no compatibility conclusion")
    return {
        "kind": "retained_fixed_parser_mapping_not_custom_map",
        "publication_source_sha256": blobs,
        "mapping_sha256": hashlib.sha256(
            json.dumps(descriptors[0], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "mapping_descriptor": descriptors[0],
    }


def fixed_mapping_evidence(row):
    source = row["source_key"]
    if (
        row.get("field_map") is not None
        or source not in FIXED
        or (str(row.get("definition_version")), row.get("artifact_sha256")) != FIXED[source]
    ):
        raise ValueError("Incomplete source mapping without exact retained fixed-parser evidence")
    return code_evidence(source)
