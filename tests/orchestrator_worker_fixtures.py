import os
import time


def project_task(task):
    return {
        "pid": os.getpid(),
        "task_id": task.task_id,
        "agent_name": task.agent_name,
        "prompt": task.prompt,
        "priority": task.priority,
        "metadata": dict(task.metadata),
    }


def delayed_task(task):
    time.sleep(float(task.metadata.get("delay", 0)))
    return project_task(task)


def result_task(task):
    from core.brain.orchestrator import AgentResult

    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        result="wrapped",
        status="success",
    )


def blocking_task(task):
    time.sleep(float(task.metadata.get("delay", 30)))
    return project_task(task)
