from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_rejects_non_pdf():
    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"title": "Test document"},
    )
    assert response.status_code == 415


def test_search_requires_query():
    response = client.post("/search", json={"query": "policy", "limit": 5})
    assert response.status_code == 200
    assert response.json()["query"] == "policy"
    assert "results" in response.json()


def test_unknown_document_404():
    response = client.get("/documents/not-a-real-id")
    assert response.status_code == 404
