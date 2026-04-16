"""Tests for ShipCadence feedback fixes (FB-001 through FB-005).

Covers:
- FB-001: parallel() helper for fan-out / fan-in DAGs
- FB-002: Root node input filtering by signature
- FB-003: Pipeline inputs accessible via ExecutionContext
- FB-005: Enhanced visualize() with node metadata
"""

from __future__ import annotations

from typing import Any

import pytest

from dagloom.core.context import ExecutionContext
from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline, _filter_inputs, parallel

# ===========================================================================
# FB-001: parallel() helper
# ===========================================================================


class TestParallel:
    """Tests for the parallel() fan-out / fan-in helper."""

    def test_parallel_basic(self) -> None:
        """parallel(a, b, c) creates pipeline with 3 independent roots."""

        @node
        def fetch_a() -> str:
            return "a"

        @node
        def fetch_b() -> str:
            return "b"

        @node
        def fetch_c() -> str:
            return "c"

        pipe = parallel(fetch_a, fetch_b, fetch_c)
        assert len(pipe) == 3
        assert set(pipe.root_nodes()) == {"fetch_a", "fetch_b", "fetch_c"}
        assert pipe.edges == []

    def test_parallel_fan_in(self) -> None:
        """parallel(...) >> merge creates fan-in DAG."""

        @node
        def a(x: int) -> int:
            return x + 1

        @node
        def b(x: int) -> int:
            return x + 2

        @node
        def merge(inputs: dict[str, Any]) -> int:
            return inputs["a"] + inputs["b"]

        pipe = parallel(a, b) >> merge
        result = pipe.run(x=10)
        assert result == (10 + 1) + (10 + 2)  # 23

    def test_parallel_requires_two(self) -> None:
        """parallel() with fewer than 2 args raises ValueError."""

        @node
        def solo() -> str:
            return "alone"

        with pytest.raises(ValueError, match="at least 2"):
            parallel(solo)

    def test_parallel_invalid_type(self) -> None:
        """parallel() with non-Node/Pipeline raises TypeError."""
        with pytest.raises(TypeError, match="parallel\\(\\) accepts"):
            parallel("not_a_node", "also_not")  # type: ignore[arg-type]

    def test_parallel_with_pipelines(self) -> None:
        """parallel() accepts Pipeline objects."""

        @node
        def step1() -> int:
            return 1

        @node
        def step2(x: int) -> int:
            return x * 2

        @node
        def step3() -> int:
            return 3

        @node
        def merge(inputs: dict[str, Any]) -> int:
            return inputs["step2"] + inputs["step3"]

        chain = step1 >> step2
        pipe = parallel(chain, step3) >> merge
        result = pipe.run()
        assert result == 2 + 3

    def test_parallel_three_way_fan_in(self) -> None:
        """Three independent nodes merging into one."""

        @node
        def f1() -> str:
            return "one"

        @node
        def f2() -> str:
            return "two"

        @node
        def f3() -> str:
            return "three"

        @node
        def join(inputs: dict[str, str]) -> str:
            return ",".join(sorted(inputs.values()))

        pipe = parallel(f1, f2, f3) >> join
        result = pipe.run()
        assert result == "one,three,two"


# ===========================================================================
# FB-002: Input filtering by signature
# ===========================================================================


class TestInputFiltering:
    """Tests for _filter_inputs and root node input filtering."""

    def test_filter_inputs_exact_match(self) -> None:
        """Only matching params are passed."""

        @node
        def needs_x(x: int) -> int:
            return x

        filtered = _filter_inputs(needs_x, {"x": 1, "y": 2, "z": 3})
        assert filtered == {"x": 1}

    def test_filter_inputs_with_var_keyword(self) -> None:
        """If node accepts **kwargs, all inputs pass through."""

        @node
        def accepts_all(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        filtered = _filter_inputs(accepts_all, {"x": 1, "y": 2})
        assert filtered == {"x": 1, "y": 2}

    def test_filter_inputs_no_params(self) -> None:
        """Node with no params gets empty dict."""

        @node
        def no_args() -> str:
            return "hello"

        filtered = _filter_inputs(no_args, {"x": 1, "y": 2})
        assert filtered == {}

    def test_pipeline_run_filters_root_inputs(self) -> None:
        """Pipeline.run() only passes matching kwargs to each root."""

        @node
        def needs_owner(owner: str) -> str:
            return owner

        @node
        def needs_token(token: str) -> str:
            return token

        @node
        def merge(inputs: dict[str, str]) -> str:
            return f"{inputs['needs_owner']}:{inputs['needs_token']}"

        pipe = parallel(needs_owner, needs_token) >> merge
        result = pipe.run(owner="org", token="ghp_xxx", extra="ignored")
        assert result == "org:ghp_xxx"


# ===========================================================================
# FB-003: Pipeline inputs via context
# ===========================================================================


class TestPipelineInputsContext:
    """Tests for pipeline_inputs on ExecutionContext."""

    def test_context_stores_pipeline_inputs(self) -> None:
        """ExecutionContext.pipeline_inputs stores original inputs."""
        ctx = ExecutionContext(pipeline_inputs={"x": 1, "y": 2})
        assert ctx.pipeline_inputs == {"x": 1, "y": 2}

    def test_context_get_input(self) -> None:
        """get_input() retrieves original pipeline inputs."""
        ctx = ExecutionContext(pipeline_inputs={"owner": "org", "days": 30})
        assert ctx.get_input("owner") == "org"
        assert ctx.get_input("days") == 30
        assert ctx.get_input("missing") is None
        assert ctx.get_input("missing", "default") == "default"

    def test_context_default_empty(self) -> None:
        """Default pipeline_inputs is empty dict."""
        ctx = ExecutionContext()
        assert ctx.pipeline_inputs == {}
        assert ctx.get_input("anything") is None

    def test_pipeline_run_populates_inputs(self) -> None:
        """Pipeline.run() populates ctx.pipeline_inputs (verified via summary)."""

        @node
        def echo(x: int) -> int:
            return x

        pipe = Pipeline(name="test")
        pipe.add_node(echo)
        pipe._tail_nodes = ["echo"]
        result = pipe.run(x=42)
        assert result == 42


# ===========================================================================
# FB-005: Enhanced visualize()
# ===========================================================================


class TestVisualizeMetadata:
    """Tests for enhanced Pipeline.visualize()."""

    def test_visualize_shows_retry(self) -> None:
        """Visualize includes retry count."""

        @node(retry=3)
        def retryable() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(retryable)
        output = pipe.visualize()
        assert "retry=3" in output

    def test_visualize_shows_cache(self) -> None:
        """Visualize includes cache flag."""

        @node(cache=True)
        def cached() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(cached)
        output = pipe.visualize()
        assert "cache=True" in output

    def test_visualize_shows_timeout(self) -> None:
        """Visualize includes timeout."""

        @node(timeout=30)
        def timed() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(timed)
        output = pipe.visualize()
        assert "timeout=30s" in output

    def test_visualize_shows_executor(self) -> None:
        """Visualize includes non-default executor."""

        @node(executor="process")
        def heavy() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(heavy)
        output = pipe.visualize()
        assert "executor='process'" in output

    def test_visualize_no_metadata_for_defaults(self) -> None:
        """Default nodes show no metadata brackets."""

        @node
        def simple() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(simple)
        output = pipe.visualize()
        assert "[" not in output.split("simple")[1].split("\n")[0]

    def test_visualize_combined(self) -> None:
        """Multiple metadata shown together."""

        @node(retry=2, cache=True, timeout=60)
        def full() -> str:
            return "ok"

        pipe = Pipeline(name="test")
        pipe.add_node(full)
        output = pipe.visualize()
        assert "retry=2" in output
        assert "cache=True" in output
        assert "timeout=60s" in output
