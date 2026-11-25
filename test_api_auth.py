from fastapi.testclient import TestClient

import api


def test_health_is_public():
    api.API_ACCESS_KEY = "test-secret"

    with TestClient(api.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200


def test_api_rejects_missing_key():
    api.API_ACCESS_KEY = "test-secret"

    with TestClient(api.app) as client:
        response = client.get("/api/time-offsets")

    assert response.status_code == 403


def test_api_rejects_invalid_key():
    api.API_ACCESS_KEY = "test-secret"

    with TestClient(api.app) as client:
        response = client.get(
            "/api/time-offsets",
            headers={"X-API-Key": "wrong-secret"},
        )

    assert response.status_code == 403


def test_api_accepts_valid_key():
    api.API_ACCESS_KEY = "test-secret"

    with TestClient(api.app) as client:
        response = client.get(
            "/api/time-offsets",
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 200


def test_api_fails_closed_without_key():
    api.API_ACCESS_KEY = None

    with TestClient(api.app) as client:
        response = client.get("/api/time-offsets")

    assert response.status_code == 403
