---
status: accepted
---

# Use explicit HTTP representations as the API authority

Crash-Cap will define named, explicit response representations for stable `/api/v1` routes and generate OpenAPI consumers from those models instead of maintaining independent Python, TypeScript, and Rust interpretations. Canonical Analysis Result continues to be governed directly by `analysis-result-v1`; SSE and binary download responses keep dedicated transport fixtures rather than being forced into ordinary JSON models. Migration is route-by-route and must preserve status, headers, error envelopes, field meaning, nullability, and compatibility with both old clients and old servers.
