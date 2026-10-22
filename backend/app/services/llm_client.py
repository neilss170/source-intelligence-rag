import time

import httpx

#: A rate limit that clears within this many seconds is waited out once;
#: a longer one is raised so the caller can shrink the request instead.
MAX_RETRY_WAIT_S = 20.0


class LLMError(RuntimeError):
    """Raised when the chat provider fails or returns nothing usable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        #: HTTP status, where there was one: 429 is a rate limit and 413 a
        #: prompt over the provider's per-request or per-minute token limit,
        #: and both are worth retrying with fewer passages.
        self.status_code = status_code


class ChatCompletionClient:
    """Minimal client for any OpenAI-compatible chat completions endpoint.

    Works with OpenAI, Groq, OpenRouter, or a local Ollama through
    ``api_base_url``. Uses plain httpx so no provider SDK is required.
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4.1-mini",
        fallback_models: tuple[str, ...] = (),
        timeout_s: float = 60.0,
    ) -> None:
        """Create the client.

        Args:
            fallback_models: Models tried in order when the ones before them
                have used up their quota. Providers such as Groq meter each
                model separately, so a second model keeps the assistant
                answering after the first runs out for the day.
        """
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._models = tuple(dict.fromkeys((model, *fallback_models)))
        self._timeout_s = timeout_s
        #: Model to the monotonic time its quota is expected back.
        self._exhausted: dict[str, float] = {}

    @property
    def model(self) -> str:
        """The model the next request will use."""
        now = time.monotonic()
        for model in self._models:
            if self._exhausted.get(model, 0.0) <= now:
                return model
        return self._models[0]

    def complete_text(self, *, system: str, user: str, max_tokens: int = 3000) -> str:
        # The budget is generous on purpose: reasoning models (Groq's
        # gpt-oss among them) spend part of it thinking before they write, and
        # a tight cap makes them return an empty string.
        last_error: LLMError | None = None
        now = time.monotonic()
        available = [m for m in self._models if self._exhausted.get(m, 0.0) <= now]
        for model in available or [self._models[0]]:
            try:
                return self._complete(model, system, user, max_tokens)
            except LLMError as exc:
                wait = getattr(exc, "retry_after", None)
                if exc.status_code != 429 or wait is None:
                    raise
                # Out of quota for longer than is worth waiting: skip this
                # model until it comes back and try the next one.
                self._exhausted[model] = time.monotonic() + wait
                last_error = exc
        raise last_error

    def _complete(self, model: str, system: str, user: str, max_tokens: int) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        for attempt in range(2):
            try:
                return self._post(payload)
            except LLMError as exc:
                wait = getattr(exc, "retry_after", None)
                if (
                    attempt == 0
                    and exc.status_code == 429
                    and wait is not None
                    and wait <= MAX_RETRY_WAIT_S
                ):
                    time.sleep(wait)
                    continue
                raise
        raise AssertionError("unreachable")

    def _post(self, payload: dict) -> str:
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(
                    f"{self._api_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error = LLMError(f"Chat provider returned {status}", status_code=status)
            error.retry_after = _retry_after(exc.response.headers.get("retry-after"))
            raise error from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"Chat provider request failed: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Chat provider returned an empty answer")
        return content.strip()


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None
