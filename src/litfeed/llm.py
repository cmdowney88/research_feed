"""Run headless Claude (`claude -p --bare`) with a JSON schema for structured output.

`--bare` skips CLAUDE.md discovery, auto-memory, hooks, and plugins, so a call depends only on
the system prompt and user message given here. It authenticates with ANTHROPIC_API_KEY.
`--tools ""` disables all tools: the model can only read its input and answer.
"""

import json
import subprocess
from dataclasses import dataclass


class BillingError(RuntimeError):
    """The API key cannot pay for calls (e.g. "Credit balance is too low").

    Raised rather than returned so that batch jobs stop at the first failure instead of
    failing every remaining item.
    """


@dataclass
class ClaudeResult:
    """Outcome of one headless call.

    Attributes:
        output: The structured output matching the schema, or None on failure.
        cost_usd: Reported cost of the call (0.0 if unavailable).
        error: Error text when `output` is None.
    """

    output: dict | None
    cost_usd: float
    error: str = ""


def run_claude(
    system_prompt: str,
    user_message: str,
    schema: dict,
    model: str = "sonnet",
    timeout_seconds: int = 900,
) -> ClaudeResult:
    """Send one message to headless Claude and return its schema-conforming output."""
    command = [
        "claude",
        "-p",
        "--bare",
        "--model",
        model,
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--system-prompt",
        system_prompt,
        "--json-schema",
        json.dumps(schema),
    ]
    try:
        completed = subprocess.run(
            command,
            input=user_message,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ClaudeResult(None, 0.0, f"timed out after {timeout_seconds}s")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ClaudeResult(None, 0.0, completed.stderr[:1000] or completed.stdout[:1000])
    if response.get("is_error") or completed.returncode != 0:
        message = str(response.get("result") or completed.stderr or "unknown error")[:1000]
        if "credit balance" in message.lower():
            raise BillingError(message)
        return ClaudeResult(None, 0.0, message)
    cost = response.get("total_cost_usd") or 0.0
    output = response.get("structured_output")
    if not output:
        return ClaudeResult(None, cost, "no structured output")
    return ClaudeResult(output, cost)
