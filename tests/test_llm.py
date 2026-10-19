"""The HTTP client against a local fake OpenAI-compatible server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dvagent.llm import LLM, LLMError, QuotaExhausted


class Fake(BaseHTTPRequestHandler):
    script: list = []
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"data": [{"id": "models/gemini-x-flash"}, {"id": "other-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append((self.path, self.headers.get("Authorization"), body))
        code, payload = Fake.script.pop(0)
        self._send(code, payload, {"Retry-After": "0"} if code == 429 else None)


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    Fake.seen = []
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def ok(text):
    return 200, {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_complete_and_usage(server, tmp_path):
    Fake.script = [ok("hello")]
    llm = LLM(provider="custom", base_url=server, api_key="k", model="m", transcript=tmp_path / "t.jsonl")
    r = llm.complete([{"role": "user", "content": "hi"}], tag="x")
    assert r.text == "hello"
    path, auth, body = Fake.seen[0]
    assert path == "/v1/chat/completions" and auth == "Bearer k" and body["model"] == "m"
    assert llm.usage.prompt_tokens == 11 and llm.usage.completion_tokens == 7
    assert json.loads((tmp_path / "t.jsonl").read_text())["response"] == "hello"


def test_retries_rate_limit_then_succeeds(server, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    Fake.script = [(429, {"error": {"message": "slow down"}}), (503, {"error": "busy"}), ok("fine")]
    llm = LLM(provider="custom", base_url=server, api_key="k", model="m")
    assert llm.complete([{"role": "user", "content": "hi"}]).text == "fine"
    assert len(Fake.seen) == 3


def test_daily_quota_raises(server, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    Fake.script = [(429, {"error": {"message": "Quota exceeded for metric: generate_content_free_tier_requests, "
                                               "limit: 250, quota_id: GenerateRequestsPerDayPerProjectPerModel"}})]
    llm = LLM(provider="custom", base_url=server, api_key="k", model="m")
    with pytest.raises(QuotaExhausted):
        llm.complete([{"role": "user", "content": "hi"}])


def test_bad_request_is_an_error(server):
    Fake.script = [(400, {"error": "bad"})]
    llm = LLM(provider="custom", base_url=server, api_key="k", model="m")
    with pytest.raises(LLMError):
        llm.complete([{"role": "user", "content": "hi"}])


def test_list_models(server):
    llm = LLM(provider="custom", base_url=server, api_key="k", model="m")
    assert llm.list_models() == ["gemini-x-flash", "other-model"]


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DVAGENT_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        LLM(provider="gemini")
