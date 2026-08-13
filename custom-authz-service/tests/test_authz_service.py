import sys
from pathlib import Path
import pytest
import httpx

# Add generated and project root to path
GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import google.rpc.status_pb2 as status_pb2
import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.type.v3.http_status_pb2 as http_status_pb2

from src.authz_service import ExternalAuthzService
from src.config import settings


def build_agent_gateway_check_request(
    agent_id: str = "agent-financial-advisor",
    tool_name: str = "execute_query",
    path: str = "/v1/agents/agent-financial-advisor/tools/execute_query",
    host: str = "agentgateway.example.com",
    method: str = "POST"
) -> external_auth_pb2.CheckRequest:
    req = external_auth_pb2.CheckRequest()
    req.attributes.request.http.method = method
    req.attributes.request.http.path = path
    req.attributes.request.http.host = host
    req.attributes.request.http.id = "req-agent-99001"
    req.attributes.request.http.headers["authorization"] = "Bearer agent-token-xyz"
    req.attributes.request.http.headers["x-agent-id"] = agent_id
    req.attributes.request.http.headers["x-agent-tool-name"] = tool_name
    req.attributes.context_extensions["tenant_id"] = "tenant-corp-1"
    req.attributes.context_extensions["dev.agentgateway.jwt"] = "user-alice@example.com"
    req.attributes.source.address = "10.128.0.45"
    return req


@pytest.mark.asyncio
async def test_agent_gateway_check_allow_success():
    async def mock_handler(request: httpx.Request):
        payload = request.read()
        return httpx.Response(
            200,
            json={
                "allowed": True,
                "principal": "alice@example.com",
                "tenant_id": "tenant-corp-1",
                "allowed_tools": ["execute_query", "search_knowledge_base"],
                "scopes": ["agent:invoke", "tools:read"]
            }
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = ExternalAuthzService(http_client=mock_client)
        req = build_agent_gateway_check_request()
        
        response = await service.Check(req, context=None)

        assert response.status.code == 0  # OK
        assert response.HasField("ok_response")
        
        headers = {h.header.key.decode("utf-8") if isinstance(h.header.key, bytes) else h.header.key: h.header.value.decode("utf-8") if isinstance(h.header.value, bytes) else h.header.value for h in response.ok_response.headers}
        assert headers.get("x-agentgateway-principal") == "alice@example.com"
        assert headers.get("x-agentgateway-tenant-id") == "tenant-corp-1"
        assert headers.get("x-agentgateway-allowed-tools") == "execute_query,search_knowledge_base"
        assert headers.get("x-agentgateway-auth-status") == "ALLOWED"


@pytest.mark.asyncio
async def test_reasoning_engine_path_context_extraction():
    captured_payload = {}
    async def mock_handler(request: httpx.Request):
        nonlocal captured_payload
        import json
        captured_payload = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "allowed": True,
                "principal": "alice@company.com",
                "tenant_id": "tenant-enterprise-01",
                "allowed_tools": ["streamQuery"],
                "scopes": ["agent:streamQuery"]
            }
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = ExternalAuthzService(http_client=mock_client)
        
        # Test Vertex AI streamQuery reasoning engine path
        req = external_auth_pb2.CheckRequest()
        req.attributes.request.http.method = "POST"
        req.attributes.request.http.path = "/v1/projects/622260204773/locations/us-central1/reasoningEngines/1231533837213761536:streamQuery"
        req.attributes.request.http.host = "agent-a.example.com"
        req.attributes.request.http.headers["x-goog-authenticated-user-email"] = "accounts.google.com:alice@company.com"

        response = await service.Check(req, context=None)
        assert response.status.code == 0
        assert captured_payload["agent_context"]["agent_id"] == "1231533837213761536"
        assert captured_payload["agent_context"]["tool_name"] == "streamQuery"


@pytest.mark.asyncio
async def test_agent_gateway_check_deny_forbidden():
    async def mock_handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "allowed": False,
                "reason": "Agent not authorized to execute tool: execute_query for tenant-corp-1"
            }
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = ExternalAuthzService(http_client=mock_client)
        req = build_agent_gateway_check_request()

        response = await service.Check(req, context=None)

        assert response.status.code == 7  # PERMISSION_DENIED
        assert response.HasField("denied_response")
        assert response.denied_response.status.code == http_status_pb2.StatusCode.Forbidden
        assert "Agent not authorized to execute tool" in response.denied_response.body


@pytest.mark.asyncio
async def test_agent_gateway_target_api_timeout_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "FAIL_OPEN", False)

    async def mock_handler(request: httpx.Request):
        raise httpx.TimeoutException("Policy Engine Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = ExternalAuthzService(http_client=mock_client)
        req = build_agent_gateway_check_request()

        response = await service.Check(req, context=None)

        assert response.status.code == 7  # PERMISSION_DENIED
        assert response.HasField("denied_response")
        assert response.denied_response.status.code == http_status_pb2.StatusCode.ServiceUnavailable


@pytest.mark.asyncio
async def test_agent_gateway_target_api_timeout_fail_open(monkeypatch):
    monkeypatch.setattr(settings, "FAIL_OPEN", True)

    async def mock_handler(request: httpx.Request):
        raise httpx.TimeoutException("Policy Engine Connection timed out")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = ExternalAuthzService(http_client=mock_client)
        req = build_agent_gateway_check_request()

        response = await service.Check(req, context=None)

        assert response.status.code == 0  # OK
        assert response.HasField("ok_response")
        headers = {h.header.key.decode("utf-8") if isinstance(h.header.key, bytes) else h.header.key: h.header.value.decode("utf-8") if isinstance(h.header.value, bytes) else h.header.value for h in response.ok_response.headers}
        assert headers.get("x-agentgateway-principal") == "fail-open-principal"
