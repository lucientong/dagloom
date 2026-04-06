"""Async DAG executor.

Executes pipeline nodes in topological order, running independent nodes
in the same layer concurrently via ``asyncio.gather``.  Supports per-node
timeout and exponential-backoff retry.

Example::

    executor = AsyncExecutor(pipeline)
    result = await executor.execute(url="https://example.com/data.csv")
"""

from __future__ import annotations

import asyncio
import inspect as _inspect
import logging
from typing import Any

from dagloom.core.context import ExecutionContext, NodeStatus
from dagloom.core.dag import build_digraph, topological_layers, validate_dag
from dagloom.core.node import Node
from dagloom.core.pipeline import Pipeline

logger = logging.getLogger(__name__)

# Default retry parameters
_DEFAULT_RETRY_BASE_DELAY = 0.5  # seconds
_DEFAULT_RETRY_MAX_DELAY = 30.0  # seconds
_DEFAULT_RETRY_MULTIPLIER = 2.0


class ExecutionError(Exception):
    """Raised when pipeline execution fails."""

    def __init__(self, node_name: str, message: str) -> None:
        self.node_name = node_name
        super().__init__(f"Node {node_name!r} failed: {message}")


class AsyncExecutor:
    """Execute a pipeline DAG using asyncio.

    Nodes are grouped into layers by topological sort.  All nodes in a
    layer are independent of each other and execute concurrently via
    ``asyncio.gather``.

    Args:
        pipeline: The pipeline to execute.
        retry_base_delay: Base delay in seconds for exponential backoff.
        retry_max_delay: Maximum delay cap for retries.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        retry_base_delay: float = _DEFAULT_RETRY_BASE_DELAY,
        retry_max_delay: float = _DEFAULT_RETRY_MAX_DELAY,
    ) -> None:
        self.pipeline = pipeline
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

    async def execute(self, **inputs: Any) -> Any:
        """Run the pipeline asynchronously.

        Args:
            **inputs: Keyword arguments passed to root nodes.

        Returns:
            The output of the leaf node(s).

        Raises:
            ExecutionError: If any node fails after all retries.
        """
        self.pipeline.validate()

        digraph = build_digraph(self.pipeline.nodes, self.pipeline.edges)
        validate_dag(digraph)
        layers = topological_layers(digraph)
        roots = set(self.pipeline.root_nodes())
        leaves = self.pipeline.leaf_nodes()

        ctx = ExecutionContext(pipeline_name=self.pipeline.name or "unnamed")

        for layer_idx, layer in enumerate(layers):
            logger.debug(
                "Executing layer %d/%d: %s",
                layer_idx + 1,
                len(layers),
                layer,
            )
            tasks = [
                self._execute_node(
                    node_name=name,
                    is_root=name in roots,
                    inputs=inputs,
                    ctx=ctx,
                )
                for name in layer
            ]
            await asyncio.gather(*tasks)

            # Check for failures in this layer.
            for name in layer:
                info = ctx.get_node_info(name)
                if info.status == NodeStatus.FAILED:
                    raise ExecutionError(name, info.error or "unknown error")

        if len(leaves) == 1:
            return ctx.get_output(leaves[0])
        return {leaf: ctx.get_output(leaf) for leaf in leaves}

    async def _execute_node(
        self,
        node_name: str,
        is_root: bool,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
    ) -> None:
        """Execute a single node with retry and timeout.

        Args:
            node_name: Name of the node to execute.
            is_root: Whether this is a root node receiving external inputs.
            inputs: External keyword arguments (for root nodes).
            ctx: The execution context.
        """
        node_obj = self.pipeline.nodes[node_name]
        info = ctx.get_node_info(node_name)
        max_attempts = node_obj.retry + 1

        for attempt in range(1, max_attempts + 1):
            info.mark_running()
            info.retry_count = attempt - 1

            try:
                # Determine input for this node.
                if is_root:
                    node_input = inputs
                    coro = self._run_callable(node_obj, **node_input)
                else:
                    preds = self.pipeline.predecessors(node_name)
                    if len(preds) == 1:
                        coro = self._run_callable(node_obj, ctx.get_output(preds[0]))
                    else:
                        pred_outputs = {p: ctx.get_output(p) for p in preds}
                        coro = self._run_callable(node_obj, pred_outputs)

                # Apply timeout if configured.
                if node_obj.timeout is not None:
                    result = await asyncio.wait_for(coro, timeout=node_obj.timeout)
                else:
                    result = await coro

                ctx.set_output(node_name, result)
                info.mark_success()
                logger.debug(
                    "Node %s succeeded (attempt %d/%d).",
                    node_name,
                    attempt,
                    max_attempts,
                )
                return

            except TimeoutError:
                error_msg = (
                    f"Timed out after {node_obj.timeout}s (attempt {attempt}/{max_attempts})"
                )
                logger.warning("Node %s: %s", node_name, error_msg)
                info.mark_failed(error_msg)

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc} (attempt {attempt}/{max_attempts})"
                logger.warning("Node %s: %s", node_name, error_msg)
                info.mark_failed(str(exc))

            # Retry with exponential backoff (unless last attempt).
            if attempt < max_attempts:
                delay = min(
                    self.retry_base_delay * (_DEFAULT_RETRY_MULTIPLIER ** (attempt - 1)),
                    self.retry_max_delay,
                )
                logger.debug("Node %s retrying in %.1fs ...", node_name, delay)
                await asyncio.sleep(delay)

    @staticmethod
    async def _run_callable(node_obj: Node, *args: Any, **kwargs: Any) -> Any:
        """Run a node function, wrapping sync functions in a thread.

        If the node function is a coroutine function, it is awaited
        directly.  Otherwise it is run in the default executor via
        ``asyncio.to_thread``.
        """
        if _inspect.iscoroutinefunction(node_obj.fn):
            return await node_obj.fn(*args, **kwargs)
        return await asyncio.to_thread(node_obj.fn, *args, **kwargs)
