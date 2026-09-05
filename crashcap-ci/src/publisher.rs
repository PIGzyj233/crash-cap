use crate::{
    error::{PublishError, Result},
    http::ApiClient,
    wire::{CompletedPart, UploadInitResponse, WorkspaceResponse},
};
use reqwest::Method;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    thread,
    time::{Duration, Instant},
};

pub struct Uploader<'a> {
    api: &'a ApiClient,
    progress: bool,
    timeout: Duration,
    interval: Duration,
}
impl<'a> Uploader<'a> {
    pub fn new(api: &'a ApiClient, progress: bool) -> Self {
        Self { api, progress, timeout: Duration::from_secs(900), interval: Duration::from_secs(1) }
    }
    pub fn upload(
        &self,
        roots: Vec<PathBuf>,
        workspace: Option<String>,
        public: bool,
        version: Option<String>,
        receipt: &Path,
    ) -> Result<Value> {
        let files = discover(&roots)?;
        if files.is_empty() {
            return Err(PublishError::message("no .exe, .dll, .pdb or .dmp files found"));
        }
        if public && files.iter().any(|path| kind(path) == Some("dmp")) {
            return Err(PublishError::message("public space does not accept DMP files; select --workspace for this batch. No files were uploaded"));
        }
        let workspace_id = if public {
            None
        } else {
            Some(
                self.resolve_workspace(
                    workspace
                        .as_deref()
                        .ok_or_else(|| PublishError::message("select --workspace or --public"))?,
                )?,
            )
        };
        let version =
            version.map(|value| value.trim().to_owned()).filter(|value| !value.is_empty());
        let mut result = json!({"schema_version":"upload-receipt-v3", "command":"upload", "target":{"workspace_id":workspace_id,"public":public},"version":version,"total":files.len(),"succeeded":0,"failed":0,"files":[],"receipt":receipt});
        // Verify the receipt destination before changing external state.
        write_receipt(receipt, &result)?;
        for path in files {
            let mut row = json!({"path":path,"filename":path.file_name().map(|name|name.to_string_lossy()),"status":"uploading","ok":false});
            if self.progress {
                eprintln!("crashcap: uploading {}", path.display());
            }
            match self.upload_one(&path, workspace_id.as_deref(), version.as_deref(), &mut row) {
                Ok(()) => {
                    row["ok"] = json!(true);
                    result["succeeded"] = json!(result["succeeded"].as_u64().unwrap() + 1);
                }
                Err(error) => {
                    row["status"] = json!("failed");
                    row["error"] = json!({"message":crate::redact(&error.to_string())});
                    result["failed"] = json!(result["failed"].as_u64().unwrap() + 1);
                }
            }
            result["files"].as_array_mut().unwrap().push(row);
            write_receipt(receipt, &result)?;
        }
        Ok(result)
    }
    fn resolve_workspace(&self, requested: &str) -> Result<String> {
        let rows: Vec<WorkspaceResponse> =
            self.api.request_json(Method::GET, "/workspaces", None)?;
        let matches = rows
            .into_iter()
            .filter(|row| row.id == requested || row.name == requested)
            .collect::<Vec<_>>();
        match matches.as_slice() {
            [one] => Ok(one.id.clone()),
            [] => Err(PublishError::message(format!(
                "Workspace {requested:?} was not found; use its ID or exact name"
            ))),
            _ => Err(PublishError::message("Workspace name is ambiguous; use its ID")),
        }
    }
    fn upload_one(
        &self,
        path: &Path,
        workspace: Option<&str>,
        version: Option<&str>,
        row: &mut Value,
    ) -> Result<()> {
        let size = fs::metadata(path).map_err(io_error)?.len();
        if size == 0 {
            return Err(PublishError::message("empty files are not accepted"));
        }
        let sha256 = sha256(path)?;
        let filename = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| PublishError::message("filename is not valid UTF-8"))?;
        let init: UploadInitResponse = self.api.request_json(Method::POST,"/uploads:init",Some(&json!({"workspace_id":workspace,"file_kind":kind(path).unwrap(),"filename":filename,"size":size,"sha256":sha256,"version":version,"source":"cli"})))?;
        row["upload_id"] = json!(init.upload_id);
        row["links"] =
            json!({"upload":self.api.resource_url(&format!("uploads/{}",init.upload_id))?});
        if init.method != "PUT" {
            return Err(PublishError::message("unsupported object upload method"));
        }
        let completion = if let Some(multipart) = &init.multipart {
            let part_size = multipart
                .part_size
                .ok_or_else(|| PublishError::message("multipart response omitted part_size"))?;
            if part_size == 0 || multipart.parts.len() as u64 != size.div_ceil(part_size) {
                return Err(PublishError::message(
                    "multipart part count differs from the file size",
                ));
            }
            let mut parts = Vec::new();
            for (index, part) in multipart.parts.iter().enumerate() {
                if part.part_number as usize != index + 1 {
                    return Err(PublishError::message("multipart parts are not contiguous"));
                }
                let offset = index as u64 * part_size;
                let etag = self
                    .api
                    .put_file_range(
                        &part.url,
                        &init.headers,
                        path,
                        offset,
                        (size - offset).min(part_size),
                        Some(part.part_number),
                    )?
                    .ok_or_else(|| PublishError::message("multipart response omitted ETag"))?;
                parts.push(CompletedPart { part_number: part.part_number, etag });
            }
            json!({"multipart_upload_id":multipart.upload_id,"parts":parts})
        } else {
            let url = init
                .url
                .as_deref()
                .ok_or_else(|| PublishError::message("upload init omitted url"))?;
            json!({"etag":self.api.put_file_range(url,&init.headers,path,0,size,None)?})
        };
        let mut status = self.api.request_value(
            Method::POST,
            &format!("/uploads/{}:complete", init.upload_id),
            Some(&completion),
        )?;
        let started = Instant::now();
        loop {
            row["result"] = status.clone();
            match status["verification_status"].as_str() {
                Some("ACCEPTED") => {
                    row["status"] = json!("accepted");
                    if let Some(id) = status["occurrence_id"].as_str() {
                        row["links"]["occurrence"] =
                            json!(self.api.resource_url(&format!("occurrences/{id}"))?);
                    }
                    if let Some(id) = status["artifact_entry_id"].as_str() {
                        row["links"]["artifact"] =
                            json!(self.api.resource_url(&format!("artifacts/{id}"))?);
                    }
                    return Ok(());
                }
                Some("REJECTED" | "QUARANTINED") => {
                    return Err(PublishError::message(
                        status["rejection_reason"].as_str().unwrap_or("file verification failed"),
                    ))
                }
                Some("VERIFYING" | "UPLOADED" | "UPLOADING" | "INITIALIZED") => {}
                _ => {
                    return Err(PublishError::message(
                        "upload query returned an unknown verification state",
                    ))
                }
            }
            if started.elapsed() >= self.timeout {
                return Err(PublishError::message("file verification timed out; use the upload link in the receipt to check later"));
            }
            thread::sleep(self.interval);
            status = self.api.request_value(
                Method::GET,
                &format!("/uploads/{}", init.upload_id),
                None,
            )?;
        }
    }
}
fn io_error(error: std::io::Error) -> PublishError {
    PublishError::message(format!("file I/O failed: {error}"))
}
fn discover(roots: &[PathBuf]) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    for root in roots {
        if !root.exists() {
            return Err(PublishError::message(format!("input does not exist: {}", root.display())));
        }
        for entry in walkdir::WalkDir::new(root).follow_links(false) {
            let entry = entry.map_err(|error| {
                PublishError::message(format!("cannot read input directory: {error}"))
            })?;
            if entry.file_type().is_file() && kind(entry.path()).is_some() {
                files.push(entry.path().canonicalize().map_err(io_error)?);
            }
        }
    }
    files.sort();
    files.dedup();
    Ok(files)
}
fn kind(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()?.to_ascii_lowercase().as_str() {
        "exe" | "dll" => Some("pe"),
        "pdb" => Some("pdb"),
        "dmp" => Some("dmp"),
        _ => None,
    }
}
fn sha256(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path).map_err(io_error)?;
    let mut hash = Sha256::new();
    let mut buffer = vec![0; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer).map_err(io_error)?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hash.finalize()))
}
fn write_receipt(path: &Path, value: &Value) -> Result<()> {
    let parent =
        path.parent().filter(|path| !path.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(parent).map_err(io_error)?;
    let mut temp = tempfile::NamedTempFile::new_in(parent).map_err(io_error)?;
    temp.write_all(&serde_json::to_vec_pretty(value).expect("serializable receipt"))
        .map_err(io_error)?;
    temp.as_file().sync_all().map_err(io_error)?;
    temp.persist(path).map_err(|error| io_error(error.error))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn recursive_discovery_deduplicates_paths_and_ignores_other_files() {
        let root = tempfile::tempdir().unwrap();
        fs::create_dir(root.path().join("sub")).unwrap();
        fs::write(root.path().join("sub/a.PDB"), b"data").unwrap();
        fs::write(root.path().join("x.txt"), b"text").unwrap();
        assert_eq!(
            discover(&[root.path().into(), root.path().join("sub/a.PDB")]).unwrap().len(),
            1
        );
    }
    #[test]
    fn receipt_replacement_is_complete_json() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("receipt.json");
        write_receipt(&path, &json!({"failed":1})).unwrap();
        write_receipt(&path, &json!({"succeeded":2})).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&fs::read(path).unwrap()).unwrap(),
            json!({"succeeded":2})
        );
    }
}
