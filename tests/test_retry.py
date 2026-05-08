"""Tests for luckyd_code.retry — retry decorator with backoff."""

import pytest

from luckyd_code.retry import (
    with_retry,
    RetryableError,
    NonRetryableError,
    ModelNotFoundError,
)


class TestRetryDecorator:
    """Tests for the @with_retry decorator."""

    def test_successful_call_no_retry(self):
        """A successful call should not retry."""
        call_count = [0]

        @with_retry(max_retries=3, base_delay=0.001)
        def succeed():
            call_count[0] += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count[0] == 1

    def test_retries_on_retryable_error(self):
        """Should retry when a RetryableError is raised."""
        call_count = [0]

        @with_retry(max_retries=2, base_delay=0.001)
        def eventually_succeed():
            call_count[0] += 1
            if call_count[0] < 2:
                raise RetryableError("Transient")
            return "recovered"

        result = eventually_succeed()
        assert result == "recovered"
        assert call_count[0] == 2

    def test_exhausts_retries(self):
        """Should raise the last exception when retries are exhausted."""
        call_count = [0]

        @with_retry(max_retries=2, base_delay=0.001)
        def always_fails():
            call_count[0] += 1
            raise RetryableError("Always")

        with pytest.raises(RetryableError):
            always_fails()
        assert call_count[0] == 3  # 1 initial + 2 retries

    def test_non_retryable_error_not_retried(self):
        """NonRetryableError should be raised immediately without retry."""
        call_count = [0]

        @with_retry(max_retries=3, base_delay=0.001)
        def bad_request():
            call_count[0] += 1
            raise NonRetryableError("Bad request")

        with pytest.raises(NonRetryableError):
            bad_request()
        assert call_count[0] == 1

    def test_model_not_found_not_retried(self):
        """ModelNotFoundError should be raised immediately."""
        call_count = [0]

        @with_retry(max_retries=3, base_delay=0.001)
        def wrong_model():
            call_count[0] += 1
            raise ModelNotFoundError("Unknown model")

        with pytest.raises(ModelNotFoundError):
            wrong_model()
        assert call_count[0] == 1

    def test_preserves_function_metadata(self):
        """@with_retry should preserve docstring and name via @wraps."""

        @with_retry()
        def documented_function():
            """This function has a docstring."""
            return 42

        assert documented_function.__name__ == "documented_function"
        assert "docstring" in (documented_function.__doc__ or "")

    def test_preserves_return_value(self):
        """Return value should be passed through correctly."""

        @with_retry()
        def returns_complex():
            return {"key": [1, 2, 3], "nested": {"a": True}}

        result = returns_complex()
        assert result == {"key": [1, 2, 3], "nested": {"a": True}}

    def test_function_arguments_preserved(self):
        """Arguments should be passed through to the function."""

        @with_retry(max_retries=1, base_delay=0.001)
        def with_args(a, b, c=None):
            return a + b + (c or 0)

        assert with_args(1, 2) == 3
        assert with_args(1, 2, c=3) == 6

    def test_zero_max_retries(self):
        """max_retries=0 should mean no retries, only the initial call."""
        call_count = [0]

        @with_retry(max_retries=0, base_delay=0.001)
        def fail_once():
            call_count[0] += 1
            raise RetryableError("Fail")

        with pytest.raises(RetryableError):
            fail_once()
        assert call_count[0] == 1

    def test_jitter_changes_delay(self, monkeypatch):
        """Jitter should modify the delay time (not test exact sleep)."""
        sleeps = []

        import time
        original_sleep = time.sleep
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        @with_retry(max_retries=1, base_delay=1.0, jitter=True)
        def fail():
            raise RetryableError("oops")

        with pytest.raises(RetryableError):
            fail()

        time.sleep = original_sleep
        assert len(sleeps) == 1
        # With jitter=True, delay should be 0.5-1.0x base_delay
        assert 0.4 < sleeps[0] < 1.1

    def test_no_jitter(self, monkeypatch):
        """With jitter=False, exact base_delay should be used."""
        sleeps = []

        import time
        original_sleep = time.sleep
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        @with_retry(max_retries=1, base_delay=1.0, jitter=False)
        def fail():
            raise RetryableError("oops")

        with pytest.raises(RetryableError):
            fail()

        time.sleep = original_sleep
        assert len(sleeps) == 1
        assert sleeps[0] == 1.0


class TestExceptionClasses:
    """Tests for custom exception hierarchy."""

    def test_retryable_error_is_exception(self):
        """RetryableError should be a subclass of Exception."""
        assert issubclass(RetryableError, Exception)

    def test_non_retryable_error_is_exception(self):
        """NonRetryableError should be a subclass of Exception."""
        assert issubclass(NonRetryableError, Exception)

    def test_model_not_found_error_is_exception(self):
        """ModelNotFoundError should be a subclass of Exception."""
        assert issubclass(ModelNotFoundError, Exception)

    def test_exceptions_not_interchangeable(self):
        """The exception types should be distinct."""
        assert RetryableError != NonRetryableError
        assert RetryableError != ModelNotFoundError

    def test_exception_message(self):
        """Exception messages should be preserved."""
        e = RetryableError("Rate limit exceeded")
        assert str(e) == "Rate limit exceeded"
