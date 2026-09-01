"""API authentication tests (NFR-4.5).

The property under test is not "the token check works" but "there is no
configuration in which the API listens beyond loopback without one". The
service previously had no authentication at all, and binding wide was a
printed warning — which is advice, not a control.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alpha500.api import auth
from alpha500.config import settings


@pytest.fixture
def no_tokens(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None, raising=False)
    monkeypatch.setattr(settings, "api_tokens", None, raising=False)


@pytest.fixture
def tokens(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None, raising=False)
    monkeypatch.setattr(
        settings, "api_tokens", "alice:alice-secret,bob:bob-secret", raising=False
    )
    return {"alice": "alice-secret", "bob": "bob-secret"}


# --- the control that matters --------------------------------------------


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_binding_beyond_loopback_without_a_token_refuses_to_start(no_tokens, host):
    """The whole point. A warning would let this run; this must not.

    Anything reaching the port would otherwise receive every endpoint and the
    full dataset, which market-data licensing does not permit redistributing.
    """
    with pytest.raises(SystemExit) as exit_info:
        auth.guard_bind_address(host)
    assert "Refusing to bind" in str(exit_info.value)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_without_a_token_still_starts(no_tokens, host):
    """The single-operator local workflow is unchanged by this feature."""
    auth.guard_bind_address(host)


def test_binding_wide_is_allowed_once_a_token_exists(tokens):
    auth.guard_bind_address("0.0.0.0")


# --- token handling -------------------------------------------------------


def test_tokens_are_labelled_so_one_reviewer_can_be_revoked(tokens):
    assert auth.configured_tokens() == tokens
    assert auth.identify("alice-secret").label == "alice"
    assert auth.identify("bob-secret").label == "bob"


def test_an_unknown_or_absent_secret_identifies_nobody(tokens):
    assert auth.identify("not-a-token") is None
    assert auth.identify("") is None
    assert auth.identify(None) is None


def test_a_near_miss_is_rejected(tokens):
    """Prefix and case must not pass; compare_digest is exact."""
    assert auth.identify("alice-secre") is None
    assert auth.identify("alice-secretx") is None
    assert auth.identify("ALICE-SECRET") is None


def test_no_tokens_means_no_authentication(no_tokens):
    assert auth.auth_required() is False
    assert auth.identify("anything") is None


def test_bearer_parsing_accepts_only_the_bearer_scheme():
    assert auth.bearer_from_header("Bearer abc") == "abc"
    assert auth.bearer_from_header("bearer abc") == "abc"
    assert auth.bearer_from_header("Basic abc") is None
    assert auth.bearer_from_header("abc") is None
    assert auth.bearer_from_header(None) is None
    assert auth.bearer_from_header("Bearer ") is None


def test_minted_tokens_are_long_and_unique():
    minted = {auth.mint_token() for _ in range(50)}
    assert len(minted) == 50
    assert all(len(t) >= 40 for t in minted)


# --- the middleware over real routes --------------------------------------


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the app at an empty store.

    The API's lifespan opens the real DuckDB, which a running server holds —
    these tests are about the middleware, not the data, so they get their own.
    """
    from alpha500.db.connection import close_process_connection

    close_process_connection()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    yield
    close_process_connection()


def client() -> TestClient:
    from alpha500.api.main import app

    return TestClient(app)


def test_every_api_route_refuses_an_anonymous_caller(tokens, isolated_store):
    """Allow-list, so a route added later is protected by default."""
    with client() as c:
        for path in ("/api/status", "/api/presets", "/api/metrics/definitions",
                     "/api/dashboard", "/api/fib/funnel"):
            assert c.get(path).status_code == 401, f"{path} was reachable anonymously"


def test_health_is_reachable_without_a_credential(tokens, isolated_store):
    """Enough to see the service is alive and wants a token; nothing more."""
    with client() as c:
        body = c.get("/api/health").json()
    assert body == {"status": "ok", "auth_required": True}


def test_a_valid_bearer_token_is_accepted(tokens, isolated_store):
    with client() as c:
        response = c.get(
            "/api/status", headers={"Authorization": "Bearer alice-secret"}
        )
    assert response.status_code == 200


def test_a_rejected_token_does_not_say_why(tokens, isolated_store):
    """Absent, malformed and wrong must be indistinguishable to the caller."""
    with client() as c:
        bodies = {
            c.get("/api/status").json()["detail"],
            c.get("/api/status", headers={"Authorization": "Bearer wrong"}).json()["detail"],
            c.get("/api/status", headers={"Authorization": "Basic x"}).json()["detail"],
        }
    assert bodies == {"Authentication required."}


def test_session_exchanges_a_token_for_a_cookie(tokens, isolated_store):
    with client() as c:
        created = c.post("/api/session", json={"token": "bob-secret"})
        assert created.status_code == 200
        assert created.json()["label"] == "bob"
        # The cookie now carries the request; no header needed.
        assert c.get("/api/status").status_code == 200


def test_the_session_cookie_is_not_readable_by_page_scripts(tokens, isolated_store):
    with client() as c:
        created = c.post("/api/session", json={"token": "alice-secret"})
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_a_bad_token_creates_no_session(tokens, isolated_store):
    with client() as c:
        assert c.post("/api/session", json={"token": "nope"}).status_code == 401
        assert c.get("/api/status").status_code == 401


def test_ending_a_session_revokes_access(tokens, isolated_store):
    with client() as c:
        c.post("/api/session", json={"token": "alice-secret"})
        assert c.get("/api/status").status_code == 200
        c.post("/api/session/end")
        assert c.get("/api/status").status_code == 401


def test_with_no_tokens_configured_the_api_is_open_as_before(no_tokens, isolated_store):
    """Loopback-only development must not need a credential."""
    with client() as c:
        assert c.get("/api/status").status_code == 200
        assert c.get("/api/health").json()["auth_required"] is False
