import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ...infrastructure.events import broker

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def stream_events():
    queue = broker.subscribe()

    async def generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
