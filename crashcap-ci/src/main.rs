use clap::Parser;
use crashcap::{human_summary, redact, run, to_sorted_pretty_json, Cli};
use serde_json::json;

fn main() {
    let cli = Cli::parse();
    let json_output = cli.json_output();
    match run(cli) {
        Ok(result) => {
            if json_output {
                println!("{}", to_sorted_pretty_json(&result));
            } else {
                println!("{}", human_summary(&result));
            }
            if result.get("failed").and_then(serde_json::Value::as_u64).unwrap_or(0) > 0 {
                std::process::exit(1);
            }
        }
        Err(error) => {
            let message = redact(&error.to_string());
            if json_output {
                eprintln!(
                    "{}",
                    to_sorted_pretty_json(&json!({
                        "error": {"code": "CLI_ERROR", "message": message}
                    }))
                );
            } else {
                eprintln!("crashcap: {message}");
            }
            std::process::exit(2);
        }
    }
}
