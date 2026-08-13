#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
import grpc

# Add generated directory to sys.path
GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.ext_proc.v3.external_processor_pb2 as ext_proc_pb2
import envoy.service.ext_proc.v3.external_processor_pb2_grpc as ext_proc_pb2_grpc
import envoy.config.core.v3.base_pb2 as base_pb2


async def test_ext_proc(host="127.0.0.1", port=8080):
    channel = grpc.aio.insecure_channel(f"{host}:{port}")
    stub = ext_proc_pb2_grpc.ExternalProcessorStub(channel)

    print(f"Connecting to Envoy ext_proc gRPC server at {host}:{port}...")

    # 1. Test standard authorized request headers
    async def request_generator():
        headers = [
            base_pb2.HeaderValue(key=b":path", value=b"/chat", raw_value=b"/chat"),
            base_pb2.HeaderValue(key=b":method", value=b"POST", raw_value=b"POST"),
            base_pb2.HeaderValue(key=b":authority", value=b"adk-agent-app.example.com", raw_value=b"adk-agent-app.example.com"),
            base_pb2.HeaderValue(key=b"authorization", value=b"Bearer user-token-alice", raw_value=b"Bearer user-token-alice"),
            base_pb2.HeaderValue(key=b"x-agent-id", value=b"adk-agent-app", raw_value=b"adk-agent-app"),
            base_pb2.HeaderValue(key=b"x-agent-tenant-id", value=b"finance-dept", raw_value=b"finance-dept"),
        ]
        yield ext_proc_pb2.ProcessingRequest(
            request_headers=ext_proc_pb2.HttpHeaders(
                headers=headers,
                end_of_stream=False
            )
        )

    stream = stub.Process(request_generator())
    print("\n--- Testing Authorized Request Headers ---")
    async for response in stream:
        resp_type = response.WhichOneof("response")
        print(f"Response type: {resp_type}")
        if resp_type == "request_headers":
            mutation = response.request_headers.response
            print("Injected / Mutated Headers:")
            for h in mutation.set_headers:
                print(f"  + {h.header.key.decode('utf-8')}: {h.header.value.decode('utf-8')}")
        elif resp_type == "immediate_response":
            print(f"Immediate Response: Code={response.immediate_response.status.code}, Details={response.immediate_response.details}")

    # 2. Test blocked request headers (unauthorized principal)
    async def blocked_request_generator():
        headers = [
            base_pb2.HeaderValue(key=b":path", value=b"/chat", raw_value=b"/chat"),
            base_pb2.HeaderValue(key=b":method", value=b"POST", raw_value=b"POST"),
            base_pb2.HeaderValue(key=b":authority", value=b"adk-agent-app.example.com", raw_value=b"adk-agent-app.example.com"),
            base_pb2.HeaderValue(key=b"authorization", value=b"Bearer blocked-user", raw_value=b"Bearer blocked-user"),
            base_pb2.HeaderValue(key=b"x-user-id", value=b"blocked-user", raw_value=b"blocked-user"),
        ]
        yield ext_proc_pb2.ProcessingRequest(
            request_headers=ext_proc_pb2.HttpHeaders(
                headers=headers,
                end_of_stream=False
            )
        )

    stream_blocked = stub.Process(blocked_request_generator())
    print("\n--- Testing Blocked Request Headers (blocked-user) ---")
    async for response in stream_blocked:
        resp_type = response.WhichOneof("response")
        print(f"Response type: {resp_type}")
        if resp_type == "immediate_response":
            print(f"Denied as expected: Code={response.immediate_response.status.code}, Details={response.immediate_response.details}")

    await channel.close()


if __name__ == "__main__":
    asyncio.run(test_ext_proc())
