from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "doctranslate-api",
    }


def test_health_check_allows_local_frontend_origin() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:3001"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:3001"
    )
