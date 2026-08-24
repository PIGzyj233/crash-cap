use clap::Parser;
use crashcap_ci::{redact, run, Cli};

fn main() {
    let cli = Cli::parse();
    match run(cli) {
        Ok(result) => {
            println!("{}", crashcap_ci::to_sorted_pretty_json(&result));
        }
        Err(error) => {
            eprintln!("crashcap-ci: {}", redact(&error.to_string()));
            std::process::exit(2);
        }
    }
}
