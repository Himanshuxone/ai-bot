"""Claude integration test with a mocked SDK client (no network)."""

from __future__ import annotations

from types import SimpleNamespace

from finrag.config import LLMProvider, Settings
from finrag.generation.llm import AnthropicLLM
from finrag.generation.prompts import SYSTEM_PROMPT, PromptSource


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _llm(monkeypatch, response):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = AnthropicLLM(Settings(llm_provider=LLMProvider.ANTHROPIC))
    fake = _FakeMessages(response)
    llm._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return llm, fake


def _response(stop_reason="end_turn", text="Revenue was 1,452,000 [S1]."):
    return SimpleNamespace(
        stop_reason=stop_reason, model="claude-opus-5-5",
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_request_shape_and_text(monkeypatch):
    llm, fake = _llm(monkeypatch, _response())
    result = llm.generate("revenue?", [PromptSource("S1", "f.csv", "table", "Revenue 1,452,000")])
    assert result.text == "Revenue was 1,452,000 [S1]." and not result.refused
    kw = fake.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"] == SYSTEM_PROMPT
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["fallbacks"] == "default"
    assert "tools" not in kw  # [RULE: OWASP-LLM06]
    assert '<source id="S1"' in kw["messages"][0]["content"]


def test_refusal_handled(monkeypatch):
    llm, _ = _llm(monkeypatch, _response(stop_reason="refusal", text=""))
    assert llm.generate("q", []).refused
