use std::collections::{BTreeMap, HashMap};
use std::env;
use std::ffi::OsStr;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::Command;

use crashcap_artifact_identity::identify_artifact;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use walkdir::WalkDir;

use crate::error::{PublishError, Result};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RepositoryConfig {
    pub schema_version: u32,
    pub workspace: String,
    pub product: String,
    pub profiles: BTreeMap<String, ProfileConfig>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileConfig {
    pub artifact_roots: Vec<PathBuf>,
    pub version: VersionSource,
    pub channel: String,
    #[serde(default)]
    pub require_clean: bool,
    pub modules: Vec<ModuleConfig>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VersionSource {
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<PathBuf>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModuleConfig {
    pub code: PathBuf,
    pub debug: PathBuf,
    pub role: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UserConfig {
    api_url: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct GitState {
    pub revision: Option<String>,
    pub worktree_state: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactKind {
    Pe,
    Pdb,
}

impl ArtifactKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pe => "pe",
            Self::Pdb => "pdb",
        }
    }
}

#[derive(Clone, Debug)]
pub struct PreparedArtifact {
    pub module_code_file: String,
    pub kind: ArtifactKind,
    pub logical_name: String,
    pub path: PathBuf,
    pub size: u64,
    pub sha256: String,
}

#[derive(Clone, Debug)]
pub struct PreparedProfile {
    pub workspace: String,
    pub profile: String,
    pub version: String,
    pub manifest: Value,
    pub artifacts: Vec<PreparedArtifact>,
    pub git: GitState,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct InitializeOptions<'a> {
    pub entrypoint: Option<&'a str>,
    pub accept_discovered_roles: bool,
    pub force: bool,
}

pub fn load_repository_config(path: &Path) -> Result<RepositoryConfig> {
    let source = fs::read_to_string(path)
        .map_err(|error| PublishError::message(format!("cannot read crashcap.toml: {error}")))?;
    let config: RepositoryConfig = toml::from_str(&source)
        .map_err(|error| PublishError::message(format!("invalid crashcap.toml: {error}")))?;
    if config.schema_version != 1 {
        return Err(PublishError::message("crashcap.toml schema_version must be 1"));
    }
    if config.workspace.trim().is_empty() || config.product.trim().is_empty() {
        return Err(PublishError::message("workspace and product must not be empty"));
    }
    if config.profiles.is_empty() {
        return Err(PublishError::message("crashcap.toml must declare at least one profile"));
    }
    Ok(config)
}

pub fn user_api_url() -> Result<Option<String>> {
    let path = if let Some(explicit) = env::var_os("CRASHCAP_USER_CONFIG") {
        Some(PathBuf::from(explicit))
    } else if let Some(appdata) = env::var_os("APPDATA") {
        Some(PathBuf::from(appdata).join("Crash-Cap").join("config.toml"))
    } else if let Some(xdg) = env::var_os("XDG_CONFIG_HOME") {
        Some(PathBuf::from(xdg).join("crash-cap").join("config.toml"))
    } else {
        env::var_os("HOME")
            .map(PathBuf::from)
            .map(|home| home.join(".config").join("crash-cap").join("config.toml"))
    };
    let Some(path) = path else { return Ok(None) };
    if !path.exists() {
        return Ok(None);
    }
    let source = fs::read_to_string(&path).map_err(|error| {
        PublishError::message(format!(
            "cannot read user Crash-Cap config {}: {error}",
            path.display()
        ))
    })?;
    let config: UserConfig = toml::from_str(&source).map_err(|error| {
        PublishError::message(format!("invalid user Crash-Cap config {}: {error}", path.display()))
    })?;
    Ok(config.api_url.filter(|value| !value.trim().is_empty()))
}

pub fn validate_profile(config_path: &Path, profile_name: &str) -> Result<PreparedProfile> {
    let config = load_repository_config(config_path)?;
    let profile = config.profiles.get(profile_name).ok_or_else(|| {
        PublishError::message(format!("profile {profile_name:?} is absent from crashcap.toml"))
    })?;
    if profile.artifact_roots.is_empty() || profile.modules.is_empty() {
        return Err(PublishError::message("profile must declare artifact_roots and exact modules"));
    }
    if !profile.modules.iter().any(|module| module.role == "entrypoint") {
        return Err(PublishError::message("profile must declare at least one entrypoint module"));
    }
    for module in &profile.modules {
        if !matches!(module.role.as_str(), "entrypoint" | "owned" | "dependency") {
            return Err(PublishError::message(format!(
                "module {} has invalid role {}",
                module.code.display(),
                module.role
            )));
        }
    }

    let config_absolute = fs::canonicalize(config_path)
        .map_err(|error| PublishError::message(format!("cannot resolve crashcap.toml: {error}")))?;
    let repository_root = config_absolute
        .parent()
        .ok_or_else(|| PublishError::message("crashcap.toml has no repository directory"))?;
    let roots = resolve_roots(repository_root, &profile.artifact_roots)?;
    let git = git_state(repository_root);
    if profile.require_clean && git.worktree_state != "clean" {
        return Err(PublishError::message(format!(
            "profile requires a clean Git worktree; observed {}",
            git.worktree_state
        )));
    }
    let version = resolve_version(repository_root, &profile.version)?;

    let mut artifacts = Vec::with_capacity(profile.modules.len() * 2);
    let mut manifest_modules = Vec::with_capacity(profile.modules.len());
    let mut logical_names: HashMap<String, PathBuf> = HashMap::new();
    for module in &profile.modules {
        let code_path = resolve_exact_artifact(&roots, &module.code)?;
        let debug_path = resolve_exact_artifact(&roots, &module.debug)?;
        let code_name = utf8_basename(&code_path)?;
        let debug_name = utf8_basename(&debug_path)?;
        if !matches!(extension(&code_name).as_deref(), Some("exe" | "dll")) {
            return Err(PublishError::message(format!(
                "module code file must be EXE or DLL: {}",
                module.code.display()
            )));
        }
        if extension(&debug_name).as_deref() != Some("pdb") {
            return Err(PublishError::message(format!(
                "module debug file must be PDB: {}",
                module.debug.display()
            )));
        }
        for (name, path) in [(&code_name, &code_path), (&debug_name, &debug_path)] {
            if let Some(other) = logical_names.insert(name.to_lowercase(), path.clone()) {
                return Err(PublishError::message(format!(
                    "duplicate artifact basename {name} resolves to {} and {}",
                    other.display(),
                    path.display()
                )));
            }
        }

        let pe = identify_artifact(&code_path, "pe").map_err(|error| {
            PublishError::message(format!(
                "PE validation failed for {}: {error}",
                code_path.display()
            ))
        })?;
        let pdb = identify_artifact(&debug_path, "pdb").map_err(|error| {
            PublishError::message(format!(
                "PDB validation failed for {}: {error}",
                debug_path.display()
            ))
        })?;
        if pdb.is_fastlink {
            return Err(PublishError::message(format!(
                "FASTLINK PDB is unsupported; produce a full PDB 7.0: {}",
                debug_path.display()
            )));
        }
        let pe_debug_id = pe.debug_id.as_deref().ok_or_else(|| {
            PublishError::message(format!(
                "PE has no RSDS debug identity and cannot be paired: {}",
                code_path.display()
            ))
        })?;
        let pdb_debug_id = pdb.debug_id.as_deref().ok_or_else(|| {
            PublishError::message(format!("PDB has no debug identity: {}", debug_path.display()))
        })?;
        if !pe_debug_id.eq_ignore_ascii_case(pdb_debug_id) {
            return Err(PublishError::message(format!(
                "PE/PDB identity mismatch for {code_name} and {debug_name}"
            )));
        }
        if let Some(embedded) = pe.debug_file.as_deref().and_then(windows_basename) {
            if !embedded.eq_ignore_ascii_case(&debug_name) {
                return Err(PublishError::message(format!(
                    "PE names PDB {} but the profile declares {debug_name}",
                    embedded
                )));
            }
        }
        manifest_modules.push(json!({
            "code_file": code_name,
            "debug_file": debug_name,
            "role": module.role,
        }));
        artifacts.push(PreparedArtifact {
            module_code_file: code_name.clone(),
            kind: ArtifactKind::Pe,
            logical_name: code_name,
            path: code_path,
            size: pe.size,
            sha256: pe.sha256,
        });
        artifacts.push(PreparedArtifact {
            module_code_file: artifacts.last().expect("PE was appended").module_code_file.clone(),
            kind: ArtifactKind::Pdb,
            logical_name: debug_name,
            path: debug_path,
            size: pdb.size,
            sha256: pdb.sha256,
        });
    }
    artifacts.sort_by(|left, right| {
        left.logical_name
            .to_lowercase()
            .cmp(&right.logical_name.to_lowercase())
            .then_with(|| left.kind.as_str().cmp(right.kind.as_str()))
    });
    manifest_modules.sort_by(|left, right| {
        left["code_file"]
            .as_str()
            .unwrap_or_default()
            .to_lowercase()
            .cmp(&right["code_file"].as_str().unwrap_or_default().to_lowercase())
    });
    let mut manifest = json!({
        "schema_version": "1.0",
        "product": config.product,
        "version": version,
        "channel": profile.channel,
        "architecture": "x86_64",
        "compiler": "msvc",
        "toolchain": "msvc",
        "modules": manifest_modules,
    });
    if let Some(revision) = &git.revision {
        manifest["commit"] = json!(revision);
    }
    Ok(PreparedProfile {
        workspace: config.workspace,
        profile: profile_name.to_owned(),
        version,
        manifest,
        artifacts,
        git,
    })
}

pub fn initialize_config(
    config_path: &Path,
    workspace: String,
    product: String,
    profile: String,
    artifact_roots: Vec<PathBuf>,
    options: InitializeOptions<'_>,
) -> Result<RepositoryConfig> {
    if config_path.exists() && !options.force {
        return Err(PublishError::message(format!(
            "{} already exists; use --force to replace it",
            config_path.display()
        )));
    }
    let config_parent = config_path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let root = fs::canonicalize(config_parent).map_err(|error| {
        PublishError::message(format!("cannot resolve config directory: {error}"))
    })?;
    let modules =
        scan_modules(&root, &artifact_roots, options.entrypoint, options.accept_discovered_roles)?;
    let mut profiles = BTreeMap::new();
    profiles.insert(
        profile,
        ProfileConfig {
            artifact_roots,
            version: VersionSource {
                source: "git-describe".to_owned(),
                value: None,
                name: None,
                path: None,
            },
            channel: "local".to_owned(),
            require_clean: false,
            modules,
        },
    );
    let config = RepositoryConfig { schema_version: 1, workspace, product, profiles };
    let encoded = toml::to_string_pretty(&config)
        .map_err(|error| PublishError::message(format!("cannot encode crashcap.toml: {error}")))?;
    fs::write(config_path, encoded)
        .map_err(|error| PublishError::message(format!("cannot write crashcap.toml: {error}")))?;
    Ok(config)
}

fn resolve_roots(repository_root: &Path, configured: &[PathBuf]) -> Result<Vec<PathBuf>> {
    configured
        .iter()
        .map(|relative| {
            validate_relative_path(relative, "artifact root")?;
            reject_symlink_components(repository_root, relative)?;
            let path = fs::canonicalize(repository_root.join(relative)).map_err(|error| {
                PublishError::message(format!(
                    "cannot resolve artifact root {}: {error}",
                    relative.display()
                ))
            })?;
            if !path.starts_with(repository_root) || !path.is_dir() {
                return Err(PublishError::message(format!(
                    "artifact root escapes the repository or is not a directory: {}",
                    relative.display()
                )));
            }
            Ok(path)
        })
        .collect()
}

fn resolve_exact_artifact(roots: &[PathBuf], relative: &Path) -> Result<PathBuf> {
    validate_relative_path(relative, "module artifact")?;
    let mut matches = Vec::new();
    for root in roots {
        let candidate = root.join(relative);
        if candidate.exists() {
            reject_symlink_components(root, relative)?;
            let resolved = fs::canonicalize(&candidate).map_err(|error| {
                PublishError::message(format!("cannot resolve {}: {error}", candidate.display()))
            })?;
            if !resolved.starts_with(root) || !resolved.is_file() {
                return Err(PublishError::message(format!(
                    "artifact escapes its root or is not a regular file: {}",
                    candidate.display()
                )));
            }
            matches.push(resolved);
        }
    }
    if matches.len() != 1 {
        return Err(PublishError::message(format!(
            "exact artifact path {} must resolve in one artifact_root; found {}",
            relative.display(),
            matches.len()
        )));
    }
    Ok(matches.remove(0))
}

fn validate_relative_path(path: &Path, label: &str) -> Result<()> {
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path.components().any(|component| {
            matches!(component, Component::ParentDir | Component::RootDir | Component::Prefix(_))
        })
    {
        return Err(PublishError::message(format!(
            "{label} must be a safe repository-relative path: {}",
            path.display()
        )));
    }
    Ok(())
}

fn reject_symlink_components(root: &Path, relative: &Path) -> Result<()> {
    let mut current = root.to_path_buf();
    for component in relative.components() {
        if let Component::Normal(value) = component {
            current.push(value);
            if current.exists()
                && fs::symlink_metadata(&current)
                    .map_err(|error| {
                        PublishError::message(format!(
                            "cannot inspect {}: {error}",
                            current.display()
                        ))
                    })?
                    .file_type()
                    .is_symlink()
            {
                return Err(PublishError::message(format!(
                    "symbolic links are not accepted in artifact paths: {}",
                    current.display()
                )));
            }
        }
    }
    Ok(())
}

fn resolve_version(repository_root: &Path, source: &VersionSource) -> Result<String> {
    let value = match source.source.as_str() {
        "literal" => source
            .value
            .clone()
            .ok_or_else(|| PublishError::message("literal version source requires value"))?,
        "env" => {
            let name = source
                .name
                .as_deref()
                .ok_or_else(|| PublishError::message("env version source requires name"))?;
            env::var(name).map_err(|_| {
                PublishError::message(format!("version environment variable {name} is not set"))
            })?
        }
        "file" => {
            let path = source
                .path
                .as_deref()
                .ok_or_else(|| PublishError::message("file version source requires path"))?;
            validate_relative_path(path, "version file")?;
            reject_symlink_components(repository_root, path)?;
            fs::read_to_string(repository_root.join(path)).map_err(|error| {
                PublishError::message(format!(
                    "cannot read version file {}: {error}",
                    path.display()
                ))
            })?
        }
        "git-describe" => {
            command_output(repository_root, "git", &["describe", "--tags", "--always"])?
        }
        other => {
            return Err(PublishError::message(format!(
                "unsupported version source {other:?}; use literal, env, file, or git-describe"
            )))
        }
    };
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.len() > 200 || trimmed.contains(['\r', '\n', '\0']) {
        return Err(PublishError::message(
            "resolved version must be one non-empty line up to 200 bytes",
        ));
    }
    Ok(trimmed.to_owned())
}

fn git_state(repository_root: &Path) -> GitState {
    let revision = command_output(repository_root, "git", &["rev-parse", "HEAD"])
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| {
            !value.is_empty() && value.chars().all(|character| character.is_ascii_hexdigit())
        });
    let worktree = command_output(
        repository_root,
        "git",
        &["status", "--porcelain", "--untracked-files=normal"],
    );
    let worktree_state = match (revision.as_ref(), worktree) {
        (Some(_), Ok(value)) if value.trim().is_empty() => "clean",
        (Some(_), Ok(_)) => "dirty",
        _ => "unknown",
    };
    GitState { revision, worktree_state: worktree_state.to_owned() }
}

fn command_output(directory: &Path, program: &str, arguments: &[&str]) -> Result<String> {
    let output = Command::new(program)
        .args(arguments)
        .current_dir(directory)
        .output()
        .map_err(|error| PublishError::message(format!("cannot execute {program}: {error}")))?;
    if !output.status.success() {
        return Err(PublishError::message(format!(
            "{program} {} failed with status {}",
            arguments.join(" "),
            output.status
        )));
    }
    String::from_utf8(output.stdout)
        .map_err(|_| PublishError::message(format!("{program} output is not UTF-8")))
}

fn scan_modules(
    repository_root: &Path,
    artifact_roots: &[PathBuf],
    entrypoint: Option<&str>,
    accept_discovered_roles: bool,
) -> Result<Vec<ModuleConfig>> {
    let roots = resolve_roots(repository_root, artifact_roots)?;
    let mut code_files: HashMap<String, Vec<(usize, PathBuf)>> = HashMap::new();
    let mut pdb_files: HashMap<String, Vec<(usize, PathBuf)>> = HashMap::new();
    for (root_index, root) in roots.iter().enumerate() {
        for entry in WalkDir::new(root).follow_links(false) {
            let entry = entry.map_err(|error| {
                PublishError::message(format!("cannot scan artifact root: {error}"))
            })?;
            if entry.file_type().is_symlink() {
                return Err(PublishError::message(format!(
                    "symbolic links are not accepted while scanning: {}",
                    entry.path().display()
                )));
            }
            if !entry.file_type().is_file() {
                continue;
            }
            let Some(stem) = entry.path().file_stem().and_then(OsStr::to_str) else { continue };
            let ext = entry.path().extension().and_then(OsStr::to_str).map(str::to_ascii_lowercase);
            let relative = entry
                .path()
                .strip_prefix(root)
                .expect("WalkDir entry remains under root")
                .to_path_buf();
            match ext.as_deref() {
                Some("exe" | "dll") => {
                    code_files.entry(stem.to_lowercase()).or_default().push((root_index, relative));
                }
                Some("pdb") => {
                    pdb_files.entry(stem.to_lowercase()).or_default().push((root_index, relative));
                }
                _ => {}
            }
        }
    }
    let mut pairs = Vec::new();
    for (stem, codes) in code_files {
        let pdbs = pdb_files.get(&stem).map(Vec::as_slice).unwrap_or_default();
        if codes.len() != 1 || pdbs.len() != 1 {
            return Err(PublishError::message(format!(
                "module stem {stem:?} must resolve to one code file and one PDB; found {} and {}",
                codes.len(),
                pdbs.len()
            )));
        }
        pairs.push((codes[0].1.clone(), pdbs[0].1.clone()));
    }
    if pairs.is_empty() {
        return Err(PublishError::message("no EXE/DLL plus PDB module pairs were found"));
    }
    pairs.sort_by_key(|(code, _)| code.to_string_lossy().to_lowercase());
    let executables = pairs
        .iter()
        .filter(|(code, _)| extension(&code.to_string_lossy()).as_deref() == Some("exe"))
        .collect::<Vec<_>>();
    let selected_entrypoint = match entrypoint {
        Some(requested) => {
            let matches = executables
                .iter()
                .filter(|(code, _)| {
                    code.file_name()
                        .and_then(OsStr::to_str)
                        .is_some_and(|name| name.eq_ignore_ascii_case(requested))
                        || code.to_string_lossy().eq_ignore_ascii_case(requested)
                })
                .collect::<Vec<_>>();
            if matches.len() != 1 {
                return Err(PublishError::message(format!(
                    "--entrypoint {requested:?} must select exactly one EXE; found {}",
                    matches.len()
                )));
            }
            matches[0].0.clone()
        }
        None if executables.len() == 1 => executables[0].0.clone(),
        None => {
            let candidates = executables
                .iter()
                .map(|(code, _)| code.display().to_string())
                .collect::<Vec<_>>()
                .join(", ");
            return Err(PublishError::message(format!(
                "entrypoint is ambiguous; choose one with --entrypoint ({candidates})"
            )));
        }
    };
    if pairs.len() > 1 && !accept_discovered_roles {
        let discovered = pairs
            .iter()
            .map(|(code, _)| {
                let role = if *code == selected_entrypoint { "entrypoint" } else { "owned" };
                format!("{}={role}", code.display())
            })
            .collect::<Vec<_>>()
            .join(", ");
        return Err(PublishError::message(format!(
            "discovered module roles require confirmation ({discovered}); review them and rerun with --accept-discovered-roles, then edit dependency roles in crashcap.toml"
        )));
    }
    Ok(pairs
        .into_iter()
        .map(|(code, debug)| ModuleConfig {
            role: if code == selected_entrypoint { "entrypoint" } else { "owned" }.to_owned(),
            code,
            debug,
        })
        .collect())
}

fn utf8_basename(path: &Path) -> Result<String> {
    path.file_name()
        .and_then(OsStr::to_str)
        .map(str::to_owned)
        .ok_or_else(|| PublishError::message("artifact basename is not valid UTF-8"))
}

fn extension(value: &str) -> Option<String> {
    Path::new(value).extension().and_then(OsStr::to_str).map(str::to_ascii_lowercase)
}

fn windows_basename(value: &str) -> Option<&str> {
    value.rsplit(['/', '\\']).find(|part| !part.is_empty())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs;
    use std::path::{Path, PathBuf};

    use tempfile::tempdir;

    use super::{
        initialize_config, validate_profile, InitializeOptions, ModuleConfig, ProfileConfig,
        RepositoryConfig, VersionSource,
    };

    fn fixture(name: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("fixtures")
            .join(".build")
            .join("golden")
            .join(name)
    }

    fn link_or_copy(source: &Path, target: &Path) {
        if fs::hard_link(source, target).is_err() {
            fs::copy(source, target).expect("copy fixture");
        }
    }

    fn write_config(root: &Path, require_clean: bool, code: &str, debug: &str) -> PathBuf {
        let mut profiles = BTreeMap::new();
        profiles.insert(
            "release".to_owned(),
            ProfileConfig {
                artifact_roots: vec![PathBuf::from("out")],
                version: VersionSource {
                    source: "literal".to_owned(),
                    value: Some("1.2.3".to_owned()),
                    name: None,
                    path: None,
                },
                channel: "local".to_owned(),
                require_clean,
                modules: vec![ModuleConfig {
                    code: PathBuf::from(code),
                    debug: PathBuf::from(debug),
                    role: "entrypoint".to_owned(),
                }],
            },
        );
        let config = RepositoryConfig {
            schema_version: 1,
            workspace: "demo".to_owned(),
            product: "Demo".to_owned(),
            profiles,
        };
        let path = root.join("crashcap.toml");
        fs::write(&path, toml::to_string_pretty(&config).expect("encode config"))
            .expect("write config");
        path
    }

    #[test]
    fn validates_real_x64_msvc_pair_with_shared_identity_parser() {
        let directory = tempdir().expect("tempdir");
        let output = directory.path().join("out");
        fs::create_dir(&output).expect("output directory");
        link_or_copy(&fixture("golden_target_debug.exe"), &output.join("golden_target_debug.exe"));
        link_or_copy(&fixture("golden_target_debug.pdb"), &output.join("golden_target_debug.pdb"));
        let config = write_config(
            directory.path(),
            false,
            "golden_target_debug.exe",
            "golden_target_debug.pdb",
        );
        let prepared = validate_profile(&config, "release").expect("valid profile");
        assert_eq!(prepared.artifacts.len(), 2);
        assert_eq!(prepared.version, "1.2.3");
        assert_eq!(prepared.manifest["architecture"], "x86_64");
        assert_eq!(prepared.manifest["compiler"], "msvc");
    }

    #[test]
    fn rejects_x86_and_mismatched_pdb_before_network_access() {
        let x86_directory = tempdir().expect("tempdir");
        let x86_output = x86_directory.path().join("out");
        fs::create_dir(&x86_output).expect("output directory");
        link_or_copy(&fixture("golden_target_x86.exe"), &x86_output.join("golden_target_x86.exe"));
        link_or_copy(&fixture("golden_target_x86.pdb"), &x86_output.join("golden_target_x86.pdb"));
        let x86_config = write_config(
            x86_directory.path(),
            false,
            "golden_target_x86.exe",
            "golden_target_x86.pdb",
        );
        assert!(validate_profile(&x86_config, "release")
            .expect_err("x86 rejected")
            .to_string()
            .contains("unsupported PE machine"));

        let mismatch_directory = tempdir().expect("tempdir");
        let mismatch_output = mismatch_directory.path().join("out");
        fs::create_dir(&mismatch_output).expect("output directory");
        link_or_copy(
            &fixture("golden_target_release.exe"),
            &mismatch_output.join("golden_target_release.exe"),
        );
        link_or_copy(
            &fixture("golden_target_debug.pdb"),
            &mismatch_output.join("golden_target_release.pdb"),
        );
        let mismatch_config = write_config(
            mismatch_directory.path(),
            false,
            "golden_target_release.exe",
            "golden_target_release.pdb",
        );
        assert!(validate_profile(&mismatch_config, "release")
            .expect_err("mismatch rejected")
            .to_string()
            .contains("identity mismatch"));
    }

    #[test]
    fn init_requires_explicit_entrypoint_when_multiple_exes_exist() {
        let directory = tempdir().expect("tempdir");
        let output = directory.path().join("out");
        fs::create_dir(&output).expect("output directory");
        for name in ["first", "second"] {
            fs::write(output.join(format!("{name}.exe")), b"candidate").expect("code");
            fs::write(output.join(format!("{name}.pdb")), b"candidate").expect("pdb");
        }
        let config_path = directory.path().join("crashcap.toml");
        assert!(initialize_config(
            &config_path,
            "demo".to_owned(),
            "Demo".to_owned(),
            "release".to_owned(),
            vec![PathBuf::from("out")],
            InitializeOptions::default(),
        )
        .expect_err("ambiguous entrypoint")
        .to_string()
        .contains("--entrypoint"));
        assert!(initialize_config(
            &config_path,
            "demo".to_owned(),
            "Demo".to_owned(),
            "release".to_owned(),
            vec![PathBuf::from("out")],
            InitializeOptions { entrypoint: Some("first.exe"), ..InitializeOptions::default() },
        )
        .expect_err("module roles require confirmation")
        .to_string()
        .contains("--accept-discovered-roles"));
        let config = initialize_config(
            &config_path,
            "demo".to_owned(),
            "Demo".to_owned(),
            "release".to_owned(),
            vec![PathBuf::from("out")],
            InitializeOptions {
                entrypoint: Some("first.exe"),
                accept_discovered_roles: true,
                force: false,
            },
        )
        .expect("explicit entrypoint");
        let roles = &config.profiles["release"].modules;
        assert_eq!(roles.iter().filter(|item| item.role == "entrypoint").count(), 1);
    }

    #[test]
    fn require_clean_rejects_unknown_non_git_worktree() {
        let directory = tempdir().expect("tempdir");
        let output = directory.path().join("out");
        fs::create_dir(&output).expect("output directory");
        link_or_copy(&fixture("golden_target_debug.exe"), &output.join("golden_target_debug.exe"));
        link_or_copy(&fixture("golden_target_debug.pdb"), &output.join("golden_target_debug.pdb"));
        let config = write_config(
            directory.path(),
            true,
            "golden_target_debug.exe",
            "golden_target_debug.pdb",
        );
        assert!(validate_profile(&config, "release")
            .expect_err("unknown worktree rejected")
            .to_string()
            .contains("requires a clean Git worktree"));
    }
}
