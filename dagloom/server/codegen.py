"""Bidirectional DAG structure <-> Python code conversion.

Provides utilities to:
1. Parse Python source code -> extract node definitions and connections -> DAG model
2. Generate Python source code from a DAG model (preserving user function bodies)

The DAG model (``DagModel``) is the shared intermediate representation
used by both directions and by the REST API for frontend communication.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# DAG Model — shared data structure for both directions
# ---------------------------------------------------------------------------


@dataclass
class NodeModel:
    """A node in the DAG model.

    Attributes:
        name: Unique node identifier (function name).
        params: Decorator keyword arguments (e.g. retry=3, cache=True).
        docstring: First line of the function docstring.
        body: The full function body source (everything inside ``def``).
        source: The complete function source including decorator.
        input_type: Input type annotation string.
        output_type: Return type annotation string.
        position: Optional UI position metadata ``{"x": float, "y": float}``.
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    docstring: str = ""
    body: str = "pass"
    source: str = ""
    input_type: str = "Any"
    output_type: str = "Any"
    position: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "params": self.params,
            "docstring": self.docstring,
            "body": self.body,
            "source": self.source,
            "input_type": self.input_type,
            "output_type": self.output_type,
            "position": self.position,
        }


@dataclass
class EdgeModel:
    """An edge in the DAG model.

    Attributes:
        source: Source node name.
        target: Target node name.
        edge_type: ``">>"`` for sequential, ``"|"`` for branch.
    """

    source: str
    target: str
    edge_type: str = ">>"

    def to_list(self) -> list[str]:
        """Serialize to ``[source, target]`` pair."""
        return [self.source, self.target]


@dataclass
class DagModel:
    """Complete DAG representation — the bridge between code and UI.

    Attributes:
        nodes: List of node definitions.
        edges: List of directed edges.
        metadata: Pipeline-level metadata (name, schedule, etc.).
        source_hash: SHA-256 hash of the original source (for conflict detection).
        raw_source: The original source code (for diff/preserve).
    """

    nodes: list[NodeModel] = field(default_factory=list)
    edges: list[EdgeModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_hash: str = ""
    raw_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the JSON structure used by the REST API."""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_list() for e in self.edges],
            "metadata": self.metadata,
            "source_hash": self.source_hash,
        }


# ---------------------------------------------------------------------------
# Code -> DAG (parsing)
# ---------------------------------------------------------------------------


def code_to_dag(source_code: str) -> dict[str, Any]:
    """Parse Python source code and extract the DAG structure.

    Looks for:
    - Functions decorated with ``@node`` or ``@node(...)``
    - Expressions of the form ``a >> b >> c``
    - Expressions of the form ``a | b`` (branch)

    Args:
        source_code: Python source code string.

    Returns:
        A dict with keys ``"nodes"``, ``"edges"``, and ``"metadata"``.
    """
    model = parse_to_model(source_code)
    return model.to_dict()


def parse_to_model(source_code: str) -> DagModel:
    """Parse Python source into a ``DagModel``.

    This is the rich version of ``code_to_dag`` that preserves
    function bodies and source for round-trip fidelity.
    """
    import hashlib

    tree = ast.parse(source_code)
    source_lines = source_code.splitlines(keepends=True)

    nodes: list[NodeModel] = []
    edges: list[EdgeModel] = []
    metadata: dict[str, Any] = {}

    # Extract @node-decorated functions at module level.
    for item in ast.iter_child_nodes(tree):
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            node_info = _extract_node_info(item, source_lines)
            if node_info is not None:
                nodes.append(node_info)

    # Extract >> and | connections from module-level expressions.
    for item in ast.iter_child_nodes(tree):
        if isinstance(item, (ast.Assign, ast.Expr)):
            value = item.value if isinstance(item, ast.Assign) else item.value
            extracted_edges = _extract_edges(value)
            edges.extend(extracted_edges)

    # Extract pipeline metadata (name, schedule) from assignments.
    metadata = _extract_pipeline_metadata(tree)

    source_hash = hashlib.sha256(source_code.encode()).hexdigest()

    return DagModel(
        nodes=nodes,
        edges=edges,
        metadata=metadata,
        source_hash=source_hash,
        raw_source=source_code,
    )


def _extract_node_info(
    func_def: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> NodeModel | None:
    """Extract node metadata from a decorated function definition."""
    node_params: dict[str, Any] = {}
    is_node = False

    for decorator in func_def.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "node":
            is_node = True
        elif isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "node":
                is_node = True
                for kw in decorator.keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        node_params[kw.arg] = kw.value.value

    if not is_node:
        return None

    # Extract full function source.
    start_line = func_def.lineno
    # Include decorator lines.
    if func_def.decorator_list:
        start_line = func_def.decorator_list[0].lineno
    end_line = func_def.end_lineno or func_def.lineno
    source = "".join(source_lines[start_line - 1 : end_line])

    # Extract function body source (lines after the def line).
    body_lines = source_lines[func_def.lineno : end_line]
    body = textwrap.dedent("".join(body_lines)).strip()

    # Extract type annotations.
    input_type = "Any"
    if func_def.args.args:
        first_arg = func_def.args.args[0]
        if first_arg.annotation:
            input_type = ast.unparse(first_arg.annotation)

    output_type = "Any"
    if func_def.returns:
        output_type = ast.unparse(func_def.returns)

    return NodeModel(
        name=func_def.name,
        params=node_params,
        docstring=ast.get_docstring(func_def) or "",
        body=body,
        source=source.rstrip(),
        input_type=input_type,
        output_type=output_type,
    )


def _extract_edges(node: ast.AST) -> list[EdgeModel]:
    """Extract edges from >> and | operator chains."""
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.RShift):
            # a >> b
            left_names = _extract_chain_names(node.left)
            right_names = _extract_chain_names(node.right)
            edges: list[EdgeModel] = []
            # Recurse into left side for chained >>
            edges.extend(_extract_edges(node.left))
            # Connect last of left to first of right
            if left_names and right_names:
                for left in left_names[-1:]:
                    for right in right_names[:1]:
                        edges.append(EdgeModel(source=left, target=right, edge_type=">>"))
            # Recurse into right side
            edges.extend(_extract_edges(node.right))
            return edges
        if isinstance(node.op, ast.BitOr):
            # a | b (branch)
            left_names = _extract_chain_names(node.left)
            right_names = _extract_chain_names(node.right)
            edges = []
            edges.extend(_extract_edges(node.left))
            edges.extend(_extract_edges(node.right))
            # We don't add edges for | here — it's branch metadata
            return edges
    return []


def _extract_chain_names(node: ast.AST) -> list[str]:
    """Extract all terminal names from an expression tree."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.RShift):
            return _extract_chain_names(node.left) + _extract_chain_names(node.right)
        if isinstance(node.op, ast.BitOr):
            return _extract_chain_names(node.left) + _extract_chain_names(node.right)
    return []


def _extract_rshift_chain(node: ast.AST) -> list[str]:
    """Recursively extract names from a >> chain (BinOp with RShift).

    Kept for backward compatibility with existing tests.
    """
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
        left = _extract_rshift_chain(node.left)
        right = _extract_rshift_chain(node.right)
        return left + right
    return []


def _extract_pipeline_metadata(tree: ast.Module) -> dict[str, Any]:
    """Extract pipeline-level metadata from assignments.

    Looks for patterns like:
    - ``pipeline.name = "..."``
    - ``pipeline.schedule = "..."``
    - ``Pipeline(name="...", schedule="...")``
    """
    metadata: dict[str, Any] = {}

    for item in ast.iter_child_nodes(tree):
        # pipeline.name = "..."
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and isinstance(item.value, ast.Constant)
                    and target.attr in ("name", "schedule")
                ):
                    metadata[target.attr] = item.value.value

        # Pipeline(name="...", schedule="...")
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call):
            func = item.value.func
            if isinstance(func, ast.Name) and func.id == "Pipeline":
                for kw in item.value.keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        metadata[kw.arg] = kw.value.value

    return metadata


# ---------------------------------------------------------------------------
# DAG -> Code (generation)
# ---------------------------------------------------------------------------


def dag_to_code(dag: dict[str, Any], pipeline_var: str = "pipeline") -> str:
    """Generate Python source code from a DAG structure.

    If nodes have ``source`` fields, the original source is preserved.
    Otherwise, function stubs are generated.

    Args:
        dag: Dict with ``"nodes"`` and ``"edges"`` (and optional ``"metadata"``).
        pipeline_var: Variable name for the pipeline assignment.

    Returns:
        Python source code string.
    """
    lines: list[str] = [
        '"""Pipeline generated by Dagloom."""',
        "",
        "from dagloom import node",
        "",
    ]

    # Generate node functions.
    for node_info in dag.get("nodes", []):
        source = node_info.get("source", "")
        if source:
            # Preserve original source verbatim.
            lines.append(source)
        else:
            # Generate a stub.
            lines.extend(_generate_node_stub(node_info))

        lines.append("")
        lines.append("")

    # Build connection expression from edges.
    edges = dag.get("edges", [])
    if edges:
        statements = _build_dag_statements(edges, pipeline_var)
        lines.extend(statements)
        lines.append("")

    # Add metadata assignments.
    metadata = dag.get("metadata", {})
    if metadata.get("name"):
        lines.append(f'{pipeline_var}.name = "{metadata["name"]}"')
    if metadata.get("schedule"):
        lines.append(f'{pipeline_var}.schedule = "{metadata["schedule"]}"')
    if metadata:
        lines.append("")

    return "\n".join(lines)


def _generate_node_stub(node_info: dict[str, Any]) -> list[str]:
    """Generate a function stub for a node without preserved source."""
    lines: list[str] = []
    name = node_info["name"]
    params = node_info.get("params", {})
    docstring = node_info.get("docstring", "")
    body = node_info.get("body", "pass")

    # Build decorator.
    if params:
        param_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
        lines.append(f"@node({param_str})")
    else:
        lines.append("@node")

    # Build function signature.
    input_type = node_info.get("input_type", "Any")
    output_type = node_info.get("output_type", "Any")
    lines.append(f"def {name}(data: {input_type}) -> {output_type}:")

    if docstring:
        lines.append(f'    """{docstring}"""')

    # Indent body lines.
    for body_line in body.splitlines():
        lines.append(f"    {body_line}" if body_line.strip() else "")

    return lines


# -- Edge -> Code helpers --------------------------------------------------


def _build_dag_statements(edges: list[list[str]], pipeline_var: str = "pipeline") -> list[str]:
    """Build Python code statements from DAG edges.

    Handles both linear chains and complex DAGs with fan-out / fan-in.
    For linear chains it produces: ``pipeline = a >> b >> c``
    For complex DAGs it produces explicit ``Pipeline()`` construction code.

    Args:
        edges: List of ``[source, target]`` pairs.
        pipeline_var: Variable name for the pipeline.

    Returns:
        A list of code lines.
    """
    if not edges:
        return []

    # Build adjacency list (supports fan-out).
    graph: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    all_nodes: set[str] = set()

    for src, tgt in edges:
        graph.setdefault(src, []).append(tgt)
        incoming.setdefault(tgt, []).append(src)
        all_nodes.add(src)
        all_nodes.add(tgt)

    # Find roots (no incoming).
    roots = [n for n in all_nodes if n not in incoming]

    # Check if the DAG is a simple linear chain.
    is_linear = all(len(succs) <= 1 for succs in graph.values()) and len(roots) == 1
    if is_linear:
        chain = _build_chain_from_edges(edges)
        if chain:
            return [f"{pipeline_var} = {' >> '.join(chain)}"]

    # Complex DAG: generate explicit Pipeline construction code.
    lines = [
        "from dagloom import Pipeline",
        "",
        f"{pipeline_var} = Pipeline()",
    ]

    # Topological sort for stable ordering.
    ordered = _topo_sort(all_nodes, edges)
    for node_name in ordered:
        lines.append(f"{pipeline_var}.add_node({node_name})")

    for src, tgt in edges:
        lines.append(f'{pipeline_var}.add_edge("{src}", "{tgt}")')

    return lines


def _topo_sort(nodes: set[str], edges: list[list[str]]) -> list[str]:
    """Simple topological sort for code generation ordering."""
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    graph: dict[str, list[str]] = {n: [] for n in nodes}
    for src, tgt in edges:
        graph[src].append(tgt)
        in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue = sorted(n for n in nodes if in_degree[n] == 0)
    result: list[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in sorted(graph.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    return result


def _build_chain_from_edges(edges: list[list[str]]) -> list[str]:
    """Build an ordered chain from edge pairs (simple linear case)."""
    if not edges:
        return []

    # Build adjacency for simple chains.
    graph: dict[str, str] = {}
    incoming: set[str] = set()
    for src, tgt in edges:
        graph[src] = tgt
        incoming.add(tgt)

    # Find the root (node with no incoming edge).
    all_nodes = set(graph.keys()) | incoming
    roots = all_nodes - incoming
    if not roots:
        return list(all_nodes)

    # Follow the chain from root.
    chain: list[str] = []
    current: str | None = roots.pop()
    visited: set[str] = set()
    while current and current not in visited:
        chain.append(current)
        visited.add(current)
        current = graph.get(current)

    return chain


# ---------------------------------------------------------------------------
# Utility: compute source hash
# ---------------------------------------------------------------------------


def compute_source_hash(source_code: str) -> str:
    """Compute SHA-256 hash of source code for conflict detection."""
    import hashlib

    return hashlib.sha256(source_code.encode()).hexdigest()
