---
status: accepted
---

# Let Core own the final Canonical Analysis Result

The platform will freeze immutable identity, resolved time, engine, artifact, and source-bundle facts in a versioned Analysis Context, and `dmp-core` will use that context to produce the final `analysis-result-v1` object. Worker may stage verified inputs and perform schema and semantic validation, but it must not rewrite identity, time, engine, or `source_context` after Core returns. Source enrichment failures omit the optional context and produce a stable warning/PARTIAL result rather than converting an otherwise useful analysis to FAILED; historical v1 objects remain readable and any external semantic change requires a new contract version.
