"""LLM provider abstraction.

Every AI call in the app (field extraction, type classification, the Settings
page connection test) goes through ``get_provider(config).complete(...)``.
Two implementations:

* ``OpenAICompatibleProvider`` - OpenAI, Azure OpenAI, xAI (Grok), local /
  self-hosted servers (Ollama, vLLM, LM Studio) and anything else that speaks
  the OpenAI chat-completions API. Adapts ``max_tokens`` vs
  ``max_completion_tokens`` and the ``temperature`` param to whatever the model
  accepts, so GPT-4-era and GPT-5-era models both work.
* ``AnthropicProvider`` - Claude via the official ``anthropic`` SDK (Messages
  API). Not an OpenAI-compatible shim: image blocks, system prompt and usage
  fields are mapped natively.

Providers return an ``LLMResult`` carrying the text plus input/output token
counts so the caller can meter cost.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Provider presets. ``kind`` selects the implementation; ``base_url`` is the
# default endpoint (None = the SDK default); ``model`` is the default model.
PROVIDER_PRESETS: dict[str, dict] = {
    "openai": {"label": "OpenAI", "kind": "openai", "base_url": None, "model": "gpt-4o-mini"},
    "azure-openai": {"label": "Azure OpenAI", "kind": "openai", "base_url": None, "model": "gpt-4o-mini"},
    "xai": {"label": "xAI (Grok)", "kind": "openai", "base_url": "https://api.x.ai/v1", "model": "grok-4"},
    "anthropic": {"label": "Anthropic (Claude)", "kind": "anthropic", "base_url": None, "model": "claude-opus-5"},
    "local": {"label": "Local / self-hosted", "kind": "openai", "base_url": "http://localhost:11434/v1", "model": ""},
    "custom": {"label": "Custom (OpenAI-compatible)", "kind": "openai", "base_url": None, "model": ""},
}

DEFAULT_PROVIDER = "openai"


def provider_preset(provider: Optional[str]) -> dict:
    return PROVIDER_PRESETS.get((provider or "").strip().lower()) or PROVIDER_PRESETS[DEFAULT_PROVIDER]


@dataclass
class LLMImage:
    """An image to attach to a prompt (raw bytes + MIME type)."""

    data: bytes
    media_type: str = "image/jpeg"

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMProvider:
    """Base class: one call, text in (plus optional images), text out."""

    kind = "base"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or None

    def complete(
        self,
        system: str,
        prompt: str,
        images: Optional[list[LLMImage]] = None,
        max_output_tokens: int = 1024,
    ) -> LLMResult:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    kind = "openai"

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def complete(self, system, prompt, images=None, max_output_tokens=1024) -> LLMResult:
        if images:
            content: list = [{"type": "text", "text": prompt}]
            for img in images:
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:{img.media_type};base64,{img.b64}"}}
                )
        else:
            content = prompt
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]
        response = _safe_chat_completion(self._client(), self.model, messages, max_output_tokens)
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=text,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            model=getattr(response, "model", "") or self.model,
        )


def _safe_chat_completion(client, model: str, messages: list, max_output_tokens: int):
    """
    Call chat.completions.create, adapting the token / temperature params to
    whatever the target model accepts. Raises the last error if all attempts
    fail.
    """
    token_param = "max_tokens"
    include_temperature = True
    last_error = None

    for _ in range(4):
        kwargs = {"model": model, "messages": messages, token_param: max_output_tokens}
        if include_temperature:
            kwargs["temperature"] = 0
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - inspect message to adapt
            last_error = exc
            msg = str(exc).lower()
            if token_param == "max_tokens" and "max_completion_tokens" in msg:
                token_param = "max_completion_tokens"
                continue
            if include_temperature and "temperature" in msg:
                include_temperature = False
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("chat completion failed")


class AnthropicProvider(LLMProvider):
    """Claude via the official Anthropic SDK (Messages API)."""

    kind = "anthropic"

    # Extraction is a simple, well-specified task: low effort keeps thinking
    # (and therefore cost and latency) minimal on adaptive-thinking models.
    EFFORT = "low"

    def _client(self):
        import anthropic

        return anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)

    def complete(self, system, prompt, images=None, max_output_tokens=1024) -> LLMResult:
        import anthropic

        content: list = []
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.media_type, "data": img.b64},
                }
            )
        content.append({"type": "text", "text": prompt})
        kwargs = {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }

        client = self._client()
        response = None
        # Preferred: low effort (cheap). Older models reject the effort param,
        # so degrade to a plain request in that case.
        attempts = [dict(kwargs, output_config={"effort": self.EFFORT}), kwargs]
        last_error: Optional[Exception] = None
        for attempt in attempts:
            try:
                response = client.messages.create(**attempt)
                break
            except anthropic.BadRequestError as exc:
                last_error = exc
                if "effort" in str(exc).lower() and "output_config" in attempt:
                    continue
                raise
        if response is None:
            raise last_error or RuntimeError("Anthropic request failed")

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise RuntimeError(f"Model declined the request (refusal: {category})")

        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        usage = response.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        input_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        input_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        return LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            model=getattr(response, "model", "") or self.model,
        )


def get_provider(config: dict) -> LLMProvider:
    """
    Build a provider from a resolved AI config dict
    ({provider, model, api_key, base_url}). The preset supplies the default
    base URL and model when the config leaves them blank.
    """
    preset = provider_preset(config.get("provider"))
    api_key = (config.get("api_key") or "").strip()
    model = (config.get("model") or "").strip() or preset["model"]
    base_url = (config.get("base_url") or "").strip() or preset["base_url"]
    if preset["kind"] == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model, base_url=base_url)
    return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)
