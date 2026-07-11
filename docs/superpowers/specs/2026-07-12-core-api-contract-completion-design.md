# Core API 契约补全设计

**日期**：2026-07-12

## 目标

在 Iteration 101-105 内，将插件、记忆、事件、SSE 与剩余稳定错误路径纳入
`contracts/core-api.openapi.json`，使 Express、Python HTTPServer 和 FastAPI 对同一能力返回
一致的机器可读形状，并由真实服务测试证明。

完成标准：

- 共享 OpenAPI 声明本批次涉及的所有请求、成功响应和稳定错误响应。
- 跨实现测试真实启动 Express、Python HTTPServer、FastAPI 适配层与本地 Ollama fixture。
- 记忆生命周期、插件动作和 SSE 终止语义均有非空数据或失败路径验证。
- 规范 Python 聚合套件、完整 discovery、静态编译、前端 Vitest、Playwright、typecheck
  与生产构建全部通过。
- 每轮更新 `PROJECT_ANALYSIS.md`、`CHANGELOG.md` 与对应 `AUDIT_REPORT_N.md`，报告窗口始终
  保留最近 10 份。

## 方案选择

采用现有依赖零新增的 OpenAPI JSON 与真实跨进程验证器。Schemathesis、openapi-core 和 Ajv
均通过初步许可证与活跃度筛选，但它们不能替代本项目对 Python/Node 适配器、Core 代理和 SSE
帧的真实验证。本批次不引入新运行时或开发依赖。

不选择先启用真实 Ollama 强制门禁，因为当前环境没有持续运行的 Ollama 服务；也不先做前端
拆包，因为其优先级为 P2，且应先取得低端设备测量数据。

## 架构与边界

`contracts/core-api.openapi.json` 继续作为稳定 HTTP 契约的单一来源。业务实现仍由三套服务
分别拥有，契约测试只负责启动服务、发起真实请求、解析 SSE，并对响应 schema 与稳定语义
进行断言，不复制业务逻辑。

Express 的能力端点通过 `JARVIS_CORE_API_URL` 指向测试中的 Core HTTP 服务，从而验证真实
代理链路。FastAPI 使用隔离的 `AppState`，Python HTTPServer 使用隔离临时记忆目录；测试结束
后关闭所有服务并清理探针数据。

## 五轮交付

### Iteration 101：只读能力

新增 `PluginListResponse`、`MemoryEntriesResponse`、`EventListResponse` 及条目 schema，声明
`GET /api/plugins`、`GET /api/memory/entries`、`GET /api/events`。测试覆盖三套实现和 Express
真实 Core 代理；独立 schema 样例确保数组元素字段确实被验证。

### Iteration 102：记忆生命周期

声明 `POST /api/memory/store` 与 `DELETE /api/memory/probes/{memory_type}/{entry_id}` 的请求和
响应。跨实现测试执行创建、读取、带正确 token 删除、删除后不可见，并验证错误 token 返回
`MEMORY_NOT_FOUND`。

### Iteration 103：插件动作

声明 load/enable/disable 请求与响应。统一空 `plugin_id` 为 400 `MISSING_PLUGIN_ID`，不存在插件
为 404 `PLUGIN_NOT_FOUND`；成功路径使用仓库内插件 fixture 或隔离 manifest 验证稳定字段。

### Iteration 104：SSE 协议

三套服务统一输出 `{model, content, done}` 内容帧、`{error:{code,message}}` 错误帧和最终
`[DONE]`。OpenAPI 声明 `text/event-stream`，测试验证至少一个内容帧、一个原生完成帧和且仅一个
终止标记；错误流不得伪造完成。

### Iteration 105：错误收口

FastAPI 的请求校验错误转为共享 `ErrorResponse`；Express 终端、Git、Core 代理和 SPA fallback
不再返回字符串 `error`。契约测试遍历所有声明响应，确保每个稳定错误路径都有 schema，并以
定向失败测试证明客户端始终可获得 `error.code` 与 `error.message`。

## 错误处理

稳定错误统一使用：

```json
{"error":{"code":"STABLE_CODE","message":"human readable"}}
```

HTTP 状态表达类别，`code` 表达机器语义。代理不得吞掉 Core 服务已返回的状态与合法 JSON；
仅连接失败、超时或无效 JSON 由 Express 转换为 `CORE_API_*`。SSE 在响应头已发送后不能改变
HTTP 状态，因此错误必须作为标准错误帧发出，且不再追加 `[DONE]`。

## 测试策略

每轮先增加能失败的契约断言，再做最小实现修改。定向测试通过后运行受影响模块；每轮交付前
运行规范聚合套件，批次结束运行完整 Python 与前端验证基线。涉及子进程和临时数据的测试必须
使用动态端口、loopback、隔离目录和 `finally` 清理，不能依赖外部 Ollama 或互联网。

## 范围外

- 不引入新的契约测试依赖。
- 不改变前端视觉设计或导航。
- 不把真实 Ollama 可用性变成当前机器的强制门禁。
- 不扩展编排器与角色业务功能；仅在最终错误门禁需要时声明已有稳定响应。
