"""Tests for exponential backoff retry in HttpApiClient."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_bridge_mcp.api_client import (
    ApiError,
    HttpApiClient,
    _body_hints_rate_limit,
    _compute_backoff_delay,
    _extract_retry_after,
    _is_retryable_status,
)
from coding_bridge_mcp.config import Settings


def _settings(max_retries: int = 3, retry_base_delay: float = 0.01) -> Settings:
    return Settings(
        provider="qianfan-coding",
        mode="http",
        api_url="https://example.com/v1/chat/completions",
        api_password="test-key",
        default_model="glm-5.2",
        timeout_seconds=30.0,
        max_context_chars=96_000,
        max_messages=40,
        max_tokens=8_192,
        proxy_mode="false",
        proxy_http=None,
        proxy_https=None,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )


def _make_response(status_code: int, body: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body, ensure_ascii=False)
    resp.headers = headers or {}
    resp.content = resp.text.encode()
    return resp


class _RetryTracker:
    """Records each call and returns configured sequence of responses/errors.

    ``responses`` may contain httpx Response-like objects (MagicMock) or
    Exception instances.  The async ``__call__`` returns/raises them in order.
    """

    def __init__(self, responses: list):
        self.responses = responses
        self.call_count = 0
        self.call_args_list: list = []

    async def __call__(self, *args, **kwargs):
        self.call_args_list.append((args, kwargs))
        idx = self.call_count
        self.call_count += 1
        item = self.responses[idx % len(self.responses)]
        if isinstance(item, Exception):
            raise item
        return item


async def _run_with_client(client: HttpApiClient):
    return await client.call([{"role": "user", "content": "hi"}], model="glm-5.2")


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestIsRetryableStatus:
    def test_429_is_retryable(self):
        assert _is_retryable_status(429) is True

    def test_5xx_is_retryable(self):
        for code in (500, 502, 503, 504, 599):
            assert _is_retryable_status(code) is True

    def test_200_not_retryable(self):
        assert _is_retryable_status(200) is False

    def test_4xx_not_retryable(self):
        for code in (400, 401, 403, 404, 422):
            assert _is_retryable_status(code) is False


class TestBodyHintsRateLimit:
    def test_request_burst_keyword(self):
        assert _body_hints_rate_limit({"message": "System protection triggered by request burst"}) is True

    def test_too_many_requests(self):
        assert _body_hints_rate_limit({"error": {"message": "Too Many Requests"}}) is True

    def test_rate_limit(self):
        assert _body_hints_rate_limit("you have hit the rate limit") is True

    def test_chinese_keywords(self):
        assert _body_hints_rate_limit({"msg": "系统保护已触发"}) is True
        assert _body_hints_rate_limit({"message": "接口限流"}) is True

    def test_unknown_error_not_retryable(self):
        assert _body_hints_rate_limit({"message": "invalid api key"}) is False

    def test_empty_body_not_retryable(self):
        assert _body_hints_rate_limit({}) is False


class TestExtractRetryAfter:
    def test_numeric_retry_after(self):
        assert _extract_retry_after({"retry-after": "5"}) == 5.0

    def test_no_header(self):
        assert _extract_retry_after({}) is None

    def test_unparseable(self):
        assert _extract_retry_after({"retry-after": "tomorrow"}) is None


class TestComputeBackoffDelay:
    def test_attempt_0_is_base_delay(self):
        delay = _compute_backoff_delay(0, 1.0, max_delay=30.0)
        # 1.0 ± 20%
        assert 0.8 <= delay <= 1.2

    def test_attempt_grows_exponentially(self):
        d0 = _compute_backoff_delay(0, 1.0, max_delay=30.0)
        d1 = _compute_backoff_delay(1, 1.0, max_delay=30.0)
        d2 = _compute_backoff_delay(2, 1.0, max_delay=30.0)
        # d1 ≈ 2 * d0, d2 ≈ 2 * d1 (with jitter tolerance)
        assert d1 > d0 * 1.3
        assert d2 > d1 * 1.3

    def test_max_delay_cap(self):
        delay = _compute_backoff_delay(10, 1.0, max_delay=5.0)
        assert delay <= 5.0 * 1.2  # jitter adds at most 20%

    def test_retry_after_overrides_when_larger(self):
        delay = _compute_backoff_delay(0, 1.0, max_delay=30.0, retry_after=10.0)
        assert delay >= 10.0

    def test_retry_after_smaller_uses_exponential(self):
        delay = _compute_backoff_delay(2, 1.0, max_delay=30.0, retry_after=0.5)
        # 4s ± 20% = 3.2 to 4.8 — much larger than 0.5
        assert delay > 2.0


# ---------------------------------------------------------------------------
# Integration tests for HttpApiClient retry loop
# ---------------------------------------------------------------------------


class TestRetryOn429:
    def test_retries_on_429_and_succeeds(self):
        """After one 429, the second call succeeds → returns content."""
        responses = [
            _make_response(429, {"error": {"message": "rate limit"}}, {"retry-after": "1"}),
            _make_response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            content, usage = asyncio.run(_run_with_client(HttpApiClient(_settings())))

        assert content == "ok"
        assert tracker.call_count == 2

    def test_429_exhausts_retries(self):
        """All attempts return 429 → ApiError after max_retries attempts."""
        responses = [
            _make_response(429, {"error": {"message": "rate limit"}}),
        ] * 5
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            with pytest.raises(ApiError, match="rate limit"):
                asyncio.run(_run_with_client(HttpApiClient(_settings(max_retries=3))))

        # 1 initial + 3 retries = 4 calls
        assert tracker.call_count == 4


class TestRetryOn5xx:
    def test_retries_on_500(self):
        responses = [
            _make_response(500, {"error": "internal server error"}),
            _make_response(502, {"error": "bad gateway"}),
            _make_response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            content, _ = asyncio.run(_run_with_client(HttpApiClient(_settings())))
        assert content == "ok"
        assert tracker.call_count == 3


class TestNoRetryOn4xx:
    def test_does_not_retry_on_401(self):
        responses = [
            _make_response(401, {"error": {"message": "invalid api key"}}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            with pytest.raises(ApiError, match="invalid api key"):
                asyncio.run(_run_with_client(HttpApiClient(_settings(max_retries=3))))

        assert tracker.call_count == 1  # no retry


class TestRetryOnRateLimitKeywords:
    def test_retries_on_qianfan_burst_protection(self):
        """Qianfan returns 200 with code + burst protection msg — should retry.

        Note: we use ``error_msg`` (not ``message``) in the response body because
        Python logging reserves ``message`` as a LogRecord attribute; the real
        provider uses its own field names on the wire and the keyword check
        covers both ``message`` and ``msg`` aliases.
        """
        responses = [
            _make_response(200, {
                "code": 1,
                "error_msg": "System protection triggered by request burst. Please slow down.",
            }),
            _make_response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            content, _ = asyncio.run(_run_with_client(HttpApiClient(_settings())))
        assert content == "ok"
        assert tracker.call_count == 2


class TestRetryOnTimeout:
    def test_retries_on_timeout(self):
        import httpx

        responses = [
            httpx.TimeoutException("timed out"),
            _make_response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            content, _ = asyncio.run(_run_with_client(HttpApiClient(_settings())))
        assert content == "ok"
        assert tracker.call_count == 2


class TestRetryOnRequestError:
    def test_retries_on_connection_error(self):
        import httpx

        responses = [
            httpx.ConnectError("connection refused"),
            _make_response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            content, _ = asyncio.run(_run_with_client(HttpApiClient(_settings())))
        assert content == "ok"
        assert tracker.call_count == 2


class TestNoRetryOnUnrecoverable:
    def test_empty_content_not_retried(self):
        """Empty content (max_tokens exhausted) is not a transient error."""
        body = {
            "choices": [{"message": {
                "content": "",
                "reasoning_content": "thinking...",
            }}],
        }
        responses = [_make_response(200, body)]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            with pytest.raises(ApiError, match="empty content"):
                asyncio.run(_run_with_client(HttpApiClient(_settings(max_retries=3))))

        assert tracker.call_count == 1


class TestZeroRetries:
    def test_zero_retries_disables_retry(self):
        responses = [
            _make_response(429, {"error": {"message": "rate limit"}}),
        ]
        tracker = _RetryTracker(responses)
        with patch("httpx.AsyncClient") as mock_cls:
            fake = MagicMock()
            fake.__aenter__ = AsyncMock(return_value=fake)
            fake.__aexit__ = AsyncMock(return_value=None)
            fake.post = tracker
            mock_cls.return_value = fake

            with pytest.raises(ApiError, match="rate limit"):
                asyncio.run(_run_with_client(HttpApiClient(_settings(max_retries=0))))

        assert tracker.call_count == 1
