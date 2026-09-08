"""Request identity shared with business code, independent of credential transport."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    display_name: str
    kind: str
    role: str
    method: str
    credential_id: str | None = None
    must_change_password: bool = False


SYSTEM = Principal("usr_system", "system", "后台系统", "system", "member", "system")
current_principal: ContextVar[Principal] = ContextVar("principal", default=SYSTEM)


def actor_id() -> str:
    return current_principal.get().user_id


def actor_name() -> str:
    return current_principal.get().display_name
