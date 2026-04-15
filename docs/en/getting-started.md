# Getting Started with Dagloom

## Installation

```bash
pip install dagloom
```

For data source connectors (PostgreSQL, MySQL, S3, HTTP):

```bash
pip install dagloom[connectors]
```

## Quick Start

### 1. Define Your First Pipeline

Create a file `my_pipeline.py`:

```python
from dagloom import node

@node
def greet(name: str) -> str:
    """Create a greeting message."""
    return f"Hello, {name}!"

@node
def shout(message: str) -> str:
    """Convert message to uppercase."""
    return message.upper()

@node
def add_emoji(message: str) -> str:
    """Add emoji to the message."""
    return f"🎉 {message} 🎉"

# Build DAG with >> operator
pipeline = greet >> shout >> add_emoji

if __name__ == "__main__":
    result = pipeline.run(name="World")
    print(result)  # 🎉 HELLO, WORLD! 🎉
```

### 2. Run from CLI

```bash
# Run a pipeline file
dagloom run my_pipeline.py -i name=World

# Inspect the DAG structure
dagloom inspect my_pipeline.py

# Start the web UI
dagloom serve
```

### 3. Advanced Node Configuration

```python
@node(retry=3, cache=True, timeout=30.0)
def fetch_data(url: str) -> list[dict]:
    """Fetch data with retry, caching, and timeout."""
    import httpx
    resp = httpx.get(url)
    return resp.json()
```

- **retry**: Number of automatic retries on failure (exponential backoff)
- **cache**: Cache output based on input hash — skip re-computation if inputs unchanged
- **timeout**: Maximum execution time in seconds

### 4. Cache Dependency Invalidation (v0.7.0)

When using `@node(cache=True)`, Dagloom now automatically invalidates downstream caches if an upstream node produces different output on re-execution. This ensures downstream nodes always re-execute with fresh data — no manual cache-busting required. Internally, Dagloom uses `networkx.descendants()` to traverse the DAG and identify all affected downstream nodes.

No API changes are needed — this works transparently with existing `cache=True` nodes:

```python
@node(cache=True)
def fetch(url: str) -> list:
    return requests.get(url).json()

@node(cache=True)
def transform(data: list) -> list:
    return [x * 2 for x in data]

@node(cache=True)
def save(data: list) -> str:
    return f"Saved {len(data)} records"

pipeline = fetch >> transform >> save

# First run: all three nodes execute and cache their outputs.
# Second run: if fetch returns the same data, all caches hit — nothing re-executes.
# If fetch returns *different* data, transform and save caches are
# automatically invalidated and both re-execute with the new data.
```

### 5. Per-Node Executor Hints (v0.8.0)

You can now control how each node is executed by passing the `executor` hint to `@node`. This lets you mix CPU-bound process isolation with async I/O in the same pipeline.

- `@node(executor="process")` — runs the function in a separate process (ideal for CPU-bound work)
- `@node(executor="async")` — forces asyncio execution
- `@node(executor="auto")` (default) — uses threads for sync functions, `await` for async functions

Executor hints work with both `AsyncExecutor` and `ProcessExecutor`.

```python
@node
def fetch(url: str) -> list:
    return [1, 2, 3]

@node(executor="process")
def heavy_compute(data: list) -> list:
    return [x ** 2 for x in data]

pipeline = fetch >> heavy_compute
```

In this example `fetch` uses the default executor (threaded, since it is a sync function), while `heavy_compute` is offloaded to a separate process — keeping the main event loop responsive while crunching numbers.

### 5. Per-Node Executor Hints (v0.8.0)

You can now control how each node is executed by passing the `executor` hint to `@node`. This lets you mix CPU-bound process isolation with async I/O in the same pipeline.

- `@node(executor="process")` — runs the function in a separate process (ideal for CPU-bound work)
- `@node(executor="async")` — forces asyncio execution
- `@node(executor="auto")` (default) — uses threads for sync functions, `await` for async functions

Executor hints work with both `AsyncExecutor` and `ProcessExecutor`.

```python
@node
def fetch(url: str) -> list:
    return [1, 2, 3]

@node(executor="process")
def heavy_compute(data: list) -> list:
    return [x ** 2 for x in data]

pipeline = fetch >> heavy_compute
```

In this example `fetch` uses the default executor (threaded, since it is a sync function), while `heavy_compute` is offloaded to a separate process — keeping the main event loop responsive while crunching numbers.

## Core Concepts

### Node

A **Node** is a decorated Python function — the atomic unit of a pipeline.

```python
@node
def my_step(input_data: dict) -> dict:
    return process(input_data)
```

### Pipeline

A **Pipeline** is a DAG (Directed Acyclic Graph) of connected nodes, built with the `>>` operator.

```python
pipeline = fetch >> clean >> transform >> save
```

### Conditional Branching

Use the `|` operator to create mutually exclusive branches — the runtime selects which branch to execute based on the upstream output:

```python
@node
def classify(text: str) -> dict:
    if "urgent" in text:
        return {"branch": "urgent_handler", "text": text}
    return {"branch": "normal_handler", "text": text}

@node
def urgent_handler(data: dict) -> str:
    return f"🚨 URGENT: {data['text']}"

@node
def normal_handler(data: dict) -> str:
    return f"📋 Normal: {data['text']}"

pipeline = classify >> (urgent_handler | normal_handler)
result = pipeline.run(text="urgent: server down!")
```

Branch selection rules:
1. If upstream output is a `dict` with a `"branch"` key → match by name
2. Two-branch groups: truthy → first branch, falsy → second branch
3. Fallback: first branch

### Streaming Nodes (Generator)

Node functions can be generators — yielded values are automatically collected into a list:

```python
@node
def stream_data(url: str):
    for i in range(5):
        yield {"chunk": i, "url": url}

@node
def aggregate(chunks: list[dict]) -> int:
    return len(chunks)

pipeline = stream_data >> aggregate
result = pipeline.run(url="https://example.com")
# 5
```

Async generators (`async def` + `yield`) are also supported.

### Execution Hooks

Monitor node execution with `on_node_start` / `on_node_end` callbacks:

```python
from dagloom import AsyncExecutor

def my_hook(node_name, ctx):
    print(f"  → {node_name}: {ctx.get_node_info(node_name).status}")

executor = AsyncExecutor(
    pipeline,
    on_node_start=my_hook,
    on_node_end=my_hook,
)
result = asyncio.run(executor.execute(x=1))
```

Hooks can be sync or async functions. Hook exceptions do not interrupt pipeline execution.

### Pipeline Scheduling

Schedule pipelines to run automatically:

```python
from dagloom import Pipeline

# Cron expression (daily at 9am)
pipeline = Pipeline(name="daily_etl", schedule="0 9 * * *")

# Interval shorthand (every 30 minutes)
pipeline = Pipeline(name="monitor", schedule="every 30m")

# Set after construction
pipeline = fetch >> process >> save
pipeline.name = "my_pipeline"
pipeline.schedule = "0 9 * * 1-5"  # Weekdays at 9am
```

Schedules are persisted to SQLite and auto-restored when `dagloom serve` restarts.

### Notifications (Email / Webhook)

Get notified when pipelines succeed or fail:

```python
pipeline.notify_on = {
    "failure": ["email://ops@team.com", "webhook://https://hooks.slack.com/xxx?format=slack"],
    "success": ["webhook://https://hooks.slack.com/yyy?format=slack"],
}
```

Supported: Email (SMTP), Slack (Block Kit), WeChat Work, Feishu, Generic Webhook.

### Execution

Pipelines execute in **topological order** — independent nodes in the same layer run in parallel.

```python
# Synchronous execution
result = pipeline.run(url="https://...")

# Async execution
import asyncio
from dagloom.scheduler import AsyncExecutor

executor = AsyncExecutor(pipeline)
result = asyncio.run(executor.execute(url="https://..."))
```

## Architecture

```
Single Process Architecture
┌─────────────────────────────────────┐
│  CLI / Web UI                       │
├─────────────────────────────────────┤
│  FastAPI (REST API + WebSocket)     │
├─────────────────────────────────────┤
│  Scheduler (APScheduler + asyncio)  │
├─────────────────────────────────────┤
│  Core (@node + Pipeline + DAG)      │
├─────────────────────────────────────┤
│  SQLite (embedded, zero config)     │
└─────────────────────────────────────┘
```

## API Reference

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pipelines` | List all pipelines |
| POST | `/api/pipelines/{id}/run` | Trigger pipeline execution |
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

### CLI Commands

| Command | Description |
|---------|-------------|
| `dagloom serve` | Start the web server (with scheduler) |
| `dagloom run <file>` | Execute a pipeline |
| `dagloom list` | List registered pipelines |
| `dagloom inspect <file>` | Show DAG structure |
| `dagloom scheduler list` | List all schedules |
| `dagloom scheduler status` | Show scheduler status |
| `dagloom version` | Show version info |

## Connectors

Dagloom provides built-in connectors for common data sources:

```python
from dagloom.connectors import ConnectionConfig
from dagloom.connectors.postgres import PostgresConnector

config = ConnectionConfig(
    host="localhost", port=5432,
    database="mydb", username="user", password="pass"
)

async with PostgresConnector(config) as pg:
    rows = await pg.execute("SELECT * FROM users WHERE active = $1", True)
```

Available connectors: **PostgreSQL**, **MySQL**, **S3/MinIO**, **HTTP API**.
