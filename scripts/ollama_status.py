"""
Ollama 服务状态检测脚本 — 小奕 J.A.R.V.I.S.
检测 Ollama 服务状态、已安装模型、GPU 信息，输出结构化报告

用法：
    python scripts/ollama_status.py

环境变量：
    OLLAMA_BASE_URL — 覆盖默认地址 http://localhost:11434

退出码：
    0 — 服务运行中
    1 — 服务未启动
"""

import argparse
import json
import os
import sys

# 确保能导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "kernel"))

from ollama_manager import OllamaManager


def build_report(manager: OllamaManager) -> dict:
    """构建结构化状态报告"""
    status = manager.get_status()

    report = {
        "service": {
            "running": status.running,
            "url": manager.base_url,
            "version": status.version,
        },
        "models": {
            "count": len(status.models),
            "list": [],
        },
        "gpu": {
            "available": status.gpu_available,
            "name": status.gpu_name,
        },
    }

    if status.running:
        # 模型详情
        for model in status.models:
            size_gb = int(model.size) / (1024 ** 3) if model.size else 0
            report["models"]["list"].append({
                "name": model.name,
                "size_gb": round(size_gb, 2),
                "modified_at": model.modified_at,
                "details": model.details or {},
            })

        # GPU 详细信息 — 通过 /api/ps 获取
        gpu_data = manager.get_gpu_info()
        if gpu_data.get("available"):
            running_models = gpu_data.get("models", [])
            report["gpu"]["running_models"] = [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "digest": m.get("digest", ""),
                    "expires_at": m.get("expires_at", ""),
                }
                for m in running_models
            ]
            report["gpu"]["count"] = len(running_models)
        else:
            report["gpu"]["error"] = gpu_data.get("error", "无 GPU 信息")

    return report


def print_human_report(report: dict) -> None:
    """人类可读的终端输出"""
    svc = report["service"]
    print("=" * 60)
    print("Ollama 服务状态报告")
    print("=" * 60)

    # 服务状态
    if svc["running"]:
        print("  状态    : 运行中")
        print(f"  地址    : {svc['url']}")
        print(f"  版本    : {svc['version'] or '未知'}")
    else:
        print("  状态    : 未启动")
        print(f"  地址    : {svc['url']}")
        print("  提示    : 请先执行 ollama serve")
        print("=" * 60)
        return

    # GPU 信息
    gpu = report["gpu"]
    if gpu["available"]:
        print(f"  GPU     : 可用 ({gpu['name']})")
        if "running_models" in gpu and gpu["running_models"]:
            print(f"  运行中模型 ({gpu['count']}):")
            for m in gpu["running_models"]:
                size_gb = m["size"] / (1024 ** 3) if m["size"] else 0
                print(f"    - {m['name']} ({size_gb:.1f} GB)")
    else:
        err = gpu.get("error", "未检测到")
        print(f"  GPU     : 不可用 ({err})")

    # 模型列表
    models = report["models"]
    print(f"\n  已安装模型 ({models['count']} 个):")
    if models["list"]:
        for i, m in enumerate(models["list"], 1):
            print(f"    {i}. {m['name']}  [{m['size_gb']:.1f} GB]")
            if m["details"]:
                params = m["details"].get("parameter_size", "?")
                quant = m["details"].get("quantization_level", "?")
                print(f"       参数: {params} | 量化: {quant}")
    else:
        print("    （空）请使用 ollama pull 拉取模型")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Ollama 服务状态检测 — 小奕 J.A.R.V.I.S."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出报告",
    )
    args = parser.parse_args()

    # 读取环境变量 OLLAMA_BASE_URL
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    manager = OllamaManager(base_url=base_url, timeout=10)

    report = build_report(manager)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human_report(report)

    # 退出码：0=运行中，1=未启动
    sys.exit(0 if report["service"]["running"] else 1)


if __name__ == "__main__":
    main()
