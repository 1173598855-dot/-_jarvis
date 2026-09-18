"""
Agent factory - Phase 11 integration layer
Connects RoleRegistry + Orchestrator for role-driven task dispatch
Zero external dependencies (stdlib only)
"""
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.brain.orchestrator import AgentTask, Orchestrator
from core.brain.role_registry import AgentProfile, create_default_registry
from core.brain.role_tool_loop import RoleToolLoop
from core.brain.role_tools import RoleToolBroker
from core.contracts.bounded_json import read_bounded_json

logger = logging.getLogger(__name__)

DEFAULT_ROLE_MODEL = "llama3.2"
ROLE_EXECUTION_ERROR = "Ollama role execution failed"


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

    def __init__(
        self,
        registry=None,
        orchestrator=None,
        ollama_manager=None,
        role_model: Optional[str] = None,
        role_tool_broker: Optional[RoleToolBroker] = None,
    ):
        self.registry = registry if registry is not None else create_default_registry()
        self.orchestrator = orchestrator or Orchestrator()
        self._ollama_manager = ollama_manager
        configured_model = role_model or os.environ.get(
            "JARVIS_ROLE_MODEL", DEFAULT_ROLE_MODEL
        )
        self._role_model = configured_model.strip() or DEFAULT_ROLE_MODEL
        self._role_tool_broker = role_tool_broker or RoleToolBroker()
        self._lock = threading.Lock()

    def _build_role_task(
        self,
        profile: AgentProfile,
        task_prompt: str,
        *,
        task_id: str,
        timeout: int,
    ) -> AgentTask:
        authorized_tools = [
            definition.name
            for definition in self._role_tool_broker.authorized_definitions(profile)
        ]
        system_prompt = profile.resolve_prompt(task_prompt)
        full_prompt = self._build_full_prompt(
            profile,
            task_prompt,
            system_prompt,
            authorized_tools=authorized_tools,
        )
        return AgentTask(
            task_id=task_id,
            agent_name=profile.name,
            prompt=full_prompt,
            timeout=timeout,
            priority=profile.priority,
            metadata={
                "role_name": profile.name,
                "capabilities": profile.capabilities,
                "constraints": profile.constraints,
                "declared_tools": list(profile.tools),
                "authorized_tools": authorized_tools,
                "task_prompt": task_prompt,
            },
        )

    def execute_role_once(
        self,
        role_name: str,
        task_prompt: str,
        *,
        task_id: str,
        timeout: int = 300,
    ) -> DispatchResult:
        profile = self.registry.get(role_name)
        if profile is None:
            return DispatchResult(
                role_name,
                task_id,
                "no_role",
                f"Role '{role_name}' not found",
            )
        task = self._build_role_task(
            profile,
            task_prompt,
            task_id=task_id,
            timeout=timeout,
        )
        try:
            output = self._default_handler(
                profile,
                allow_model_tools=True,
            )(task)
        except Exception:
            logger.warning("Direct role execution failed for role %s", profile.name)
            return DispatchResult(role_name, task_id, "error", ROLE_EXECUTION_ERROR)
        return DispatchResult(role_name, task_id, "success", output)

    def dispatch_by_role(self, role_name: str, task_prompt: str, timeout: int = 300) -> DispatchResult:
        profile = self.registry.get(role_name)
        if profile is None:
            return DispatchResult(role_name, "", "no_role", f"Role '{role_name}' not found")

        if profile.name not in self.orchestrator._agents:
            self.orchestrator.register_in_process(
                profile.name,
                handler=self._default_handler(profile),
                capabilities=profile.capabilities,
            )

        task = self._build_role_task(
            profile,
            task_prompt,
            task_id=f"{role_name}_{abs(hash(task_prompt)) % 100000}",
            timeout=timeout,
        )
        result = self.orchestrator.dispatch(task)
        if result.status == "error":
            self.orchestrator.recover_agent(profile.name)
        status = "dispatched" if result.status == "completed" else result.status
        return DispatchResult(
            role_name=role_name, task_id=result.task_id,
            status=status, message=result.result or result.error or "",
        )

    def _default_handler(
        self,
        profile: AgentProfile,
        *,
        allow_model_tools: bool = False,
    ):
        if self._ollama_manager is None:
            def compatibility_handler(task: AgentTask) -> str:
                return f"[{profile.display_name}] Task received: {task.prompt[:100]}"

            return compatibility_handler

        def ollama_handler(task: AgentTask) -> str:
            authorized_tools = [
                name
                for name in task.metadata.get("authorized_tools", [])
                if isinstance(name, str) and name
            ] if allow_model_tools else []
            messages = [
                {
                    "role": "system",
                    "content": self._build_system_prompt(
                        profile,
                        authorized_tools=authorized_tools,
                    ),
                },
                {
                    "role": "user",
                    "content": str(task.metadata.get("task_prompt", "")),
                },
            ]
            try:
                if allow_model_tools:
                    return RoleToolLoop(
                        self._ollama_manager,
                        self._role_tool_broker,
                    ).run(
                        model=self._role_model,
                        messages=messages,
                        profile=profile,
                        timeout_seconds=task.timeout,
                    )
                response = self._ollama_manager.chat(
                    self._role_model,
                    messages,
                    stream=False,
                )
            except Exception:
                logger.warning(
                    "Ollama role execution raised for role %s",
                    profile.name,
                )
                raise RuntimeError(ROLE_EXECUTION_ERROR) from None

            if not isinstance(response, dict) or response.get("error"):
                raise RuntimeError(ROLE_EXECUTION_ERROR)
            message = response.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(ROLE_EXECUTION_ERROR)
            return content.strip()

        return ollama_handler

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
                self._role_model,
                [{"role": "user", "content": prompt}],
                stream=False,
            )
        except Exception as exc:
            logger.warning(f"dispatch_llm: LLM call failed ({exc}), falling back")
            return self._fallback_dispatch(task_prompt, timeout)

        message = response.get("message") if isinstance(response, dict) else None
        content = message.get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            return self._fallback_dispatch(task_prompt, timeout)
        candidate = content.strip().split()[0].strip("[]").lower()
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

    def _build_full_prompt(
        self,
        profile: AgentProfile,
        task: str,
        system_prompt: str,
        authorized_tools: Optional[List[str]] = None,
    ) -> str:
        parts = [f"[ROLE: {profile.display_name}]", system_prompt]
        if profile.constraints:
            parts.append(f"[CONSTRAINTS] {chr(59).join(profile.constraints)}")
        self._append_tool_access(parts, profile, authorized_tools)
        sep = "\n\n"
        return sep.join(parts + [f"[TASK]{NL}{task}"])

    def _build_system_prompt(
        self,
        profile: AgentProfile,
        authorized_tools: Optional[List[str]] = None,
    ) -> str:
        parts = [
            f"[ROLE: {profile.display_name}]",
            profile.resolve_prompt("Follow the user message."),
        ]
        if profile.constraints:
            parts.append(f"[CONSTRAINTS] {chr(59).join(profile.constraints)}")
        self._append_tool_access(parts, profile, authorized_tools)
        return "\n\n".join(parts)

    def _append_tool_access(
        self,
        parts: List[str],
        profile: AgentProfile,
        authorized_tools: Optional[List[str]],
    ) -> None:
        resolved = (
            self._role_tool_broker.authorized_tools(profile)
            if authorized_tools is None
            else authorized_tools
        )
        if resolved:
            parts.append(f"[AUTHORIZED TOOLS] {chr(44).join(resolved)}")
        else:
            parts.append("[TOOL ACCESS] disabled")

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
        tasks = read_bounded_json(sys.argv[2], label="batch JSON input")
        results = factory.batch_dispatch(tasks)
        for r in results:
            print(f"  [{r.status}] {r.role_name}: {r.task_id}")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
    factory.shutdown()


if __name__ == "__main__":
    main()
