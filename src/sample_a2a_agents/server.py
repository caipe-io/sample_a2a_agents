"""Official SDK adapter shared by the optional local A2A example agents."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessageChunk

logger = logging.getLogger(__name__)


def _text_content(content: Any) -> str:
    """Preserve string and text-block content identically for streaming and complete responses."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text_content(part) for part in content)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return ""


class LangGraphExecutor(AgentExecutor):
    """Delegate A2A requests to the LangGraph agent."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if not context.task_id or not context.context_id:
            raise ValueError("A2A task identifiers are required")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(
            Task(id=context.task_id, context_id=context.context_id,
                 status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
        )
        await updater.start_work()
        artifact_id = str(uuid.uuid4())
        emitted = False
        try:
            inputs = {"messages": [{"role": "user", "content": context.get_user_input()}]}
            if hasattr(self._agent, "astream"):
                async for chunk, _metadata in self._agent.astream(inputs, stream_mode="messages"):
                    # Tool arguments and tool results stay private to the remote agent.
                    if not isinstance(chunk, AIMessageChunk) or chunk.tool_call_chunks:
                        continue
                    content = _text_content(chunk.content)
                    if content:
                        await updater.add_artifact([Part(text=content)], artifact_id=artifact_id, append=emitted)
                        emitted = True
            else:
                result = await self._agent.ainvoke(inputs)
                messages = result.get("messages", [])
                content = _text_content(messages[-1].content) if messages else ""
                if content:
                    await updater.add_artifact([Part(text=content)], artifact_id=artifact_id)
                    emitted = True
            await updater.add_artifact(
                [Part(text="" if emitted else "Agent returned no response.")],
                artifact_id=artifact_id, append=emitted, last_chunk=True,
            )
            await updater.complete()
        except Exception:
            logger.exception("A2A execution failed for task %s in context %s", context.task_id, context.context_id)
            await updater.failed(Message(message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT,
                                         parts=[Part(text="Agent execution failed. Check the remote agent logs.")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Ignoring cancellation for example A2A task %s", context.task_id)


async def _health(request: Request) -> JSONResponse:
    ready = getattr(request.app.state, "ready", False)
    return JSONResponse({"status": "healthy" if ready else "starting"}, status_code=200 if ready else 503)


def create_example_app(
    *,
    name: str,
    description: str,
    skill: AgentSkill,
    agent_url: str,
    build_agent: Callable[[], Awaitable[Any]],
    agent: Any | None = None,
) -> FastAPI:
    """Create an SDK A2A server with injectable agent for offline protocol tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_agent = agent if agent is not None else await build_agent()
        card = AgentCard(
            name=name,
            description=description,
            version="1.0.0",
            capabilities=AgentCapabilities(streaming=True),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=[skill],
            supported_interfaces=[AgentInterface(url=agent_url, protocol_binding="JSONRPC", protocol_version="1.0")],
        )
        handler = DefaultRequestHandler(
            agent_executor=LangGraphExecutor(active_agent),
            task_store=InMemoryTaskStore(),
            agent_card=card,
        )
        app.state.agent_card = card
        app.state.request_handler = handler
        app.router.routes.extend(create_agent_card_routes(card))
        app.router.routes.extend(create_jsonrpc_routes(handler, rpc_url="/"))
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False

    app = FastAPI(lifespan=lifespan)
    app.add_api_route("/healthz", _health, methods=["GET"])
    return app
