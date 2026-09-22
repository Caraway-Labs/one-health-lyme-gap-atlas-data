## Delivery evidence

- Outcome and out-of-scope:
- Starting commit/date:
- Authoritative contracts/ADRs:
- Required environment and execution identity:
- Action-specific authorization required:

### Verification states

| State | Result | Independently checkable evidence identity |
| --- | --- | --- |
| Local tests | UNKNOWN | command and commit |
| CI | UNKNOWN | workflow URL/head SHA |
| Deployment | UNKNOWN | artifact/image digest and runtime target |
| Live functional verification | UNKNOWN | sanitized runtime evidence/time |

Do not represent a merge as deployment or live verification. Record unavailable
evidence as `UNKNOWN`, never as an estimate.

### Artifact and workload binding

- Requested workload SHA:
- Workflow head SHA:
- Tested artifact/build identity:
- Deployed artifact/image identity:
- Semantic bundle/API-contract identity (if applicable):

### Optional failure packet

- Stage and safe error category/query reference:
- Verified facts and unknowns:
- Missing preventive check and required regression:
