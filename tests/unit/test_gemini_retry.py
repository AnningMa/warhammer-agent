from types import SimpleNamespace

import pytest

from warhammer_agent.gemini_retry import (
    generate_content_with_retry,
    retry_after_seconds,
)


class APIError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Responses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **request):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(*outcomes):
    return SimpleNamespace(models=Responses(outcomes))


def test_short_rate_limit_waits_and_retries_once():
    error = APIError(429, "Please retry in 58.5s.")
    expected = object()
    resource = client(error, expected)
    waits = []

    result = generate_content_with_retry(
        resource,
        model="test",
        sleep=waits.append,
    )

    assert result is expected
    assert resource.models.calls == 2
    assert waits == [59.5]


@pytest.mark.parametrize(
    "error",
    [
        APIError(403, "The caller does not have permission"),
        APIError(429, "Please retry in 10h50m51s."),
        APIError(429, "Quota exceeded without a retry duration"),
    ],
)
def test_non_short_rate_limits_are_not_retried(error):
    resource = client(error)

    with pytest.raises(APIError):
        generate_content_with_retry(resource, model="test", sleep=lambda _: None)

    assert resource.models.calls == 1


def test_retry_duration_parses_compound_units():
    error = APIError(429, "Please retry in 1m2.5s.")

    assert retry_after_seconds(error) == 62.5
