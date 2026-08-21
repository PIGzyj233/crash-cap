from __future__ import annotations

import json
import socket

TARGETS = (
    ("symbolicator-gateway", 3021, True),
    ("postgres", 5432, False),
    ("rustfs", 9000, False),
    ("1.1.1.1", 443, False),
)


def main() -> int:
    results: dict[str, dict[str, object]] = {}
    passed = True
    for host, port, expected in TARGETS:
        reachable = False
        error_type: str | None = None
        connection = socket.socket()
        connection.settimeout(2)
        try:
            connection.connect((host, port))
            reachable = True
        except OSError as error:
            error_type = type(error).__name__
        finally:
            connection.close()
        results[host] = {
            "reachable": reachable,
            "expected": expected,
            "error_type": error_type,
        }
        passed = passed and reachable is expected
    print(json.dumps({"passed": passed, "targets": results}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
