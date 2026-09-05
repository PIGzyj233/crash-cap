# syntax=docker/dockerfile:1.7
#
# P0-A04: dmp-core is built in a pinned Rust toolchain image and copied into
# a pinned distroless runtime.  Keep both digests in sync with the evidence
# produced by scripts/core/verify_oci.py when the base images are refreshed.

FROM rust:1.96-slim-bookworm@sha256:e18a79fc84dfcfc3ab5ba72290398a644c135c97eaa881447fddc354ee4701a3 AS builder

WORKDIR /src
ENV CARGO_TERM_COLOR=always

# Copy manifests first so BuildKit can reuse dependency layers.  The complete
# source copy below is intentionally limited by the repository .dockerignore.
COPY Cargo.toml Cargo.lock ./
COPY artifact-identity/Cargo.toml artifact-identity/Cargo.toml
COPY crashcap-ci/Cargo.toml crashcap-ci/Cargo.toml
COPY core/Cargo.toml core/Cargo.toml
COPY tests/schema/Cargo.toml tests/schema/Cargo.toml
COPY artifact-identity artifact-identity
COPY crashcap-ci crashcap-ci
COPY contracts contracts
COPY core core
COPY tests/schema tests/schema

RUN --mount=type=cache,id=crashcap-cargo-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=crashcap-core-target,target=/src/target,sharing=locked \
    cargo build --release --locked --package dmp-core \
    && install -D /src/target/release/dmp-core /out/dmp-core

FROM gcr.io/distroless/cc-debian12:nonroot@sha256:adcd20c7b4c988b73cbfbddb26d2eee574571e6d7c9ffea29b3821e0690efb77 AS runtime

COPY --from=builder /out/dmp-core /usr/local/bin/dmp-core

# Numeric UID/GID is stable in the pinned distroless image and makes the
# non-root contract visible to image inspection without depending on a shell.
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/dmp-core"]
