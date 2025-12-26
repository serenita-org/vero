import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from observability import ErrorType, Metrics

if TYPE_CHECKING:
    from collections.abc import Coroutine


class TaskManager:
    def __init__(self, shutdown_event: asyncio.Event, metrics: Metrics) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = metrics

        self.shutdown_event = shutdown_event

        # asyncio tasks - we store references to them here to prevent them
        #  from being garbage collected
        self._tasks: set[asyncio.Task[Any]] = set()

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        try:
            # Re-raise the exception to get a nice traceback
            task.result()
        except Exception as e:
            self.logger.exception(
                f"Task {task} failed with exception {e!r}",
            )
            self.metrics.errors_c.labels(error_type=ErrorType.OTHER.value).inc()

    def task_done_callback(self, task: asyncio.Task[Any]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            if not self.shutdown_event.is_set():
                # Log cancellations as errors only if we're not shutting down
                self.logger.exception(
                    f"Task {task} was cancelled",
                )
                self.metrics.errors_c.labels(error_type=ErrorType.OTHER.value).inc()
        else:
            if exc is not None:
                self._log_task_exception(task)
        finally:
            # Remove the task from the set once it's done
            self._tasks.discard(task)

    def create_task(
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
        self.add_existing_task(task=task)

    def add_existing_task(
        self,
        task: asyncio.Task[Any],
    ) -> None:
        """Track an existing task, ensuring it is not garbage collected."""
        if self.shutdown_event.is_set():
            self.logger.debug(f"Cancelling task {task}, shutting down...")
            task.cancel()
            return

        task.add_done_callback(partial(self.task_done_callback))
        self._tasks.add(task)

    def cancel_all(self) -> None:
        for task in self._tasks:
            task.cancel()
