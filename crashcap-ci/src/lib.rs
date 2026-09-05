mod cli;
mod error;
mod http;
mod publisher;
mod redaction;
mod wire;
use crate::{cli::resolve_api_url, http::ApiClient, publisher::Uploader};
pub use cli::{Cli, Command};
pub use error::{PublishError, Result};
pub use redaction::redact;
use serde_json::{Map, Value};

pub fn run(cli: Cli) -> Result<Value> {
    match cli.command {
        Command::Upload { paths, workspace, public, build_version, api_url, json, receipt } => {
            let api = ApiClient::new(&resolve_api_url(api_url)?)?;
            Uploader::new(&api, !json).upload(paths, workspace, public, build_version, &receipt)
        }
    }
}
pub fn to_sorted_pretty_json(value: &Value) -> String {
    serde_json::to_string_pretty(&sort_json(value)).expect("JSON serialization")
}
pub fn human_summary(value: &Value) -> String {
    format!(
        "Uploaded {} of {} file(s); {} failed. Receipt: {}",
        value.get("succeeded").and_then(Value::as_u64).unwrap_or(0),
        value.get("total").and_then(Value::as_u64).unwrap_or(0),
        value.get("failed").and_then(Value::as_u64).unwrap_or(0),
        value.get("receipt").and_then(Value::as_str).unwrap_or("crashcap-upload.json")
    )
}
fn sort_json(value: &Value) -> Value {
    match value {
        Value::Object(m) => {
            let mut keys = m.keys().collect::<Vec<_>>();
            keys.sort();
            let mut out = Map::new();
            for key in keys {
                out.insert(key.clone(), sort_json(&m[key]));
            }
            Value::Object(out)
        }
        Value::Array(a) => Value::Array(a.iter().map(sort_json).collect()),
        _ => value.clone(),
    }
}
