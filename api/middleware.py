"""ASGI request body size limit, enforced before FastAPI parses anything."""

from __future__ import annotations

import json

BODY_MAX_BYTES = 16384


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject request bodies over ``max_bytes``: declared Content-Length gets a
    fast 413; chunked/undeclared bodies are counted as they stream and cut off
    at the cap. Runs beneath CORS so the 413 still carries CORS headers."""

    def __init__(self, app, max_bytes: int = BODY_MAX_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _send_413(self, send) -> None:
        body = json.dumps(
            {"detail": f"request body too large (max {self.max_bytes} bytes)"}
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                if declared is not None and declared > self.max_bytes:
                    await self._send_413(send)
                    return
        received = 0
        response_started = False

        async def wrapped_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def wrapped_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._send_413(send)
