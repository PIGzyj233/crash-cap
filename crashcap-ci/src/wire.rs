use std::collections::HashMap;

use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub(crate) struct WorkspaceResponse {
    pub(crate) id: String,
    pub(crate) name: String,
}

#[derive(Debug, Deserialize)]
pub(crate) struct ProducerResponse {
    pub(crate) producer: ProducerName,
    pub(crate) status: ProducerStatus,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum ProducerName {
    Msvc,
    ClangCl,
    Crashpad,
}

impl ProducerName {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Msvc => "msvc",
            Self::ClangCl => "clang-cl",
            Self::Crashpad => "crashpad",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ProducerStatus {
    Supported,
    Experimental,
}

impl ProducerStatus {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Supported => "supported",
            Self::Experimental => "experimental",
        }
    }
}

#[derive(Debug, Deserialize)]
pub(crate) struct BuildResponse {
    pub(crate) id: String,
    pub(crate) artifacts: Vec<ArtifactResponse>,
}

#[derive(Debug, Deserialize)]
pub(crate) struct ArtifactResponse {
    pub(crate) kind: ArtifactKind,
    pub(crate) logical_name: String,
    pub(crate) sha256: String,
    pub(crate) verification_status: ArtifactVerificationStatus,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ArtifactKind {
    Pe,
    Pdb,
    SourceBundle,
}

impl ArtifactKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::Pe => "pe",
            Self::Pdb => "pdb",
            Self::SourceBundle => "source_bundle",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ArtifactVerificationStatus {
    Pending,
    Verified,
    RejectedFastlink,
    PdbMismatch,
    PeMismatch,
    Corrupted,
    RejectedFormat,
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

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct CiStatusResponse {
    pub(crate) build_id: String,
    pub(crate) manifest_schema_version: Option<ManifestSchemaVersion>,
    pub(crate) producer: Option<ProducerNameForOutput>,
    pub(crate) producer_status: CiProducerStatus,
    pub(crate) manifest_present: bool,
    pub(crate) module_count: u64,
    pub(crate) missing_artifacts: Vec<MissingArtifactResponse>,
    pub(crate) rejected_artifacts: Vec<RejectedArtifactResponse>,
    pub(crate) source_bundle_status: SourceBundleStatus,
    pub(crate) ready: bool,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) enum ManifestSchemaVersion {
    #[serde(rename = "1.0")]
    V1,
    #[serde(rename = "2.0")]
    V2,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum ProducerNameForOutput {
    Msvc,
    ClangCl,
    Crashpad,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CiProducerStatus {
    Supported,
    Experimental,
    Unregistered,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct MissingArtifactResponse {
    pub(crate) module_id: String,
    pub(crate) kind: PePdbKind,
    pub(crate) logical_name: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum PePdbKind {
    Pe,
    Pdb,
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct RejectedArtifactResponse {
    pub(crate) artifact_id: String,
    pub(crate) logical_name: String,
    pub(crate) status: RejectedArtifactStatus,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RejectedArtifactStatus {
    RejectedFastlink,
    PdbMismatch,
    PeMismatch,
    Corrupted,
    RejectedFormat,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum SourceBundleStatus {
    NotDeclared,
    Verified,
    Pending,
    MissingOrRejected,
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{UploadInitResponse, WorkspaceResponse};

    #[test]
    fn typed_decode_tolerates_unknown_fields_but_requires_consumed_fields() {
        let workspace: WorkspaceResponse = serde_json::from_value(json!({
            "id": "wsp_test",
            "name": "test",
            "future_additive_field": {"safe": true}
        }))
        .expect("unknown fields remain forward-compatible");
        assert_eq!(workspace.id, "wsp_test");

        assert!(serde_json::from_value::<WorkspaceResponse>(json!({"id": "wsp_test"})).is_err());
        assert!(serde_json::from_value::<WorkspaceResponse>(json!({
            "id": 7,
            "name": "test"
        }))
        .is_err());
    }

    #[test]
    fn multipart_part_size_supports_new_and_old_servers_and_rejects_unknown_enums() {
        let base = json!({
            "upload_id": "upl_test",
            "method": "PUT",
            "url": "",
            "headers": {},
            "expires_in": 900,
            "multipart": {
                "upload_id": "mp_test",
                "parts": [{"part_number": 1, "url": "http://upload.invalid/1"}]
            }
        });
        let old: UploadInitResponse =
            serde_json::from_value(base.clone()).expect("old server omits additive part_size");
        assert_eq!(old.multipart.expect("multipart").part_size, None);

        let mut new = base;
        new["multipart"]["part_size"] = json!(5);
        let new: UploadInitResponse =
            serde_json::from_value(new).expect("new server provides part_size");
        assert_eq!(new.multipart.expect("multipart").part_size, Some(5));

        let invalid = json!({
            "upload_id": "upl_test",
            "method": "PATCH",
            "url": "http://upload.invalid/object",
            "headers": {},
            "expires_in": 900
        });
        assert!(serde_json::from_value::<UploadInitResponse>(invalid).is_err());
    }
}
