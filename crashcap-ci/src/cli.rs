use std::env;
use std::path::PathBuf;

use clap::{Parser, ValueEnum};

use crate::error::{PublishError, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum Producer {
    Msvc,
    ClangCl,
    Crashpad,
}

impl Producer {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Msvc => "msvc",
            Self::ClangCl => "clang-cl",
            Self::Crashpad => "crashpad",
        }
    }
}

#[derive(Clone, Debug, Parser)]
#[command(name = "crashcap-ci", version, about = "Idempotently publish one Crash-Cap CI Build")]
pub struct Cli {
    #[arg(long)]
    pub api_url: Option<String>,

    #[arg(long, help = "Workspace id or exact name")]
    pub workspace: String,

    #[arg(long)]
    pub manifest: PathBuf,

    #[arg(long)]
    pub artifact_root: PathBuf,

    #[arg(long, value_enum, default_value_t = Producer::Msvc)]
    pub producer: Producer,

    #[arg(long)]
    pub producer_build_id: Option<String>,

    #[arg(long)]
    pub allow_experimental: bool,

    #[arg(long, default_value_t = 600)]
    pub wait_seconds: u64,
}

#[derive(Clone, Debug)]
pub struct ResolvedArgs {
    pub api_url: String,
    pub workspace: String,
    pub manifest: PathBuf,
    pub artifact_root: PathBuf,
    pub producer: Producer,
    pub producer_build_id: String,
    pub allow_experimental: bool,
    pub wait_seconds: u64,
}

impl Cli {
    pub fn resolve(self) -> Result<ResolvedArgs> {
        self.resolve_with(|name| env::var(name).ok())
    }

    fn resolve_with<F>(self, env_value: F) -> Result<ResolvedArgs>
    where
        F: Fn(&str) -> Option<String>,
    {
        let non_empty = |value: Option<String>| value.filter(|item| !item.is_empty());
        let api_url = non_empty(self.api_url)
            .or_else(|| non_empty(env_value("CRASHCAP_API_URL")))
            .ok_or_else(|| {
                PublishError::message("--api-url is required when CRASHCAP_API_URL is not set")
            })?;
        let producer_build_id = non_empty(self.producer_build_id)
            .or_else(|| non_empty(env_value("GITHUB_RUN_ID")))
            .or_else(|| non_empty(env_value("BUILD_BUILDID")))
            .or_else(|| non_empty(env_value("CI_PIPELINE_ID")))
            .ok_or_else(|| {
                PublishError::message(
                    "--producer-build-id is required when no supported CI build id is set",
                )
            })?;
        Ok(ResolvedArgs {
            api_url,
            workspace: self.workspace,
            manifest: self.manifest,
            artifact_root: self.artifact_root,
            producer: self.producer,
            producer_build_id,
            allow_experimental: self.allow_experimental,
            wait_seconds: self.wait_seconds.max(1),
        })
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use clap::Parser;

    use super::Cli;

    fn base_cli() -> Cli {
        Cli::try_parse_from([
            "crashcap-ci",
            "--workspace",
            "demo",
            "--manifest",
            "manifest.json",
            "--artifact-root",
            "out",
        ])
        .expect("parse CLI")
    }

    #[test]
    fn resolves_gitlab_pipeline_id_after_existing_ci_fallbacks() {
        let values = HashMap::from([
            ("CRASHCAP_API_URL", "http://api/api/v1"),
            ("CI_PIPELINE_ID", "gitlab-42"),
        ]);
        let resolved = base_cli()
            .resolve_with(|name| values.get(name).map(|value| (*value).to_owned()))
            .expect("resolve GitLab variables");
        assert_eq!(resolved.api_url, "http://api/api/v1");
        assert_eq!(resolved.producer_build_id, "gitlab-42");
        assert_eq!(resolved.wait_seconds, 600);
    }

    #[test]
    fn explicit_values_win_and_zero_wait_is_clamped() {
        let mut cli = base_cli();
        cli.api_url = Some("http://explicit/api/v1".to_owned());
        cli.producer_build_id = Some("explicit-build".to_owned());
        cli.wait_seconds = 0;
        let resolved = cli
            .resolve_with(|_| Some("environment-value".to_owned()))
            .expect("resolve explicit values");
        assert_eq!(resolved.api_url, "http://explicit/api/v1");
        assert_eq!(resolved.producer_build_id, "explicit-build");
        assert_eq!(resolved.wait_seconds, 1);
    }
}
