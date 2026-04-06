"""Tests for the Pipeline class."""

import pytest

from dagloom.core.dag import CycleError
from dagloom.core.node import Node, node
from dagloom.core.pipeline import Pipeline


class TestPipelineConstruction:
    """Test building pipelines with add_node/add_edge and >> operator."""

    def test_add_node_and_edge(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipe = Pipeline(name="test")
        pipe.add_node(a)
        pipe.add_node(b)
        pipe.add_edge("a", "b")

        assert "a" in pipe.nodes
        assert "b" in pipe.nodes
        assert ("a", "b") in pipe.edges

    def test_add_duplicate_node(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        pipe = Pipeline()
        pipe.add_node(a)
        pipe.add_node(a)  # Should be idempotent
        assert len(pipe) == 1

    def test_add_edge_missing_source(self) -> None:
        @node
        def b(x: int) -> int:
            return x

        pipe = Pipeline()
        pipe.add_node(b)
        with pytest.raises(ValueError, match="Source node"):
            pipe.add_edge("missing", "b")

    def test_add_edge_missing_target(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        pipe = Pipeline()
        pipe.add_node(a)
        with pytest.raises(ValueError, match="Target node"):
            pipe.add_edge("a", "missing")

    def test_rshift_two_nodes(self) -> None:
        @node
        def a(x: int) -> int:
            return x + 1

        @node
        def b(x: int) -> int:
            return x * 2

        pipe = a >> b
        assert isinstance(pipe, Pipeline)
        assert len(pipe) == 2
        assert ("a", "b") in pipe.edges

    def test_rshift_chain(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        @node
        def c(x: int) -> int:
            return x

        @node
        def d(x: int) -> int:
            return x

        pipe = a >> b >> c >> d
        assert len(pipe) == 4
        assert ("a", "b") in pipe.edges
        assert ("b", "c") in pipe.edges
        assert ("c", "d") in pipe.edges


class TestPipelineQueries:
    """Test graph query methods."""

    def test_root_and_leaf_nodes(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        @node
        def c(x: int) -> int:
            return x

        pipe = a >> b >> c
        assert pipe.root_nodes() == ["a"]
        assert pipe.leaf_nodes() == ["c"]

    def test_predecessors_and_successors(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        @node
        def c(x: int) -> int:
            return x

        pipe = a >> b >> c
        assert pipe.predecessors("b") == ["a"]
        assert pipe.successors("b") == ["c"]
        assert pipe.predecessors("a") == []
        assert pipe.successors("c") == []

    def test_adjacency_list(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipe = a >> b
        adj = pipe.graph
        assert adj["a"] == ["b"]
        assert adj["b"] == []

    def test_visualize(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipe = a >> b
        text = pipe.visualize()
        assert "a -> b" in text


class TestPipelineValidation:
    """Test DAG validation."""

    def test_empty_pipeline_raises(self) -> None:
        pipe = Pipeline()
        with pytest.raises(ValueError, match="empty"):
            pipe.validate()

    def test_valid_pipeline(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipe = a >> b
        pipe.validate()  # Should not raise

    def test_cycle_detection(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipe = Pipeline()
        pipe.add_node(a)
        pipe.add_node(b)
        pipe.add_edge("a", "b")
        pipe.add_edge("b", "a")  # Creates a cycle

        with pytest.raises(CycleError):
            pipe.validate()


class TestPipelineExecution:
    """Test synchronous pipeline execution."""

    def test_simple_chain(self) -> None:
        @node
        def add_one(x: int) -> int:
            return x + 1

        @node
        def double(x: int) -> int:
            return x * 2

        pipe = add_one >> double
        result = pipe.run(x=5)
        # add_one(5) = 6, double(6) = 12
        assert result == 12

    def test_three_step_chain(self) -> None:
        @node
        def step1(x: int) -> int:
            return x + 1

        @node
        def step2(x: int) -> int:
            return x * 2

        @node
        def step3(x: int) -> str:
            return f"result={x}"

        pipe = step1 >> step2 >> step3
        result = pipe.run(x=3)
        # step1(3) = 4, step2(4) = 8, step3(8) = "result=8"
        assert result == "result=8"

    def test_string_pipeline(self) -> None:
        @node
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        @node
        def shout(message: str) -> str:
            return message.upper()

        @node
        def add_emoji(message: str) -> str:
            return f"🎉 {message} 🎉"

        pipe = greet >> shout >> add_emoji
        result = pipe.run(name="World")
        assert result == "🎉 HELLO, WORLD! 🎉"

    def test_node_failure_raises(self) -> None:
        @node
        def fail_node(x: int) -> int:
            raise ValueError("intentional error")

        @node
        def ok_node(x: int) -> int:
            return x

        pipe = ok_node >> fail_node
        with pytest.raises(RuntimeError, match="intentional error"):
            pipe.run(x=1)

    def test_single_node_pipeline(self) -> None:
        """A pipeline with a single node that is both root and leaf."""

        @node
        def solo(x: int) -> int:
            return x + 10

        pipe = Pipeline()
        pipe.add_node(solo)
        pipe._tail_nodes = ["solo"]
        result = pipe.run(x=5)
        assert result == 15


class TestPipelineCopy:
    """Test pipeline copy."""

    def test_copy_is_independent(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        @node
        def c(x: int) -> int:
            return x

        pipe1 = a >> b
        pipe2 = pipe1.copy()
        pipe2.add_node(c)
        pipe2.add_edge("b", "c")

        assert len(pipe1) == 2
        assert len(pipe2) == 3
