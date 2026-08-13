#!/usr/bin/env python3
"""Direct gRPC test against Cloud Run Custom Authz extension."""
import asyncio
import sys
from pathlib import Path
import grpc

GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc

async def test_direct_grpc_check(host="custom-authz-agent-gateway-ey4s27drla-uc.a.run.app", port=443):
    print(f"Connecting to gRPC target: {host}:{port} ...")
    creds = grpc.ssl_channel_credentials()
    async with grpc.aio.secure_channel(f"{host}:{port}", creds) as channel:
        stub = external_auth_pb2_grpc.AuthorizationStub(channel)
        
        req = external_auth_pb2.CheckRequest()
        http_req = req.attributes.request.http
        http_req.method = "POST"
        http_req.path = "/streamQuery"
        http_req.host = "agw-ingress.agentgateway"
        http_req.headers["x-request-id"] = "req-direct-grpc-debug-99"
        http_req.headers["authorization"] = "Bearer test-direct-user-token"
        http_req.headers["x-agent-id"] = "gw-ingress-test"
        http_req.headers["x-agent-tool-name"] = "get_weather"

        print("Sending CheckRequest...")
        resp = await stub.Check(req, timeout=10.0)
        print("CheckResponse received:")
        print(f"  Status Code: {resp.status.code} (0 = OK)")
        if resp.HasField("ok_response"):
            print("  OK Headers injected:")
            for h in resp.ok_response.headers:
                print(f"    {h.header.key}: {h.header.value}")
        elif resp.HasField("denied_response"):
            print(f"  Denied: {resp.denied_response.status.code} body={resp.denied_response.body}")

if __name__ == "__main__":
    asyncio.run(test_direct_grpc_check())
