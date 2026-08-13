import re
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure generated protobuf modules are available on path
GENERATED_DIR = Path(__file__).parent / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.config.core.v3.base_pb2 as base_pb2
import envoy.service.ext_proc.v3.external_processor_pb2 as ext_proc_pb2
import envoy.service.ext_proc.v3.external_processor_pb2_grpc as ext_proc_pb2_grpc
import envoy.type.v3.http_status_pb2 as http_status_pb2

from src.config import settings

logger = structlog = None
try:
    import structlog
    logger = structlog.get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# Basic safety patterns for inline Prompt Inspection (Model Armor guardrail)
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+prompts", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
    re.compile(r"<script>.*?</script>", re.IGNORECASE | re.DOTALL),
]


def _to_str(val: Any) -> str:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="ignore")
    return str(val or "")


def _to_bytes(val: Any) -> bytes:
    if isinstance(val, bytes):
        return val
    return str(val or "").encode("utf-8")


class ExternalProcessorService(ext_proc_pb2_grpc.ExternalProcessorServicer):
    """
    Unified Envoy ext_proc (External Processing) Servicer.
    Intercepts headers and/or body payloads to inject governance headers
    and perform prompt safety inspection.
    """

    def __init__(self, http_client: Optional[Any] = None):
        self.http_client = http_client

    async def _get_client(self):
        if self.http_client is None or getattr(self.http_client, "is_closed", False) is True:
            import httpx
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.TARGET_API_TIMEOUT_SECONDS)
            )
        return self.http_client

    def _extract_agent_context(self, header_map: Dict[str, str], path: str, authority: str) -> Dict[str, str]:
        """Extract Agent ID, Tool Name, Action, Tenant ID, and Principal from headers/path."""
        auth_header = header_map.get("authorization", "")

        # 1. Agent ID - check x-agent-id header, hostname, or path
        host_agent = None
        if authority and "." in authority:
            host_prefix = authority.split(".")[0]
            if host_prefix.startswith("agent-") or host_prefix.startswith("adk-") or host_prefix.startswith("gw-"):
                host_agent = host_prefix

        # Reasoning Engine path pattern matcher for fallback
        re_agent_id = None
        for pattern in (r"/reasoningEngines/([^/:]+)", r"/v1/agents/([^/]+)"):
            match = re.search(pattern, path)
            if match:
                re_agent_id = match.group(1)
                break

        agent_id = (
            header_map.get("x-agent-id")
            or re_agent_id
            or host_agent
            or "adk-agent-app"
        )

        # 2. Tool Name / Action
        re_tool_name = None
        match_action = re.search(r":([a-zA-Z0-9_]+)$", path)
        if match_action:
            re_tool_name = match_action.group(1)

        tool_name = (
            header_map.get("x-agent-tool-name")
            or re_tool_name
            or ("streamQuery" if "/chat" in path or "streamQuery" in path else "query")
        )

        # 3. Tenant ID
        tenant_id = (
            header_map.get("x-agent-tenant-id")
            or header_map.get("x-tenant-id")
            or "default-tenant"
        )

        # 4. User Principal / Identity
        principal = (
            header_map.get("x-agentgateway-principal")
            or header_map.get("x-user-id")
            or header_map.get("x-goog-authenticated-user-email")
            or (auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else auth_header)
            or "anonymous-user"
        )

        return {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tenant_id": tenant_id,
            "principal": principal,
        }

    def _inspect_prompt_safety(self, text: str) -> bool:
        """Inspect prompt payload against known prompt injection and jailbreak patterns."""
        if not settings.ENABLE_PROMPT_INSPECTION or not text:
            return True
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                logger.warning("Prompt injection pattern detected in payload", pattern=pattern.pattern)
                return False
        return True

    async def Process(self, request_iterator, context):
        try:
            async for request in request_iterator:
                req_type = request.WhichOneof("request")

                if req_type == "request_headers":
                    http_headers = request.request_headers
                    header_map = {}
                    for h in http_headers.headers:
                        k = _to_str(h.key).lower()
                        v = _to_str(h.value)
                        if not v and h.raw_value:
                            v = _to_str(h.raw_value)
                        header_map[k] = v

                    path = header_map.get(":path", "/")
                    method = header_map.get(":method", "POST")
                    authority = header_map.get(":authority", "")
                    request_id = header_map.get("x-request-id", f"req-ext-proc-{int(time.time() * 1000)}")

                    # Extract Agent metadata
                    agent_ctx = self._extract_agent_context(header_map, path, authority)

                    logger.info(
                        "Received ext_proc REQUEST_HEADERS on ALB Ingress",
                        path=path,
                        method=method,
                        authority=authority,
                        agent_id=agent_ctx["agent_id"],
                        principal=agent_ctx["principal"],
                        request_id=request_id,
                    )

                    # Build Apigee Policy Evaluation Payload
                    api_payload = {
                        "agent_context": agent_ctx,
                        "request": {
                            "id": request_id,
                            "method": method,
                            "path": path,
                            "host": authority,
                            "headers": header_map,
                        }
                    }

                    target_url = f"{settings.TARGET_API_URL}?source=cloud_run_ext_proc"
                    api_headers = {
                        "Content-Type": "application/json",
                        "User-Agent": "AgentGateway-CloudRun-ExtProc/1.0",
                        "X-AgentGateway-Request-ID": request_id,
                    }
                    if settings.TARGET_API_KEY:
                        api_headers["Authorization"] = f"Bearer {settings.TARGET_API_KEY}"

                    allowed = True
                    extra_headers = {}
                    denial_reason = "Access denied by Apigee Agent Policy Engine"

                    try:
                        client = await self._get_client()
                        resp = await client.post(target_url, json=api_payload, headers=api_headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            allowed = data.get("allowed", True)
                            denial_reason = data.get("reason", denial_reason)
                            extra_headers = data.get("injected_headers", {})
                        elif resp.status_code in (401, 403):
                            allowed = False
                            denial_reason = f"Apigee policy rejected request (HTTP {resp.status_code})"
                        else:
                            logger.warning(
                                "Apigee Policy API returned non-200 status",
                                status=resp.status_code,
                                text=resp.text[:200]
                            )
                            allowed = settings.FAIL_OPEN
                    except Exception as e:
                        logger.error("Failed to connect to Apigee Policy Engine", error=str(e))
                        allowed = settings.FAIL_OPEN

                    if allowed:
                        logger.info(
                            "Apigee Policy check ALLOWED. Mutating headers for Backend Agent",
                            agent_id=agent_ctx["agent_id"],
                            principal=agent_ctx["principal"]
                        )
                        set_headers = [
                            base_pb2.HeaderValueOption(
                                header=base_pb2.HeaderValue(
                                    key=_to_bytes(settings.HEADER_AUTH_STATUS),
                                    value=b"ALLOWED",
                                    raw_value=b"ALLOWED"
                                )
                            ),
                            base_pb2.HeaderValueOption(
                                header=base_pb2.HeaderValue(
                                    key=_to_bytes(settings.HEADER_PRINCIPAL),
                                    value=_to_bytes(agent_ctx["principal"]),
                                    raw_value=_to_bytes(agent_ctx["principal"])
                                )
                            ),
                            base_pb2.HeaderValueOption(
                                header=base_pb2.HeaderValue(
                                    key=_to_bytes(settings.HEADER_TENANT_ID),
                                    value=_to_bytes(agent_ctx["tenant_id"]),
                                    raw_value=_to_bytes(agent_ctx["tenant_id"])
                                )
                            ),
                            base_pb2.HeaderValueOption(
                                header=base_pb2.HeaderValue(
                                    key=b"x-agent-id",
                                    value=_to_bytes(agent_ctx["agent_id"]),
                                    raw_value=_to_bytes(agent_ctx["agent_id"])
                                )
                            ),
                        ]

                        # Add extra headers from policy engine
                        for k, v in extra_headers.items():
                            set_headers.append(
                                base_pb2.HeaderValueOption(
                                    header=base_pb2.HeaderValue(
                                        key=_to_bytes(k.lower()),
                                        value=_to_bytes(v),
                                        raw_value=_to_bytes(v)
                                    )
                                )
                            )

                        mutation = ext_proc_pb2.HeaderMutation(set_headers=set_headers)
                        yield ext_proc_pb2.ProcessingResponse(
                            request_headers=ext_proc_pb2.HeadersResponse(response=mutation)
                        )
                    else:
                        logger.warning("ext_proc policy check DENIED", reason=denial_reason)
                        yield ext_proc_pb2.ProcessingResponse(
                            immediate_response=ext_proc_pb2.ImmediateResponse(
                                status=http_status_pb2.HttpStatus(code=http_status_pb2.StatusCode.Forbidden),
                                body=f"Policy violation: {denial_reason}",
                                details=denial_reason
                            )
                        )

                elif req_type == "request_body":
                    # Model Armor payload inspection on prompt body
                    if settings.ENABLE_PROMPT_INSPECTION:
                        http_body = request.request_body
                        body_text = _to_str(http_body.body)

                        if not self._inspect_prompt_safety(body_text):
                            logger.warning("Prompt safety inspection failed on request body")
                            yield ext_proc_pb2.ProcessingResponse(
                                immediate_response=ext_proc_pb2.ImmediateResponse(
                                    status=http_status_pb2.HttpStatus(code=http_status_pb2.StatusCode.Forbidden),
                                    body="Blocked by Model Armor Guardrail: Malicious prompt pattern detected.",
                                    details="Prompt injection detected"
                                )
                            )
                        else:
                            yield ext_proc_pb2.ProcessingResponse(
                                request_body=ext_proc_pb2.BodyResponse()
                            )
                    else:
                        yield ext_proc_pb2.ProcessingResponse(
                            request_body=ext_proc_pb2.BodyResponse()
                        )

                else:
                    # Pass-through for other events (e.g. response_headers, response_body)
                    yield ext_proc_pb2.ProcessingResponse()

        except Exception as e:
            logger.exception("Error in ext_proc Process stream", error=str(e))
            yield ext_proc_pb2.ProcessingResponse()
