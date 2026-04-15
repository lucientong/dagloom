# Dagloom 架构文档

本文档全面介绍 Dagloom 的架构设计、技术决策和实现细节。

## 目录

- [概述](#概述)
- [设计哲学](#设计哲学)
- [系统架构](#系统架构)
- [核心组件](#核心组件)
- [数据流](#数据流)
- [执行模型](#执行模型)
- [存储层](#存储层)
- [Web 服务](#web-服务)
- [安全](#安全)
- [认证](#认证)
- [未来规划](#未来规划)

---

## 概述

Dagloom 是一个轻量级、Python 原生的管道/工作流引擎，专注于简洁性和开发者体验。与重量级编排工具（Airflow、Dagster、Prefect）不同，Dagloom 采用极简主义设计：

- **单进程**：无需外部服务（PostgreSQL、Redis、Celery）
- **零配置**：内嵌 SQLite，开箱即用
- **Pythonic API**：使用装饰器和运算符，而非 YAML 或 DSL
- **双向 UI 同步**：代码变更实时反映到 UI，反之亦然

```
┌─────────────────────────────────────────────────────────────┐
│                      Dagloom 技术栈                          │
├─────────────────────────────────────────────────────────────┤
│  CLI / Web UI                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  React + TypeScript + React Flow（拖拽式 DAG 编辑）  │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  FastAPI 服务器                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  REST API    │  │  WebSocket   │  │  静态文件服务   │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  调度器（APScheduler + asyncio）                                │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  执行器      │  │  缓存管理    │  │  检查点管理     │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  核心层                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  @node 装饰器│  │  Pipeline    │  │  DAG 验证器     │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  存储层                                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLite (aiosqlite) — 内嵌数据库，零配置             │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 设计哲学

### 1. 简洁优于功能

> *"让简单的事情简单，让复杂的事情可能。"*

Dagloom 追求最小化的 API 表面：

| 概念 | Dagloom | Airflow | Dagster |
|------|---------|---------|---------|
| 定义任务 | `@node` | `@task`, `Operator` | `@op`, `@asset` |
| 构建 DAG | `a >> b >> c` | `a >> b >> c` | `@job`, `@graph` |
| 配置选项 | `@node(retry=3)` | Operator 参数 + airflow.cfg | Resources, IO Managers |

### 2. Python 原生

没有 YAML，没有 DSL，没有外部配置文件。一切皆 Python：

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

### 3. 零外部依赖

与 Airflow（需要 PostgreSQL + Redis + Celery + 消息队列）不同，Dagloom 完全在单个 Python 进程中运行：

```bash
pip install dagloom
dagloom serve  # 就这样！
```

### 4. 失败后可恢复

失败的管道可以从最后一个检查点恢复，跳过已完成的节点：

```bash
dagloom run my_pipeline.py  # 节点 3 失败
dagloom resume              # 从节点 3 继续执行
```

---

## 系统架构

### 模块结构

```
dagloom/
├── __init__.py          # 公开 API：node, Pipeline, SchedulerService 等
├── core/
│   ├── __init__.py
│   ├── node.py          # @node 装饰器和 Node 类
│   ├── pipeline.py      # Pipeline 类，支持 >> 运算符和 schedule= 参数
│   ├── dag.py           # 基于 NetworkX 的 DAG 验证
│   └── context.py       # 执行上下文和节点状态
├── scheduler/
│   ├── __init__.py
│   ├── executor.py      # 异步执行器，支持并行执行
│   ├── process_executor.py  # 进程执行器，支持 CPU 密集型节点
│   ├── scheduler.py     # SchedulerService（APScheduler 封装）
│   ├── triggers.py      # Cron/间隔触发器解析
│   ├── cache.py         # 基于 SHA-256 哈希的输出缓存，支持依赖失效，支持依赖失效
│   └── checkpoint.py    # 失败恢复支持
├── notifications/
│   ├── __init__.py
│   ├── base.py          # NotificationChannel ABC、ExecutionEvent
│   ├── email.py         # SMTPChannel（aiosmtplib）
│   ├── webhook.py       # WebhookChannel（Slack、企微、飞书、通用 JSON）
│   └── registry.py      # ChannelRegistry、resolve_channel（URI 解析）
├── server/
│   ├── __init__.py
│   ├── app.py           # FastAPI 应用工厂（启动调度器）
│   ├── api.py           # REST API 端点（管道 + 调度）
│   ├── codegen.py       # 双向代码 ↔ DAG 转换（支持 round-trip 保真）
│   ├── middleware.py    # AuthMiddleware、RequireAuth、OptionalAuth
│   ├── watcher.py       # 文件监控，实现代码 → UI 实时同步
│   └── ws.py            # WebSocket 连接管理器
├── store/
│   ├── __init__.py
│   └── db.py            # SQLite 数据库层
├── security/
│   ├── __init__.py
│   ├── auth.py          # AuthProvider ABC、APIKeyAuth、BasicAuth、NoAuth
│   ├── encryption.py    # Encryptor 类（基于 Fernet），DecryptionError，generate_key()
│   └── secrets.py       # SecretStore，分层解析（env → .env → 加密数据库）
├── demo/
│   ├── __init__.py
│   └── etl_pipeline.py  # create_demo_pipeline() 工厂函数 — 一键体验 ETL 演示管道
├── demo/
│   ├── __init__.py
│   └── etl_pipeline.py  # create_demo_pipeline() 工厂函数 — 一键体验 ETL 演示管道
├── connectors/
│   ├── __init__.py
│   ├── base.py          # 抽象连接器接口
│   ├── postgres.py      # PostgreSQL 连接器
│   ├── mysql.py         # MySQL 连接器
│   ├── s3.py            # S3/MinIO 连接器
│   └── http.py          # HTTP API 连接器
└── cli/
    ├── __init__.py
    └── main.py          # Click CLI 命令（serve、run、demo、scheduler、secret 等）
```

---

## 核心组件

### Node（节点）— `dagloom/core/node.py`

**Node** 封装 Python 函数，添加执行元数据：

```python
class Node:
    name: str           # 唯一标识符（函数名）
    fn: Callable        # 被封装的函数
    retry: int          # 失败重试次数（默认：0）
    cache: bool         # 是否启用输出缓存（默认：False）
    timeout: float      # 最大执行时间，秒（默认：None）
    executor: str       # 执行器提示："auto" | "async" | "process"（默认："auto"）
    description: str    # 来自函数 docstring
```

`@node` 装饰器支持两种形式：

```python
@node                           # 裸装饰器
def step_a(x): ...

@node(retry=3, cache=True)     # 带参数的装饰器
def step_b(x): ...

@node(executor="process")      # CPU 密集型：分派到 ProcessPoolExecutor
def step_c(x): ...

@node(executor="async")        # 强制 asyncio 执行
def step_d(x): ...
```

**执行器提示**（v0.8.0）：

模块级常量定义了允许的值：

```python
EXECUTOR_HINTS = frozenset({"auto", "async", "process"})
```

| 提示值 | 行为 |
|-------|------|
| `"auto"`（默认） | 保持现有行为——同步函数通过 `asyncio.to_thread` 运行，异步函数直接 await |
| `"async"` | 强制 asyncio 执行（适用于实际为 I/O 密集型且可安全在事件循环中运行的同步函数） |
| `"process"` | 将 CPU 密集型同步函数分派到 `ProcessPoolExecutor`，通过顶层可序列化辅助函数 `_run_in_process()` 实现 |

关键实现细节：

- **`__rshift__`**：实现 `node_a >> node_b` 语法
- **`__or__`**：实现 `node_a | node_b` 创建条件分支 `Branch`
- **`__call__`**：允许直接调用 `node(args)`
- **类型内省**：通过 `inspect.signature` 提取输入参数和返回类型

### Branch（条件分支）— `dagloom/core/node.py`

**Branch** 表示一组互斥的节点替代方案，通过 `|` 运算符创建：

```python
class Branch:
    nodes: list[Node]       # 分支中的候选节点
```

```python
# 创建分支
branch = validate_a | validate_b | validate_c

# 连接到管道
pipeline = classify >> (urgent_handler | normal_handler)
```

分支选择规则（`_select_branch`）：

1. 如果上游输出是包含 `"branch"` 键的 *dict*，用其值匹配分支节点名称
2. 对于双分支组：*truthy* 输出 → 第一个分支，*falsy* → 第二个分支
3. 兜底：默认选择第一个分支

### Pipeline（管道）— `dagloom/core/pipeline.py`

**Pipeline** 是由节点组成的 DAG（有向无环图）：

```python
class Pipeline:
    name: str                           # 可选的管道名称
    schedule: str | None                # Cron 表达式或间隔简写（如 "0 9 * * *"、"every 30m"）
    notify_on: dict | None              # 通知配置（如 {"failure": ["email://..."], "success": ["webhook://..."]}）
    _nodes: dict[str, Node]             # 节点注册表
    _edges: list[tuple[str, str]]       # 边列表 (source, target)
    _tail_nodes: list[str]              # >> 操作的当前链尾
    _branches: dict[str, Branch]        # 条件分支映射 (前驱节点名 → Branch)
```

**构建 Pipeline：**

```python
# 方式 1：使用 >> 运算符
pipeline = fetch >> clean >> save

# 方式 2：显式构建
pipeline = Pipeline()
pipeline.add_node(fetch)
pipeline.add_node(clean)
pipeline.add_node(save)
pipeline.add_edge("fetch", "clean")
pipeline.add_edge("clean", "save")
```

**执行：**

```python
result = pipeline.run(url="https://...")
```

`run()` 方法的执行流程：
1. 验证 DAG（检查是否存在环）
2. 计算拓扑排序
3. 按顺序执行节点
4. 将输出作为依赖节点的输入传递

### DAG 验证 — `dagloom/core/dag.py`

使用 **NetworkX** 进行图操作：

```python
def validate_dag(graph: nx.DiGraph) -> None:
    """如果检测到环则抛出 CycleError。"""
    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        raise CycleError(cycle)

def topological_layers(graph: nx.DiGraph) -> list[list[str]]:
    """按执行层分组节点，用于并行化。"""
    return list(nx.topological_generations(graph))
```

---

## 数据流

### 输入传播

```
              inputs: {url: "https://..."}
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  根节点 (fetch)                                             │
│  fn(url="https://...")  →  返回: dict                      │
└────────────────────────────────┬────────────────────────────┘
                                 │ output: dict
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  节点 (clean)                                               │
│  fn(data=<fetch 的输出>)  →  返回: DataFrame               │
└────────────────────────────────┬────────────────────────────┘
                                 │ output: DataFrame
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  叶节点 (save)                                              │
│  fn(df=<clean 的输出>)  →  返回: str (路径)                │
└─────────────────────────────────────────────────────────────┘
```

### 多前驱节点处理

当节点有多个前驱时，它接收一个输出字典：

```python
@node
def merge(inputs: dict[str, Any]) -> pd.DataFrame:
    # inputs = {"process_a": df_a, "process_b": df_b}
    return pd.concat([inputs["process_a"], inputs["process_b"]])
```

---

## 执行模型

### 同步执行 — `Pipeline.run()`

按拓扑顺序逐个执行节点：

```python
for node_name in topological_order:
    node = nodes[node_name]
    result = node(**get_inputs(node_name))
    outputs[node_name] = result
```

### 异步执行 — `AsyncExecutor`

将节点分组为**层**——同层节点相互独立，可并发执行：

```
Layer 0: [fetch_a, fetch_b]     ← 并行
Layer 1: [process_a, process_b] ← 并行  
Layer 2: [merge]                ← 串行
Layer 3: [save]                 ← 串行
```

```python
class AsyncExecutor:
    async def execute(self, **inputs):
        for layer in topological_layers(graph):
            # 并发运行本层所有节点
            await asyncio.gather(*[
                self._execute_node(name, inputs, ctx)
                for name in layer
            ])
```

### 条件分支选择

在同步和异步执行中，当节点连接到 `Branch` 时，运行时会在该节点执行后选择分支：

```python
# 同步 (Pipeline.run)
if node_name in self._branches:
    branch = self._branches[node_name]
    selected = _select_branch(result, branch)
    for bn in branch.nodes:
        if bn.name != selected:
            skipped_nodes.add(bn.name)  # 未选中的分支标记为跳过

# 异步 (AsyncExecutor)
# 同一层执行完毕后，对该层中的分支节点进行选择
for name in layer:
    if name in self.pipeline._branches:
        selected = _select_branch(output, branch)
        # 未选中的分支在后续层中跳过
```

### 流式节点（Generator / Async Generator）

节点函数可以是生成器或异步生成器，运行时会自动收集 yield 的值：

```python
@node
def stream_chunks(url: str):
    for i in range(10):
        yield fetch_chunk(url, offset=i)

# Pipeline._call_node 自动处理：
# - generator → list(generator)
# - async generator → [item async for item in gen]
# - coroutine → await / asyncio.run
# - 普通函数 → 直接调用
```

在 `AsyncExecutor._run_callable` 中：

| 函数类型 | 检测方式 | 处理方式 |
|---------|---------|---------|
| async generator | `isasyncgenfunction()` | `[item async for item in fn()]` |
| coroutine | `iscoroutinefunction()` | `await fn()` |
| sync generator | `isgeneratorfunction()` | `asyncio.to_thread(lambda: list(fn()))` |
| 普通函数 | 兜底 | `asyncio.to_thread(fn)` |

#### 逐节点执行器分派（v0.8.0）

`AsyncExecutor._run_callable()` 现在会在上述函数类型分派表**之前**检查 `node_obj.executor`，实现逐节点的执行策略控制：

```python
async def _run_callable(self, node_obj, fn, *args, **kwargs):
    hint = node_obj.executor          # "auto" | "async" | "process"

    if hint == "process":
        return await loop.run_in_executor(
            self._process_pool,       # ProcessPoolExecutor
            _run_in_process,          # 顶层可序列化辅助函数
            fn, args, kwargs,
        )

    if hint == "async":
        return await fn(*args, **kwargs)   # 强制直接 await

    # hint == "auto" → 使用上述函数类型分派表
    ...
```

`_run_in_process(fn, args, kwargs)` 是一个**模块级**（顶层）函数，确保可被 `multiprocessing` 机制序列化（pickle）：

```python
def _run_in_process(fn, args, kwargs):
    """顶层辅助函数——必须可被 ProcessPoolExecutor 序列化。"""
    return fn(*args, **kwargs)
```

`AsyncExecutor` 现在接受可选的 `max_process_workers` 参数，用于控制内部 `ProcessPoolExecutor` 的大小：

```python
executor = AsyncExecutor(
    pipeline,
    max_process_workers=4,   # 默认为 os.cpu_count()
)
```

### ProcessExecutor（v0.8.0 简化版）

`ProcessExecutor`（`dagloom/scheduler/process_executor.py`）已被简化。它不再维护独立的并行执行逻辑，而是：

1. 遍历管道中的所有节点
2. 将所有 `executor="auto"` 的节点设置为 `executor="process"`
3. 完全委托给 `AsyncExecutor.execute()`

这意味着 `ProcessExecutor` 现在是一个轻量封装，默认强制所有节点使用进程执行，同时仍然尊重用户显式设置的 `executor="async"` 提示。

```python
class ProcessExecutor:
    def __init__(self, pipeline, **kwargs):
        self.pipeline = pipeline
        self._kwargs = kwargs

    async def execute(self, **inputs):
        for node_obj in self.pipeline._nodes.values():
            if node_obj.executor == "auto":
                node_obj.executor = "process"
        inner = AsyncExecutor(self.pipeline, **self._kwargs)
        return await inner.execute(**inputs)
```

### 执行钩子（on_node_start / on_node_end）

`AsyncExecutor` 支持在节点执行前后触发回调：

```python
executor = AsyncExecutor(
    pipeline,
    on_node_start=lambda name, ctx: print(f"开始: {name}"),
    on_node_end=lambda name, ctx: print(f"结束: {name}"),
)
```

- 钩子可以是同步函数或异步函数（通过 `inspect.isawaitable` 自动检测）
- 钩子异常**不会中断**执行，只记录警告日志
- `on_node_start` 在缓存检查之后、实际执行之前触发
- `on_node_end` 在节点成功或所有重试耗尽后触发

### 指数退避重试

```python
delay = min(base_delay * (2 ** attempt), max_delay)
# 第 1 次: 0.5s, 第 2 次: 1s, 第 3 次: 2s, ...
```

### 超时处理

```python
if node.timeout:
    result = await asyncio.wait_for(coro, timeout=node.timeout)
```

---

## 内置调度器

### SchedulerService（`dagloom/scheduler/scheduler.py`）

封装 APScheduler 的 `AsyncIOScheduler`，支持 Cron 和间隔调度。随 FastAPI 服务在进程内运行。

```python
from dagloom import SchedulerService

scheduler = SchedulerService(db)
await scheduler.start()

# 注册管道定时执行
schedule_id = await scheduler.register(
    pipeline=my_pipeline,
    cron_expr="0 9 * * *",       # 或 "every 30m"
)

# 管理调度
await scheduler.pause(schedule_id)
await scheduler.resume(schedule_id)
await scheduler.unregister(schedule_id)

schedules = await scheduler.list_schedules()
await scheduler.stop()
```

核心特性：
- **持久化**：调度配置存储在 SQLite `schedules` 表，重启后自动恢复
- **漏触发处理**：通过 APScheduler 配置（合并 + 宽限期，默认：跳过）
- **触发器解析**（`triggers.py`）：支持 5 字段 cron（`"0 9 * * *"`）和间隔简写（`"every 30m"`、`"every 2h"`、`"every 1d"`）
- **进程内运行**：无需独立守护进程，随 `dagloom serve` 启停

### Pipeline 调度参数

```python
# 通过构造函数
pipeline = Pipeline(name="daily_etl", schedule="0 9 * * *")

# 通过属性
pipeline = fetch >> process
pipeline.schedule = "every 30m"
```

---

## 通知系统

### 概览（`dagloom/notifications/`）

管道执行结果可通过邮件或 Webhook 发送到外部服务。通知在 `AsyncExecutor.execute()` 的 finally 块中分发——永远不会掩盖执行错误。

### 通知渠道

- **SMTPChannel**（`email.py`）：通过 `aiosmtplib` 异步发送邮件，支持 STARTTLS，可自定义主题模板
- **WebhookChannel**（`webhook.py`）：通过 `httpx` 发送 HTTP POST，内置格式化器：
  - `"slack"` — Slack Block Kit，带颜色编码
  - `"wechat_work"` — 企业微信 Markdown 消息
  - `"feishu"` — 飞书交互式卡片
  - `"generic"` — 纯 JSON，包含所有事件字段

### URI 解析（`registry.py`）

通过 URI 字符串创建渠道：
```python
resolve_channel("email://ops@team.com")                  # → SMTPChannel
resolve_channel("webhook://https://...?format=slack")     # → WebhookChannel
```

### Pipeline 配置

```python
pipeline.notify_on = {
    "failure": ["email://ops@team.com", "webhook://https://hooks.slack.com/...?format=slack"],
    "success": ["webhook://https://hooks.slack.com/...?format=slack"],
}
```

### 执行流程

```
AsyncExecutor.execute() → finally 块
  ├─ 检查 pipeline.notify_on
  ├─ 构建 ExecutionEvent（状态、耗时、错误、失败节点）
  ├─ 对 notify_on[status] 中每个 URI：
  │   ├─ resolve_channel(uri)
  │   └─ channel.send(event)  # 失败仅记录警告，不抛异常
  └─ 完成
```

---

## 存储层

### SQLite 表结构 — `dagloom/store/db.py`

```sql
-- 管道表
CREATE TABLE pipelines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    node_names TEXT,      -- JSON 数组
    edges TEXT,           -- JSON 数组 [[src, tgt], ...]
    created_at TEXT,
    updated_at TEXT
);

-- 执行记录表
CREATE TABLE executions (
    id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- running, success, failed
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);

-- 节点执行记录表（用于检查点/恢复）
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

-- 缓存记录表
CREATE TABLE cache_entries (
    node_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_path TEXT NOT NULL,
    serialization_format TEXT DEFAULT 'pickle',
    size_bytes INTEGER,
    created_at TEXT,
    PRIMARY KEY (node_id, input_hash)
);
```

**缓存失效相关的数据库方法（v0.7.0）：**

```python
# 删除指定节点的所有缓存条目
await db.delete_cache_entries_for_node(node_id)

# 查询指定节点的所有缓存条目
entries = await db.get_cache_entries_for_node(node_id)
```

```sql
-- 调度表（Cron/间隔）
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

-- 元数据表（Schema 版本管理）
CREATE TABLE dagloom_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 密钥表（v0.9.0）
CREATE TABLE secrets (
    key TEXT PRIMARY KEY,
    encrypted_value BLOB NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
```

### 缓存机制 — `dagloom/scheduler/cache.py`

缓存键是序列化输入的 **SHA-256 哈希**：

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

缓存文件存储在 `.dagloom/cache/<node_id>/<hash>.pkl`。

#### 缓存依赖失效（v0.7.0）

当某个节点的输出发生变化时，下游的缓存必须被自动清除。`CacheManager` 提供以下方法：

```python
# 批量删除指定节点的所有缓存条目
cache_manager.invalidate_node(node_id)

# 利用 networkx.descendants() 级联失效所有下游节点的缓存
cache_manager.invalidate_downstream(node_id, nodes, edges)

# 计算输出的 SHA-256 哈希，用于变更检测
output_hash = cache_manager.compute_output_hash(value)
```

- **`invalidate_node(node_id)`**：删除 `.dagloom/cache/<node_id>/` 下的所有缓存文件，并通过 `Database.delete_cache_entries_for_node()` 移除 `cache_entries` 表中的对应记录。
- **`invalidate_downstream(node_id, nodes, edges)`**：根据传入的节点和边构建 `networkx.DiGraph`，通过 `networkx.descendants()` 计算 `node_id` 的所有下游节点，然后对每个下游节点调用 `invalidate_node()`。
- **`compute_output_hash(value)`**：使用 `pickle.dumps()` 序列化值，返回其 SHA-256 十六进制摘要。用于判断节点输出是否实际发生了变化。
- **`_output_hashes`**：`CacheManager` 上的内存字典（`dict[str, str]`），记录每个节点最后一次已知的输出哈希。每次执行后与新哈希比对，决定是否需要级联失效下游缓存。

**`AsyncExecutor._execute_node()` 中的自动失效逻辑：**

写入缓存后，执行器会计算输出哈希并与 `_output_hashes` 中的旧值比较。如果哈希不同（即输出发生了变化），则自动调用 `invalidate_downstream()` 级联清除所有受影响的下游缓存。

### 检查点/恢复 — `dagloom/scheduler/checkpoint.py`

每个节点的执行状态都会持久化：

```python
await checkpoint.save_state(
    execution_id="abc123",
    pipeline_id="my_pipeline",
    node_id="clean",
    status="success",
    output_path=".dagloom/cache/clean/xyz789.pkl"
)
```

恢复时跳过已完成的节点：

```python
completed = await checkpoint.get_completed_nodes(execution_id)
for node_name in topological_order:
    if node_name in completed:
        continue  # 跳过
    # 执行节点...
```

---

## Web 服务

### FastAPI 应用 — `dagloom/server/app.py`

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

### REST API 端点

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/pipelines` | 列出所有管道 |
| POST | `/api/pipelines/{id}/run` | 触发执行 |
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
| GET | `/api/secrets` | 列出所有密钥名称 |
| POST | `/api/secrets` | 创建或更新密钥 |
| DELETE | `/api/secrets/{key}` | 删除密钥 |

### WebSocket — `dagloom/server/ws.py`

实时推送执行状态更新：

```python
class ConnectionManager:
    async def broadcast(self, pipeline_id: str, message: dict):
        for connection in self.connections[pipeline_id]:
            await connection.send_json(message)
```

事件类型：
- `execution_started` — 执行开始
- `node_running` — 节点运行中
- `node_success` — 节点成功
- `node_failed` — 节点失败
- `execution_completed` — 执行完成
- `dag_updated` — DAG 结构更新（来自文件编辑或 UI 保存）

### 双向同步流程

**UI → 文件（保存）：**
```
前端拖拽编辑 → PUT /api/pipelines/{id}/dag
  ├─ 乐观锁：比对 source_hash → 冲突时返回 409
  ├─ dag_to_code() → 生成 Python 源码（保留原始函数体）
  ├─ 写入 .py 文件
  ├─ 更新 watcher 哈希（防止回声触发）
  ├─ 保存到数据库
  └─ 通过 WebSocket 广播 dag_updated
```

**文件 → UI（监控）：**
```
用户在 VS Code / vim 中编辑 .py → watchfiles 检测到变更
  ├─ 内容哈希去重（未变则跳过）
  ├─ code_to_dag() → 解析为 DagModel（含函数体）
  ├─ 通过 WebSocket 广播 dag_updated
  └─ 前端重新渲染 DAG
```

---

## 安全

### 凭据安全管理（v0.9.0）— `dagloom/security/`

Dagloom 提供内置的凭据管理功能，使管道可以安全地访问敏感值（API 密钥、数据库密码、令牌），无需在源代码中硬编码。新增依赖：`cryptography>=41`、`python-dotenv>=1.0`。

### 加密 — `dagloom/security/encryption.py`

`Encryptor` 类封装 `cryptography.fernet.Fernet`，提供对称加密能力：

```python
from dagloom.security.encryption import Encryptor, DecryptionError, generate_key

# 生成新的主密钥（请安全存储！）
key = Encryptor.generate_key()  # 返回 Fernet 兼容的 base64 密钥

# 创建加密器 — 从 DAGLOOM_MASTER_KEY 环境变量读取主密钥
encryptor = Encryptor()                    # 使用 os.environ["DAGLOOM_MASTER_KEY"]
encryptor = Encryptor(master_key=key)      # 或显式传入

# 加密 / 解密
token = encryptor.encrypt("my-api-key")    # 返回 bytes
value = encryptor.decrypt(token)           # 返回 str；失败时抛出 DecryptionError
```

- **主密钥来源**：`DAGLOOM_MASTER_KEY` 环境变量（运行时必需）
- **加密算法**：Fernet（AES-128-CBC + HMAC-SHA256），基于 `cryptography` 库
- **`DecryptionError`**：自定义异常，在解密失败时抛出（密钥错误、数据损坏）
- **`generate_key()`**：静态方法，返回一个全新的 Fernet 密钥，用于初始化配置

### 密钥存储 — `dagloom/security/secrets.py`

`SecretStore` 提供统一的密钥获取接口，采用**分层解析**策略：

```
SecretStore.get("DB_PASSWORD")
  ├─ 1. 环境变量：DAGLOOM_SECRET_DB_PASSWORD
  ├─ 2. .env 文件（通过 python-dotenv 加载）：DAGLOOM_SECRET_DB_PASSWORD
  └─ 3. 加密 SQLite 数据库：secrets 表 → Fernet 解密
```

```python
from dagloom.security.secrets import SecretStore

store = SecretStore(db, encryptor)

# CRUD 操作（针对加密 SQLite 数据库）
await store.save_secret("DB_PASSWORD", "s3cret!")       # 加密 + upsert
value = await store.get_secret("DB_PASSWORD")            # 分层解析
keys  = await store.list_secrets()                       # 返回 list[str]
await store.delete_secret("DB_PASSWORD")                 # 从数据库删除
```

**解析顺序**（首次匹配即返回）：
1. **环境变量** — `DAGLOOM_SECRET_<KEY>`（如 `DAGLOOM_SECRET_DB_PASSWORD`）
2. **`.env` 文件** — 启动时通过 `python-dotenv` 加载一次；使用相同命名规范
3. **加密数据库** — `secrets` 表；值在存储时使用 Fernet 加密

这种分层设计允许运维人员按环境覆盖密钥，无需修改数据库（例如通过 CI/CD 环境变量注入，或在 Kubernetes 中挂载 `.env` 文件）。

### 数据库表

```sql
CREATE TABLE secrets (
    key TEXT PRIMARY KEY,
    encrypted_value BLOB NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
```

`Database` 上的 CRUD 方法：
- `save_secret(key, encrypted_value)` — INSERT OR REPLACE
- `get_secret(key)` — 返回加密字节或 `None`
- `list_secrets()` — 返回所有密钥名称（不返回值）
- `delete_secret(key)` — 按 key 删除

### REST API

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/secrets` | 列出所有密钥名称（不返回密钥值） |
| POST | `/api/secrets` | 创建或更新密钥（`{"key": "...", "value": "..."}`） |
| DELETE | `/api/secrets/{key}` | 删除密钥 |

### CLI

```bash
dagloom secret set DB_PASSWORD          # 提示输入值（不回显）
dagloom secret get DB_PASSWORD          # 输出解密后的值
dagloom secret list                     # 列出所有密钥名称
dagloom secret delete DB_PASSWORD       # 从数据库删除
```

### 安全架构流程

```
                       ┌──────────────────────┐
                       │  DAGLOOM_MASTER_KEY   │  （环境变量）
                       └──────────┬───────────┘
                                  │
                                  ▼
┌───────────────────────────────────────────────────────────┐
│  Encryptor (Fernet)                                       │
│  encrypt(明文) → 密文                                      │
│  decrypt(密文) → 明文                                      │
└────────────────┬──────────────────────┬───────────────────┘
                 │                      │
          写入 (save_secret)     读取 (get_secret)
                 │                      │
                 ▼                      ▼
┌───────────────────────────────────────────────────────────┐
│  SQLite: secrets 表                                       │
│  key TEXT PK | encrypted_value BLOB | 时间戳               │
└───────────────────────────────────────────────────────────┘
                                  ▲
                                  │ 兜底（第 3 层）
                                  │
┌───────────────────────────────────────────────────────────┐
│  SecretStore — 分层解析                                    │
│  1. 环境变量  DAGLOOM_SECRET_<KEY>                         │
│  2. .env 文件（python-dotenv）                             │
│  3. 加密数据库                                             │
└───────────────────────────────────────────────────────────┘
```

---

## 认证

### 请求认证（v0.11.0）— `dagloom/security/auth.py`、`dagloom/server/middleware.py`

Dagloom 支持可选的请求级认证。启用后，所有 API 端点都需要有效凭据——公共路径除外（`/health`、`/docs`、`/openapi.json`、`/redoc`）。

### 认证提供者（`dagloom/security/auth.py`）

`AuthProvider` 是一个抽象基类，内置三种实现：

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credential: str) -> bool: ...

class APIKeyAuth(AuthProvider):
    """根据配置的 API Key 验证 Bearer 令牌。"""

class BasicAuth(AuthProvider):
    """验证 HTTP Basic 凭据（用户名:密码）。"""

class NoAuth(AuthProvider):
    """空操作提供者——始终返回 True。认证未启用时使用。"""
```

| 提供者 | `--auth-type` | 凭据格式 | 请求头 |
|--------|---------------|---------|--------|
| `APIKeyAuth` | `API_KEY` | 原始 API Key 字符串 | `Authorization: Bearer sk-abc123` |
| `BasicAuth` | `BASIC_AUTH` | `用户名:密码` | `Authorization: Basic <base64>` |
| `NoAuth` | *（默认）* | — | — |

### 中间件（`dagloom/server/middleware.py`）

`AuthMiddleware` 是一个 Starlette 中间件，拦截每个请求：

1. 跳过公共路径：`/health`、`/docs`、`/openapi.json`、`/redoc`
2. 从 `Authorization` 请求头中提取凭据（Bearer 或 Basic 方案）
3. 调用 `AuthProvider.authenticate(credential)` 进行验证
4. 验证失败时返回 `401 Unauthorized`

```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_provider: AuthProvider):
        super().__init__(app)
        self.auth_provider = auth_provider

    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        # 提取并验证凭据...
```

### FastAPI 依赖项

提供两个依赖项用于路由级别的控制：

- **`RequireAuth`** — 凭据缺失或无效时返回 `401`
- **`OptionalAuth`** — 允许未认证访问；将认证状态写入 `request.state.authenticated` 供下游逻辑使用

### 配置

通过 CLI 参数或环境变量配置认证：

| CLI 参数 | 环境变量 | 描述 |
|---------|---------|------|
| `--auth-type` | `DAGLOOM_AUTH_TYPE` | `API_KEY`、`BASIC_AUTH` 或留空（禁用） |
| `--auth-key` | `DAGLOOM_AUTH_KEY` | API Key 或 `用户名:密码` 字符串 |

```bash
# API Key 认证
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic 认证
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password

# 环境变量
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### 认证流程

```
传入请求
  │
  ├─ 路径在 PUBLIC_PATHS 中？ ──是──→ 跳过认证 → call_next()
  │
  否
  │
  ├─ 提取 Authorization 请求头
  │   ├─ Bearer <token>  → credential = token
  │   └─ Basic <base64>  → credential = 解码后的 用户名:密码
  │
  ├─ AuthProvider.authenticate(credential)
  │   ├─ True  → call_next()
  │   └─ False → 401 Unauthorized
  │
  └─ 无请求头 → 401 Unauthorized
```

---

## 认证

### 请求认证（v0.11.0）— `dagloom/security/auth.py`、`dagloom/server/middleware.py`

Dagloom 支持可选的请求级认证。启用后，所有 API 端点都需要有效凭据——公共路径除外（`/health`、`/docs`、`/openapi.json`、`/redoc`）。

### 认证提供者（`dagloom/security/auth.py`）

`AuthProvider` 是一个抽象基类，内置三种实现：

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credential: str) -> bool: ...

class APIKeyAuth(AuthProvider):
    """根据配置的 API Key 验证 Bearer 令牌。"""

class BasicAuth(AuthProvider):
    """验证 HTTP Basic 凭据（用户名:密码）。"""

class NoAuth(AuthProvider):
    """空操作提供者——始终返回 True。认证未启用时使用。"""
```

| 提供者 | `--auth-type` | 凭据格式 | 请求头 |
|--------|---------------|---------|--------|
| `APIKeyAuth` | `API_KEY` | 原始 API Key 字符串 | `Authorization: Bearer sk-abc123` |
| `BasicAuth` | `BASIC_AUTH` | `用户名:密码` | `Authorization: Basic <base64>` |
| `NoAuth` | *（默认）* | — | — |

### 中间件（`dagloom/server/middleware.py`）

`AuthMiddleware` 是一个 Starlette 中间件，拦截每个请求：

1. 跳过公共路径：`/health`、`/docs`、`/openapi.json`、`/redoc`
2. 从 `Authorization` 请求头中提取凭据（Bearer 或 Basic 方案）
3. 调用 `AuthProvider.authenticate(credential)` 进行验证
4. 验证失败时返回 `401 Unauthorized`

```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_provider: AuthProvider):
        super().__init__(app)
        self.auth_provider = auth_provider

    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        # 提取并验证凭据...
```

### FastAPI 依赖项

提供两个依赖项用于路由级别的控制：

- **`RequireAuth`** — 凭据缺失或无效时返回 `401`
- **`OptionalAuth`** — 允许未认证访问；将认证状态写入 `request.state.authenticated` 供下游逻辑使用

### 配置

通过 CLI 参数或环境变量配置认证：

| CLI 参数 | 环境变量 | 描述 |
|---------|---------|------|
| `--auth-type` | `DAGLOOM_AUTH_TYPE` | `API_KEY`、`BASIC_AUTH` 或留空（禁用） |
| `--auth-key` | `DAGLOOM_AUTH_KEY` | API Key 或 `用户名:密码` 字符串 |

```bash
# API Key 认证
dagloom serve --auth-type API_KEY --auth-key sk-abc123

# Basic 认证
dagloom serve --auth-type BASIC_AUTH --auth-key admin:password

# 环境变量
export DAGLOOM_AUTH_TYPE=API_KEY
export DAGLOOM_AUTH_KEY=sk-abc123
dagloom serve
```

### 认证流程

```
传入请求
  │
  ├─ 路径在 PUBLIC_PATHS 中？ ──是──→ 跳过认证 → call_next()
  │
  否
  │
  ├─ 提取 Authorization 请求头
  │   ├─ Bearer <token>  → credential = token
  │   └─ Basic <base64>  → credential = 解码后的 用户名:密码
  │
  ├─ AuthProvider.authenticate(credential)
  │   ├─ True  → call_next()
  │   └─ False → 401 Unauthorized
  │
  └─ 无请求头 → 401 Unauthorized
```

---

## 未来规划

### 计划中的功能

1. **分布式执行**：可选的 Redis 后端，支持多 Worker
2. ~~**定时调度**：类 Cron 的触发器（每日、每小时等）~~ ✅ 已在 v0.4.0 实现
3. ~~**密钥管理**：安全的凭据注入~~ ✅ 已在 v0.9.0 实现
4. **插件系统**：自定义节点类型（Docker、Kubernetes Job）
5. **数据血缘**：跟踪数据在管道中的流转
6. **监控**：Prometheus 指标、Grafana 仪表板
7. ~~**通知节点**：Email / Webhook（Slack、企微、飞书）管道事件告警~~ ✅ 已在 v0.5.0 实现
8. ~~**缓存依赖失效**：节点输出变化时自动级联清除下游缓存~~ ✅ 已在 v0.7.0 实现
9. ~~**逐节点执行器提示**：`@node(executor="process"|"async"|"auto")` 实现细粒度分派控制~~ ✅ 已在 v0.8.0 实现
10. ~~**PyPI 发布 & 一键演示**：`dagloom demo --run` 即刻体验 ETL 演示管道~~ ✅ 已在 v0.10.0 实现
11. ~~**认证**：基于中间件的 API Key / Basic 认证~~ ✅ 已在 v0.11.0 实现

### 非目标

- 完整的 Airflow 兼容性
- 企业级 RBAC/多租户（请使用托管方案）
- GUI 优先的工作流设计（坚持代码优先的哲学）

---

## 贡献

请参阅 [主 README](../../README_zh.md) 了解贡献指南。

## 许可证

Apache License 2.0
