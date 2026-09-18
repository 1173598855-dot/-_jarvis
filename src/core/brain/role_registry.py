"""
角色注册表 - 小奕 J.A.R.V.I.S. Phase 11 MetaGPT 集成层
萃取自 MetaGPT 的 Role / Agent 定义模式

MetaGPT 核心概念映射：
  MetaGPT Role   -> XiaoYi AgentProfile（角色定义）
  MetaGPT Agent  -> XiaoYi OrchestratorAgent（编排代理）
  MetaGPT Action -> XiaoYi AgentAction（原子动作）
  MetaGPT Memory -> Orchestrator.metadata（任务上下文）

设计原则：
- 零外部依赖（仅 stdlib，与 orchestrator.py 一致）
- 角色可配置（YAML/JSON 友好格式）
- 支持角色继承（parent_role）
- 与现有 Orchestrator 完全兼容（通过 register() 接口）

运行：python role_registry.py [list|register|dispatch <role_name> <prompt>]
"""

import copy
import json
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.contracts.bounded_json import read_bounded_json


@dataclass
class AgentProfile:
    """
    代理角色配置 - 等价于 MetaGPT 的 Role 类
    """
    name: str
    display_name: str
    description: str
    parent_role: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    prompt_template: str = "You are {name}. {description}\n\nTask: {task}"
    tools: List[str] = field(default_factory=list)
    priority: int = 5
    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolve_prompt(self, task: str) -> str:
        return self.prompt_template.format(
            name=self.display_name,
            description=self.description,
            task=task,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class RoleRegistry:
    """线程安全的角色注册表"""

    def __init__(self):
        self._roles: Dict[str, AgentProfile] = {}
        self._lock = threading.Lock()

    def register(self, profile: AgentProfile) -> None:
        owned_profile = copy.deepcopy(profile)
        with self._lock:
            if owned_profile.name in self._roles:
                raise ValueError(f"Role '{owned_profile.name}' already registered")
            self._validate_acyclic_registration(owned_profile)
            self._roles[owned_profile.name] = owned_profile

    def _validate_acyclic_registration(self, profile: AgentProfile) -> None:
        """Reject a registration that closes a parent-role cycle."""
        path = [profile.name]
        seen = {profile.name}
        parent_name = profile.parent_role
        while parent_name is not None:
            if parent_name in seen:
                cycle = " -> ".join([*path, parent_name])
                raise ValueError(f"Role inheritance cycle detected: {cycle}")
            seen.add(parent_name)
            path.append(parent_name)
            parent = self._roles.get(parent_name)
            if parent is None:
                return
            parent_name = parent.parent_role

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._roles.pop(name, None) is not None

    def get(self, name: str) -> Optional[AgentProfile]:
        with self._lock:
            profile = self._roles.get(name)
            if profile is None:
                return None
            return self._resolve_inheritance(profile)

    def list_roles(self, capability: Optional[str] = None) -> List[AgentProfile]:
        with self._lock:
            profiles = [self._resolve_inheritance(p) for p in self._roles.values()]
        if capability:
            profiles = [p for p in profiles if capability in p.capabilities]
        return sorted(profiles, key=lambda p: -p.priority)

    def _resolve_inheritance(self, profile: AgentProfile) -> AgentProfile:
        chain = [profile]
        current = profile
        while current.parent_role is not None:
            parent = self._roles.get(current.parent_role)
            if parent is None:
                break
            chain.append(parent)
            current = parent

        resolved = copy.deepcopy(chain[-1])
        for child in reversed(chain[:-1]):
            resolved = AgentProfile(
                name=child.name,
                display_name=child.display_name,
                description=child.description,
                parent_role=None,
                capabilities=list(dict.fromkeys(resolved.capabilities + child.capabilities)),
                constraints=list(dict.fromkeys(resolved.constraints + child.constraints)),
                prompt_template=child.prompt_template,
                tools=list(dict.fromkeys(resolved.tools + child.tools)),
                priority=max(resolved.priority, child.priority),
                metadata=copy.deepcopy({**resolved.metadata, **child.metadata}),
            )
        return resolved

    def to_json(self) -> str:
        with self._lock:
            return json.dumps(
                {name: p.to_dict() for name, p in self._roles.items()},
                ensure_ascii=False, indent=2,
            )

    @classmethod
    def from_json(cls, json_str: str) -> "RoleRegistry":
        registry = cls()
        data = json.loads(json_str)
        for name, d in data.items():
            registry.register(AgentProfile.from_dict(d))
        return registry

    def __len__(self) -> int:
        with self._lock:
            return len(self._roles)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._roles


READ_ONLY_ROLE_TOOLS: Dict[str, List[str]] = {
    "product_manager": ["orchestrator_status", "memory_search"],
    "architect": [
        "system_status", "model_list", "orchestrator_status",
        "memory_search", "repository_metadata",
    ],
    "engineer": [
        "system_status", "model_list", "memory_search", "repository_metadata",
    ],
    "reviewer": [
        "system_status", "orchestrator_status", "memory_search",
        "repository_metadata",
    ],
    "tester": ["system_status", "model_list", "repository_metadata"],
    "fullstack_engineer": ["orchestrator_status"],
    "senior_reviewer": ["model_list"],
}


BASE_ROLES = [
    AgentProfile(name="product_manager", display_name="产品经理",
        description="负责需求分析、用户故事编写、PRD 生成。精通 PRD 文档结构和敏捷开发流程。",
        capabilities=["requirements", "documentation", "user_stories"],
        constraints=["no_destructive_ops"], tools=["orchestrator", "context_compressor", *READ_ONLY_ROLE_TOOLS["product_manager"]], priority=8),
    AgentProfile(name="architect", display_name="架构师",
        description="负责系统设计、技术选型、架构图生成。精通 Clean Architecture 和 DDD 设计模式。",
        capabilities=["design", "architecture", "tech_selection"],
        constraints=["no_destructive_ops"], tools=["orchestrator", "project_scanner", *READ_ONLY_ROLE_TOOLS["architect"]], priority=9),
    AgentProfile(name="engineer", display_name="工程师",
        description="负责代码实现、单元测试编写、Bug 修复。精通 Python/TypeScript，遵循 Karpathy 编码准则。",
        capabilities=["coding", "testing", "debugging", "refactoring"],
        constraints=[], tools=["orchestrator", "terminal_executor", "plugin_sdk", *READ_ONLY_ROLE_TOOLS["engineer"]], priority=7),
    AgentProfile(name="reviewer", display_name="审核员",
        description="负责代码审查、安全审计、合规检查。精通 AST 扫描和静态分析。",
        capabilities=["code_review", "security", "compliance"],
        constraints=["no_destructive_ops", "audit_log"], tools=["orchestrator", "security_auditor", *READ_ONLY_ROLE_TOOLS["reviewer"]], priority=6),
    AgentProfile(name="tester", display_name="测试工程师",
        description="负责测试用例设计、自动化测试执行、覆盖率分析。精通 pytest 和 TDD。",
        capabilities=["testing", "tdd", "coverage"],
        constraints=[], tools=["orchestrator", "terminal_executor", *READ_ONLY_ROLE_TOOLS["tester"]], priority=5),
]

EXTENDED_ROLES = [
    AgentProfile(name="fullstack_engineer", display_name="全栈工程师",
        description="负责前后端全链路开发，继承工程师能力并扩展前端和数据库技能。",
        parent_role="engineer",
        capabilities=["frontend", "backend", "database", "api_design", "coding", "testing"],
        constraints=[], tools=["orchestrator", "terminal_executor", "plugin_sdk", "ollama_manager", *READ_ONLY_ROLE_TOOLS["fullstack_engineer"]], priority=8),
    AgentProfile(name="senior_reviewer", display_name="高级审核员",
        description="负责安全审计和架构合规审查，继承审核员能力并扩展渗透测试知识。",
        parent_role="reviewer",
        capabilities=["code_review", "security", "compliance", "penetration_testing", "audit"],
        constraints=["no_destructive_ops", "audit_log"],
        tools=["orchestrator", "security_auditor", "project_scanner", *READ_ONLY_ROLE_TOOLS["senior_reviewer"]], priority=9),
]


def create_default_registry() -> RoleRegistry:
    registry = RoleRegistry()
    for role in BASE_ROLES + EXTENDED_ROLES:
        registry.register(role)
    return registry


def main():
    import sys
    registry = create_default_registry()
    if len(sys.argv) < 2:
        print("Usage: python role_registry.py <command> [args...]")
        print("Commands:")
        print("  list [capability]    List roles (optionally filter by capability)")
        print("  get <role_name>      Show role details")
        print("  register <json_file> Register role from JSON file")
        print("  export               Export all roles as JSON")
        sys.exit(0)
    command = sys.argv[1]
    if command == "list":
        cap = sys.argv[2] if len(sys.argv) >= 3 else None
        roles = registry.list_roles(capability=cap)
        print(f"Total {len(roles)} roles:")
        for r in roles:
            print(f"  [{r.priority}] {r.name} ({r.display_name})")
            print(f"       capabilities: {', '.join(r.capabilities)}")
            if r.parent_role:
                print(f"       inherits from: {r.parent_role}")
    elif command == "get":
        if len(sys.argv) < 3:
            print("Usage: python role_registry.py get <role_name>")
            sys.exit(1)
        profile = registry.get(sys.argv[2])
        if profile:
            print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Role '{sys.argv[2]}' not found")
            sys.exit(1)
    elif command == "register":
        if len(sys.argv) < 3:
            print("Usage: python role_registry.py register <json_file>")
            sys.exit(1)
        data = read_bounded_json(sys.argv[2], label="role JSON input")
        profile = AgentProfile.from_dict(data)
        registry.register(profile)
        print(f"Registered role: {profile.name}")
    elif command == "export":
        print(registry.to_json())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
