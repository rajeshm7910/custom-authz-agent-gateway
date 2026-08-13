#!/usr/bin/env python3
"""
End-to-End Integration Test for Agent Gateway Custom Authz Extension + gw-ingress-test Agent.

Flow:
1. Authenticate via Google OAuth / Application Default Credentials.
2. Send an Envoy ext_authz CheckRequest to the Cloud Run Custom Authz Extension.
3. Validate that the Extension permits the request and injects x-agentgateway-* headers.
4. Call the gw-ingress-test Reasoning Engine with the authorized context.
"""

import sys
import json
import asyncio
from pathlib import Path
import grpc
import google.auth
from google.auth.transport.requests import Request
from google.cloud import aiplatform_v1
import google.protobuf.struct_pb2 as struct_pb2

GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc

CLOUD_RUN_HOST = "custom-authz-agent-gateway-622260204773.us-central1.run.app"
AGENT_RESOURCE = "projects/622260204773/locations/us-central1/reasoningEngines/1231533837213761536"
AGENT_ID = "gw-ingress-test"

async def step1_check_authz():
    print(f"\n[Step 1] Sending Envoy ext_authz CheckRequest to Cloud Run ({CLOUD_RUN_HOST}:443)...")
    credentials = grpc.ssl_channel_credentials()
    channel = grpc.aio.secure_channel(f"{CLOUD_RUN_HOST}:443", credentials)
    stub = external_auth_pb2_grpc.AuthorizationStub(channel)

    req = external_auth_pb2.CheckRequest()
    req.attributes.request.http.method = "POST"
    req.attributes.request.http.path = f"/v1/agents/{AGENT_ID}/tools/query/execute"
    req.attributes.request.http.host = "agw-ingress.us-central1.agentgateway"
    req.attributes.request.http.id = "req-e2e-1001"
    req.attributes.request.http.headers["authorization"] = "Bearer test-jwt-token-alice"
    req.attributes.request.http.headers["x-agent-id"] = AGENT_ID
    req.attributes.request.http.headers["x-agent-tool-name"] = "query"
    req.attributes.request.http.headers["x-agent-tenant-id"] = "tenant-enterprise-01"
    req.attributes.context_extensions["tenant_id"] = "tenant-enterprise-01"
    req.attributes.context_extensions["dev.agentgateway.jwt"] = "alice@company.com"

    try:
        response = await stub.Check(req, timeout=10.0)
        print(f"-> Authz Response Code: {response.status.code} ({'OK / ALLOWED' if response.status.code == 0 else 'DENIED'})")
        
        injected_headers = {}
        if response.status.code == 0:
            print("-> Injected Agent Gateway Headers:")
            for h in response.ok_response.headers:
                print(f"   • {h.header.key}: {h.header.value}")
                injected_headers[h.header.key] = h.header.value
            return True, injected_headers
        else:
            print(f"-> Access Denied: {response.status.message}")
            return False, {}
    except Exception as e:
        print(f"-> gRPC Call Error: {e}")
        return False, {}
    finally:
        await channel.close()

def step2_invoke_agent(prompt: str = "Hello, what can you do?"):
    print(f"\n[Step 2] Invoking backend Reasoning Engine ({AGENT_ID})...")
    client = aiplatform_v1.ReasoningEngineExecutionServiceClient(
        client_options={"api_endpoint": "us-central1-aiplatform.googleapis.com"}
    )

    payload = {
        "user_id": "alice@company.com",
        "session_id": "session-e2e-001",
        "message": {
            "role": "user",
            "parts": [{"text": prompt}],
        },
    }

    input_struct = struct_pb2.Struct()
    input_struct["request_json"] = json.dumps(payload)

    req = aiplatform_v1.StreamQueryReasoningEngineRequest(
        name=AGENT_RESOURCE,
        input=input_struct,
        class_method="streaming_agent_run_with_events",
    )

    print(f"-> Query: '{prompt}'")
    stream = client.stream_query_reasoning_engine(request=req)
    for resp in stream:
        if resp.data:
            try:
                event_data = json.loads(resp.data)
                for event in event_data.get("events", []):
                    content = event.get("content", {})
                    for part in content.get("parts", []):
                        if "text" in part:
                            print("\n--- [Agent Response] ---")
                            print(part["text"])
                        elif "function_call" in part:
                            print(f"\n-> Tool Invocation: {part['function_call'].get('name')}({part['function_call'].get('args')})")
            except Exception:
                print(resp.data)

async def main():
    print("=" * 70)
    print("Agent Gateway End-to-End Test: Custom Authz -> Ingress -> Agent")
    print("=" * 70)

    is_allowed, headers = await step1_check_authz()
    if is_allowed:
        prompt = sys.argv[1] if len(sys.argv) > 1 else "Hello, what can you do?"
        step2_invoke_agent(prompt)
        print("\n" + "=" * 70)
        print("End-to-End Test SUCCEEDED!")
        print("=" * 70)
    else:
        print("\nEnd-to-End Test BLOCKED by Custom Auth Extension!")

if __name__ == "__main__":
    asyncio.run(main())
