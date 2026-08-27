use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

use chrono::{SecondsFormat, Utc};
use reqwest::Method;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::NamedTempFile;

use crate::cli::PublicationOrigin;
use crate::config::{ArtifactKind, PreparedArtifact, PreparedProfile};
use crate::error::{PublishError, Result};
use crate::http::ApiClient;
use crate::wire::{
    ArtifactDeliveryInitResponse, ArtifactProducerResponse, ExpectedArtifactState,
    MultipartInitResponse, PublicationState, PublicationStatusResponse, UploadCompletionResponse,
    UploadInitResponse, UploadLifecycleStatus, UploadMethod, WorkspaceResponse,
};

const DEFAULT_PART_SIZE: u64 = 64 * 1024 * 1024;
const ZSTD_LEVEL: i32 = 6;
const TEMP_CAPACITY_RESERVE: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Default)]
struct DeliveryCapabilities {
    v1: bool,
    v2: bool,
}

impl DeliveryCapabilities {
    const fn supports_claims(self) -> bool {
        self.v1 || self.v2
    }

    const fn selected_contract(self) -> Option<&'static str> {
        if self.v2 {
            Some("artifact-delivery-v2")
        } else if self.v1 {
            Some("artifact-delivery-v1")
        } else {
            None
        }
    }
}

struct WireArtifact {
    path: PathBuf,
    size: u64,
    sha256: String,
    encoding: &'static str,
    _temporary: Option<NamedTempFile>,
}

impl WireArtifact {
    fn identity(artifact: &PreparedArtifact) -> Self {
        Self {
            path: artifact.path.clone(),
            size: artifact.size,
            sha256: artifact.sha256.clone(),
            encoding: "identity",
            _temporary: None,
        }
    }
}

pub struct Publisher<'a> {
    api: &'a ApiClient,
    poll_interval: Duration,
    progress: bool,
}

impl<'a> Publisher<'a> {
    pub fn new(api: &'a ApiClient, progress: bool) -> Self {
        Self { api, poll_interval: Duration::from_secs(1), progress }
    }

    pub fn resolve_workspace(
        &self,
        requested: &str,
        create_if_missing: bool,
    ) -> Result<WorkspaceResponse> {
        let rows: Vec<WorkspaceResponse> =
            self.api.request_json(Method::GET, "/workspaces", None)?;
        let matches = rows
            .iter()
            .filter(|row| row.id == requested || row.name == requested)
            .cloned()
            .collect::<Vec<_>>();
        if matches.len() == 1 {
            return Ok(matches[0].clone());
        }
        if !matches.is_empty() {
            return Err(PublishError::message(format!(
                "Workspace {requested:?} is ambiguous; found {} matches",
                matches.len()
            )));
        }
        if !create_if_missing {
            return Err(PublishError::message(format!(
                "Workspace {requested:?} does not exist; rerun init with --create-workspace to confirm creation"
            )));
        }
        if requested.starts_with("wsp_") {
            return Err(PublishError::message(
                "a missing Workspace id cannot be created; provide a valid Workspace name",
            ));
        }
        let body = json!({"name": requested, "display_name": requested});
        self.api.request_json(Method::POST, "/workspaces", Some(&body))
    }

    pub fn doctor(&self, requested_workspace: &str) -> Result<Value> {
        self.stage("checking API and Workspace");
        let workspace = self.resolve_workspace(requested_workspace, false)?;
        let producers: Vec<ArtifactProducerResponse> =
            self.api.request_json(Method::GET, "/artifact-producers", None)?;
        let msvc = producers.iter().find(|row| row.producer == "msvc").ok_or_else(|| {
            PublishError::message("API does not advertise the MSVC Artifact Producer")
        })?;
        if msvc.status != "supported" {
            return Err(PublishError::message(format!(
                "MSVC Artifact Producer is {} rather than supported",
                msvc.status
            )));
        }
        if !msvc.publication_contracts.iter().any(|version| version == "1.0") {
            return Err(PublishError::message(
                "API does not advertise build-publication-v1 compatibility",
            ));
        }
        if !version_at_least(env!("CARGO_PKG_VERSION"), &msvc.minimum_client_version) {
            return Err(PublishError::message(format!(
                "crashcap {} is older than the server minimum {}",
                env!("CARGO_PKG_VERSION"),
                msvc.minimum_client_version
            )));
        }
        if !msvc.build_publications_enabled {
            return Err(PublishError::message(
                "Build Publications are compatible but disabled in this environment",
            ));
        }
        Ok(json!({
            "ok": true,
            "api": "reachable",
            "workspace": workspace,
            "artifact_producer": "msvc",
            "artifact_profile": "windows-x64-msvc-full-pdb-7.0",
            "publication_contract": "build-publication-v1",
            "artifact_delivery_contract": if msvc.artifact_delivery_contracts.iter().any(|contract| contract == "artifact-delivery-v2") { Value::String("artifact-delivery-v2".to_owned()) } else if msvc.artifact_delivery_contracts.iter().any(|contract| contract == "artifact-delivery-v1") { Value::String("artifact-delivery-v1".to_owned()) } else { Value::Null },
            "client_version": env!("CARGO_PKG_VERSION"),
            "minimum_client_version": msvc.minimum_client_version,
            "build_publications_enabled": true,
        }))
    }

    pub fn publish(
        &self,
        prepared: &PreparedProfile,
        origin: PublicationOrigin,
        wait_seconds: u64,
        receipt_path: &Path,
    ) -> Result<Value> {
        let wait_seconds = wait_seconds.max(1);
        let reproducibility_warnings = match prepared.git.worktree_state.as_str() {
            "dirty" => vec!["git_worktree_dirty"],
            "unknown" => vec!["git_worktree_unknown"],
            _ => Vec::new(),
        };
        if prepared.git.worktree_state == "dirty" {
            self.stage("WARNING: Git worktree is dirty; source reproducibility is reduced");
        } else if prepared.git.worktree_state == "unknown" {
            self.stage("WARNING: Git worktree state is unknown; a clean source state is unproven");
        }
        self.stage("resolving Workspace and producer compatibility");
        let workspace = self.resolve_workspace(&prepared.workspace, false)?;
        let delivery = self.ensure_publication_capability()?;
        let client_publication_id = client_publication_id(prepared, origin)?;
        let inventory = prepared
            .artifacts
            .iter()
            .map(|artifact| {
                json!({
                    "module_code_file": artifact.module_code_file,
                    "kind": artifact.kind.as_str(),
                    "logical_name": artifact.logical_name,
                    "size": artifact.size,
                    "sha256": artifact.sha256,
                })
            })
            .collect::<Vec<_>>();
        let body = json!({
            "schema_version": "1.0",
            "origin": origin.as_str(),
            "client_publication_id": client_publication_id,
            "client_version": format!("crashcap/{}", env!("CARGO_PKG_VERSION")),
            "git": prepared.git,
            "manifest": prepared.manifest,
            "artifacts": inventory,
        });
        self.stage("registering idempotent Build Publication");
        let registered: PublicationStatusResponse = self.api.request_json(
            Method::POST,
            &format!("/workspaces/{}/build-publications", workspace.id),
            Some(&body),
        )?;
        let publication = registered
            .publication
            .as_ref()
            .ok_or_else(|| PublishError::message("registration response omitted Publication"))?;
        if publication.workspace_id != workspace.id || publication.build_id != registered.build_id {
            return Err(PublishError::message(
                "registration response returned inconsistent Workspace/Build identity",
            ));
        }
        if let Some(rejected) = registered.expected_artifacts.iter().find(|expected| {
            expected.status == ExpectedArtifactState::Rejected && expected.artifact_id.is_some()
        }) {
            return Err(PublishError::message(format!(
                "expected {} {} failed Artifact identity validation: {}; rebuild the PE/PDB set so content changes produce a new Build",
                rejected.kind,
                rejected.logical_name,
                rejected.rejection_reason.as_deref().unwrap_or("rejected")
            )));
        }

        let pending = registered
            .expected_artifacts
            .iter()
            .filter(|expected| {
                expected.status != ExpectedArtifactState::Verified
                    && (delivery.supports_claims()
                        || expected.status != ExpectedArtifactState::Verifying)
            })
            .collect::<Vec<_>>();
        for (index, expected) in pending.iter().enumerate() {
            match expected.status {
                ExpectedArtifactState::Verified => continue,
                // An INITIALIZED multipart may belong to a process that died
                // before completion. Re-initializing under the same Publication
                // identity is safe; the Worker still accepts only exact bytes.
                ExpectedArtifactState::Uploading
                | ExpectedArtifactState::Verifying
                | ExpectedArtifactState::Missing
                | ExpectedArtifactState::Rejected => {}
            }
            let artifact = prepared
                .artifacts
                .iter()
                .find(|artifact| {
                    artifact.kind.as_str() == expected.kind
                        && artifact.logical_name.eq_ignore_ascii_case(&expected.logical_name)
                        && artifact.size == expected.size
                        && artifact.sha256.eq_ignore_ascii_case(&expected.sha256)
                })
                .ok_or_else(|| {
                    PublishError::message(format!(
                        "server expectation {} {} is absent from the validated local inventory",
                        expected.kind, expected.logical_name
                    ))
                })?;
            self.stage(&format!(
                "delivering file {}/{}: {} {} ({} bytes)",
                index + 1,
                pending.len(),
                artifact.kind.as_str(),
                artifact.logical_name,
                artifact.size
            ));
            let disposition = if delivery.supports_claims() {
                self.deliver(
                    &registered.build_id,
                    &publication.id,
                    artifact,
                    wait_seconds,
                    delivery.v2,
                )?
            } else {
                self.upload(&registered.build_id, artifact, wait_seconds)?;
                "uploaded"
            };
            self.stage(&format!(
                "{} file {}/{}: {}",
                disposition,
                index + 1,
                pending.len(),
                artifact.logical_name
            ));
        }

        self.stage("waiting for verified inventory and sealed Build");
        let status = self.wait_for_publication(&publication.id, wait_seconds)?;
        let receipt = json!({
            "schema_version": "1.0",
            "created_at": Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true),
            "workspace_id": workspace.id,
            "workspace": workspace.name,
            "profile": prepared.profile,
            "version": prepared.version,
            "publication": status.publication,
            "build_id": status.build_id,
            "fingerprint_version": status.fingerprint_version,
            "content_fingerprint": status.content_fingerprint,
            "sealed_at": status.sealed_at,
            "ready": status.ready,
            "git": prepared.git,
            "warnings": reproducibility_warnings,
            "artifact_delivery_contract": delivery.selected_contract(),
            "artifacts": status.expected_artifacts.iter().map(|item| json!({
                "module_code_file": item.module_code_file,
                "kind": item.kind,
                "logical_name": item.logical_name,
                "size": item.size,
                "sha256": item.sha256,
                "status": item.status,
                "artifact_blob_id": item.artifact_blob_id,
                "delivery": item.delivery,
            })).collect::<Vec<_>>(),
        });
        write_receipt(receipt_path, &receipt)?;
        self.stage(&format!("wrote safe receipt {}", receipt_path.display()));
        Ok(receipt)
    }

    fn ensure_publication_capability(&self) -> Result<DeliveryCapabilities> {
        let rows: Vec<ArtifactProducerResponse> =
            self.api.request_json(Method::GET, "/artifact-producers", None)?;
        let msvc = rows.iter().find(|row| row.producer == "msvc").ok_or_else(|| {
            PublishError::message("API does not advertise MSVC publication support")
        })?;
        if msvc.status != "supported"
            || !msvc.build_publications_enabled
            || !msvc.publication_contracts.iter().any(|version| version == "1.0")
        {
            return Err(PublishError::message(
                "API is not ready for enabled build-publication-v1 MSVC publishing; run crashcap doctor",
            ));
        }
        if !version_at_least(env!("CARGO_PKG_VERSION"), &msvc.minimum_client_version) {
            return Err(PublishError::message(format!(
                "server requires crashcap {} or newer",
                msvc.minimum_client_version
            )));
        }
        Ok(DeliveryCapabilities {
            v1: msvc
                .artifact_delivery_contracts
                .iter()
                .any(|contract| contract == "artifact-delivery-v1"),
            v2: msvc
                .artifact_delivery_contracts
                .iter()
                .any(|contract| contract == "artifact-delivery-v2"),
        })
    }

    fn deliver(
        &self,
        build_id: &str,
        publication_id: &str,
        artifact: &PreparedArtifact,
        wait_seconds: u64,
        delivery_v2: bool,
    ) -> Result<&'static str> {
        let deadline = Instant::now() + Duration::from_secs(wait_seconds.max(1));
        let wire = if delivery_v2 {
            match prepare_zstd_wire_artifact(artifact) {
                Ok(wire) => wire,
                Err(error) => {
                    self.stage(&format!(
                        "wire compression unavailable for {}; falling back to identity: {error}",
                        artifact.logical_name
                    ));
                    WireArtifact::identity(artifact)
                }
            }
        } else {
            WireArtifact::identity(artifact)
        };
        let body = if delivery_v2 {
            json!({
                "file_kind": artifact.kind.as_str(),
                "filename": artifact.logical_name,
                "logical": {"size": artifact.size, "sha256": artifact.sha256},
                "wire": {
                    "encoding": wire.encoding,
                    "size": wire.size,
                    "sha256": wire.sha256,
                },
            })
        } else {
            json!({
                "file_kind": artifact.kind.as_str(),
                "filename": artifact.logical_name,
                "size": artifact.size,
                "sha256": artifact.sha256,
            })
        };
        let endpoint = if delivery_v2 {
            format!("/builds/{build_id}/artifacts/deliveries-v2:init")
        } else {
            format!("/builds/{build_id}/artifacts/deliveries:init")
        };
        loop {
            let initialized: ArtifactDeliveryInitResponse =
                self.api.request_json(Method::POST, &endpoint, Some(&body))?;
            match initialized {
                ArtifactDeliveryInitResponse::Upload {
                    upload_id,
                    method,
                    url,
                    headers,
                    expires_in,
                    multipart,
                    wire_encoding,
                    wire_size,
                } => {
                    if delivery_v2
                        && (wire_encoding.as_deref() != Some(wire.encoding)
                            || wire_size != Some(wire.size))
                    {
                        return Err(PublishError::message(
                            "artifact-delivery-v2 response changed the declared wire identity",
                        ));
                    }
                    let upload = UploadInitResponse {
                        upload_id,
                        method,
                        url,
                        headers,
                        expires_in,
                        multipart,
                    };
                    self.transfer_initialized(
                        &upload,
                        &wire.path,
                        wire.size,
                        &artifact.logical_name,
                        remaining_seconds(deadline, "Artifact delivery")?,
                    )?;
                    return Ok("uploaded");
                }
                ArtifactDeliveryInitResponse::Reused {
                    artifact_blob_id,
                    artifact_id,
                    delivery,
                } => {
                    if !artifact_blob_id.starts_with("abl_")
                        || !artifact_id.starts_with("art_")
                        || delivery != "reused"
                    {
                        return Err(PublishError::message(
                            "artifact delivery reuse response was inconsistent",
                        ));
                    }
                    return Ok("reused");
                }
                ArtifactDeliveryInitResponse::Wait { retry_after_seconds, lease_expires_at } => {
                    if retry_after_seconds == 0 || lease_expires_at.is_empty() {
                        return Err(PublishError::message(
                            "artifact delivery wait response was invalid",
                        ));
                    }
                    self.stage(&format!(
                        "waiting for the first transfer of {} (lease expires {})",
                        artifact.logical_name, lease_expires_at
                    ));
                    let remaining = remaining_duration(deadline, "Artifact delivery")?;
                    thread::sleep(Duration::from_secs(retry_after_seconds).min(remaining));
                    let status: PublicationStatusResponse = self.api.request_json(
                        Method::GET,
                        &format!("/build-publications/{publication_id}"),
                        None,
                    )?;
                    let expected = status
                        .expected_artifacts
                        .iter()
                        .find(|expected| {
                            expected.kind == artifact.kind.as_str()
                                && expected
                                    .logical_name
                                    .eq_ignore_ascii_case(&artifact.logical_name)
                                && expected.size == artifact.size
                                && expected.sha256.eq_ignore_ascii_case(&artifact.sha256)
                        })
                        .ok_or_else(|| {
                            PublishError::message(
                                "Publication status omitted the exact waiting expectation",
                            )
                        })?;
                    if expected.status == ExpectedArtifactState::Verified {
                        return Ok("reused");
                    }
                    // Missing or rejected means the previous owner released its
                    // claim. Uploading/verifying can still race with lease expiry.
                    // In every case, the next init atomically decides wait/reuse/upload.
                    remaining_duration(deadline, "Artifact delivery")?;
                }
            }
        }
    }

    fn upload(&self, build_id: &str, artifact: &PreparedArtifact, wait_seconds: u64) -> Result<()> {
        let body = json!({
            "file_kind": artifact.kind.as_str(),
            "filename": artifact.logical_name,
            "size": artifact.size,
            "sha256": artifact.sha256,
        });
        let initialized: UploadInitResponse = self.api.request_json(
            Method::POST,
            &format!("/builds/{build_id}/artifacts/uploads:init"),
            Some(&body),
        )?;
        self.transfer_initialized(
            &initialized,
            &artifact.path,
            artifact.size,
            &artifact.logical_name,
            wait_seconds,
        )
    }

    fn transfer_initialized(
        &self,
        initialized: &UploadInitResponse,
        path: &Path,
        size: u64,
        logical_name: &str,
        wait_seconds: u64,
    ) -> Result<()> {
        if initialized.method != UploadMethod::Put || initialized.expires_in == 0 {
            return Err(PublishError::message(
                "artifact upload initialization returned an invalid method or expiry",
            ));
        }
        let (multipart_upload_id, completed_parts) = match initialized.multipart.as_ref() {
            Some(multipart) => {
                let parts = self.upload_multipart(
                    &initialized.headers,
                    path,
                    size,
                    logical_name,
                    multipart,
                )?;
                (Some(multipart.upload_id.clone()), parts)
            }
            None => {
                if initialized.url.is_empty() {
                    return Err(PublishError::message(
                        "artifact upload initialization returned no URL",
                    ));
                }
                self.api.put_file_range(
                    &initialized.url,
                    &initialized.headers,
                    path,
                    0,
                    size,
                    None,
                )?;
                (None, Vec::new())
            }
        };
        let completion = json!({
            "multipart_upload_id": multipart_upload_id,
            "parts": completed_parts,
        });
        let completed: UploadCompletionResponse = self.api.request_json(
            Method::POST,
            &format!("/uploads/{}/complete", initialized.upload_id),
            Some(&completion),
        )?;
        validate_upload_response(&completed, &initialized.upload_id)?;
        self.wait_for_upload(&initialized.upload_id, wait_seconds)
    }

    fn upload_multipart(
        &self,
        headers: &HashMap<String, String>,
        path: &Path,
        size: u64,
        logical_name: &str,
        multipart: &MultipartInitResponse,
    ) -> Result<Vec<Value>> {
        let part_size = multipart.part_size.unwrap_or(DEFAULT_PART_SIZE);
        if part_size == 0 {
            return Err(PublishError::message("multipart upload returned an invalid part_size"));
        }
        let expected_count = size.div_ceil(part_size);
        if multipart.parts.len() as u64 != expected_count {
            return Err(PublishError::message(format!(
                "multipart upload returned {} parts; expected {expected_count}",
                multipart.parts.len()
            )));
        }
        let mut result = Vec::with_capacity(multipart.parts.len());
        for (index, part) in multipart.parts.iter().enumerate() {
            let expected_number = u32::try_from(index + 1)
                .map_err(|_| PublishError::message("multipart part number overflow"))?;
            if part.part_number != expected_number {
                return Err(PublishError::message(
                    "multipart upload returned non-contiguous part numbers",
                ));
            }
            let offset = u64::from(part.part_number - 1) * part_size;
            let length = (size - offset).min(part_size);
            let etag = self
                .api
                .put_file_range(&part.url, headers, path, offset, length, Some(part.part_number))?
                .ok_or_else(|| {
                    PublishError::message(format!(
                        "multipart upload part {} returned no ETag",
                        part.part_number
                    ))
                })?;
            result.push(json!({"part_number": part.part_number, "etag": etag}));
            self.stage(&format!(
                "uploaded multipart part {}/{} for {}",
                index + 1,
                multipart.parts.len(),
                logical_name
            ));
        }
        Ok(result)
    }

    fn wait_for_upload(&self, upload_id: &str, wait_seconds: u64) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(wait_seconds);
        loop {
            let upload: UploadCompletionResponse =
                self.api.request_json(Method::GET, &format!("/uploads/{upload_id}"), None)?;
            validate_upload_response(&upload, upload_id)?;
            match upload.verification_status {
                UploadLifecycleStatus::Accepted => return Ok(()),
                UploadLifecycleStatus::Rejected | UploadLifecycleStatus::Quarantined => {
                    return Err(PublishError::message(format!(
                        "artifact upload ended in {}: {}",
                        upload.verification_status.as_str(),
                        upload.rejection_reason.as_deref().unwrap_or("no rejection reason")
                    )))
                }
                _ => {}
            }
            if Instant::now() >= deadline {
                return Err(PublishError::message(format!(
                    "timed out waiting for upload {upload_id}"
                )));
            }
            thread::sleep(self.poll_interval);
        }
    }

    fn wait_for_publication(
        &self,
        publication_id: &str,
        wait_seconds: u64,
    ) -> Result<PublicationStatusResponse> {
        let deadline = Instant::now() + Duration::from_secs(wait_seconds);
        loop {
            let status: PublicationStatusResponse = self.api.request_json(
                Method::GET,
                &format!("/build-publications/{publication_id}"),
                None,
            )?;
            if status.publication.as_ref().map(|item| item.id.as_str()) != Some(publication_id) {
                return Err(PublishError::message(
                    "Publication status returned the wrong publication id",
                ));
            }
            if status.ready && status.status == PublicationState::Ready {
                return Ok(status);
            }
            if status.status == PublicationState::Rejected {
                let reasons = status
                    .rejected_artifacts
                    .iter()
                    .map(|item| {
                        format!(
                            "{}:{}:{}",
                            item.kind,
                            item.logical_name,
                            item.rejection_reason.as_deref().unwrap_or("rejected")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(", ");
                return Err(PublishError::message(format!(
                    "Build Publication was rejected: {reasons}"
                )));
            }
            if Instant::now() >= deadline {
                return Err(PublishError::message(format!(
                    "timed out waiting for Publication {publication_id}; last state {}",
                    status.status.as_str()
                )));
            }
            thread::sleep(self.poll_interval);
        }
    }

    fn stage(&self, message: &str) {
        if self.progress {
            eprintln!("crashcap: {message}");
        }
    }
}

fn prepare_zstd_wire_artifact(artifact: &PreparedArtifact) -> Result<WireArtifact> {
    if artifact.kind != ArtifactKind::Pdb {
        return Ok(WireArtifact::identity(artifact));
    }
    let temp_root = std::env::temp_dir();
    let available = fs2::available_space(&temp_root).map_err(|error| {
        PublishError::message(format!(
            "cannot inspect temporary-disk capacity at {}: {error}",
            temp_root.display()
        ))
    })?;
    let required = artifact.size.saturating_add(TEMP_CAPACITY_RESERVE);
    if available < required {
        return Err(PublishError::message(format!(
            "temporary disk has {available} bytes available; at least {required} are required"
        )));
    }

    let mut temporary = NamedTempFile::new_in(&temp_root).map_err(|error| {
        PublishError::message(format!("cannot create bounded wire payload file: {error}"))
    })?;
    let mut source = fs::File::open(&artifact.path).map_err(|error| {
        PublishError::message(format!(
            "cannot open Artifact {} for wire compression: {error}",
            artifact.path.display()
        ))
    })?;
    {
        let mut encoder = zstd::stream::write::Encoder::new(temporary.as_file_mut(), ZSTD_LEVEL)
            .map_err(|error| {
                PublishError::message(format!("cannot initialize zstd-v1 encoder: {error}"))
            })?;
        encoder.include_checksum(true).map_err(|error| {
            PublishError::message(format!("cannot enable zstd-v1 checksum: {error}"))
        })?;
        encoder.set_pledged_src_size(Some(artifact.size)).map_err(|error| {
            PublishError::message(format!("cannot declare zstd-v1 content size: {error}"))
        })?;
        std::io::copy(&mut source, &mut encoder).map_err(|error| {
            PublishError::message(format!("zstd-v1 streaming compression failed: {error}"))
        })?;
        encoder.finish().map_err(|error| {
            PublishError::message(format!("cannot finalize zstd-v1 payload: {error}"))
        })?;
    }
    temporary
        .as_file_mut()
        .flush()
        .map_err(|error| PublishError::message(format!("cannot flush zstd-v1 payload: {error}")))?;
    let size = temporary
        .as_file()
        .metadata()
        .map_err(|error| PublishError::message(format!("cannot inspect zstd-v1 payload: {error}")))?
        .len();
    if size == 0 || size >= artifact.size {
        return Ok(WireArtifact::identity(artifact));
    }
    let sha256 = sha256_path(temporary.path())?;
    Ok(WireArtifact {
        path: temporary.path().to_path_buf(),
        size,
        sha256,
        encoding: "zstd-v1",
        _temporary: Some(temporary),
    })
}

fn sha256_path(path: &Path) -> Result<String> {
    let mut source = fs::File::open(path).map_err(|error| {
        PublishError::message(format!("cannot hash wire payload {}: {error}", path.display()))
    })?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let read = source.read(&mut buffer).map_err(|error| {
            PublishError::message(format!("cannot hash wire payload {}: {error}", path.display()))
        })?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn client_publication_id(prepared: &PreparedProfile, origin: PublicationOrigin) -> Result<String> {
    let inventory = prepared
        .artifacts
        .iter()
        .map(|artifact| {
            json!({
                "module_code_file": artifact.module_code_file,
                "kind": artifact.kind.as_str(),
                "logical_name": artifact.logical_name,
                "size": artifact.size,
                "sha256": artifact.sha256,
            })
        })
        .collect::<Vec<_>>();
    let identity = json!({
        "schema_version": "1.0",
        "origin": origin.as_str(),
        "profile": prepared.profile,
        "git": prepared.git,
        "manifest": prepared.manifest,
        "artifacts": inventory,
    });
    let encoded = serde_json::to_vec(&identity).map_err(|error| {
        PublishError::message(format!("cannot encode Publication identity: {error}"))
    })?;
    let digest = format!("{:x}", Sha256::digest(encoded));
    Ok(format!("{}:{digest}", origin.as_str()))
}

fn write_receipt(path: &Path, receipt: &Value) -> Result<()> {
    let encoded = serde_json::to_vec_pretty(receipt)
        .map_err(|error| PublishError::message(format!("cannot encode receipt: {error}")))?;
    fs::write(path, encoded).map_err(|error| {
        PublishError::message(format!("cannot write receipt {}: {error}", path.display()))
    })
}

fn validate_upload_response(response: &UploadCompletionResponse, upload_id: &str) -> Result<()> {
    if response.upload_id != upload_id {
        return Err(PublishError::message("Upload response returned the wrong upload_id"));
    }
    if response.status != response.verification_status {
        return Err(PublishError::message(
            "Upload response returned inconsistent lifecycle states",
        ));
    }
    if let Some(delivery) = response.delivery.as_deref() {
        if !matches!(delivery, "uploaded" | "reused" | "backfilled")
            || !response.artifact_blob_id.as_deref().is_some_and(|id| id.starts_with("abl_"))
        {
            return Err(PublishError::message(
                "Upload response returned inconsistent Artifact Blob receipt fields",
            ));
        }
    } else if response.artifact_blob_id.is_some() {
        return Err(PublishError::message(
            "Upload response returned an Artifact Blob without a delivery disposition",
        ));
    }
    Ok(())
}

fn remaining_duration(deadline: Instant, label: &str) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| PublishError::message(format!("timed out waiting for {label}")))
}

fn remaining_seconds(deadline: Instant, label: &str) -> Result<u64> {
    let remaining = remaining_duration(deadline, label)?;
    Ok(remaining.as_secs().saturating_add(u64::from(remaining.subsec_nanos() > 0)).max(1))
}

fn version_at_least(actual: &str, minimum: &str) -> bool {
    fn parts(value: &str) -> Option<[u64; 3]> {
        let parsed = value
            .split('.')
            .take(3)
            .map(|part| part.split('-').next().unwrap_or(part).parse::<u64>().ok())
            .collect::<Option<Vec<_>>>()?;
        (parsed.len() == 3).then(|| [parsed[0], parsed[1], parsed[2]])
    }
    matches!((parts(actual), parts(minimum)), (Some(actual), Some(minimum)) if actual >= minimum)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::io::Read;

    use tempfile::tempdir;

    use crate::config::{ArtifactKind, PreparedArtifact};

    use super::{prepare_zstd_wire_artifact, sha256_path, version_at_least};

    #[test]
    fn semantic_version_floor_is_numeric() {
        assert!(version_at_least("1.10.0", "1.2.0"));
        assert!(version_at_least("1.0.0", "1.0.0"));
        assert!(!version_at_least("0.9.9", "1.0.0"));
        assert!(!version_at_least("invalid", "1.0.0"));
    }

    #[test]
    fn pdb_wire_compression_is_streamed_and_round_trips_exactly() {
        let root = tempdir().expect("temporary directory");
        let source = root.path().join("large.pdb");
        let raw = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0"
            .iter()
            .copied()
            .chain(std::iter::repeat(b'P').take(2 * 1024 * 1024))
            .collect::<Vec<_>>();
        fs::write(&source, &raw).expect("write source PDB");
        let artifact = PreparedArtifact {
            module_code_file: "app.exe".to_owned(),
            kind: ArtifactKind::Pdb,
            logical_name: "app.pdb".to_owned(),
            path: source,
            size: raw.len() as u64,
            sha256: sha256_path(&root.path().join("large.pdb")).expect("raw sha256"),
        };

        let wire = prepare_zstd_wire_artifact(&artifact).expect("prepare compressed wire payload");
        assert_eq!(wire.encoding, "zstd-v1");
        assert!(wire.size < artifact.size);
        assert_eq!(sha256_path(&wire.path).expect("wire sha256"), wire.sha256);
        let mut decoded = Vec::new();
        zstd::stream::read::Decoder::new(fs::File::open(&wire.path).expect("wire file"))
            .expect("zstd decoder")
            .read_to_end(&mut decoded)
            .expect("decode wire payload");
        assert_eq!(decoded, raw);
    }
}
