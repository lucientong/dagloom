"""Pipeline class — a DAG of connected Nodes.

A Pipeline maintains the graph structure (adjacency list), validates
the DAG, and orchestrates synchronous execution of nodes in topological
order.

Example::

    from dagloom import node, Pipeline

    @node
    def a(x: int) -> int:
        return x + 1

    @node
    def b(x: int) -> int:
        return x * 2

    pipeline = a >> b
    result = pipeline.run(x=1)  # b(a(1)) -> (1+1)*2 = 4
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.core.context import ExecutionContext
from dagloom.core.dag import (
    build_digraph,
    find_leaf_nodes,
    find_root_nodes,
    topological_sort,
    validate_dag,
)
from dagloom.core.node import Node

logger = logging.getLogger(__name__)


class Pipeline:
    """A DAG of connected Nodes.

    Attributes:
        name: Human-readable pipeline name.
        nodes: Registry mapping node name to Node object.
        edges: List of (source, target) tuples.
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._nodes: dict[str, Node] = {}
        self._edges: list[tuple[str, str]] = []
        # Track the "tail" nodes of the latest chain for >> operator.
        self._tail_nodes: list[str] = []

    # -- Graph construction --------------------------------------------------

    def add_node(self, node: Node) -> None:
        """Register a node in the pipeline.

        Args:
            node: The Node to add. If a node with the same name already
                  exists, it is silently skipped (idempotent).
        """
        if node.name not in self._nodes:
            self._nodes[node.name] = node

    def add_edge(self, source: str, target: str) -> None:
        """Add a directed edge from *source* to *target*.

        Args:
            source: Name of the upstream node.
            target: Name of the downstream node.

        Raises:
            ValueError: If either node has not been added yet.
        """
        if source not in self._nodes:
            raise ValueError(f"Source node {source!r} not found in pipeline.")
        if target not in self._nodes:
            raise ValueError(f"Target node {target!r} not found in pipeline.")

        edge = (source, target)
        if edge not in self._edges:
            self._edges.append(edge)

    # -- Operator overloading -----------------------------------------------

    def __rshift__(self, other: Node | Pipeline) -> Pipeline:
        """Extend the pipeline: ``pipeline >> node`` or ``pipeline >> other_pipeline``.

        Args:
            other: A Node or Pipeline to connect after the current tail.

        Returns:
            This pipeline (mutated) for chaining.

        Raises:
            TypeError: If *other* is neither a Node nor a Pipeline.
        """
        if isinstance(other, Node):
            self.add_node(other)
            # Connect current tail nodes to the new node.
            for tail in self._tail_nodes:
                self.add_edge(tail, other.name)
            self._tail_nodes = [other.name]
            return self

        if isinstance(other, Pipeline):
            # Merge the other pipeline into this one.
            for node in other._nodes.values():
                self.add_node(node)
            for edge in other._edges:
                self.add_edge(edge[0], edge[1])
            # Connect current tails to other's root nodes.
            other_roots = other.root_nodes()
            for tail in self._tail_nodes:
                for root in other_roots:
                    self.add_edge(tail, root)
            self._tail_nodes = other._tail_nodes or other.leaf_nodes()
            return self

        return NotImplemented

    def __rrshift__(self, other: Any) -> Pipeline:
        """Support ``node >> pipeline``."""
        if isinstance(other, Node):
            self.add_node(other)
            for root in self.root_nodes():
                self.add_edge(other.name, root)
            return self
        return NotImplemented

    # -- Graph queries -------------------------------------------------------

    @property
    def nodes(self) -> dict[str, Node]:
        """Return a copy of the node registry."""
        return dict(self._nodes)

    @property
    def edges(self) -> list[tuple[str, str]]:
        """Return a copy of the edge list."""
        return list(self._edges)

    @property
    def graph(self) -> dict[str, list[str]]:
        """Return the adjacency list representation."""
        adj: dict[str, list[str]] = {name: [] for name in self._nodes}
        for source, target in self._edges:
            adj[source].append(target)
        return adj

    def root_nodes(self) -> list[str]:
        """Return nodes with no incoming edges."""
        incoming = {target for _, target in self._edges}
        return [name for name in self._nodes if name not in incoming]

    def leaf_nodes(self) -> list[str]:
        """Return nodes with no outgoing edges."""
        outgoing = {source for source, _ in self._edges}
        return [name for name in self._nodes if name not in outgoing]

    def predecessors(self, node_name: str) -> list[str]:
        """Return direct predecessors of a node.

        Args:
            node_name: Name of the node.

        Returns:
            List of predecessor node names.
        """
        return [src for src, tgt in self._edges if tgt == node_name]

    def successors(self, node_name: str) -> list[str]:
        """Return direct successors of a node.

        Args:
            node_name: Name of the node.

        Returns:
            List of successor node names.
        """
        return [tgt for src, tgt in self._edges if src == node_name]

    # -- Validation ----------------------------------------------------------

    def validate(self) -> None:
        """Validate the pipeline DAG (check for cycles).

        Raises:
            CycleError: If a cycle is detected.
            ValueError: If the pipeline is empty.
        """
        if not self._nodes:
            raise ValueError("Pipeline is empty — no nodes added.")
        digraph = build_digraph(self._nodes, self._edges)
        validate_dag(digraph)

    # -- Execution -----------------------------------------------------------

    def run(self, **inputs: Any) -> Any:
        """Execute the pipeline synchronously in topological order.

        Root nodes receive keyword arguments from *inputs*. Each subsequent
        node receives the output of its predecessor. If a node has multiple
        predecessors, it receives a dict keyed by predecessor name.

        Args:
            **inputs: Keyword arguments passed to root nodes.

        Returns:
            The output of the leaf node. If there are multiple leaf nodes,
            returns a dict keyed by leaf node name.
        """
        self.validate()

        digraph = build_digraph(self._nodes, self._edges)
        order = topological_sort(digraph)
        roots = find_root_nodes(digraph)
        leaves = find_leaf_nodes(digraph)

        ctx = ExecutionContext(pipeline_name=self.name or "unnamed")

        for node_name in order:
            node = self._nodes[node_name]
            info = ctx.get_node_info(node_name)
            info.mark_running()

            try:
                # Determine input for this node.
                if node_name in roots:
                    result = node(**inputs)
                else:
                    preds = self.predecessors(node_name)
                    if len(preds) == 1:
                        result = node(ctx.get_output(preds[0]))
                    else:
                        # Multiple predecessors: pass dict of outputs.
                        pred_outputs = {p: ctx.get_output(p) for p in preds}
                        result = node(pred_outputs)

                ctx.set_output(node_name, result)
                info.mark_success()
                logger.debug("Node %s completed successfully.", node_name)

            except Exception as exc:
                info.mark_failed(str(exc))
                logger.error("Node %s failed: %s", node_name, exc)
                raise RuntimeError(
                    f"Pipeline execution failed at node {node_name!r}: {exc}"
                ) from exc

        # Return result.
        if len(leaves) == 1:
            return ctx.get_output(leaves[0])
        return {leaf: ctx.get_output(leaf) for leaf in leaves}

    # -- Utilities -----------------------------------------------------------

    def copy(self) -> Pipeline:
        """Create a deep copy of this pipeline."""
        new = Pipeline(name=self.name)
        new._nodes = dict(self._nodes)
        new._edges = list(self._edges)
        new._tail_nodes = list(self._tail_nodes)
        return new

    def visualize(self) -> str:
        """Return a simple text visualization of the DAG.

        Returns:
            A multi-line string showing nodes and edges.
        """
        lines = [f"Pipeline: {self.name or '(unnamed)'}"]
        lines.append(f"Nodes ({len(self._nodes)}): {', '.join(self._nodes.keys())}")
        lines.append("Edges:")
        for source, target in self._edges:
            lines.append(f"  {source} -> {target}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"Pipeline(name={self.name!r}, nodes={len(self._nodes)}, edges={len(self._edges)})"

    def __len__(self) -> int:
        return len(self._nodes)
