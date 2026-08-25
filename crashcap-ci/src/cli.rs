use std::env;
use std::path::PathBuf;

use clap::{Parser, Subcommand, ValueEnum};

use crate::config::user_api_url;
use crate::error::{PublishError, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum PublicationOrigin {
    Local,
    Ci,
}

impl PublicationOrigin {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Ci => "ci",
        }
    }
}

#[derive(Clone, Debug, Parser)]
#[command(
    name = "crashcap",
    version,
    about = "Validate and publish local or CI MSVC crash-analysis artifacts"
)]
pub struct Cli {
    #[arg(long, global = true)]
    pub api_url: Option<String>,

    #[arg(long, global = true)]
    pub json: bool,

    #[arg(long, global = true, default_value = "crashcap.toml")]
    pub config: PathBuf,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Clone, Debug, Subcommand)]
pub enum Command {
    /// Scan compiled outputs and create a repository-safe crashcap.toml.
    Init {
        #[arg(long, help = "Existing Workspace id/name, or name to create explicitly")]
        workspace: String,

        #[arg(long)]
        product: Option<String>,

        #[arg(long = "artifact-root", required = true)]
        artifact_roots: Vec<PathBuf>,

        #[arg(long, default_value = "release")]
        profile: String,

        #[arg(long, help = "EXE basename/path to use when entrypoint discovery is ambiguous")]
        entrypoint: Option<String>,

        #[arg(
            long,
            help = "Confirm that every discovered non-entrypoint module should initially be owned"
        )]
        accept_discovered_roles: bool,

        #[arg(long, help = "Explicitly allow creation when the Workspace does not exist")]
        create_workspace: bool,

        #[arg(long, help = "Replace an existing crashcap.toml")]
        force: bool,
    },

    /// Perform complete offline config, path, PE and PDB validation.
    Validate {
        #[arg(long, default_value = "release")]
        profile: String,
    },

    /// Read-only API, Workspace, compatibility and producer checks.
    Doctor {
        #[arg(long, help = "Override the Workspace from crashcap.toml")]
        workspace: Option<String>,
    },

    /// Register, stream, verify and seal one Build Publication.
    Publish {
        #[arg(long, default_value = "release")]
        profile: String,

        #[arg(long, value_enum)]
        origin: Option<PublicationOrigin>,

        #[arg(long, default_value_t = 600)]
        wait_seconds: u64,

        #[arg(long, default_value = "crashcap-publication.json")]
        receipt: PathBuf,
    },
}

impl Cli {
    pub fn resolve_api_url(&self) -> Result<String> {
        let explicit = self.api_url.clone().filter(|value| !value.trim().is_empty());
        let environment =
            env::var("CRASHCAP_API_URL").ok().filter(|value| !value.trim().is_empty());
        explicit.or(environment).or(user_api_url()?).ok_or_else(|| {
            PublishError::message(
                "API URL is required: use --api-url, CRASHCAP_API_URL, or the user config",
            )
        })
    }
}

pub fn detected_origin(explicit: Option<PublicationOrigin>) -> PublicationOrigin {
    explicit.unwrap_or_else(|| {
        if ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "TF_BUILD"]
            .iter()
            .any(|name| env::var_os(name).is_some())
        {
            PublicationOrigin::Ci
        } else {
            PublicationOrigin::Local
        }
    })
}

#[cfg(test)]
mod tests {
    use clap::Parser;

    use super::{Cli, Command};

    #[test]
    fn fixed_commands_and_global_json_parse() {
        for command in ["init", "validate", "doctor", "publish"] {
            let mut arguments = vec!["crashcap", "--json", command];
            if command == "init" {
                arguments.extend(["--workspace", "demo", "--artifact-root", "deploy/bin"]);
            }
            let parsed = Cli::try_parse_from(arguments).expect("parse command");
            assert!(parsed.json);
        }
    }

    #[test]
    fn publish_defaults_are_local_friendly() {
        let parsed = Cli::try_parse_from(["crashcap", "publish"]).expect("parse publish");
        let Command::Publish { profile, wait_seconds, receipt, .. } = parsed.command else {
            panic!("publish command")
        };
        assert_eq!(profile, "release");
        assert_eq!(wait_seconds, 600);
        assert_eq!(receipt.to_string_lossy(), "crashcap-publication.json");
    }
}
