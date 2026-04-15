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

### 4. 缓存依赖自动失效（v0.7.0）

使用 `@node(cache=True)` 时，Dagloom 现在会自动处理缓存的级联失效：当上游节点重新执行后产生了不同的输出，所有下游节点的缓存会被自动清除，确保下游节点在下次运行时使用最新数据重新计算。底层通过 `networkx.descendants()` 遍历 DAG 来定位所有受影响的下游节点。

无需任何 API 变更，已有的 `cache=True` 节点即可自动享受此特性：

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

# 第一次运行：三个节点依次执行，结果均被缓存。
# 第二次运行：若 fetch 返回的数据与上次相同，全部命中缓存，无需重新执行。
# 若 fetch 返回了不同的数据，transform 和 save 的缓存会被自动失效，
# 两者将使用新数据重新执行。
```

### 5. 逐节点执行器提示（v0.8.0）

现在可以通过向 `@node` 传递 `executor` 参数来控制每个节点的执行方式，从而在同一管道中混合使用 CPU 密集型进程隔离与异步 I/O。

- `@node(executor="process")` — 在独立进程中运行函数（适用于 CPU 密集型任务）
- `@node(executor="async")` — 强制使用 asyncio 执行
- `@node(executor="auto")`（默认）— 同步函数使用线程，异步函数使用 `await`

执行器提示可与 `AsyncExecutor` 和 `ProcessExecutor` 配合使用。

```python
@node
def fetch(url: str) -> list:
    return [1, 2, 3]

@node(executor="process")
def heavy_compute(data: list) -> list:
    return [x ** 2 for x in data]

pipeline = fetch >> heavy_compute
```

在此示例中，`fetch` 使用默认执行器（因为它是同步函数，所以使用线程），而 `heavy_compute` 被分派到独立进程中执行——在进行大量计算时不会阻塞主事件循环。

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

### 条件分支（Branch）

使用 `|` 运算符创建互斥分支——运行时根据上游输出自动选择执行哪个分支：

```python
@node
def classify(text: str) -> dict:
    if "紧急" in text:
        return {"branch": "urgent_handler", "text": text}
    return {"branch": "normal_handler", "text": text}

@node
def urgent_handler(data: dict) -> str:
    return f"🚨 紧急: {data['text']}"

@node
def normal_handler(data: dict) -> str:
    return f"📋 普通: {data['text']}"

pipeline = classify >> (urgent_handler | normal_handler)
result = pipeline.run(text="紧急: 服务器宕机!")
```

分支选择规则：
1. 上游输出是 `dict` 且包含 `"branch"` 键 → 按名称匹配
2. 双分支组：truthy → 第一个分支，falsy → 第二个分支
3. 兜底：默认第一个分支

### 流式节点（Generator）

节点函数可以是生成器——yield 的值自动收集为列表：

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

同时也支持异步生成器（`async def` + `yield`）。

### 执行钩子

通过 `on_node_start` / `on_node_end` 回调监控节点执行：

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

钩子可以是同步函数或异步函数，异常不会中断管道执行。

### 定时调度

支持 Cron 表达式或固定间隔自动运行管道：

```python
from dagloom import Pipeline

# Cron 表达式（每天 9 点）
pipeline = Pipeline(name="daily_etl", schedule="0 9 * * *")

# 间隔简写（每 30 分钟）
pipeline = Pipeline(name="monitor", schedule="every 30m")

# 构造后设置
pipeline = fetch >> process >> save
pipeline.name = "my_pipeline"
pipeline.schedule = "0 9 * * 1-5"  # 工作日每天 9 点
```

调度配置持久化到 SQLite，`dagloom serve` 重启后自动恢复。

### 通知（Email / Webhook）

管道成功或失败时自动发送通知：

```python
pipeline.notify_on = {
    "failure": ["email://ops@team.com", "webhook://https://hooks.slack.com/xxx?format=slack"],
    "success": ["webhook://https://hooks.slack.com/yyy?format=slack"],
}
```

支持：Email（SMTP）、Slack（Block Kit）、企业微信、飞书、通用 Webhook。

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
│  调度器（APScheduler + asyncio）      │
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
| GET | `/api/schedules` | 列出所有定时调度 |
| POST | `/api/schedules` | 创建定时调度 |
| DELETE | `/api/schedules/{id}` | 删除定时调度 |
| POST | `/api/schedules/{id}/pause` | 暂停调度 |
| POST | `/api/schedules/{id}/resume` | 恢复调度 |
| GET | `/api/notifications` | 列出通知渠道 |
| POST | `/api/notifications` | 创建通知渠道 |
| DELETE | `/api/notifications/{id}` | 删除通知渠道 |
| POST | `/api/notifications/test` | 发送测试通知 |

### CLI 命令

| 命令 | 描述 |
|------|------|
| `dagloom serve` | 启动 Web 服务（含调度器） |
| `dagloom run <文件>` | 执行管道 |
| `dagloom list` | 列出已注册的管道 |
| `dagloom inspect <文件>` | 查看 DAG 结构 |
| `dagloom scheduler list` | 列出所有定时调度 |
| `dagloom scheduler status` | 查看调度器状态 |
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
