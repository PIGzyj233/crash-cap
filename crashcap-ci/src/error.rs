use thiserror::Error;

#[derive(Debug, Error)]
pub enum PublishError {
    #[error("{0}")]
    Message(String),
}

impl PublishError {
    pub fn message(value: impl Into<String>) -> Self {
        Self::Message(value.into())
    }
}

pub type Result<T> = std::result::Result<T, PublishError>;
