"""Process-based DAG executor for CPU-intensive nodes.

Uses ``concurrent.futures.ProcessPoolExecutor`` to offload heavy
computation to separate processes, while keeping the asyncio event loop
responsive.

.. note::

    For finer control, use the per-node ``executor="process"`` hint with
    the standard ``AsyncExecutor`` instead. ``ProcessExecutor`` is a
    convenience that forces **all** sync nodes into the process pool.

Example::

    executor = ProcessExecutor(pipeline, max_workers=4)
    result = await executor.execute(data=large_dataframe)
"""

from __future__ import annotations

import logging

from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.cache import CacheManager
from dagloom.scheduler.checkpoint import CheckpointManager
from dagloom.scheduler.executor import AsyncExecutor, NodeHook

logger = logging.getLogger(__name__)


class ProcessExecutor(AsyncExecutor):
    """DAG executor that uses a process pool for **all** sync nodes.

    Inherits from ``AsyncExecutor`` and sets ``max_process_workers``
    so that every synchronous node function is dispatched to a
    ``ProcessPoolExecutor``.  Async (coroutine) nodes are still
    awaited directly on the event loop.

    For per-node control, use ``@node(executor="process")`` with the
    standard ``AsyncExecutor`` instead.

    Args:
        pipeline: The pipeline to execute.
        max_workers: Maximum number of worker processes.
        retry_base_delay: Base delay for exponential backoff retries.
        retry_max_delay: Maximum retry delay cap.
        cache_manager: Optional cache manager for node output caching.
        checkpoint_manager: Optional checkpoint manager for resume support.
        on_node_start: Optional pre-execution hook.
        on_node_end: Optional post-execution hook.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        max_workers: int | None = None,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 30.0,
        cache_manager: CacheManager | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        on_node_start: NodeHook | None = None,
        on_node_end: NodeHook | None = None,
    ) -> None:
        # Mark all sync nodes as "process" so AsyncExecutor dispatches them.
        for node_obj in pipeline.nodes.values():
            if node_obj.executor == "auto":
                node_obj.executor = "process"

        super().__init__(
            pipeline,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
            cache_manager=cache_manager,
            checkpoint_manager=checkpoint_manager,
            max_process_workers=max_workers,
            on_node_start=on_node_start,
            on_node_end=on_node_end,
        )
