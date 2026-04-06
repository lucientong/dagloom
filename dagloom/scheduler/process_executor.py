"""Process-based DAG executor for CPU-intensive nodes.

Uses ``concurrent.futures.ProcessPoolExecutor`` to offload heavy
computation to separate processes, while keeping the asyncio event loop
responsive.

Example::

    executor = ProcessExecutor(pipeline, max_workers=4)
    result = await executor.execute(data=large_dataframe)
"""

from __future__ import annotations

import asyncio
import inspect as _inspect
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from dagloom.core.node import Node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.executor import AsyncExecutor

logger = logging.getLogger(__name__)


def _run_in_process(fn: Any, args: tuple, kwargs: dict) -> Any:
    """Top-level function that can be pickled for process pool execution."""
    return fn(*args, **kwargs)


class ProcessExecutor(AsyncExecutor):
    """DAG executor that uses a process pool for CPU-bound nodes.

    Inherits from ``AsyncExecutor`` but overrides the callable runner
    to dispatch synchronous node functions to a ``ProcessPoolExecutor``.

    Args:
        pipeline: The pipeline to execute.
        max_workers: Maximum number of worker processes.
        retry_base_delay: Base delay for exponential backoff retries.
        retry_max_delay: Maximum retry delay cap.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        max_workers: int | None = None,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 30.0,
    ) -> None:
        super().__init__(
            pipeline,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )
        self.max_workers = max_workers
        self._pool: ProcessPoolExecutor | None = None

    async def execute(self, **inputs: Any) -> Any:
        """Run the pipeline with a process pool for CPU-bound nodes.

        The process pool is created on entry and shut down on exit.

        Args:
            **inputs: Keyword arguments passed to root nodes.

        Returns:
            The output of the leaf node(s).
        """
        self._pool = ProcessPoolExecutor(max_workers=self.max_workers)
        try:
            return await super().execute(**inputs)
        finally:
            self._pool.shutdown(wait=False)
            self._pool = None

    async def _run_callable(self, node_obj: Node, *args: Any, **kwargs: Any) -> Any:
        """Run a node function in a process or thread.

        - Coroutine functions are awaited directly (they use asyncio).
        - Synchronous functions are dispatched to the process pool.
        """
        if _inspect.iscoroutinefunction(node_obj.fn):
            return await node_obj.fn(*args, **kwargs)

        if self._pool is not None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._pool,
                _run_in_process,
                node_obj.fn,
                args,
                kwargs,
            )

        # Fallback to thread if pool is somehow unavailable.
        return await asyncio.to_thread(node_obj.fn, *args, **kwargs)
