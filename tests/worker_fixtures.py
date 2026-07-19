import os
import time


def succeed(request, config):
    return {
        "role_name": request["role_name"],
        "prompt": request["prompt"],
        "marker": config.get("marker", "ok"),
    }


def fail(_request, _config):
    raise RuntimeError("fixture runner failed")


def sleep_then_succeed(request, config):
    time.sleep(float(config.get("delay", 2)))
    return {"prompt": request["prompt"]}


def crash(_request, _config):
    os._exit(17)


def oversized(_request, config):
    return "x" * int(config.get("size", 2 * 1024 * 1024))
