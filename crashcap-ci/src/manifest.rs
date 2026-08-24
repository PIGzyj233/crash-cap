use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};

use jsonschema::Validator;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use walkdir::WalkDir;

use crate::error::{PublishError, Result};

const BUILD_MANIFEST_V1: &str = include_str!("../../contracts/build-manifest-v1.schema.json");
const BUILD_MANIFEST_V2: &str = include_str!("../../contracts/build-manifest-v2.schema.json");
const HASH_BUFFER_SIZE: usize = 1024 * 1024;

#[derive(Clone, Debug, Deserialize)]
pub struct BuildManifest {
    pub schema_version: String,
    pub version: String,
    pub channel: Option<String>,
    pub commit: Option<String>,
    pub build_number: Option<String>,
    pub architecture: String,
    pub toolchain: Option<String>,
    pub modules: Vec<ManifestModule>,
    pub source_bundle: Option<SourceBundle>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ManifestModule {
    pub code_file: String,
    pub debug_file: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct SourceBundle {
    pub archive: String,
}

#[derive(Clone, Debug)]
pub struct LoadedManifest {
    pub raw: Value,
    pub manifest: BuildManifest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactKind {
    Pe,
    Pdb,
    SourceBundle,
}

impl ArtifactKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pe => "pe",
            Self::Pdb => "pdb",
            Self::SourceBundle => "source_bundle",
        }
    }
}

#[derive(Clone, Debug)]
pub struct RequiredArtifact {
    pub kind: ArtifactKind,
    pub path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct PreparedArtifact {
    pub kind: ArtifactKind,
    pub path: PathBuf,
    pub size: u64,
    pub sha256: String,
}

pub fn load_manifest(path: &Path) -> Result<LoadedManifest> {
    let source = fs::read_to_string(path)
        .map_err(|error| PublishError::message(format!("cannot read Build Manifest: {error}")))?;
    let raw: Value = serde_json::from_str(&source)
        .map_err(|error| PublishError::message(format!("cannot read Build Manifest: {error}")))?;
    if !raw.is_object() {
        return Err(PublishError::message("Build Manifest must be a JSON object"));
    }
    let version = raw.get("schema_version").and_then(Value::as_str).unwrap_or_default();
    let schema_source = match version {
        "1.0" => BUILD_MANIFEST_V1,
        "2.0" => BUILD_MANIFEST_V2,
        _ => return Err(PublishError::message("Build Manifest schema_version must be 1.0 or 2.0")),
    };
    let schema: Value = serde_json::from_str(schema_source).map_err(|error| {
        PublishError::message(format!("embedded Build Manifest schema is invalid: {error}"))
    })?;
    let validator = compile_schema(&schema)?;
    let mut errors = validator.iter_errors(&raw).collect::<Vec<_>>();
    errors.sort_by_key(|error| error.instance_path.to_string());
    if let Some(error) = errors.first() {
        let path = error.instance_path.to_string();
        let location = if path.is_empty() { "/" } else { path.as_str() };
        return Err(PublishError::message(format!(
            "Build Manifest validation failed at {location}: {error}"
        )));
    }
    let manifest: BuildManifest = serde_json::from_value(raw.clone()).map_err(|error| {
        PublishError::message(format!("Build Manifest cannot be decoded: {error}"))
    })?;
    if manifest.schema_version != version {
        return Err(PublishError::message("Build Manifest schema_version changed during decoding"));
    }
    Ok(LoadedManifest { raw, manifest })
}

fn compile_schema(schema: &Value) -> Result<Validator> {
    jsonschema::validator_for(schema).map_err(|error| {
        PublishError::message(format!("embedded Build Manifest schema is invalid: {error}"))
    })
}

pub fn required_artifacts(
    manifest: &BuildManifest,
    artifact_root: &Path,
) -> Result<Vec<RequiredArtifact>> {
    if !artifact_root.is_dir() {
        return Err(PublishError::message(format!(
            "artifact root is not a directory: {}",
            artifact_root.display()
        )));
    }
    let available = files_by_basename(artifact_root)?;
    let mut required = Vec::new();
    for module in &manifest.modules {
        required.push(resolve_artifact(
            &available,
            ArtifactKind::Pe,
            &module.code_file,
            "CI artifact",
        )?);
        required.push(resolve_artifact(
            &available,
            ArtifactKind::Pdb,
            &module.debug_file,
            "CI artifact",
        )?);
    }
    if let Some(source) = &manifest.source_bundle {
        required.push(resolve_artifact(
            &available,
            ArtifactKind::SourceBundle,
            &source.archive,
            "source bundle",
        )?);
    }
    Ok(required)
}

fn files_by_basename(root: &Path) -> Result<HashMap<String, Vec<PathBuf>>> {
    let mut result: HashMap<String, Vec<PathBuf>> = HashMap::new();
    for entry in WalkDir::new(root).follow_links(false) {
        let entry = entry.map_err(|error| {
            PublishError::message(format!("cannot inspect artifact root: {error}"))
        })?;
        if entry.path().is_file() {
            let basename = entry.file_name().to_string_lossy().to_lowercase();
            result.entry(basename).or_default().push(entry.path().to_path_buf());
        }
    }
    Ok(result)
}

fn resolve_artifact(
    available: &HashMap<String, Vec<PathBuf>>,
    kind: ArtifactKind,
    logical_name: &str,
    label: &str,
) -> Result<RequiredArtifact> {
    let matches =
        available.get(&logical_name.to_lowercase()).map(Vec::as_slice).unwrap_or_default();
    if matches.len() != 1 {
        return Err(PublishError::message(format!(
            "{label} {logical_name} must resolve to exactly one file; found {}",
            matches.len()
        )));
    }
    Ok(RequiredArtifact { kind, path: matches[0].clone() })
}

pub fn prepare_artifacts(required: Vec<RequiredArtifact>) -> Result<Vec<PreparedArtifact>> {
    required
        .into_iter()
        .map(|artifact| {
            let metadata = fs::metadata(&artifact.path).map_err(|error| {
                PublishError::message(format!(
                    "cannot inspect artifact {}: {error}",
                    artifact.path.display()
                ))
            })?;
            let sha256 = sha256_file(&artifact.path)?;
            Ok(PreparedArtifact {
                kind: artifact.kind,
                path: artifact.path,
                size: metadata.len(),
                sha256,
            })
        })
        .collect()
}

pub fn sha256_file(path: &Path) -> Result<String> {
    let file = File::open(path).map_err(|error| {
        PublishError::message(format!("cannot hash artifact {}: {error}", path.display()))
    })?;
    let mut reader = BufReader::with_capacity(HASH_BUFFER_SIZE, file);
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; HASH_BUFFER_SIZE];
    loop {
        let count = reader.read(&mut buffer).map_err(|error| {
            PublishError::message(format!("cannot hash artifact {}: {error}", path.display()))
        })?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use std::fs;

    use serde_json::json;
    use tempfile::tempdir;

    use super::{load_manifest, prepare_artifacts, required_artifacts, sha256_file};

    fn manifest(version: &str) -> serde_json::Value {
        json!({
            "schema_version": version,
            "product": "Native CLI",
            "version": "1.0.0",
            "architecture": "x86_64",
            "compiler": "msvc",
            "modules": [{
                "code_file": "App.EXE",
                "debug_file": "App.PDB",
                "role": "entrypoint"
            }]
        })
    }

    #[test]
    fn validates_v1_and_v2_from_embedded_schemas() {
        let directory = tempdir().expect("temporary directory");
        for version in ["1.0", "2.0"] {
            let path = directory.path().join(format!("manifest-{version}.json"));
            fs::write(&path, manifest(version).to_string()).expect("write manifest");
            let loaded = load_manifest(&path).expect("valid embedded schema");
            assert_eq!(loaded.manifest.schema_version, version);
        }
    }

    #[test]
    fn rejects_unknown_schema_and_invalid_manifest() {
        let directory = tempdir().expect("temporary directory");
        let unknown = directory.path().join("unknown.json");
        fs::write(&unknown, manifest("3.0").to_string()).expect("write manifest");
        assert!(load_manifest(&unknown)
            .expect_err("unknown version")
            .to_string()
            .contains("1.0 or 2.0"));

        let invalid = directory.path().join("invalid.json");
        let mut value = manifest("1.0");
        value["modules"] = json!([]);
        fs::write(&invalid, value.to_string()).expect("write manifest");
        assert!(load_manifest(&invalid)
            .expect_err("empty modules")
            .to_string()
            .contains("validation failed"));
    }

    #[test]
    fn resolves_case_insensitively_and_rejects_duplicates() {
        let directory = tempdir().expect("temporary directory");
        let manifest_path = directory.path().join("manifest.json");
        fs::write(&manifest_path, manifest("1.0").to_string()).expect("write manifest");
        fs::create_dir(directory.path().join("bin")).expect("create bin");
        fs::create_dir(directory.path().join("symbols")).expect("create symbols");
        fs::write(directory.path().join("bin/app.exe"), b"pe").expect("write PE");
        fs::write(directory.path().join("symbols/app.pdb"), b"pdb").expect("write PDB");
        let loaded = load_manifest(&manifest_path).expect("load manifest");
        let artifacts =
            required_artifacts(&loaded.manifest, directory.path()).expect("resolve unique files");
        assert_eq!(prepare_artifacts(artifacts).expect("prepare").len(), 2);

        fs::write(directory.path().join("app.exe"), b"duplicate").expect("write duplicate");
        assert!(required_artifacts(&loaded.manifest, directory.path())
            .expect_err("duplicate PE")
            .to_string()
            .contains("found 2"));
    }

    #[test]
    fn resolves_v2_source_bundle_as_a_required_artifact() {
        let directory = tempdir().expect("temporary directory");
        let manifest_path = directory.path().join("manifest-v2.json");
        let mut value = manifest("2.0");
        value["source_bundle"] = json!({
            "schema_version": "1.0",
            "archive": "source-bundle.zip",
            "source_root": "C:/agent/product"
        });
        fs::write(&manifest_path, value.to_string()).expect("write manifest");
        fs::write(directory.path().join("app.exe"), b"pe").expect("write PE");
        fs::write(directory.path().join("app.pdb"), b"pdb").expect("write PDB");
        fs::write(directory.path().join("source-bundle.zip"), b"zip").expect("write source");
        let loaded = load_manifest(&manifest_path).expect("load v2 manifest");
        let artifacts =
            required_artifacts(&loaded.manifest, directory.path()).expect("resolve v2 artifacts");
        assert_eq!(artifacts.len(), 3);
        assert_eq!(artifacts[2].kind.as_str(), "source_bundle");
    }

    #[test]
    fn streams_sha256() {
        let directory = tempdir().expect("temporary directory");
        let path = directory.path().join("payload.bin");
        fs::write(&path, b"abc").expect("write payload");
        assert_eq!(
            sha256_file(&path).expect("hash"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
