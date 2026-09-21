"""Purpose: Minimal stdlib client for the Jev System One endpoint, plus a fake provider, token and cost estimates.

The design follows the shared wave-3 conventions: pinned model, explicit timeout, retries only on
429/529 and network errors, strict response validation, key redaction, and a test double with the same
`ask(state, questions)` contract so tests and the offline demo never touch the network.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"
# Published price list (docs.typesafe.ai, 21 Sept 2026): USD 0.042 per million input tokens, output free.
USD_PER_MILLION_INPUT_TOKENS = 0.042
DEFAULT_STATE_TOKEN_BUDGET = 24_000
DEFAULT_REQUESTS_PER_MINUTE = 1_000
RETRY_STATUSES = frozenset({429, 529})
# urllib raises these for connection resets, DNS failures and socket timeouts; they are worth one retry.
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, OSError)


class JevError(Exception):
    """Base class for every error raised by the client."""


class JevConfigError(JevError):
    """Missing key or unsafe endpoint; raised before any network call."""


class JevHTTPError(JevError):
    """Non-200 status that is not retried (or exhausted its retries)."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class JevResponseError(JevError):
    """The endpoint answered 200 but the payload does not match the requested contract."""


def canonical_json(value: Any) -> str:
    """Stable serialisation so the same logical request always hashes to the same cache key."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def estimate_tokens(value: Any) -> int:
    """Rough token estimate (chars / 4) used for budgets and cost previews; never a billing figure."""
    text = value if isinstance(value, str) else canonical_json(value)
    return max(1, math.ceil(len(text) / 4))


def estimate_cost_usd(input_tokens: int) -> float:
    """Estimate from the published price list; output tokens are free so they are ignored."""
    return input_tokens * USD_PER_MILLION_INPUT_TOKENS / 1e6


def request_key(model: str, state: Any, questions: dict[str, Any]) -> str:
    """Exact-input cache key: sha256 of the canonical request, so a changed criterion never hits a stale entry."""
    payload = canonical_json({"model": model, "state": state, "questions": questions})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redact(text: str, secret: str | None) -> str:
    """Errors may echo request headers; the key must never reach logs or tracebacks."""
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


@dataclass(frozen=True)
class JevResult:
    """Validated answers for one request. `cached` tells reports whether tokens were actually spent."""

    model: str
    answers: dict[str, Any]
    usage: dict[str, int]
    estimated_cost_usd: float
    cached: bool = False

    @property
    def input_tokens(self) -> int:
        return int(self.usage.get("input_tokens", 0))


class RateLimiter:
    """In-process sliding-window limiter kept under the published 1,200 requests/min ceiling.

    Threads share one window; a caller that would exceed the limit sleeps until the oldest timestamp expires.
    """

    def __init__(self, max_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE, *, clock=time.monotonic, sleep=time.sleep):
        if max_per_minute < 1:
            raise ValueError("max_per_minute must be >= 1")
        self.max_per_minute = max_per_minute
        self._clock = clock
        self._sleep = sleep
        self._stamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                self._stamps = [t for t in self._stamps if now - t < 60.0]
                if len(self._stamps) < self.max_per_minute:
                    self._stamps.append(now)
                    return
                wait = 60.0 - (now - self._stamps[0])
            self._sleep(max(wait, 0.01))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would resend the bearer key to another host; refuse instead of following."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook signature
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused by jev-screen", headers, fp)


def _default_opener(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    """Send with urllib; HTTPError carries the status and body so the caller decides about retries."""
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as err:
        body = err.read() if hasattr(err, "read") else b""
        headers = dict(err.headers.items()) if err.headers is not None else {}
        return err.code, headers, body


def _endpoint_allowed(endpoint: str) -> bool:
    """HTTPS everywhere except loopback, which tests use for a fake server."""
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _check_probability(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or not 0.0 <= value <= 1.0:
        raise JevResponseError(f"{where}: probability must be a number in [0, 1], got {value!r}")
    return float(value)


def validate_response(payload: Any, questions: dict[str, Any], expected_model: str) -> dict[str, Any]:
    """Reject anything that does not match the requested contract; never coerce silently.

    A wrong model or a missing question would otherwise turn into a wrong decision downstream.
    """
    if not isinstance(payload, dict):
        raise JevResponseError("response body is not a JSON object")
    if payload.get("model") != expected_model:
        raise JevResponseError(f"model mismatch: requested {expected_model!r}, got {payload.get('model')!r}")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevResponseError("response has no 'answers' object")
    for qid, question in questions.items():
        answer = answers.get(qid)
        if not isinstance(answer, dict):
            raise JevResponseError(f"missing answer for question {qid!r}")
        qtype = question.get("type")
        if answer.get("type") != qtype:
            raise JevResponseError(f"question {qid!r}: expected type {qtype!r}, got {answer.get('type')!r}")
        if qtype == "noul":
            _check_probability(answer.get("noul"), f"question {qid!r}")
        elif qtype == "choice":
            options = question.get("criteria") or {}
            if answer.get("choice") not in options:
                raise JevResponseError(f"question {qid!r}: choice {answer.get('choice')!r} is not one of the criteria")
            probs = answer.get("probabilities")
            if not isinstance(probs, dict):
                raise JevResponseError(f"question {qid!r}: probabilities missing")
            for option, p in probs.items():
                _check_probability(p, f"question {qid!r} option {option!r}")
            _check_probability(answer.get("confidence"), f"question {qid!r} confidence")
        elif qtype == "score":
            levels = question.get("criteria") or []
            score = answer.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= len(levels) - 1:
                raise JevResponseError(f"question {qid!r}: score {score!r} outside 0..{len(levels) - 1}")
            probs = answer.get("probabilities")
            if not isinstance(probs, dict):
                raise JevResponseError(f"question {qid!r}: probabilities missing")
            for level, p in probs.items():
                _check_probability(p, f"question {qid!r} level {level!r}")
            _check_probability(answer.get("confidence"), f"question {qid!r} confidence")
        else:
            raise JevResponseError(f"question {qid!r}: unsupported type {qtype!r}")
    usage = payload.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("input_tokens"), int):
        raise JevResponseError("response has no usage.input_tokens")
    return answers


class JevClient:
    """Stdlib-only client with the same contract as `FakeJev`: `ask(state, questions) -> JevResult`."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        state_token_budget: int = DEFAULT_STATE_TOKEN_BUDGET,
        rate_limiter: RateLimiter | None = None,
        opener: Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ):
        key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")
        if not isinstance(key, str) or not key.strip():
            raise JevConfigError("Set TYPESAFE_API_KEY (no API key configured).")
        if not _endpoint_allowed(endpoint):
            raise JevConfigError("Endpoint must use https:// (http:// is allowed only for 127.0.0.1 or localhost).")
        if timeout_seconds <= 0:
            raise JevConfigError("timeout_seconds must be positive")
        self._api_key = key.strip()
        self.endpoint = endpoint
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max(0, int(max_retries))
        self.state_token_budget = int(state_token_budget)
        self.rate_limiter = rate_limiter
        self._opener = opener or _default_opener
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.calls = 0

    def __repr__(self) -> str:  # never expose the key
        return f"JevClient(endpoint={self.endpoint!r}, model={self.model!r})"

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        """Exponential backoff with jitter; a numeric Retry-After header wins when it is longer."""
        delay = min(30.0, 0.5 * (2**attempt)) + self._rng.uniform(0.0, 0.25)
        if retry_after:
            try:
                delay = max(delay, min(60.0, float(retry_after)))
            except ValueError:
                pass  # HTTP-date form of Retry-After: keep the computed delay
        self._sleep(delay)

    def ask(self, state: Any, questions: dict[str, Any]) -> JevResult:
        if not questions:
            raise JevError("at least one question is required")
        state_tokens = estimate_tokens(state)
        if state_tokens > self.state_token_budget:
            raise JevError(
                f"state estimate {state_tokens} tokens exceeds budget {self.state_token_budget}; keep state small"
            )
        body = json.dumps({"model": self.model, "state": state, "questions": questions}).encode("utf-8")
        attempt = 0
        while True:
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()
            request = urllib.request.Request(
                self.endpoint,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "jev-screen/0.1.0",
                },
            )
            self.calls += 1
            try:
                status, headers, raw = self._opener(request, self.timeout_seconds)
            except NETWORK_ERRORS as err:
                if attempt >= self.max_retries:
                    raise JevError(
                        f"network error after {attempt + 1} attempt(s): {redact(str(err), self._api_key)}"
                    ) from err
                self._backoff(attempt, None)
                attempt += 1
                continue
            if status in RETRY_STATUSES and attempt < self.max_retries:
                self._backoff(attempt, _header(headers, "retry-after"))
                attempt += 1
                continue
            if status != 200:
                excerpt = redact(raw[:300].decode("utf-8", "replace"), self._api_key)
                raise JevHTTPError(status, excerpt or "no body")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                raise JevResponseError(f"response is not valid JSON: {err}") from err
            answers = validate_response(payload, questions, self.model)
            usage = {k: int(v) for k, v in payload["usage"].items() if isinstance(v, int)}
            return JevResult(
                model=self.model,
                answers=answers,
                usage=usage,
                estimated_cost_usd=estimate_cost_usd(usage.get("input_tokens", 0)),
            )


@dataclass
class FakeJev:
    """Offline provider with the `ask` contract, answering noul questions from a fixture file.

    Fixture shape: `{"key_field": "title", "default": {qid: p}, "records": {"<title>": {qid: p}}}`.
    Probabilities are synthetic values written by hand, not measured Jev output. A missing probability
    raises instead of guessing, so a fixture gap surfaces in tests rather than as a silent 0.5.
    """

    fixtures: dict[str, Any]
    model: str = DEFAULT_MODEL
    calls: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "FakeJev":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("records", {}), dict):
            raise JevError(f"fixture file {path} must be an object with a 'records' object")
        return cls(fixtures=data)

    def ask(self, state: Any, questions: dict[str, Any]) -> JevResult:
        if not questions:
            raise JevError("at least one question is required")
        key_field = self.fixtures.get("key_field", "title")
        key = state.get(key_field) if isinstance(state, dict) else state
        per_record = self.fixtures.get("records", {}).get(key, {})
        default = self.fixtures.get("default", {})
        answers: dict[str, Any] = {}
        for qid, question in questions.items():
            if question.get("type") != "noul":
                raise JevError(f"FakeJev answers noul questions only (question {qid!r} is {question.get('type')!r})")
            value = per_record.get(qid, default.get(qid))
            if value is None:
                raise JevError(f"fixture has no probability for question {qid!r} and {key_field}={key!r}")
            answers[qid] = {"type": "noul", "noul": _check_probability(value, f"fixture {key!r}/{qid!r}")}
        self.calls.append({"state": state, "questions": list(questions)})
        tokens = estimate_tokens({"model": self.model, "state": state, "questions": questions})
        usage = {"input_tokens": tokens, "output_tokens": 0}
        return JevResult(model=self.model, answers=answers, usage=usage, estimated_cost_usd=estimate_cost_usd(tokens))
