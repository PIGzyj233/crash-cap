use dmp_core::cli::{parse_cli, run};

fn main() {
    let cli = match parse_cli() {
        Ok(cli) => cli,
        Err(error) => {
            if error.exit_code == 0 {
                print!("{}", error.message);
            } else {
                eprintln!("{}", error.to_json_line());
            }
            std::process::exit(error.exit_code);
        }
    };

    if let Err(error) = run(cli) {
        eprintln!("{}", error.to_json_line());
        std::process::exit(error.exit_code);
    }
}
