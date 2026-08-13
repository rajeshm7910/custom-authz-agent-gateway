import re
import sys
import time
from pathlib import Path
import httpx
import structlog
from typing import Optional, Dict, Any

# Ensure generated protobuf modules are available on path
GENERATED_DIR = Path(__file__).parent / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import google.rpc.status_pb2 as status_pb2
import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc
import envoy.config.core.v3.base_pb2 as base_pb2
import envoy.type.v3.http_status_pb2 as http_status_pb2

from src.config import settings

logger = structlog.get_logger(__name__)


def _to_bytes(val) -> bytes:
    if isinstance(val, bytes):
        return val
    return str(val or "").encode("utf-8")


class ExternalAuthzService(external_auth_pb2_grpc.AuthorizationServicer):
    """
    Unified External Authorization Servicer (Envoy ext_authz).
    Handles both standard HTTP/Cloud Run backends and Two-Tier Ingress routing.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.http_client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self.http_client is None or getattr(self.http_client, "is_closed", False) is True:
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.TARGET_API_TIMEOUT_SECONDS)
            )
        return self.http_client

    def _extract_agent_context(self, http_req, context_extensions: dict) -> dict:
        """Extract Agent ID, Tool Name, Action, Tenant ID, and Principal from headers/path/context_extensions."""
        headers = dict(http_req.headers)
        path = http_req.path or "/"
        host = http_req.host or ""

        # Extract agent prefix from hostname if applicable
        host_agent = None
        if host and "." in host:
            host_prefix = host.split(".")[0]
            if host_prefix.startswith("agent-") or host_prefix.startswith("gw-"):
                host_agent = host_prefix

        # 1. Agent ID
        agent_id = (
            context_extensions.get("agent_id")
            or headers.get("x-agent-id")
            or self._parse_path_param(path, r"/reasoningEngines/([^/:]+)")
            or self._parse_path_param(path, r"/v1/agents/([^/]+)")
            or host_agent
            or "adk-agent-app"
        )

        # 2. Tool Name / Action
        method_action = self._parse_path_param(path, r":([a-zA-Z0-9_]+)$")
        tool_name = (
            context_extensions.get("tool_name")
            or headers.get("x-agent-tool-name")
            or self._parse_path_param(path, r"/tools/([^/]+)")
            or method_action
            or ("streamQuery" if "/chat" in path or "streamQuery" in path else "query")
        )

        # 3. Tenant ID
        tenant_id = (
            context_extensions.get("tenant_id")
            or headers.get("x-agent-tenant-id")
            or headers.get("x-tenant-id")
            or "default-tenant"
        )

        # 4. User Principal / Identity
        principal = (
            context_extensions.get("principal")
            or context_extensions.get("dev.agentgateway.jwt")
            or headers.get("x-user-id")
            or headers.get("x-goog-authenticated-user-email")
            or headers.get("authorization", "")
            or "anonymous"
        )

        return {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tenant_id": tenant_id,
            "principal": principal,
            "context_extensions": context_extensions,
        }

    @staticmethod
    def _parse_path_param(path: str, pattern: str) -> str | None:
        match = re.search(pattern, path)
        return match.group(1) if match else None

    async def Check(self, request: external_auth_pb2.CheckRequest, context) -> external_auth_pb2.CheckResponse:
        start_time = time.perf_counter()

        attributes = request.attributes
        http_req = attributes.request.http
        context_extensions = dict(attributes.context_extensions)

        method = http_req.method or "POST"
        path = http_req.path or "/"
        host = http_req.host or ""
        request_id = http_req.id or http_req.headers.get("x-request-id", "")
        headers = dict(http_req.headers)
        client_ip = attributes.source.address if attributes.HasField("source") else ""

        agent_ctx = self._extract_agent_context(http_req, context_extensions)

        log = logger.bind(
            request_id=request_id,
            agent_id=agent_ctx["agent_id"],
            tool_name=agent_ctx["tool_name"],
            tenant_id=agent_ctx["tenant_id"],
            method=method,
            path=path,
            host=host,
        )
        log.info("Received Agent Gateway authorization check")

        # Construct Agent Gateway Auth Payload
        api_payload = {
            "agent_context": agent_ctx,
            "request": {
                "id": request_id,
                "method": method,
                "path": path,
                "host": host,
                "headers": headers,
                "client_ip": client_ip,
            }
        }

        api_headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentGateway-CustomAuthz-CloudRun/1.0",
            "X-AgentGateway-Request-ID": request_id or "gw-req-live",
            "X-Source": "CloudRun-ExtAuthz",
        }
        if settings.TARGET_API_KEY:
            api_headers["Authorization"] = f"Bearer {settings.TARGET_API_KEY}"

        target_url = f"{settings.TARGET_API_URL}?source=cloud_run_authz_extension"

        try:
            client = await self._get_client()
            response = await client.post(
                target_url,
                json=api_payload,
                headers=api_headers,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                allowed = data.get("allowed", True)

                if allowed:
                    principal = str(data.get("principal") or data.get("user_id", agent_ctx["principal"] or "anonymous"))
                    tenant_id = str(data.get("tenant_id", agent_ctx["tenant_id"]))
                    allowed_tools = ",".join(data.get("allowed_tools", ["*"]))
                    scopes = ",".join(data.get("scopes", ["agent:invoke"]))

                    log.info("Agent Authorization GRANTED", duration_ms=round(duration_ms, 2), principal=principal)
                    return self._build_allow_response(
                        principal=principal,
                        tenant_id=tenant_id,
                        allowed_tools=allowed_tools,
                        scopes=scopes,
                    )
                else:
                    reason = data.get("reason", "Agent access denied by policy")
                    log.warn("Agent Authorization DENIED by Policy API", duration_ms=round(duration_ms, 2), reason=reason)
                    return self._build_deny_response(
                        status_code=http_status_pb2.StatusCode.Forbidden,
                        message=reason
                    )
            elif response.status_code in (401, 403):
                log.warn("Agent Authorization DENIED by API status", status_code=response.status_code)
                code = http_status_pb2.StatusCode.Unauthorized if response.status_code == 401 else http_status_pb2.StatusCode.Forbidden
                return self._build_deny_response(status_code=code, message="Agent unauthorized")
            else:
                log.error("External Auth API returned error status", status_code=response.status_code)
                return self._handle_failure("External Policy Engine error", log)

        except (httpx.TimeoutException, httpx.RequestError) as e:
            log.error("Failed to connect to External Auth API", error=str(e))
            return self._handle_failure(f"Policy Engine unreachable: {str(e)}", log)
        except Exception as e:
            log.exception("Unexpected error during Agent Authz Check", error=str(e))
            return self._handle_failure(f"Internal gateway error: {str(e)}", log)

    def _handle_failure(self, reason: str, log) -> external_auth_pb2.CheckResponse:
        if settings.FAIL_OPEN:
            log.warn("FAIL_OPEN active - Granting agent request despite error", reason=reason)
            return self._build_allow_response(
                principal="fail-open-principal",
                tenant_id="fail-open-tenant",
                allowed_tools="*",
                scopes="agent:fail-open"
            )
        else:
            log.error("FAIL_CLOSED active - Denying agent request due to error", reason=reason)
            return self._build_deny_response(
                status_code=http_status_pb2.StatusCode.ServiceUnavailable,
                message=f"Agent Gateway Authz service error: {reason}"
            )

    def _build_allow_response(self, principal: str, tenant_id: str, allowed_tools: str, scopes: str) -> external_auth_pb2.CheckResponse:
        ok_response = external_auth_pb2.OkHttpResponse()

        # Inject standard Agent Gateway headers into upstream request
        self._add_header(ok_response, settings.HEADER_PRINCIPAL, principal)
        self._add_header(ok_response, settings.HEADER_TENANT_ID, tenant_id)
        self._add_header(ok_response, settings.HEADER_ALLOWED_TOOLS, allowed_tools)
        self._add_header(ok_response, settings.HEADER_SCOPES, scopes)
        self._add_header(ok_response, settings.HEADER_AUTH_STATUS, "ALLOWED")

        return external_auth_pb2.CheckResponse(
            status=status_pb2.Status(code=0),  # 0 = google.rpc.Code.OK
            ok_response=ok_response
        )

    def _build_deny_response(self, status_code: int, message: str) -> external_auth_pb2.CheckResponse:
        denied_response = external_auth_pb2.DeniedHttpResponse()
        denied_response.status.code = status_code
        denied_response.body = f'{{"error": "Agent Authorization Denied", "detail": "{message}"}}'

        content_type = denied_response.headers.add()
        content_type.header.key = b"content-type"
        content_type.header.value = b"application/json"

        return external_auth_pb2.CheckResponse(
            status=status_pb2.Status(code=7, message=message),  # 7 = google.rpc.Code.PERMISSION_DENIED
            denied_response=denied_response
        )

    @staticmethod
    def _add_header(ok_response, key: str, value: str):
        h = ok_response.headers.add()
        h.header.key = _to_bytes(key)
        h.header.value = _to_bytes(value)
