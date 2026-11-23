import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select

from app.ai.prompts import build_system_prompt
from app.ai.providers import (
    ChatMessage,
    ChatProvider,
    ChatRequest,
    Completed,
    EmbeddingProvider,
    TextDelta,
    ToolCall,
    WebSearchProvider,
)
from app.db.models import Message, User
from app.db.session import user_session
from app.services import (
    agent_actions,
    agent_settings,
    agent_tools,
    conversations,
    memories,
    module_settings,
    usage,
)

logger = logging.getLogger(__name__)

HISTORY_CHARACTER_BUDGET = 24_000
MAX_TOOL_ROUNDS = 4


class NotFound(Exception):
    """The conversation is missing or does not belong to the user."""


@dataclass(frozen=True)
class UserMessageStored:
    id: str
    conversation_id: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Done:
    message_id: str
    title: str


@dataclass(frozen=True)
class Error:
    code: str = "PROVIDER_ERROR"


@dataclass(frozen=True)
class ToolStatus:
    name: str
    status: str  # running, done, error, awaiting_confirmation


@dataclass(frozen=True)
class SourcesFound:
    items: list[dict]


@dataclass(frozen=True)
class ActionProposed:
    id: str
    tool: str
    arguments: dict
    status: str = "pending"


type ChatStreamEvent = UserMessageStored | Delta | ToolStatus | SourcesFound | ActionProposed | Done | Error


def build_history(messages: list[Message]) -> list[ChatMessage]:
    """Newest messages that fit the character budget; empty assistant stubs carry no information."""
    selected: list[Message] = []
    used = 0
    for message in reversed(messages):
        if not message.content:
            continue
        if used + len(message.content) > HISTORY_CHARACTER_BUDGET:
            break
        selected.append(message)
        used += len(message.content)
    selected.reverse()
    return [ChatMessage(role=item.role, content=item.content) for item in selected]


def _tool_output(payload: dict) -> str:
    """Tool output is untrusted data: serialized and delimited so it cannot pose as instructions."""
    return f"<tool_result>{json.dumps(payload, ensure_ascii=False)}</tool_result>"


def _number(output: agent_tools.ToolOutput, collected: list[dict]) -> dict:
    results = output.data.get("results")
    if isinstance(results, list):
        for result, source in zip(results, output.sources, strict=True):
            collected.append({**source, "ref": len(collected) + 1})
            result["ref"] = len(collected)
    return output.data


async def run_chat_turn(
    user: User,
    conversation_id: str,
    user_text: str,
    provider: ChatProvider,
    now: datetime | None = None,
    *,
    embedder: EmbeddingProvider | None = None,
    web_search: WebSearchProvider | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    current_time = now or datetime.now(UTC)
    normalized_title = " ".join(user_text.split())[:60]

    async with user_session(user.id) as session:
        conversation = await conversations.get_conversation(session, user, conversation_id)
        if conversation is None:
            raise NotFound
        stored = await conversations.add_message(
            session, user, conversation_id, "user", user_text
        )
        assert stored is not None
        if conversation.title == conversations.DEFAULT_TITLE:
            conversation.title = normalized_title or conversations.DEFAULT_TITLE
        conversation.updated_at = current_time
        await session.flush()
        user_message = UserMessageStored(
            id=stored.id,
            conversation_id=stored.conversation_id,
            content=stored.content,
            created_at=stored.created_at,
        )

    yield user_message

    async with user_session(user.id) as session:
        rows = list((await session.scalars(
            select(Message).where(
                Message.user_id == user.id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            ).order_by(Message.created_at, Message.id)
        )).all())
        remembered = await memories.memories_for_context(session, user)
        write_mode = await agent_settings.get_write_mode(session, user)
        tools = agent_tools.available_tools(
            await module_settings.enabled_module_keys(session),
            has_embedder=embedder is not None,
            has_web_search=web_search is not None,
        )
    system = build_system_prompt(remembered)
    history = build_history(rows)
    specs = [tool.spec() for tool in tools]
    by_name = {tool.name: tool for tool in tools}

    answer: list[str] = []
    sources: list[dict] = []
    tool_log: list[dict] = []
    proposals: list[tuple[agent_tools.Tool, dict]] = []
    input_tokens = output_tokens = 0
    try:
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            # The last round offers no tools so the model has to answer.
            request = ChatRequest(
                system=system, messages=history, tools=specs if round_number < MAX_TOOL_ROUNDS else []
            )
            calls: list[ToolCall] = []
            completed = False
            async for event in provider.stream(request):
                if isinstance(event, TextDelta):
                    answer.append(event.text)
                    yield Delta(event.text)
                elif isinstance(event, Completed):
                    completed = True
                    input_tokens += event.usage.input_tokens
                    output_tokens += event.usage.output_tokens
                elif isinstance(event, ToolCall):
                    calls.append(event)
            if not completed:
                raise RuntimeError("Provider stream did not complete")
            if not calls:
                break
            awaiting_user = False
            for call in calls:
                history.append(ChatMessage(role="assistant", content="", tool_call=call))
                payload, status = await _handle_call(
                    user, call, by_name, write_mode, sources, proposals, embedder, web_search,
                )
                awaiting_user = awaiting_user or status == "awaiting_confirmation"
                tool_log.append({"name": call.name, "status": status})
                yield ToolStatus(call.name, status)
                history.append(ChatMessage(role="tool", content=_tool_output(payload), tool_call_id=call.id))
            if awaiting_user:
                break
    except Exception:
        logger.warning("Chat turn failed", exc_info=True)
        await usage.record(user.id, chat_requests=1, input_tokens=input_tokens, output_tokens=output_tokens)
        yield Error()
        return

    missing = False
    assistant_id = ""
    title = ""
    proposed: list[ActionProposed] = []
    async with user_session(user.id) as session:
        await usage.add(session, user.id, {
            usage.CHAT_REQUESTS: 1, usage.INPUT_TOKENS: input_tokens, usage.OUTPUT_TOKENS: output_tokens,
        })
        conversation = await conversations.get_conversation(session, user, conversation_id)
        if conversation is None:
            missing = True
        else:
            assistant = await conversations.add_message(
                session,
                user,
                conversation_id,
                "assistant",
                "".join(answer),
                tool_calls=tool_log or None,
                citations=sources or None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            assert assistant is not None
            for tool, arguments in proposals:
                action = await agent_actions.create_pending(
                    session, user, conversation_id, assistant.id, tool.name, arguments
                )
                proposed.append(ActionProposed(action.id, tool.name, arguments))
            conversation.updated_at = current_time
            title = conversation.title
            assistant_id = assistant.id
    if missing:
        yield Error()
        return
    if sources:
        yield SourcesFound(sources)
    for item in proposed:
        yield item
    yield Done(message_id=assistant_id, title=title)


async def _handle_call(
    user: User,
    call: ToolCall,
    by_name: dict[str, agent_tools.Tool],
    write_mode: str,
    sources: list[dict],
    proposals: list[tuple[agent_tools.Tool, dict]],
    embedder: EmbeddingProvider | None,
    web_search: WebSearchProvider | None,
) -> tuple[dict, str]:
    """Run or defer one model-requested tool call. Returns the model-facing payload and a UI status."""
    tool = by_name.get(call.name)
    if tool is None:
        return {"error": "UNKNOWN_TOOL"}, "error"
    try:
        arguments = tool.input_model.model_validate_json(call.arguments_json)
    except ValidationError:
        return {"error": "INVALID_ARGUMENTS"}, "error"
    if tool.write and write_mode == "ask":
        proposals.append((tool, arguments.model_dump(mode="json")))
        return {"status": "awaiting_user_confirmation"}, "awaiting_confirmation"
    try:
        async with user_session(user.id) as session:
            context = agent_tools.ToolContext(
                user=user, session=session, embedder=embedder, web_search=web_search
            )
            output = await agent_tools.run_tool(context, tool, arguments)
    except agent_tools.ToolError as exc:
        return {"error": exc.code}, "error"
    except Exception:
        logger.warning("Tool %s failed", tool.name, exc_info=True)
        return {"error": "TOOL_FAILED"}, "error"
    return _number(output, sources), "done"
