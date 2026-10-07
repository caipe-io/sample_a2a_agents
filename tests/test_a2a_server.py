"""Official SDK contracts for both standalone sample agents."""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import uvicorn
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from fastapi import FastAPI
from langchain_core.messages import AIMessageChunk

from sample_a2a_agents.netutils_agent.server import create_app as netutils_app
from sample_a2a_agents.weather_agent.server import create_app as weather_app


class _FakeAgent:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def astream(
        self, input: dict[str, Any], stream_mode: str
    ) -> AsyncIterator[tuple[AIMessageChunk, dict[str, object]]]:
        assert stream_mode == "messages"
        self.messages.append(input["messages"][-1]["content"])
        # Internal tool arguments must not appear in the public response.
        yield AIMessageChunk(content="", tool_call_chunks=[{"name": "internal", "args": "{}", "id": "call"}]), {}
        yield AIMessageChunk(content="Example "), {}
        await asyncio.sleep(0.02)
        yield AIMessageChunk(content="response"), {}


@asynccontextmanager
async def _server(app_factory: Any, agent: Any) -> AsyncIterator[str]:
    # Hold the ephemeral port until Uvicorn takes ownership to avoid a bind race.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}/"
        app = app_factory(agent=agent, agent_url=endpoint)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="on"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("A2A sample server exited before startup")
                    await asyncio.sleep(0.01)
            yield endpoint
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("app_factory", [netutils_app, weather_app])
async def test_health_needs_no_query_parameters(app_factory: Any) -> None:
    app: FastAPI = app_factory(agent=_FakeAgent())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://example.test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.parametrize("app_factory", [netutils_app, weather_app])
@pytest.mark.parametrize("streaming", [False, True])
async def test_sdk_discovery_and_incremental_response(app_factory: Any, streaming: bool) -> None:
    agent = _FakeAgent()
    async with _server(app_factory, agent) as endpoint:
        async with httpx.AsyncClient(timeout=10) as http_client:
            card = (await http_client.get(endpoint + ".well-known/agent-card.json")).json()
            assert card["capabilities"]["streaming"] is True
            assert card["supportedInterfaces"][0]["url"] == endpoint
            factory = ClientFactory(ClientConfig(streaming=streaming, httpx_client=http_client))
            client = await factory.create_from_url(endpoint)
            response_text = ""
            chunks: list[str] = []
            completed = False
            try:
                request = SendMessageRequest(
                    message=Message(message_id="test-message", role=Role.ROLE_USER, parts=[Part(text="hello")])
                )
                async for response in client.send_message(request):
                    if response.HasField("artifact_update"):
                        chunks.append("".join(part.text for part in response.artifact_update.artifact.parts))
                    if response.HasField("status_update"):
                        completed = response.status_update.status.state == TaskState.TASK_STATE_COMPLETED
                    if response.HasField("task"):
                        response_text = "".join(part.text for a in response.task.artifacts for part in a.parts)
                        completed = response.task.status.state == TaskState.TASK_STATE_COMPLETED
            finally:
                await client.close()
    assert agent.messages == ["hello"]
    assert completed
    if streaming:
        assert chunks[:2] == ["Example ", "response"]
        assert "".join(chunks) == "Example response"
    else:
        assert response_text == "Example response"
