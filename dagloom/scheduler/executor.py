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
import time
from typing import Any

from dagloom.core.context import ExecutionContext, NodeStatus
from dagloom.core.dag import build_digraph, topological_layers, validate_dag
from dagloom.core.node import Node
from dagloom.core.pipeline import Pipeline, _select_branch
from dagloom.scheduler.cache import CacheManager, compute_input_hash
from dagloom.scheduler.checkpoint import CheckpointManager

logger = logging.getLogger(__name__)

# Type alias for hook callbacks.
NodeHook = Any  # Callable[[str, ExecutionContext], None] or async variant

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
        cache_manager: Optional cache manager for node output caching.
        checkpoint_manager: Optional checkpoint manager for resume support.
        on_node_start: Optional callback invoked before each node executes.
            Signature: ``(node_name: str, ctx: ExecutionContext) -> None``
            (may also be an async function).
        on_node_end: Optional callback invoked after each node finishes.
            Signature: ``(node_name: str, ctx: ExecutionContext) -> None``
            (may also be an async function).
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        retry_base_delay: float = _DEFAULT_RETRY_BASE_DELAY,
        retry_max_delay: float = _DEFAULT_RETRY_MAX_DELAY,
        cache_manager: CacheManager | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        on_node_start: NodeHook | None = None,
        on_node_end: NodeHook | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.cache_manager = cache_manager
        self.checkpoint_manager = checkpoint_manager
        self.on_node_start = on_node_start
        self.on_node_end = on_node_end

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
        failed_node: str | None = None
        skipped_nodes: set[str] = set()
        start_time = time.monotonic()

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
                        skipped_nodes=skipped_nodes,
                    )
                    for name in layer
                ]
                await asyncio.gather(*tasks)

                # Check for failures in this layer.
                for name in layer:
                    info = ctx.get_node_info(name)
                    if info.status == NodeStatus.FAILED:
                        raise ExecutionError(name, info.error or "unknown error")

                # --- Branch selection for this layer ---
                for name in layer:
                    if name in self.pipeline._branches and name not in skipped_nodes:
                        branch = self.pipeline._branches[name]
                        output = ctx.get_output(name)
                        selected = _select_branch(output, branch)
                        for bn in branch.nodes:
                            if bn.name != selected:
                                skipped_nodes.add(bn.name)

            if len(leaves) == 1:
                return ctx.get_output(leaves[0])
            active_leaves = [lf for lf in leaves if lf not in skipped_nodes]
            if len(active_leaves) == 1:
                return ctx.get_output(active_leaves[0])
            return {leaf: ctx.get_output(leaf) for leaf in active_leaves}

        except ExecutionError as exc:
            success = False
            failed_node = exc.node_name
            error_message = str(exc)
            raise

        except Exception as exc:
            success = False
            error_message = str(exc)
            raise

        finally:
            duration = time.monotonic() - start_time

            if ckpt is not None:
                await ckpt.finish_execution(
                    execution_id,
                    pipeline_id,
                    success=success,
                    error_message=error_message,
                )

            # --- Notification dispatch ---
            await self._send_notifications(
                pipeline_id=pipeline_id,
                execution_id=execution_id,
                success=success,
                error_message=error_message,
                failed_node=failed_node,
                duration=duration,
            )

    async def _send_notifications(
        self,
        pipeline_id: str,
        execution_id: str,
        success: bool,
        error_message: str | None,
        failed_node: str | None,
        duration: float,
    ) -> None:
        """Dispatch notifications based on ``pipeline.notify_on`` config.

        Silently logs and continues if any notification fails — never
        raises exceptions to avoid masking the original execution result.
        """
        notify_on = getattr(self.pipeline, "notify_on", None)
        if not notify_on:
            return

        from dagloom.notifications.base import ExecutionEvent
        from dagloom.notifications.registry import resolve_channel

        status = "success" if success else "failed"
        uris = notify_on.get(status, [])
        if not uris:
            return

        event = ExecutionEvent(
            pipeline_name=self.pipeline.name or "unnamed",
            pipeline_id=pipeline_id,
            execution_id=execution_id,
            status=status,
            duration_seconds=duration,
            node_count=len(self.pipeline.nodes),
            error_message=error_message,
            failed_node=failed_node,
        )

        for uri in uris:
            try:
                channel = resolve_channel(uri)
                await channel.send(event)
            except Exception:
                logger.warning(
                    "Notification to %r failed for pipeline %r.",
                    uri,
                    pipeline_id,
                    exc_info=True,
                )

    async def _execute_node(
        self,
        node_name: str,
        is_root: bool,
        inputs: dict[str, Any],
        ctx: ExecutionContext,
        execution_id: str = "",
        completed_nodes: set[str] | None = None,
        skipped_nodes: set[str] | None = None,
    ) -> None:
        """Execute a single node with retry, timeout, and cache support.

        Args:
            node_name: Name of the node to execute.
            is_root: Whether this is a root node receiving external inputs.
            inputs: External keyword arguments (for root nodes).
            ctx: The execution context.
            execution_id: The execution ID for checkpointing.
            completed_nodes: Set of already-completed node names (for resume).
            skipped_nodes: Set of nodes to skip (branch selection).
        """
        node_obj = self.pipeline.nodes[node_name]
        info = ctx.get_node_info(node_name)
        ckpt = self.checkpoint_manager
        pipeline_id = self.pipeline.name or "unnamed"

        # --- Branch: skip unselected branch nodes ---
        if skipped_nodes and node_name in skipped_nodes:
            info.mark_skipped()
            logger.debug("Node %s skipped (branch not selected).", node_name)
            return

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

        # --- Hook: on_node_start ---
        if self.on_node_start is not None:
            try:
                _rv = self.on_node_start(node_name, ctx)
                if _inspect.isawaitable(_rv):
                    await _rv
            except Exception:
                logger.warning("on_node_start hook raised for node %s.", node_name)

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

                # --- Hook: on_node_end (success) ---
                if self.on_node_end is not None:
                    try:
                        _rv = self.on_node_end(node_name, ctx)
                        if _inspect.isawaitable(_rv):
                            await _rv
                    except Exception:
                        logger.warning("on_node_end hook raised for node %s.", node_name)

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

        # --- Hook: on_node_end (after all retries exhausted) ---
        if self.on_node_end is not None:
            try:
                _rv = self.on_node_end(node_name, ctx)
                if _inspect.isawaitable(_rv):
                    await _rv
            except Exception:
                logger.warning("on_node_end hook raised for node %s.", node_name)

    @staticmethod
    async def _run_callable(node_obj: Node, *args: Any, **kwargs: Any) -> Any:
        """Run a node function, wrapping sync functions in a thread.

        Supports:
        - Coroutine functions: awaited directly.
        - Async generator functions: collected into a list.
        - Generator functions: collected into a list (via thread).
        - Regular functions: run in thread via ``asyncio.to_thread``.
        """
        # Async generator: async def ... yield ...
        if _inspect.isasyncgenfunction(node_obj.fn):
            return [item async for item in node_obj.fn(*args, **kwargs)]

        # Coroutine function: async def ... return ...
        if _inspect.iscoroutinefunction(node_obj.fn):
            return await node_obj.fn(*args, **kwargs)

        # Sync generator: def ... yield ...
        if _inspect.isgeneratorfunction(node_obj.fn):
            return await asyncio.to_thread(lambda: list(node_obj.fn(*args, **kwargs)))

        # Regular sync function.
        return await asyncio.to_thread(node_obj.fn, *args, **kwargs)
