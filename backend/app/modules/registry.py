from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    """A feature area. Modules never depend unconditionally on each other:
    `optional_with` only lists modules it can enrich when they are present."""

    key: str
    name_key: str
    icon: str
    route: str
    scopes: tuple[str, ...]
    optional_with: tuple[str, ...] = ()


REGISTRY: tuple[Module, ...] = (
    Module("chat", "modules.chat", "chat", "/chat", ("chat:use",), ("files", "tasks")),
    Module("files", "modules.files", "files", "/files", ("files:read", "files:write")),
    Module("tasks", "modules.tasks", "tasks", "/tasks", ("tasks:read", "tasks:write")),
    Module("audio", "modules.audio", "audio", "/audio", ("audio:read", "audio:write")),
)


def modules_for_scopes(granted: frozenset[str]) -> list[Module]:
    """Modules whose required scopes the caller holds, in registry order."""
    return [m for m in REGISTRY if set(m.scopes) <= granted]


ALL_SCOPES: frozenset[str] = frozenset(s for m in REGISTRY for s in m.scopes)
