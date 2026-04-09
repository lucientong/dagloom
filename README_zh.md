# 🧶 Dagloom

[![PyPI version](https://img.shields.io/pypi/v/dagloom.svg)](https://pypi.org/project/dagloom/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/dagloom?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/dagloom)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](https://github.com/lucientong/dagloom/blob/master/LICENSE)

**如同织布机将丝线编织成织物，Dagloom 将数据处理节点编织成 DAG 工作流。**

一个轻量级的 Python 管道/工作流引擎。使用装饰器定义节点，用 `>>` 运算符连接它们，在可拖拽的 Web UI 中可视化和编辑。

[English](https://github.com/lucientong/dagloom/blob/master/README.md)

---

## ✨ 为什么选择 Dagloom？

| 痛点 | 竞品方案 | Dagloom |
|------|---------|---------|
| **安装过于复杂** | Airflow 需要 PostgreSQL + Redis + Celery + Webserver | `pip install dagloom && dagloom serve` |
| **概念过多** | Dagster: Assets, Ops, Jobs, Resources, IO Managers... | 只需 `@node` 和 `>>` |
| **代码与可视化脱节** | Airflow UI 只读，无法同步编辑 | 真正的双向同步 |
| **失败后无法续跑** | 必须重新执行整个管道 | `dagloom resume` 从断点继续 |
| **只支持 Shell 节点** | Dagu 只支持 Shell 命令 | 原生 Python 对象（DataFrame、dict、类） |

## 🚀 快速开始

### 安装

```bash
pip install dagloom
```

### 你的第一个管道

```python
from dagloom import node, Pipeline

@node
def greet(name: str) -> str:
    """创建问候消息。"""
    return f"Hello, {name}!"

@node
def shout(message: str) -> str:
    """将消息转为大写。"""
    return message.upper()

@node
def add_emoji(message: str) -> str:
    """添加表情符号。"""
    return f"🎉 {message} 🎉"

# 用 >> 运算符构建 DAG
pipeline = greet >> shout >> add_emoji

# 运行管道
result = pipeline.run(name="World")
print(result)  # 🎉 HELLO, WORLD! 🎉
```

### 高级特性

```python
@node(retry=3, cache=True, timeout=30.0)
def fetch_data(url: str) -> pd.DataFrame:
    """带重试、缓存和超时的数据获取。"""
    return pd.read_csv(url)

@node(cache=True)
def clean(df: pd.DataFrame) -> pd.DataFrame:
    """删除缺失值行。"""
    return df.dropna()

@node
def save(df: pd.DataFrame) -> str:
    """将清洗后的数据保存为 parquet 文件。"""
    path = "output/cleaned.parquet"
    df.to_parquet(path)
    return path

pipeline = fetch_data >> clean >> save
pipeline.run(url="https://example.com/data.csv")
```

### 启动 Web UI

```bash
dagloom serve
# 在浏览器中打开 http://localhost:8000
```

## 🏗️ 架构

```
单进程架构
┌─────────────────────────────────────┐
│  CLI / Web UI                       │
├─────────────────────────────────────┤
│  FastAPI (REST API + WebSocket)     │
├─────────────────────────────────────┤
│  调度器（asyncio 执行器）             │
├─────────────────────────────────────┤
│  核心（@node + Pipeline + DAG）      │
├─────────────────────────────────────┤
│  SQLite（内嵌，零配置）               │
└─────────────────────────────────────┘
```

## 📦 项目结构

```
dagloom/
├── core/       # @node 装饰器、Pipeline 类、DAG 验证
├── scheduler/  # asyncio 执行器、缓存、检查点
├── connectors/ # PostgreSQL、MySQL、S3、HTTP 连接器
├── server/     # FastAPI REST API + WebSocket
├── store/      # SQLite 存储层
└── cli/        # Click CLI（serve、run、list、inspect）
```

## 📖 核心概念

### 节点（Node）

**节点** 是被 `@node` 装饰的 Python 函数——管道中的原子处理单元。

```python
@node
def my_step(input_data: dict) -> dict:
    return process(input_data)
```

节点支持以下配置：
- **retry**: 失败后自动重试次数（指数退避策略）
- **cache**: 基于输入哈希缓存输出——输入不变时跳过重复计算
- **timeout**: 最大执行时间（秒）

### 管道（Pipeline）

**管道** 是由节点组成的 DAG（有向无环图），使用 `>>` 运算符构建。

```python
# 线性管道
pipeline = fetch >> clean >> transform >> save

# 分支管道
pipeline = fetch >> (process_a | process_b) >> merge
```

### 执行模式

```python
# 同步执行
result = pipeline.run(url="https://...")

# 异步执行（同层节点并发运行）
import asyncio
from dagloom.scheduler import AsyncExecutor

executor = AsyncExecutor(pipeline)
result = asyncio.run(executor.execute(url="https://..."))
```

## 🔌 CLI 命令

| 命令 | 描述 |
|------|------|
| `dagloom serve` | 启动 Web 服务 |
| `dagloom run <文件>` | 执行管道文件 |
| `dagloom list` | 列出已注册的管道 |
| `dagloom inspect <文件>` | 查看 DAG 结构 |
| `dagloom version` | 显示版本信息 |

## 🔗 REST API

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/pipelines` | 列出所有管道 |
| POST | `/api/pipelines/{id}/run` | 触发管道执行 |
| GET | `/api/pipelines/{id}/status` | 获取执行状态 |
| POST | `/api/pipelines/{id}/resume` | 从检查点恢复执行 |
| GET | `/api/pipelines/{id}/dag` | 获取 DAG 结构 |
| PUT | `/api/pipelines/{id}/dag` | 从 UI 更新 DAG |

## 📚 连接器

Dagloom 内置常见数据源的连接器：

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

**可用连接器**：PostgreSQL、MySQL、S3/MinIO、HTTP API

## 📖 文档

- [快速入门](https://github.com/lucientong/dagloom/blob/master/docs/zh/getting-started.md)
- [架构文档](https://github.com/lucientong/dagloom/blob/master/docs/zh/ARCHITECTURE.md)
- [English Documentation](https://github.com/lucientong/dagloom/blob/master/docs/en/getting-started.md)

## 🤝 贡献指南

欢迎贡献！请按以下步骤操作：

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 📄 许可证

Apache License 2.0 — 详见 [LICENSE](https://github.com/lucientong/dagloom/blob/master/LICENSE)。
