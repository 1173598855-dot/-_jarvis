# 受控角色模型工具循环设计

**日期**: 2026-07-27  
**目标迭代**: Iteration 134  
**状态**: Approved by the existing Stage C guidance

## 目标

为生产角色执行增加有界的 Ollama `model -> tool -> model` 循环。模型只能看到由角色声明、显式策略授权、已注册且带参数 Schema 的只读工具。任何模型请求都不能形成命令、插件生命周期操作或 HTTP capability token。

本设计落实 `docs/DEVELOPMENT_GUIDE.md` 阶段 C 的四项要求：工具请求/结果 Schema，调用次数/总时限/参数/输出预算，固定只读工具目录，以及 Broker + Worker 强制路径。

## 备选方案

### 方案 A: 继续内联扩展 AgentFactory

优点是文件改动少。缺点是协议解析、预算、审计和角色执行继续耦合，难以独立验证；当前探索性实现已经出现消息列表被调用后改写的回归，也没有生产工具装配点。

### 方案 B: 独立循环引擎，运行在现有 RoleWorker 内

这是采用方案。工具协议和预算使用独立模块，`AgentFactory` 只负责构造角色消息并委托循环。生产 `execute_role_task()` 在既有可终止 Worker 进程中创建只读 Broker，因此模型调用和工具处理共享 Worker 的总时限、终止确认及输出上限。

### 方案 C: 每次工具调用再创建嵌套 Worker

隔离最强，但会引入嵌套进程、第二套生命周期和额外 IPC。首批工具全部是固定只读查询，现有角色 Worker 已经提供进程级终止边界，因此当前没有足够收益支撑该复杂度。

## 架构

### 工具协议

新增版本化、不可变的结构：

- `RoleToolDefinition`: 工具名、描述和受限 JSON 参数 Schema，并生成 Ollama function definition。
- `RoleToolCall`: 从 Ollama `tool_calls` 严格解析出的调用 ID、工具名和参数。
- `RoleToolResult`: `succeeded`、`denied` 或 `failed` 的稳定结果，生成 Ollama `role=tool` 消息。
- `RoleToolInvocation`: 可序列化审计记录，保存顺序、请求、结果状态和有界结果。
- `RoleToolBudget`: 最大调用数、参数字节数、单次/累计输出字节数和总时限。

所有 JSON 大小按 UTF-8、稳定键顺序和紧凑分隔符计算。布尔值不得冒充整数。未知字段和类型不匹配默认拒绝。

### Broker

`RoleToolBroker` 仍保持声明 + 授权 + handler 三重匹配，并增加定义匹配和调用审计：

1. `authorized_tools()` 保持现有名称接口。
2. `authorized_definitions()` 只暴露同时具有 Schema 的授权工具。
3. `invoke()` 在 handler 前执行参数 Schema 和参数字节预算。
4. handler 的返回值先转为 JSON 安全值、脱敏并执行单次输出预算。
5. 允许、拒绝和 handler 失败都写入有界 invocation log。

模型不会收到原始异常文本。拒绝和失败使用稳定代码，详细但已脱敏的证据只保存在 Worker 审计结果中。

### 循环引擎

`RoleToolLoop` 接收已构造消息、角色、模型、Broker、任务时限和单调时钟：

1. 每次调用 Ollama 时传入消息快照，调用后不修改已经交给 manager 的对象。
2. 没有工具请求且内容非空时完成。
3. 每个工具请求先计入总调用预算，再由 Broker 解析、授权、校验和执行。
4. 工具结果使用 Ollama 的 `tool_name` 字段回填；已有 `tool_call_id` 时保留。
5. 达到次数、总时限或累计输出预算时失败关闭，不返回伪造的“已完成”成功结果。

Worker 的任务 deadline 是生产总时限的最终权威。循环自身在每次模型和工具边界检查同一预算，使直接单元测试和 Worker 路径具有一致语义；若上游调用卡住，Supervisor 仍负责终止进程并确认退出。

### 只读工具目录

新增固定目录并只在 `execute_role_task()` 的 Worker 子进程内创建：

- `system_status`: 平台、CPU 数量和仓库所在磁盘容量，不接受参数。
- `model_list`: 从受信任 Ollama base URL 列出模型，`limit` 为 1..50。
- `orchestrator_status`: 返回受信任的已注册角色快照和 Worker 隔离状态，不执行 dispatch。
- `memory_search`: 在受信任 memory root 内做大小和数量受限的只读查询，查询文本不超过 256 字符。
- `repository_metadata`: 通过固定参数的 `GitWorkspaceInspector` 返回 HEAD、branch 和有界 dirty paths。

角色注册表为各角色新增明确的只读工具名，策略再按角色精确授权子集。旧的 `terminal_executor`、`plugin_sdk` 等声明保留为未授权兼容元数据，但不会获得 definition、handler 或模型可见性。

### Worker 数据流

```text
HTTP role dispatch
  -> RoleDispatchService
  -> RoleWorkerSupervisor (authoritative deadline)
  -> execute_role_task child process
  -> read-only RoleToolBroker
  -> AgentFactory
  -> RoleToolLoop
  -> Ollama /api/chat
  -> Broker.invoke(read-only handler)
  -> tool message -> Ollama
  -> dispatch + token usage + tool_audit
  -> WorkerTaskRecord
```

通用 `/api/orchestrator/dispatch` 不迁移、不获得工具目录，也不改变现有行为。

## 错误与审计

- 无效 `tool_calls`、未知工具、参数不合 Schema 和超预算均 fail closed。
- Broker 拒绝作为稳定、短小的工具结果返回模型，使模型有机会不用工具完成回答。
- handler 异常也返回稳定失败结果；原始异常经秘密脱敏后仅进入有界审计。
- 若模型持续调用工具直到预算耗尽，角色执行返回现有稳定错误 `Ollama role execution failed`。
- 成功 Worker 结果包含 `tool_audit`，因此允许和拒绝路径可从异步任务详情回放。

## 验证

- 协议和 Broker 单元测试覆盖严格解析、Schema、预算、脱敏及审计上限。
- 循环测试覆盖消息快照、正常两轮、多调用计数、拒绝后恢复、四类预算和空 Broker。
- OllamaManager 测试覆盖 `tools` 请求序列化和仅含 `tool_calls` 的合法响应。
- 真实 RoleWorker HTTP fixture 产生一次工具请求并验证最终响应、Token 汇总和审计。
- 本地 Ollama fixture 支持确定性工具调用，以便集成 profile 走真实 HTTP 路径。
- 最终运行聚合套件、完整 discovery、compileall、前端 Vitest/Playwright/typecheck/build 和 `git diff --check`。

## 非目标

- 任意终端命令、写文件、Plugin 安装或生命周期操作。
- HTTP capability token 传递或复用。
- 通用 orchestrator dispatch 迁移。
- 并行工具调用、流式工具调用和外部工具市场。
