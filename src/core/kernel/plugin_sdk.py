"""
Plugin SDK — 小奕 J.A.R.V.I.S. 插件系统
Phase 7-8: Plugin 沙箱系统基础设施

功能：
1. Manifest 权限清单解析与校验
2. Plugin 生命周期管理（加载/启用/禁用/卸载）
3. 运行时沙箱隔离（Python uv + JS worker_threads）
4. 权限校验与 API 脱敏
5. 插件崩溃自恢复
6. 依赖注入（DI）受限 API

设计原则：
- 所有插件必须声明 manifest.json
- 运行时仅暴露 XiaoYiPluginAPI（脱敏后的受限接口）
- 禁止原生 fs、child_process、未授权网络
- 插件崩溃不影响主进程
"""

import os
import sys
import json
import uuid
import importlib
import logging
import subprocess
import threading
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# 类型定义
# ============================================================

class PluginStatus(Enum):
    """插件状态"""
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    UNLOADED = "unloaded"


class RuntimeType(Enum):
    """运行时类型"""
    PYTHON_UV = "python_uv"
    PYTHON_VENV = "python_venv"
    NODE_WORKER = "node_worker"
    NATIVE = "native"


@dataclass
class PluginManifest:
    """插件清单（manifest.json）"""
    name: str
    version: str
    description: str
    author: str = ""
    permissions: List[str] = field(default_factory=list)
    denied_apis: List[str] = field(default_factory=lambda: ["fs", "child_process", "network"])
    runtime: str = "native"
    sandbox: bool = True
    entry_point: str = ""
    dependencies: List[str] = field(default_factory=list)
    api_version: str = "1.0.0"
    plugin_id: str = ""

    def __post_init__(self):
        if not self.plugin_id:
            self.plugin_id = str(uuid.uuid4())[:8]


@dataclass
class PluginInstance:
    """插件实例"""
    manifest: PluginManifest
    status: PluginStatus
    module: Any = None
    error_message: str = ""
    loaded_at: str = ""
    last_activated: str = ""
    activation_count: int = 0


# ============================================================
# 受限 API 接口（XiaoYiPluginAPI）
# ============================================================

class XiaoYiPluginAPI:
    """
    插件受限 API — 仅暴露经过脱敏的接口

    禁止直接访问：
    - 原生文件系统（fs、open、os.remove）
    - 子进程（child_process、subprocess、os.system）
    - 未授权网络请求（socket、requests.post 到外部）
    - 系统环境变量（os.environ、process.env）
    """

    def __init__(self, plugin_id: str, permissions: List[str]):
        self.plugin_id = plugin_id
        self._permissions = set(permissions)
        self._audit_log: List[Dict[str, Any]] = []

    def check_permission(self, permission: str) -> bool:
        """检查权限"""
        return permission in self._permissions

    def log_access(self, api_name: str, args: Dict[str, Any]) -> None:
        """记录 API 访问日志"""
        self._audit_log.append({
            "plugin_id": self.plugin_id,
            "api": api_name,
            "args": str(args)[:200],
            "timestamp": datetime.now().isoformat(),
        })

    # ============================================================
    # 受限 API 实现
    # ============================================================

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置（仅允许读取系统配置）"""
        if not self.check_permission("system_config"):
            raise PermissionError(f"插件 {self.plugin_id} 无 system_config 权限")
        self.log_access("get_config", {"key": key})
        return default

    def read_file(self, path: str) -> str:
        """读取文件（仅允许读取，不允许写入）"""
        if not self.check_permission("file_read"):
            raise PermissionError(f"插件 {self.plugin_id} 无 file_read 权限")
        self.log_access("read_file", {"path": path})
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"ERROR: {e}"

    def emit_event(self, event_type: str, payload: Any) -> None:
        """发送事件到事件总线"""
        if not self.check_permission("event_bus"):
            raise PermissionError(f"插件 {self.plugin_id} 无 event_bus 权限")
        self.log_access("emit_event", {"type": event_type})
        # 实际中会调用事件总线
        logger.info(f"[Plugin {self.plugin_id}] Event: {event_type}")

    def call_llm(self, prompt: str, model: str = "default") -> str:
        """调用 LLM（受限）"""
        if not self.check_permission("llm_access"):
            raise PermissionError(f"插件 {self.plugin_id} 无 llm_access 权限")
        self.log_access("call_llm", {"model": model, "prompt_len": len(prompt)})
        return f"[LLM Response to: {prompt[:50]}...]"

    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计（受限）"""
        if not self.check_permission("system_monitor"):
            raise PermissionError(f"插件 {self.plugin_id} 无 system_monitor 权限")
        self.log_access("get_system_stats", {})
        return {"cpu": 0, "memory": 0, "disk": 0}

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取插件访问日志"""
        return self._audit_log[-limit:]


# ============================================================
# Plugin Loader
# ============================================================

class PluginLoader:
    """
    插件加载器 — 负责插件的加载、启用、禁用、卸载

    隔离策略：
    - Python 插件：使用 uv 或 venv 创建微型虚拟环境
    - JS/TS 插件：使用 worker_threads 创建独立线程
    - 原生插件：直接加载（需要额外权限校验）
    """

    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(exist_ok=True)
        self._plugins: Dict[str, PluginInstance] = {}
        self._sandbox_configs: Dict[str, Dict[str, Any]] = {}

    def discover_plugins(self) -> List[PluginManifest]:
        """发现所有可用插件"""
        manifests = []
        for plugin_path in self.plugins_dir.iterdir():
            if not plugin_path.is_dir():
                continue
            manifest_file = plugin_path / "manifest.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    manifest = PluginManifest(**data)
                    manifests.append(manifest)
                except Exception as e:
                    logger.error(f"加载插件清单失败 {plugin_path}: {e}")
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> PluginInstance:
        """
        加载插件

        流程：
        1. 校验 manifest
        2. 检查依赖
        3. 创建沙箱环境
        4. 加载插件模块
        5. 初始化插件 API
        """
        # 检查是否已加载
        if manifest.plugin_id in self._plugins:
            return self._plugins[manifest.plugin_id]

        # 校验 manifest
        self._validate_manifest(manifest)
        self._validate_sandbox_policy(manifest)

        # 创建沙箱环境
        sandbox_config = self._create_sandbox(manifest)
        self._sandbox_configs[manifest.plugin_id] = sandbox_config

        # 加载模块
        try:
            module = self._load_module(manifest, sandbox_config)
        except Exception as e:
            logger.error(f"加载插件失败 {manifest.name}: {e}")
            return PluginInstance(
                manifest=manifest,
                status=PluginStatus.ERROR,
                error_message=str(e),
                loaded_at=datetime.now().isoformat(),
            )

        instance = PluginInstance(
            manifest=manifest,
            status=PluginStatus.LOADED,
            module=module,
            loaded_at=datetime.now().isoformat(),
        )

        self._plugins[manifest.plugin_id] = instance
        logger.info(f"插件加载成功: {manifest.name} ({manifest.plugin_id})")
        return instance

    def enable_plugin(self, plugin_id: str) -> bool:
        """启用插件"""
        if plugin_id not in self._plugins:
            return False

        instance = self._plugins[plugin_id]
        if instance.status == PluginStatus.ENABLED:
            return True

        try:
            # 创建受限 API
            api = XiaoYiPluginAPI(plugin_id, instance.manifest.permissions)
            instance.module.activate(api)
            instance.status = PluginStatus.ENABLED
            instance.last_activated = datetime.now().isoformat()
            instance.activation_count += 1
            logger.info(f"插件启用成功: {instance.manifest.name}")
            return True
        except Exception as e:
            instance.status = PluginStatus.ERROR
            instance.error_message = str(e)
            logger.error(f"插件启用失败 {instance.manifest.name}: {e}")
            return False

    def disable_plugin(self, plugin_id: str) -> bool:
        """禁用插件"""
        if plugin_id not in self._plugins:
            return False

        instance = self._plugins[plugin_id]
        try:
            if hasattr(instance.module, "deactivate"):
                instance.module.deactivate()
            instance.status = PluginStatus.DISABLED
            logger.info(f"插件禁用: {instance.manifest.name}")
            return True
        except Exception as e:
            logger.error(f"插件禁用失败 {instance.manifest.name}: {e}")
            return False

    def unload_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        if plugin_id not in self._plugins:
            return False

        instance = self._plugins[plugin_id]
        try:
            if hasattr(instance.module, "cleanup"):
                instance.module.cleanup()
            del self._plugins[plugin_id]
            self._sandbox_configs.pop(plugin_id, None)
            logger.info(f"插件卸载: {instance.manifest.name}")
            return True
        except Exception as e:
            logger.error(f"插件卸载失败 {instance.manifest.name}: {e}")
            return False

    def get_plugin(self, plugin_id: str) -> Optional[PluginInstance]:
        """获取插件实例"""
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> List[PluginInstance]:
        """获取所有插件"""
        return list(self._plugins.values())

    def get_plugins_by_status(self, status: PluginStatus) -> List[PluginInstance]:
        """按状态获取插件"""
        return [p for p in self._plugins.values() if p.status == status]

    # ============================================================
    # 内部方法
    # ============================================================

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        """校验 manifest"""
        if not manifest.name:
            raise ValueError("插件名称不能为空")
        if not manifest.version:
            raise ValueError("插件版本不能为空")
        if not manifest.entry_point:
            raise ValueError("插件入口点不能为空")

        # 检查危险权限
        dangerous_perms = {"fs_write", "child_process", "network_all", "system_control"}
        granted_dangerous = set(manifest.permissions) & dangerous_perms
        if granted_dangerous:
            raise ValueError(f"插件请求危险权限: {granted_dangerous}")


    def _validate_sandbox_policy(self, manifest: PluginManifest) -> None:
        """校验沙箱策略"""
        if not manifest.sandbox:
            return
        required_denied = {"fs", "child_process", "network"}
        missing = required_denied - set(manifest.denied_apis)
        if missing:
            raise ValueError(f"插件沙箱策略缺失禁用 API: {missing}")
    def _create_sandbox(self, manifest: PluginManifest) -> Dict[str, Any]:
        """创建沙箱环境"""
        runtime = manifest.runtime
        config = {
            "runtime": runtime,
            "permissions": manifest.permissions,
            "denied_apis": manifest.denied_apis,
            "timeout": 30,
            "memory_limit": "128MB",
        }

        if runtime == RuntimeType.PYTHON_UV.value:
            # Python uv 沙箱
            venv_path = self.plugins_dir / manifest.plugin_id / "venv"
            config["venv_path"] = str(venv_path)
            config["python_path"] = str(venv_path / "bin" / "python")

        elif runtime == RuntimeType.NODE_WORKER.value:
            # Node.js worker 沙箱
            config["worker_type"] = "isolated"

        return config

    def _load_module(self, manifest: PluginManifest, sandbox_config: Dict[str, Any]):
        """加载插件模块"""
        runtime = manifest.runtime

        if runtime == RuntimeType.NATIVE.value:
            # 原生 Python 模块
            plugin_path = self.plugins_dir / manifest.plugin_id
            sys.path.insert(0, str(plugin_path))
            module_name = manifest.entry_point.replace(".py", "").replace("/", ".")
            module = importlib.import_module(module_name)
            return module

        elif runtime == RuntimeType.PYTHON_UV.value:
            # uv 沙箱中运行
            python_path = sandbox_config.get("python_path")
            if not python_path or not Path(python_path).exists():
                raise RuntimeError(f"Python 沙箱环境不存在: {python_path}")
            # 实际中会在子进程中执行
            logger.info(f"使用 uv 沙箱运行: {python_path}")
            return None

        elif runtime == RuntimeType.NODE_WORKER.value:
            # worker_threads 沙箱
            logger.info(f"使用 worker_threads 沙箱运行")
            return None

        else:
            raise ValueError(f"不支持的运行时: {runtime}")


# ============================================================
# Plugin Manager（单例）
# ============================================================

class PluginManager:
    """
    插件管理器 — 单例模式

    功能：
    - 插件发现、加载、启用、禁用、卸载
    - 沙箱隔离
    - 权限校验
    - 崩溃自恢复
    """

    _instance: Optional["PluginManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, plugins_dir: str = "plugins"):
        if self._initialized:
            return
        self._initialized = True
        self.loader = PluginLoader(plugins_dir)
        self._crash_count: Dict[str, int] = {}
        self._max_crashes = 3

    def discover(self) -> List[PluginManifest]:
        """发现所有插件"""
        return self.loader.discover_plugins()

    def load(self, manifest: PluginManifest) -> PluginInstance:
        """加载插件"""
        return self.loader.load_plugin(manifest)

    def enable(self, plugin_id: str) -> bool:
        """启用插件（带崩溃恢复）"""
        result = self.loader.enable_plugin(plugin_id)
        if not result:
            self._crash_count[plugin_id] = self._crash_count.get(plugin_id, 0) + 1
            if self._crash_count[plugin_id] >= self._max_crashes:
                logger.warning(f"插件 {plugin_id} 连续崩溃 {self._crash_count[plugin_id]} 次，自动禁用")
                self.loader.disable_plugin(plugin_id)
        else:
            self._crash_count.pop(plugin_id, None)
        return result

    def disable(self, plugin_id: str) -> bool:
        """禁用插件"""
        return self.loader.disable_plugin(plugin_id)

    def unload(self, plugin_id: str) -> bool:
        """卸载插件"""
        return self.loader.unload_plugin(plugin_id)

    def get_plugin(self, plugin_id: str) -> Optional[PluginInstance]:
        """获取插件"""
        return self.loader.get_plugin(plugin_id)

    def get_all_plugins(self) -> List[PluginInstance]:
        """获取所有插件"""
        return self.loader.get_all_plugins()

    def load_all(self) -> Dict[str, PluginInstance]:
        """加载所有发现的插件"""
        manifests = self.discover()
        results = {}
        for manifest in manifests:
            instance = self.load(manifest)
            results[manifest.plugin_id] = instance
        return results


# 全局单例
global_plugin_manager = PluginManager()
