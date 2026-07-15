# J.A.R.V.I.S. 自动化开发与演化指导设计

**日期**：2026-07-16
**状态**：已批准
**产出**：`docs/DEVELOPMENT_GUIDE.md`
**基线**：Iteration 128

## 1. 目标

为项目维护者和自动化 Agent 提供一份权威、全面、可扩展的开发指导。指导必须把核心指令的长期使命映射到当前 Solid.js、Express、FastAPI、Brain、Kernel、Skill 和 Plugin 架构，并解决：

- 阶段能力如何排序和验收。
- 自动化开发的权限、测试和 Git 边界。
- 多子代理如何穿插而不互相污染。
- 本地能力如何默认复用，外部能力如何安全下载和部署。
- 上下文接近上限时如何保存现场，压缩后如何准确续作。
- 摄像头自主视觉如何在本地、最小留存和分级响应下运行。

## 2. 已确认的用户约束

- 文档主要面向项目维护者和后续自动化 Agent。
- 采用分级自治：安全、可回滚工作自动执行，高风险操作审批。
- Git 不按微步骤频繁提交，只在稳定阶段形成检查点。
- 上下文接近上限时自动写恢复文档，不丢失目标、决策、差异和下一步。
- 任务可以穿插多子代理，但职责、写入范围和权限必须清晰。
- 默认调用匹配的本地 Skill、Plugin 和前端组件。
- 本地能力不足时可以从 GitHub 或可信注册表搜索、下载和部署。
- 外部代码、依赖、模型和数据必须经过供应链安全流程。
- 摄像头采用自主视觉代理，而不是只做手动预览。
- 视觉数据采用最小留存：原始视频只在内存环形缓冲，默认只保存不含图像的事件元数据；关键截图仅在独立租约授权后保存。
- 视觉响应采用分级权限：自动告警和本地只读任务，外部或有副作用动作审批。
- 首期视觉采用 OpenCV 与 ONNX Runtime 的独立 Python Vision Worker。

## 3. 方案比较

### 3.1 项目演化组织

#### 方案 A：能力门禁双循环

外层按基础能力演化，内层对每个阶段执行感知、设计、实现、验证、安全、文档和 Git 保存。

优点：适应研究型项目，避免为了固定轮次制造变更，能把安全和恢复作为前置门禁。

#### 方案 B：严格 Iteration 连续循环

每轮都执行完整搜索、代码、报告和提交。

优点是形式统一；缺点是容易产生重复审计、过密提交和无价值代码。

#### 方案 C：固定版本发布列车

按版本或日历推进。

优点是里程碑清晰；缺点是对本地 Agent 研究和能力依赖变化不够灵活。

**决定**：采用方案 A。Twelve-Phase Loop 保留为相关性检查框架。

### 3.2 自主视觉技术

#### 方案 A：独立 Python Vision Worker

OpenCV 负责采集，ONNX Runtime 负责本地推理，可选 MediaPipe 和 aiortc，Ollama 只分析事件关键帧。

#### 方案 B：go2rtc 加分析 Worker

go2rtc 负责多协议摄像头流，JARVIS 负责分析。

#### 方案 C：Frigate 集成

使用完整 NVR 和检测控制面。

**决定**：首期采用独立 Python Vision Worker。go2rtc 保留为多摄像头适配器；Frigate 只作为未来 NVR 场景候选。

## 4. 治理模型

长期使命、当前工程规则、当前事实、历史证据和未完成现场分层保存：

1. 安全规则和人工审批。
2. 当前代码、配置和本次测试。
3. `docs/DEVELOPMENT_GUIDE.md`。
4. 核心指令。
5. 当前项目分析。
6. CHANGELOG 与审计报告。
7. `.auto-memory/` 运行现场。

历史报告不覆盖当前代码。安全规则不因任务参数、Skill 文本或模型输出而放宽。

## 5. 目标架构

### 5.1 服务

- Solid.js 负责 UI，不做权威权限判断。
- Express 作为 BFF、静态托管、系统/Git 遥测和 Core 代理。
- FastAPI 作为 AI、编排、记忆、Plugin、工具、视觉和策略的权威核心。
- `src/main.py` 保留为兼容入口，按证据渐进迁移。

### 5.2 内部分层

    App / API → Brain → Contracts ← Kernel / Adapters / Runtime

新增能力通过 Provider、Adapter、Broker 和隔离 Runtime 接入。Brain 不直接构造模型、终端、存储、Plugin 或摄像头实现。

具体实现放入 Adapter 或 Runtime，通过 app composition root 显式注册，并提供 capability ID、契约版本、权限、配置 Schema、健康检查和统一契约测试。Plugin 作者与 PluginRuntime 作者使用不同扩展面。`PolicyEngine` 是唯一权威授权引擎，领域策略只能生成候选动作并委托其裁决。

### 5.3 统一执行

    触发
    → 风险分类
    → run_id
    → 工作包依赖图
    → 最小权限
    → 隔离 Worker
    → Broker 能力调用
    → 产物与审计
    → 验证
    → 上下文检查点
    → 阶段 Git 保存

## 6. 多子代理

主协调 Agent 负责目标、依赖图、权限和串行集成。调查、实现、验证和安全 Agent 具有单一职责。

每个工作包声明：

- 目标和基线 commit。
- 允许与禁止路径。
- 依赖关系。
- 权限与网络白名单。
- 输入、输出和验收命令。
- 上下文预算与交接路径。

只读任务可以共享工作区。写入任务默认使用独立 Worktree。公共 API、依赖锁、数据库迁移和权限策略保持串行。高风险变更不能由同一 Agent 实现和批准。

## 7. 能力生态

任务解析器按以下顺序选择能力：

    本地 Skill/Plugin/UI
    → 本地能力组合
    → 现有依赖
    → 外部搜索
    → 隔离验证与安装
    → 自定义实现

Skill 是指导，不自动获得执行权限。Plugin 是可执行代码，安装与启用分离。前端优先复用现有 Solid.js primitive 和组件，外部 React 组件不能直接混入运行时。

统一注册表保存能力 ID、版本、来源、权限、兼容性、哈希、许可证、测试和健康状态。生命周期为 discovered、quarantined、verified、installed-disabled、enabled、degraded、deprecated、blocked/removed。

## 8. 供应链和数据安全

下载采用：

    精确来源与版本
    → quarantine
    → 哈希和签名
    → 许可证
    → 静态和漏洞扫描
    → 沙箱安装
    → 最小验证
    → 锁文件和 provenance
    → 提升

Python 必须补齐精确锁定；npm 继续使用 package-lock 和 npm ci。Git 固定 commit，容器固定 digest，模型和数据固定 URL、版本与 SHA-256。

实际负载保存在 Git 忽略的 `artifacts/`，可回读来源记录保存在版本控制的 `provenance/`。未知来源、哈希不匹配、恶意行为或秘密外传自动阻断。

L2 候选可以自动评估和安装为 disabled；只有可信源、独立信任锚、兼容许可证、无权限扩大且全部验证通过时才能自动提升。否则需要人工审批。内部固定 loopback 服务由 Broker allowlist 访问；不可信下载器和 URL 代理禁止访问 loopback、私网与元数据地址。

## 9. 上下文恢复

水位默认：

- Green：`0% ≤ usage < 65%`。
- Amber：`65% ≤ usage < 80%`。
- Orange：`80% ≤ usage < 90%`，更新恢复文档并收集子代理交接。
- Red：`usage ≥ 90%`，停止派发并保存现场。

`.auto-memory/runs/<run_id>/` 保存 `resume.md`、结构化状态、决策、事件、产物、验证和子代理交接。

不可压缩内容包括目标、已确认决策、阶段、Git 基线、已完成证据、未完成项、外部资源来源、权限、未知用户改动和唯一下一动作。

压缩后先读取指令、开发指导、活动运行、恢复文档和 Git 现场，再核对资源、进程和权限，运行最小恢复验证后续作。

恢复文件使用专属 ACL、严格 Schema、路径包含、单调 revision 和完整性校验。`next_command` 只是建议，必须重新通过当前策略和权限。

## 10. 错误与验证

所有服务和 Worker 使用稳定错误码、类别、retryable、run/work package/trace ID。只有暂时性且幂等的操作可以有界重试。

验证按改动影响选择 Python、契约、前端、Worker、Plugin、Memory、供应链、Vision 和性能门禁。本次实际结果写入结构化证据；未执行不能表述为通过。

Git 只保存经过验证的阶段或独立稳定子阶段。该预授权来自用户在本次设计中提出的“完成一个阶段性开发就 Git 保存、不要过于频繁”，仅适用于当前仓库、归属明确的本地分支、精确 pathspec 和已通过门禁的阶段，可由用户随时撤销。提交前执行秘密扫描、cached diff 检查和回读，未知 hook 或签名命令需要审批。push、merge 和 release 仍需审批。自动化流程不在含未知改动的工作区执行破坏性 reset、clean 或覆盖。

## 11. 自主视觉

视觉管线：

    CameraBroker
    → VisionWorker
    → 内存环形缓冲
    → ONNX 检测和跟踪
    → 时间聚合
    → 可选 Ollama 关键帧分析
    → VisionActionPolicy
    → PolicyEngine
    → 告警、只读 Skill 或待审批任务

首期不进行身份识别、声纹、情绪推断或云端分析。默认预览 720p、检测约 5 FPS、环形缓冲约 30 秒。关键截图建议保留 24 小时，无图像元数据建议保留 30 天。

摄像头首次启用需要授权，后台观察使用可撤销租约，UI 持续显示工作状态并提供全局隐私开关。`camera.observe`、`vision.persist_snapshot` 和 `vision.export_clip` 是互不蕴含的独立租约；关键截图只有在单独授权后保存。文件写入、外部消息、设备控制和录像需要相应审批。视觉 API 使用 capability、会话所有权、Origin/CSRF 和短期令牌，不能只依赖 loopback。

CI 使用合成帧与视频夹具；真实 Windows 摄像头使用可选本机 Profile。

## 12. 演化阶段

- A：上下文续航与治理。
- B：可终止 Agent Worker。
- C：受控模型工具循环。
- D：能力注册表与安全部署。
- E：Plugin/Skill 安全运行时。
- F：长期记忆与 RAG。
- G：自主视觉代理。
- H：多模态与自主演进控制面。
- I：产品化与持续优化。

每个阶段按退出门禁推进，不绑定固定 Iteration 数量。

A 是所有长期自动化的硬前置；A 通过后 B 与 D 可以并行；C 依赖 B，E 依赖 D，F 依赖 A/D，G1-G4 依赖 A/B/D 且 G5-G7 还依赖 C；H 依赖 C/E/F/G，I 在 H 后完成正式产品化验收。

## 13. 非目标

- 不在本次文档阶段实现上述运行时代码。
- 不立即删除 Python HTTPServer。
- 不直接安装视觉或外部能力依赖。
- 不默认启用未验证 Plugin。
- 不开放任意 Shell、任意网络或摄像头云上传。
- 不为了形式完整一次性重构所有目录。

## 14. 文档验收

`docs/DEVELOPMENT_GUIDE.md` 必须：

- 与 Iteration 128 代码和报告基线一致。
- 不把历史测试数写成永久事实。
- 包含架构、流程、安全、恢复、测试、Git、扩展和视觉协议。
- 不含待定占位符或相互矛盾的权限描述。
- 让无上下文读者回答下一阶段、并行条件、下载流程、恢复顺序、Git 时机、timeout 恢复、扩展接入和审批边界。
