"""Close the lead's event stream when its browser connection ends."""

from collections.abc import AsyncIterator
from typing import Any

from anyio import CancelScope
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from starlette.responses import StreamingResponse
from starlette.types import Send


async def _close(iterator: AsyncIterator) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


class _ChatResponse(StreamingResponse):
    def __init__(self, content, *, events: AsyncIterator, **kwargs):
        super().__init__(content, **kwargs)
        self.events = events

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            # A disconnect can interrupt ASGI send while both generators are suspended
            # at yield. Closing only the encoder does not close its upstream iterator.
            # Shield teardown from Starlette's cancelled disconnect task group.
            with CancelScope(shield=True):
                try:
                    await _close(self.events)
                finally:
                    await _close(self.body_iterator)


class ChatAdapter(VercelAIAdapter):
    def streaming_response(self, stream: AsyncIterator[Any]) -> StreamingResponse:
        events = self.build_event_stream()
        return _ChatResponse(
            events.encode_stream(stream), events=stream,
            headers=events.response_headers, media_type=events.content_type,
        )
