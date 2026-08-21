---
status: accepted
---

# Use plain HTTP inside the Phase 1 trusted intranet

Phase 1 deliberately uses plain HTTP for the Browser/API, metrics, and RustFS S3 paths because the deployment is confined to an operator-controlled trusted intranet; it does not require TLS certificates or a CA. This narrows rather than removes the boundary from [ADR-0003](0003-run-anonymously-on-a-trusted-intranet.md): every published port must bind only to loopback or an explicitly approved private address, firewall/outside-probe evidence must still prove that untrusted networks cannot connect, RustFS remains authenticated/private with SSE-S3 at rest, and raw binary download remains disabled by default. Microsoft and other deployment-approved external symbol sources continue to use their upstream HTTPS endpoints, and the historical Phase 0 RustFS TLS qualification evidence is not rewritten; if the platform leaves the trusted network, authentication and transport encryption must be redesigned before exposure.
