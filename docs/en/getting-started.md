# Getting Started with Dagloom

> **v1.0.0 Stable Release** — Dagloom is now production-stable. The API is fully covered by semantic versioning guarantees.

## Installation

```bash
pip install dagloom   # v1.0.0 — production-stable
```

For data source connectors (PostgreSQL, MySQL, S3, HTTP):

```bash
pip install dagloom[connectors]
```

For additional connectors (v0.12.0):

```bash
pip install dagloom[mongodb]          # MongoDB
pip install dagloom[redis]            # Redis
pip install dagloom[kafka]            # Kafka
pip install dagloom[all-connectors]   # All connectors
```

For additional connectors (v0.12.0):

```bash
pip install dagloom[mongodb]          # MongoDB
pip install dagloom[redis]            # Redis
pip install dagloom[kafka]            # Kafka
pip install dagloom[all-connectors]   # All connectors
```

## Quick Demo

The fastest way to see Dagloom in action — no code required:

```bash
# Run the built-in demo ETL pipeline and print a sales summary report
dagloom demo --run
```

The demo pipeline uses the following DAG:

```
generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report
```

You can also customize the number of generated records:

```bash
dagloom demo --records 200
```

Or start the web server with the demo pipeline pre-registered:

```bash
dagloom demo
```

## Quick Demo

The fastest way to see Dagloom in action — no code required:

```bash
# Run the built-in demo ETL pipeline and print a sales summary report
dagloom demo --run
```

The demo pipeline uses the following DAG:

```
generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report
```

You can also customize the number of generated records:

```bash
dagloom demo --records 200
```

Or start the web server with the demo pipeline pre-registered:

```bash
dagloom demo
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

### 6. Credential Security Management (v0.9.0)

Dagloom now includes built-in credential security management. Secrets are encrypted at rest using Fernet symmetric encryption and resolved through a layered lookup: environment variables → `.env` file → encrypted database.

- `Encryptor` — provides Fernet encryption; the master key is read from the `DAGLOOM_MASTER_KEY` environment variable
- `SecretStore` — layered secret resolution: env vars → `.env` → encrypted DB
- CLI: `dagloom secret set/get/list/delete`
- REST API: `GET /api/secrets`, `POST /api/secrets`, `DELETE /api/secrets/{name}`

#### CLI Usage

```bash
# Generate a master key and export it
export DAGLOOM_MASTER_KEY=$(python -c "from dagloom.security import Encryptor; print(Encryptor.generate_key())")

# Store and retrieve secrets
dagloom secret set DB_PASSWORD "super-secret"
dagloom secret get DB_PASSWORD
```

#### Python Usage

```python
from dagloom.security import Encryptor, SecretStore

store = SecretStore(db=db, encryptor=Encryptor())
await store.set("API_KEY", "sk-abc123")
value = await store.get("API_KEY")
```

### 7. Observability & Metrics (v0.13.0)

Dagloom can automatically record per-node timing and outcome data. Pass a `Database` instance to `AsyncExecutor` to enable metrics:

```python
from dagloom.scheduler import AsyncExecutor
from dagloom.store import Database

db = Database()
await db.connect()

executor = AsyncExecutor(pipeline, metrics_db=db)
result = await executor.execute(url="https://...")
```

Every node execution is recorded to the `node_metrics` table with wall-clock time, outcome, retry count, and error message. No changes to node code are needed.

#### Querying Metrics

```python
# Aggregate stats per node: total_runs, success/failure count, avg/min/max/p50/p95 ms
stats = await db.get_node_stats("my_pipeline")

# Recent execution history with per-node metrics attached
history = await db.get_execution_history("my_pipeline", limit=20)
```

#### REST API

```bash
# Per-node aggregate stats
curl http://localhost:8000/api/metrics/my_pipeline

# Execution history with node detail
curl http://localhost:8000/api/history/my_pipeline?limit=10
```

### 8. Pipeline Version Management (v0.14.0)

Dagloom automatically versions your pipeline DAG every time you save changes via the UI. Each version is identified by a SHA-256 hash of the code snapshot — identical saves are deduplicated.

#### Listing Versions

```bash
# List recent versions for a pipeline
curl http://localhost:8000/api/pipelines/my_pipeline/versions?limit=10
```

```python
versions = await db.list_pipeline_versions("my_pipeline", limit=10)
# Returns: [{"version_hash": "a1b2...", "created_at": "...", ...}, ...]
```

#### Inspecting a Version

```bash
# Get the full snapshot (code, nodes, edges) for a specific version
curl http://localhost:8000/api/versions/a1b2c3d4...
```

#### Comparing Versions

```bash
# Structured diff between two versions: added/removed/unchanged nodes and edges, plus unified code diff
curl http://localhost:8000/api/versions/a1b2c3d4.../diff/e5f6a7b8...
```

The diff response includes:
- **Nodes**: `added`, `removed`, `unchanged`
- **Edges**: `added`, `removed`, `unchanged`
- **Code**: Unified diff (Python `difflib` format)

### 9. Web UI Components (v1.0.0)

The Dagloom Web UI now includes three dedicated views:

- **PipelineList** — Browse all registered pipelines with status indicators and quick-action buttons (run, pause, inspect)
- **MetricsDashboard** — Real-time and historical per-node metrics visualization (success rate, latency percentiles, throughput)
- **VersionHistory** — Side-by-side version comparison with structured diffs (added/removed nodes and edges, unified code diff)

Access the Web UI by running `dagloom serve` and opening `http://localhost:8000` in your browser.

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
| GET | `/api/secrets` | List all secrets |
| POST | `/api/secrets` | Create or update a secret |
| DELETE | `/api/secrets/{name}` | Delete a secret |
| GET | `/api/metrics/{pipeline_id}` | Per-node aggregate stats |
| GET | `/api/history/{pipeline_id}?limit=N` | Execution history with node detail |
| GET | `/api/pipelines/{id}/versions?limit=N` | List pipeline version history |
| GET | `/api/versions/{hash}` | Get specific version snapshot |
| GET | `/api/versions/{hash_a}/diff/{hash_b}` | Structured diff between two versions |

### CLI Commands

| Command | Description |
|---------|-------------|
| `dagloom serve` | Start the web server (with scheduler) |
| `dagloom run <file>` | Execute a pipeline |
| `dagloom demo` | Start web server with demo pipeline registered |
| `dagloom demo --run` | Run the demo ETL pipeline directly |
| `dagloom demo` | Start web server with demo pipeline registered |
| `dagloom demo --run` | Run the demo ETL pipeline directly |
| `dagloom list` | List registered pipelines |
| `dagloom inspect <file>` | Show DAG structure |
| `dagloom scheduler list` | List all schedules |
| `dagloom scheduler status` | Show scheduler status |
| `dagloom secret set <name> <value>` | Store a secret |
| `dagloom secret get <name>` | Retrieve a secret |
| `dagloom secret list` | List all secret names |
| `dagloom secret delete <name>` | Delete a secret |
| `dagloom secret set <name> <value>` | Store a secret |
| `dagloom secret get <name>` | Retrieve a secret |
| `dagloom secret list` | List all secret names |
| `dagloom secret delete <name>` | Delete a secret |
| `dagloom version` | Show version info |

## Authentication (v0.11.0)

Dagloom supports optional request-level authentication for the web server. By default, auth is disabled (open access).

### Enabling Authentication

Pass `--auth-type` and `--auth-key` to `dagloom serve`:

```bash
# API key authentication — clients send "Authorization: Bearer <key>"
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic authentication — clients send standard HTTP Basic credentials
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password
```

Or use environment variables:

```bash
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### Public Paths

The following paths are always accessible without credentials:

- `/health` — health check
- `/docs` — Swagger UI
- `/openapi.json` — OpenAPI spec
- `/redoc` — ReDoc UI

### Calling Authenticated Endpoints

```bash
# API key
curl -H "Authorization: Bearer sk-abc123" http://localhost:8000/api/pipelines

# Basic auth
curl -u admin:password http://localhost:8000/api/pipelines
```

```python
import httpx

# API key
resp = httpx.get("http://localhost:8000/api/pipelines",
                 headers={"Authorization": "Bearer sk-abc123"})

# Basic auth
resp = httpx.get("http://localhost:8000/api/pipelines",
                 auth=("admin", "password"))
```

## Authentication (v0.11.0)

Dagloom supports optional request-level authentication for the web server. By default, auth is disabled (open access).

### Enabling Authentication

Pass `--auth-type` and `--auth-key` to `dagloom serve`:

```bash
# API key authentication — clients send "Authorization: Bearer <key>"
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic authentication — clients send standard HTTP Basic credentials
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password
```

Or use environment variables:

```bash
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### Public Paths

The following paths are always accessible without credentials:

- `/health` — health check
- `/docs` — Swagger UI
- `/openapi.json` — OpenAPI spec
- `/redoc` — ReDoc UI

### Calling Authenticated Endpoints

```bash
# API key
curl -H "Authorization: Bearer sk-abc123" http://localhost:8000/api/pipelines

# Basic auth
curl -u admin:password http://localhost:8000/api/pipelines
```

```python
import httpx

# API key
resp = httpx.get("http://localhost:8000/api/pipelines",
                 headers={"Authorization": "Bearer sk-abc123"})

# Basic auth
resp = httpx.get("http://localhost:8000/api/pipelines",
                 auth=("admin", "password"))
```

## Connectors

Dagloom provides built-in connectors for common data sources. All connectors follow the `BaseConnector` pattern with async context manager support.

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

### MongoDB (v0.12.0)

Requires `motor>=3.3`. Install: `pip install dagloom[mongodb]`

```python
from dagloom.connectors.mongodb import MongoDBConnector

config = ConnectionConfig(host="localhost", port=27017, database="mydb")

async with MongoDBConnector(config) as mongo:
    await mongo.insert_one("users", {"name": "Alice", "age": 30})
    user = await mongo.find_one("users", {"name": "Alice"})
    users = await mongo.find("users", {"age": {"$gte": 18}})
    await mongo.update_one("users", {"name": "Alice"}, {"$set": {"age": 31}})
    await mongo.delete_one("users", {"name": "Alice"})
    results = await mongo.aggregate("orders", [{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
```

Operations: `find`, `find_one`, `insert_one`, `insert_many`, `update_one`, `update_many`, `delete_one`, `delete_many`, `aggregate`, `count`.

### Redis (v0.12.0)

Requires `redis>=5.0`. Install: `pip install dagloom[redis]`

```python
from dagloom.connectors.redis import RedisConnector

config = ConnectionConfig(host="localhost", port=6379)

async with RedisConnector(config) as r:
    await r.set("key", "value")
    value = await r.get("key")
    await r.hset("user:1", "name", "Alice")
    name = await r.hget("user:1", "name")
    await r.delete("key")
```

Commands are mapped directly: `get`, `set`, `delete`, `hget`, `hset`, etc.

### Kafka (v0.12.0)

Requires `aiokafka>=0.9`. Install: `pip install dagloom[kafka]`

```python
from dagloom.connectors.kafka import KafkaConnector

config = ConnectionConfig(host="localhost", port=9092)

async with KafkaConnector(config) as kafka:
    await kafka.send("my-topic", value=b'{"event": "order_created"}')
    messages = await kafka.consume("my-topic", timeout=5.0)
```

Operations: `send` (produce), `consume` (temporary consumer).

Available connectors: **PostgreSQL**, **MySQL**, **S3/MinIO**, **HTTP API**, **MongoDB**, **Redis**, **Kafka**.
