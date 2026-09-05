use crate::error::{CliError, CliResult};
use crate::minidump::{inspect_bytes, InspectFailureKind, MAX_DUMP_BYTES};
use clap::{error::ErrorKind, Args, Parser, Subcommand};
use serde_json::Value;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

const EXIT_UNSUPPORTED: i32 = 2;
const EXIT_CORRUPT: i32 = 3;

#[derive(Debug, Parser)]
#[command(
    name = "dmp-core",
    version,
    about = "Crash-Cap Windows x64 minidump inspection and analysis core"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
#[allow(clippy::large_enum_variant)]
pub enum Command {
    /// Validate a dump and extract its stable metadata streams.
    Inspect(InspectArgs),
    /// Execute a system-generated immutable Run v3 as Canonical 2.0.
    AnalyzeFrozen(crate::frozen_cli::AnalyzeFrozenArgs),
    /// Extract authoritative PE/PDB identity from verified bytes.
    Identify(IdentifyArgs),
    /// Print the core version in a script-friendly form.
    Version,
}

#[derive(Debug, Args)]
pub struct IdentifyArgs {
    /// Artifact kind (`pe` or `pdb`).
    #[arg(long, value_parser = ["pe", "pdb"])]
    pub kind: String,
    /// Input PE or PDB path.
    #[arg(long, value_name = "PATH")]
    pub artifact: PathBuf,
    /// JSON output path, or `-` for stdout.
    #[arg(long, value_name = "PATH")]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct InspectArgs {
    /// Input Windows Minidump path.
    #[arg(long, value_name = "PATH")]
    pub dump: PathBuf,
    /// JSON output path, or `-` for stdout.
    #[arg(long, value_name = "PATH")]
    pub output: PathBuf,
}

pub fn parse_cli() -> CliResult<Cli> {
    match Cli::try_parse() {
        Ok(cli) => Ok(cli),
        Err(error)
            if matches!(error.kind(), ErrorKind::DisplayHelp | ErrorKind::DisplayVersion) =>
        {
            Err(CliError::new("CLI_OUTPUT", error.to_string(), 0))
        }
        Err(error) => {
            let rendered = error.render().to_string();
            Err(CliError::with_details(
                "INVALID_ARGUMENT",
                rendered.clone(),
                2,
                serde_json::json!({ "usage": rendered }),
            ))
        }
    }
}

pub fn run(cli: Cli) -> CliResult<()> {
    match cli.command {
        Command::Version => {
            println!("dmp-core {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        Command::Inspect(args) => run_inspect(args),
        Command::AnalyzeFrozen(args) => crate::frozen_cli::run(args),
        Command::Identify(args) => run_identify(args),
    }
}

fn run_identify(args: IdentifyArgs) -> CliResult<()> {
    let report = crate::artifact::identify_artifact(&args.artifact, &args.kind)
        .map_err(map_artifact_error)?;
    write_json(&args.output, &report)
}

fn map_artifact_error(error: crate::artifact::ArtifactError) -> CliError {
    match error {
        crate::artifact::ArtifactError::TooLarge { path, kind, size, limit } => {
            CliError::with_details(
                "ARTIFACT_TOO_LARGE",
                format!("{kind} artifact exceeds its size limit: {}", path.display()),
                1,
                serde_json::json!({
                    "path": path,
                    "kind": kind,
                    "size": size,
                    "limit": limit,
                }),
            )
        }
        crate::artifact::ArtifactError::UnsupportedKind(kind) => CliError::with_details(
            "UNSUPPORTED_ARTIFACT_KIND",
            format!("unsupported artifact kind: {kind}"),
            2,
            serde_json::json!({ "kind": kind }),
        ),
        other => CliError::new("ARTIFACT_IDENTIFY_FAILED", other.to_string(), 1),
    }
}

fn run_inspect(args: InspectArgs) -> CliResult<()> {
    let bytes = read_input(&args.dump)?;
    let report = inspect_bytes(&bytes).map_err(map_inspect_error)?;
    write_json(&args.output, &report)
}

fn read_input(path: &Path) -> CliResult<Vec<u8>> {
    let metadata = fs::metadata(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            CliError::input_not_found(path, error)
        } else {
            CliError::io(path, error)
        }
    })?;
    if metadata.len() > MAX_DUMP_BYTES as u64 {
        return Err(CliError::with_details(
            "INPUT_TOO_LARGE",
            format!("input exceeds the {MAX_DUMP_BYTES}-byte core limit"),
            2,
            serde_json::json!({ "path": path, "size": metadata.len(), "limit": MAX_DUMP_BYTES }),
        ));
    }
    fs::read(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            CliError::input_not_found(path, error)
        } else {
            CliError::io(path, error)
        }
    })
}

fn write_json<T: serde::Serialize>(path: &Path, value: &T) -> CliResult<()> {
    let encoded = serde_json::to_vec_pretty(value)
        .map_err(|error| CliError::new("SERIALIZATION_ERROR", error.to_string(), 1))?;
    if path == Path::new("-") {
        let mut stdout = io::stdout().lock();
        stdout
            .write_all(&encoded)
            .and_then(|_| stdout.write_all(b"\n"))
            .map_err(|error| CliError::new("IO_ERROR", error.to_string(), 1))?;
        return Ok(());
    }
    if let Some(parent) = path.parent().filter(|parent| !parent.as_os_str().is_empty()) {
        fs::create_dir_all(parent).map_err(|error| CliError::io(parent, error))?;
    }
    fs::write(path, encoded).map_err(|error| CliError::io(path, error))
}

fn map_inspect_error(error: crate::minidump::InspectFailure) -> CliError {
    match error.kind {
        InspectFailureKind::Unsupported => CliError::with_details(
            "UNSUPPORTED_DUMP",
            error.message,
            EXIT_UNSUPPORTED,
            Value::Object(Default::default()),
        ),
        InspectFailureKind::Corrupt => CliError::with_details(
            "CORRUPT_DUMP",
            error.message,
            EXIT_CORRUPT,
            Value::Object(Default::default()),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    #[test]
    fn inspect_arguments_match_documented_shape() {
        let cli = Cli::try_parse_from([
            "dmp-core",
            "inspect",
            "--dump",
            "input.dmp",
            "--output",
            "inspect.json",
        ])
        .expect("inspect arguments parse");
        assert!(matches!(cli.command, Command::Inspect(_)));
    }

    #[test]
    fn identify_arguments_match_documented_shape() {
        let cli = Cli::try_parse_from([
            "dmp-core",
            "identify",
            "--kind",
            "pe",
            "--artifact",
            "app.exe",
            "--output",
            "identity.json",
        ])
        .expect("identify arguments parse");
        assert!(matches!(cli.command, Command::Identify(_)));
    }

    #[test]
    fn unsupported_and_corrupt_codes_are_design_codes() {
        assert_eq!(EXIT_UNSUPPORTED, 2);
        assert_eq!(EXIT_CORRUPT, 3);
    }
}
