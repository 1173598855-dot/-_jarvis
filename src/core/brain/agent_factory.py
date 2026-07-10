"""
Agent factory - Phase 11 integration layer
Connects RoleRegistry + Orchestrator for role-driven task dispatch
Zero external dependencies (stdlib only)
"""
import logging
import threading
from typing import Any, Dict, List, Optional

from core.brain.orchestrator import AgentTask, Orchestrator
from core.brain.role_registry import AgentProfile, create_default_registry

logger = logging.getLogger(__name__)


class DispatchResult:
    def __init__(self, role_name: str, task_id: str, status: str, message: str = ""):
        self.role_name = role_name
        self.task_id = task_id
        self.status = status
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {"role_name": self.role_name, "task_id": self.task_id,
                "status": self.status, "message": self.message}


NL = "\n"  # avoid f-string newline truncation


class AgentFactory:
    """Role-driven agent factory connecting RoleRegistry + Orchestrator"""

    def __init__(self, registry=None, orchestrator=None, ollama_manager=None):
        self.registry = registry if registry is not None else create_default_registry()
        self.orchestrator = orchestrator or Orchestrator()
        self._ollama_manager = ollama_manager
        self._lock = threading.Lock()

    def dispatch_by_role(self, role_name: str, task_prompt: str, timeout: int = 300) -> DispatchResult:
        profile = self.registry.get(role_name)
        if profile is None:
            return DispatchResult(role_name, "", "no_role", f"Role '{role_name}' not found")

        if profile.name not in self.orchestrator._agents:
            self.orchestrator.register(
                profile.name,
                handler=self._default_handler(profile),
                capabilities=profile.capabilities,
            )

        system_prompt = profile.resolve_prompt(task_prompt)
        full_prompt = self._build_full_prompt(profile, task_prompt, system_prompt)

        task = AgentTask(
            task_id=f"{role_name}_{abs(hash(task_prompt)) % 100000}",
            agent_name=profile.name,
            prompt=full_prompt,
            timeout=timeout,
            priority=profile.priority,
            metadata={"role_name": role_name, "capabilities": profile.capabilities,
                      "constraints": profile.constraints, "tools": profile.tools},
        )
        result = self.orchestrator.dispatch(task)
        status = "dispatched" if result.status == "completed" else result.status
        return DispatchResult(
            role_name=role_name, task_id=result.task_id,
            status=status, message=result.result or result.error or "",
        )

    @staticmethod
    def _default_handler(profile: AgentProfile):
        def handler(task: AgentTask) -> str:
            return f"[{profile.display_name}] Task received: {task.prompt[:100]}"
        return handler

    def dispatch_by_capability(self, capability: str, task_prompt: str, timeout: int = 300) -> DispatchResult:
        candidates = self.registry.list_roles(capability=capability)
        if not candidates:
            return DispatchResult("", "", "no_capability", f"No role with capability '{capability}'")
        best = candidates[0]
        return self.dispatch_by_role(best.name, task_prompt, timeout)

    def dispatch_llm(self, task_prompt: str, timeout: int = 300) -> DispatchResult:
        """Route task to best role using LLM semantic matching.

        Falls back to dispatch_by_capability if no ollama_manager is set
        or if the LLM call fails.
        """
        if self._ollama_manager is None:
            logger.warning("dispatch_llm: no ollama_manager, falling back to first capability match")
            return self._fallback_dispatch(task_prompt, timeout)

        roles = self.registry.list_roles()
        if not roles:
            return DispatchResult("", "", "no_roles", "No roles registered")

        role_descriptions = (
            "\n".join(
                f"- {r.name} ({r.display_name}): capabilities={r.capabilities}, "
                f"priority={r.priority}"
                for r in roles
            )
        )
        prompt = (
            f"Given the following task:\n{task_prompt}\n\n"
            f"Available roles:\n{role_descriptions}\n\n"
            f"Which role is best suited for this task? Reply with ONLY the role name."
        )
        try:
            response = self._ollama_manager.chat(
                prompt, model="llama3.2", max_tokens=32, temperature=0.0
            )
        except Exception as exc:
            logger.warning(f"dispatch_llm: LLM call failed ({exc}), falling back")
            return self._fallback_dispatch(task_prompt, timeout)

        candidate = response.strip().split()[0].strip("[]").lower()
        for role in roles:
            if role.name.lower() == candidate:
                return self.dispatch_by_role(role.name, task_prompt, timeout)
        # No exact match, try partial
        for role in roles:
            if candidate in role.name.lower() or role.name.lower() in candidate:
                return self.dispatch_by_role(role.name, task_prompt, timeout)
        return self._fallback_dispatch(task_prompt, timeout)

    def _fallback_dispatch(self, task_prompt: str, timeout: int = 300) -> DispatchResult:
        """Fallback: dispatch to role matching first capability keyword in prompt."""
        roles = self.registry.list_roles()
        if not roles:
            return DispatchResult("", "", "no_roles", "No roles registered")
        words = set(task_prompt.lower().split())
        for role in roles:
            role_words = set(" ".join(role.capabilities).lower().split())
            overlap = words & role_words
            if overlap:
                return self.dispatch_by_role(role.name, task_prompt, timeout)
        return self.dispatch_by_role(roles[0].name, task_prompt, timeout)

    def batch_dispatch(self, tasks: List[Dict[str, Any]]) -> List[DispatchResult]:
        results = []
        for t in tasks:
            role = t.get("role", "")
            prompt = t.get("prompt", "")
            timeout = t.get("timeout", 300)
            if role:
                results.append(self.dispatch_by_role(role, prompt, timeout))
            else:
                cap = t.get("capability", "")
                results.append(self.dispatch_by_capability(cap, prompt, timeout))
        return results

    def list_roles(self, capability=None) -> List[AgentProfile]:
        return self.registry.list_roles(capability=capability)

    def get_role(self, name: str) -> Optional[AgentProfile]:
        return self.registry.get(name)

    def _build_full_prompt(self, profile: AgentProfile, task: str, system_prompt: str) -> str:
        parts = [f"[ROLE: {profile.display_name}]", system_prompt]
        if profile.constraints:
            parts.append(f"[CONSTRAINTS] {chr(59).join(profile.constraints)}")
        if profile.tools:
            parts.append(f"[AVAILABLE TOOLS] {chr(44).join(profile.tools)}")
        sep = "\n\n"
        return sep.join(parts + [f"[TASK]{NL}{task}"])

    def shutdown(self):
        self.orchestrator.shutdown()


def main():
    import sys
    factory = AgentFactory()
    if len(sys.argv) < 2:
        print("Usage: python agent_factory.py <command> [args...]")
        print("Commands: list, get, dispatch, dispatch_cap, batch")
        sys.exit(0)
    command = sys.argv[1]
    if command == "list":
        cap = sys.argv[2] if len(sys.argv) >= 3 else None
        roles = factory.list_roles(capability=cap)
        print(f"Available roles ({len(roles)}):")
        for r in roles:
            print(f"  [{r.priority}] {r.name} ({r.display_name}) - {chr(44).join(r.capabilities)}")
    elif command == "get":
        if len(sys.argv) < 3:
            print("Usage: python agent_factory.py get <role_name>")
        sys.exit(1)
        profile = factory.get_role(sys.argv[2])
        if profile:
            import json
            print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
        else:
            print("Role not found")
        sys.exit(1)
    elif command == "dispatch":
        if len(sys.argv) < 4:
            print("Usage: python agent_factory.py dispatch <role> <task>")
        sys.exit(1)
        result = factory.dispatch_by_role(sys.argv[2], " ".join(sys.argv[3:]))
        print(f"Dispatched: role={result.role_name}, status={result.status}")
    elif command == "dispatch_cap":
        if len(sys.argv) < 4:
            print("Usage: python agent_factory.py dispatch_cap <cap> <task>")
        sys.exit(1)
        result = factory.dispatch_by_capability(sys.argv[2], " ".join(sys.argv[3:]))
        print(f"Dispatched: role={result.role_name}, status={result.status}")
    elif command == "batch":
        if len(sys.argv) < 3:
            print("Usage: python agent_factory.py batch <json_file>")
        sys.exit(1)
        import json
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            tasks = json.load(f)
        results = factory.batch_dispatch(tasks)
        for r in results:
            print(f"  [{r.status}] {r.role_name}: {r.task_id}")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
    factory.shutdown()


if __name__ == "__main__":
    main()
