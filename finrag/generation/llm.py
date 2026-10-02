"""
Answer generators.

``AnthropicLLM``  - Claude via the official ``anthropic`` SDK.
``OfflineLLM``    - deterministic extractive answerer; no network, no
                    third-party processing. Default provider, also used in tests.

Both implement ``generate(question, sources) -> LLMResult``.

[RULE: GDPR-ART44]   Only pseudonymised, minimised context (top-k chunks) is
                     ever sent to the external provider; raw files never are.
[RULE: GDPR-ART25]   Offline provider is the default.
[RULE: OWASP-LLM06]  No tools / function calling are offered to the model.
[RULE: OWASP-LLM10]  ``max_tokens`` cap and SDK timeouts/retries bound cost.
[RULE: EUAIA-ART15]  Provider errors and refusals are handled explicitly and
                     fail closed (no partial / unvalidated answer is returned).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from finrag.config import LLMProvider, Settings
from finrag.generation.prompts import SYSTEM_PROMPT, PromptSource, build_user_message
from finrag.retrieval.index import tokenize

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """The provider could not produce an answer (network, quota, refusal...)."""


@dataclass
class LLMResult:
    """Normalised generation result."""

    text: str
    model: str
    refused: bool = False
    truncated: bool = False
    usage: dict[str, int] = field(default_factory=dict)


class AnswerGenerator(Protocol):
    """Interface implemented by every answer generator."""

    model_name: str

    def generate(self, question: str, sources: list[PromptSource]) -> LLMResult:
        """Produce an answer grounded in ``sources``."""
        ...


class AnthropicLLM:
    """Claude-backed generator using the Messages API."""

    def __init__(self, settings: Settings) -> None:
        import anthropic  # imported lazily so offline installs need no SDK

        self._anthropic = anthropic
        # [RULE: SEC-SECRETS] Credentials are resolved by the SDK from the
        # environment (ANTHROPIC_API_KEY or an `ant auth login` profile); they
        # are never passed through FinRAG settings or logged.
        self._client = anthropic.Anthropic(max_retries=3, timeout=180.0)
        self.model_name = settings.anthropic_model
        self._effort = settings.anthropic_effort
        self._max_tokens = settings.max_output_tokens

    def generate(self, question: str, sources: list[PromptSource]) -> LLMResult:
        """Call Claude with fenced sources; handle refusals and API errors."""
        anthropic = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model_name,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(question, sources)}],
                # Adaptive thinking lets the model reason about multi-step
                # calculations (growth rates, margins) before answering.
                thinking={"type": "adaptive"},
                output_config={"effort": self._effort},
                # If a safety classifier declines, the API re-runs the request
                # on Anthropic's recommended fallback model server-side.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("LLM rate limit reached, retry later") from exc
        except anthropic.APIStatusError as exc:
            # Log only status code - never request bodies (they hold user data).
            logger.error("LLM API error status=%s", exc.status_code)
            raise LLMUnavailableError("LLM provider returned an error") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError("LLM provider unreachable") from exc

        usage = {"input_tokens": response.usage.input_tokens,
                 "output_tokens": response.usage.output_tokens}
        # Always check stop_reason before reading content.
        if response.stop_reason == "refusal":
            return LLMResult(text="", model=response.model, refused=True, usage=usage)
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResult(text=text.strip(), model=response.model,
                         truncated=response.stop_reason == "max_tokens", usage=usage)


class OfflineLLM:
    """Extractive answerer: returns the most relevant source lines with citations.

    Useful for air-gapped deployments, CI, and as a privacy-preserving default.
    It never fabricates numbers because it only copies text from sources.
    """

    model_name = "finrag-offline-extractive-v1"

    def generate(self, question: str, sources: list[PromptSource]) -> LLMResult:
        """Select up to four best-matching lines across the sources."""
        if not sources:
            return LLMResult(text="The documents do not contain enough information to answer "
                                  "this question.", model=self.model_name)
        q_tokens = set(tokenize(question))
        # (token overlap, original order, line, label); earlier = more relevant source.
        scored: list[tuple[int, int, str, str]] = []
        for src in sources:
            for line in re.split(r"\n+|(?<=[.!?])\s+", src.text):
                line = line.strip()
                if len(line) < 3 or line.startswith("Columns:"):
                    continue
                overlap = len(q_tokens & set(tokenize(line)))
                if overlap:
                    scored.append((overlap, -len(scored), line, src.label))
        if not scored:
            return LLMResult(text="The documents do not contain enough information to answer "
                                  "this question.", model=self.model_name)
        scored.sort(reverse=True)
        lines = [f"- {line} [{label}]" for _, _, line, label in scored[:4]]
        text = "Most relevant information found in the documents:\n" + "\n".join(lines)
        return LLMResult(text=text, model=self.model_name)


def build_generator(settings: Settings) -> AnswerGenerator:
    """Factory selecting the configured provider."""
    if settings.llm_provider is LLMProvider.ANTHROPIC:
        return AnthropicLLM(settings)
    return OfflineLLM()
