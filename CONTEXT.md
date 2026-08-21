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
One exact set of compiled program artifacts. A build has its own identity even when another build uses the same version label.
_Avoid_: Version, release

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
An archived build file associated with a build, such as a PE, PDB, or source bundle.
_Avoid_: Module, dump

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
The analysis run selected to represent an occurrence in current dashboards and classifications. Historical runs remain available but do not add another occurrence.
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

**In-App Frame**:
A stack frame from an entrypoint or owned module in the workspace.
_Avoid_: Any frame with an uploaded symbol

**Partial Analysis**:
A completed interpretation that contains useful crash evidence but has missing, mismatched, or unavailable supporting artifacts.
_Avoid_: Failed analysis

**Rejected Upload**:
An input that cannot be accepted as a supported, valid dump or artifact.
_Avoid_: Failed analysis
