from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, csrf, new_client, register


def test_register_creates_admin_workspace_and_session(client: TestClient) -> None:
    me = register(client, "ana@example.com", "Loja da Ana")
    assert me["user"]["email"] == "ana@example.com"
    assert me["workspace"]["name"] == "Loja da Ana"
    assert me["workspace"]["role"] == "admin"
    assert "datasets:upload" in me["permissions"]
    cookie = client.cookies.get("df_session")
    assert cookie
    assert len(cookie) > 30

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ana@example.com"


def test_session_cookie_is_httponly(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Bia",
            "email": "bia@example.com",
            "password": PASSWORD,
            "workspace_name": "WS",
        },
        headers=csrf(client),
    )
    set_cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookies if c.startswith("df_session="))
    csrf_cookie = next(c for c in set_cookies if c.startswith("df_csrf="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    register(client, "dup@example.com")
    other = new_client()
    response = other.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Outra",
            "email": "DUP@example.com",
            "password": PASSWORD,
            "workspace_name": "Outro WS",
        },
        headers=csrf(other),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_unavailable"


def test_weak_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Fraca",
            "email": "f@example.com",
            "password": "123",
            "workspace_name": "Outro WS",
        },
        headers=csrf(client),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "password"


def test_login_logout_flow(client: TestClient) -> None:
    register(client, "carlos@example.com")
    client.post("/api/v1/auth/logout", headers=csrf(client))
    assert client.get("/api/v1/auth/me").status_code == 401

    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "carlos@example.com", "password": "errada-123456"},
        headers=csrf(client),
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["message"] == "E-mail ou senha inválidos."

    ok = client.post(
        "/api/v1/auth/login",
        json={"email": "Carlos@Example.com", "password": PASSWORD},
        headers=csrf(client),
    )
    assert ok.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_unknown_email_gets_same_error_as_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ninguem@example.com", "password": "qualquer-coisa"},
        headers=csrf(client),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_logout_revokes_session_server_side(client: TestClient) -> None:
    register(client)
    token = client.cookies.get("df_session")
    client.post("/api/v1/auth/logout", headers=csrf(client))
    replay = new_client()
    replay.cookies.set("df_session", token)
    assert replay.get("/api/v1/auth/me").status_code == 401


def test_unsafe_requests_require_csrf(client: TestClient) -> None:
    register(client)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"

    forged = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forjado"})
    assert forged.status_code == 403


def test_csrf_token_is_bound_to_session(client: TestClient) -> None:
    register(client)
    other = new_client()
    register(other)
    stolen = other.cookies.get("df_csrf")
    client.cookies.set("df_csrf", stolen)
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": stolen})
    assert response.status_code == 403


def test_foreign_origin_is_rejected(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/auth/logout", headers={**csrf(client), "Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_origin"


def test_login_is_rate_limited(client: TestClient) -> None:
    register(client, "rl@example.com")
    client.post("/api/v1/auth/logout", headers=csrf(client))
    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "rl@example.com", "password": "errada-errada"},
            headers=csrf(client),
        ).status_code
        for _ in range(12)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[-1] == 429


def test_password_reset_flow(client: TestClient, dispatched: list) -> None:
    register(client, "reset@example.com")
    old_session = client.cookies.get("df_session")

    anon = new_client()
    response = anon.post(
        "/api/v1/auth/password/forgot", json={"email": "reset@example.com"}, headers=csrf(anon)
    )
    assert response.status_code == 202
    unknown = anon.post(
        "/api/v1/auth/password/forgot", json={"email": "nao-existe@example.com"}, headers=csrf(anon)
    )
    assert unknown.status_code == 202
    assert unknown.json() == response.json()

    sent = [args for name, args in dispatched if name == "email.password_reset"]
    assert len(sent) == 1
    token = sent[0][1]

    reset = anon.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "Nova-senha-456"},
        headers=csrf(anon),
    )
    assert reset.status_code == 200
    again = anon.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "Outra-senha-789"},
        headers=csrf(anon),
    )
    assert again.status_code == 422

    replay = new_client()
    replay.cookies.set("df_session", old_session)
    assert replay.get("/api/v1/auth/me").status_code == 401

    login = anon.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "Nova-senha-456"},
        headers=csrf(anon),
    )
    assert login.status_code == 200


def test_error_responses_are_standardized(client: TestClient) -> None:
    response = client.get("/api/v1/datasets")
    body = response.json()
    assert response.status_code == 401
    assert set(body) == {"error", "request_id"}
    assert body["error"]["code"] == "unauthenticated"
    assert response.headers["x-request-id"] == body["request_id"]
    assert response.headers["x-content-type-options"] == "nosniff"
