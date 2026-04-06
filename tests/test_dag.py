"""Tests for DAG validation and topological sort utilities."""

import networkx as nx
import pytest

from dagloom.core.dag import (
    CycleError,
    build_digraph,
    find_leaf_nodes,
    find_root_nodes,
    topological_layers,
    topological_sort,
    validate_dag,
)


class TestBuildDigraph:
    """Test building a networkx DiGraph."""

    def test_basic_graph(self) -> None:
        nodes = {"a": None, "b": None, "c": None}
        edges = [("a", "b"), ("b", "c")]
        g = build_digraph(nodes, edges)

        assert isinstance(g, nx.DiGraph)
        assert set(g.nodes) == {"a", "b", "c"}
        assert set(g.edges) == {("a", "b"), ("b", "c")}

    def test_empty_graph(self) -> None:
        g = build_digraph({}, [])
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_disconnected_nodes(self) -> None:
        nodes = {"a": None, "b": None, "c": None}
        g = build_digraph(nodes, [])
        assert len(g.nodes) == 3
        assert len(g.edges) == 0


class TestValidateDAG:
    """Test cycle detection."""

    def test_valid_dag(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("a", "c")])
        validate_dag(g)  # Should not raise

    def test_simple_cycle(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "a")])
        with pytest.raises(CycleError) as exc_info:
            validate_dag(g)
        assert len(exc_info.value.cycle) > 0

    def test_three_node_cycle(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])
        with pytest.raises(CycleError):
            validate_dag(g)

    def test_self_loop(self) -> None:
        g = nx.DiGraph()
        g.add_edge("a", "a")
        with pytest.raises(CycleError):
            validate_dag(g)

    def test_cycle_error_message(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "a")])
        with pytest.raises(CycleError, match="Cycle detected"):
            validate_dag(g)


class TestTopologicalSort:
    """Test topological ordering."""

    def test_linear_chain(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c")])
        order = topological_sort(g)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dag(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        order = topological_sort(g)
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")


class TestTopologicalLayers:
    """Test layered topological sort for parallel execution."""

    def test_linear_chain_layers(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c")])
        layers = topological_layers(g)
        assert layers == [["a"], ["b"], ["c"]]

    def test_parallel_layer(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        layers = topological_layers(g)
        assert layers[0] == ["a"]
        assert set(layers[1]) == {"b", "c"}  # b and c can run in parallel
        assert layers[2] == ["d"]

    def test_single_node(self) -> None:
        g = nx.DiGraph()
        g.add_node("a")
        layers = topological_layers(g)
        assert layers == [["a"]]

    def test_wide_dag(self) -> None:
        """All nodes independent — single layer."""
        g = nx.DiGraph()
        g.add_nodes_from(["a", "b", "c", "d"])
        layers = topological_layers(g)
        assert len(layers) == 1
        assert set(layers[0]) == {"a", "b", "c", "d"}


class TestFindRootAndLeafNodes:
    """Test root/leaf node discovery."""

    def test_linear(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("b", "c")])
        assert find_root_nodes(g) == ["a"]
        assert find_leaf_nodes(g) == ["c"]

    def test_diamond(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        assert find_root_nodes(g) == ["a"]
        assert find_leaf_nodes(g) == ["d"]

    def test_multiple_roots_and_leaves(self) -> None:
        g = nx.DiGraph()
        g.add_edges_from([("a", "c"), ("b", "c"), ("c", "d"), ("c", "e")])
        roots = set(find_root_nodes(g))
        leaves = set(find_leaf_nodes(g))
        assert roots == {"a", "b"}
        assert leaves == {"d", "e"}
