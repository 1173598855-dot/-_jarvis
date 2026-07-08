#!/usr/bin/env python3
"""
小奕 J.A.R.V.I.S. — Ollama 聊天演示
验证 Phase 11 本地 LLM 集成是否正常工作

运行：python chat_demo.py
"""

import requests
import json
import sys

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"


def check_ollama() -> bool:
    """检查 Ollama 服务是否运行"""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def list_models() -> list:
    """列出已安装模型"""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass
    return []


def chat(model: str, message: str, history: list = None) -> tuple:
    """
    与 Ollama 对话

    Returns:
        (response_text, updated_history)
    """
    if history is None:
        history = []

    # 添加用户消息
    history.append({"role": "user", "content": message})

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": history,
                "stream": False,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            return f"错误: HTTP {resp.status_code}", history

        result = resp.json()
        assistant_msg = result.get("message", {})
        response_text = assistant_msg.get("content", "")

        # 添加助手回复到历史
        history.append({"role": "assistant", "content": response_text})

        return response_text, history

    except requests.ConnectionError:
        return "错误: 无法连接到 Ollama 服务", history
    except requests.Timeout:
        return "错误: 请求超时", history
    except Exception as e:
        return f"错误: {e}", history


def main():
    """主程序"""
    print("=" * 60)
    print("🤖 小奕 J.A.R.V.I.S. — Ollama 聊天演示")
    print("=" * 60)
    print()

    # 检查 Ollama 服务
    if not check_ollama():
        print("❌ Ollama 服务未运行")
        print("   请先启动 Ollama：")
        print("   - Windows: 双击系统托盘图标或运行 'ollama serve'")
        print("   - 或使用脚本：scripts\\start-jarvis.bat")
        sys.exit(1)

    print("✅ Ollama 服务运行正常")
    print()

    # 列出已安装模型
    models = list_models()
    if not models:
        print("⚠️  未找到已安装的模型")
        print("   请先拉取模型：ollama pull qwen2.5:7b")
        sys.exit(1)

    print(f"📦 已安装模型：{', '.join(models)}")
    print()

    # 选择模型
    model = DEFAULT_MODEL if DEFAULT_MODEL in models else models[0]
    print(f"🎯 使用模型：{model}")
    print()

    # 对话循环
    history = []
    print("💬 开始对话（输入 'quit' 或 'exit' 退出）")
    print("-" * 60)

    while True:
        try:
            user_input = input("\n你: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["quit", "exit", "退出"]:
                print("\n👋 再见！")
                break

            print("\n小奕: ", end="", flush=True)
            response, history = chat(model, user_input, history)
            print(response)

        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    main()
