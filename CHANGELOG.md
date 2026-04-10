# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-04-10

### Added

- **Conditional branching (`|` operator)**: `Branch` class for mutually exclusive node alternatives — `node_a | node_b` creates a branch group; upstream output selects which branch to execute via dict `"branch"` key, boolean truthiness, or default-first fallback
- **Node streaming (generator / async generator)**: `Pipeline.run()` and `AsyncExecutor` now transparently handle generator and async generator node functions, collecting yielded values into lists
- **Node execution hooks (`on_node_start` / `on_node_end`)**: `AsyncExecutor` accepts optional hook callbacks invoked before and after each node execution; supports both sync and async callables
- **API real execution**: `run_pipeline` endpoint now performs actual pipeline execution via `AsyncExecutor` in a background task when a `Pipeline` object is registered; broadcasts WebSocket events on completion/failure
- `Branch` class exported from top-level `dagloom` package
- `_select_branch()` helper for conditional branch selection logic
- `Pipeline._branches` dict to track branch relationships in the DAG
- `Pipeline.__rshift__` now accepts `Branch` objects for inline conditional routing
- `Node.__or__` operator to create `Branch` from two nodes
- Comprehensive tests for all four new features

### Changed

- `AsyncExecutor._run_callable()` now detects and handles async generators (`isasyncgenfunction`) and sync generators (`isgeneratorfunction`)
- `Pipeline._call_node()` now handles coroutines, generators, async generators, and regular functions
- `Pipeline.run()` implements branch selection with `skipped_nodes` set
- `Pipeline.copy()` now copies `_branches` dict

## [0.2.0] - 2026-04-10

### Added

- `Pipeline.arun()` async convenience method — delegates to `AsyncExecutor` internally
- `Pipeline.run()` now transparently handles async node functions via `asyncio.run`
- `AsyncExecutor` cache integration — nodes with `@node(cache=True)` automatically lookup/store results via `CacheManager`
- `AsyncExecutor` checkpoint integration — supports `resume_id` for resuming failed executions from checkpoint
- `Database.get_latest_execution()` helper method with optional status filtering
- Expanded public API in `__init__.py`: now exports `AsyncExecutor`, `CacheManager`, `CheckpointManager`, `CycleError`, `ExecutionContext`, `ExecutionError`, `Node`, `NodeStatus`
- Comprehensive test suite for all new features (22 new tests)

### Changed

- `codegen.dag_to_code()` now correctly handles complex DAGs (fan-out, diamond/fan-in) via new `_build_dag_statements()` function
- `codegen.code_to_dag()` uses `ast.iter_child_nodes` instead of `ast.walk` to avoid extracting nested functions
- `NodeStatus` in `store/models.py` is now re-exported from `core/context.py` (single source of truth)

### Fixed

- `server/api.py`: replaced `__import__("json")` hack with proper top-level `import json`
- `server/api.py`: replaced raw SQL queries with `Database.get_latest_execution()` method
- `server/api.py`: removed redundant local `import json` in `get_dag` endpoint

## [0.1.1] - 2026-04-07

### Added

- `AsyncExecutor` with retry and timeout support
- `CacheManager` for node-level result caching
- `CheckpointManager` for execution state persistence
- Web UI with drag-and-drop DAG editor
- `codegen` module for bidirectional code ↔ DAG conversion
- REST API server with pipeline CRUD and execution endpoints
- SQLite-based storage layer (`Database`)

## [0.1.0] - 2026-04-05

### Added

- `@node` decorator to turn Python functions into pipeline nodes
- `>>` operator for building DAG pipelines
- `Pipeline` class with DAG validation (cycle detection) and topological sort
- `ExecutionContext` for passing data and metadata between nodes
- Basic synchronous pipeline execution
- Project skeleton with PyPI publishing metadata

[Unreleased]: https://github.com/lucientong/dagloom/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lucientong/dagloom/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lucientong/dagloom/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/lucientong/dagloom/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lucientong/dagloom/releases/tag/v0.1.0
