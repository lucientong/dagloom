# 🧶 Dagloom

[![PyPI version](https://img.shields.io/pypi/v/dagloom.svg)](https://pypi.org/project/dagloom/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/dagloom?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/dagloom)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](https://github.com/lucientong/dagloom/blob/master/LICENSE)

**Like a loom weaving threads into fabric, Dagloom weaves data processing nodes into DAG workflows.**

A lightweight pipeline/workflow engine for Python. Define nodes with decorators, connect them with the `>>` operator, visualize and edit in a drag-and-drop Web UI.

[中文文档](https://github.com/lucientong/dagloom/blob/master/README_zh.md)

---

## ✨ Why Dagloom?

| Problem | Competitors | Dagloom |
|---------|------------|---------|
| **Overkill installation** | Airflow needs PostgreSQL + Redis + Celery + Webserver | `pip install dagloom && dagloom serve` |
| **Too many concepts** | Dagster: Assets, Ops, Jobs, Resources, IO Managers... | Just `@node` and `>>` |
| **Code/visual disconnect** | Airflow UI is read-only | True bidirectional sync |
| **Can't resume from failure** | Re-run the entire pipeline | `dagloom resume` picks up where it left off |
| **Shell-only nodes** | Dagu only supports shell commands | Native Python objects (DataFrames, dicts, classes) |

## 🚀 Quick Start

### Installation

```bash
pip install dagloom
```

### Your First Pipeline

```python
from dagloom import node, Pipeline

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

# Run the pipeline
result = pipeline.run(name="World")
print(result)  # 🎉 HELLO, WORLD! 🎉
```

### Conditional Branching

Use the `|` operator to create mutually exclusive branches — the runtime selects which branch to execute based on the upstream output:

```python
from dagloom import node

@node
def classify(text: str) -> dict:
    """Route to different processors."""
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
# 🚨 URGENT: urgent: server down!
```

### Streaming Nodes (Generator)

Node functions can be generators — yielded values are automatically collected into a list:

```python
@node
def stream_data(url: str):
    """Yield data chunks."""
    for i in range(5):
        yield {"chunk": i, "url": url}

@node
def aggregate(chunks: list[dict]) -> int:
    return len(chunks)

pipeline = stream_data >> aggregate
result = pipeline.run(url="https://example.com")
# 5
```

### Execution Hooks

Monitor node execution with `on_node_start` / `on_node_end` callbacks:

```python
import asyncio
from dagloom import node, AsyncExecutor

@node
def step(x: int) -> int:
    return x + 1

pipeline = step

def my_hook(node_name, ctx):
    print(f"  → {node_name}: {ctx.get_node_info(node_name).status}")

executor = AsyncExecutor(
    pipeline,
    on_node_start=my_hook,
    on_node_end=my_hook,
)
result = asyncio.run(executor.execute(x=1))
```

### Pipeline Scheduling

Schedule pipelines to run automatically on cron expressions or fixed intervals:

```python
from dagloom import node, Pipeline

@node
def fetch(url: str = "https://example.com/data.csv") -> list:
    return [1, 2, 3]

@node
def process(data: list) -> int:
    return sum(data)

# Set schedule via Pipeline constructor
pipeline = Pipeline(name="daily_etl", schedule="0 9 * * *")

# Or use interval shorthand
pipeline = Pipeline(name="frequent_check", schedule="every 30m")

# Or set after construction
pipeline = fetch >> process
pipeline.name = "my_pipeline"
pipeline.schedule = "0 9 * * 1-5"  # Weekdays at 9am
```

The scheduler runs in-process with `dagloom serve` — schedules are persisted to SQLite and auto-restored on restart.

### Notifications (Email / Webhook)

Get notified when pipelines succeed or fail:

```python
from dagloom import node, Pipeline

@node
def fetch(url: str = "https://example.com") -> dict:
    return {"data": [1, 2, 3]}

@node
def process(data: dict) -> int:
    return sum(data["data"])

pipeline = fetch >> process
pipeline.name = "daily_etl"
pipeline.notify_on = {
    "failure": ["email://ops@team.com", "webhook://https://hooks.slack.com/xxx?format=slack"],
    "success": ["webhook://https://hooks.slack.com/yyy?format=slack"],
}
```

Supported channels:
- **Email**: `email://recipient@example.com` — SMTP delivery via `aiosmtplib`
- **Slack**: `webhook://https://hooks.slack.com/...?format=slack` — Block Kit formatting
- **WeChat Work**: `webhook://https://qyapi.weixin.qq.com/...?format=wechat_work`
- **Feishu**: `webhook://https://open.feishu.cn/...?format=feishu`
- **Generic Webhook**: `webhook://https://your-endpoint.com/hook` — plain JSON POST

### Advanced Features

```python
@node(retry=3, cache=True, timeout=30.0)
def fetch_data(url: str) -> pd.DataFrame:
    """Fetch CSV data with retry and caching."""
    return pd.read_csv(url)

@node(cache=True)
def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows with missing values."""
    return df.dropna()

@node
def save(df: pd.DataFrame) -> str:
    """Persist cleaned data to parquet file."""
    path = "output/cleaned.parquet"
    df.to_parquet(path)
    return path

pipeline = fetch_data >> clean >> save
pipeline.run(url="https://example.com/data.csv")
```

**Cache dependency invalidation**: When `fetch_data` produces a different output on re-run, Dagloom automatically invalidates the caches for `clean` and `save` so they re-execute with fresh data. No manual cache management needed.

### Per-Node Executor Hints

Control execution strategy per node — run CPU-heavy work in separate processes while keeping I/O-bound nodes in the event loop:

```python
from dagloom import node, AsyncExecutor

@node
def fetch(url: str) -> list:
    """I/O-bound: runs in thread (default)."""
    return [1, 2, 3]

@node(executor="process")
def transform(data: list) -> list:
    """CPU-bound: runs in a separate process."""
    return [x ** 2 for x in data]

@node
async def save(data: list) -> str:
    """Async: awaited directly on the event loop."""
    return f"Saved {len(data)} records"

pipeline = fetch >> transform >> save
executor = AsyncExecutor(pipeline)
result = await executor.execute(url="https://example.com")
```

### Start the Web UI

```bash
dagloom serve
# Open http://localhost:8000 in your browser
```

## 🏗️ Architecture

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

## 📦 Project Structure

```
dagloom/
├── core/       # @node decorator, Pipeline class, DAG validation
├── scheduler/  # Cron/interval scheduler, asyncio executor, caching, checkpoint
├── connectors/ # PostgreSQL, MySQL, S3, HTTP connectors
├── server/     # FastAPI REST API + WebSocket
├── store/      # SQLite storage layer
└── cli/        # Click CLI (serve, run, list, inspect, scheduler)
```

## 📖 Documentation

- [中文文档](https://github.com/lucientong/dagloom/blob/master/README_zh.md)
- [Architecture Guide](https://github.com/lucientong/dagloom/blob/master/docs/en/ARCHITECTURE.md) | [架构文档](https://github.com/lucientong/dagloom/blob/master/docs/zh/ARCHITECTURE.md)
- [Getting Started (EN)](https://github.com/lucientong/dagloom/blob/master/docs/en/getting-started.md) | [快速入门 (中文)](https://github.com/lucientong/dagloom/blob/master/docs/zh/getting-started.md)

## 🤝 Contributing

Contributions are welcome! Please feel free to:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

Apache License 2.0 — see [LICENSE](https://github.com/lucientong/dagloom/blob/master/LICENSE) for details.
