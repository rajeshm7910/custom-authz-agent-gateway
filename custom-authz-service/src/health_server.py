import json
import asyncio
from aiohttp import web
import structlog
import google.auth
from google.auth.transport.requests import Request
import httpx
from src.config import settings

logger = structlog.get_logger(__name__)

# Construct Reasoning Engine URL
REASONING_ENGINE_URL = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/us-central1/reasoningEngines/{settings.REASONING_ENGINE_ID}:streamQuery"


async def handle_root(request: web.Request) -> web.Response:
    """Root endpoint for status."""
    return web.json_response({
        "status": "healthy",
        "service": "custom-authz-agent-gateway",
        "ingress_gateway": "active",
        "protocols": ["HTTP/REST", "gRPC (ext_authz)", "gRPC (ext_proc)"],
        "endpoints": {
            "health": "/healthz",
            "ready": "/readyz",
            "stream_query": "/streamQuery",
            "agent_query": "/v1/agents/{agent_id}/query"
        }
    })


async def handle_healthz(request: web.Request) -> web.Response:
    """Readiness and Liveness probe handler."""
    return web.json_response({"status": "healthy", "service": "gcp-custom-authz-extension"})


async def handle_readyz(request: web.Request) -> web.Response:
    return web.json_response({"status": "READY", "service": "gcp-custom-authz-extension"})


async def handle_stream_query(request: web.Request) -> web.StreamResponse:
    """
    Direct /streamQuery endpoint:
    1. Authenticates & authorizes the request via External Policy API (Apigee).
    2. Dispatches to Vertex AI Reasoning Engine.
    3. Streams chunked response back to client.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    auth_header = request.headers.get("Authorization", "")
    request_id = request.headers.get("X-Request-ID", "req-gw-stream-001")

    logger.info("Received HTTP /streamQuery request", request_id=request_id, body=body)

    # 1. Authorize via External Policy API (Apigee)
    api_payload = {
        "agent_context": {
            "agent_id": "gw-ingress-test",
            "tool_name": "get_weather",
            "tenant_id": "default-tenant",
            "principal": "user-123"
        },
        "request": {
            "id": request_id,
            "method": "POST",
            "path": "/streamQuery",
            "host": request.host,
            "client_ip": request.remote or "127.0.0.1"
        }
    }

    target_url = f"{settings.TARGET_API_URL}?source=cloud_run_authz_gateway"
    api_headers = {
        "Content-Type": "application/json",
        "User-Agent": "AgentGateway-CustomAuthz-CloudRun/1.0",
        "X-AgentGateway-Request-ID": request_id,
        "X-Source": "CloudRun-ExtAuthz"
    }
    if settings.TARGET_API_KEY:
        api_headers["Authorization"] = f"Bearer {settings.TARGET_API_KEY}"

    allowed = True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(target_url, json=api_payload, headers=api_headers)
            if resp.status_code == 200:
                data = resp.json()
                allowed = data.get("allowed", True)
            else:
                logger.warning("Apigee Policy API returned non-200", status=resp.status_code)
                allowed = settings.FAIL_OPEN
    except Exception as e:
        logger.error("Failed to connect to Apigee Policy API", error=str(e))
        allowed = settings.FAIL_OPEN

    if not allowed:
        return web.json_response({
            "error": "Forbidden",
            "message": "Custom Auth Policy denied access to Agent Reasoning Engine"
        }, status=403)

    # 2. Invoke Vertex AI Reasoning Engine streamQuery
    try:
        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        vertex_headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }

        # Forward incoming payload
        vertex_payload = body if "class_method" in body else {
            "class_method": "async_stream_query",
            "input": {
                "user_id": "user-123",
                "message": body.get("input", {}).get("message") or body.get("prompt", "Weather in Fremont today?")
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            vertex_resp = await client.post(REASONING_ENGINE_URL, headers=vertex_headers, json=vertex_payload)
            return web.Response(
                body=vertex_resp.content,
                status=vertex_resp.status_code,
                content_type=vertex_resp.headers.get("Content-Type", "application/json")
            )
    except Exception as e:
        logger.error("Vertex AI Reasoning Engine error", error=str(e))
        return web.json_response({"error": "Internal Gateway Error", "details": str(e)}, status=500)


def create_http_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_get("/readyz", handle_readyz)
    app.router.add_post("/streamQuery", handle_stream_query)
    app.router.add_post("/v1/agents/{agent_id}/query", handle_stream_query)
    return app


async def start_http_server(host: str = "0.0.0.0", port: int = 8081) -> web.AppRunner:
    app = create_http_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Auxiliary HTTP Gateway and health server started", host=host, port=port)
    return runner
