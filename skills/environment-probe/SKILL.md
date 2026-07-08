# Environment Probe — 本地环境动态探针技能

## 触发条件

"环境扫描"、"探测本地环境"、"系统信息"、"生成 LOCAL_ENVIRONMENT"。
每轮迭代开始时自动激活。
也可通过 `/env` 手动激活。

---

## 执行协议

### 第一步：运行时环境扫描

使用 `mcp__workspace__bash` 执行探测命令：

```bash
# Python 环境
python3 --version 2>/dev/null || python --version
which python3 || which python
pip list 2>/dev/null | head -20

# Node.js 环境
node --version
npm --version
pnpm --version 2>/dev/null

# Rust 环境
rustc --version 2>/dev/null
cargo --version 2>/dev/null

# Docker 环境
docker --version 2>/dev/null
docker ps 2>/dev/null | head -10
```

### 第二步：AI 工具链扫描

```bash
# CUDA / GPU
nvidia-smi 2>/dev/null || echo "No NVIDIA GPU"

# Ollama
ollama --version 2>/dev/null
ollama list 2>/dev/null

# LM Studio
ls -la ~/.lmstudio 2>/dev/null || echo "LM Studio not found"

# FFmpeg
ffmpeg -version 2>/dev/null | head -1
```

### 第三步：MCP 环境扫描

使用 `mcp__skills__list_skills` 获取已安装技能清单。

使用 `mcp__scheduled_tasks__list_scheduled_tasks` 获取已配置定时任务。

### 第四步：系统信息收集

```bash
# OS 信息
uname -a

# CPU 信息
nproc
lscpu | grep "Model name" 2>/dev/null || sysctl -n machdep.cpu.brand_string 2>/dev/null

# 内存信息
free -h 2>/dev/null || vm_stat 2>/dev/null

# 磁盘信息
df -h
```

### 第五步：生成 LOCAL_ENVIRONMENT.md

使用 `Write` 工具创建报告：

```markdown
# LOCAL_ENVIRONMENT.md

**生成时间**：[ISO 时间戳]  
**主机名**：[主机名]

## 运行时环境

| 工具 | 版本 | 路径 |
|------|------|------|
| Python | [版本] | [路径] |
| Node.js | [版本] | [路径] |
| npm | [版本] | [路径] |
| pnpm | [版本/未安装] | [路径] |
| Rust | [版本/未安装] | [路径] |
| Docker | [版本/未安装] | [路径] |

## AI 工具链

| 工具 | 状态 | 版本 | 可用模型 |
|------|------|------|---------|
| CUDA | [✅/❌] | [版本] | — |
| Ollama | [✅/❌] | [版本] | [模型列表] |
| LM Studio | [✅/❌] | — | — |

## 多媒体工具

| 工具 | 状态 | 版本 |
|------|------|------|
| FFmpeg | [✅/❌] | [版本] |
| ImageMagick | [✅/❌] | [版本] |

## MCP 环境

**已安装技能**：[从 list_skills 获取]  
**已配置定时任务**：[从 list_scheduled_tasks 获取]

## 可注册工具链

以下本地工具可直接注册为 Skill/Plugin：
- [工具名]：[路径] — [用途]

## 缺失依赖建议

| 缺失工具 | 安装建议 | 优先级 |
|---------|---------|-------|
| [工具名] | [安装命令] | [高/中/低] |
```

---

## 输出物

1. `LOCAL_ENVIRONMENT.md` — 完整环境报告
2. 可注册工具链清单
3. 缺失依赖补全建议

---

## 执行时机

- 每轮迭代开始时自动执行
- 环境变更后手动触发（安装新工具后）
- 用户请求时手动触发

---

**版本**：v1.0  
**工具依赖**：mcp__workspace__bash, mcp__skills__list_skills, mcp__scheduled_tasks__list_scheduled_tasks, Write
