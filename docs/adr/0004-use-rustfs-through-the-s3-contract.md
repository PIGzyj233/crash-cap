---
status: accepted
---

# Use RustFS through the S3 contract

As of 2026-08-20, [MinIO Community Edition is distributed as source only and its legacy prebuilt releases no longer receive updates](https://github.com/minio/minio/blob/master/README.md), while the selected [RustFS distribution provides current prebuilt releases but is still labelled beta](https://github.com/RustFS/RustFS/releases). Phase 1 therefore uses RustFS while explicitly accepting a higher maturity risk. Crash-Cap will depend only on the standard S3-compatible operations it qualifies, pin the RustFS image by digest, keep buckets private, and isolate RustFS credentials from anonymous platform clients. RustFS remains behind an application storage adapter so a failed compatibility or upgrade qualification does not lock the platform to RustFS-specific APIs.
