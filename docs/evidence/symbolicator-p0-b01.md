# P0-B01 Symbolicator query evidence

The pinned Symbolicator container was running from the digest fixed by the
main deployment lane:

```text
image: ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959
version: symbolicator 26.7.2
git commit: 9afe47323f4a0264afc03afdaf84db7fa4a81f52
scope: wsp_p0test
```

## Reproduction

Start the already-pinned Compose stack, then sort the current fixture and
query the gateway:

```text
docker compose -f deploy/compose/symbolicator.yml up -d --build --wait
PYTHONDONTWRITEBYTECODE=1 python scripts/symbolicator/symsorter/fetch_and_sort.py --clean-debug-id --evidence docs/evidence/symsorter-p0-test.json
PYTHONDONTWRITEBYTECODE=1 python scripts/symbolicator/query_p0_b01.py
```

`query_p0_b01.py` obtains `exception_address` and the actual fault module base
from the local DbgHelp verifier, computes a relative instruction address, and
sends a deployment-scoped `/symbolicate` request. It does not send a request
owned symbol URL.

## Observed result

The query returned HTTP 200 and passed all checks:

```text
module debug_status: found
source candidate: crash-cap:p0-test, download status: ok
frame status: symbolicated
function: crashcap::trigger_null_read()
source: null_read_target.cpp:76
```

Current fixture IDs were `code_id=6A87124AC8000` and
`debug_id=5295c1f4535d4f8aa0b1989805198bb815`. The Unified files were found at:

```text
/symbols/workspaces/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/debuginfo
/symbols/workspaces/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/executable
```

The complete request/response, candidate statuses and address derivation are
in [symbolicator-p0-b01-query.json](symbolicator-p0-b01-query.json). The
response reports `has_sources=false`; source bundle consumption is outside
the current Phase 0 fixture and does not invalidate function/line lookup.
