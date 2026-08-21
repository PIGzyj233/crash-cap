# Phase 0 calibration probes

Run the F03–F07 calibration evidence locally with:

```text
python scripts/calibration/phase0_calibration.py \
  --core-image-digest sha256:<audited-core-image-id> \
  --reset-symbolicator-cache
```

The tool writes only `docs/evidence/phase0-calibration.json` and
`docs/evidence/phase0-calibration.md`. It uses temporary files for restored
PE/PDB copies, CDB symbols, match inputs, and a mock Symbolicator. It does not
edit `fixtures/**`, the Golden runner, contracts, or the roadmap.

`--reset-symbolicator-cache` is required for F07 to pass. Before deletion the
tool verifies that the exact volume is
`crash-cap-symbolicator-p0_symbolicator-cache` and that its Compose labels are
`project=crash-cap-symbolicator-p0` and `volume=symbolicator-cache`. It then
recreates only that disposable cache, waits for the loopback gateway to become
healthy, and records the first query per Microsoft module as controlled cold
followed by hot repeats. Fixture files, Unified private symbols, and RustFS
data are not removed.
