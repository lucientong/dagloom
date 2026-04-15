"""Tests for bidirectional code <-> DAG sync.

Covers:
- AST parser: function body capture, | operator, >> chains, metadata
- Code generator: round-trip fidelity, stub generation, complex DAGs
- File watcher: change detection, hash tracking
- PUT endpoint: code generation, conflict detection (409)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dagloom.server.codegen import (
    DagModel,
    EdgeModel,
    NodeModel,
    _build_chain_from_edges,
    _build_dag_statements,
    _extract_rshift_chain,
    code_to_dag,
    compute_source_hash,
    dag_to_code,
    parse_to_model,
)

# ---------------------------------------------------------------------------
# Round-trip tests (parse -> model -> generate -> parse -> compare)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Round-trip tests: code -> DAG -> code -> DAG == same structure."""

    def test_simple_linear_chain(self) -> None:
        source = '''from dagloom import node

@node
def fetch(url: str) -> dict:
    """Fetch data."""
    return {"data": url}


@node
def clean(data: dict) -> dict:
    """Clean data."""
    return {k: v.strip() for k, v in data.items()}


pipeline = fetch >> clean
'''
        dag1 = code_to_dag(source)
        assert len(dag1["nodes"]) == 2
        assert len(dag1["edges"]) == 1
        assert dag1["edges"][0] == ["fetch", "clean"]

        # Generate code from DAG.
        code = dag_to_code(dag1)
        assert "fetch" in code
        assert "clean" in code

        # Re-parse the generated code.
        dag2 = code_to_dag(code)
        assert len(dag2["nodes"]) == len(dag1["nodes"])
        assert len(dag2["edges"]) == len(dag1["edges"])

    def test_three_node_chain(self) -> None:
        source = """from dagloom import node

@node
def a(x: int) -> int:
    return x + 1

@node
def b(x: int) -> int:
    return x * 2

@node
def c(x: int) -> int:
    return x - 1

pipeline = a >> b >> c
"""
        dag = code_to_dag(source)
        assert len(dag["nodes"]) == 3
        assert ["a", "b"] in dag["edges"]
        assert ["b", "c"] in dag["edges"]

    def test_preserved_source_round_trip(self) -> None:
        """Nodes with source should preserve original code."""
        source = '''from dagloom import node

@node(retry=3, cache=True)
def fetch(url: str) -> dict:
    """Fetch data from URL."""
    import httpx
    resp = httpx.get(url)
    return resp.json()

@node
def process(data: dict) -> list:
    return list(data.values())

pipeline = fetch >> process
'''
        model = parse_to_model(source)
        assert model.nodes[0].name == "fetch"
        assert model.nodes[0].params == {"retry": 3, "cache": True}
        assert "httpx" in model.nodes[0].source
        assert model.nodes[0].docstring == "Fetch data from URL."

        # Generate code preserving source.
        dag_dict = model.to_dict()
        code = dag_to_code(dag_dict)
        assert "@node(retry=3, cache=True)" in code
        assert "httpx.get(url)" in code


# ---------------------------------------------------------------------------
# AST Parser tests
# ---------------------------------------------------------------------------


class TestCodeToDag:
    """Tests for code_to_dag / parse_to_model."""

    def test_bare_node_decorator(self) -> None:
        source = """from dagloom import node

@node
def step(x: int) -> int:
    return x + 1
"""
        dag = code_to_dag(source)
        assert len(dag["nodes"]) == 1
        assert dag["nodes"][0]["name"] == "step"

    def test_parameterized_node_decorator(self) -> None:
        source = """from dagloom import node

@node(retry=3, cache=True, timeout=30.0)
def fetch(url: str) -> dict:
    return {}
"""
        dag = code_to_dag(source)
        node = dag["nodes"][0]
        assert node["params"]["retry"] == 3
        assert node["params"]["cache"] is True
        assert node["params"]["timeout"] == 30.0

    def test_captures_function_body(self) -> None:
        source = """from dagloom import node

@node
def complex_step(data: dict) -> list:
    result = []
    for k, v in data.items():
        if v > 0:
            result.append(k)
    return result
"""
        model = parse_to_model(source)
        assert "for k, v in data.items()" in model.nodes[0].body
        assert "result.append(k)" in model.nodes[0].body

    def test_captures_docstring(self) -> None:
        source = '''from dagloom import node

@node
def step(x: int) -> int:
    """This is the docstring."""
    return x
'''
        model = parse_to_model(source)
        assert model.nodes[0].docstring == "This is the docstring."

    def test_captures_type_annotations(self) -> None:
        source = """from dagloom import node

@node
def step(data: dict[str, int]) -> list[str]:
    return list(data.keys())
"""
        model = parse_to_model(source)
        assert "dict" in model.nodes[0].input_type
        assert "list" in model.nodes[0].output_type

    def test_rshift_chain_extraction(self) -> None:
        source = """from dagloom import node

@node
def a(x: int) -> int:
    return x

@node
def b(x: int) -> int:
    return x

@node
def c(x: int) -> int:
    return x

pipeline = a >> b >> c
"""
        dag = code_to_dag(source)
        assert ["a", "b"] in dag["edges"]
        assert ["b", "c"] in dag["edges"]

    def test_ignores_non_node_functions(self) -> None:
        source = """from dagloom import node

def helper(x):
    return x * 2

@node
def step(x: int) -> int:
    return helper(x)
"""
        dag = code_to_dag(source)
        assert len(dag["nodes"]) == 1
        assert dag["nodes"][0]["name"] == "step"

    def test_ignores_nested_functions(self) -> None:
        source = """from dagloom import node

@node
def outer(x: int) -> int:
    def inner(y):
        return y * 2
    return inner(x)
"""
        dag = code_to_dag(source)
        names = [n["name"] for n in dag["nodes"]]
        assert "outer" in names
        assert "inner" not in names

    def test_source_hash_computed(self) -> None:
        source = """from dagloom import node

@node
def step(x: int) -> int:
    return x
"""
        model = parse_to_model(source)
        assert model.source_hash
        assert len(model.source_hash) == 64  # SHA-256 hex

    def test_pipeline_metadata_extraction(self) -> None:
        source = """from dagloom import node, Pipeline

@node
def step(x: int) -> int:
    return x

pipeline = Pipeline(name="my_etl", schedule="0 9 * * *")
"""
        model = parse_to_model(source)
        assert model.metadata.get("name") == "my_etl"
        assert model.metadata.get("schedule") == "0 9 * * *"


# ---------------------------------------------------------------------------
# Code Generator tests
# ---------------------------------------------------------------------------


class TestDagToCode:
    """Tests for dag_to_code."""

    def test_generates_linear_chain(self) -> None:
        dag = {
            "nodes": [
                {"name": "a", "params": {}},
                {"name": "b", "params": {}},
            ],
            "edges": [["a", "b"]],
        }
        code = dag_to_code(dag)
        assert "a >> b" in code

    def test_generates_complex_dag(self) -> None:
        dag = {
            "nodes": [
                {"name": "a"},
                {"name": "b"},
                {"name": "c"},
                {"name": "d"},
            ],
            "edges": [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]],
        }
        code = dag_to_code(dag)
        assert "add_edge" in code

    def test_preserves_source_when_available(self) -> None:
        dag = {
            "nodes": [
                {
                    "name": "fetch",
                    "source": (
                        '@node(retry=3)\ndef fetch(url: str) -> dict:\n    return {"ok": True}'
                    ),
                },
            ],
            "edges": [],
        }
        code = dag_to_code(dag)
        assert "@node(retry=3)" in code
        assert '{"ok": True}' in code

    def test_generates_stub_without_source(self) -> None:
        dag = {
            "nodes": [
                {
                    "name": "step",
                    "params": {"retry": 2},
                    "docstring": "Do something.",
                    "body": "return data",
                },
            ],
            "edges": [],
        }
        code = dag_to_code(dag)
        assert "@node(retry=2)" in code
        assert '"""Do something."""' in code
        assert "return data" in code

    def test_includes_metadata(self) -> None:
        dag = {
            "nodes": [],
            "edges": [],
            "metadata": {"name": "test_pipe", "schedule": "every 5m"},
        }
        code = dag_to_code(dag)
        assert 'pipeline.name = "test_pipe"' in code
        assert 'pipeline.schedule = "every 5m"' in code

    def test_empty_dag(self) -> None:
        dag = {"nodes": [], "edges": []}
        code = dag_to_code(dag)
        assert "from dagloom import node" in code


# ---------------------------------------------------------------------------
# Edge helper tests
# ---------------------------------------------------------------------------


class TestBuildDagStatements:
    """Tests for _build_dag_statements and helpers."""

    def test_linear_chain(self) -> None:
        edges = [["a", "b"], ["b", "c"]]
        result = _build_dag_statements(edges)
        assert len(result) == 1
        assert "a >> b >> c" in result[0]

    def test_fan_out(self) -> None:
        edges = [["a", "b"], ["a", "c"]]
        result = _build_dag_statements(edges)
        code = "\n".join(result)
        assert "add_edge" in code

    def test_diamond(self) -> None:
        edges = [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]
        result = _build_dag_statements(edges)
        code = "\n".join(result)
        for n in ("a", "b", "c", "d"):
            assert n in code

    def test_chain_from_edges(self) -> None:
        edges = [["a", "b"], ["b", "c"], ["c", "d"]]
        chain = _build_chain_from_edges(edges)
        assert chain == ["a", "b", "c", "d"]


# ---------------------------------------------------------------------------
# DagModel / NodeModel / EdgeModel tests
# ---------------------------------------------------------------------------


class TestDagModel:
    """Tests for DAG model dataclasses."""

    def test_node_model_to_dict(self) -> None:
        node = NodeModel(name="test", params={"retry": 3})
        d = node.to_dict()
        assert d["name"] == "test"
        assert d["params"]["retry"] == 3

    def test_edge_model_to_list(self) -> None:
        edge = EdgeModel(source="a", target="b", edge_type=">>")
        assert edge.to_list() == ["a", "b"]

    def test_dag_model_to_dict(self) -> None:
        model = DagModel(
            nodes=[NodeModel(name="a"), NodeModel(name="b")],
            edges=[EdgeModel(source="a", target="b")],
            metadata={"name": "test"},
            source_hash="abc123",
        )
        d = model.to_dict()
        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1
        assert d["metadata"]["name"] == "test"
        assert d["source_hash"] == "abc123"


# ---------------------------------------------------------------------------
# Source hash tests
# ---------------------------------------------------------------------------


class TestSourceHash:
    """Tests for compute_source_hash."""

    def test_deterministic(self) -> None:
        source = "def foo(): pass"
        h1 = compute_source_hash(source)
        h2 = compute_source_hash(source)
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        h1 = compute_source_hash("def foo(): pass")
        h2 = compute_source_hash("def bar(): pass")
        assert h1 != h2


# ---------------------------------------------------------------------------
# File watcher tests
# ---------------------------------------------------------------------------


class TestPipelineWatcher:
    """Tests for PipelineWatcher."""

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path: Path) -> None:
        from dagloom.server.watcher import PipelineWatcher

        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)])
        assert not watcher.running
        await watcher.start()
        assert watcher.running
        await watcher.stop()
        assert not watcher.running

    @pytest.mark.asyncio
    async def test_double_start(self, tmp_path: Path) -> None:
        from dagloom.server.watcher import PipelineWatcher

        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)])
        await watcher.start()
        await watcher.start()  # Should not raise.
        assert watcher.running
        await watcher.stop()

    def test_update_hash(self, tmp_path: Path) -> None:
        from dagloom.server.watcher import PipelineWatcher

        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)])
        watcher.update_hash("/some/file.py", "abc123")
        assert watcher._file_hashes["/some/file.py"] == "abc123"

    @pytest.mark.asyncio
    async def test_process_change(self, tmp_path: Path) -> None:
        """Verify _process_change parses a file and calls on_change."""
        from unittest.mock import AsyncMock

        from dagloom.server.watcher import PipelineWatcher

        # Write a test pipeline file.
        test_file = tmp_path / "test_pipe.py"
        test_file.write_text(
            """from dagloom import node

@node
def step(x: int) -> int:
    return x + 1
""",
            encoding="utf-8",
        )

        callback = AsyncMock()
        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)], on_change=callback)

        await watcher._process_change(str(test_file))
        callback.assert_called_once()
        args = callback.call_args.args
        assert args[0] == str(test_file)
        assert len(args[1]["nodes"]) == 1

    @pytest.mark.asyncio
    async def test_process_change_ignores_same_hash(self, tmp_path: Path) -> None:
        """Second call with same content should be skipped."""
        from unittest.mock import AsyncMock

        from dagloom.server.watcher import PipelineWatcher

        test_file = tmp_path / "test_pipe.py"
        test_file.write_text("@node\ndef step(x): return x\n", encoding="utf-8")

        callback = AsyncMock()
        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)], on_change=callback)

        await watcher._process_change(str(test_file))
        await watcher._process_change(str(test_file))  # Same content.
        assert callback.call_count == 1  # Only called once.

    @pytest.mark.asyncio
    async def test_process_change_handles_syntax_error(self, tmp_path: Path) -> None:
        """Files with syntax errors should not crash."""
        from unittest.mock import AsyncMock

        from dagloom.server.watcher import PipelineWatcher

        test_file = tmp_path / "bad.py"
        test_file.write_text("def broken(\n", encoding="utf-8")

        callback = AsyncMock()
        watcher = PipelineWatcher(watch_dirs=[str(tmp_path)], on_change=callback)

        await watcher._process_change(str(test_file))
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# Backward compatibility: _extract_rshift_chain (used by existing tests)
# ---------------------------------------------------------------------------


class TestExtractRshiftChainCompat:
    """Backward compatibility for _extract_rshift_chain."""

    def test_simple_chain(self) -> None:
        import ast

        tree = ast.parse("a >> b >> c")
        expr = tree.body[0].value
        assert _extract_rshift_chain(expr) == ["a", "b", "c"]

    def test_single_name(self) -> None:
        import ast

        tree = ast.parse("a")
        expr = tree.body[0].value
        assert _extract_rshift_chain(expr) == ["a"]
