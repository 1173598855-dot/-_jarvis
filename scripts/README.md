# 维护脚本

本目录只保存可重复执行的维护工具，不保存一次性代码生成器。

| 脚本 | 用途 | 是否修改项目文件 |
|---|---|---|
| `ollama_status.py` | 检查本机 Ollama 服务、模型与基础状态 | 否 |
| `ruff_check.py` | 对指定 Python 源码运行 Ruff 检查，可选生成报告 | 默认否；`--fix` 时会修改 |

常用命令：

```powershell
python scripts/ollama_status.py
python scripts/ruff_check.py
```
