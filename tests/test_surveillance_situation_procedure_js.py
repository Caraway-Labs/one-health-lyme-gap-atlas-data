"""Execute the actual JavaScript failure path with a minimal Snowflake fake.

This is offline transaction-control coverage, not Snowflake DEV/runtime evidence.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("authorized", [True, False])
def test_all_procedure_bodies_parse_and_damaged_county_bytes_roll_back(tmp_path, authorized):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node needed for offline JavaScript procedure execution")
    migrations = [
        ROOT / f"migrations/{name}"
        for name in (
            "V157__model_release_compatibility.sql",
            "V158__surveillance_situation_publication.sql",
        )
    ]
    sql = migrations[1].read_text()
    bodies = [
        part
        for migration in migrations
        for i, part in enumerate(migration.read_text().split("$$"))
        if i % 2
    ]
    body = sql.split("SP_PUBLISH_SURVEILLANCE_SITUATIONS", 1)[1].split("$$")[1]
    folder = ROOT / "docs/contracts/surveillance-situations"
    documents = [
        (folder / name).read_bytes().decode("utf-8")
        for name in (
            "138-surveillance-situation-batch-v1.json",
            "138-surveillance-situation-class-dictionary-v1.json",
            "138-surveillance-situation-batch-v1-approval.json",
        )
    ]
    harness = r"""
const crypto = require('crypto');
const assert = require('assert');
const logs = [];
function result(rows) {
 let i=-1;
 return {next:()=>++i<rows.length, getColumnValue:n=>rows[i][n-1]};
}
const snowflake={createStatement:({sqlText,binds=[]})=>({execute:()=>{
 logs.push(sqlText);
 if(sqlText.includes('SELECT LOWER(SHA2(?,256))'))
   return result([[crypto.createHash('sha256').update(binds[0]).digest('hex')]]);
 if(sqlText.includes('SELECT LISTAGG(part_text')) return result([['{}']]);
 if(sqlText.includes('SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_AUTHORIZATIONS'))
   return result([[AUTHORIZED ? 1:0]]);
 if(sqlText.startsWith('SELECT COUNT(*)')) return result([[1]]);
 return result([]);
}})};
for(const body of BODIES) new Function(body);
let error;
try {
 new Function('snowflake','P_AUTHORIZATION','P_ATTEMPT',
  'P_MANIFEST','P_DICTIONARY','P_APPROVAL',BODY)(
  snowflake,'fixture-data-authorization','fixture-attempt',...DOCUMENTS);
}
catch(e){error=String(e);}
assert.equal(error,AUTHORIZED?'COUNTY_DIGEST_MISMATCH':'DATA_PUBLICATION_AUTHORIZATION_REQUIRED');
assert.equal(logs.at(-1),'ROLLBACK');
assert(!logs.includes('COMMIT'));
assert(!logs.some(s=>s.startsWith('INSERT INTO')));
"""
    source = (
        "const AUTHORIZED="
        + json.dumps(authorized)
        + ";\nconst BODIES="
        + json.dumps(bodies)
        + ";\nconst BODY="
        + json.dumps(body)
        + ";\nconst DOCUMENTS="
        + json.dumps(documents)
        + ";\n"
        + harness
    )
    path = tmp_path / "procedure.js"
    path.write_text(source, encoding="utf-8")
    completed = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
