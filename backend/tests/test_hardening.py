"""Production hardening: security headers, request size limit, CORS, docs and config checks."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main as main_module
from app import middleware as middleware_module
from app.config import Settings, get_settings
from app.middleware import SecurityHeadersMiddleware

STRONG_SECRET = "Q8v!x2Lr#9pZt4Wm@7Ky$3Nd&6Hs^1Bc*5Jf"


def settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://logitrack:s3cret@db:5432/logitrack",
        "jwt_secret": STRONG_SECRET,
    }
    return Settings(**{**base, **overrides})


# ---------------------------------------------------------------- headers
@pytest.mark.parametrize("path", ["/api/health", "/api/auth/me", "/api/does-not-exist"])
def test_security_headers_on_every_api_response(client, path) -> None:
    r = client.get(path)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"  # per-user data is never cached


def test_explicit_cache_control_is_preserved(auth_client) -> None:
    r = auth_client.get("/api/reports/export/fleet.csv")
    assert r.headers.get_list("cache-control") == ["no-store"]  # not duplicated


def test_hsts_only_when_cookies_are_https_only(monkeypatch) -> None:
    for secure, expected in ((False, False), (True, True)):
        monkeypatch.setattr(
            middleware_module, "get_settings", lambda s=secure: settings(cookie_secure=s)
        )
        sent: list[dict] = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def collect(message, sent=sent):
            sent.append(message)

        mw = SecurityHeadersMiddleware(app)
        scope = {"type": "http", "path": "/api/health", "headers": []}
        asyncio.run(mw(scope, None, collect))
        names = {k for k, _ in sent[0]["headers"]}
        assert (b"strict-transport-security" in names) is expected


# ---------------------------------------------------------------- body size limit
def test_oversized_request_is_refused_before_reading_the_body() -> None:
    reached = False

    async def app(scope, receive, send):  # must never run
        nonlocal reached
        reached = True

    sent: list[dict] = []

    async def collect(message):
        sent.append(message)

    mw = SecurityHeadersMiddleware(app)
    too_big = str(get_settings().max_upload_bytes + 2 * 1024 * 1024).encode()
    scope = {
        "type": "http",
        "path": "/api/compliance/documents/1/file",
        "headers": [(b"content-length", too_big)],
    }
    asyncio.run(mw(scope, None, collect))
    assert not reached
    assert sent[0]["status"] == 413
    assert b"too large" in sent[1]["body"]


def test_normal_requests_pass_the_size_check(client) -> None:
    r = client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code == 401


# ---------------------------------------------------------------- CORS
def test_cors_allows_only_configured_origins(client) -> None:
    allowed = get_settings().cors_origins[0]
    ok = client.options(
        "/api/auth/login",
        headers={"Origin": allowed, "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == allowed
    assert ok.headers.get("access-control-allow-credentials") == "true"
    evil = client.options(
        "/api/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers


# ---------------------------------------------------------------- API docs
def test_docs_hidden_in_production(monkeypatch) -> None:
    prod = settings(
        environment="production",
        cookie_secure=True,
        cors_origins=["https://logitrack.example.com"],
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: prod)
    monkeypatch.setattr(middleware_module, "get_settings", lambda: prod)
    with TestClient(main_module.create_app()) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/api/health").status_code == 200


def test_docs_available_in_development(client) -> None:
    assert client.get("/openapi.json").status_code == 200


# ---------------------------------------------------------------- configuration checks
def test_wildcard_cors_is_always_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit origins"):
        settings(cors_origins=["*"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"jwt_secret": "change-me-change-me-change-me-change-me"}, "JWT_SECRET"),
        ({"jwt_secret": "a" * 40}, "JWT_SECRET"),  # long but not random
        ({"cors_origins": ["http://localhost:5190"]}, "localhost"),
        ({"cors_origins": ["http://logitrack.example.com"]}, "https://"),
        (
            {"database_url": "postgresql+psycopg://logitrack:change-me@db/logitrack"},
            "placeholder",
        ),
    ],
)
def test_production_refuses_unsafe_settings(overrides, message) -> None:
    good = {
        "environment": "production",
        "cookie_secure": True,
        "cors_origins": ["https://logitrack.example.com"],
    }
    with pytest.raises(ValidationError, match=message):
        settings(**{**good, **overrides})


def test_safe_production_settings_are_accepted() -> None:
    s = settings(
        environment="production",
        cookie_secure=True,
        cors_origins=["https://logitrack.example.com"],
    )
    assert s.docs_enabled is False
    assert (
        settings(
            environment="production",
            cookie_secure=True,
            cors_origins=["https://x.example"],
            api_docs=True,
        ).docs_enabled
        is True
    )
