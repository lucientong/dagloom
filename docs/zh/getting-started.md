# Dagloom 快速入门

## 安装

```bash
pip install dagloom
```

安装数据源连接器（PostgreSQL、MySQL、S3、HTTP）：

```bash
pip install dagloom[connectors]
```

安装额外连接器（v0.12.0）：

```bash
pip install dagloom[mongodb]          # MongoDB
pip install dagloom[redis]            # Redis
pip install dagloom[kafka]            # Kafka
pip install dagloom[all-connectors]   # 所有连接器
```

安装额外连接器（v0.12.0）：

```bash
pip install dagloom[mongodb]          # MongoDB
pip install dagloom[redis]            # Redis
pip install dagloom[kafka]            # Kafka
pip install dagloom[all-connectors]   # 所有连接器
```

## 一键体验

无需编写代码，即可快速体验 Dagloom：

```bash
# 运行内置的 ETL 演示管道，输出销售汇总报告
dagloom demo --run
```

演示管道使用以下 DAG 结构：

```
generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report
```

可自定义生成的数据记录数：

```bash
dagloom demo --records 200
```

也可以启动 Web 服务并预注册演示管道：

```bash
dagloom demo
```

## 一键体验

无需编写代码，即可快速体验 Dagloom：

```bash
# 运行内置的 ETL 演示管道，输出销售汇总报告
dagloom demo --run
```

演示管道使用以下 DAG 结构：

```
generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report
```

可自定义生成的数据记录数：

```bash
dagloom demo --records 200
```

也可以启动 Web 服务并预注册演示管道：

```bash
dagloom demo
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

### 6. 凭据安全管理（v0.9.0）

Dagloom 现已内置凭据安全管理功能。密钥使用 Fernet 对称加密进行静态加密，并通过分层查找进行解析：环境变量 → `.env` 文件 → 加密数据库。

- `Encryptor` — 提供 Fernet 加密；主密钥从环境变量 `DAGLOOM_MASTER_KEY` 读取
- `SecretStore` — 分层密钥解析：环境变量 → `.env` → 加密数据库
- CLI：`dagloom secret set/get/list/delete`
- REST API：`GET /api/secrets`、`POST /api/secrets`、`DELETE /api/secrets/{name}`

#### CLI 用法

```bash
# 生成主密钥并导出
export DAGLOOM_MASTER_KEY=$(python -c "from dagloom.security import Encryptor; print(Encryptor.generate_key())")

# 存储和检索密钥
dagloom secret set DB_PASSWORD "super-secret"
dagloom secret get DB_PASSWORD
```

#### Python 用法

```python
from dagloom.security import Encryptor, SecretStore

store = SecretStore(db=db, encryptor=Encryptor())
await store.set("API_KEY", "sk-abc123")
value = await store.get("API_KEY")
```

### 7. 可观测性与指标（v0.13.0）

Dagloom 可自动记录逐节点的耗时和结果数据。向 `AsyncExecutor` 传递 `Database` 实例即可启用指标：

```python
from dagloom.scheduler import AsyncExecutor
from dagloom.store import Database

db = Database()
await db.connect()

executor = AsyncExecutor(pipeline, metrics_db=db)
result = await executor.execute(url="https://...")
```

每次节点执行都会记录到 `node_metrics` 表中，包括耗时、结果、重试次数和错误信息。无需修改节点代码。

#### 查询指标

```python
# 逐节点聚合统计：总运行次数、成功/失败次数、avg/min/max/p50/p95 毫秒
stats = await db.get_node_stats("my_pipeline")

# 最近的执行历史，附带逐节点指标
history = await db.get_execution_history("my_pipeline", limit=20)
```

#### REST API

```bash
# 逐节点聚合统计
curl http://localhost:8000/api/metrics/my_pipeline

# 执行历史，附带节点详情
curl http://localhost:8000/api/history/my_pipeline?limit=10
```

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
| GET | `/api/secrets` | 列出所有密钥 |
| POST | `/api/secrets` | 创建或更新密钥 |
| DELETE | `/api/secrets/{name}` | 删除密钥 |
| GET | `/api/secrets` | 列出所有密钥 |
| POST | `/api/secrets` | 创建或更新密钥 |
| DELETE | `/api/secrets/{name}` | 删除密钥 |
| GET | `/api/metrics/{pipeline_id}` | 逐节点聚合统计 |
| GET | `/api/history/{pipeline_id}?limit=N` | 执行历史，附带节点详情 |

### CLI 命令

| 命令 | 描述 |
|------|------|
| `dagloom serve` | 启动 Web 服务（含调度器） |
| `dagloom run <文件>` | 执行管道 |
| `dagloom demo` | 启动 Web 服务并预注册演示管道 |
| `dagloom demo --run` | 直接运行 ETL 演示管道 |
| `dagloom list` | 列出已注册的管道 |
| `dagloom inspect <文件>` | 查看 DAG 结构 |
| `dagloom scheduler list` | 列出所有定时调度 |
| `dagloom scheduler status` | 查看调度器状态 |
| `dagloom secret set <名称> <值>` | 存储密钥 |
| `dagloom secret get <名称>` | 检索密钥 |
| `dagloom secret list` | 列出所有密钥名称 |
| `dagloom secret delete <名称>` | 删除密钥 |
| `dagloom version` | 显示版本信息 |

## 认证（v0.11.0）

Dagloom 支持可选的请求级认证。默认情况下认证处于禁用状态（开放访问）。

### 启用认证

向 `dagloom serve` 传递 `--auth-type` 和 `--auth-key` 参数：

```bash
# API Key 认证 — 客户端发送 "Authorization: Bearer <key>"
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic 认证 — 客户端发送标准 HTTP Basic 凭据
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password
```

也可以通过环境变量配置：

```bash
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### 公共路径

以下路径始终无需凭据即可访问：

- `/health` — 健康检查
- `/docs` — Swagger UI
- `/openapi.json` — OpenAPI 规范
- `/redoc` — ReDoc UI

### 调用需认证的端点

```bash
# API Key
curl -H "Authorization: Bearer sk-abc123" http://localhost:8000/api/pipelines

# Basic 认证
curl -u admin:password http://localhost:8000/api/pipelines
```

```python
import httpx

# API Key
resp = httpx.get("http://localhost:8000/api/pipelines",
                 headers={"Authorization": "Bearer sk-abc123"})

# Basic 认证
resp = httpx.get("http://localhost:8000/api/pipelines",
                 auth=("admin", "password"))
```

## 连接器

Dagloom 内置了常见数据源的连接器。所有连接器遵循 `BaseConnector` 模式，支持异步上下文管理器。

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

### MongoDB（v0.12.0）

依赖 `motor>=3.3`。安装：`pip install dagloom[mongodb]`

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

支持操作：`find`、`find_one`、`insert_one`、`insert_many`、`update_one`、`update_many`、`delete_one`、`delete_many`、`aggregate`、`count`。

### Redis（v0.12.0）

依赖 `redis>=5.0`。安装：`pip install dagloom[redis]`

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

命令直接映射：`get`、`set`、`delete`、`hget`、`hset` 等。

### Kafka（v0.12.0）

依赖 `aiokafka>=0.9`。安装：`pip install dagloom[kafka]`

```python
from dagloom.connectors.kafka import KafkaConnector

config = ConnectionConfig(host="localhost", port=9092)

async with KafkaConnector(config) as kafka:
    await kafka.send("my-topic", value=b'{"event": "order_created"}')
    messages = await kafka.consume("my-topic", timeout=5.0)
```

支持操作：`send`（生产消息）、`consume`（临时消费者）。

可用连接器：**PostgreSQL**、**MySQL**、**S3/MinIO**、**HTTP API**、**MongoDB**、**Redis**、**Kafka**。
