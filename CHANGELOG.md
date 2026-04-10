# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
