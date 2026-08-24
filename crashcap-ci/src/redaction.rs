use std::sync::OnceLock;

use regex::{Captures, Regex};

fn url_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r#"(?i)\bhttps?://[^\s\"'<>]+"#).expect("static URL redaction regex")
    })
}

fn assignment_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(
            r#"(?ix)
            (?P<key>
                x-amz-(?:signature|credential|security-token)|
                aws[_-](?:access[_-]?key(?:[_-]?id)?|secret[_-]?access[_-]?key)|
                (?:access[_ -]?key|secret|token|password|authorization|credential|session[_ -]?token|signature)
            )
            (?P<separator>[\"'=:\x20]+)
            (?P<value>[^,;\s\"'&]+)
            "#,
        )
        .expect("static assignment redaction regex")
    })
}

fn bearer_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*").expect("static bearer regex")
    })
}

fn is_sensitive_url(candidate: &str) -> bool {
    let lower = candidate.to_ascii_lowercase();
    lower.contains('?')
        && [
            "x-amz-",
            "signature",
            "credential",
            "security-token",
            "access_key",
            "accesskey",
            "secret",
            "token=",
            "sig=",
        ]
        .iter()
        .any(|marker| lower.contains(marker))
}

pub fn redact(value: &str) -> String {
    let urls_removed = url_pattern().replace_all(value, |captures: &Captures<'_>| {
        let candidate = captures.get(0).map_or("", |item| item.as_str());
        if is_sensitive_url(candidate) {
            "[REDACTED_URL]".to_owned()
        } else {
            candidate.to_owned()
        }
    });
    let assignments_removed =
        assignment_pattern().replace_all(&urls_removed, |captures: &Captures<'_>| {
            format!(
                "{}{}[REDACTED]",
                captures.name("key").map_or("", |item| item.as_str()),
                captures.name("separator").map_or("=", |item| item.as_str())
            )
        });
    bearer_pattern().replace_all(&assignments_removed, "Bearer [REDACTED]").into_owned()
}

#[cfg(test)]
mod tests {
    use super::redact;

    #[test]
    fn removes_presigned_urls_and_credentials() {
        let sentinel = "SUPER_SECRET_SENTINEL";
        let text = format!(
            "upload https://store/object?X-Amz-Credential={sentinel}&X-Amz-Signature={sentinel} authorization=Bearer.{sentinel} secret: {sentinel} Bearer {sentinel}"
        );
        let output = redact(&text);
        assert!(!output.contains(sentinel), "redacted output: {output}");
        assert!(output.contains("[REDACTED_URL]"));
        assert!(output.contains("[REDACTED]"));
    }

    #[test]
    fn keeps_non_sensitive_api_urls_visible() {
        let text = "API http://127.0.0.1:8000/api/v1 failed";
        assert_eq!(redact(text), text);
    }
}
