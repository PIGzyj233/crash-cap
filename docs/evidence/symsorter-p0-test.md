# P0 Symbolicator Unified fixture evidence

The pinned helper is downloaded only by
`scripts/symbolicator/symsorter/fetch_and_sort.py`:

```text
version: 26.7.2
asset: symsorter-Windows-x86_64.exe
sha256: b13e3b176ab8a5c1bacbf4743061496c27240bba56220f6b73318804944a3ccd
url: https://github.com/getsentry/symbolicator/releases/download/26.7.2/symsorter-Windows-x86_64.exe
```

## Reproduction

```text
PYTHONDONTWRITEBYTECODE=1 python scripts/symbolicator/symsorter/fetch_and_sort.py --clean-debug-id --evidence docs/evidence/symsorter-p0-test.json
```

The script downloads atomically into the ignored
`scripts/symbolicator/.tools/` cache, verifies SHA-256, runs the pinned
binary's `--help` probe, then runs:

```text
symsorter-Windows-x86_64.exe --output deploy/symbolicator/symbols/p0-test fixtures/p0-b01-null-read/generated/null_read_target.exe fixtures/p0-b01-null-read/generated/null_read_target.pdb
```

The `--clean-debug-id` option removes only the exact input Debug ID directory
under the explicit `p0-test` output root before sorting; it preserves the
workspace README and any other Debug IDs.

## Observed result

The command returned `0` and produced:

```text
deploy/symbolicator/symbols/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/debuginfo
deploy/symbolicator/symbols/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/debuginfo.meta
deploy/symbolicator/symbols/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/executable
deploy/symbolicator/symbols/p0-test/52/95c1f4535d4f8aa0b1989805198bb815/executable.meta
```

The input PE identity was `code_id=6A87124AC8000` and
`debug_id=5295c1f4535d4f8aa0b1989805198bb815`; the copied `executable` parsed
to the same Code ID and Debug ID. `debuginfo` and `executable` are both
present, so the evidence JSON reports `ready_for_symbolicator=true`.

The layout follows Symbolicator's Unified Symbol Server Layout:
`<debug-id-first-two>/<debug-id-rest>/debuginfo|executable`.

The binary outputs are generated local evidence and must not be committed.
The complete machine-readable command, hash, stdout, layout and identity
checks are in `symsorter-p0-test.json`.
