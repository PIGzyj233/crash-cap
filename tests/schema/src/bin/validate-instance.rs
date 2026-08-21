use jsonschema::validator_for;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::Path;

fn load(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    serde_json::from_str(&text)
        .map_err(|error| format!("cannot parse {} as JSON: {error}", path.display()))
}

fn main() {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args.len() < 2 {
        eprintln!("usage: validate-instance <schema.json> <instance.json> [...]");
        std::process::exit(2);
    }
    let schema_path = Path::new(&args[0]);
    let schema = load(schema_path).unwrap_or_else(|error| {
        eprintln!("{error}");
        std::process::exit(2);
    });
    let validator = validator_for(&schema).unwrap_or_else(|error| {
        eprintln!("schema {} is invalid: {error}", schema_path.display());
        std::process::exit(2);
    });
    let mut results = Vec::new();
    let mut failed = false;
    for value in &args[1..] {
        let path = Path::new(value);
        match load(path) {
            Ok(instance) => match validator.validate(&instance) {
                Ok(()) => results.push(json!({"instance": value, "status": "PASS"})),
                Err(error) => {
                    failed = true;
                    results.push(json!({
                        "instance": value,
                        "status": "FAIL",
                        "error": error.to_string()
                    }));
                }
            },
            Err(error) => {
                failed = true;
                results.push(json!({"instance": value, "status": "FAIL", "error": error}));
            }
        }
    }
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema": args[0],
            "status": if failed { "FAIL" } else { "PASS" },
            "instances": results
        }))
        .expect("validation result serializes")
    );
    if failed {
        std::process::exit(1);
    }
}
