use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct WorkspaceResponse {
    pub(crate) id: String,
    pub(crate) name: String,
}
#[derive(Clone, Debug, Deserialize)]
pub(crate) struct UploadInitResponse {
    pub(crate) upload_id: String,
    pub(crate) method: String,
    pub(crate) url: Option<String>,
    #[serde(default)]
    pub(crate) headers: HashMap<String, String>,
    pub(crate) multipart: Option<MultipartInitResponse>,
}
#[derive(Clone, Debug, Deserialize)]
pub(crate) struct MultipartInitResponse {
    pub(crate) upload_id: String,
    pub(crate) parts: Vec<MultipartPartUrl>,
    pub(crate) part_size: Option<u64>,
}
#[derive(Clone, Debug, Deserialize)]
pub(crate) struct MultipartPartUrl {
    pub(crate) part_number: u32,
    pub(crate) url: String,
}
#[derive(Clone, Debug, Serialize)]
pub(crate) struct CompletedPart {
    pub(crate) part_number: u32,
    pub(crate) etag: String,
}
