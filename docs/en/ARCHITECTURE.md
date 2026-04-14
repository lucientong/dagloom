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
│   ├── cache.py         # Output caching with SHA-256 hashing
│   └── checkpoint.py    # Resume from failure support
├── server/
│   ├── __init__.py
│   ├── app.py           # FastAPI application factory (starts scheduler)
│   ├── api.py           # REST endpoints (pipelines + schedules)
│   ├── codegen.py       # Bidirectional code ↔ DAG conversion
│   └── ws.py            # WebSocket connection manager
├── store/
│   ├── __init__.py
│   └── db.py            # SQLite database layer
├── connectors/
│   ├── __init__.py
│   ├── base.py          # Abstract connector interface
│   ├── postgres.py      # PostgreSQL connector
│   ├── mysql.py         # MySQL connector
│   ├── s3.py            # S3/MinIO connector
│   └── http.py          # HTTP API connector
└── cli/
    ├── __init__.py
    └── main.py          # Click CLI commands (serve, run, scheduler, etc.)
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
    description: str    # From function docstring
```

The `@node` decorator supports both bare and parameterized forms:

```python
@node                           # Bare decorator
def step_a(x): ...

@node(retry=3, cache=True)     # Parameterized decorator
def step_b(x): ...
```

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
- `dag_updated`

---

## Future Roadmap

### Planned Features

1. **Distributed Execution**: Optional Redis backend for multi-worker support
2. ~~**Scheduling**: Cron-like triggers (daily, hourly, etc.)~~ ✅ Implemented in v0.4.0
3. **Secrets Management**: Secure credential injection
4. **Plugins**: Custom node types (Docker, Kubernetes jobs)
5. **Lineage Tracking**: Track data provenance through pipelines
6. **Monitoring**: Prometheus metrics, Grafana dashboards
7. **Notification Nodes**: Email / Webhook (Slack, WeChat Work, Feishu) alerts on pipeline events

### Non-Goals

- Full Airflow compatibility
- Enterprise RBAC/multi-tenancy (use managed solutions)
- GUI-first workflow design (code-first philosophy)

---

## Contributing

See the [main README](../../README.md) for contribution guidelines.

## License

Apache License 2.0
