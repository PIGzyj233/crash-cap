# Golden fixture workspace

This directory contains the reviewable metadata for the 21-item Phase 0
Golden set: 20 synthetic Windows fixtures and one licensed public-upstream
real-origin test artifact. A fixture is metadata and expectations first;
Windows binaries are generated or fetched locally and are never source-controlled.

## Layout

Each fixture is a directory containing:

```text
<fixture-id>/
├── fixture.json       # source, build, capture and artifact metadata
├── expected.json      # stable comparison rules and expected evidence
├── reference/         # redacted CDB/WinDbg transcript, if available
└── generated/         # local-only EXE/PDB/DMP/context/raw output
```

`fixture.json` uses `fixture-v0.1`. The required identity is `fixture_id`.
`expected.json` is intentionally declarative: addresses, paths, thread IDs and
other build-specific values may be listed under `allowed_differences`, but an
exception code or a PDB mismatch must not be made optional.

Generate the 20 synthetic fixtures from the repository root:

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/fixtures/build_golden.ps1 -Clean -PreserveExistingP0
```

`-PreserveExistingP0` keeps the already Symbolicator-verified P0-B01 binary
identity stable; omit it only when intentionally refreshing the P0-B01
Symbolicator evidence. The generator has a fixed built-in scenario table and
does not execute fixture metadata commands.

Import and verify the authorized real-origin fixture into private local RustFS:

```text
bash scripts/authorized_samples/run.sh
```

The imported artifact is pinned by commit, SHA-256, size and MIT license. It is
a public upstream test artifact, not a Crash-Cap production incident.

Run the metadata/runtime harness:

```text
python scripts/fixtures/harness.py --output fixtures/harness-summary.json --coverage-output docs/evidence/golden-fixtures.json
```

The harness emits JSON to stdout and writes the category coverage report. It
does not execute arbitrary commands from fixture metadata. Complete-symbol
fixtures have redacted portable CDB summaries generated with:

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/fixtures/summarize_golden_cdb.ps1
```

Every crash, no-exception, hang and x86 boundary sample is captured by the
independent `golden_collector.exe` process calling `MiniDumpWriteDump`; it is
not collected from inside the target process. Artifact-treatment fixtures are
derived from a real base dump and retain independent expected metadata.

## Binary policy

The following are local evidence only and must remain ignored:

```text
generated/**/*.dmp
generated/**/*.exe
generated/**/*.dll
generated/**/*.pdb
generated/**/*.obj
generated/**/*.ilk
generated/**/*.lib
generated/**/*.exp
generated/**/*.bin
generated/**/*.json  # generated manifest/verifier output
```

Small text metadata, expected results and redacted debugger summaries are the
reviewable evidence. Do not commit a DMP, PE, PDB or a raw process-memory
capture. The authorized real-origin sample is stored in a private, SSE-enabled
RustFS bucket; only its manifest, expected result, license/provenance and
sanitized derived facts are reviewable repository content. Its ignored local
cache is used only while running the analysis verification.

The current coverage report is
[golden-fixtures.md](../docs/evidence/golden-fixtures.md). P0-D07 is satisfied by
the licensed upstream real-origin artifact, while the evidence explicitly makes
no claim that it is a production incident.
