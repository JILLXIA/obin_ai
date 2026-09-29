from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, AuthenticationError, RateLimitError

from app.config import Settings
from app.index import read_metadata, write_index
from app.main import create_app
from app.service import ChatService


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, openai_api_key="", index_path=tmp_path / "index.sqlite3")


def test_setup_state_document_and_pdf(settings):
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        assert health.json()["status"] == "setup_required"
        assert not health.json()["api_key_configured"]
        assert "X-Request-ID" in health.headers
        document = client.get("/api/document").json()
        assert document["page_count"] == 80
        pdf = client.get("/api/document/pdf")
        assert pdf.content.startswith(b"%PDF")
        assert pdf.headers["content-type"] == "application/pdf"
        ranged = client.get("/api/document/pdf", headers={"Range": "bytes=0-9"})
        assert ranged.status_code == 206
        assert len(ranged.content) == 10
        response = client.post("/api/chat", json={"query": "sales?"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "api_key_missing"


@pytest.mark.parametrize(
    "body", [{"query": " "}, {"query": "x" * 2001}, {}, {"query": "sales?", "history": []}]
)
def test_query_validation(settings, body):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/chat", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_query"


def test_stateless_chat_contract(settings):
    answer = ChatService.insufficient("placeholder")
    service = Mock(answer=AsyncMock(return_value=answer))
    with TestClient(create_app(settings, service)) as client:
        assert client.post("/api/chat", json={"query": "  first question  "}).status_code == 200
        client.post("/api/chat", json={"query": "second question"})
    assert service.answer.call_args_list[0].args[0] == "first question"
    assert service.answer.call_args_list[1].args[0] == "second question"
    assert len(service.answer.call_args_list[1].args) == 2


@pytest.mark.parametrize(
    "exception,status,code",
    [
        (TimeoutError(), 504, "request_timeout"),
        (
            APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
            503,
            "provider_connection",
        ),
        (
            RateLimitError(
                "secret provider body",
                response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            429,
            "provider_rate_limit",
        ),
        (
            AuthenticationError(
                "secret provider body",
                response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            503,
            "provider_auth",
        ),
        (RuntimeError("secret provider body"), 500, "request_failed"),
    ],
)
def test_actionable_redacted_errors(settings, exception, status, code):
    service = Mock(answer=AsyncMock(side_effect=exception))
    with TestClient(create_app(settings, service)) as client:
        response = client.post("/api/chat", json={"query": "sales?"})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert "secret provider body" not in response.text


def test_stale_index_is_not_accepted(settings, index):
    metadata = read_metadata(index.path)
    metadata["extraction_version"] = "old"
    write_index(settings.index_path, index.ordered, metadata)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["index_status"] == "stale"


def test_host_allowlist(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400
