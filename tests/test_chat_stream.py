"""A disconnected browser must not leave the lead or provider stream running."""

import asyncio
import inspect
import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.durable_exec.temporal import TemporalDurability
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from starlette.requests import ClientDisconnect, Request

from vis_agent.chat_stream import ChatAdapter


def scope(version="2.4"):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": version},
        "http_version": "1.1", "method": "POST", "path": "/api/chat", "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }


def body():
    return json.dumps({
        "id": "stream-test", "trigger": "submit-message",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "hello"}]}],
    }).encode()


def run(awaitable):
    return asyncio.run(awaitable)


class RecordingSpans(SpanProcessor):
    def __init__(self):
        self.started, self.finished = {}, {}

    def on_start(self, span, parent_context=None):
        self.started[span.get_span_context().span_id] = span.name

    def on_end(self, span):
        self.finished[span.context.span_id] = span

    def assert_closed(self):
        assert any("vis-lead" in name for name in self.started.values())
        assert any(name.startswith("chat ") for name in self.started.values())
        assert self.started.keys() == self.finished.keys(), self.started
        assert all(span.end_time is not None for span in self.finished.values())


def instrumented_agent(model_stream):
    provider, spans = TracerProvider(), RecordingSpans()
    provider.add_span_processor(spans)
    agent = Agent(
        FunctionModel(stream_function=model_stream), name="vis-lead",
        capabilities=[TemporalDurability(), Instrumentation(InstrumentationSettings(tracer_provider=provider))],
    )
    return agent, provider, spans


@pytest.mark.parametrize("failure", ["send_error", "disconnect", "cancel"])
@pytest.mark.parametrize("boundary", ["text-delta", "text-end", "finish"])
def test_abandoned_http_stream_closes_model_and_background_run(failure, boundary):
    async def scenario():
        model_closed, sent_text = asyncio.Event(), asyncio.Event()
        requests = []

        async def model_stream(messages, info):
            requests.append(1)
            try:
                yield "The visible answer is ready."
                if boundary == "text-delta":
                    await asyncio.Event().wait()  # Provider is still waiting for a trailing chunk.
            finally:
                model_closed.set()

        agent, provider, spans = instrumented_agent(model_stream)
        initial_body = True

        async def receive():
            nonlocal initial_body
            if initial_body:
                initial_body = False
                return {"type": "http.request", "body": body(), "more_body": False}
            await sent_text.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if f'"type":"{boundary}"'.encode() in message.get("body", b""):
                sent_text.set()
                if failure == "send_error":
                    raise OSError("The browser closed the connection")
                await asyncio.Event().wait()  # Disconnect/cancel while ASGI send has backpressure.

        request_scope = scope("2.0" if failure == "disconnect" else "2.4")
        response = await ChatAdapter.dispatch_request(Request(request_scope, receive), agent=agent, sdk_version=7)
        before = set(asyncio.all_tasks())
        serving = asyncio.create_task(response(request_scope, receive, send))
        await asyncio.wait_for(sent_text.wait(), timeout=2)
        if failure == "cancel":
            serving.cancel()
            with pytest.raises(asyncio.CancelledError):
                await serving
        elif failure == "send_error":
            with pytest.raises(ClientDisconnect):
                await serving
        else:
            await asyncio.wait_for(serving, timeout=2)
        # Cleanup is awaited before HTTP handling returns, not deferred until garbage collection.
        assert model_closed.is_set()
        assert requests == [1]
        spans.assert_closed()
        remaining = [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        # Exiting an exhausted UI protocol hook can schedule CPython asyncgen finalizers.
        # The provider, agent and capability coroutine tasks must already have ended.
        running = [task for task in remaining if inspect.iscoroutine(task.get_coro())]
        assert not running, [repr(task) for task in running]
        if remaining:
            await asyncio.wait_for(asyncio.gather(*remaining), timeout=1)
        assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        provider.shutdown()

    run(scenario())


def test_completed_http_stream_keeps_the_final_answer_and_closes_once():
    async def scenario():
        closed, chunks = [], []

        async def model_stream(messages, info):
            try:
                yield "A complete answer."
            finally:
                closed.append(True)

        async def receive():
            return {"type": "http.request", "body": body(), "more_body": False}

        async def send(message):
            chunks.append(message.get("body", b""))

        agent, provider, spans = instrumented_agent(model_stream)
        request_scope = scope()
        response = await ChatAdapter.dispatch_request(Request(request_scope, receive), agent=agent, sdk_version=7)
        before = set(asyncio.all_tasks())
        await response(request_scope, receive, send)
        output = b"".join(chunks)
        assert b"A complete answer." in output and b'"type":"finish"' in output
        assert b"[DONE]" in output and closed == [True]
        assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        spans.assert_closed()
        provider.shutdown()

    run(scenario())
