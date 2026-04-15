# Dagloom Architecture

This document provides a comprehensive overview of Dagloom's architecture, design decisions, and implementation details.

## Table of Contents

- [Overview](#overview)
- [Design Philosophy](#design-philosophy)
- [System Architecture](#system-architecture)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Execution Model](#execution-model)
- [Storage Layer](#storage-layer)
- [Web Server](#web-server)
- [Security](#security)
- [Authentication](#authentication)
- [Future Roadmap](#future-roadmap)

---

## Overview

Dagloom is a lightweight, Python-native pipeline/workflow engine designed for simplicity and developer productivity. Unlike heavyweight orchestration tools (Airflow, Dagster, Prefect), Dagloom takes a minimalist approach:

- **Single process**: No external services (PostgreSQL, Redis, Celery) required
- **Zero configuration**: Works out of the box with embedded SQLite
- **Pythonic API**: Use decorators and operators, not YAML or DSLs
- **Bidirectional UI sync**: Code changes reflect in the UI and vice versa

```
┌─────────────────────────────────────────────────────────────┐
│                      Dagloom Stack                          │
├─────────────────────────────────────────────────────────────┤
│  CLI / Web UI                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  React + TypeScript + React Flow (drag-and-drop)    │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Server                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  REST API    │  │  WebSocket   │  │  Static Files  │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Scheduler (APScheduler + asyncio)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  Executor    │  │  Cache       │  │  Checkpoint    │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Core                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  @node       │  │  Pipeline    │  │  DAG Validator │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Storage                                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLite (aiosqlite) — embedded, zero config          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Philosophy

### 1. Simplicity Over Features

> *"Make the simple things simple, and the complex things possible."*

Dagloom prioritizes a minimal API surface:

| Concept | Dagloom | Airflow | Dagster |
|---------|---------|---------|---------|
| Define a task | `@node` | `@task`, `Operator` | `@op`, `@asset` |
| Build a DAG | `a >> b >> c` | `a >> b >> c` | `@job`, `@graph` |
| Configure | `@node(retry=3)` | Operator params + airflow.cfg | Resources, IO Managers |

### 2. Python-Native

No YAML, no DSLs, no external config files. Everything is Python:

```python
from dagloom import node, Pipeline

@node(retry=3, cache=True)
def fetch(url: str) -> dict:
    return requests.get(url).json()

@node
def transform(data: dict) -> pd.DataFrame:
    return pd.DataFrame(data)

pipeline = fetch >> transform
```

### 3. Zero External Dependencies

Unlike Airflow (requires PostgreSQL + Redis + Celery + message broker), Dagloom runs entirely within a single Python process:

```bash
pip install dagloom
dagloom serve  # That's it!
```

### 4. Resume from Failure

Failed pipelines can be resumed from the last checkpoint, skipping already-completed nodes:

```bash
dagloom run my_pipeline.py  # Node 3 fails
dagloom resume              # Continues from node 3
```

---

## System Architecture

### Module Structure

```
dagloom/
├── __init__.py          # Public API: node, Pipeline, SchedulerService, etc.
├── core/
│   ├── __init__.py
│   ├── node.py          # @node decorator and Node class
│   ├── pipeline.py      # Pipeline class with >> operator and schedule= param
│   ├── dag.py           # DAG validation using NetworkX
│   └── context.py       # Execution context and node status
├── scheduler/
│   ├── __init__.py
│   ├── executor.py      # AsyncExecutor for parallel execution
│   ├── process_executor.py  # ProcessExecutor for CPU-bound nodes
│   ├── scheduler.py     # SchedulerService (APScheduler wrapper)
│   ├── triggers.py      # Cron/interval trigger parsing
│   ├── cache.py         # Output caching with SHA-256 hashing and dependency invalidation
│   └── checkpoint.py    # Resume from failure support
├── notifications/
│   ├── __init__.py
│   ├── base.py          # NotificationChannel ABC, ExecutionEvent
│   ├── email.py         # SMTPChannel (aiosmtplib)
│   ├── webhook.py       # WebhookChannel (Slack, WeChat Work, Feishu, generic)
│   └── registry.py      # ChannelRegistry, resolve_channel (URI-based)
├── server/
│   ├── __init__.py
│   ├── app.py           # FastAPI application factory (starts scheduler)
│   ├── api.py           # REST endpoints (pipelines + schedules)
│   ├── codegen.py       # Bidirectional code ↔ DAG conversion (round-trip fidelity)
│   ├── middleware.py    # AuthMiddleware, RequireAuth, OptionalAuth
│   ├── watcher.py       # File watcher for live code → UI sync
│   └── ws.py            # WebSocket connection manager
├── store/
│   ├── __init__.py
│   └── db.py            # SQLite database layer
├── security/
│   ├── __init__.py
│   ├── auth.py          # AuthProvider ABC, APIKeyAuth, BasicAuth, NoAuth
│   ├── encryption.py    # Encryptor class (Fernet-based), DecryptionError, generate_key()
│   └── secrets.py       # SecretStore with layered resolution (env → .env → encrypted DB)
├── demo/
│   ├── __init__.py
│   └── etl_pipeline.py  # create_demo_pipeline() factory — one-click demo ETL pipeline
├── demo/
│   ├── __init__.py
│   └── etl_pipeline.py  # create_demo_pipeline() factory — one-click demo ETL pipeline
├── connectors/
│   ├── __init__.py
│   ├── base.py          # Abstract connector interface
│   ├── postgres.py      # PostgreSQL connector
│   ├── mysql.py         # MySQL connector
│   ├── s3.py            # S3/MinIO connector
│   ├── http.py          # HTTP API connector
│   ├── mongodb.py       # MongoDB connector (motor>=3.3)
│   ├── redis.py         # Redis connector (redis>=5.0)
│   └── kafka.py         # Kafka connector (aiokafka>=0.9)
└── cli/
    ├── __init__.py
    └── main.py          # Click CLI commands (serve, run, demo, scheduler, secret, etc.)
```

---

## Core Components

### Node (`dagloom/core/node.py`)

A **Node** wraps a Python function with execution metadata:

```python
class Node:
    name: str           # Unique identifier (function name)
    fn: Callable        # The wrapped function
    retry: int          # Retry count on failure (default: 0)
    cache: bool         # Enable output caching (default: False)
    timeout: float      # Max execution time in seconds (default: None)
    executor: str       # Executor hint: "auto" | "async" | "process" (default: "auto")
    description: str    # From function docstring
```

The `@node` decorator supports both bare and parameterized forms:

```python
@node                           # Bare decorator
def step_a(x): ...

@node(retry=3, cache=True)     # Parameterized decorator
def step_b(x): ...

@node(executor="process")      # CPU-bound: dispatched to ProcessPoolExecutor
def step_c(x): ...

@node(executor="async")        # Force asyncio execution
def step_d(x): ...
```

**Executor hints** (v0.8.0):

A module-level constant defines the allowed values:

```python
EXECUTOR_HINTS = frozenset({"auto", "async", "process"})
```

| Hint | Behavior |
|------|----------|
| `"auto"` (default) | Preserves existing behavior — sync functions run in `asyncio.to_thread`, async functions are awaited directly |
| `"async"` | Forces asyncio execution (useful for sync functions that are actually I/O-bound and safe to run in the event loop) |
| `"process"` | Dispatches CPU-bound sync functions to a `ProcessPoolExecutor` via a top-level picklable helper `_run_in_process()` |

Key implementation details:

- **`__rshift__`**: Enables `node_a >> node_b` syntax
- **`__call__`**: Allows direct invocation `node(args)`
- **Type introspection**: Extracts input parameters and return type via `inspect.signature`

### Pipeline (`dagloom/core/pipeline.py`)

A **Pipeline** is a DAG (Directed Acyclic Graph) of connected nodes:

```python
class Pipeline:
    name: str                           # Optional pipeline name
    schedule: str | None                # Cron expression or interval shorthand (e.g. "0 9 * * *", "every 30m")
    notify_on: dict | None              # Notification config (e.g. {"failure": ["email://..."], "success": ["webhook://..."]})
    notify_on: dict | None              # Notification config (e.g. {"failure": ["email://..."], "success": ["webhook://..."]})
    _nodes: dict[str, Node]             # Node registry
    _edges: list[tuple[str, str]]       # Edge list (source, target)
    _tail_nodes: list[str]              # Current chain tails for >>
    _branches: dict[str, Branch]        # Conditional branch mapping (predecessor name → Branch)
```

**Building a Pipeline:**

```python
# Method 1: Using >> operator
pipeline = fetch >> clean >> save

# Method 2: Explicit construction
pipeline = Pipeline()
pipeline.add_node(fetch)
pipeline.add_node(clean)
pipeline.add_node(save)
pipeline.add_edge("fetch", "clean")
pipeline.add_edge("clean", "save")
```

**Execution:**

```python
result = pipeline.run(url="https://...")
```

The `run()` method:
1. Validates the DAG (checks for cycles)
2. Computes topological order
3. Executes nodes sequentially
4. Passes outputs as inputs to dependent nodes

### DAG Validation (`dagloom/core/dag.py`)

Uses **NetworkX** for graph operations:

```python
def validate_dag(graph: nx.DiGraph) -> None:
    """Raises CycleError if cycles detected."""
    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        raise CycleError(cycle)

def topological_layers(graph: nx.DiGraph) -> list[list[str]]:
    """Group nodes by execution layer for parallelization."""
    return list(nx.topological_generations(graph))
```

---

## Data Flow

### Input Propagation

```
              inputs: {url: "https://..."}
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Root Node (fetch)                                          │
│  fn(url="https://...")  →  returns: dict                   │
└────────────────────────────────┬────────────────────────────┘
                                 │ output: dict
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Node (clean)                                               │
│  fn(data=<output from fetch>)  →  returns: DataFrame       │
└────────────────────────────────┬────────────────────────────┘
                                 │ output: DataFrame
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Leaf Node (save)                                           │
│  fn(df=<output from clean>)  →  returns: str (path)        │
└─────────────────────────────────────────────────────────────┘
```

### Multi-Predecessor Handling

When a node has multiple predecessors, it receives a dict of outputs:

```python
@node
def merge(inputs: dict[str, Any]) -> pd.DataFrame:
    # inputs = {"process_a": df_a, "process_b": df_b}
    return pd.concat([inputs["process_a"], inputs["process_b"]])
```

---

## Execution Model

### Synchronous Execution (`Pipeline.run()`)

Executes nodes in topological order, one at a time:

```python
for node_name in topological_order:
    node = nodes[node_name]
    result = node(**get_inputs(node_name))
    outputs[node_name] = result
```

### Asynchronous Execution (`AsyncExecutor`)

Groups nodes into **layers** — nodes in the same layer have no dependencies on each other and execute concurrently:

```
Layer 0: [fetch_a, fetch_b]     ← parallel
Layer 1: [process_a, process_b] ← parallel  
Layer 2: [merge]                ← sequential
Layer 3: [save]                 ← sequential
```

```python
class AsyncExecutor:
    async def execute(self, **inputs):
        for layer in topological_layers(graph):
            # Run all nodes in this layer concurrently
            await asyncio.gather(*[
                self._execute_node(name, inputs, ctx)
                for name in layer
            ])
```

### Conditional Branch Selection

In both synchronous and asynchronous execution, when a node feeds into a `Branch`, the runtime selects which branch to execute after the node completes:

```python
# Synchronous (Pipeline.run)
if node_name in self._branches:
    branch = self._branches[node_name]
    selected = _select_branch(result, branch)
    for bn in branch.nodes:
        if bn.name != selected:
            skipped_nodes.add(bn.name)  # Unselected branches are skipped

# Asynchronous (AsyncExecutor)
# After each layer completes, branch selection is performed
for name in layer:
    if name in self.pipeline._branches:
        selected = _select_branch(output, branch)
        # Unselected branches are skipped in subsequent layers
```

### Streaming Nodes (Generator / Async Generator)

Node functions can be generators or async generators — the runtime automatically collects yielded values:

```python
@node
def stream_chunks(url: str):
    for i in range(10):
        yield fetch_chunk(url, offset=i)

# Pipeline._call_node handles transparently:
# - generator → list(generator)
# - async generator → [item async for item in gen]
# - coroutine → await / asyncio.run
# - regular function → direct call
```

In `AsyncExecutor._run_callable`:

| Function Type | Detection | Handling |
|--------------|-----------|----------|
| async generator | `isasyncgenfunction()` | `[item async for item in fn()]` |
| coroutine | `iscoroutinefunction()` | `await fn()` |
| sync generator | `isgeneratorfunction()` | `asyncio.to_thread(lambda: list(fn()))` |
| regular function | fallback | `asyncio.to_thread(fn)` |

#### Per-Node Executor Dispatch (v0.8.0)

`AsyncExecutor._run_callable()` now checks `node_obj.executor` **before** the function-type table above. This allows per-node control over execution strategy:

```python
async def _run_callable(self, node_obj, fn, *args, **kwargs):
    hint = node_obj.executor          # "auto" | "async" | "process"

    if hint == "process":
        return await loop.run_in_executor(
            self._process_pool,       # ProcessPoolExecutor
            _run_in_process,          # top-level picklable helper
            fn, args, kwargs,
        )

    if hint == "async":
        return await fn(*args, **kwargs)   # force direct await

    # hint == "auto" → existing function-type dispatch (table above)
    ...
```

`_run_in_process(fn, args, kwargs)` is a **module-level** (top-level) function so that it is picklable by the `multiprocessing` machinery:

```python
def _run_in_process(fn, args, kwargs):
    """Top-level helper — must be picklable for ProcessPoolExecutor."""
    return fn(*args, **kwargs)
```

`AsyncExecutor` now accepts an optional `max_process_workers` parameter that controls the size of the internal `ProcessPoolExecutor`:

```python
executor = AsyncExecutor(
    pipeline,
    max_process_workers=4,   # defaults to os.cpu_count()
)
```

### ProcessExecutor (Simplified in v0.8.0)

`ProcessExecutor` (`dagloom/scheduler/process_executor.py`) has been simplified. Instead of maintaining its own parallel-execution logic, it now:

1. Iterates over all nodes in the pipeline
2. Sets any node with `executor="auto"` to `executor="process"`
3. Delegates entirely to `AsyncExecutor.execute()`

This means `ProcessExecutor` is now a thin wrapper that forces process-based execution for all nodes by default, while still respecting any explicit `executor="async"` hints set by the user.

```python
class ProcessExecutor:
    def __init__(self, pipeline, **kwargs):
        self.pipeline = pipeline
        self._kwargs = kwargs

    async def execute(self, **inputs):
        for node_obj in self.pipeline._nodes.values():
            if node_obj.executor == "auto":
                node_obj.executor = "process"
        inner = AsyncExecutor(self.pipeline, **self._kwargs)
        return await inner.execute(**inputs)
```

### Execution Hooks (on_node_start / on_node_end)

`AsyncExecutor` supports callbacks before and after each node execution:

```python
executor = AsyncExecutor(
    pipeline,
    on_node_start=lambda name, ctx: print(f"Starting: {name}"),
    on_node_end=lambda name, ctx: print(f"Finished: {name}"),
)
```

- Hooks can be sync or async functions (auto-detected via `inspect.isawaitable`)
- Hook exceptions **do not interrupt** execution — only a warning is logged
- `on_node_start` fires after cache check, before actual execution
- `on_node_end` fires after node success or after all retries are exhausted

### Retry with Exponential Backoff

```python
delay = min(base_delay * (2 ** attempt), max_delay)
# Attempt 1: 0.5s, Attempt 2: 1s, Attempt 3: 2s, ...
```

### Timeout Handling

```python
if node.timeout:
    result = await asyncio.wait_for(coro, timeout=node.timeout)
```

---

## Built-in Scheduler

### SchedulerService (`dagloom/scheduler/scheduler.py`)

Wraps APScheduler's `AsyncIOScheduler` for cron and interval-based pipeline scheduling. Runs in-process with the FastAPI server.

```python
from dagloom import SchedulerService

scheduler = SchedulerService(db)
await scheduler.start()

# Register a pipeline for scheduled execution
schedule_id = await scheduler.register(
    pipeline=my_pipeline,
    cron_expr="0 9 * * *",       # or "every 30m"
)

# Manage schedules
await scheduler.pause(schedule_id)
await scheduler.resume(schedule_id)
await scheduler.unregister(schedule_id)

schedules = await scheduler.list_schedules()
await scheduler.stop()
```

Key features:
- **Persistence**: Schedules stored in SQLite `schedules` table — auto-restored on restart
- **Missed-fire handling**: Configurable via APScheduler (coalesce + grace time, default: skip)
- **Trigger parsing** (`triggers.py`): Supports 5-field cron (`"0 9 * * *"`) and interval shorthands (`"every 30m"`, `"every 2h"`, `"every 1d"`)
- **In-process**: No separate daemon — scheduler starts/stops with `dagloom serve`

### Pipeline Schedule Parameter

```python
# Via constructor
pipeline = Pipeline(name="daily_etl", schedule="0 9 * * *")

# Via attribute
pipeline = fetch >> process
pipeline.schedule = "every 30m"
```

---

## Notification System

### Overview (`dagloom/notifications/`)

Pipeline execution results can be sent to external services via email or webhooks. Notifications are dispatched in the `AsyncExecutor.execute()` finally block — they never mask execution errors.

### Channels

- **SMTPChannel** (`email.py`): Async email via `aiosmtplib`. Supports STARTTLS, customizable subject template.
- **WebhookChannel** (`webhook.py`): HTTP POST via `httpx`. Built-in formatters:
  - `"slack"` — Slack Block Kit with color-coded attachments
  - `"wechat_work"` — WeChat Work (WeCom) markdown message
  - `"feishu"` — Feishu (Lark) interactive card
  - `"generic"` — plain JSON with all event fields

### URI Resolution (`registry.py`)

Channels are created from URI strings:
```python
resolve_channel("email://ops@team.com")           # → SMTPChannel
resolve_channel("webhook://https://...?format=slack")  # → WebhookChannel
```

### Pipeline Configuration

```python
pipeline.notify_on = {
    "failure": ["email://ops@team.com", "webhook://https://hooks.slack.com/...?format=slack"],
    "success": ["webhook://https://hooks.slack.com/...?format=slack"],
}
```

### Execution Flow

```
AsyncExecutor.execute() → finally block
  ├─ Check pipeline.notify_on
  ├─ Build ExecutionEvent (status, duration, error, failed_node)
  ├─ For each URI in notify_on[status]:
  │   ├─ resolve_channel(uri)
  │   └─ channel.send(event)  # failure logged as warning, never raised
  └─ Done
```

---

## Storage Layer

### SQLite Schema (`dagloom/store/db.py`)

```sql
-- Pipelines
CREATE TABLE pipelines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    node_names TEXT,      -- JSON array
    edges TEXT,           -- JSON array of [src, tgt]
    created_at TEXT,
    updated_at TEXT
);

-- Executions
CREATE TABLE executions (
    id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- running, success, failed
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);

-- Node Executions (for checkpoint/resume)
CREATE TABLE node_executions (
    id INTEGER PRIMARY KEY,
    execution_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending, running, success, failed
    input_hash TEXT,
    output_path TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at TEXT,
    finished_at TEXT
);

-- Cache Entries
CREATE TABLE cache_entries (
    node_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_path TEXT NOT NULL,
    serialization_format TEXT DEFAULT 'pickle',
    size_bytes INTEGER,
    created_at TEXT,
    PRIMARY KEY (node_id, input_hash)
);
```

**Database methods for cache invalidation (v0.7.0):**

```python
# Delete all cache entries for a given node
await db.delete_cache_entries_for_node(node_id)

# Retrieve all cache entries for a given node
entries = await db.get_cache_entries_for_node(node_id)
```

```sql
-- Schedules (Cron/Interval)
CREATE TABLE schedules (
    id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    cron_expr TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    last_run TEXT,
    next_run TEXT,
    misfire_policy TEXT DEFAULT 'skip',
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);

-- Schema Versioning
CREATE TABLE dagloom_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Secrets (v0.9.0)
CREATE TABLE secrets (
    key TEXT PRIMARY KEY,
    encrypted_value BLOB NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
```

### Caching (`dagloom/scheduler/cache.py`)

Cache keys are **SHA-256 hashes** of serialized inputs:

```python
def compute_input_hash(*args, **kwargs) -> str:
    hasher = hashlib.sha256()
    for arg in args:
        hasher.update(pickle.dumps(arg))
    for key in sorted(kwargs):
        hasher.update(key.encode())
        hasher.update(pickle.dumps(kwargs[key]))
    return hasher.hexdigest()
```

Cache files are stored in `.dagloom/cache/<node_id>/<hash>.pkl`.

#### Cache Dependency Invalidation (v0.7.0)

When a node's output changes, stale downstream caches must be invalidated. `CacheManager` provides the following methods:

```python
# Bulk-remove all cache entries for a single node
cache_manager.invalidate_node(node_id)

# Cascade-invalidate all downstream nodes using networkx.descendants()
cache_manager.invalidate_downstream(node_id, nodes, edges)

# SHA-256 output hashing for change detection
output_hash = cache_manager.compute_output_hash(value)
```

- **`invalidate_node(node_id)`**: Deletes all cache files under `.dagloom/cache/<node_id>/` and removes corresponding rows from the `cache_entries` table via `Database.delete_cache_entries_for_node()`.
- **`invalidate_downstream(node_id, nodes, edges)`**: Builds a `networkx.DiGraph` from the provided nodes and edges, computes all descendants of `node_id` via `networkx.descendants()`, and calls `invalidate_node()` on each.
- **`compute_output_hash(value)`**: Serializes the value with `pickle.dumps()` and returns its SHA-256 hex digest. Used to detect whether a node's output has actually changed.
- **`_output_hashes`**: An in-memory `dict[str, str]` registry on `CacheManager` that tracks the last-known output hash for each node. Compared after each execution to decide whether downstream invalidation is needed.

**Auto-invalidation in `AsyncExecutor._execute_node()`:**

After writing a cache entry, the executor computes the output hash and compares it against the previous value in `_output_hashes`. If the hash differs (i.e., the output changed), it automatically calls `invalidate_downstream()` to cascade-clear all affected caches.

### Checkpoint/Resume (`dagloom/scheduler/checkpoint.py`)

Each node's execution state is persisted:

```python
await checkpoint.save_state(
    execution_id="abc123",
    pipeline_id="my_pipeline",
    node_id="clean",
    status="success",
    output_path=".dagloom/cache/clean/xyz789.pkl"
)
```

On resume, completed nodes are skipped:

```python
completed = await checkpoint.get_completed_nodes(execution_id)
for node_name in topological_order:
    if node_name in completed:
        continue  # Skip
    # Execute node...
```

---

## Web Server

### FastAPI Application (`dagloom/server/app.py`)

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Dagloom", version=__version__)
    app.include_router(api.router)
    
    @app.on_event("startup")
    async def startup():
        db = Database()
        await db.connect()
        api.set_state("db", db)
    
    return app
```

### REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pipelines` | List all pipelines |
| POST | `/api/pipelines/{id}/run` | Trigger execution |
| GET | `/api/pipelines/{id}/status` | Get execution status |
| POST | `/api/pipelines/{id}/resume` | Resume from checkpoint |
| GET | `/api/pipelines/{id}/dag` | Get DAG structure |
| PUT | `/api/pipelines/{id}/dag` | Update DAG from UI |
| GET | `/api/schedules` | List all schedules |
| POST | `/api/schedules` | Create a schedule |
| DELETE | `/api/schedules/{id}` | Delete a schedule |
| POST | `/api/schedules/{id}/pause` | Pause a schedule |
| POST | `/api/schedules/{id}/resume` | Resume a schedule |
| GET | `/api/notifications` | List notification channels |
| POST | `/api/notifications` | Create a notification channel |
| DELETE | `/api/notifications/{id}` | Delete a channel |
| POST | `/api/notifications/test` | Send a test notification |
| GET | `/api/notifications` | List notification channels |
| POST | `/api/notifications` | Create a notification channel |
| DELETE | `/api/notifications/{id}` | Delete a channel |
| POST | `/api/notifications/test` | Send a test notification |
| GET | `/api/secrets` | List all secret keys |
| POST | `/api/secrets` | Create or update a secret |
| DELETE | `/api/secrets/{key}` | Delete a secret |

### WebSocket (`dagloom/server/ws.py`)

Real-time updates for execution status:

```python
class ConnectionManager:
    async def broadcast(self, pipeline_id: str, message: dict):
        for connection in self.connections[pipeline_id]:
            await connection.send_json(message)
```

Events:
- `execution_started`
- `node_running`
- `node_success`
- `node_failed`
- `execution_completed`
- `dag_updated` — DAG structure changed (from file edit or UI save)

### Bidirectional Sync Flow

**UI → File (Save):**
```
Frontend drag-and-drop → PUT /api/pipelines/{id}/dag
  ├─ Optimistic locking: compare source_hash → 409 if conflict
  ├─ dag_to_code() → generate Python source (preserving original bodies)
  ├─ Write .py file
  ├─ Update watcher hash (prevent echo)
  ├─ Save to DB
  └─ Broadcast dag_updated via WebSocket
```

**File → UI (Watch):**
```
User edits .py in VS Code / vim → watchfiles detects change
  ├─ Content hash dedup (skip if unchanged)
  ├─ code_to_dag() → parse to DagModel (with function bodies)
  ├─ Broadcast dag_updated via WebSocket
  └─ Frontend re-renders DAG
``` — DAG structure changed (from file edit or UI save)

### Bidirectional Sync Flow

**UI → File (Save):**
```
Frontend drag-and-drop → PUT /api/pipelines/{id}/dag
  ├─ Optimistic locking: compare source_hash → 409 if conflict
  ├─ dag_to_code() → generate Python source (preserving original bodies)
  ├─ Write .py file
  ├─ Update watcher hash (prevent echo)
  ├─ Save to DB
  └─ Broadcast dag_updated via WebSocket
```

**File → UI (Watch):**
```
User edits .py in VS Code / vim → watchfiles detects change
  ├─ Content hash dedup (skip if unchanged)
  ├─ code_to_dag() → parse to DagModel (with function bodies)
  ├─ Broadcast dag_updated via WebSocket
  └─ Frontend re-renders DAG
```

---

## Security

### Credential Security Management (v0.9.0) — `dagloom/security/`

Dagloom provides built-in credential management so that pipelines can access sensitive values (API keys, database passwords, tokens) without hard-coding them in source files. New dependencies: `cryptography>=41`, `python-dotenv>=1.0`.

### Encryption (`dagloom/security/encryption.py`)

The `Encryptor` class wraps `cryptography.fernet.Fernet` for symmetric encryption of secret values:

```python
from dagloom.security.encryption import Encryptor, DecryptionError, generate_key

# Generate a new master key (store securely!)
key = Encryptor.generate_key()  # returns a Fernet-compatible base64 key

# Create an encryptor — reads master key from DAGLOOM_MASTER_KEY env var
encryptor = Encryptor()                    # uses os.environ["DAGLOOM_MASTER_KEY"]
encryptor = Encryptor(master_key=key)      # or pass explicitly

# Encrypt / decrypt
token = encryptor.encrypt("my-api-key")    # returns bytes
value = encryptor.decrypt(token)           # returns str; raises DecryptionError on failure
```

- **Master key source**: `DAGLOOM_MASTER_KEY` environment variable (required at runtime)
- **Algorithm**: Fernet (AES-128-CBC + HMAC-SHA256), via the `cryptography` library
- **`DecryptionError`**: Custom exception raised when decryption fails (invalid key, corrupted data)
- **`generate_key()`**: Static method that returns a fresh Fernet key for initial setup

### Secret Store (`dagloom/security/secrets.py`)

`SecretStore` provides a unified interface for secret retrieval with **layered resolution**:

```
SecretStore.get("DB_PASSWORD")
  ├─ 1. Environment variable: DAGLOOM_SECRET_DB_PASSWORD
  ├─ 2. .env file (loaded via python-dotenv): DAGLOOM_SECRET_DB_PASSWORD
  └─ 3. Encrypted SQLite DB: secrets table → Fernet-decrypt
```

```python
from dagloom.security.secrets import SecretStore

store = SecretStore(db, encryptor)

# CRUD operations (against the encrypted SQLite DB)
await store.save_secret("DB_PASSWORD", "s3cret!")       # encrypt + upsert
value = await store.get_secret("DB_PASSWORD")            # layered resolution
keys  = await store.list_secrets()                       # returns list[str]
await store.delete_secret("DB_PASSWORD")                 # remove from DB
```

**Resolution order** (first match wins):
1. **Environment variable** — `DAGLOOM_SECRET_<KEY>` (e.g. `DAGLOOM_SECRET_DB_PASSWORD`)
2. **`.env` file** — loaded once at startup via `python-dotenv`; same naming convention
3. **Encrypted database** — `secrets` table; values are Fernet-encrypted at rest

This layered approach allows operators to override secrets per-environment without touching the database (e.g., inject via CI/CD env vars or a mounted `.env` file in Kubernetes).

### Database Table

```sql
CREATE TABLE secrets (
    key TEXT PRIMARY KEY,
    encrypted_value BLOB NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
```

Database CRUD methods on `Database`:
- `save_secret(key, encrypted_value)` — INSERT OR REPLACE
- `get_secret(key)` — returns encrypted bytes or `None`
- `list_secrets()` — returns all keys (no values)
- `delete_secret(key)` — DELETE by key

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/secrets` | List all secret keys (values are never returned) |
| POST | `/api/secrets` | Create or update a secret (`{"key": "...", "value": "..."}`) |
| DELETE | `/api/secrets/{key}` | Delete a secret |

### CLI

```bash
dagloom secret set DB_PASSWORD          # prompts for value (no echo)
dagloom secret get DB_PASSWORD          # prints decrypted value
dagloom secret list                     # lists all secret keys
dagloom secret delete DB_PASSWORD       # removes from DB
```

### Security Architecture Flow

```
                       ┌──────────────────────┐
                       │  DAGLOOM_MASTER_KEY   │  (env var)
                       └──────────┬───────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────┐
│  Encryptor (Fernet)                                       │
│  encrypt(plaintext) → ciphertext                          │
│  decrypt(ciphertext) → plaintext                          │
└────────────────┬──────────────────────┬───────────────────┘
                 │                      │
          write (save_secret)    read (get_secret)
                 │                      │
                 ▼                      ▼
┌───────────────────────────────────────────────────────────┐
│  SQLite: secrets table                                    │
│  key TEXT PK | encrypted_value BLOB | timestamps          │
└───────────────────────────────────────────────────────────┘
                                  ▲
                                  │ fallback (layer 3)
                                  │
┌───────────────────────────────────────────────────────────┐
│  SecretStore — layered resolution                         │
│  1. env var  DAGLOOM_SECRET_<KEY>                         │
│  2. .env file (python-dotenv)                             │
│  3. encrypted DB                                          │
└───────────────────────────────────────────────────────────┘
```

---

## Authentication

### Request Authentication (v0.11.0) — `dagloom/security/auth.py`, `dagloom/server/middleware.py`

Dagloom supports optional request-level authentication for the web server. When enabled, all API endpoints require valid credentials — except public paths (`/health`, `/docs`, `/openapi.json`, `/redoc`).

### Auth Providers (`dagloom/security/auth.py`)

`AuthProvider` is an abstract base class with three built-in implementations:

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credential: str) -> bool: ...

class APIKeyAuth(AuthProvider):
    """Validates Bearer tokens against a configured API key."""

class BasicAuth(AuthProvider):
    """Validates HTTP Basic credentials (username:password)."""

class NoAuth(AuthProvider):
    """No-op provider — always returns True. Used when auth is disabled."""
```

| Provider | `--auth-type` | Credential format | Header |
|----------|---------------|-------------------|--------|
| `APIKeyAuth` | `API_KEY` | Raw API key string | `Authorization: Bearer sk-abc123` |
| `BasicAuth` | `BASIC_AUTH` | `username:password` | `Authorization: Basic <base64>` |
| `NoAuth` | *(default)* | — | — |

### Middleware (`dagloom/server/middleware.py`)

`AuthMiddleware` is a Starlette middleware that intercepts every request:

1. Skip public paths: `/health`, `/docs`, `/openapi.json`, `/redoc`
2. Extract credentials from the `Authorization` header (Bearer or Basic scheme)
3. Call `AuthProvider.authenticate(credential)` to validate
4. Reject with `401 Unauthorized` on failure

```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_provider: AuthProvider):
        super().__init__(app)
        self.auth_provider = auth_provider

    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        # Extract and validate credentials...
```

### FastAPI Dependencies

Two dependencies are provided for route-level control:

- **`RequireAuth`** — raises `401` if credentials are missing or invalid
- **`OptionalAuth`** — allows unauthenticated access; populates `request.state.authenticated` for downstream logic

### Configuration

Auth is configured via CLI flags or environment variables:

| CLI Flag | Environment Variable | Description |
|----------|---------------------|-------------|
| `--auth-type` | `DAGLOOM_AUTH_TYPE` | `API_KEY`, `BASIC_AUTH`, or empty (disabled) |
| `--auth-key` | `DAGLOOM_AUTH_KEY` | The API key or `username:password` string |

```bash
# API key authentication
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic authentication
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password

# Environment variables
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### Authentication Flow

```
Incoming Request
  │
  ├─ Path in PUBLIC_PATHS? ──yes──→ Skip auth → call_next()
  │
  no
  │
  ├─ Extract Authorization header
  │   ├─ Bearer <token>  → credential = token
  │   └─ Basic <base64>  → credential = decoded username:password
  │
  ├─ AuthProvider.authenticate(credential)
  │   ├─ True  → call_next()
  │   └─ False → 401 Unauthorized
  │
  └─ No header → 401 Unauthorized
```

---

## Authentication

### Request Authentication (v0.11.0) — `dagloom/security/auth.py`, `dagloom/server/middleware.py`

Dagloom supports optional request-level authentication for the web server. When enabled, all API endpoints require valid credentials — except public paths (`/health`, `/docs`, `/openapi.json`, `/redoc`).

### Auth Providers (`dagloom/security/auth.py`)

`AuthProvider` is an abstract base class with three built-in implementations:

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credential: str) -> bool: ...

class APIKeyAuth(AuthProvider):
    """Validates Bearer tokens against a configured API key."""

class BasicAuth(AuthProvider):
    """Validates HTTP Basic credentials (username:password)."""

class NoAuth(AuthProvider):
    """No-op provider — always returns True. Used when auth is disabled."""
```

| Provider | `--auth-type` | Credential format | Header |
|----------|---------------|-------------------|--------|
| `APIKeyAuth` | `API_KEY` | Raw API key string | `Authorization: Bearer sk-abc123` |
| `BasicAuth` | `BASIC_AUTH` | `username:password` | `Authorization: Basic <base64>` |
| `NoAuth` | *(default)* | — | — |

### Middleware (`dagloom/server/middleware.py`)

`AuthMiddleware` is a Starlette middleware that intercepts every request:

1. Skip public paths: `/health`, `/docs`, `/openapi.json`, `/redoc`
2. Extract credentials from the `Authorization` header (Bearer or Basic scheme)
3. Call `AuthProvider.authenticate(credential)` to validate
4. Reject with `401 Unauthorized` on failure

```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_provider: AuthProvider):
        super().__init__(app)
        self.auth_provider = auth_provider

    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        # Extract and validate credentials...
```

### FastAPI Dependencies

Two dependencies are provided for route-level control:

- **`RequireAuth`** — raises `401` if credentials are missing or invalid
- **`OptionalAuth`** — allows unauthenticated access; populates `request.state.authenticated` for downstream logic

### Configuration

Auth is configured via CLI flags or environment variables:

| CLI Flag | Environment Variable | Description |
|----------|---------------------|-------------|
| `--auth-type` | `DAGLOOM_AUTH_TYPE` | `API_KEY`, `BASIC_AUTH`, or empty (disabled) |
| `--auth-key` | `DAGLOOM_AUTH_KEY` | The API key or `username:password` string |

```bash
# API key authentication
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic authentication
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password

# Environment variables
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### Authentication Flow

```
Incoming Request
  │
  ├─ Path in PUBLIC_PATHS? ──yes──→ Skip auth → call_next()
  │
  no
  │
  ├─ Extract Authorization header
  │   ├─ Bearer <token>  → credential = token
  │   └─ Basic <base64>  → credential = decoded username:password
  │
  ├─ AuthProvider.authenticate(credential)
  │   ├─ True  → call_next()
  │   └─ False → 401 Unauthorized
  │
  └─ No header → 401 Unauthorized
```

---

## Future Roadmap

### Planned Features

1. **Distributed Execution**: Optional Redis backend for multi-worker support
2. ~~**Scheduling**: Cron-like triggers (daily, hourly, etc.)~~ ✅ Implemented in v0.4.0
3. ~~**Secrets Management**: Secure credential injection~~ ✅ Implemented in v0.9.0
4. **Plugins**: Custom node types (Docker, Kubernetes jobs)
5. **Lineage Tracking**: Track data provenance through pipelines
6. **Monitoring**: Prometheus metrics, Grafana dashboards
7. ~~**Notification Nodes**: Email / Webhook (Slack, WeChat Work, Feishu) alerts on pipeline events~~ ✅ Implemented in v0.5.0
8. ~~**Cache Dependency Invalidation**: Automatic downstream cache invalidation on output changes~~ ✅ Implemented in v0.7.0
9. ~~**Per-Node Executor Hints**: `@node(executor="process"|"async"|"auto")` for fine-grained dispatch control~~ ✅ Implemented in v0.8.0
10. ~~**PyPI Package & One-Click Demo**: `dagloom demo --run` for an instant ETL demo pipeline~~ ✅ Implemented in v0.10.0
11. ~~**Authentication**: Middleware-based API key / Basic auth for the web server~~ ✅ Implemented in v0.11.0
11. ~~**Authentication**: Middleware-based API key / Basic auth for the web server~~ ✅ Implemented in v0.11.0

### Non-Goals

- Full Airflow compatibility
- Enterprise RBAC/multi-tenancy (use managed solutions)
- GUI-first workflow design (code-first philosophy)

---

## Contributing

See the [main README](../../README.md) for contribution guidelines.

## License

Apache License 2.0
