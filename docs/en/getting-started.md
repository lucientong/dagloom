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
│  Scheduler (asyncio executor)       │
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

### CLI Commands

| Command | Description |
|---------|-------------|
| `dagloom serve` | Start the web server |
| `dagloom run <file>` | Execute a pipeline |
| `dagloom list` | List registered pipelines |
| `dagloom inspect <file>` | Show DAG structure |
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
