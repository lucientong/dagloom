"""Dagloom — A lightweight pipeline/workflow engine.

Like a loom weaving threads into fabric, Dagloom weaves data processing
nodes into DAG workflows. Define nodes with decorators, connect them with
the >> operator, visualize and edit in a drag-and-drop Web UI.

Example::

    from dagloom import node, Pipeline

    @node
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    @node
    def shout(message: str) -> str:
        return message.upper()

    pipeline = greet >> shout
    result = pipeline.run(name="World")
"""

__version__ = "0.3.0"

from dagloom.core.context import ExecutionContext, NodeStatus
from dagloom.core.dag import CycleError
from dagloom.core.node import Branch, Node, node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.cache import CacheManager
from dagloom.scheduler.checkpoint import CheckpointManager
from dagloom.scheduler.executor import AsyncExecutor, ExecutionError

__all__ = [
    "AsyncExecutor",
    "Branch",
    "CacheManager",
    "CheckpointManager",
    "CycleError",
    "ExecutionContext",
    "ExecutionError",
    "Node",
    "NodeStatus",
    "Pipeline",
    "__version__",
    "node",
]
