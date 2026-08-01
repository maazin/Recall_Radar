"""How the runner treats each kind of source failure.

The distinction matters operationally. Three of the four agency sources refuse
datacenter IP ranges, so on a CI runner or a cloud host they fail every single
time. Treating that the same as a drifted parser would leave the daily job
permanently red, and a job that is always red is one nobody reads — which is
exactly when a real structure break gets missed.
"""

from __future__ import annotations

import httpx
import pytest

from app.ingest import run as run_module
from app.ingest.base import (
    NormalizedAdvisory,
    SourceStructureError,
    SourceUnavailableError,
    check_not_bot_walled,
    fetch_url,
)
from app.models import AGENCY_FDA, STATUS_ACTIVE, TYPE_RECALL


def _advisory(uid: str = "FDA:TEST-1") -> NormalizedAdvisory:
    return NormalizedAdvisory(
        source_uid=uid,
        type=TYPE_RECALL,
        source_agency=AGENCY_FDA,
        brand_or_chain="Test Foods",
        description="A product",
        reason="Undeclared allergen",
        status=STATUS_ACTIVE,
        started_at="2026-07-01",
        updated_at="2026-07-01",
        source_url="https://example.test/record",
        category="grocery",
    )


@pytest.fixture
def sources(monkeypatch):
    """Replace the real source table with controllable fakes."""

    def install(**behaviours):
        table = {}
        for name, behaviour in behaviours.items():
            if isinstance(behaviour, Exception):

                def fetch(exc=behaviour):
                    raise exc

                table[name] = (fetch, lambda raw: [])
            else:
                table[name] = (lambda: "raw", lambda raw: [_advisory()])
        monkeypatch.setattr(run_module, "SOURCES", table)
        # Keep the database out of it; upserting is covered elsewhere.
        monkeypatch.setattr(run_module, "ingest", lambda db, advisories: (len(advisories), 0))
        return table

    return install


class TestExitCodes:
    def test_all_sources_working_exits_zero(self, sources, db):
        sources(good_a="ok", good_b="ok")
        assert run_module.main(["--source", "all"]) == 0

    def test_an_unreachable_source_does_not_fail_the_run(self, sources, db):
        sources(good="ok", blocked=SourceUnavailableError("403 from a datacenter IP"))
        assert run_module.main(["--source", "all"]) == 0

    def test_a_drifted_source_always_fails_the_run(self, sources, db):
        sources(good="ok", drifted=SourceStructureError("column renamed"))
        assert run_module.main(["--source", "all"]) == 1

    def test_drift_fails_even_alongside_unreachable_sources(self, sources, db):
        sources(
            good="ok",
            blocked=SourceUnavailableError("403"),
            drifted=SourceStructureError("table vanished"),
        )
        assert run_module.main(["--source", "all"]) == 1

    def test_everything_unreachable_fails_the_run(self, sources, db):
        """Nothing ingested at all is a real problem, even without drift."""
        sources(
            a=SourceUnavailableError("403"),
            b=SourceUnavailableError("403"),
        )
        assert run_module.main(["--source", "all"]) == 1

    def test_an_unexpected_error_fails_the_run(self, sources, db):
        sources(good="ok", odd=ValueError("something nobody predicted"))
        assert run_module.main(["--source", "all"]) == 1


class TestLogging:
    def test_unreachable_is_a_warning_not_an_error(self, sources, db, caplog):
        sources(good="ok", blocked=SourceUnavailableError("403 Forbidden"))
        run_module.main(["--source", "all"])

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert not errors, "a blocked site must not be logged as an error"
        assert any("unavailable" in r.message.lower() for r in caplog.records)

    def test_drift_is_logged_as_an_error_naming_the_source(self, sources, db, caplog):
        sources(drifted=SourceStructureError("headers changed"))
        run_module.main(["--source", "all"])

        text = " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")
        assert "STRUCTURE CHANGED" in text
        assert "drifted" in text


class TestBotWallDetection:
    """fda.gov answers a blocked caller with a redirect, not a status code.

    Following it lands on a 404 for a URL nobody requested, which hides the real
    cause behind a misleading error.
    """

    def test_redirect_to_an_abuse_page_is_recognised(self):
        request = httpx.Request("GET", "https://www.fda.gov/food/outbreaks")
        hop = httpx.Response(302, request=request)
        final = httpx.Response(
            404,
            request=httpx.Request(
                "GET", "https://www.fda.gov/apology_objects/abuse-detection-apology.html"
            ),
            history=[hop],
        )

        with pytest.raises(SourceUnavailableError) as excinfo:
            check_not_bot_walled(final, "FDA outbreak investigations")
        assert "bot-detection" in str(excinfo.value)

    def test_a_normal_response_passes_through(self):
        request = httpx.Request("GET", "https://www.fda.gov/food/outbreaks")
        check_not_bot_walled(httpx.Response(200, request=request), "FDA")


class TestFetchUrl:
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_403_becomes_unavailable_not_a_raw_status_error(self):
        with self._client(lambda request: httpx.Response(403)) as client:
            with pytest.raises(SourceUnavailableError) as excinfo:
                fetch_url(client, "https://www.fsis.usda.gov/x", "FSIS")
        message = str(excinfo.value)
        assert "403" in message
        # The message has to say the mapper is fine, or every 403 reads as a bug.
        assert "mapper is untouched" in message

    def test_server_error_becomes_unavailable(self, monkeypatch):
        # 5xx is retryable, so skip the real backoff rather than sleeping.
        monkeypatch.setattr("time.sleep", lambda _seconds: None)
        with self._client(lambda request: httpx.Response(503)) as client:
            with pytest.raises(SourceUnavailableError):
                fetch_url(client, "https://example.test/x", "Example")

    def test_connection_failure_becomes_unavailable(self):
        def boom(request):
            raise httpx.ConnectError("name resolution failed")

        with self._client(boom) as client:
            with pytest.raises(SourceUnavailableError) as excinfo:
                fetch_url(client, "https://example.test/x", "Example")
        assert "could not reach" in str(excinfo.value)

    def test_a_good_response_is_returned(self):
        with self._client(lambda request: httpx.Response(200, text="payload")) as client:
            assert fetch_url(client, "https://example.test/x", "Example").text == "payload"

    def test_404_is_still_an_error_but_reported_as_unavailable(self):
        """A missing page is not drift either — the parser never ran."""
        with self._client(lambda request: httpx.Response(404)) as client:
            with pytest.raises(SourceUnavailableError):
                fetch_url(client, "https://example.test/gone", "Example")

    def test_allowed_status_is_handed_back_for_the_caller_to_read(self):
        """openFDA answers 404 when `skip` passes the end of the results.

        That is the pagination loop's exit condition, so the caller has to be
        able to see it rather than have it raised.
        """
        with self._client(lambda request: httpx.Response(404)) as client:
            response = fetch_url(
                client, "https://api.fda.gov/x", "openFDA", allow_status=(404,)
            )
        assert response.status_code == 404

    def test_query_params_are_forwarded(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, text="ok")

        with self._client(handler) as client:
            fetch_url(client, "https://api.fda.gov/x", "openFDA", params={"limit": 100})
        assert "limit=100" in seen["url"]


class TestRateLimitRetry:
    """429 is transient, so it is worth asking again before giving up."""

    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_a_rate_limit_that_clears_is_retried_and_succeeds(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda _seconds: None)
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(429, headers={"retry-after": "1"})
            return httpx.Response(200, text="payload")

        with self._client(handler) as client:
            assert fetch_url(client, "https://api.fda.gov/x", "openFDA").text == "payload"
        assert attempts["n"] == 2

    def test_a_persistent_rate_limit_is_unavailable_not_broken(self, monkeypatch):
        """The regression this whole change exists for.

        openFDA's unauthenticated cap is per IP, and shared CI runner addresses
        exhaust it. Before this, the raw httpx error fell through to the
        runner's generic handler and was counted as a drifted source, turning a
        rate limit into a failed job and a notification email.
        """
        monkeypatch.setattr("time.sleep", lambda _seconds: None)

        with self._client(lambda request: httpx.Response(429)) as client:
            with pytest.raises(SourceUnavailableError) as excinfo:
                fetch_url(client, "https://api.fda.gov/x", "openFDA")

        message = str(excinfo.value)
        assert "429" in message
        assert "rate limited, not malformed" in message
        # The message has to name the fix, or the next person re-debugs it.
        assert "OPENFDA_API_KEY" in message

    def test_a_forbidden_response_is_not_retried(self, monkeypatch):
        """An IP-range block does not clear by asking again a second later."""
        monkeypatch.setattr("time.sleep", lambda _seconds: None)
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            return httpx.Response(403)

        with self._client(handler) as client:
            with pytest.raises(SourceUnavailableError):
                fetch_url(client, "https://www.cdc.gov/x", "CDC")
        assert attempts["n"] == 1

    def test_an_absurd_retry_after_is_capped(self):
        """Some servers answer with an hour, which outlasts the whole job."""
        from app.ingest.base import _MAX_RETRY_AFTER, _retry_delay

        response = httpx.Response(429, headers={"retry-after": "3600"})
        assert _retry_delay(response, 0) == _MAX_RETRY_AFTER
