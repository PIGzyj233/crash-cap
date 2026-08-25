mod cli;
mod config;
mod error;
mod http;
mod publisher;
mod redaction;
mod wire;

pub use cli::{Cli, Command, PublicationOrigin};
pub use error::{PublishError, Result};
pub use redaction::redact;

use serde_json::{json, Map, Value};

use crate::cli::detected_origin;
use crate::config::{
    initialize_config, load_repository_config, validate_profile, InitializeOptions,
};
use crate::http::ApiClient;
use crate::publisher::Publisher;

pub fn run(cli: Cli) -> Result<Value> {
    let progress = !cli.json;
    match cli.command.clone() {
        Command::Init {
            workspace,
            product,
            artifact_roots,
            profile,
            entrypoint,
            accept_discovered_roles,
            create_workspace,
            force,
        } => {
            let api = ApiClient::new(&cli.resolve_api_url()?)?;
            let publisher = Publisher::new(&api, progress);
            if progress {
                eprintln!("crashcap: resolving Workspace and scanning compiled outputs");
            }
            let resolved = publisher.resolve_workspace(&workspace, create_workspace)?;
            let product = product.unwrap_or_else(|| resolved.name.clone());
            let config = initialize_config(
                &cli.config,
                resolved.name.clone(),
                product,
                profile.clone(),
                artifact_roots,
                InitializeOptions {
                    entrypoint: entrypoint.as_deref(),
                    accept_discovered_roles,
                    force,
                },
            )?;
            let module_count =
                config.profiles.get(&profile).map(|item| item.modules.len()).unwrap_or_default();
            Ok(json!({
                "command": "init",
                "config": cli.config,
                "workspace_id": resolved.id,
                "workspace": resolved.name,
                "profile": profile,
                "module_count": module_count,
            }))
        }
        Command::Validate { profile } => {
            if progress {
                eprintln!("crashcap: validating config, paths, architecture, PE/PDB identity and Git state");
            }
            let prepared = validate_profile(&cli.config, &profile)?;
            Ok(json!({
                "command": "validate",
                "valid": true,
                "workspace": prepared.workspace,
                "profile": prepared.profile,
                "version": prepared.version,
                "git": prepared.git,
                "artifact_profile": "windows-x64-msvc-full-pdb-7.0",
                "artifacts": prepared.artifacts.iter().map(|item| json!({
                    "module_code_file": item.module_code_file,
                    "kind": item.kind.as_str(),
                    "logical_name": item.logical_name,
                    "size": item.size,
                    "sha256": item.sha256,
                })).collect::<Vec<_>>(),
            }))
        }
        Command::Doctor { workspace } => {
            let requested = match workspace {
                Some(value) => value,
                None => load_repository_config(&cli.config)?.workspace,
            };
            let api = ApiClient::new(&cli.resolve_api_url()?)?;
            Publisher::new(&api, progress).doctor(&requested)
        }
        Command::Publish { profile, origin, wait_seconds, receipt } => {
            if progress {
                eprintln!("crashcap: running complete offline preflight");
            }
            let prepared = validate_profile(&cli.config, &profile)?;
            let api = ApiClient::new(&cli.resolve_api_url()?)?;
            Publisher::new(&api, progress).publish(
                &prepared,
                detected_origin(origin),
                wait_seconds,
                &receipt,
            )
        }
    }
}

pub fn to_sorted_pretty_json(value: &Value) -> String {
    serde_json::to_string_pretty(&sort_json(value)).expect("JSON Value serialization cannot fail")
}

pub fn human_summary(value: &Value) -> String {
    if value.get("ready").and_then(Value::as_bool) == Some(true) {
        let mut summary = format!(
            "Publication {} is Ready; Build {} is sealed. Receipt written.",
            value.pointer("/publication/id").and_then(Value::as_str).unwrap_or("<unknown>"),
            value.get("build_id").and_then(Value::as_str).unwrap_or("<unknown>")
        );
        match value.pointer("/git/worktree_state").and_then(Value::as_str) {
            Some("dirty") => summary.push_str(" WARNING: Git worktree was dirty."),
            Some("unknown") => summary.push_str(" WARNING: Git worktree state was unknown."),
            _ => {}
        }
        return summary;
    }
    match value.get("command").and_then(Value::as_str) {
        Some("init") => format!(
            "Initialized {} for Workspace {} with {} module(s).",
            value.get("config").and_then(Value::as_str).unwrap_or("crashcap.toml"),
            value.get("workspace").and_then(Value::as_str).unwrap_or("<unknown>"),
            value.get("module_count").and_then(Value::as_u64).unwrap_or(0)
        ),
        Some("validate") => format!(
            "Profile {} is valid for version {} (Git {}).",
            value.get("profile").and_then(Value::as_str).unwrap_or("<unknown>"),
            value.get("version").and_then(Value::as_str).unwrap_or("<unknown>"),
            value.pointer("/git/worktree_state").and_then(Value::as_str).unwrap_or("unknown")
        ),
        _ if value.get("ok").and_then(Value::as_bool) == Some(true) => {
            "Doctor checks passed: API, Workspace, client contract and MSVC profile are compatible."
                .to_owned()
        }
        _ => to_sorted_pretty_json(value),
    }
}

fn sort_json(value: &Value) -> Value {
    match value {
        Value::Object(mapping) => {
            let mut keys = mapping.keys().collect::<Vec<_>>();
            keys.sort();
            let mut result = Map::new();
            for key in keys {
                result.insert(key.clone(), sort_json(&mapping[key]));
            }
            Value::Object(result)
        }
        Value::Array(items) => Value::Array(items.iter().map(sort_json).collect()),
        _ => value.clone(),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::to_sorted_pretty_json;

    #[test]
    fn recursively_sorts_success_json() {
        let output = to_sorted_pretty_json(&json!({"z": {"b": 1, "a": 2}, "a": 0}));
        assert!(output.find("\"a\": 0").expect("top a") < output.find("\"z\"").expect("z"));
        assert!(
            output.find("\"a\": 2").expect("nested a") < output.find("\"b\": 1").expect("nested b")
        );
    }
}
