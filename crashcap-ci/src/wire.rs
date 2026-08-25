use std::collections::HashMap;

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct WorkspaceResponse {
    pub(crate) id: String,
    pub(crate) name: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct ArtifactProducerResponse {
    pub(crate) producer: String,
    pub(crate) status: String,
    pub(crate) publication_contracts: Vec<String>,
    pub(crate) minimum_client_version: String,
    pub(crate) build_publications_enabled: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct PublicationSummaryResponse {
    pub(crate) id: String,
    pub(crate) workspace_id: String,
    pub(crate) build_id: String,
    pub(crate) origin: String,
    pub(crate) client_publication_id: String,
    pub(crate) client_version: String,
    pub(crate) git_revision: Option<String>,
    pub(crate) git_worktree_state: String,
    pub(crate) created_at: String,
    pub(crate) last_seen_at: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum PublicationState {
    Registered,
    Uploading,
    Verifying,
    Ready,
    Rejected,
}

impl PublicationState {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Registered => "registered",
            Self::Uploading => "uploading",
            Self::Verifying => "verifying",
            Self::Ready => "ready",
            Self::Rejected => "rejected",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ExpectedArtifactState {
    Missing,
    Uploading,
    Verifying,
    Verified,
    Rejected,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct ExpectedArtifactResponse {
    pub(crate) module_id: String,
    pub(crate) module_code_file: String,
    pub(crate) kind: String,
    pub(crate) logical_name: String,
    pub(crate) size: u64,
    pub(crate) sha256: String,
    pub(crate) status: ExpectedArtifactState,
    pub(crate) artifact_id: Option<String>,
    pub(crate) upload_id: Option<String>,
    pub(crate) rejection_reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct PublicationStatusResponse {
    pub(crate) publication: Option<PublicationSummaryResponse>,
    pub(crate) publications: Vec<PublicationSummaryResponse>,
    pub(crate) build_id: String,
    pub(crate) identity_mode: String,
    pub(crate) fingerprint_version: String,
    pub(crate) content_fingerprint: String,
    pub(crate) status: PublicationState,
    pub(crate) sealed_at: Option<String>,
    pub(crate) expected_artifacts: Vec<ExpectedArtifactResponse>,
    pub(crate) missing_artifacts: Vec<ExpectedArtifactResponse>,
    pub(crate) rejected_artifacts: Vec<ExpectedArtifactResponse>,
    pub(crate) ready: bool,
}

#[derive(Debug, Deserialize)]
pub(crate) struct UploadInitResponse {
    pub(crate) upload_id: String,
    pub(crate) method: UploadMethod,
    pub(crate) url: String,
    pub(crate) headers: HashMap<String, String>,
    pub(crate) expires_in: u64,
    pub(crate) multipart: Option<MultipartInitResponse>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
pub(crate) enum UploadMethod {
    #[serde(rename = "PUT")]
    Put,
    #[serde(rename = "POST")]
    Post,
}

#[derive(Debug, Deserialize)]
pub(crate) struct MultipartInitResponse {
    pub(crate) upload_id: String,
    pub(crate) part_size: Option<u64>,
    pub(crate) parts: Vec<MultipartPartResponse>,
}

#[derive(Debug, Deserialize)]
pub(crate) struct MultipartPartResponse {
    pub(crate) part_number: u32,
    pub(crate) url: String,
}

#[derive(Debug, Deserialize)]
pub(crate) struct UploadCompletionResponse {
    pub(crate) upload_id: String,
    pub(crate) status: UploadLifecycleStatus,
    pub(crate) verification_status: UploadLifecycleStatus,
    pub(crate) rejection_reason: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
pub(crate) enum UploadLifecycleStatus {
    #[serde(rename = "INITIALIZED")]
    Initialized,
    #[serde(rename = "UPLOADING")]
    Uploading,
    #[serde(rename = "UPLOADED")]
    Uploaded,
    #[serde(rename = "VERIFYING")]
    Verifying,
    #[serde(rename = "ACCEPTED")]
    Accepted,
    #[serde(rename = "QUARANTINED")]
    Quarantined,
    #[serde(rename = "REJECTED")]
    Rejected,
}

impl UploadLifecycleStatus {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Initialized => "INITIALIZED",
            Self::Uploading => "UPLOADING",
            Self::Uploaded => "UPLOADED",
            Self::Verifying => "VERIFYING",
            Self::Accepted => "ACCEPTED",
            Self::Quarantined => "QUARANTINED",
            Self::Rejected => "REJECTED",
        }
    }
}
