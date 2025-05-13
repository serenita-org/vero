import asyncio
import logging
from collections.abc import Coroutine
from functools import partial
from typing import Any

from observability import ErrorType, get_shared_metrics

(_ERRORS_METRIC,) = get_shared_metrics()


class TaskManager:
    def __init__(self, shutdown_event: asyncio.Event) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        self.shutdown_event = shutdown_event

        # asyncio tasks - we store references to them here to prevent them
        #  from being garbage collected
        self._tasks: set[asyncio.Task[Any]] = set()

    def _log_task_exception(self, task: asyncio.Task[Any]) -> None:
        try:
            # Re-raise the exception to get a nice traceback
            task.result()
        except Exception as e:
            self.logger.error(
                f"Task {task} failed with exception {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            _ERRORS_METRIC.labels(error_type=ErrorType.OTHER.value).inc()

    def task_done_callback(self, task: asyncio.Task[Any]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            if not self.shutdown_event.is_set():
                # Log cancellations as errors only if we're not shutting down
                self.logger.error(
                    f"Task {task} was cancelled",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )
                _ERRORS_METRIC.labels(error_type=ErrorType.OTHER.value).inc()
        else:
            if exc is not None:
                self._log_task_exception(task)
        finally:
            # Remove the task from the set once it's done
            self._tasks.discard(task)

    def submit_task(
        self,
        coro: Coroutine[Any, Any, None],
        delay: float = 0.0,
        name: str | None = None,
    ) -> None:
        """Create and track a task from the given coroutine."""
        if self.shutdown_event.is_set():
            self.logger.debug(f"Cancelling task {name!r}, shutting down...")
            asyncio.create_task(coro).cancel()
            return

        async def _delayed_coro() -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            await coro

        task: asyncio.Task[None] = asyncio.create_task(_delayed_coro(), name=name)
        task.add_done_callback(partial(self.task_done_callback))
        self._tasks.add(task)

    def cancel_all(self) -> None:
        for task in self._tasks:
            task.cancel()
