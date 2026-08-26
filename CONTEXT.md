# Crash-Cap

Crash-Cap organizes Windows native crash evidence for one or more program families and turns each captured dump into a reproducible analysis without confusing reanalysis with a new crash.

## Organization

**Workspace**:
A container for one program or product family, including all of its versions, builds, occurrences, and analysis results.
_Avoid_: Project, tenant

**Version**:
A human-facing release label used to aggregate and navigate crashes. Multiple builds may share the same version.
_Avoid_: Build ID, artifact version

**Build**:
One exact set of compiled program artifacts. A content-identified build is determined by its normalized Manifest and the size and SHA-256 of every expected PE/PDB, and has its own identity even when another build uses the same version label.
_Avoid_: Version, release

**Build Publication**:
One idempotent attempt by a local developer or CI system to publish an exact Build. Multiple Publications may refer to the same Build when their content is identical.
_Avoid_: Build, upload session

**Publication Origin**:
The workflow that initiated a Build Publication: `local` or `ci`. It describes provenance, not the compiler or artifact format.
_Avoid_: Artifact Producer

**Artifact Producer**:
The toolchain capability that produced and identifies an Artifact, such as MSVC. It does not identify whether the Artifact arrived from a local machine or CI.
_Avoid_: Publication Origin

**Build Content Fingerprint**:
The versioned server-computed digest of a normalized Build Manifest plus the sorted kind, logical name, size, and SHA-256 of every expected PE/PDB. `build-content-v1` is the first algorithm.
_Avoid_: Git revision, producer Build ID

**Expected Artifact**:
A PE or PDB declared by a content-identified Build Publication, including its exact logical name, size, and SHA-256. Only Expected Artifacts may complete that Build.
_Avoid_: Uploaded Artifact

**Sealed Build**:
A content-identified Build whose complete Expected Artifact set has been verified. Its Manifest and Artifact set are thereafter immutable.
_Avoid_: Build with any uploaded file

**Module**:
One executable or library loaded by the captured process.
_Avoid_: Artifact

**Entrypoint Module**:
An executable that can identify a build when it appears in a captured process. A build may have more than one entrypoint module.
_Avoid_: Primary module

**Owned Module**:
A module produced and maintained as part of the workspace's program family.
_Avoid_: Dependency, system module

**Dependency Module**:
A third-party or shared module used by the program but not owned by the workspace.
_Avoid_: In-app module

**Artifact**:
A Build-scoped binding between one Expected Artifact and the verified bytes that satisfy it. For PE/PDB content Builds it projects the Artifact Blob's hash, size, identity, and canonical object location; source bundles and legacy Artifacts retain their existing storage behavior.
_Avoid_: Artifact Blob, Module, dump

**Artifact Blob**:
Immutable PE or PDB bytes identified by server-verified SHA-256 within exactly one Workspace. Multiple Build-scoped Artifacts may bind the same Artifact Blob, but trust never crosses a Workspace.
_Avoid_: Artifact, upload claim, source bundle

## Crash evidence

**Occurrence**:
One distinct accepted DMP within a workspace. Its current analysis may classify it as a crash, hang, or unknown; reanalysis does not create another occurrence.
_Avoid_: Analysis, upload attempt

**Crash Occurrence**:
An occurrence whose current analysis confirms `crash`. Crash statistics exclude hang, unknown, and rejected uploads.
_Avoid_: Any uploaded dump

**Dump Blob**:
The immutable DMP bytes that provide evidence for an occurrence.
_Avoid_: Crash report, analysis result

**Analysis Run**:
One immutable interpretation of an occurrence using a specific analysis configuration and artifact set.
_Avoid_: Crash occurrence, current result

**Current Analysis**:
The successful or partial analysis run selected to represent an occurrence in current dashboards and classifications. Selection advances by analysis-run creation order and never means merely the latest attempt.
_Avoid_: Latest attempt

**Crash Group**:
A collection of crash occurrences whose current analyses have sufficient evidence of the same failure signature.
_Avoid_: Stack search result, version

**Unclassified Crash**:
A confirmed crash occurrence whose current analysis lacks enough reliable evidence for automatic grouping.
_Avoid_: Failed analysis

**Hang Capture**:
A user-declared capture of an unresponsive process. Absence of exception information alone does not make a dump a hang capture.
_Avoid_: Unknown dump, crash without symbols

## Analysis outcomes

**Canonical Analysis Result**:
The stable, platform-facing structured report produced by an analysis run.
_Avoid_: Raw engine output, Symbolicator response

**Build Resolution**:
The evidence-backed association between an analysis run and a build. It may be reported, automatically resolved, manually confirmed, ambiguous, or unresolved.
_Avoid_: Version inference, filename match

**Build Candidate Selection**:
A conservative, metadata-only narrowing of the artifacts that may help analyze a dump. It reduces physical input work but never decides Build Resolution.
_Avoid_: Build Resolution, latest Build, Version match

**In-App Frame**:
A stack frame from an entrypoint or owned module in the workspace.
_Avoid_: Any frame with an uploaded symbol

**Partial Analysis**:
A completed interpretation that contains useful crash evidence but has missing, mismatched, or unavailable supporting artifacts.
_Avoid_: Failed analysis

**Missing Symbol Observation**:
The association between one missing symbol identity and an occurrence's Current Analysis. Historical runs and audit entries are not current observations.
_Avoid_: Missing-symbol log event, historical missing symbol

**Workspace Symbol Source**:
The private, Workspace-owned collection of verified symbols that may only satisfy analyses for that Workspace.
_Avoid_: Public Symbol Cache, Build artifact inventory

**Public Symbol Cache**:
A deployment-owned, cross-Workspace cache of symbols fetched from an approved public symbol source. Cache reuse never grants a public source access to Workspace-private symbols.
_Avoid_: Workspace Symbol Source, Build Manifest, public upload area

**Rejected Upload**:
An input that cannot be accepted as a supported, valid dump or artifact.
_Avoid_: Failed analysis
