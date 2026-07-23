"""Tests for MCP tool-enabled sampling (sampling.tools capability + requests)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import types as mcp_types

from agent.llm_provider import (
    McpSamplingLLMProvider,
    SamplingToolCall,
    _client_supports_sampling_tools,
)

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "inputSchema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def _ctx(session) -> SimpleNamespace:
    return SimpleNamespace(session=session)


def _tools_result(*blocks) -> mcp_types.CreateMessageResultWithTools:
    return mcp_types.CreateMessageResultWithTools(
        role="assistant",
        content=list(blocks),
        model="client-model",
        stopReason="toolUse",
    )


class TestSamplingToolsCapabilityDetection:
    def test_public_api_check_client_capability(self) -> None:
        recorded = {}

        def check(capabilities):
            recorded["capabilities"] = capabilities
            return True

        session = SimpleNamespace(
            client_params=SimpleNamespace(capabilities=SimpleNamespace()),
            check_client_capability=check,
        )
        assert _client_supports_sampling_tools(_ctx(session)) is True
        assert recorded["capabilities"].sampling.tools is not None

    def test_public_api_declares_no_tools(self) -> None:
        session = SimpleNamespace(
            client_params=SimpleNamespace(capabilities=SimpleNamespace()),
            check_client_capability=lambda capabilities: False,
        )
        assert _client_supports_sampling_tools(_ctx(session)) is False

    def test_private_params_with_tools(self) -> None:
        session = SimpleNamespace(
            _client_params={"capabilities": {"sampling": {"tools": {}}}},
        )
        assert _client_supports_sampling_tools(_ctx(session)) is True

    def test_private_params_sampling_without_tools(self) -> None:
        session = SimpleNamespace(
            _client_params={"capabilities": {"sampling": {}}},
        )
        assert _client_supports_sampling_tools(_ctx(session)) is False

    def test_unknown_capabilities_are_not_optimistic(self) -> None:
        """Unlike basic sampling, tools require explicit declaration."""
        assert _client_supports_sampling_tools(SimpleNamespace(session=None)) is False
        assert (
            _client_supports_sampling_tools(_ctx(SimpleNamespace(client_params=None))) is False
        )
        assert (
            _client_supports_sampling_tools(_ctx(SimpleNamespace(_client_params=None))) is False
        )

    def test_public_client_params_direct_inspection(self) -> None:
        """Without check_client_capability, fall back to field inspection."""
        session = SimpleNamespace(
            client_params=SimpleNamespace(
                capabilities=SimpleNamespace(
                    sampling=SimpleNamespace(tools=SimpleNamespace())
                )
            ),
        )
        assert _client_supports_sampling_tools(_ctx(session)) is True

        session_no_tools = SimpleNamespace(
            client_params=SimpleNamespace(
                capabilities=SimpleNamespace(sampling=SimpleNamespace(tools=None))
            ),
        )
        assert _client_supports_sampling_tools(_ctx(session_no_tools)) is False


class TestCompleteWithTools:
    def test_sends_scoped_tools_and_parses_tool_use(self) -> None:
        recorded = {}

        async def create_message(messages, **kwargs):
            recorded["messages"] = messages
            recorded["kwargs"] = kwargs
            return _tools_result(
                mcp_types.TextContent(type="text", text="Checking the weather."),
                mcp_types.ToolUseContent(
                    type="tool_use",
                    name="get_weather",
                    id="call_1",
                    input={"city": "Tokyo"},
                ),
            )

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {"tools": {}}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        completion = provider.complete_with_tools(
            [{"role": "user", "content": "What's the weather in Tokyo?"}],
            "gpt-4o",
            [WEATHER_TOOL],
            tool_choice="auto",
        )

        # Tool definitions are scoped to the request.
        sent_tools = recorded["kwargs"]["tools"]
        assert len(sent_tools) == 1
        assert isinstance(sent_tools[0], mcp_types.Tool)
        assert sent_tools[0].name == "get_weather"
        assert recorded["kwargs"]["tool_choice"].mode == "auto"
        assert recorded["kwargs"]["metadata"] == {
            "mumei_agent_llm_provider": "mcp_sampling_tools"
        }

        assert completion.text == "Checking the weather."
        assert completion.tool_calls == [
            SamplingToolCall(name="get_weather", id="call_1", input={"city": "Tokyo"})
        ]
        assert completion.stop_reason == "toolUse"

    def test_accepts_tool_instances_and_no_tool_choice(self) -> None:
        recorded = {}

        async def create_message(messages, **kwargs):
            recorded["kwargs"] = kwargs
            return _tools_result(mcp_types.TextContent(type="text", text="done"))

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {"tools": {}}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))
        tool = mcp_types.Tool.model_validate(WEATHER_TOOL)

        completion = provider.complete_with_tools(
            [{"role": "user", "content": "hi"}], "gpt-4o", [tool]
        )

        assert recorded["kwargs"]["tools"] == [tool]
        assert recorded["kwargs"]["tool_choice"] is None
        assert completion.text == "done"
        assert completion.tool_calls == []

    def test_rejects_client_without_tools_capability(self) -> None:
        async def create_message(messages, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("tool-enabled sampling must not be sent")

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        with pytest.raises(RuntimeError, match="sampling.tools"):
            provider.complete_with_tools(
                [{"role": "user", "content": "hi"}], "gpt-4o", [WEATHER_TOOL]
            )

    def test_rejects_client_without_basic_sampling(self) -> None:
        session = SimpleNamespace(
            create_message=None,
            _client_params={"capabilities": {"sampling": None}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        with pytest.raises(RuntimeError, match="sampling capability"):
            provider.complete_with_tools(
                [{"role": "user", "content": "hi"}], "gpt-4o", [WEATHER_TOOL]
            )

    def test_rejects_invalid_tool_definition(self) -> None:
        session = SimpleNamespace(
            create_message=None,
            _client_params={"capabilities": {"sampling": {"tools": {}}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        with pytest.raises(TypeError, match="unsupported sampling tool definition"):
            provider.complete_with_tools(
                [{"role": "user", "content": "hi"}], "gpt-4o", [42]
            )

    def test_result_without_content_raises(self) -> None:
        async def create_message(messages, **kwargs):
            return SimpleNamespace(content=[], stopReason=None)

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {"tools": {}}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        with pytest.raises(RuntimeError, match="did not contain text or tool-use"):
            provider.complete_with_tools(
                [{"role": "user", "content": "hi"}], "gpt-4o", [WEATHER_TOOL]
            )


class _RecordingFallback:
    """Minimal LLMProvider stub that records the OpenAI-compatible fallback call."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, str]] = []

    def complete(self, messages, model: str) -> str:
        self.calls.append((tuple(messages), model))
        return "openai-fallback"


class TestBasicSamplingMonitoringContract:
    """Lock the soft-deprecation / fallback guarantees tracked as MCP monitoring items."""

    def test_basic_sampling_omits_soft_deprecated_include_context(self) -> None:
        """2025-11-25 soft-deprecates includeContext; it must not be sent."""
        recorded = {}

        async def create_message(messages, **kwargs):
            recorded["kwargs"] = kwargs
            return mcp_types.CreateMessageResult(
                role="assistant",
                content=mcp_types.TextContent(type="text", text="ok"),
                model="client-model",
            )

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        assert provider.complete([{"role": "user", "content": "hi"}], "gpt-4o") == "ok"
        assert "includeContext" not in recorded["kwargs"]
        assert "include_context" not in recorded["kwargs"]
        # tools are also soft-gated and must not leak into the basic text path.
        assert "tools" not in recorded["kwargs"]

    def test_basic_sampling_falls_back_to_openai_on_failure(self) -> None:
        """Sampling failure must delegate to the OpenAI-compatible fallback unchanged."""
        async def create_message(messages, **kwargs):
            raise RuntimeError("sampling unsupported")

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
        fallback = _RecordingFallback()
        provider = McpSamplingLLMProvider(_ctx(session), fallback=fallback)

        messages = [{"role": "user", "content": "hi"}]
        assert provider.complete(messages, "gpt-4o") == "openai-fallback"
        assert len(fallback.calls) == 1
        assert fallback.calls[0][1] == "gpt-4o"

    def test_basic_sampling_without_fallback_reraises(self) -> None:
        async def create_message(messages, **kwargs):
            raise RuntimeError("sampling unsupported")

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session))

        with pytest.raises(RuntimeError, match="sampling unsupported"):
            provider.complete([{"role": "user", "content": "hi"}], "gpt-4o")

    def test_basic_sampling_bounds_max_tokens(self) -> None:
        recorded = {}

        async def create_message(messages, **kwargs):
            recorded["kwargs"] = kwargs
            return mcp_types.CreateMessageResult(
                role="assistant",
                content=mcp_types.TextContent(type="text", text="ok"),
                model="client-model",
            )

        session = SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
        provider = McpSamplingLLMProvider(_ctx(session), max_tokens=123)

        provider.complete([{"role": "user", "content": "hi"}], "gpt-4o")
        assert recorded["kwargs"]["max_tokens"] == 123
