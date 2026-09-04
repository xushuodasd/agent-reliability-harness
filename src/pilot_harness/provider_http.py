from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, is_dataclass
from typing import Callable, Mapping

from .models import Action, Observation, Task
from .provider import Provider


def _parse_action_content(content: str) -> dict:
    """Extract one JSON action, discarding provider reasoning wrappers."""
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    decoder = json.JSONDecoder()
    for offset, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise json.JSONDecodeError("no complete JSON object", cleaned, 0)


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    status: int = 200
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class CallMetadata:
    operation: str
    latency_ms: int
    request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    json_mode: bool | None


class EpisodeBudgetExceeded(RuntimeError):
    pass


Transport = Callable[[urllib.request.Request, float], bytes | HttpResponse]


def _default_transport(request: urllib.request.Request, timeout: float) -> HttpResponse:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return HttpResponse(response.read(), response.status, dict(response.headers.items()))


def _header(headers: Mapping[str, str] | None, *names: str) -> str | None:
    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    return next((lowered[n.lower()] for n in names if n.lower() in lowered), None)


class OpenAICompatibleProvider(Provider):
    """Chat adapter with observable usage and fail-closed episode budgets."""

    def __init__(self, base_url: str, model: str, *, api_key_env: str = "AGENT_PILOT_API_KEY",
                 scaffold: str = "basic", timeout_seconds: float = 60.0,
                 transport: Transport | None = None, json_mode: str = "auto",
                 max_output_tokens: int = 512, max_episode_tokens: int | None = None,
                 max_episode_cost_usd: float | None = None,
                 input_cost_per_million_usd: float | None = None,
                 output_cost_per_million_usd: float | None = None) -> None:
        self.base_url, self.model, self.api_key_env = base_url.rstrip("/"), model, api_key_env
        if scaffold not in {"basic", "verified"}:
            raise ValueError("scaffold must be basic or verified")
        if json_mode not in {"auto", "required", "disabled"}:
            raise ValueError("json_mode must be auto, required, or disabled")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if max_episode_tokens is not None and max_episode_tokens <= 0:
            raise ValueError("max_episode_tokens must be positive")
        if max_episode_cost_usd is not None and max_episode_cost_usd <= 0:
            raise ValueError("max_episode_cost_usd must be positive")
        for value, label in ((input_cost_per_million_usd, "input_cost_per_million_usd"),
                             (output_cost_per_million_usd, "output_cost_per_million_usd")):
            if value is not None and value < 0:
                raise ValueError(f"{label} cannot be negative")
        if max_episode_cost_usd is not None and (input_cost_per_million_usd is None or output_cost_per_million_usd is None):
            raise ValueError("cost budget requires both input and output pricing")
        self.scaffold, self.timeout_seconds = scaffold, timeout_seconds
        self.json_mode, self.max_output_tokens = json_mode, max_output_tokens
        self.max_episode_tokens, self.max_episode_cost_usd = max_episode_tokens, max_episode_cost_usd
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd
        self._transport = transport or _default_transport
        self._metadata: list[CallMetadata] = []
        self._episode_tokens, self._episode_cost, self._episode_call_start = 0, 0.0, 0

    @property
    def name(self) -> str:
        return f"openai-compatible:{self.model}:{self.scaffold}"

    @property
    def call_metadata(self) -> tuple[CallMetadata, ...]:
        return tuple(self._metadata)

    def begin_episode(self) -> None:
        self._episode_tokens, self._episode_cost = 0, 0.0
        self._episode_call_start = len(self._metadata)

    def episode_usage(self) -> dict:
        current = self._metadata[self._episode_call_start:]
        return {"total_tokens": self._episode_tokens, "cost_usd": round(self._episode_cost, 10),
                "calls": len(current), "requests": [asdict(item) for item in current]}

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"missing API key environment variable: {self.api_key_env}")
        return key

    def _send(self, path: str, *, payload: dict | None, operation: str,
              json_mode: bool | None = None) -> dict:
        api_key = self._key()
        request = urllib.request.Request(f"{self.base_url}/{path.lstrip('/')}",
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="GET" if payload is None else "POST")
        started = time.perf_counter()
        raw = self._transport(request, self.timeout_seconds)
        latency = round((time.perf_counter() - started) * 1000)
        response = raw if isinstance(raw, HttpResponse) else HttpResponse(raw)
        data = json.loads(response.body.decode("utf-8"))
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        prompt, completion, total = (usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"))
        if total is None and isinstance(prompt, int) and isinstance(completion, int):
            total = prompt + completion
        cost = None
        if isinstance(prompt, int) and isinstance(completion, int) and self.input_cost_per_million_usd is not None and self.output_cost_per_million_usd is not None:
            cost = (prompt * self.input_cost_per_million_usd + completion * self.output_cost_per_million_usd) / 1_000_000
        request_id = _header(response.headers, "x-request-id", "request-id", "x-amzn-requestid")
        if request_id and api_key in request_id:
            request_id = "[redacted]"
        self._metadata.append(CallMetadata(operation, latency, request_id,
            prompt if isinstance(prompt, int) else None, completion if isinstance(completion, int) else None,
            total if isinstance(total, int) else None, cost, json_mode))
        metered = operation == "next_action"
        if metered and isinstance(total, int): self._episode_tokens += total
        if metered and cost is not None: self._episode_cost += cost
        if metered and self.max_episode_tokens is not None:
            if total is None: raise EpisodeBudgetExceeded("provider omitted usage; token budget cannot be enforced")
            if self._episode_tokens > self.max_episode_tokens: raise EpisodeBudgetExceeded("episode token budget exceeded")
        if metered and self.max_episode_cost_usd is not None:
            if cost is None: raise EpisodeBudgetExceeded("pricing or usage missing; cost budget cannot be enforced")
            if self._episode_cost > self.max_episode_cost_usd: raise EpisodeBudgetExceeded("episode cost budget exceeded")
        return data

    def preflight(self, probe: str = "models") -> dict:
        if probe not in {"models", "chat"}: raise ValueError("probe must be models or chat")
        if probe == "models":
            data = self._send("models", payload=None, operation="preflight_models")
            ids = [x.get("id") for x in data.get("data", []) if isinstance(x, dict)]
            visible = self.model in ids
        else:
            self._send("chat/completions", payload={"model": self.model,
                "messages": [{"role": "user", "content": "Reply OK."}], "temperature": 0,
                "max_tokens": 2}, operation="preflight_chat", json_mode=False)
            visible = None
        last = self._metadata[-1]
        return {"ok": True, "probe": probe, "model_visible": visible,
                "request_id": last.request_id, "latency_ms": last.latency_ms}

    def next_action(self, task: Task, history: list[tuple[Action, Observation]]) -> Action:
        instruction = ("Complete the task using the fewest valid tool actions." if self.scaffold == "basic" else
            "After any write, independently read the target state before finishing. If an error or mismatch occurs, inspect state and retry only when safe.")
        allowed = tuple(getattr(task, "allowed_actions", ("write_file", "read_file")))
        task_data = asdict(task) if is_dataclass(task) else {"task_id": task.task_id,
            "instruction": task.instruction, "allowed_actions": list(allowed), "max_steps": task.max_steps}
        example_kind = allowed[0] if allowed else "finish"
        messages = [{"role": "system", "content": "Return exactly one JSON object and no markdown. "
            f"Allowed action kinds: {', '.join(allowed)}, finish. "
            f'Put the literal selected action name in kind, for example {{"kind":"{example_kind}","arguments":{{}}}}. '
            + instruction},
            {"role": "user", "content": json.dumps({"task": task_data, "scaffold": self.scaffold,
             "history": [(asdict(a), asdict(o)) for a, o in history]}, ensure_ascii=False)}]
        payload = {"model": self.model, "messages": messages, "temperature": 0,
                   "max_tokens": self.max_output_tokens}
        use_json = self.json_mode != "disabled"
        if use_json: payload["response_format"] = {"type": "json_object"}
        try:
            response = self._send("chat/completions", payload=payload, operation="next_action", json_mode=use_json)
        except urllib.error.HTTPError as exc:
            compatible = self.json_mode == "auto" and exc.code in {400, 404, 422}
            exc.close()
            if not compatible: raise
            payload.pop("response_format", None)
            response = self._send("chat/completions", payload=payload, operation="next_action", json_mode=False)
        try:
            item = _parse_action_content(response["choices"][0]["message"]["content"])
            action = Action(str(item["kind"]), dict(item.get("arguments", {})))
        except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"invalid provider response: {type(exc).__name__}") from exc
        if action.kind not in set(allowed) | {"finish"}:
            safe_kind = re.sub(r"[^A-Za-z0-9_.-]", "?", action.kind)[:64]
            safe_keys = ",".join(sorted(re.sub(r"[^A-Za-z0-9_.-]", "?", str(k))[:32] for k in item))
            safe_arg_keys = ",".join(sorted(re.sub(r"[^A-Za-z0-9_.-]", "?", str(k))[:32] for k in action.arguments))
            raise RuntimeError(
                f"provider returned a disallowed action: {safe_kind}; keys={safe_keys}; argument_keys={safe_arg_keys}"
            )
        return action
