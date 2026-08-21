use serde::Serialize;
use serde_json::Value;
use std::fmt::{Display, Formatter};

pub type CliResult<T> = Result<T, CliError>;

#[derive(Debug, Clone, Serialize)]
pub struct ErrorBody {
    pub code: String,
    pub message: String,
    pub details: Value,
}

#[derive(Debug, Clone)]
pub struct CliError {
    pub code: String,
    pub message: String,
    pub details: Value,
    pub exit_code: i32,
}

impl CliError {
    pub fn new(code: impl Into<String>, message: impl Into<String>, exit_code: i32) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            details: Value::Object(Default::default()),
            exit_code,
        }
    }

    pub fn with_details(
        code: impl Into<String>,
        message: impl Into<String>,
        exit_code: i32,
        details: Value,
    ) -> Self {
        Self { code: code.into(), message: message.into(), details, exit_code }
    }

    pub fn input_not_found(path: &std::path::Path, source: std::io::Error) -> Self {
        Self::with_details(
            "INPUT_NOT_FOUND",
            format!("input file cannot be read: {}", path.display()),
            1,
            serde_json::json!({ "path": path, "reason": source.to_string() }),
        )
    }

    pub fn io(path: &std::path::Path, source: std::io::Error) -> Self {
        Self::with_details(
            "IO_ERROR",
            format!("cannot access {}", path.display()),
            1,
            serde_json::json!({ "path": path, "reason": source.to_string() }),
        )
    }

    pub fn invalid_inspect(path: &std::path::Path, source: impl Display) -> Self {
        Self::with_details(
            "INVALID_INSPECT",
            format!("inspect JSON is invalid: {}", path.display()),
            3,
            serde_json::json!({ "path": path, "reason": source.to_string() }),
        )
    }

    pub fn to_json_line(&self) -> String {
        serde_json::to_string(&serde_json::json!({
            "error": ErrorBody {
                code: self.code.clone(),
                message: self.message.clone(),
                details: self.details.clone(),
            }
        }))
        .unwrap_or_else(|_| {
            "{\"error\":{\"code\":\"INTERNAL_ERROR\",\"message\":\"failed to serialize error\",\"details\":{}}}".to_owned()
        })
    }
}

impl Display for CliError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for CliError {}
