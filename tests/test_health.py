from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/utils/health-check/")
    assert response.status_code == 200
    assert response.json() == {"message": "ok"}
