import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import httpx

# Ensure generated protobuf modules are available on path
GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
from src.authz_service import ExternalAuthzService


def build_check_request(headers, path="/chat", method="POST", host="agent.example.com") -> external_auth_pb2.CheckRequest:
    req = external_auth_pb2.CheckRequest()
    req.attributes.request.http.method = method
    req.attributes.request.http.path = path
    req.attributes.request.http.host = host
    for k, v in headers.items():
        req.attributes.request.http.headers[k] = v
    req.attributes.source.address = "127.0.0.1"
    return req


@pytest.mark.asyncio
async def test_authz_service_check_allowed():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"allowed": True}
    mock_client.post.return_value = mock_resp

    servicer = ExternalAuthzService(http_client=mock_client)
    req = build_check_request(headers={"authorization": "Bearer valid-token", "x-agent-id": "adk-agent-app"})

    resp = await servicer.Check(req, None)
    assert resp.status.code == 0
    assert len(resp.ok_response.headers) >= 1


@pytest.mark.asyncio
async def test_authz_service_check_denied():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"allowed": False}
    mock_client.post.return_value = mock_resp

    servicer = ExternalAuthzService(http_client=mock_client)
    req = build_check_request(headers={"authorization": "Bearer denied-token", "x-agent-id": "adk-agent-app"})

    resp = await servicer.Check(req, None)
    assert resp.status.code == 7
    assert resp.denied_response.status.code == 403
