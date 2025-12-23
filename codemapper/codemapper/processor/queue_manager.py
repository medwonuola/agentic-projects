import asyncio
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkItem:
    path: Path
    priority: int = 0

    def __lt__(self, other: "WorkItem") -> bool:
        return self.priority < other.priority


class WorkQueue:
    def __init__(self, concurrency: int = 2) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, WorkItem]] = asyncio.PriorityQueue()
        self._in_progress: set[Path] = set()
        self._concurrency = concurrency

    def add(self, path: Path, priority: int = 0) -> None:
        if path not in self._in_progress:
            item = WorkItem(path=path, priority=priority)
            self._queue.put_nowait((priority, item))

    async def process(self, handler: Callable[[Path], Awaitable[None]]) -> int:
        tasks: set[asyncio.Task[None]] = set()
        processed = 0

        async def worker() -> None:
            nonlocal processed
            while True:
                try:
                    _, item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._in_progress.add(item.path)
                try:
                    await handler(item.path)
                    processed += 1
                finally:
                    self._in_progress.discard(item.path)
                    self._queue.task_done()

        for _ in range(self._concurrency):
            task = asyncio.create_task(worker())
            tasks.add(task)

        await asyncio.gather(*tasks)
        return processed

    def size(self) -> int:
        return self._queue.qsize()

    def is_empty(self) -> bool:
        return self._queue.empty()
