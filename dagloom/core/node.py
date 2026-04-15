"""Node definition and @node decorator.

A Node wraps a plain Python function, adding metadata for retry, caching,
and timeout. Nodes are the atomic units of a Dagloom pipeline.

Example::

    @node
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    @node(retry=3, cache=True, timeout=30.0)
    def fetch_data(url: str) -> pd.DataFrame:
        return pd.read_csv(url)
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, overload

if TYPE_CHECKING:
    from dagloom.core.pipeline import Pipeline

F = TypeVar("F", bound=Callable[..., Any])

# Valid executor hint values.
EXECUTOR_HINTS = frozenset({"auto", "async", "process"})


class Branch:
    """A group of mutually exclusive Node alternatives.

    Created via the ``|`` operator::

        branch = validate_a | validate_b | validate_c

    When a ``Branch`` is connected to a pipeline with ``>>``, the
    runtime selects **one** branch to execute based on the upstream
    output:

    * If the upstream output is a *dict* containing a ``"branch"`` key,
      its value is used to look up the branch node by name.
    * If the upstream output is *truthy*, the first branch is executed;
      otherwise the second branch is executed (for two-branch groups).
    * For any other case the first branch is used as a default.

    Attributes:
        nodes: List of Node objects forming the branch alternatives.
    """

    def __init__(self, nodes: list[Node]) -> None:
        self.nodes = list(nodes)

    def __or__(self, other: Node | Branch) -> Branch:
        """Add another alternative: ``branch | node``."""
        if isinstance(other, Node):
            return Branch([*self.nodes, other])
        if isinstance(other, Branch):
            return Branch([*self.nodes, *other.nodes])
        return NotImplemented

    def __ror__(self, other: Any) -> Branch:
        if isinstance(other, Node):
            return Branch([other, *self.nodes])
        return NotImplemented

    def __repr__(self) -> str:
        names = " | ".join(n.name for n in self.nodes)
        return f"Branch({names})"


class Node:
    """A decorated Python function that serves as a DAG node.

    Attributes:
        name: Unique identifier derived from the wrapped function name.
        fn: The original callable.
        retry: Number of retries on failure (0 means no retry).
        cache: Whether to cache the node output based on input hash.
        timeout: Maximum execution time in seconds (None means no limit).
        executor: Execution strategy hint — ``"auto"`` (default) uses threads
            for sync functions and ``await`` for async; ``"process"`` dispatches
            to a ``ProcessPoolExecutor``; ``"async"`` always uses asyncio.
        description: Human-readable description from the function docstring.
    """

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        retry: int = 0,
        cache: bool = False,
        timeout: float | None = None,
        executor: str = "auto",
        description: str = "",
    ) -> None:
        if executor not in EXECUTOR_HINTS:
            raise ValueError(
                f"Invalid executor hint {executor!r}. "
                f"Choose from: {', '.join(sorted(EXECUTOR_HINTS))}"
            )
        self.name = name
        self.fn = fn
        self.retry = retry
        self.cache = cache
        self.timeout = timeout
        self.executor = executor
        self.description = description
        self._metadata: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the wrapped function directly."""
        return self.fn(*args, **kwargs)

    def __rshift__(self, other: Node | Branch | Pipeline) -> Pipeline:
        """Build a pipeline: ``node_a >> node_b``, ``node_a >> branch``, or
        ``node_a >> pipeline``.

        Args:
            other: The next Node, Branch, or an existing Pipeline to append to.

        Returns:
            A new Pipeline containing the connection.

        Raises:
            TypeError: If *other* is not a Node, Branch, or Pipeline.
        """
        from dagloom.core.pipeline import Pipeline

        if isinstance(other, Node):
            pipe = Pipeline()
            pipe.add_node(self)
            pipe.add_node(other)
            pipe.add_edge(self.name, other.name)
            pipe._tail_nodes = [other.name]
            return pipe

        if isinstance(other, Branch):
            pipe = Pipeline()
            pipe.add_node(self)
            pipe._tail_nodes = [self.name]
            return pipe >> other

        if isinstance(other, Pipeline):
            pipe = other.copy()
            pipe.add_node(self)
            # Connect self to all root nodes (nodes with no incoming edges).
            for root in pipe.root_nodes():
                pipe.add_edge(self.name, root)
            return pipe

        return NotImplemented

    def __rrshift__(self, other: Any) -> Pipeline:
        """Support ``other >> self`` when *other* does not implement __rshift__."""
        if isinstance(other, Node):
            return other.__rshift__(self)
        return NotImplemented

    def __or__(self, other: Node | Branch) -> Branch:
        """Create a conditional branch: ``node_a | node_b``.

        Args:
            other: Another Node or an existing Branch to combine with.

        Returns:
            A ``Branch`` containing both alternatives.
        """
        if isinstance(other, Node):
            return Branch([self, other])
        if isinstance(other, Branch):
            return Branch([self, *other.nodes])
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented
        return self.name == other.name

    def __repr__(self) -> str:
        parts = [f"Node({self.name!r}"]
        if self.retry:
            parts.append(f"retry={self.retry}")
        if self.cache:
            parts.append(f"cache={self.cache}")
        if self.timeout is not None:
            parts.append(f"timeout={self.timeout}")
        if self.executor != "auto":
            parts.append(f"executor={self.executor!r}")
        return ", ".join(parts) + ")"

    @property
    def input_params(self) -> dict[str, inspect.Parameter]:
        """Return the function's input parameters (excluding 'return')."""
        sig = inspect.signature(self.fn)
        return dict(sig.parameters)

    @property
    def return_annotation(self) -> Any:
        """Return the function's return type annotation."""
        sig = inspect.signature(self.fn)
        return sig.return_annotation


# ---------------------------------------------------------------------------
# @node decorator — supports both @node and @node(retry=3, cache=True)
# ---------------------------------------------------------------------------


@overload
def node(fn: F, /) -> Node: ...


@overload
def node(
    *,
    retry: int = 0,
    cache: bool = False,
    timeout: float | None = None,
    executor: str = "auto",
    name: str | None = None,
) -> Callable[[F], Node]: ...


def node(
    fn: F | None = None,
    /,
    *,
    retry: int = 0,
    cache: bool = False,
    timeout: float | None = None,
    executor: str = "auto",
    name: str | None = None,
) -> Node | Callable[[F], Node]:
    """Decorator that turns a plain Python function into a pipeline Node.

    Can be used with or without arguments::

        @node
        def step_a(x: int) -> int:
            return x + 1

        @node(retry=3, cache=True, executor="process")
        def step_b(x: int) -> int:
            return x * 2

    Args:
        fn: The function to wrap (when used without parentheses).
        retry: Number of retries on failure.
        cache: Whether to cache the output.
        timeout: Max execution time in seconds.
        executor: Execution strategy — ``"auto"`` (default), ``"process"``
            (runs in a separate process), or ``"async"`` (always asyncio).
        name: Override the node name (defaults to ``fn.__name__``).

    Returns:
        A ``Node`` instance (bare decorator) or a decorator factory.
    """
    import functools

    def _wrap(func: F) -> Node:
        node_name = name if name is not None else func.__name__
        description = (func.__doc__ or "").strip().split("\n")[0]

        wrapped = Node(
            name=node_name,
            fn=func,
            retry=retry,
            cache=cache,
            timeout=timeout,
            executor=executor,
            description=description,
        )
        functools.update_wrapper(wrapped, func)
        return wrapped

    # Bare decorator: @node
    if fn is not None:
        return _wrap(fn)

    # Decorator factory: @node(retry=3, cache=True)
    return _wrap
