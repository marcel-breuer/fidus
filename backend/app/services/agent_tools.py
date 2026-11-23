"""Typed, registered agent tools.

Every tool is a service operation with a pydantic input model. The agent can only call tools
listed in `REGISTRY`; there is no raw SQL or command execution. Write tools run behind the
per-user "ask before write" policy (see `agent_actions`) and always leave an audit row."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import EmbeddingProvider, ToolSpec, WebSearchProvider
from app.db.models import User
from app.services import audit, conversations, memories, retrieval, tasks

MAX_WEB_ANSWER_CHARACTERS = 4000


class ToolError(Exception):
    """A tool failed in an expected way; the code is safe to show the model."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ToolContext:
    user: User
    session: AsyncSession
    embedder: EmbeddingProvider | None = None
    web_search: WebSearchProvider | None = None


@dataclass
class ToolOutput:
    """`data["results"][i]` is described by `sources[i]`; the caller numbers them."""

    data: dict[str, Any]
    sources: list[dict[str, Any]] = field(default_factory=list)
    target: tuple[str, str | None] | None = None


Handler = Callable[[ToolContext, Any], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    write: bool = False
    module: str | None = None
    needs: str | None = None  # "web_search" or "embedder"

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.input_model.model_json_schema())


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class RememberInput(BaseModel):
    content: str = Field(min_length=1, max_length=memories.MAX_CONTENT_LENGTH)


class CreateTaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = Field(default=None, description="ISO 8601 date and time with offset")


async def _search_knowledge(ctx: ToolContext, args: SearchInput) -> ToolOutput:
    assert ctx.embedder is not None
    hits = await retrieval.search_knowledge(ctx.session, ctx.user, args.query, ctx.embedder)
    return ToolOutput(
        data={"results": [
            {"file": hit.file_name, "version": hit.version, "passage": hit.snippet} for hit in hits
        ]},
        sources=[{
            "type": "file", "file_name": hit.file_name, "node_id": hit.node_id, "folder_id": hit.folder_id,
            "version": hit.version, "position": hit.position, "snippet": hit.snippet,
        } for hit in hits],
    )


async def _search_conversations(ctx: ToolContext, args: SearchInput) -> ToolOutput:
    rows = await conversations.search_messages(ctx.session, ctx.user, args.query, limit=5)
    snippets = [re.sub(r"</?b>", "", str(row["snippet"])) for row in rows]
    return ToolOutput(
        data={"results": [{"passage": snippet} for snippet in snippets]},
        sources=[{
            "type": "conversation", "conversation_id": str(row["conversation_id"]),
            "message_id": str(row["message_id"]), "snippet": snippet,
        } for row, snippet in zip(rows, snippets, strict=True)],
    )


async def _web_search(ctx: ToolContext, args: SearchInput) -> ToolOutput:
    assert ctx.web_search is not None
    result = await ctx.web_search.search(args.query)
    sources = [item for item in result.sources if item.url.lower().startswith(("https://", "http://"))]
    return ToolOutput(
        data={
            "answer": result.answer[:MAX_WEB_ANSWER_CHARACTERS],
            "results": [{"title": item.title, "url": item.url} for item in sources],
        },
        sources=[{"type": "web", "title": item.title, "url": item.url} for item in sources],
    )


async def _remember(ctx: ToolContext, args: RememberInput) -> ToolOutput:
    try:
        memory = await memories.create_memory(ctx.session, ctx.user, args.content, source="agent")
    except memories.MemoryLimitReached as exc:
        raise ToolError("MEMORY_LIMIT_REACHED") from exc
    return ToolOutput(data={"saved": True}, target=("memory", memory.id))


async def _create_task(ctx: ToolContext, args: CreateTaskInput) -> ToolOutput:
    task = await tasks.create_task(ctx.session, ctx.user, args.title, args.notes, args.due_at)
    return ToolOutput(data={"created": True}, target=("task", task.id))


REGISTRY: dict[str, Tool] = {tool.name: tool for tool in (
    Tool(
        "search_knowledge", "Search the user's uploaded files for relevant passages.",
        SearchInput, _search_knowledge, module="files", needs="embedder",
    ),
    Tool(
        "search_conversations", "Search the user's earlier chat messages.",
        SearchInput, _search_conversations,
    ),
    Tool(
        "web_search", "Search the web for current information.",
        SearchInput, _web_search, needs="web_search",
    ),
    Tool(
        "remember", "Save a durable fact about the user that should be remembered in later conversations.",
        RememberInput, _remember, write=True,
    ),
    Tool(
        "create_task", "Create a task for the user, optionally with notes and a due date.",
        CreateTaskInput, _create_task, write=True, module="tasks",
    ),
)}


def available_tools(
    enabled_modules: set[str], *, has_embedder: bool, has_web_search: bool
) -> list[Tool]:
    """Registered tools whose module is enabled and whose provider exists."""
    capabilities = {"embedder": has_embedder, "web_search": has_web_search}
    return [
        tool for tool in REGISTRY.values()
        if (tool.module is None or tool.module in enabled_modules)
        and (tool.needs is None or capabilities[tool.needs])
    ]


async def run_tool(ctx: ToolContext, tool: Tool, arguments: BaseModel) -> ToolOutput:
    """Execute a tool in the caller's transaction; writes are audited atomically with the change."""
    output = await tool.handler(ctx, arguments)
    if tool.write:
        target_type, target_id = output.target or ("none", None)
        await audit.record(ctx.session, ctx.user, f"agent.{tool.name}", target_type, target_id)
    return output
