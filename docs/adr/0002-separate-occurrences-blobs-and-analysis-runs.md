---
status: accepted
---

# Separate occurrences, dump blobs, and analysis runs

A distinct accepted DMP in a workspace represents one Occurrence, while its bytes are stored as an immutable Dump Blob and every interpretation is an immutable Analysis Run. Reanalysis changes the occurrence's Current Analysis and may change its type, build, or group classification, but never creates another occurrence; only occurrences currently confirmed as `crash` enter crash counts. This separation prevents content deduplication from being confused with analysis history and keeps live statistics from counting reprocessing as another crash.
