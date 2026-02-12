from __future__ import annotations

import asyncio
from typing import Any, Optional


def send_custom(
    session,
    msg_type: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """Safely dispatch send_custom_message from any context.

    Uses asyncio.create_task when in an event loop, otherwise schedules onto
    the provided loop (or the current loop) with call_soon_threadsafe.
    """
    if payload is None:
        payload = {}
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if loop is None:
            loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(lambda: asyncio.create_task(session.send_custom_message(msg_type, payload)))
        return
    asyncio.create_task(session.send_custom_message(msg_type, payload))
