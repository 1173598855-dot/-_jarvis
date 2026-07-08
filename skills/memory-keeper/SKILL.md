# Memory Keeper — 上下文压缩与多模态感知技能

## 触发条件

"记忆维护"、"上下文压缩"、"长期记忆"、"多模态分析"、"OCR"、"文件分析"。
也可通过 `/memory` 手动激活。

---

## 执行协议

### 第一部分：上下文无损压缩

**触发时机**：当会话上下文接近 Token 上限时自动激活。

**执行步骤**：

1. **识别关键信息**：
   - 使用 `Grep` 搜索当前会话中的关键决策
   - 提取技术架构决策、用户偏好、项目状态

2. **压缩策略**：
   - 保留：决策、约束、偏好、项目状态
   - 丢弃：重复讨论、已解决的问题、临时调试信息

3. **持久化**：
   - 使用 `Write` 创建记忆文件到 `.auto-memory/` 目录
   - 更新 `MEMORY.md` 索引

**记忆类型**：

| 类型 | 文件名 | 内容示例 |
|------|--------|---------|
| user | `user_preferences.md` | 用户角色、偏好、沟通风格 |
| feedback | `feedback_coding.md` | 编码规范反馈、架构决策反馈 |
| project | `project_status.md` | 当前项目状态、进行中的工作 |
| reference | `reference_tools.md` | 工具链配置、外部系统引用 |

### 第二部分：多模态文件分析

**支持的文件类型**（直接调用对应技能）：

| 文件类型 | 技能 | 能力 |
|---------|------|------|
| PDF | `pdf-reading` | 文本提取、OCR、表单识别 |
| Word (.docx) | `docx` | 读取、编辑、追踪修改 |
| PowerPoint (.pptx) | `pptx` | 读取、提取文本、幻灯片分析 |
| Excel (.xlsx) | `xlsx` | 数据读取、公式分析、格式清洗 |
| 图片 (.png/.jpg) | `Read` 工具 | 视觉分析（多模态） |

**执行流程**：

1. **识别文件类型**：使用 `Glob` 或从用户输入中提取
2. **调用对应技能**：使用 `Skill` 工具激活
3. **提取内容**：从技能输出中获取结构化数据
4. **分析总结**：使用 `Agent` 进行内容分析
5. **持久化结果**：使用 `Write` 保存分析结果

### 第三部分：记忆系统维护

**调用 `consolidate-memory` 技能**：

```
Skill("consolidate-memory")
```

该技能自动执行：
- 合并重复记忆
- 修复过时信息
- 清理索引（保持 MEMORY.md < 200 行）
- 归档过期项目记忆

**手动维护流程**：

1. **列出记忆文件**：
   ```bash
   Bash: "ls -la /sessions/.../mnt/.auto-memory/")
   ```

2. **读取记忆索引**：
   ```
   Read("/sessions/.../mnt/.auto-memory/MEMORY.md")
   ```

3. **更新/创建记忆**：
   ```
   Write("/sessions/.../mnt/.auto-memory/[type]_[name].md", content)
   ```

4. **更新索引**：
   ```
   Edit("MEMORY.md", "[旧索引行]", "[新索引行]")
   ```

---

## 输出物

1. 压缩后的上下文摘要（在会话中输出）
2. 持久化记忆文件（`.auto-memory/` 目录）
3. 更新的记忆索引（`MEMORY.md`）
4. 多模态文件分析结果（如适用）

---

## 安全约束

- 记忆文件仅存储非敏感信息（不存储密码、密钥、个人信息）
- 定期清理过期记忆（通过 `consolidate-memory` 技能）
- 记忆索引保持简洁（< 200 行，每行 < 150 字符）

---

**版本**：v1.0  
**工具依赖**：Grep, Glob, Read, Write, Edit, Skill(consolidate-memory), Bash, pdf-reading, docx, pptx, xlsx
