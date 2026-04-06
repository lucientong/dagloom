"""Bidirectional DAG structure <-> Python code conversion.

Provides utilities to:
1. Parse Python source code → extract node definitions and ``>>`` connections → DAG JSON
2. Generate Python source code from a DAG JSON structure (preserving user function bodies)
"""

from __future__ import annotations

import ast
from typing import Any


def code_to_dag(source_code: str) -> dict[str, Any]:
    """Parse Python source code and extract the DAG structure.

    Looks for:
    - Functions decorated with ``@node`` or ``@node(...)``
    - Expressions of the form ``a >> b >> c``

    Args:
        source_code: Python source code string.

    Returns:
        A dict with keys "nodes" and "edges"::

            {
                "nodes": [
                    {"name": "fetch_data", "params": {"retry": 3}, "docstring": "..."},
                    ...
                ],
                "edges": [["fetch_data", "clean"], ["clean", "save"]]
            }
    """
    tree = ast.parse(source_code)
    nodes: list[dict[str, Any]] = []
    edges: list[list[str]] = []

    for item in ast.walk(tree):
        # Extract @node decorated functions.
        if isinstance(item, ast.FunctionDef):
            node_info = _extract_node_info(item)
            if node_info:
                nodes.append(node_info)

    # Extract >> connections from module-level expressions.
    for item in ast.iter_child_nodes(tree):
        if isinstance(item, (ast.Assign, ast.Expr)):
            value = item.value if isinstance(item, ast.Assign) else item.value
            chain = _extract_rshift_chain(value)
            if len(chain) >= 2:
                for i in range(len(chain) - 1):
                    edges.append([chain[i], chain[i + 1]])

    return {"nodes": nodes, "edges": edges}


def dag_to_code(dag: dict[str, Any], pipeline_var: str = "pipeline") -> str:
    """Generate Python source code from a DAG structure.

    Args:
        dag: Dict with "nodes" (list of node dicts) and "edges" (list of pairs).
        pipeline_var: Variable name for the pipeline assignment.

    Returns:
        Python source code string.
    """
    lines: list[str] = [
        '"""Auto-generated pipeline by Dagloom."""',
        "",
        "from dagloom import node",
        "",
    ]

    # Generate node function stubs.
    for node_info in dag.get("nodes", []):
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

        lines.append(f"    {body}")
        lines.append("")
        lines.append("")

    # Build >> chain from edges (find linear order).
    edges = dag.get("edges", [])
    if edges:
        chain = _build_chain_from_edges(edges)
        if chain:
            chain_str = " >> ".join(chain)
            lines.append(f"{pipeline_var} = {chain_str}")
            lines.append("")

    return "\n".join(lines)


# -- Helpers ------------------------------------------------------------------


def _extract_node_info(func_def: ast.FunctionDef) -> dict[str, Any] | None:
    """Extract node metadata from a decorated function definition."""
    for decorator in func_def.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "node":
            return {
                "name": func_def.name,
                "params": {},
                "docstring": ast.get_docstring(func_def) or "",
            }
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "node":
                params = {}
                for kw in decorator.keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        params[kw.arg] = kw.value.value
                return {
                    "name": func_def.name,
                    "params": params,
                    "docstring": ast.get_docstring(func_def) or "",
                }
    return None


def _extract_rshift_chain(node: ast.AST) -> list[str]:
    """Recursively extract names from a >> chain (BinOp with RShift)."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
        left = _extract_rshift_chain(node.left)
        right = _extract_rshift_chain(node.right)
        return left + right
    return []


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
    chain = []
    current = roots.pop()
    visited: set[str] = set()
    while current and current not in visited:
        chain.append(current)
        visited.add(current)
        current = graph.get(current)

    return chain
