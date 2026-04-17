# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.2] - 2026-04-17

### Added

- **`Encryptor(key_file=...)` persistent key storage** (FB-006): When `DAGLOOM_MASTER_KEY` env var is unset, `Encryptor` can now auto-generate a Fernet key and persist it to a file with `0o600` permissions. On subsequent invocations the same key is reused, making `SecretStore` usable out-of-the-box for CLI tools without manual key management.
  - Priority order: explicit `master_key` → `DAGLOOM_MASTER_KEY` env var → `key_file` → ephemeral (warning)
  - Parent directories are created automatically
  - 5 new tests covering key file creation, reuse, permissions, parent dir creation, and env var precedence

### Changed

- `dagloom/security/encryption.py`: `Encryptor.__init__` accepts optional `key_file` parameter; new `_load_or_create_key()` static method

## [1.0.1] - 2026-04-16

### Added

- **`parallel()` helper** (FB-001): Declarative fan-out / fan-in DAGs — `parallel(fetch_a, fetch_b, fetch_c) >> merge_node`. Accepts `Node` and `Pipeline` objects; downstream merge node receives `{predecessor_name: output}` dict.
- **Root node input filtering** (FB-002): `pipeline.run(**inputs)` now filters kwargs per root node by `inspect.signature` — only matching parameters are passed. Nodes with `**kwargs` receive all inputs (backward compatible).
- **Pipeline inputs on ExecutionContext** (FB-003): `ctx.pipeline_inputs` stores the original `**inputs` dict; `ctx.get_input(key, default)` convenience accessor. Available to all nodes via context.
- **Enhanced `Pipeline.visualize()`** (FB-005): Now shows per-node metadata — `retry`, `cache`, `timeout`, `executor` settings inline.
- 20 new tests covering all feedback fixes.

### Changed

- `dagloom/core/pipeline.py`: added `parallel()` and `_filter_inputs()` functions; updated `run()` to filter root inputs; enhanced `visualize()` output.
- `dagloom/core/context.py`: added `pipeline_inputs` field and `get_input()` method to `ExecutionContext`.
- `dagloom/scheduler/executor.py`: `_execute_node()` filters root inputs; `_execute_dag()` stores inputs on context.
- `dagloom/__init__.py`: exported `parallel`.

## [1.0.0] - 2026-04-16

### 🎉 Stable Release

Dagloom v1.0.0 marks the first stable release — a full-featured, production-ready DAG pipeline engine for Python.

### Added

- **Web UI enhancements for v1.0**:
  - Integrated `usePipeline` and `useWebSocket` hooks into the main App — real-time pipeline execution with backend fallback to demo data
  - `PipelineList` component — sidebar listing all pipelines with selection, node count, and last updated
  - `MetricsDashboard` component — per-node execution stats with recharts bar charts (success/failure counts, avg/p95 latency)
  - `VersionHistory` component — timeline UI for pipeline version history with expandable details
  - Error toast notifications for API failures with auto-dismiss
  - Loading spinners during API calls
  - Fixed HTML title from generic "Vite + React + TS" to "Dagloom — Pipeline Engine"
  - Removed unused `App.css` boilerplate
- **Comprehensive connector test coverage**: 46 new mock-based tests for PostgreSQL, MySQL, S3/MinIO, and HTTP connectors
  - PostgresConnector: connect, disconnect, health_check, execute, execute_one, execute_val, context manager, import error
  - MySQLConnector: connect, disconnect, health_check, execute (cursor-based), context manager, import error
  - S3Connector: connect, disconnect, health_check, get/put/delete/list operations, MinIO endpoint, import error
  - HTTPConnector: connect, disconnect, health_check, GET/POST (JSON/text), basic auth, base URL config, import error
- Extended `usePipeline` hook with `getMetrics()`, `getVersions()`, `getSecrets()`, `clearError()` methods

### Changed

- `pyproject.toml`: Development Status upgraded from "3 - Alpha" to "5 - Production/Stable"
- `web/src/App.tsx`: Complete rewrite integrating all hooks and new components
- `web/src/hooks/usePipeline.ts`: Extended with metrics/versions/secrets endpoints
- `web/src/types/index.ts`: Added `NodeMetric`, `PipelineMetrics`, `PipelineVersion` interfaces

### Summary — v0.3 → v1.0 Journey

| Version | Feature |
|---------|---------|
| v0.4.0 | Built-in scheduler (Cron/Interval, APScheduler) |
| v0.5.0 | Email + Webhook notifications |
| v0.6.0 | Bidirectional code↔UI sync (AST codegen + file watcher) |
| v0.7.0 | Cache dependency invalidation (SHA-256 + NetworkX) |
| v0.8.0 | Per-node executor hints (auto/async/process) |
| v0.9.0 | Credential management (Fernet encryption + SecretStore) |
| v0.10.0 | One-click demo pipeline + CLI |
| v0.11.0 | HTTP authentication (API Key + Basic Auth) |
| v0.12.0 | MongoDB, Redis, Kafka connectors |
| v0.13.0 | Observability (node metrics, execution history, REST API) |
| v0.14.0 | Pipeline version management (snapshots + structured diff) |
| **v1.0.0** | **Web UI polish, full test coverage, production-stable** |

**Total: 548 tests, 7 connectors, 12 API endpoint groups, 4 notification channels.**

## [0.14.0] - 2026-04-16

### Added

- **Pipeline version management**: Track code snapshots with SHA-256 hashing, compare versions with structured diffs
  - `pipeline_versions` table (version_hash PK, pipeline_id, code_snapshot, node_names, edges, description, created_at) with pipeline index
  - `Database.save_pipeline_version()` — idempotent version save (INSERT OR IGNORE by hash)
  - `Database.get_pipeline_version(hash)` — fetch a specific version
  - `Database.list_pipeline_versions(pipeline_id)` — list versions newest-first with limit
  - `Database.delete_pipeline_version(hash)` — remove a version
- **Version REST API endpoints**:
  - `GET /api/pipelines/{id}/versions?limit=N` — list version history for a pipeline
  - `GET /api/versions/{hash}` — get a specific version snapshot (code, nodes, edges)
  - `GET /api/versions/{hash_a}/diff/{hash_b}` — structured diff: added/removed/unchanged nodes and edges, plus unified code diff
- **Auto-versioning**: `PUT /api/pipelines/{id}/dag` now automatically saves a version snapshot when the DAG is updated from the UI
- 17 new tests covering DB CRUD, API endpoints, and diff logic

### Changed

- `dagloom/store/db.py`: added `pipeline_versions` table to schema DDL; 4 new CRUD methods
- `dagloom/server/api.py`: 3 new version endpoints; `update_dag` now auto-saves version snapshot

## [0.13.0] - 2026-04-16

### Added

- **Observability — Node execution metrics**: Per-node timing, outcome, and retry tracking persisted to SQLite
  - `node_metrics` table with indexed columns for pipeline, node, and timestamp queries
  - `Database.save_node_metric()` — record wall time, outcome, retry count per node execution
  - `Database.get_node_metrics(node_id)` — fetch recent metrics for a specific node
  - `Database.get_pipeline_metrics(pipeline_id)` — fetch all node metrics for a pipeline
  - `Database.get_node_stats(pipeline_id)` — aggregate stats per node: total runs, success/failure counts, avg/min/max/p50/p95 wall time
  - `Database.get_execution_history(pipeline_id)` — execution history with per-node metrics attached
- **Metrics REST API endpoints**:
  - `GET /api/metrics/{pipeline_id}` — per-node aggregate statistics (runs, failure rate, latency percentiles)
  - `GET /api/history/{pipeline_id}?limit=N` — execution history with node-level detail
- **Executor instrumentation**: `AsyncExecutor` accepts optional `metrics_db` parameter; automatically records wall time and outcome for each node on success or failure
- 19 new tests covering DB metrics CRUD, executor instrumentation, and API endpoints

### Changed

- `dagloom/store/db.py`: added `node_metrics` table with 3 indexes to schema DDL; 5 new query methods
- `dagloom/scheduler/executor.py`: `AsyncExecutor.__init__` accepts `metrics_db`; `_execute_node` records metrics after success/failure; new `_record_metric()` helper

## [0.12.0] - 2026-04-16

### Added

- **MongoDB connector** (`dagloom/connectors/mongodb.py`): Async MongoDB connector using `motor>=3.3`
  - `MongoDBConnector` — full CRUD operations: `find`, `find_one`, `insert_one`, `insert_many`, `update_one`, `update_many`, `delete_one`, `delete_many`, `aggregate`, `count`
  - Connection URI auto-built from config (supports `mongodb+srv` via `extra["srv"]`)
  - Default port: 27017, connection pool size configurable
- **Redis connector** (`dagloom/connectors/redis.py`): Async Redis connector using `redis>=5.0`
  - `RedisConnector` — direct command mapping: `get`, `set`, `delete`, `hget`, `hset`, `lpush`, `rpush`, `lrange`, `keys`, `exists`, `expire`, `ttl`, and any other redis-py command
  - `config.database` used as Redis DB index; supports SSL and connection pooling
  - Default port: 6379, `decode_responses=True` by default
- **Kafka connector** (`dagloom/connectors/kafka.py`): Async Kafka connector using `aiokafka>=0.9`
  - `KafkaConnector` — `send` operation (produce via `AIOKafkaProducer`), `consume` operation (temporary `AIOKafkaConsumer`)
  - Bootstrap servers from `config.host` (comma-separated for multiple brokers)
  - Default port: 9092, SSL support via `config.ssl`
- Optional dependency extras: `pip install dagloom[mongodb]`, `dagloom[redis]`, `dagloom[kafka]`, `dagloom[all-connectors]`
- 48 new tests covering all three connectors (mock-based, no external services required)

### Changed

- `pyproject.toml`: added `mongodb`, `redis`, `kafka`, `all-connectors` optional dependency groups

## [0.11.0] - 2026-04-15

### Added

- **Basic Auth & API Key authentication**: Opt-in HTTP authentication for the REST API and Web UI
  - `AuthProvider` abstract base class with pluggable provider pattern
  - `APIKeyAuth` — Bearer token authentication with layered key resolution (direct → SecretStore → `DAGLOOM_API_KEY` env var)
  - `BasicAuth` — HTTP Basic authentication with PBKDF2-SHA256 password hashing (100,000 iterations), layered credential resolution (direct → SecretStore → `DAGLOOM_AUTH_USERNAME`/`DAGLOOM_AUTH_PASSWORD` env vars)
  - `NoAuth` — null provider for development (always succeeds)
- **Authentication middleware** (`dagloom/server/middleware.py`):
  - `AuthMiddleware` — Starlette-based HTTP middleware for Bearer/Basic credential extraction and validation
  - `RequireAuth` — FastAPI dependency for mandatory authentication (raises HTTP 401)
  - `OptionalAuth` — FastAPI dependency for optional authentication (returns guest user)
  - Public path exclusion: `/health`, `/docs`, `/openapi.json`, `/redoc` bypass authentication
- **CLI authentication options**: `dagloom serve --auth-type API_KEY --auth-key sk-abc123` or `--auth-type BASIC_AUTH --auth-key admin:password`
- **Environment variable configuration**: `DAGLOOM_AUTH_TYPE` and `DAGLOOM_AUTH_KEY` for container/CI deployments
- `create_app()` factory function accepts `auth_type` and `auth_key` parameters
- 62 new tests covering auth providers, middleware, and end-to-end integration (100% patch coverage)

### Changed

- `dagloom/server/app.py`: `create_app()` now accepts `auth_type` and `auth_key` parameters; adds `AuthMiddleware` when configured
- `dagloom/cli/main.py`: `serve` command accepts `--auth-type` and `--auth-key` options
- `dagloom/security/__init__.py`: exports `AuthProvider`, `APIKeyAuth`, `BasicAuth`, `NoAuth`

## [0.10.0] - 2026-04-15

### Added

- **One-click demo pipeline**: Self-contained ETL demo exercising `@node`, `>>`, `|` (branching), caching, scheduling
  - `dagloom demo --run` — run the demo pipeline directly and print a sales summary report
  - `dagloom demo` — start the web server with the demo pipeline registered
  - `dagloom demo --records 200` — customize the number of generated records
  - Demo pipeline: `generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report`
  - `create_demo_pipeline()` factory function for programmatic use
- `dagloom/demo/` package with `etl_pipeline.py` — 6 demo nodes generating, validating, cleaning/flagging, summarizing, and reporting sales data
- 21 new tests covering all demo nodes, pipeline structure, execution, and CLI

### Fixed

- **Branch merge bug**: `Pipeline.run()` and `AsyncExecutor._execute_node()` now filter out skipped predecessors when resolving node inputs — previously crashed with `KeyError` when a branch-skipped node was a predecessor of a merge node

## [0.9.0] - 2026-04-15

### Added

- **Credential security management**: Encrypted secret storage with layered resolution (env vars → `.env` → Fernet-encrypted SQLite)
  - `Encryptor` class — Fernet symmetric encryption with master key from `DAGLOOM_MASTER_KEY` env var; ephemeral key fallback for development
  - `SecretStore` class — layered secret resolution: environment variables (`DAGLOOM_SECRET_<KEY>`) → `.env` file (via `python-dotenv`) → encrypted database
  - `DecryptionError` exception for wrong-key / corrupted-data scenarios
- **Database**: `secrets` table (`key`, `encrypted_value`, `created_at`, `updated_at`) with CRUD methods: `save_secret`, `get_secret`, `list_secrets` (keys only, never exposes values), `delete_secret`
- **Secrets REST API endpoints**:
  - `GET /api/secrets` — list secret keys (values never exposed)
  - `POST /api/secrets` — create/update an encrypted secret
  - `DELETE /api/secrets/{key}` — delete a secret
- **Secrets CLI commands**: `dagloom secret set|get|list|delete`
- `cryptography>=41` and `python-dotenv>=1.0` added to core dependencies
- 41 new tests covering encryption, SecretStore layered resolution, DB CRUD, REST API, and CLI commands (98% patch coverage)

### Changed

- `pyproject.toml`: added `cryptography>=41` and `python-dotenv>=1.0` to dependencies

## [0.8.0] - 2026-04-15

### Added

- **Per-node executor hints (`executor="process"`)**: Control how each node is executed — in the asyncio event loop thread, a separate thread, or a dedicated process
  - `@node(executor="process")` dispatches CPU-bound sync functions to a `ProcessPoolExecutor`
  - `@node(executor="async")` forces asyncio-based execution
  - `@node(executor="auto")` (default) preserves existing behavior: threads for sync, await for async
  - `EXECUTOR_HINTS` constant exported from `dagloom.core.node`
- `AsyncExecutor` now accepts `max_process_workers` parameter to configure the process pool size
- `AsyncExecutor` automatically creates/shuts down a `ProcessPoolExecutor` on-demand when any node uses `executor="process"`
- 19 new tests covering executor hints, per-node dispatch, mixed pipelines, and ProcessExecutor backward compatibility

### Changed

- `Node.__init__` now accepts optional `executor` parameter (default `"auto"`, backward compatible)
- `@node()` decorator accepts `executor` keyword argument
- `AsyncExecutor._run_callable()` now checks `node_obj.executor` hint to decide between thread and process dispatch
- `ProcessExecutor` simplified — now delegates to `AsyncExecutor` by setting all `"auto"` nodes to `"process"` executor hint
- `Node.__repr__` includes `executor` when not `"auto"`

## [0.7.0] - 2026-04-14

### Added

- **Cache dependency invalidation**: When a node's output changes, all downstream node caches are automatically invalidated so they re-execute on the next run
  - `CacheManager.invalidate_node(node_id)` — bulk-remove all cache entries (and files) for a node
  - `CacheManager.invalidate_downstream(node_id, nodes, edges)` — uses `networkx.descendants()` to find all downstream nodes and cascade-invalidate their caches
  - `CacheManager.compute_output_hash(value)` — SHA-256 hash of node output for change detection
  - In-memory output hash registry (`_output_hashes`) survives cache invalidation for accurate change detection
- `Database.delete_cache_entries_for_node(node_id)` — bulk delete returning row count
- `Database.get_cache_entries_for_node(node_id)` — fetch all cache entries for a node
- 18 new tests covering cache invalidation (unit + integration with AsyncExecutor)

### Changed

- `AsyncExecutor._execute_node()` now detects output changes after cache write: compares new output hash with stored hash, triggers `invalidate_downstream()` when different
- `CacheManager.put()` now records output hashes in the in-memory registry for subsequent change detection

## [0.6.0] - 2026-04-15

### Added

- **Bidirectional code ↔ UI sync (end-to-end)**:
- **Enhanced AST parser**: `code_to_dag` now captures full function bodies via `ast.get_source_segment`, extracts type annotations, handles `|` (BitOr) operator for branch detection, and extracts pipeline metadata (`name`, `schedule`) from assignments and `Pipeline()` constructor
- **Rich DAG model**: `DagModel`, `NodeModel`, `EdgeModel` dataclasses as shared intermediate representation between code and UI
- **Round-trip code generation**: `dag_to_code` preserves original function source when available (no stub regeneration), falls back to clean stub generation for new nodes
- **File watcher** (`dagloom/server/watcher.py`): `PipelineWatcher` using `watchfiles` monitors pipeline directories for `.py` file changes, re-parses on change, broadcasts `dag_updated` via WebSocket — debounced with content hash deduplication
- **Optimistic locking**: `PUT /api/pipelines/{id}/dag` accepts `source_hash` for conflict detection — returns HTTP 409 if the file was modified since last read
- **Save flow wired**: `PUT /api/pipelines/{id}/dag` now calls `dag_to_code()` and writes the generated Python file to disk, updating the watcher hash to prevent echo
- **Read flow wired**: `GET /api/pipelines/{id}/dag` parses the source file (when available) for the richest DAG representation including function bodies
  - `parse_to_model()` function for rich parsing with `DagModel` output
  - `compute_source_hash()` utility for SHA-256 content hashing
  - Pipeline metadata extraction from `Pipeline(name="...", schedule="...")` constructor calls
- File watcher auto-starts with `dagloom serve` (integrated into FastAPI lifespan)
- 36 new tests for codegen round-trip, AST parsing, code generation, file watcher, and model dataclasses

### Changed

- `DagUpdateRequest` now includes optional `metadata` and `source_hash` fields
- `GET /api/pipelines/{id}/dag` returns richer structure with `metadata` and `source_hash`
- `PUT /api/pipelines/{id}/dag` returns `source_hash` in response for subsequent conflict detection
- `dagloom/server/app.py`: lifespan now starts/stops `PipelineWatcher` alongside scheduler

## [0.5.0] - 2026-04-15

### Added

- **Email / Webhook notification channels**: Pipeline execution results can be sent via SMTP email or HTTP webhooks (Slack Block Kit, WeChat Work, Feishu, generic JSON)
  - `Pipeline(notify_on={"failure": ["email://ops@team.com"], "success": ["webhook://https://hooks.slack.com/...?format=slack"]})` to configure notifications
  - `SMTPChannel` — async email delivery via `aiosmtplib`
  - `WebhookChannel` — HTTP POST with built-in formatters for Slack, WeChat Work, Feishu, and generic JSON
  - `ChannelRegistry` — named channel management
  - `resolve_channel()` — create channels from URI strings (`email://...`, `webhook://...`)
- **Notification REST API endpoints**:
  - `GET /api/notifications` — list all notification channels
  - `POST /api/notifications` — create a notification channel
  - `DELETE /api/notifications/{id}` — delete a channel
  - `POST /api/notifications/test` — send a test notification
- **Database**: `notification_channels` table for storing channel configurations
- **Executor integration**: `AsyncExecutor` dispatches notifications in the `finally` block — never masks execution errors; notification failures are logged as warnings
- `httpx` added as core dependency (used by WebhookChannel)
- `aiosmtplib>=3.0` added to dev dependencies
- 36 new tests covering all notification components

### Changed

- `Pipeline.__init__` now accepts optional `notify_on` parameter (default `None`, backward compatible)
- `Pipeline.copy()` preserves the `notify_on` attribute
- `AsyncExecutor.execute()` now tracks execution duration and failed node name for notification events

## [0.4.0] - 2026-04-14

### Added

- **Built-in scheduler (Cron/Interval)**: `SchedulerService` wrapping APScheduler `AsyncIOScheduler` for automatic pipeline execution on cron schedules or fixed intervals
  - `Pipeline(schedule="0 9 * * *")` or `Pipeline(schedule="every 30m")` to set a schedule directly on a pipeline
  - `SchedulerService` with full lifecycle: `register`, `unregister`, `pause`, `resume`, `list_schedules`
  - Persists schedules to SQLite — auto-restores on server restart
  - Missed-fire handling via APScheduler (coalesce + grace time)
- **Trigger parsing module** (`dagloom/scheduler/triggers.py`): `parse_trigger()` converts cron expressions and interval shorthands into APScheduler trigger objects; `validate_expression()` for input validation; `describe_trigger()` for human-readable descriptions
- **Schedule REST API endpoints**:
  - `GET /api/schedules` — list all schedules
  - `POST /api/schedules` — create a new schedule
  - `DELETE /api/schedules/{id}` — remove a schedule
  - `POST /api/schedules/{id}/pause` — pause a schedule
  - `POST /api/schedules/{id}/resume` — resume a paused schedule
- **CLI scheduler commands**: `dagloom scheduler list` and `dagloom scheduler status`
- **Database schema additions**: `schedules` table (pipeline_id, cron_expr, enabled, last_run, next_run, misfire_policy) and `dagloom_meta` table for schema versioning
- `SchedulerService` exported from top-level `dagloom` package
- Scheduler auto-starts with `dagloom serve` (integrated into FastAPI lifespan)
- 40 new tests covering trigger parsing, schedule CRUD, and SchedulerService lifecycle

### Changed

- `Pipeline.__init__` now accepts optional `schedule` parameter (default `None`, backward compatible)
- `Pipeline.copy()` preserves the `schedule` attribute
- `pyproject.toml`: added `apscheduler>=3.10,<4` to core dependencies

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

[Unreleased]: https://github.com/lucientong/dagloom/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/lucientong/dagloom/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/lucientong/dagloom/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/lucientong/dagloom/compare/v0.14.0...v1.0.0
[0.14.0]: https://github.com/lucientong/dagloom/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/lucientong/dagloom/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/lucientong/dagloom/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/lucientong/dagloom/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/lucientong/dagloom/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/lucientong/dagloom/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/lucientong/dagloom/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/lucientong/dagloom/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lucientong/dagloom/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lucientong/dagloom/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lucientong/dagloom/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lucientong/dagloom/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lucientong/dagloom/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/lucientong/dagloom/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lucientong/dagloom/releases/tag/v0.1.0
