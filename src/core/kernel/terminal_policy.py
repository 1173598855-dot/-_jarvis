"""Fixed, read-only terminal operations exposed through the HTTP API."""

from __future__ import annotations

MAX_ARGUMENTS = 16
MAX_ARGUMENT_LENGTH = 256
MAX_TIMEOUT_SECONDS = 30
_OPERATION_ARGUMENT_LIMITS = {
    "echo": MAX_ARGUMENTS,
    "pwd": 0,
    "whoami": 0,
    "hostname": 0,
    "date": 0,
}


class TerminalPolicyError(ValueError):
    """Raised when a terminal request is outside the HTTP capability contract."""


def validate_terminal_operation(command, args, timeout) -> tuple[str, list[str], int]:
    """Validate a fixed operation and bounded arguments before creating a process."""
    if not isinstance(command, str) or command not in _OPERATION_ARGUMENT_LIMITS:
        raise TerminalPolicyError("Command is not available through the terminal API")
    if not isinstance(args, list) or len(args) > _OPERATION_ARGUMENT_LIMITS[command]:
        raise TerminalPolicyError("Command arguments are not permitted")
    if any(
        not isinstance(argument, str)
        or not argument
        or len(argument) > MAX_ARGUMENT_LENGTH
        or "\x00" in argument
        for argument in args
    ):
        raise TerminalPolicyError("Command arguments are invalid")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise TerminalPolicyError("Timeout must be an integer between 1 and 30 seconds")
    return command, args, timeout
