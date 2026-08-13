import os
import json
import time
from typing import Dict, Any, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="ADK Cloud Run Backend Agent",
    description="Agent Application running on Cloud Run fronted by Tier 1 Global ALB and Service Extension ext_proc",
    version="1.0.0"
)


class QueryRequest(BaseModel):
    prompt: Optional[str] = "Hello Agent"
    message: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


@app.get("/health")
@app.get("/healthz")
async def health():
    return {
        "status": "HEALTHY",
        "service": "adk-agent-app",
        "timestamp": time.time()
    }


@app.get("/")
async def root(request: Request):
    return {
        "service": "adk-agent-app",
        "description": "ADK Agent Service on Cloud Run",
        "headers_received": dict(request.headers)
    }


@app.post("/chat")
@app.post("/query")
async def handle_query(
    req: QueryRequest,
    request: Request,
    x_agentgateway_auth_status: Optional[str] = Header(None),
    x_agentgateway_principal: Optional[str] = Header(None),
    x_agentgateway_tenant_id: Optional[str] = Header(None),
    x_agent_id: Optional[str] = Header(None),
):
    query_text = req.prompt or req.message or "Default query"
    
    logger.info(
        "Backend Agent received request",
        auth_status=x_agentgateway_auth_status,
        principal=x_agentgateway_principal,
        tenant_id=x_agentgateway_tenant_id,
        agent_id=x_agent_id,
        query=query_text
    )

    # In production, if fronted by Service Extension, enforce governance header
    # If x_agentgateway_auth_status is present, ensure it is ALLOWED
    if x_agentgateway_auth_status and x_agentgateway_auth_status != "ALLOWED":
        raise HTTPException(
            status_code=403,
            detail=f"Unauthorized by Agent Gateway: auth status is '{x_agentgateway_auth_status}'"
        )

    # Simulate ADK Agent response execution
    response_content = (
        f"Hello {x_agentgateway_principal or 'User'}! I am agent '{x_agent_id or 'adk-agent-app'}'. "
        f"I received your prompt: '{query_text}' and processed it successfully under tenant '{x_agentgateway_tenant_id or 'default'}'."
    )

    return {
        "agent": x_agent_id or "adk-agent-app",
        "principal": x_agentgateway_principal or "anonymous",
        "tenant_id": x_agentgateway_tenant_id or "default-tenant",
        "auth_status": x_agentgateway_auth_status or "DIRECT_ACCESS",
        "response": response_content,
        "timestamp": time.time(),
        "status": "SUCCESS"
    }


@app.post("/streamQuery")
async def stream_query(
    req: QueryRequest,
    request: Request,
    x_agentgateway_auth_status: Optional[str] = Header(None),
    x_agentgateway_principal: Optional[str] = Header(None),
):
    query_text = req.prompt or req.message or "Default query"

    async def event_generator():
        chunks = [
            f"Event 1: Processing query '{query_text}' for principal {x_agentgateway_principal}...\n",
            "Event 2: Model reasoning complete.\n",
            "Event 3: Response finalized.\n"
        ]
        for chunk in chunks:
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("agent_backend.main:app", host="0.0.0.0", port=port)
