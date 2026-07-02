"""Small compatibility shim for OpenAI-compatible chat completions.

Newer models (e.g. GPT-5 / o-series) require ``max_completion_tokens`` instead
of ``max_tokens`` and may reject a non-default ``temperature``. Older models
only accept ``max_tokens``. This helper adapts based on the API's error
messages so the same code works across model generations and providers.
"""

import logging

logger = logging.getLogger(__name__)


def safe_chat_completion(client, model: str, messages: list, max_output_tokens: int):
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
