from __future__ import annotations

import asyncio

from chipevolve.domain.models import EvolutionEvent


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[EvolutionEvent]] = set()

    async def publish(self, event: EvolutionEvent) -> None:
        for queue in tuple(self._subscribers):
            await queue.put(event)

    def subscribe(self) -> asyncio.Queue[EvolutionEvent]:
        queue: asyncio.Queue[EvolutionEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EvolutionEvent]) -> None:
        self._subscribers.discard(queue)

