"""Транспорты: OpenRouter, локальный OpenAI-совместимый сервер, фиктивный стенд.

Успешный HTTP-статус не считается завершённой генерацией.
Повтор после обрыва, случившегося когда запрос уже ушёл, не делается: он может стоить денег.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from sitewatch.experiments.vlm_compare.common import redact

COMPLETED_FINISH = {"stop"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class ImagePayload:
    neutral_id: str
    role: str
    sha256: str
    data: bytes
    width: int
    height: int


@dataclass
class CallSpec:
    requested_model: str
    prompt_text: str
    images: list[ImagePayload]
    response_mode: str
    schema: dict[str, Any] | None
    generation: dict[str, Any]
    route: dict[str, Any]
    schema_name: str = "observation"


@dataclass
class ProviderRaw:
    status: str
    completed: bool
    raw_text: str | None = None
    http_status: int | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    requested_model: str = ""
    actual_model: str = "unknown"
    actual_provider: str = "unknown"
    provider_revision: str | None = None
    generation_id: str | None = None
    request_id: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    cost_status: str = "unknown"
    duration_ms: float | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    unsupported_settings: list[str] = field(default_factory=list)
    synthetic: bool = False
    invoked: bool = True
    settings_applied: dict[str, Any] = field(default_factory=dict)
    request_provider: dict[str, Any] = field(default_factory=dict)
    reasoning_text: str | None = None
    reproducibility_note: str = "Провайдер не сообщил ревизию весов."


_SECRET_HEADER_PARTS = ("authorization", "cookie", "api-key", "apikey", "token")
_SAFE_HEADER_NAMES = {
    "x-request-id",
    "x-openrouter-request-id",
    "x-generation-id",
    "cf-ray",
    "date",
    "content-type",
}


def safe_response_headers(headers: Any) -> dict[str, str]:
    """Диагностические заголовки без ключа, cookie и авторизации."""
    kept: dict[str, str] = {}
    items = headers.items() if hasattr(headers, "items") else []
    for key, value in items:
        name = str(key).lower()
        if any(part in name for part in _SECRET_HEADER_PARTS):
            continue
        if name not in _SAFE_HEADER_NAMES and "request-id" not in name:
            continue
        text = str(value)
        if len(text) > 200:
            text = text[:200]
        kept[name] = text
    return kept


def request_id_from_headers(headers: dict[str, str]) -> str | None:
    return headers.get("x-request-id") or headers.get("x-openrouter-request-id")


def empty_usage() -> dict[str, Any]:
    return {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "cached_tokens": None,
    }


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    try:
        return int(payload[key])
    except (TypeError, ValueError):
        return None


def usage_from_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], float | None, str]:
    """Отсутствующие usage и стоимость остаются пустыми, а не нулём."""
    usage = empty_usage()
    if not isinstance(payload, dict):
        return usage, None, "unknown"
    usage["prompt_tokens"] = _optional_int(payload, "prompt_tokens")
    usage["completion_tokens"] = _optional_int(payload, "completion_tokens")
    usage["total_tokens"] = _optional_int(payload, "total_tokens")
    completion_details = payload.get("completion_tokens_details")
    if isinstance(completion_details, dict) and "reasoning_tokens" in completion_details:
        usage["reasoning_tokens"] = _optional_int(completion_details, "reasoning_tokens")
    prompt_details = payload.get("prompt_tokens_details")
    if isinstance(prompt_details, dict) and "cached_tokens" in prompt_details:
        usage["cached_tokens"] = _optional_int(prompt_details, "cached_tokens")
    if "cost" not in payload or payload.get("cost") is None:
        return usage, None, "unknown"
    try:
        return usage, float(payload["cost"]), "api"
    except (TypeError, ValueError):
        return usage, None, "unknown"


def _reasoning_text(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _message_text(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts) if parts else None
    return None


def reported_name(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        for key in keys:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "unknown"


def classify_completion(payload: Any) -> tuple[str, bool, str | None, str | None, str | None]:
    """Возвращает status, completed, raw_text, finish_reason, native_finish_reason.

    HTTP 200 с ошибкой, пустым choices или finish_reason=length — не завершённый результат.
    """
    if not isinstance(payload, dict):
        return "provider_error", False, None, None, None
    if payload.get("error"):
        message = payload["error"]
        text = message.get("message") if isinstance(message, dict) else str(message)
        return "provider_error", False, text, None, None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "provider_error", False, None, None, None
    choice = choices[0]
    if choice.get("error"):
        err = choice["error"]
        text = err.get("message") if isinstance(err, dict) else str(err)
        return "provider_error", False, text, choice.get("finish_reason"), choice.get("native_finish_reason")
    finish = choice.get("finish_reason")
    native = choice.get("native_finish_reason")
    text = _message_text(choice.get("message"))
    if finish == "length":
        return "truncated", False, text, finish, native
    if finish == "content_filter":
        return "refused", False, text, finish, native
    if finish not in COMPLETED_FINISH:
        return "provider_error", False, text, finish if isinstance(finish, str) else None, native if isinstance(native, str) else None
    if text is None or text.strip() == "":
        return "provider_error", False, text, finish, native
    return "completed", True, text, finish, native


def _retry_delay(attempt: int, headers: Any, cap: float) -> float:
    raw = None
    if headers is not None:
        getter = getattr(headers, "get", None)
        if callable(getter):
            raw = getter("Retry-After") or getter("retry-after")
    if raw is not None:
        try:
            return min(float(raw), cap)
        except (TypeError, ValueError):
            pass
    return min(2 ** max(attempt - 1, 0), cap)


class OpenRouterTransport:
    name = "openrouter"
    billed = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        client: Any | None = None,
        max_retries: int = 2,
        timeout: float = 180,
        sleep: Callable[[float], None] = time.sleep,
        retry_cap_seconds: float = 15,
        lookup_generation: bool = True,
        max_http_attempts: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.max_retries = max_retries
        self.max_http_attempts = max_http_attempts
        self.timeout = timeout
        self.sleep = sleep
        self.retry_cap_seconds = retry_cap_seconds
        self.lookup_generation = lookup_generation

    def complete(self, spec: CallSpec) -> ProviderRaw:
        import base64

        content: list[dict[str, Any]] = [{"type": "text", "text": spec.prompt_text}]
        for image in spec.images:
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        body: dict[str, Any] = {
            "model": spec.requested_model,
            "messages": [{"role": "user", "content": content}],
        }
        applied: dict[str, Any] = {}
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if spec.generation.get(key) is not None:
                body[key] = spec.generation[key]
                applied[key] = spec.generation[key]
        provider: dict[str, Any] = {"allow_fallbacks": bool(spec.route.get("allow_fallbacks", False))}
        if spec.route.get("order"):
            provider["order"] = list(spec.route["order"])
        if spec.route.get("only"):
            provider["only"] = list(spec.route["only"])
        if spec.route.get("ignore"):
            provider["ignore"] = list(spec.route["ignore"])
        unsupported: list[str] = []
        if spec.response_mode == "structured":
            if not spec.schema:
                return ProviderRaw(
                    status="unsupported",
                    completed=False,
                    requested_model=spec.requested_model,
                    unsupported_settings=["response_format"],
                    errors=["structured_schema_missing"],
                    invoked=False,
                    settings_applied=applied,
                )
            provider["require_parameters"] = True
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": spec.schema_name, "strict": True, "schema": spec.schema},
            }
            applied["response_format"] = "json_schema"
        else:
            provider["require_parameters"] = False
        body["provider"] = provider
        applied["provider"] = dict(provider)
        reasoning = spec.generation.get("reasoning")
        if isinstance(reasoning, dict) and reasoning:
            body["reasoning"] = {key: reasoning[key] for key in ("enabled",) if key in reasoning}
            applied["reasoning"] = dict(body["reasoning"])
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "Skripka-vlm-compare",
        }
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0))
        errors: list[str] = []
        attempts = 0
        started = time.perf_counter()
        attempt_limit = self.max_retries + 1
        if self.max_http_attempts is not None:
            attempt_limit = min(attempt_limit, max(int(self.max_http_attempts), 0))
        if attempt_limit < 1:
            if owns_client:
                client.close()
            return self._finish(
                spec,
                status="not_sent",
                completed=False,
                attempts=0,
                errors=["attempt_budget_exhausted"],
                started=started,
                applied=applied,
                unsupported=unsupported,
                invoked=False,
            )
        try:
            for attempt in range(1, attempt_limit + 1):
                attempts = attempt
                try:
                    response = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
                except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
                    errors.append(redact(f"{type(exc).__name__}", [self.api_key]))
                    if attempt >= attempt_limit:
                        return self._finish(
                            spec,
                            status="http_error",
                            completed=False,
                            attempts=attempts,
                            errors=errors,
                            started=started,
                            applied=applied,
                            unsupported=unsupported,
                        )
                    self.sleep(_retry_delay(attempt, None, self.retry_cap_seconds))
                    continue
                except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
                    errors.append(redact(f"ambiguous_after_send:{type(exc).__name__}", [self.api_key]))
                    return self._finish(
                        spec,
                        status="ambiguous_after_send",
                        completed=False,
                        attempts=attempts,
                        errors=errors,
                        started=started,
                        applied=applied,
                        unsupported=unsupported,
                    )
                diag_headers = safe_response_headers(response.headers)
                diag_request_id = request_id_from_headers(diag_headers)
                if response.status_code in RETRYABLE_STATUS:
                    errors.append(f"http_{response.status_code}")
                    if attempt >= attempt_limit:
                        return self._finish(
                            spec,
                            status="http_error",
                            completed=False,
                            http_status=response.status_code,
                            request_id=diag_request_id,
                            response_headers=diag_headers,
                            attempts=attempts,
                            errors=errors,
                            started=started,
                            applied=applied,
                            unsupported=unsupported,
                        )
                    self.sleep(_retry_delay(attempt, response.headers, self.retry_cap_seconds))
                    continue
                if response.status_code >= 400:
                    detail = redact(getattr(response, "text", "")[:500], [self.api_key])
                    errors.append(f"http_{response.status_code}:{detail}")
                    status = "unsupported" if response.status_code in {400, 404} and spec.response_mode == "structured" else "http_error"
                    if status == "unsupported":
                        unsupported.append("response_format")
                    return self._finish(
                        spec,
                        status=status,
                        completed=False,
                        http_status=response.status_code,
                        request_id=diag_request_id,
                        response_headers=diag_headers,
                        attempts=attempts,
                        errors=errors,
                        started=started,
                        applied=applied,
                        unsupported=unsupported,
                    )
                try:
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    errors.append(redact(f"bad_json:{type(exc).__name__}", [self.api_key]))
                    return self._finish(
                        spec,
                        status="provider_error",
                        completed=False,
                        http_status=response.status_code,
                        request_id=diag_request_id,
                        response_headers=diag_headers,
                        attempts=attempts,
                        errors=errors,
                        started=started,
                        applied=applied,
                        unsupported=unsupported,
                    )
                status, completed, text, finish, native = classify_completion(payload)
                usage, cost, cost_status = usage_from_payload(payload.get("usage") if isinstance(payload, dict) else None)
                reasoning_text = None
                if isinstance(payload, dict):
                    choices = payload.get("choices")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                        reasoning_text = _reasoning_text(choices[0].get("message"))
                actual_model = reported_name(payload, ("model",))
                actual_provider = reported_name(payload, ("provider", "provider_name"))
                generation_id = payload.get("id") if isinstance(payload, dict) and isinstance(payload.get("id"), str) else None
                if actual_provider == "unknown" and generation_id and self.lookup_generation and completed:
                    looked = self._generation_meta(client, generation_id, headers)
                    if looked:
                        actual_provider = looked.get("provider") or "unknown"
                        if looked.get("model"):
                            actual_model = looked["model"]
                        if cost is None and looked.get("cost") is not None:
                            cost = looked["cost"]
                            cost_status = "api"
                return self._finish(
                    spec,
                    status=status,
                    completed=completed,
                    raw_text=text,
                    http_status=response.status_code,
                    finish_reason=finish,
                    native_finish_reason=native,
                    actual_model=actual_model,
                    actual_provider=actual_provider,
                    generation_id=generation_id,
                    request_id=diag_request_id,
                    response_headers=diag_headers,
                    usage=usage,
                    cost_usd=cost,
                    cost_status=cost_status,
                    attempts=attempts,
                    errors=errors,
                    started=started,
                    applied=applied,
                    unsupported=unsupported,
                    reasoning_text=reasoning_text,
                )
        finally:
            if owns_client:
                client.close()
        return self._finish(
            spec,
            status="http_error",
            completed=False,
            attempts=attempts,
            errors=errors or ["retry_loop_exhausted"],
            started=started,
            applied=applied,
            unsupported=unsupported,
        )

    def _generation_meta(self, client: Any, generation_id: str, headers: dict[str, str]) -> dict[str, Any] | None:
        try:
            response = client.get(
                f"{self.base_url}/generation",
                params={"id": generation_id},
                headers=headers,
            )
            if response.status_code != 200:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        provider = data.get("provider_name") if isinstance(data.get("provider_name"), str) else "unknown"
        model = data.get("model") if isinstance(data.get("model"), str) else None
        cost = data.get("total_cost")
        try:
            cost_value = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_value = None
        return {"provider": provider or "unknown", "model": model, "cost": cost_value}

    def _finish(self, spec: CallSpec, *, started: float, applied: dict[str, Any], unsupported: list[str], **kwargs: Any) -> ProviderRaw:
        raw = ProviderRaw(
            requested_model=spec.requested_model,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            settings_applied=applied,
            request_provider=dict(applied.get("provider") or {}),
            unsupported_settings=unsupported,
            usage=kwargs.pop("usage", None) or empty_usage(),
            **kwargs,
        )
        raw.errors = [redact(item, [self.api_key]) for item in raw.errors]
        if raw.raw_text:
            raw.raw_text = redact(raw.raw_text, [self.api_key])
        if raw.reasoning_text:
            raw.reasoning_text = redact(raw.reasoning_text, [self.api_key])
        return raw


class LocalOpenAITransport:
    """Текущий локальный сервер. Не меняет его настройки и не останавливает процесс."""

    name = "local_openai"
    billed = False

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        client: Any | None = None,
        timeout: float = 180,
        structured_output: str = "unsupported",
        provider_routing: str = "unsupported",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client
        self.timeout = timeout
        self.structured_output = structured_output
        self.provider_routing = provider_routing

    def complete(self, spec: CallSpec) -> ProviderRaw:
        unsupported: list[str] = []
        if spec.response_mode == "structured" and self.structured_output != "enforced":
            return ProviderRaw(
                status="unsupported",
                completed=False,
                requested_model=spec.requested_model,
                actual_model="unknown",
                actual_provider="local",
                unsupported_settings=["response_format"],
                errors=["local_shim_does_not_enforce_schema"],
                invoked=False,
                reproducibility_note="Локальный shim не принуждает JSON Schema и при ошибке разбора подставляет другой объект.",
            )
        route_requested = bool(spec.route.get("order") or spec.route.get("only") or spec.route.get("ignore"))
        if route_requested or self.provider_routing == "unsupported" and spec.route.get("allow_fallbacks") is not None:
            if route_requested:
                unsupported.append("provider")
        import base64

        content: list[dict[str, Any]] = [{"type": "text", "text": spec.prompt_text}]
        for image in spec.images:
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        body: dict[str, Any] = {
            "model": spec.requested_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": spec.generation.get("temperature", 0),
            "max_tokens": spec.generation.get("max_tokens", 400),
        }
        applied = {"temperature": body["temperature"], "max_tokens": body["max_tokens"]}
        for skipped in ("seed", "top_p", "provider"):
            if spec.generation.get(skipped) is not None or skipped == "provider":
                if skipped != "provider" or route_requested:
                    if skipped not in unsupported:
                        unsupported.append(skipped)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0))
        started = time.perf_counter()
        try:
            try:
                response = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
                return ProviderRaw(
                    status="ambiguous_after_send",
                    completed=False,
                    requested_model=spec.requested_model,
                    actual_provider="local",
                    attempts=1,
                    errors=[redact(type(exc).__name__, [self.api_key])],
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    unsupported_settings=unsupported,
                    settings_applied=applied,
                )
            except httpx.HTTPError as exc:
                return ProviderRaw(
                    status="http_error",
                    completed=False,
                    requested_model=spec.requested_model,
                    actual_provider="local",
                    attempts=1,
                    errors=[redact(type(exc).__name__, [self.api_key])],
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    unsupported_settings=unsupported,
                    settings_applied=applied,
                )
            if response.status_code >= 400:
                return ProviderRaw(
                    status="http_error",
                    completed=False,
                    http_status=response.status_code,
                    requested_model=spec.requested_model,
                    actual_provider="local",
                    attempts=1,
                    errors=[redact(getattr(response, "text", "")[:400], [self.api_key])],
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    unsupported_settings=unsupported,
                    settings_applied=applied,
                )
            payload = response.json()
            status, completed, text, finish, native = classify_completion(payload)
            usage, cost, cost_status = usage_from_payload(payload.get("usage") if isinstance(payload, dict) else None)
            actual_model = reported_name(payload, ("model",)) if isinstance(payload, dict) else "unknown"
            return ProviderRaw(
                status=status,
                completed=completed,
                raw_text=redact(text or "", [self.api_key]) if text else text,
                http_status=response.status_code,
                finish_reason=finish,
                native_finish_reason=native,
                requested_model=spec.requested_model,
                actual_model=actual_model,
                actual_provider="local",
                usage=usage,
                cost_usd=cost,
                cost_status=cost_status if cost is not None else "unknown",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                attempts=1,
                unsupported_settings=unsupported,
                settings_applied=applied,
                reproducibility_note="Локальный сервер не сообщает ревизию весов отдельно от имени модели.",
            )
        finally:
            if owns_client:
                client.close()


class FixtureTransport:
    """Фиктивные ответы. Их нельзя принимать за ответы реальных моделей."""

    name = "fixture"
    billed = False

    def __init__(self) -> None:
        self.calls: list[CallSpec] = []

    def complete(self, spec: CallSpec) -> ProviderRaw:
        self.calls.append(spec)
        kind = _fixture_kind(spec)
        usage = empty_usage()
        cost_status = "unknown"
        if kind == "tokens":
            usage = {"prompt_tokens": 1200, "completion_tokens": 40, "total_tokens": 1240}
        text, finish, status, completed = _fixture_body(spec, kind)
        return ProviderRaw(
            status=status,
            completed=completed,
            raw_text=text,
            http_status=200,
            finish_reason=finish,
            native_finish_reason=finish,
            requested_model=spec.requested_model,
            actual_model="fixture-transport",
            actual_provider="fixture",
            usage=usage,
            cost_usd=None,
            cost_status=cost_status,
            duration_ms=1.0,
            attempts=1,
            synthetic=True,
            settings_applied=dict(spec.generation),
            reproducibility_note="Фикстура. Это не ответ модели и не измерение качества.",
        )


def _fixture_kind(spec: CallSpec) -> str:
    if "235b" in spec.requested_model and spec.response_mode == "text":
        return "three"
    if "397b" in spec.requested_model:
        return "unknown"
    if "kimi" in spec.requested_model and spec.response_mode == "structured":
        return "broken"
    if "Qwen3-VL-8B" in spec.requested_model or spec.requested_model.endswith("8B-Instruct"):
        return "truncated"
    if "kimi" in spec.requested_model:
        return "zero"
    return "tokens"


def _fixture_body(spec: CallSpec, kind: str) -> tuple[str, str, str, bool]:
    prefix = "[FIXTURE] Ответ тестового транспорта, не модели.\n"
    if kind == "truncated":
        if spec.response_mode == "structured":
            return prefix + '{"count": 2', "length", "truncated", False
        return prefix + "count: 2\nvisibility: full", "length", "truncated", False
    if kind == "broken":
        return prefix + "{not json", "stop", "completed", True
    if "элементы" in spec.prompt_text and spec.response_mode != "structured":
        return (
            prefix
            + "window: presence=present; count=unknown; boxes=none\n"
            + "column: presence=uncertain; count=unknown; boxes=none\n"
            + "floor_slab: presence=not_visible; count=unknown; boxes=none\n"
            + "roof: presence=present; count=1; boxes=none\n"
            + "facade: presence=present; count=unknown; boxes=none\n"
            + "grounds: fixture",
            "stop",
            "completed",
            True,
        )
    if "признаки работ" in spec.prompt_text and spec.response_mode != "structured":
        return (
            prefix
            + "structure: presence=uncertain; completion=unknown\n"
            + "enclosure: presence=not_visible; completion=unknown\n"
            + "roofing: presence=uncertain; completion=unknown\n"
            + "equipment: presence=present; completion=unknown; role=resource\n"
            + "grounds: fixture",
            "stop",
            "completed",
            True,
        )
    if "изменилось" in spec.prompt_text and spec.response_mode != "structured":
        return (
            prefix + "added: fixture-element\nremoved: none\nchanged: none\nviewpoint: partial\nlimitations: fixture",
            "stop",
            "completed",
            True,
        )
    if spec.response_mode == "structured":
        if kind == "broken":
            return prefix + "{not json", "stop", "completed", True
        if kind == "truncated":
            return prefix + '{"count": 2', "length", "truncated", False
        if spec.schema_name == "floors" or "этажность" in spec.prompt_text:
            count: int | None = 3 if kind == "three" else None if kind == "unknown" else 0 if kind == "zero" else 2
            body = {
                "count": count,
                "visibility": "full" if count else "none",
                "grounds": "fixture visual note",
                "uncertainty": "high",
                "refusal": count is None,
            }
            import json

            return prefix + json.dumps(body, ensure_ascii=False), "stop", "completed", True
        if "элементы" in spec.prompt_text:
            import json

            return prefix + json.dumps(
                {
                    "grounds": "fixture",
                    "items": [
                        {"category": "window", "presence": "present", "count": None, "boxes": None},
                        {"category": "roof", "presence": "present", "count": 1, "boxes": None},
                    ],
                },
                ensure_ascii=False,
            ), "stop", "completed", True
        if "признаки работ" in spec.prompt_text:
            import json

            return prefix + json.dumps(
                {
                    "grounds": "fixture",
                    "aspects": [
                        {"name": "structure", "presence": "uncertain", "completion": "unknown", "equipment_role": "not_applicable"},
                        {"name": "equipment", "presence": "present", "completion": "unknown", "equipment_role": "resource"},
                    ],
                },
                ensure_ascii=False,
            ), "stop", "completed", True
        import json

        return prefix + json.dumps(
            {
                "added": ["fixture-element"],
                "removed": [],
                "changed": [],
                "viewpoint": "partial",
                "limitations": "fixture",
            },
            ensure_ascii=False,
        ), "stop", "completed", True
    if kind == "truncated":
        return prefix + "count: 2\nvisibility: full", "length", "truncated", False
    if kind == "unknown":
        return prefix + "count: unknown\nvisibility: none\ngrounds: fixture\nuncertainty: high\nrefusal: yes", "stop", "completed", True
    if kind == "zero":
        return prefix + "count: 0\nvisibility: full\ngrounds: fixture zero\nuncertainty: low\nrefusal: no", "stop", "completed", True
    if kind == "three":
        return prefix + "count: 3\nvisibility: full\ngrounds: fixture rows\nuncertainty: low\nrefusal: no", "stop", "completed", True
    if "элементы" in spec.prompt_text:
        return (
            prefix
            + "window: presence=present; count=unknown; boxes=none\n"
            + "column: presence=uncertain; count=unknown; boxes=none\n"
            + "floor_slab: presence=not_visible; count=unknown; boxes=none\n"
            + "roof: presence=present; count=1; boxes=none\n"
            + "facade: presence=present; count=unknown; boxes=none\n"
            + "grounds: fixture",
            "stop",
            "completed",
            True,
        )
    if "признаки работ" in spec.prompt_text:
        return (
            prefix
            + "structure: presence=uncertain; completion=unknown\n"
            + "enclosure: presence=not_visible; completion=unknown\n"
            + "roofing: presence=uncertain; completion=unknown\n"
            + "equipment: presence=present; completion=unknown; role=resource\n"
            + "grounds: fixture",
            "stop",
            "completed",
            True,
        )
    if "изменилось" in spec.prompt_text:
        return (
            prefix + "added: fixture-element\nremoved: none\nchanged: none\nviewpoint: partial\nlimitations: fixture",
            "stop",
            "completed",
            True,
        )
    return prefix + "count: 2\nvisibility: partial\ngrounds: fixture\nuncertainty: medium\nrefusal: no", "stop", "completed", True
