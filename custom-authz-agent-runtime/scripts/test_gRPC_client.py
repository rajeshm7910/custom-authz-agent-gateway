#!/usr/bin/env python3
"""
Integration script to test local Agent Gateway Envoy ext_authz gRPC server.
"""
import sys
import asyncio
from pathlib import Path
import grpc

GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc

async def main():
    channel = grpc.aio.insecure_channel("localhost:50051")
    stub = external_auth_pb2_grpc.AuthorizationStub(channel)

    req = external_auth_pb2.CheckRequest()
    req.attributes.request.http.method = "POST"
    req.attributes.request.http.path = "/v1/agents/agent-sales-bot/tools/bigquery_query/execute"
    req.attributes.request.http.host = "agentgateway.company.com"
    req.attributes.request.http.id = "agent-req-99001"
    req.attributes.request.http.headers["authorization"] = "Bearer jwt-token-user-alice"
    req.attributes.request.http.headers["x-agent-id"] = "agent-sales-bot"
    req.attributes.request.http.headers["x-agent-tool-name"] = "bigquery_query"
    req.attributes.context_extensions["tenant_id"] = "tenant-corp-alpha"
    req.attributes.context_extensions["dev.agentgateway.jwt"] = "alice@company.com"
    req.attributes.source.address = "10.0.1.20"

    print("Sending Agent Gateway CheckRequest to gRPC server at localhost:50051...")
    try:
        response = await stub.Check(req, timeout=5.0)
        print(f"Received CheckResponse with status code: {response.status.code}")
        if response.status.code == 0:
            print("Status: OK (AGENT AUTHORIZED)")
            for h in response.ok_response.headers:
                print(f"  Injected Header: {h.header.key} = {h.header.value}")
        else:
            print(f"Status: DENIED ({response.status.message})")
            if response.HasField("denied_response"):
                print(f"  HTTP Status: {response.denied_response.status.code}")
                print(f"  Body: {response.denied_response.body}")
    except grpc.RpcError as e:
        print(f"gRPC Error: {e.code()} - {e.details()}")
    finally:
        await channel.close()

if __name__ == "__main__":
    asyncio.run(main())
