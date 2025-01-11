import asyncio
import logging
from collections.abc import Coroutine
from functools import partial
from typing import Any

from observability import ErrorType, get_shared_metrics

(_ERRORS_METRIC,) = get_shared_metrics()


class TaskManager:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        # asyncio tasks - we store references to them here to prevent them
        #  from being garbage collected
        self._tasks: set[asyncio.Task[Any]] = set()

    def task_done_callback(self, task: asyncio.Task[Any]) -> None:
        if task.exception():
            try:
                # Re-raise the exception to get a nice traceback
                task.result()
            except Exception as e:
                self.logger.error(
                    f"Task {task} failed with exception {e!r}",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )
                _ERRORS_METRIC.labels(error_type=ErrorType.OTHER.value).inc()

        # Remove the task from the set once it's done
        self._tasks.discard(task)

    def submit_task(
        self,
        coro: Coroutine[Any, Any, None],
        delay: float = 0.0,
        name: str | None = None,
    ) -> None:
        """Create and track a task from the given coroutine."""

        async def _delayed_coro() -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            await coro

        task: asyncio.Task[None] = asyncio.create_task(_delayed_coro(), name=name)
        task.add_done_callback(partial(self.task_done_callback))
        self._tasks.add(task)
