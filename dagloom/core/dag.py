"""DAG validation and topological sort utilities.

Provides cycle detection and layered topological sorting for the Pipeline
execution scheduler.
"""

from __future__ import annotations

from typing import Any

import networkx as nx


class CycleError(Exception):
    """Raised when a cycle is detected in the pipeline DAG."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        cycle_path = " -> ".join(cycle)
        super().__init__(f"Cycle detected in DAG: {cycle_path}")


def build_digraph(
    nodes: dict[str, Any],
    edges: list[tuple[str, str]],
) -> nx.DiGraph:
    """Build a NetworkX directed graph from nodes and edges.

    Args:
        nodes: Mapping of node name to node object.
        edges: List of (source, target) edge tuples.

    Returns:
        A ``networkx.DiGraph`` instance.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes.keys())
    graph.add_edges_from(edges)
    return graph


def validate_dag(graph: nx.DiGraph) -> None:
    """Validate that the graph is a DAG (no cycles).

    Args:
        graph: A ``networkx.DiGraph`` to validate.

    Raises:
        CycleError: If a cycle is detected.
    """
    if not nx.is_directed_acyclic_graph(graph):
        # Find one cycle for a helpful error message.
        cycle = nx.find_cycle(graph, orientation="original")
        cycle_nodes = [edge[0] for edge in cycle] + [cycle[-1][1]]
        raise CycleError(cycle_nodes)


def topological_sort(graph: nx.DiGraph) -> list[str]:
    """Return nodes in topological order.

    Args:
        graph: A validated DAG (``networkx.DiGraph``).

    Returns:
        A list of node names in topological order.
    """
    return list(nx.topological_sort(graph))


def topological_layers(graph: nx.DiGraph) -> list[list[str]]:
    """Return nodes grouped by execution layer.

    Nodes in the same layer have no dependencies on each other and can
    be executed in parallel.

    Args:
        graph: A validated DAG (``networkx.DiGraph``).

    Returns:
        A list of layers, where each layer is a list of node names.
    """
    return [list(layer) for layer in nx.topological_generations(graph)]


def find_root_nodes(graph: nx.DiGraph) -> list[str]:
    """Find all root nodes (nodes with no incoming edges).

    Args:
        graph: A ``networkx.DiGraph``.

    Returns:
        A list of node names that have zero in-degree.
    """
    return [n for n, d in graph.in_degree() if d == 0]


def find_leaf_nodes(graph: nx.DiGraph) -> list[str]:
    """Find all leaf nodes (nodes with no outgoing edges).

    Args:
        graph: A ``networkx.DiGraph``.

    Returns:
        A list of node names that have zero out-degree.
    """
    return [n for n, d in graph.out_degree() if d == 0]
