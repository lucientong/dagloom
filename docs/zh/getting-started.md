# Dagloom 快速入门

## 安装

```bash
pip install dagloom
```

安装数据源连接器（PostgreSQL、MySQL、S3、HTTP）：

```bash
pip install dagloom[connectors]
```

## 快速开始

### 1. 定义你的第一个管道

创建文件 `my_pipeline.py`：

```python
from dagloom import node

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

if __name__ == "__main__":
    result = pipeline.run(name="World")
    print(result)  # 🎉 HELLO, WORLD! 🎉
```

### 2. 通过 CLI 运行

```bash
# 运行管道文件
dagloom run my_pipeline.py -i name=World

# 查看 DAG 结构
dagloom inspect my_pipeline.py

# 启动 Web UI
dagloom serve
```

### 3. 高级节点配置

```python
@node(retry=3, cache=True, timeout=30.0)
def fetch_data(url: str) -> list[dict]:
    """带重试、缓存和超时的数据获取。"""
    import httpx
    resp = httpx.get(url)
    return resp.json()
```

- **retry**: 失败时自动重试次数（指数退避策略）
- **cache**: 基于输入哈希缓存输出 — 输入未变时跳过重复计算
- **timeout**: 最大执行时间（秒）

## 核心概念

### 节点（Node）

**节点** 是一个被装饰的 Python 函数 — 管道中的原子单元。

```python
@node
def my_step(input_data: dict) -> dict:
    return process(input_data)
```

### 管道（Pipeline）

**管道** 是由节点连接而成的 DAG（有向无环图），通过 `>>` 运算符构建。

```python
pipeline = fetch >> clean >> transform >> save
```

### 执行

管道按 **拓扑排序** 执行 — 同层独立节点自动并行运行。

```python
# 同步执行
result = pipeline.run(url="https://...")

# 异步执行
import asyncio
from dagloom.scheduler import AsyncExecutor

executor = AsyncExecutor(pipeline)
result = asyncio.run(executor.execute(url="https://..."))
```

## 架构

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

## API 参考

### REST API

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/pipelines` | 列出所有管道 |
| POST | `/api/pipelines/{id}/run` | 触发管道执行 |
| GET | `/api/pipelines/{id}/status` | 获取执行状态 |
| POST | `/api/pipelines/{id}/resume` | 从检查点恢复 |
| GET | `/api/pipelines/{id}/dag` | 获取 DAG 结构 |
| PUT | `/api/pipelines/{id}/dag` | 从 UI 更新 DAG |

### CLI 命令

| 命令 | 描述 |
|------|------|
| `dagloom serve` | 启动 Web 服务 |
| `dagloom run <文件>` | 执行管道 |
| `dagloom list` | 列出已注册的管道 |
| `dagloom inspect <文件>` | 查看 DAG 结构 |
| `dagloom version` | 显示版本信息 |

## 连接器

Dagloom 内置了常见数据源的连接器：

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

可用连接器：**PostgreSQL**、**MySQL**、**S3/MinIO**、**HTTP API**。
