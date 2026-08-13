import asyncio
import json
import os
from aiohttp import web
import structlog

logger = structlog.get_logger(__name__)

# List of blocked principals / tokens for testing policy denial
DENIED_PRINCIPALS = {"blocked-user", "bad-actor", "unauthorized-client", "revoked-token"}
DENIED_AGENTS = {"unauthorized-agent", "deprecated-agent"}


async def evaluate_policy(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}

    agent_ctx = body.get("agent_context", {})
    req_data = body.get("request", {})

    agent_id = agent_ctx.get("agent_id", "default-agent")
    principal = agent_ctx.get("principal", "anonymous")
    tool_name = agent_ctx.get("tool_name", "query")

    logger.info(
        "Apigee Policy Engine evaluating request",
        agent_id=agent_id,
        principal=principal,
        tool_name=tool_name
    )

    # 1. Check if principal is blacklisted
    if principal in DENIED_PRINCIPALS:
        logger.warning("Apigee Policy Engine: Principal is blacklisted", principal=principal)
        return web.json_response({
            "allowed": False,
            "reason": f"Principal '{principal}' is not authorized by enterprise access policy.",
            "policy_id": "APIGEE_POLICY_AUTHZ_001"
        }, status=200)

    # 2. Check if target agent is disabled/unauthorized
    if agent_id in DENIED_AGENTS:
        logger.warning("Apigee Policy Engine: Target Agent not allowed", agent_id=agent_id)
        return web.json_response({
            "allowed": False,
            "reason": f"Agent '{agent_id}' is restricted or unavailable.",
            "policy_id": "APIGEE_POLICY_AGENT_002"
        }, status=200)

    # 3. Allow valid request and return policy enrichment headers
    return web.json_response({
        "allowed": True,
        "policy_id": "APIGEE_POLICY_AUTHZ_OK",
        "injected_headers": {
            "x-apigee-org": "enterprise-agent-org",
            "x-apigee-environment": "prod",
            "x-agent-tier": "premium",
            "x-governance-eval": "PASSED"
        }
    }, status=200)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "SERVING", "service": "mock-apigee-policy-engine"})


def main():
    app = web.Application()
    app.router.add_post("/v1/authz/evaluate", evaluate_policy)
    app.router.add_post("/authz/evaluate", evaluate_policy)
    app.router.add_get("/healthz", health)
    app.router.add_get("/", health)

    port = int(os.environ.get("MOCK_APIGEE_PORT", "8082"))
    print(f"Starting Mock Apigee Policy Server on http://0.0.0.0:{port}...")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
