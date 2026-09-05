"""OpenAPI docs stay on by default."""

from fastapi.testclient import TestClient


def test_docs_available_when_enabled(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "ForiFlow API"
