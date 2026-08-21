from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlsplit

_URL = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?ix)"
    r"(?P<key>"
    r"x-amz-(?:signature|credential|security-token)|"
    r"aws[_-](?:access[_-]?key(?:[_-]?id)?|secret[_-]?access[_-]?key)|"
    r"(?:access[_ -]?key|secret|token|password|authorization|credential|"
    r"session[_ -]?token|signature)"
    r")"
    r"(?P<separator>[\"'=: ]+)"
    r"(?P<value>[^,;\s\"'&]+)"
)
_PRESIGNED_QUERY_KEYS = {
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signature",
    "x-amz-signedheaders",
    "awsaccesskeyid",
    "signature",
    "sig",
}

_SENSITIVE_KEY_NAMES = {
    "authorization",
    "credential",
    "credentials",
    "memory",
    "memorybytes",
    "memorycontent",
    "minidump",
    "password",
    "presignedurl",
    "rawmemory",
    "rawsource",
    "secret",
    "sessiontoken",
    "signature",
    "signedurl",
    "source",
    "sourcecode",
    "sourcecontent",
    "sourcetext",
    "token",
    "url",
}
_DROP = object()


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    return (
        any(
            marker in normalized
            for marker in (
                "accesskey",
                "authorization",
                "credential",
                "password",
                "secret",
                "token",
            )
        )
        or "presigned" in normalized
    )


def _redact_url(match: re.Match[str]) -> str:
    candidate = match.group(0)
    trailing = ""
    while candidate and candidate[-1] in ".,;:)]}":
        trailing = candidate[-1] + trailing
        candidate = candidate[:-1]
    try:
        query_keys = {
            key.casefold().replace("_", "-")
            for key, _value in parse_qsl(urlsplit(candidate).query, keep_blank_values=True)
        }
    except ValueError:
        query_keys = set()
    if query_keys & _PRESIGNED_QUERY_KEYS:
        return "[REDACTED_URL]" + trailing
    return candidate + trailing


def redact(value: Any) -> str:
    text = str(value)
    text = _URL.sub(_redact_url, text)
    return _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}[REDACTED]", text
    )


def sanitize_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Return JSON-safe details with sensitive nested fields removed or redacted."""
    sanitized = _sanitize_value(details)
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapping_result: dict[Any, Any] = {}
        for key, child in value.items():
            if _is_sensitive_key(key):
                continue
            safe_child = _sanitize_value(child)
            if safe_child is not _DROP:
                mapping_result[key] = safe_child
        return mapping_result
    if isinstance(value, list):
        list_result: list[Any] = []
        for item in value:
            safe_item = _sanitize_value(item)
            list_result.append(safe_item if safe_item is not _DROP else "[REDACTED]")
        return list_result
    if isinstance(value, tuple):
        tuple_result: list[Any] = []
        for item in value:
            safe_item = _sanitize_value(item)
            tuple_result.append(safe_item if safe_item is not _DROP else "[REDACTED]")
        return tuple(tuple_result)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(value)


def _redact_log_argument(value: Any) -> Any:
    """Redact secrets without changing numeric arguments used by logging formats."""
    text = str(value)
    redacted = redact(text)
    if isinstance(value, str) or redacted != text:
        return redacted
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: _redact_log_argument(value) for key, value in record.args.items()
                }
            else:
                record.args = tuple(_redact_log_argument(value) for value in record.args)
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
