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
│  调度器（asyncio）                                          │
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
├── __init__.py          # 公开 API：node, Pipeline, Branch, AsyncExecutor 等
├── core/
│   ├── __init__.py
│   ├── node.py          # @node 装饰器和 Node 类
│   ├── pipeline.py      # Pipeline 类，支持 >> 运算符
│   ├── dag.py           # 基于 NetworkX 的 DAG 验证
│   └── context.py       # 执行上下文和节点状态
├── scheduler/
│   ├── __init__.py
│   ├── executor.py      # 异步执行器，支持并行执行
│   ├── cache.py         # 基于 SHA-256 哈希的输出缓存
│   └── checkpoint.py    # 失败恢复支持
├── server/
│   ├── __init__.py
│   ├── app.py           # FastAPI 应用工厂
│   ├── api.py           # REST API 端点
│   └── ws.py            # WebSocket 连接管理器
├── store/
│   ├── __init__.py
│   └── db.py            # SQLite 数据库层
├── connectors/
│   ├── __init__.py
│   ├── base.py          # 抽象连接器接口
│   ├── postgres.py      # PostgreSQL 连接器
│   ├── mysql.py         # MySQL 连接器
│   ├── s3.py            # S3/MinIO 连接器
│   └── http.py          # HTTP API 连接器
└── cli/
    ├── __init__.py
    └── main.py          # Click CLI 命令
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
    description: str    # 来自函数 docstring
```

`@node` 装饰器支持两种形式：

```python
@node                           # 裸装饰器
def step_a(x): ...

@node(retry=3, cache=True)     # 带参数的装饰器
def step_b(x): ...
```

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
- `dag_updated` — DAG 结构更新

---

## 未来规划

### 计划中的功能

1. **分布式执行**：可选的 Redis 后端，支持多 Worker
2. **定时调度**：类 Cron 的触发器（每日、每小时等）
3. **密钥管理**：安全的凭据注入
4. **插件系统**：自定义节点类型（Docker、Kubernetes Job）
5. **数据血缘**：跟踪数据在管道中的流转
6. **监控**：Prometheus 指标、Grafana 仪表板

### 非目标

- 完整的 Airflow 兼容性
- 企业级 RBAC/多租户（请使用托管方案）
- GUI 优先的工作流设计（坚持代码优先的哲学）

---

## 贡献

请参阅 [主 README](../../README_zh.md) 了解贡献指南。

## 许可证

Apache License 2.0
