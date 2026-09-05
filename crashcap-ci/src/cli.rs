use crate::error::{PublishError, Result};
use clap::{ArgGroup, Parser, Subcommand};
use std::{env, path::PathBuf};

#[derive(Clone, Debug, Parser)]
#[command(name = "crashcap", version, about = "Upload crash dumps, executables and symbols")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Clone, Debug, Subcommand)]
pub enum Command {
    /// Recursively upload .exe, .dll, .pdb and .dmp files.
    #[command(group(ArgGroup::new("scope").required(true).multiple(false).args(["workspace", "public"])))]
    Upload {
        #[arg(required = true)]
        paths: Vec<PathBuf>,
        #[arg(long, help = "Workspace ID or exact name")]
        workspace: Option<String>,
        #[arg(long, help = "Upload shared symbols (DMP files are rejected)")]
        public: bool,
        #[arg(long, value_name = "LABEL")]
        build_version: Option<String>,
        #[arg(long)]
        api_url: Option<String>,
        #[arg(long)]
        json: bool,
        #[arg(long, default_value = "crashcap-upload.json")]
        receipt: PathBuf,
    },
}

pub fn resolve_api_url(explicit: Option<String>) -> Result<String> {
    explicit
        .filter(|v| !v.trim().is_empty())
        .or_else(|| env::var("CRASHCAP_API_URL").ok().filter(|v| !v.trim().is_empty()))
        .map(|v| {
            let v = v.trim_end_matches('/');
            if v.ends_with("/api/v3") {
                v.to_owned()
            } else {
                format!("{v}/api/v3")
            }
        })
        .ok_or_else(|| {
            PublishError::message("API URL is required: use --api-url or CRASHCAP_API_URL")
        })
}

impl Cli {
    pub fn json_output(&self) -> bool {
        matches!(&self.command, Command::Upload { json: true, .. })
    }
}

#[cfg(test)]
mod tests {
    use super::{Cli, Command};
    use clap::Parser;
    #[test]
    fn upload_requires_exactly_one_scope() {
        assert!(Cli::try_parse_from(["crashcap", "upload", "a.pdb", "--workspace", "Demo"]).is_ok());
        assert!(Cli::try_parse_from(["crashcap", "upload", "a.pdb", "--public"]).is_ok());
        assert!(Cli::try_parse_from(["crashcap", "upload", "a.pdb"]).is_err());
        assert!(Cli::try_parse_from([
            "crashcap",
            "upload",
            "a.pdb",
            "--public",
            "--workspace",
            "Demo"
        ])
        .is_err());
    }
    #[test]
    fn accepts_multiple_inputs_and_local_options() {
        let parsed = Cli::try_parse_from([
            "crashcap",
            "upload",
            "bin",
            "dump.dmp",
            "--workspace",
            "wsp_1",
            "--build-version",
            "2.4",
            "--json",
        ])
        .unwrap();
        let Command::Upload { paths, build_version, json, .. } = parsed.command;
        assert_eq!(paths.len(), 2);
        assert_eq!(build_version.as_deref(), Some("2.4"));
        assert!(json);
    }
}
