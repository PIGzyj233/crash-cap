mod cli;
mod error;
mod http;
mod manifest;
mod publisher;
mod redaction;
mod wire;

pub use cli::{Cli, Producer};
pub use error::{PublishError, Result};
pub use redaction::redact;
use serde_json::{Map, Value};

use crate::http::ApiClient;
use crate::manifest::{load_manifest, prepare_artifacts, required_artifacts};
use crate::publisher::Publisher;

pub fn run(cli: Cli) -> Result<Value> {
    let args = cli.resolve()?;
    let loaded = load_manifest(&args.manifest)?;
    let required = required_artifacts(&loaded.manifest, &args.artifact_root)?;
    let artifacts = prepare_artifacts(required)?;
    let api = ApiClient::new(&args.api_url)?;
    Publisher::new(&api).publish(&args, &loaded, &artifacts)
}

pub fn to_sorted_pretty_json(value: &Value) -> String {
    serde_json::to_string_pretty(&sort_json(value)).expect("JSON Value serialization cannot fail")
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
