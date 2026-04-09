# 🧶 Dagloom

[![PyPI version](https://img.shields.io/pypi/v/dagloom.svg)](https://pypi.org/project/dagloom/)
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
│  Scheduler (asyncio executor)       │
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
├── scheduler/  # asyncio executor, caching, checkpoint
├── connectors/ # PostgreSQL, MySQL, S3, HTTP connectors
├── server/     # FastAPI REST API + WebSocket
├── store/      # SQLite storage layer
└── cli/        # Click CLI (serve, run, list, inspect)
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
