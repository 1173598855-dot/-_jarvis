# LOCAL_ENVIRONMENT.md
**小奕 J.A.R.V.I.S. — 本地环境动态探针报告**

**探测时间**：2026-07-08  
**主机名**：claude  
**OS**：Linux (Ubuntu 22.04.1 LTS, x86_64)

---

## 运行时环境

| 工具 | 版本 | 路径 | 状态 |
|------|------|------|------|
| Python | 3.10.12 | `/usr/bin/python3` | ✅ |
| Node.js | v22.22.3 | — | ✅ |
| npm | 10.9.8 | — | ✅ |
| pnpm | 11.10.0 | ~/.npm-global/bin/pnpm | ✅ |
| Rust | — | — | ❌ 未安装 |
| Docker | — | — | ❌ 未安装 |

## AI 工具链

| 工具 | 状态 | 版本 | 可用模型 |
|------|------|------|---------|
| CUDA | ❌ | — | — |
| Ollama | ✅ 已运行 | 0.31.1 | 服务正常，待拉取模型 |
| LM Studio | ❌ | — | — |

## 多媒体工具

| 工具 | 状态 | 版本 |
|------|------|------|
| FFmpeg | ✅ | 4.4.2 |

## 系统资源

| 资源 | 总量 | 已用 | 可用 | 使用率 |
|------|------|------|------|--------|
| CPU | 2 核 | — | — | — |
| 内存 | 3.8 GiB | 144 MiB | 3.2 GiB | 4% |
| 磁盘 | 9.6 GB | 5.2 GB | 4.4 GB | 54% |

## MCP 环境

**已安装技能**：14 个（jarvis-orchestrator, project-scanner, github-learner, security-auditor, ui-enforcer, audit-reporter, memory-keeper, environment-probe, karpathy-guidelines, code-review, tdd, diagnosing-bugs, research, knowledge-graph-mapping）  
**已配置定时任务**：2 个（jarvis-daily-scan, jarvis-weekly-github）  
**已部署 Artifacts**：1 个（jarvis-dashboard）

## 可注册工具链

以下本地工具可直接注册为 Skill/Plugin：
- Python 3.10.12 — 脚本自动化、数据处理
- Node.js v22.22.3 — 前端构建、工具开发
- FFmpeg 4.4.2 — 音视频处理
- npm 10.9.8 — 包管理

## 缺失依赖建议

| 缺失工具 | 安装建议 | 优先级 | 用途 |
|---------|---------|--------|------|
| pnpm | `npm install -g pnpm` | 高 | 包管理（推荐替代 npm） |
| Ollama | `ollama pull qwen2.5:7b` | 🔴 高（本地 LLM 核心依赖） | 已安装，需拉取模型 |
| Docker | 参考 docker.com 安装 | 中 | 容器化隔离 |
| nvidia-smi (CUDA) | 需 NVIDIA GPU | 低 | GPU 加速推理 |

---

**报告生成**：小奕 JARVIS 自主演进引擎 Phase 5  
**状态**：✅ 环境探测完成
