# Crash-Cap machine contracts

The stable Phase 1 write contract is version `1.0`:

- `analysis-result-v1.schema.json`
- `build-manifest-v1.schema.json`
- `task-message-v1.schema.json`
- stable API prefix: `/api/v1`

The `*-v0.schema.json` files describe the former Phase 0 draft (`schema_version: "0.1"`). They remain in the repository so old draft payloads can be read deliberately and cross-version rejection can be tested. Phase 1 producers must not emit v0.1 payloads.

Stable schemas are immutable. A field, enum, constraint, or semantic change requires a new schema and API version; adding an optional property is not a way around `additionalProperties: false`. Readers may support multiple explicit versions, but each payload must validate only against its declared version.

Validate the schemas and the positive/negative compatibility matrix with:

```powershell
cargo test -p crash-cap-schema-tests
python scripts/schema/validate.py
```

Validate a produced Canonical JSON against stable v1 with:

```powershell
cargo run -q -p crash-cap-schema-tests --bin validate-instance -- contracts/analysis-result-v1.schema.json path/to/canonical.json
```

The Phase 0 freeze decision and evidence are recorded in [the design](../docs/design.md) and [Golden results](../docs/evidence/phase0-golden-results.md); the final gate command publishes `docs/evidence/phase0-go-no-go.{json,md}`.
