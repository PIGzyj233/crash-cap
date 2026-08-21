from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Any

SYSTEM_DENY_MODULES = frozenset(
    {
        "ntdll.dll",
        "kernel32.dll",
        "kernelbase.dll",
        "ucrtbase.dll",
        "msvcp140.dll",
        "vcruntime140.dll",
        "combase.dll",
        "ws2_32.dll",
        "bcryptprimitives.dll",
        "win32u.dll",
    }
)


def module_basename(value: str) -> str:
    return PureWindowsPath(value.replace("/", "\\")).name.casefold()


def is_system_module(value: str) -> bool:
    normalized = value.replace("/", "\\").casefold()
    return (
        "\\windows\\system32\\" in normalized
        or "\\windows\\syswow64\\" in normalized
        or module_basename(value) in SYSTEM_DENY_MODULES
    )


def resolve_in_app(code_file: str, role: str, rules: dict[str, Any] | None) -> bool:
    if is_system_module(code_file):
        return False
    name = module_basename(code_file)
    selected = rules or {}
    excluded = {str(item).casefold() for item in selected.get("exclude_modules", [])}
    included = {str(item).casefold() for item in selected.get("include_modules", [])}
    if name in excluded:
        return False
    if name in included:
        return True
    return role in {"entrypoint", "owned"}
