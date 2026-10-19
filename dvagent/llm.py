"""LLM access through any OpenAI-compatible chat-completions endpoint.

Works with Gemini (AI Studio), Groq, OpenRouter, OpenAI, Anthropic and a local
Ollama server, using only the Python standard library. Also provides offline
providers for tests: ``replay`` (recorded transcript), ``script`` (callable)
and ``files`` (a human or another program answers prompts written to disk).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-3.8-flash",
        "rpm": 8,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
        "rpm": 20,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": None,
        "rpm": 15,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "model": None,
        "rpm": 60,
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
        "model": "claude-sonnet-5-5",
        "rpm": 30,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": None,
        "model": "qwen2.5-coder:14b",
        "rpm": 0,
    },
}


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    """The provider's (daily) quota is used up: stop now and resume later."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    def add(self, other: "Usage"):
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.seconds += other.seconds

    def to_dict(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "seconds": round(self.seconds, 1)}


@dataclass
class Reply:
    text: str
    usage: Usage


@dataclass
class LLM:
    """Chat client. ``complete(messages, tag)`` returns a Reply and logs the exchange."""

    provider: str = "gemini"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    rpm: float | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    timeout: float = 300.0
    transcript: Path | None = None
    usage: Usage = field(default_factory=Usage)
    _last_call: float = 0.0
    _backend: Callable | None = None

    def __post_init__(self):
        if self.provider in PROVIDERS:
            p = PROVIDERS[self.provider]
            self.base_url = (self.base_url or p["base_url"]).rstrip("/")
            self.model = self.model or os.environ.get("DVAGENT_MODEL") or p["model"]
            if self.api_key is None and p["key_env"]:
                self.api_key = os.environ.get(p["key_env"]) or os.environ.get("DVAGENT_API_KEY")
                if not self.api_key:
                    raise LLMError(f"Set the {p['key_env']} environment variable (your {self.provider} API key).")
            if self.rpm is None:
                self.rpm = p["rpm"]
            if not self.model:
                raise LLMError(f"Choose a model for provider '{self.provider}' with --model "
                               f"(run `dvagent models --provider {self.provider}` to list them).")
        elif self.provider == "custom":
            if not self.base_url:
                raise LLMError("provider 'custom' needs --base-url")
            self.api_key = self.api_key or os.environ.get("DVAGENT_API_KEY", "")
        elif self._backend is None:
            raise LLMError(f"unknown provider '{self.provider}'")

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        if self.provider == "anthropic":
            req.add_header("x-api-key", self.api_key or "")
            req.add_header("anthropic-version", "2023-06-01")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def list_models(self) -> list[str]:
        data = self._request("GET", "models")
        ids = [m.get("id", "") for m in data.get("data", [])]
        return sorted(i.removeprefix("models/") for i in ids if i)

    def _throttle(self):
        if self.rpm:
            gap = 60.0 / self.rpm
            wait = self._last_call + gap - time.time()
            if wait > 0:
                time.sleep(wait)
        self._last_call = time.time()

    def _call_api(self, messages: list[dict]) -> tuple[str, Usage]:
        body: dict = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        delay = 10.0
        last_err = ""
        for attempt in range(8):
            self._throttle()
            t0 = time.time()
            try:
                data = self._request("POST", "chat/completions", body)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:1500]
                last_err = f"HTTP {e.code}: {detail}"
                if e.code == 429 and re.search(r"per ?day|PerDay|daily|quota exceeded for metric.*day", detail, re.I):
                    raise QuotaExhausted(last_err) from None
                if e.code in (429, 500, 502, 503, 504, 529):
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    m = re.search(r'"retryDelay":\s*"(\d+)', detail)
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else (
                        float(m.group(1)) + 1 if m else delay)
                    time.sleep(min(wait, 120))
                    delay = min(delay * 2, 120)
                    continue
                if e.code == 404 and "model" in detail.lower():
                    raise LLMError(f"Model '{self.model}' not found at {self.base_url}. "
                                   f"Run `dvagent models` to list available models. ({detail[:300]})") from None
                raise LLMError(last_err) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            if isinstance(text, list):   # some providers return content parts
                text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
            if not text.strip():
                last_err = f"empty response (finish_reason={choice.get('finish_reason')})"
                time.sleep(delay)
                continue
            u = data.get("usage") or {}
            return text, Usage(1, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0),
                               time.time() - t0)
        raise LLMError(f"LLM request failed after retries: {last_err}")

    # ---------------------------------------------------------------- public
    def complete(self, messages: list[dict], tag: str = "") -> Reply:
        t0 = time.time()
        if self._backend is not None:
            text = self._backend(messages, tag)
            usage = Usage(1, sum(len(m["content"]) for m in messages) // 4, len(text) // 4, time.time() - t0)
        else:
            text, usage = self._call_api(messages)
        self.usage.add(usage)
        if self.transcript is not None:
            self.transcript.parent.mkdir(parents=True, exist_ok=True)
            with open(self.transcript, "a") as f:
                f.write(json.dumps({"tag": tag, "model": self.model, "messages": messages, "response": text,
                                    "usage": usage.to_dict(), "time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        return Reply(text, usage)


# ---------------------------------------------------------------- offline providers
def replay_backend(path: str | Path) -> Callable:
    """Return recorded responses in order (for deterministic tests and demos)."""
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    state = {"i": 0}

    def backend(messages, tag):
        if state["i"] >= len(records):
            raise LLMError("replay transcript exhausted")
        rec = records[state["i"]]
        state["i"] += 1
        return rec["response"]

    return backend


def files_backend(directory: str | Path, poll: float = 2.0, timeout: float = 3600) -> Callable:
    """Write each prompt to <dir>/NNN_prompt.md and wait for <dir>/NNN_response.md."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    state = {"i": len(list(d.glob("*_prompt.md")))}

    def backend(messages, tag):
        n = state["i"]
        state["i"] += 1
        prompt = "\n\n".join(f"## {m['role'].upper()}\n\n{m['content']}" for m in messages)
        (d / f"{n:03d}_prompt.md").write_text(f"<!-- tag: {tag} -->\n{prompt}")
        resp = d / f"{n:03d}_response.md"
        t0 = time.time()
        while not resp.exists():
            if time.time() - t0 > timeout:
                raise LLMError(f"no answer in {resp}")
            time.sleep(poll)
        time.sleep(0.5)
        return resp.read_text()

    return backend


def make_llm(provider: str, model: str | None = None, transcript: Path | None = None, **kw) -> LLM:
    if provider == "replay":
        return LLM(provider="replay", model="replay", transcript=transcript,
                   _backend=replay_backend(kw.pop("replay_file")))
    if provider == "files":
        return LLM(provider="files", model=model or "files", transcript=transcript,
                   _backend=files_backend(kw.pop("files_dir")))
    return LLM(provider=provider, model=model, transcript=transcript, **kw)
