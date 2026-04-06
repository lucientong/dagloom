"""Tests for the @node decorator and Node class."""

import inspect

from dagloom.core.node import Node, node


class TestBareNodeDecorator:
    """Test @node without arguments."""

    def test_creates_node_instance(self) -> None:
        @node
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert isinstance(greet, Node)

    def test_preserves_function_name(self) -> None:
        @node
        def my_func(x: int) -> int:
            return x

        assert my_func.name == "my_func"

    def test_callable(self) -> None:
        @node
        def add_one(x: int) -> int:
            return x + 1

        assert add_one(5) == 6

    def test_default_attributes(self) -> None:
        @node
        def step(x: int) -> int:
            return x

        assert step.retry == 0
        assert step.cache is False
        assert step.timeout is None

    def test_description_from_docstring(self) -> None:
        @node
        def documented(x: int) -> int:
            """This is the first line.

            Additional details here.
            """
            return x

        assert documented.description == "This is the first line."

    def test_no_docstring(self) -> None:
        @node
        def no_doc(x: int) -> int:
            return x

        assert no_doc.description == ""


class TestParameterizedNodeDecorator:
    """Test @node(retry=3, cache=True, ...)."""

    def test_retry_and_cache(self) -> None:
        @node(retry=3, cache=True)
        def fetch(url: str) -> str:
            return url

        assert isinstance(fetch, Node)
        assert fetch.retry == 3
        assert fetch.cache is True

    def test_timeout(self) -> None:
        @node(timeout=30.0)
        def slow_step(x: int) -> int:
            return x

        assert slow_step.timeout == 30.0

    def test_custom_name(self) -> None:
        @node(name="custom_name")
        def original_name(x: int) -> int:
            return x

        assert original_name.name == "custom_name"

    def test_callable_with_params(self) -> None:
        @node(retry=2)
        def multiply(x: int) -> int:
            return x * 2

        assert multiply(3) == 6


class TestNodeProperties:
    """Test Node introspection properties."""

    def test_input_params(self) -> None:
        @node
        def func(a: int, b: str, c: float = 1.0) -> str:
            return f"{a}{b}{c}"

        params = func.input_params
        assert "a" in params
        assert "b" in params
        assert "c" in params
        assert len(params) == 3

    def test_return_annotation(self) -> None:
        @node
        def func(x: int) -> str:
            return str(x)

        assert func.return_annotation is str

    def test_repr(self) -> None:
        @node(retry=2, cache=True, timeout=10.0)
        def step(x: int) -> int:
            return x

        r = repr(step)
        assert "step" in r
        assert "retry=2" in r
        assert "cache=True" in r
        assert "timeout=10.0" in r

    def test_equality_by_name(self) -> None:
        @node(name="same")
        def func_a(x: int) -> int:
            return x

        @node(name="same")
        def func_b(x: int) -> int:
            return x + 1

        assert func_a == func_b

    def test_hash(self) -> None:
        @node
        def step(x: int) -> int:
            return x

        assert hash(step) == hash("step")


class TestNodeShiftOperator:
    """Test >> operator on Node instances."""

    def test_node_rshift_node(self) -> None:
        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipeline = a >> b
        from dagloom.core.pipeline import Pipeline

        assert isinstance(pipeline, Pipeline)
        assert "a" in pipeline.nodes
        assert "b" in pipeline.nodes
        assert ("a", "b") in pipeline.edges

    def test_three_node_chain(self) -> None:
        @node
        def step1(x: int) -> int:
            return x + 1

        @node
        def step2(x: int) -> int:
            return x * 2

        @node
        def step3(x: int) -> int:
            return x - 1

        pipeline = step1 >> step2 >> step3
        assert len(pipeline) == 3
        assert ("step1", "step2") in pipeline.edges
        assert ("step2", "step3") in pipeline.edges
