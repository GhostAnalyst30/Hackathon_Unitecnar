"""Broker simple de eventos en memoria para SSE (progreso del pipeline)."""

import asyncio
import json


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


broker = EventBroker()


def publish_document_event(document_id: str, status: str, **extra) -> None:
    broker.publish({"type": "document", "document_id": document_id, "status": status, **extra})
