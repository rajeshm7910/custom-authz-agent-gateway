#!/usr/bin/env python3
"""
Mock External Policy & Authorization Engine API server for Agent Gateway testing.
Listens on http://localhost:8000/v1/agentgateway/authorize
"""
from aiohttp import web

async def handle_authorize(request: web.Request) -> web.Response:
    data = await request.json()
    agent_ctx = data.get("agent_context", {})
    req_info = data.get("request", {})
    
    agent_id = agent_ctx.get("agent_id", "unknown")
    tool_name = agent_ctx.get("tool_name", "")
    principal = agent_ctx.get("principal", "anonymous")
    tenant_id = agent_ctx.get("tenant_id", "default-tenant")

    print(f"[PolicyEngine] Received Authz request for Agent: '{agent_id}', Tool: '{tool_name}', Principal: '{principal}'")

    # Simulate authorization policy logic
    if "restricted" in tool_name or "forbidden" in agent_id:
        return web.json_response({
            "allowed": False,
            "reason": f"Principal '{principal}' is not authorized to execute tool '{tool_name}' on agent '{agent_id}'"
        })

    return web.json_response({
        "allowed": True,
        "principal": principal or "user-alice@example.com",
        "tenant_id": tenant_id,
        "allowed_tools": [tool_name or "*", "search_kb", "read_db"],
        "scopes": ["agent:invoke", "tools:execute"]
    })

app = web.Application()
app.router.add_post("/v1/agentgateway/authorize", handle_authorize)

if __name__ == "__main__":
    print("Starting Mock Agent Gateway External Policy API on http://localhost:8000/v1/agentgateway/authorize")
    web.run_app(app, host="0.0.0.0", port=8000)
