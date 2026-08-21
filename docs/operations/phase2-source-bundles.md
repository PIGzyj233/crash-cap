# Phase 2 source bundle contract and safety

Source context uses Build Manifest `2.0` plus `source-bundle-v1`. Builds without source context may continue using Manifest `1.0`; existing Canonical `1.0` remains readable and its already-reserved `frame.source_context` object is populated only when a verified bundle maps uniquely to the Symbolicator file/line.

The ZIP is uploaded directly through the object-storage presigned path. Worker ingest rejects:

- absolute paths, `..`, backslashes, NULs, symlinks, or encrypted entries;
- nested archives;
- more than 20,000 files, more than 512 MiB uncompressed total, a source file over 2 MiB, or compression ratio over 100:1;
- archives without supported native source files.

Only UTF-8/UTF-8-BOM source text is rendered. A source path must match the configured `source_root`/`strip_prefixes`, an exact relative path, or a unique suffix/basename. Ambiguous matches remain without context. At most 10 lines before/after are allowed, and each rendered line is truncated to 1,000 characters.

Adding a verified source bundle increments the Workspace inventory version. The next reprocess creates a new immutable Analysis Run; old Canonical results remain unchanged.
