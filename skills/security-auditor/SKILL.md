# Security Auditor — 静态代码审计与沙箱隔离技能

## 触发条件

"安全审计"、"代码审计"、"AST 扫描"、"沙箱隔离"、"供应链安全检查"。
也可通过 `/security` 手动激活。

---

## 执行协议

### 第一步：高危模式静态扫描

使用 `Grep` 搜索高危敏感词：

```bash
# 危险命令模式
Grep(pattern="rm -rf", glob="*.{py,js,ts,sh,bash}", output_mode="content")
Grep(pattern="os\.system|subprocess\.call|exec\(", glob="*.py", output_mode="content")
Grep(pattern="child_process|exec\(|spawn\(", glob="*.{js,ts}", output_mode="content")
Grep(pattern="format\(|delete|erase|wipe", glob="*.{py,js,ts}", output_mode="content")
Grep(pattern="registry|reg add|reg delete", glob="*.{py,js,ts,sh}", output_mode="content")
Grep(pattern="dd if=|shred|mkfs", glob="*.{sh,bash}", output_mode="content")
```

使用 `Read` 检查文件头部，识别：
- 未声明的 `import socket` / `import requests`（网络外发）
- 直接文件系统操作（`open(..., 'w')`、`fs.writeFile`）
- 环境变量读取（`os.environ`、`process.env`）

### 第二步：Agent 辅助 AST 分析

调用 `Agent`（subagent_type: "general-purpose"）进行深度分析：

```
对以下代码进行静态安全审计：

文件：[文件路径]
内容：[代码片段]

检查项：
1. 是否包含高危敏感词（rm -rf, format, os.system, child_process 等）
2. 是否包含未声明的网络请求
3. 是否直接操作文件系统或子进程
4. 是否读取敏感环境变量
5. 是否有数据外发风险

输出：安全评级（安全 / 需审查 / 高危）+ 具体风险点
```

### 第三步：风险归档

如发现高危代码，使用 `Write` 工具创建/追加至 `RISK_COMPONENTS.log`：

```markdown
## [时间戳] 风险组件归档

**文件**：[文件路径]
**风险等级**：🔴 极高 / 🟠 高 / 🟡 中
**风险类型**：[具体类型]
**代码片段**：
\```[语言]
[问题代码]
\```
**拦截原因**：[具体说明]
**处理动作**：中止集成 / 标记为风险 / 请求用户确认
```

### 第四步：沙箱隔离配置

为 Skill 生成隔离配置：

**Python Skill**：
```bash
# 创建微型虚拟环境
uv venv .skills/[skill-name]/venv
uv pip install --python .skills/[skill-name]/venv/bin/python [依赖包]
```

**JS/TS Plugin**：
```javascript
// 使用 Node.js worker_threads 创建隔离环境
// const { Worker } = require('worker_threads');
// const worker = new Worker(pluginEntryPoint, { workerData: {} });
```

### 第五步：权限清单生成

为每个 Skill/Plugin 生成 `manifest.json`：

```json
{
  "name": "[skill-name]",
  "version": "1.0.0",
  "permissions": ["system_monitor"],
  "denied": ["fs", "child_process", "network"],
  "runtime": "uv",
  "sandbox": true
}
```

---

## 输出物

1. `RISK_COMPONENTS.log` — 风险组件归档（如发现高危）
2. `manifest.json` — Skill/Plugin 权限清单
3. 安全审计报告（Markdown 格式）

---

## 快速扫描命令

使用 `mcp__workspace__bash` 执行：

```bash
# 扫描所有代码文件的高危模式
grep -r "rm -rf\|os\.system\|subprocess\|child_process\|format(" --include="*.py" --include="*.js" --include="*.ts" .

# 检查网络请求
grep -r "import socket\|import requests\|fetch(" --include="*.py" --include="*.js" --include="*.ts" .

# 检查文件系统操作
grep -r "open(.*'w')\|fs\.write\|os\.remove" --include="*.py" --include="*.js" --include="*.ts" .
```

---

## 安全铁律

- ❌ 未经 AST 审计的外部代码，严禁集成
- ❌ 未在沙箱中运行的 Skill，严禁执行
- ❌ 未声明权限的 Plugin，严禁加载
- ✅ 所有 Skill 必须运行在隔离环境中
- ✅ 所有 Plugin 必须通过 DI 注入受限 API
- ✅ 回滚机制必须随时可用

---

**版本**：v1.0  
**工具依赖**：Grep, Read, Agent(general-purpose), Write, mcp__workspace__bash
