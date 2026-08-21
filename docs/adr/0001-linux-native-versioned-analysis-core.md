---
status: accepted
---

# Use a Linux-native, versioned analysis core

Crash-Cap will analyze Windows native x64 user-mode minidumps on Linux through a versioned Rust CLI and OCI image. Rust minidump tooling supplies dump inspection, unwind evidence, and frame trust; Symbolicator supplies PDB/PE symbolication; Crash-Cap owns the canonical result, quality evaluation, and grouping rules. This keeps engine-native formats out of the platform contract and makes every analysis run reproducible without claiming to replace WinDbg.
