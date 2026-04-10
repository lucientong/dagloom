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
from dagloom.scheduler.cache import CacheManager, compute_input_hash
from dagloom.scheduler.checkpoint import CheckpointManager

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
        cache_manager: CacheManager | None = None,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.cache_manager = cache_manager
        self.checkpoint_manager = checkpoint_manager

    async def execute(self, *, resume_id: str | None = None, **inputs: Any) -> Any:
        """Run the pipeline asynchronously.

        Args:
            resume_id: If provided, resume a previously failed execution
                       by skipping already-completed nodes.
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

        # --- Checkpoint: init ---
        ckpt = self.checkpoint_manager
        execution_id = resume_id or ctx.execution_id
        pipeline_id = self.pipeline.name or "unnamed"
        completed_nodes: set[str] = set()

        if ckpt is not None:
            if resume_id:
                completed_nodes = await ckpt.get_completed_nodes(resume_id)
            else:
                await ckpt.init_execution(execution_id, pipeline_id)

        success = True
        error_message: str | None = None

        try:
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
                        execution_id=execution_id,
                        completed_nodes=completed_nodes,
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

        except ExecutionError:
            success = False
            raise

        except Exception as exc:
            success = False
            error_message = str(exc)
            raise

        finally:
            if ckpt is not None:
                await ckpt.finish_execution(
                    execution_id,
                    pipeline_id,
                    success=success,
                    error_message=error_message,
                )

    async def _execute_node(
        self,
        node_name: str,
        is_root: bool,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        execution_id: str = "",
        completed_nodes: set[str] | None = None,
    ) -> None:
        """Execute a single node with retry, timeout, and cache support.

        Args:
            node_name: Name of the node to execute.
            is_root: Whether this is a root node receiving external inputs.
            inputs: External keyword arguments (for root nodes).
            ctx: The execution context.
            execution_id: The execution ID for checkpointing.
            completed_nodes: Set of already-completed node names (for resume).
        """
        node_obj = self.pipeline.nodes[node_name]
        info = ctx.get_node_info(node_name)
        ckpt = self.checkpoint_manager
        pipeline_id = self.pipeline.name or "unnamed"

        # --- Checkpoint: skip already completed ---
        if completed_nodes and node_name in completed_nodes:
            info.mark_skipped()
            logger.debug("Node %s skipped (already completed in checkpoint).", node_name)
            return

        max_attempts = node_obj.retry + 1

        # Resolve the arguments that will be passed to this node.
        if is_root:
            node_args: tuple[Any, ...] = ()
            node_kwargs = dict(inputs)
        else:
            preds = self.pipeline.predecessors(node_name)
            if len(preds) == 1:
                node_args = (ctx.get_output(preds[0]),)
                node_kwargs = {}
            else:
                pred_outputs = {p: ctx.get_output(p) for p in preds}
                node_args = (pred_outputs,)
                node_kwargs = {}

        # --- Cache lookup ---
        input_hash: str | None = None
        if node_obj.cache and self.cache_manager is not None:
            input_hash = compute_input_hash(*node_args, **node_kwargs)
            cached = await self.cache_manager.get(node_name, input_hash)
            if cached is not None:
                ctx.set_output(node_name, cached)
                info.mark_skipped()
                logger.debug("Node %s cache HIT (hash=%s).", node_name, input_hash[:12])
                return

        # --- Execute with retry ---
        for attempt in range(1, max_attempts + 1):
            info.mark_running()
            info.retry_count = attempt - 1

            try:
                if node_kwargs:
                    coro = self._run_callable(node_obj, *node_args, **node_kwargs)
                else:
                    coro = self._run_callable(node_obj, *node_args)

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

                # --- Checkpoint: save success ---
                if ckpt is not None:
                    await ckpt.save_state(
                        execution_id,
                        pipeline_id,
                        node_name,
                        "success",
                        input_hash=input_hash,
                        retry_count=info.retry_count,
                    )

                # --- Cache write ---
                if node_obj.cache and self.cache_manager is not None and input_hash is not None:
                    try:
                        await self.cache_manager.put(node_name, input_hash, result)
                        logger.debug("Node %s cache STORED (hash=%s).", node_name, input_hash[:12])
                    except Exception:
                        logger.warning("Node %s cache write failed, continuing.", node_name)

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

        # --- Checkpoint: save failure (all retries exhausted) ---
        if ckpt is not None and info.status == NodeStatus.FAILED:
            await ckpt.save_state(
                execution_id,
                pipeline_id,
                node_name,
                "failed",
                error_message=info.error,
                retry_count=info.retry_count,
            )

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
