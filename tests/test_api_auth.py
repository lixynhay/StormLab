from fastapi.testclient import TestClient

import api


def test_documentation_page_is_public():
    with TestClient(api.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Документация API" in response.text
    assert "/api/health" in response.text
    assert "X-API-Key" in response.text


def test_health_is_public():
    api.API_ACCESS_KEY = "test-secret"
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_rejects_missing_key():
    api.API_ACCESS_KEY = "test-secret"
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        response = client.get("/api/time-offsets")

    assert response.status_code == 401
    assert "test-secret" not in response.text


def test_api_rejects_invalid_key():
    api.API_ACCESS_KEY = "test-secret"
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        response = client.get(
            "/api/time-offsets",
            headers={"X-API-Key": "wrong-secret"},
        )

    assert response.status_code == 401
    assert "wrong-secret" not in response.text


def test_api_accepts_valid_key():
    api.API_ACCESS_KEY = "test-secret"
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        response = client.get(
            "/api/time-offsets",
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 200


def test_api_fails_closed_without_key():
    api.API_ACCESS_KEY = None
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        response = client.get("/api/time-offsets")

    assert response.status_code == 401


def test_api_rate_limit():
    api.API_ACCESS_KEY = "test-secret"
    api._rest_rate_limits.clear()

    with TestClient(api.app) as client:
        for _ in range(api.REST_RATE_LIMIT):
            response = client.get(
                "/api/time-offsets",
                headers={"X-API-Key": "test-secret"},
            )
            assert response.status_code == 200

        response = client.get(
            "/api/time-offsets",
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 429
