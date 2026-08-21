# Phase 0 verification entry points

The default local/CI command is:

```bash
python scripts/phase0/verify.py --output docs/evidence/ci-phase0-verification.json
```

It runs deterministic checks for local Markdown links, Draft 2020-12 schemas,
Rust format/lint/tests, fixture metadata, the Symbolicator policy gateway unit
tests and the offline S3 adapter unit tests. Docker, Windows fixture generation,
and the full Golden corpus remain explicit lanes so a safe default run cannot
claim evidence from infrastructure it did not start.

The following lanes are intentionally separate and are never started by the
default CI job:

```bash
python scripts/phase0/verify.py --run-s3                  # RustFS Docker S3 qualification
python scripts/phase0/verify.py --run-docker              # Symbolicator Compose smoke
python scripts/phase0/verify.py --run-windows-fixture     # MSVC/Windows fixture generation
```

After building and auditing the final Core OCI image, run the complete Golden
lane against the exact image ID recorded in `docs/evidence/core-oci.json`:

```bash
python scripts/symbolicator/verify.py --keep
python scripts/phase0/golden_runner.py \
  --core target/release/dmp-core.exe \
  --symbolicator http://127.0.0.1:3021 \
  --version 26.7.2 \
  --core-image-digest sha256:<final-local-image-id> \
  --workers 2
python scripts/calibration/phase0_calibration.py \
  --core-image-digest sha256:<final-local-image-id> \
  --reset-symbolicator-cache
python scripts/phase0/gate.py
```

The cache reset is restricted to the Compose-labeled disposable volume
`crash-cap-symbolicator-p0_symbolicator-cache`; the script refuses an unexpected
name or label. Run Golden once more after the reset before publishing the final
gate report.

The aggregator exits `0` when every check it attempted passes, including the
default `PARTIAL` run whose Docker/Windows/Golden lanes were explicitly skipped. It
exits `1` for any attempted failure. `overall_status` and
`required_ci_checks_passed` distinguish passing required CI checks from external
lane coverage; `scripts/phase0/gate.py` is the complete local Phase 0 decision.
The JSON contains `remote_ci_executed: false` so local evidence
cannot be mistaken for a remote workflow result.
