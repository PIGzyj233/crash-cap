# Crash-Cap machine contracts

The stable Phase 1 write contract is version `1.0`:

- `analysis-result-v1.schema.json`
- `build-manifest-v1.schema.json`
- `task-message-v1.schema.json`
- stable API prefix: `/api/v1`

Phase 2 keeps those readers and the `/api/v1` HTTP prefix, and adds:

- `build-manifest-v2.schema.json` (`schema_version: "2.0"`) for optional source-bundle metadata
- `source-bundle-v1.schema.json` for the bounded ZIP/path/context policy
- `artifact-delivery-v1.schema.json` and positive fixtures for the optional
  `upload`, `wait`, and `reused` PE/PDB delivery dispositions
- `artifact-delivery-v2.schema.json` and positive fixtures for the same dispositions while
  separating the logical raw identity from the optional `identity|zstd-v1` wire identity
- `task-message-v1.1.schema.json` for durable Artifact Blob pair publication;
  existing task kinds continue to use stable task-message v1.0

Build Manifest v1 remains readable and writable for builds without source context. A source bundle requires Manifest v2. Canonical v1 already reserved the closed `frame.source_context` shape; Phase 2 fills only that existing field and does not add or reinterpret any other Canonical property.

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
