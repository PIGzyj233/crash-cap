from __future__ import annotations

import re
import secrets
import threading
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = frozenset(
    {"wsp", "bld", "mod", "art", "abl", "abp", "blob", "occ", "run", "grp", "upl", "pub"}
)
ID_RE = re.compile(
    r"^(wsp|bld|mod|art|abl|abp|blob|occ|run|grp|upl|pub)_([0-9A-HJKMNP-TV-Z]{26})$"
)
_lock = threading.Lock()
_last_timestamp = -1
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = CROCKFORD[value & 31]
        value >>= 5
    if value:
        raise ValueError("value exceeds ULID width")
    return "".join(chars)


def new_ulid() -> str:
    global _last_random, _last_timestamp
    with _lock:
        timestamp = time.time_ns() // 1_000_000
        if timestamp == _last_timestamp:
            _last_random = (_last_random + 1) & ((1 << 80) - 1)
            if _last_random == 0:
                while timestamp <= _last_timestamp:
                    timestamp = time.time_ns() // 1_000_000
                _last_random = secrets.randbits(80)
        else:
            _last_random = secrets.randbits(80)
            _last_timestamp = timestamp
        _last_timestamp = timestamp
        return _encode(timestamp, 10) + _encode(_last_random, 16)


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unsupported Crash-Cap ID prefix: {prefix}")
    return f"{prefix}_{new_ulid()}"


def validate_id(value: str, expected_prefix: str | None = None) -> str:
    match = ID_RE.fullmatch(value)
    if not match:
        raise ValueError("invalid Crash-Cap identifier")
    if expected_prefix is not None and match.group(1) != expected_prefix:
        raise ValueError(f"expected {expected_prefix}_ identifier")
    return value
