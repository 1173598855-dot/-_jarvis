# 维护脚本

本目录只保存可重复执行的维护和验证工具，不保存一次性代码生成器。

| 脚本 | 用途 | 是否修改项目文件 |
|---|---|---|
| `ollama_status.py` | 检查本机 Ollama 服务、模型与基础状态 | 否 |
| `ruff_check.py` | 对指定 Python 源码运行 Ruff 检查，可选生成报告 | 默认否；`--fix` 时会修改 |
| `discover_tests.py` | 在独立进程中发现并运行 Python 测试，支持超时和 JSON 报告 | 否 |
| `local_integration_profile.py` | 检查本机 FastAPI、Express 和 Ollama 的真实联调 | 否 |
| `ci_local_integration.py` | 启动仓库自有服务夹具并运行必需服务联调 | 会创建并清理临时服务 |
| `local_ollama_fixture.py` | 提供确定性的本地 Ollama 测试夹具 | 仅运行期间监听端口 |

常用命令：

```powershell
python scripts/ollama_status.py
python scripts/ruff_check.py
python scripts/discover_tests.py --timeout 1800
python scripts/ci_local_integration.py --require-services
```
